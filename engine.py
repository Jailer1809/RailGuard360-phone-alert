"""Detection + alert-gating logic (no UI), shared by app.py and test_pipeline.py."""
import json, time, datetime, collections, os, joblib, numpy as np, pandas as pd
try:
    from features import CameraTracker, Window, FEATURES
except Exception:
    CameraTracker, Window, FEATURES = None, None, []
from geo import Stations, Route
import alerts
class Engine:
    def __init__(self, cfg_path="config.json", model_path="models/model.joblib", load_model=True):
        base = os.path.dirname(os.path.abspath(__file__))
        cfg_path = cfg_path if os.path.isabs(cfg_path) else os.path.join(base, cfg_path)
        model_path = model_path if os.path.isabs(model_path) else os.path.join(base, model_path)
        self.cfg = json.load(open(cfg_path, encoding="utf-8"))
        if load_model:
            m = joblib.load(model_path)
            self.clf, self.classes = m["model"], list(m["model"].classes_)
        else:
            self.clf, self.classes = None, []
        self.tracker = CameraTracker() if CameraTracker is not None else None
        self.win = Window(1.0) if Window is not None else None
        self.stations, self.route = Stations(os.path.join(base, "data/stations.csv")), Route(os.path.join(base, "data/route.csv"))
        d = self.cfg["detect"]; self.votes = collections.deque(maxlen=d["of_last"]); self.last_alert = -1e9
        self.speed_override = None; self.t0 = time.time()
    def pos(self, now):
        r = self.route.at(now - self.t0)
        if self.speed_override is not None: r = dict(r, speed_kmph=self.speed_override)
        return r
    def process(self, frame, now):
        if self.clf is None: raise RuntimeError("The ML model was not loaded")
        blob, energy = self.tracker.observe(frame); self.win.add(now, blob, energy)
        f = self.win.features()
        if f is None: return blob, "normal", 0.0, None
        p = self.clf.predict_proba(pd.DataFrame([f], columns=FEATURES))[0]; i = int(np.argmax(p)); return blob, self.classes[i], float(p[i]), f
    def confirm(self, label, prob, now):
        """Majority vote over the last frames; returns the event label or None."""
        d = self.cfg["detect"]
        self.votes.append(label if prob >= d["min_probability"] else "normal")
        if now - self.last_alert <= d["cooldown_seconds"]: return None
        if sum(v == "push_fall" for v in self.votes) >= d["votes_needed"]: return "push_fall"
        if sum(v in ("fall", "push_fall") for v in self.votes) >= d["votes_needed"]: return "fall"
        return None
    def handle_external(self, event, now, speed, loc, stage="ALERT", person_count=1):
        """Handle an event detected by the browser/another sensor using its GPS location."""
        speed = float(speed); lim = self.cfg["min_speed_kmph"]
        if stage == "ALERT" and speed <= lim:
            return {"sent": False, "reason": f"{event} detected but train speed {speed:.0f} km/h <= {lim} km/h: no alert sent"}
        if stage == "ALERT" and now - self.last_alert <= self.cfg["detect"]["cooldown_seconds"]:
            return {"sent": False, "reason": "alert suppressed by cooldown"}
        if stage == "ALERT": self.last_alert = now
        stn, km = self.stations.nearest(float(loc["lat"]), float(loc["lon"]))
        ctx = dict(time=datetime.datetime.now(), lat=float(loc["lat"]), lon=float(loc["lon"]),
                   accuracy=float(loc["accuracy"]) if loc.get("accuracy") is not None else None,
                   speed=speed, km=km, person_count=person_count,
                   prev=loc.get("segment", "").split(" -> ")[0], next=loc.get("segment", "").split(" -> ")[-1])
        res = alerts.send_all(alerts.build(event, ctx, self.cfg, stn, stage))
        return {"sent": True, "reason": f"{stage}: alerts to {', '.join(x[0] for x in res)}", "results": res, "ctx": ctx}

    def handle(self, event, now):
        """Speed gate: alerts go out ONLY when the train is faster than min_speed_kmph."""
        r = self.pos(now); speed = float(r["speed_kmph"]); lim = self.cfg["min_speed_kmph"]
        self.last_alert = now; self.votes.clear()
        if speed <= lim:
            return {"sent": False, "reason": f"{event} detected but train speed {speed:.0f} km/h <= {lim} km/h: no alert sent"}
        stn, km = self.stations.nearest(r["lat"], r["lon"])
        ctx = dict(time=datetime.datetime.now(), lat=r["lat"], lon=r["lon"], speed=speed, km=km, prev=r["prev_station"], next=r["next_station"])
        res = alerts.send_all(alerts.build(event, ctx, self.cfg, stn))
        return {"sent": True, "reason": f"{event} at {speed:.0f} km/h: alerts to {', '.join(x[0] for x in res)}", "results": res, "ctx": ctx}
