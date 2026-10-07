"""Headless self-test: synthetic 'camera' video -> tracker -> classifier -> speed gate -> alert messages. No webcam needed."""
import sys, os, numpy as np, cv2
from engine import Engine
FPS, W, H = 15, 640, 480
def person(cx, cy, ang, w=60, h=200):
    r = cv2.boxPoints(((cx, cy), (w, h), ang)).astype(np.int32)
    f = np.full((H, W, 3), 90, np.uint8); cv2.fillPoly(f, [r], (230, 200, 160)); return f
def scenario(kind):
    """yield frames: 45 empty frames, person walks in, still, then the event."""
    rng = np.random.default_rng(3)
    for i in range(45): yield np.clip(np.full((H, W, 3), 90) + rng.normal(0, 2, (H, W, 3)), 0, 255).astype(np.uint8)
    cx, cy = 200, 260
    for i in range(30): yield person(cx + i*3, cy, 0)
    cx += 90
    for i in range(10): yield person(cx, cy, 0)
    n = 9
    for i in range(1, n + 1):
        k = i / n
        if kind == "walk": yield person(cx + i*3, cy, 0)
        elif kind == "crowd": yield person(cx + 30*np.sin(i*1.6), cy, 4*np.sin(i))
        elif kind == "fall": yield person(cx + 25*k, cy + 70*k, 90*k)
        elif kind == "push": yield person(cx + 150*k, cy + 70*k, 90*k)
    for i in range(20): yield person(cx + (0 if kind in ("walk","crowd") else 25 if kind == "fall" else 150), cy + (0 if kind in ("walk","crowd") else 70), 0 if kind in ("walk","crowd") else 90)
def run(kind, speed):
    eng = Engine(); eng.speed_override = speed; eng.t0 = 0; os.makedirs("logs", exist_ok=True)
    got = None; seen = set()
    for i, fr in enumerate(scenario(kind)):
        now = i / FPS; _, lab, p, f = eng.process(fr, now); seen.add(lab)
        ev = eng.confirm(lab, p, now)
        if ev and not got: got = (ev, eng.handle(ev, now))
    return seen, got
if __name__ == "__main__":
    ok = True
    for kind, speed, expect in [("walk", 80, None), ("crowd", 80, None), ("fall", 80, "fall"), ("push", 80, "push_fall"), ("push", 10, "push_fall")]:
        seen, got = run(kind, speed); ev = got[0] if got else None
        sent = got[1]["sent"] if got else None
        good = (ev == expect) or (expect == "fall" and ev == "push_fall")
        want_sent = None if expect is None else speed > 20
        good = good and sent == want_sent
        ok &= good; print(f"{'PASS' if good else 'FAIL'}  {kind:6s} speed={speed:3d} -> labels seen={sorted(seen)} event={ev} alert_sent={sent}")
        if got and got[1]["sent"] and kind == "push": print("   guard msg:", got[1]["results"][0][3][:230], "...")
        if got and not got[1]["sent"]: print("   ", got[1]["reason"])
    sys.exit(0 if ok else 1)
