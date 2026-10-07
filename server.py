"""Unified RailGuard 360 web server using the prototype Engine + browser detector."""
import json, os, time
import math
from flask import Flask, jsonify, request, send_from_directory
from engine import Engine
from alerts import load_env

BASE = os.path.dirname(os.path.abspath(__file__))
load_env(os.path.join(BASE, ".env"))
app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="")
CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
ENGINE = Engine(load_model=False)
_last = {}

def provider():
    if os.environ.get("FAST2SMS_API_KEY"): return "Fast2SMS"
    if os.environ.get("TWILIO_ACCOUNT_SID"): return "Twilio"
    return "Dry-run"

LIVE_ALERTS = []

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
                   numbers=nums, sms_provider=provider(), contacts=c)

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
                "accuracy": loc.get("accuracy")
            })

        return jsonify(ok=out["sent"], message=out["reason"], results=out.get("results", []))
    except (KeyError, TypeError, ValueError) as e:
        return jsonify(ok=False, message=f"bad request: {e}"), 400

@app.get("/api/ml")
def ml_status():
    return jsonify(ok=True, model="models/model.joblib", engine="shared prototype Engine")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
