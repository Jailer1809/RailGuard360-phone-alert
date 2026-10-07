"""RailGuard 360 - live prototype. Laptop camera = fall/push sensor, simulated train GPS = speed + location.
Keys: q quit | + / - set train speed (10 km/h steps) | 0 back to route speed | f / p inject test fall / push"""
import argparse, csv, os, time, cv2
BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
from engine import Engine
from features import FEATURES
ap = argparse.ArgumentParser()
ap.add_argument("--camera", type=int, default=0); ap.add_argument("--video", help="video file instead of camera")
ap.add_argument("--record", choices=["normal", "crowd", "fall", "push_fall"], help="append labelled feature windows to data/real_samples.csv")
ap.add_argument("--headless", action="store_true", help="no window (for tests)"); a = ap.parse_args()
eng = Engine(); cap = cv2.VideoCapture(a.video if a.video else a.camera)
if not cap.isOpened(): raise SystemExit("Cannot open camera/video. Try --camera 1 or --video file.mp4")
status, status_t, speed_set = "Monitoring...", 0, None
def show_status(txt): 
    global status, status_t; status, status_t = txt, time.time()
def fire(ev, now):
    out = eng.handle(ev, now); show_status(("ALERTS SENT: " if out["sent"] else "SUPPRESSED: ") + out["reason"]); print(("\n[ALERT] " if out["sent"] else "\n[NO ALERT] ") + out["reason"])
    for role, to, st, body in out.get("results", []): print(f"  -> {role:9s} {to:15s} {st}\n     {body}\n")
print(__doc__)
while True:
    ok, frame = cap.read()
    if not ok: break
    now = time.time(); blob, lab, prob, f = eng.process(frame, now)
    if a.record and f is not None:
        new = not os.path.exists("data/real_samples.csv")
        with open("data/real_samples.csv", "a", newline="") as fh:
            w = csv.writer(fh); new and w.writerow(FEATURES + ["label"]); w.writerow(list(f) + [a.record])
    ev = None if a.record else eng.confirm(lab, prob, now)
    if ev: fire(ev, now)
    r = eng.pos(now); sp = r["speed_kmph"]; gate = sp > eng.cfg["min_speed_kmph"]
    if not a.headless:
        if blob:
            x, y, w_, h_ = blob["box"]; s = frame.shape[1] / 320
            cv2.rectangle(frame, (int(x*s), int(y*s)), (int((x+w_)*s), int((y+h_)*s)), (0, 0, 255) if lab in ("fall", "push_fall") else (0, 200, 0), 2)
        hud = [f"Train speed: {sp:.0f} km/h  ({'ALERTS ARMED' if gate else 'alerts OFF: speed <= %d' % eng.cfg['min_speed_kmph']})",
               f"GPS {r['lat']:.4f},{r['lon']:.4f}  {r['prev_station']} -> {r['next_station']}",
               f"Camera sees: {lab} ({prob*100:.0f}%)", status if time.time() - status_t < 8 else "Monitoring..."]
        for i, t in enumerate(hud):
            cv2.putText(frame, t, (10, 24 + 24*i), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 4); cv2.putText(frame, t, (10, 24 + 24*i), cv2.FONT_HERSHEY_SIMPLEX, .6, (255, 255, 255) if gate else (80, 180, 255), 1)
        cv2.imshow("RailGuard 360", frame); k = cv2.waitKey(1) & 0xFF
        if k == ord("q"): break
        if k in (ord("+"), ord("=")): speed_set = min(130, (eng.speed_override if eng.speed_override is not None else sp) + 10); eng.speed_override = speed_set
        if k == ord("-"): eng.speed_override = max(0, (eng.speed_override if eng.speed_override is not None else sp) - 10)
        if k == ord("0"): eng.speed_override = None
        if k == ord("f"): fire("fall", now)
        if k == ord("p"): fire("push_fall", now)
cap.release(); cv2.destroyAllWindows()
