"""Unified RailGuard 360 web server using the prototype Engine + browser detector."""
import json, os, time
import math
import re
import threading
from flask import Flask, jsonify, request, send_from_directory
import pandas as pd
import requests
from engine import Engine
from alerts import load_env
from geo import haversine

BASE = os.path.dirname(os.path.abspath(__file__))
load_env(os.path.join(BASE, ".env"))
app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="")
CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
ENGINE = Engine(load_model=False)
_last = {}
TRAIN_DATA_PATH = os.path.join(BASE, "isl_wise_train_detail_03082015_v1.csv")
TRAIN_ROWS = pd.read_csv(TRAIN_DATA_PATH, dtype=str, keep_default_na=False)
TRAIN_ROWS["Train No."] = TRAIN_ROWS["Train No."].str.strip().str.strip("'\"")
TRAIN_ROWS["train Name"] = TRAIN_ROWS["train Name"].str.strip()
TRAIN_ROWS["station Code"] = TRAIN_ROWS["station Code"].str.strip()
TRAIN_ROWS["Station Name"] = TRAIN_ROWS["Station Name"].str.strip()
TRAIN_ROWS["Arrival time"] = TRAIN_ROWS["Arrival time"].str.strip().str.strip("'\"")
TRAIN_ROWS["Departure time"] = TRAIN_ROWS["Departure time"].str.strip().str.strip("'\"")
TRAIN_GROUPS = {
    (number, name): rows.sort_values("islno", key=lambda col: pd.to_numeric(col, errors="coerce"))
    for (number, name), rows in TRAIN_ROWS.groupby(["Train No.", "train Name"], sort=False)
}
STATION_COORDS = pd.read_csv(os.path.join(BASE, "data/stations.csv")).fillna("")
GEOCODE_CACHE = {}
GEOCODE_LOCK = threading.Lock()
ROUTE_CACHE = {}
LAST_GEOCODE_AT = 0.0

def provider():
    if os.environ.get("FAST2SMS_API_KEY"): return "Fast2SMS"
    if os.environ.get("TWILIO_ACCOUNT_SID"): return "Twilio"
    return "Dry-run"

LIVE_ALERTS = []

def _train_summary(number, name, rows):
    first = rows.iloc[0]
    return {
        "number": number,
        "name": name,
        "coach": CFG["train"]["coach"] if number == CFG["train"]["number"] else "",
        "source": first["source Station Name"].strip(),
        "destination": first["Destination Station Name"].strip(),
        "stops": len(rows),
    }

def _train_for_number(number):
    for (train_number, name), rows in TRAIN_GROUPS.items():
        if train_number == number:
            return _train_summary(number, name, rows)
    return None

def _geocode_station(name):
    global LAST_GEOCODE_AT
    key = " ".join(name.casefold().split())
    if key in GEOCODE_CACHE:
        return GEOCODE_CACHE[key]

    known = STATION_COORDS[
        STATION_COORDS["name"].astype(str).str.casefold().str.strip().eq(key)
    ]
    if not known.empty:
        station = known.iloc[0]
        result = {"lat": float(station["lat"]), "lon": float(station["lon"]), "source": "local"}
        GEOCODE_CACHE[key] = result
        return result

    with GEOCODE_LOCK:
        if key in GEOCODE_CACHE:
            return GEOCODE_CACHE[key]
        wait = 1.1 - (time.time() - LAST_GEOCODE_AT)
        if wait > 0:
            time.sleep(wait)
        search_name = re.sub(r"\bNRTH\b", "NORTH", name, flags=re.IGNORECASE)
        search_name = re.sub(r"\bJN\b", "JUNCTION", search_name, flags=re.IGNORECASE)
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": f"{search_name} railway station, India", "format": "jsonv2", "limit": 5},
            headers={"User-Agent": "RailGuard360/1.0 (https://github.com/Jailer1809/RailGuard360-phone-alert)"},
            timeout=12,
        )
        LAST_GEOCODE_AT = time.time()
        response.raise_for_status()
        candidates = response.json()
        result = None
        for candidate in candidates:
            try:
                lat, lon = float(candidate["lat"]), float(candidate["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if 6 <= lat <= 38 and 68 <= lon <= 98:
                result = {"lat": lat, "lon": lon, "source": "OpenStreetMap"}
                break
        GEOCODE_CACHE[key] = result
        return result

def _route_for_train(number):
    if number in ROUTE_CACHE:
        return ROUTE_CACHE[number]
    summary = _train_for_number(number)
    if summary is None:
        return None
    rows = TRAIN_GROUPS[(number, summary["name"])]
    stops = []
    for _, row in rows.iterrows():
        station_name = row["Station Name"].strip()
        coordinates = _geocode_station(station_name)
        if coordinates is None:
            raise ValueError(f"No map location found for station {row['station Code'].strip()} ({station_name})")
        try:
            distance_km = float(row["Distance"])
        except (TypeError, ValueError):
            distance_km = 0.0
        stops.append({
            "code": row["station Code"].strip(),
            "name": station_name,
            "lat": coordinates["lat"],
            "lon": coordinates["lon"],
            "distance_km": distance_km,
            "arrival": row["Arrival time"].strip(),
            "departure": row["Departure time"].strip(),
        })
    route = {"train": summary, "stops": stops, "map_note": "Station-to-station corridor; not exact rail-track geometry."}
    ROUTE_CACHE[number] = route
    return route

def _route_location(route, lat, lon):
    stops = route["stops"]
    nearest_stop = min(stops, key=lambda stop: haversine(lat, lon, stop["lat"], stop["lon"]))
    nearest_segment = None
    nearest_segment_distance = float("inf")
    longitude_scale = math.cos(math.radians(lat))
    point_x, point_y = lon * longitude_scale, lat
    for first, second in zip(stops, stops[1:]):
        x1, y1 = first["lon"] * longitude_scale, first["lat"]
        x2, y2 = second["lon"] * longitude_scale, second["lat"]
        dx, dy = x2 - x1, y2 - y1
        denominator = dx * dx + dy * dy
        fraction = 0.0 if denominator == 0 else max(0.0, min(1.0, ((point_x - x1) * dx + (point_y - y1) * dy) / denominator))
        projected_lat = first["lat"] + fraction * (second["lat"] - first["lat"])
        projected_lon = first["lon"] + fraction * (second["lon"] - first["lon"])
        distance = haversine(lat, lon, projected_lat, projected_lon)
        if distance < nearest_segment_distance:
            nearest_segment_distance = distance
            route_km = first["distance_km"] + fraction * (second["distance_km"] - first["distance_km"])
            nearest_segment = {
                "segment": f"{first['name']} -> {second['name']}",
                "km": route_km,
                "route_distance_km": distance,
            }
    return {
        **(nearest_segment or {}),
        "nearest_station": {
            "name": nearest_stop["name"],
            "distance_km": haversine(lat, lon, nearest_stop["lat"], nearest_stop["lon"]),
        },
    }

@app.get("/")
def home(): return send_from_directory(app.static_folder, "index.html")

@app.get("/receiver")
def receiver(): return send_from_directory(app.static_folder, "receiver.html")

@app.get("/api/alerts/live")
def get_live_alerts():
    return jsonify(alerts=LIVE_ALERTS[:20])

@app.get("/api/config")
def config():
    c = CFG["contacts"]
    nums = [f"{k.capitalize()}: {c[k]['phone']}" for k in ("guard","control","police","ambulance")]
    return jsonify(speed_threshold_kmph=CFG["min_speed_kmph"], time_scale=CFG["web"]["time_scale"],
                   cruise_speed_kmph=CFG["web"]["cruise_speed_kmph"], cooldown_seconds=CFG["detect"]["cooldown_seconds"],
                   numbers=nums, sms_provider=provider(), contacts=c, train=CFG["train"])

@app.get("/api/trains")
def search_trains():
    query = request.args.get("q", "").strip().casefold()
    if len(query) > 80:
        return jsonify(ok=False, message="Search text must be 80 characters or less"), 400
    summaries = []
    for (number, name), rows in TRAIN_GROUPS.items():
        if query and query not in number.casefold() and query not in name.casefold():
            continue
        summaries.append(_train_summary(number, name, rows))
        if len(summaries) >= 30:
            break
    return jsonify(trains=summaries)

@app.get("/api/trains/<train_number>/route")
def train_route(train_number):
    if not train_number.isdigit() or len(train_number) > 6:
        return jsonify(ok=False, message="Train number must contain 1 to 6 digits"), 400
    try:
        route = _route_for_train(train_number)
    except requests.RequestException as error:
        return jsonify(ok=False, message=f"OpenStreetMap station lookup failed: {error}"), 503
    except ValueError as error:
        return jsonify(ok=False, message=str(error)), 424
    if route is None:
        return jsonify(ok=False, message="Train number is not present in the supplied timetable"), 404
    return jsonify(route)

@app.post("/api/alert")
def alert():
    d = request.get_json(force=True, silent=True) or {}
    if not isinstance(d, dict):
        return jsonify(ok=False, message="bad request: request body must be a JSON object"), 400
    try:
        stage = d.get("stage", "ALERT")
        if stage not in ("ALERT", "HALTED"): raise ValueError("bad stage")
        speed = float(d["speed"])
        loc = d["loc"]
        if not isinstance(loc, dict):
            raise ValueError("loc must be an object")
        person_count = d.get("persons", 1)
        if not isinstance(person_count, int) or isinstance(person_count, bool) or not 1 <= person_count <= 4:
            raise ValueError("persons must be an integer from 1 to 4")
        lat, lon = float(loc["lat"]), float(loc["lon"])
        if not math.isfinite(speed) or speed < 0:
            raise ValueError("speed must be a finite non-negative number")
        if not math.isfinite(lat) or not -90 <= lat <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if not math.isfinite(lon) or not -180 <= lon <= 180:
            raise ValueError("longitude must be between -180 and 180")
        loc = dict(loc, lat=lat, lon=lon)
        if loc.get("accuracy") is not None:
            accuracy = float(loc["accuracy"])
            if not math.isfinite(accuracy) or accuracy <= 0:
                raise ValueError("GPS accuracy must be a finite positive number")
            loc["accuracy"] = accuracy
        raw_ev = d.get("event", "PUSH")
        if isinstance(raw_ev, dict): raw = str(raw_ev.get("type", "PUSH")).upper()
        else: raw = str(raw_ev).upper()
        event = "push_fall" if ("PUSH" in raw or "CRIME" in raw) else "fall"
        train_number = str(d.get("train_number", CFG["train"]["number"])).strip()
        train_data = _train_for_number(train_number)
        if train_data is None:
            raise ValueError("train_number is not present in the supplied timetable")
        loc = dict(loc, train=train_data)
        cached_route = ROUTE_CACHE.get(train_number)
        if cached_route:
            loc.update(_route_location(cached_route, lat, lon))
        if stage == "ALERT" and speed <= CFG["min_speed_kmph"]:
            return jsonify(ok=False, message=f"blocked: speed {speed:.0f} <= {CFG['min_speed_kmph']} km/h")
        key = stage
        if time.time() - _last.get(key, 0) < 5:
            return jsonify(ok=False, message="rate limited (wait 5 s)")
        _last[key] = time.time()
        out = ENGINE.handle_external(event, time.time(), speed, loc, stage, person_count)
        
        # Push into live alerts stream for connected phones
        ts_str = time.strftime("%H:%M:%S")
        maps_link = f"https://maps.google.com/?q={loc['lat']:.6f},{loc['lon']:.6f}"
        for role, to, status, body in out.get("results", []):
            LIVE_ALERTS.insert(0, {
                "id": f"{time.time()}_{role}",
                "time": ts_str,
                "role": role,
                "to": to,
                "status": status,
                "event": raw,
                "speed": speed,
                "message": body,
                "map": maps_link,
                "lat": loc["lat"],
                "lon": loc["lon"],
                "accuracy": loc.get("accuracy"),
                "train": train_data
            })

        return jsonify(ok=out["sent"], message=out["reason"], results=out.get("results", []))
    except (KeyError, TypeError, ValueError) as e:
        return jsonify(ok=False, message=f"bad request: {e}"), 400

@app.get("/api/ml")
def ml_status():
    return jsonify(ok=True, model="models/model.joblib", engine="shared prototype Engine")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
