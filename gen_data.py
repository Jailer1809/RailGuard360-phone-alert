"""Generates the demo datasets: data/pushfall_dataset.csv (synthetic training data),
data/stations.csv and data/route.csv (simulated train GPS/speed track)."""
import math, numpy as np, pandas as pd
from geo import haversine
rng = np.random.default_rng(42)
FEATURES = ["ar_end","ar_change","angle_end","height_ratio","max_vy","max_vx","lat_accel","motion_energy"]
N = 2000
def cls(n, spec, label):
    d = {k: rng.normal(m, s, n) for k, (m, s) in spec.items()}
    df = pd.DataFrame(d)[FEATURES]; df["label"] = label; return df
# (mean, std) per feature. Ranges follow the camera tracker's output (see features.py)
spec = {
 "normal":    dict(ar_end=(.45,.15),ar_change=(0,.08),angle_end=(8,6),height_ratio=(1,.06),max_vy=(.15,.1),max_vx=(.25,.15),lat_accel=(.8,.5),motion_energy=(.02,.015)),
 "crowd":     dict(ar_end=(.6,.2),ar_change=(.05,.12),angle_end=(14,8),height_ratio=(.97,.08),max_vy=(.3,.15),max_vx=(.9,.3),lat_accel=(4,1.5),motion_energy=(.10,.04)),
 "fall":      dict(ar_end=(1.5,.4),ar_change=(1.0,.35),angle_end=(68,14),height_ratio=(.45,.12),max_vy=(1.4,.4),max_vx=(.5,.25),lat_accel=(4,1.5),motion_energy=(.08,.03)),
 "push_fall": dict(ar_end=(1.5,.4),ar_change=(1.0,.35),angle_end=(72,12),height_ratio=(.42,.12),max_vy=(1.7,.45),max_vx=(2.2,.5),lat_accel=(10,2.5),motion_energy=(.18,.05)),
}
df = pd.concat([cls(N, s, k) for k, s in spec.items()]).sample(frac=1, random_state=1)
for c in ["ar_end","height_ratio","max_vy","max_vx","lat_accel","motion_energy"]: df[c] = df[c].clip(lower=0)
df["angle_end"] = df["angle_end"].clip(0, 90)
df.round(4).to_csv("data/pushfall_dataset.csv", index=False)
print("dataset:", df.label.value_counts().to_dict())

# Stations (approximate coordinates). Blank phone = use defaults from config.json
ST = [("Coimbatore Jn",11.0003,76.9663),("Tiruppur",11.1085,77.3411),("Erode Jn",11.3410,77.7172),("Salem Jn",11.6643,78.1460),
      ("Jolarpettai",12.5690,78.5740),("Katpadi Jn",12.9718,79.1365),("Arakkonam",13.0770,79.6700),("Chennai Central",13.0827,80.2757)]
pd.DataFrame([(n,a,o,"","") for n,a,o in ST], columns=["name","lat","lon","police_phone","ambulance_phone"]).to_csv("data/stations.csv", index=False)

# Route: 1 row = 1 real second of the demo = 60 s of simulated travel (time warp)
WARP, VMAX, K, rows, km = 60, 90.0, 4.0, [], 0.0
for i in range(len(ST) - 1):
    a, b = ST[i], ST[i+1]; D = haversine(a[1],a[2],b[1],b[2]); d = 0.0
    rows += [(a[1],a[2],0.0,a[0],b[0],km)] * 8              # stopped at station
    while d < D:
        v = max(12.0, min(VMAX, 12 + K*d, 12 + K*(D-d)))
        d += v/3600*WARP; f = min(d/D, 1)
        rows.append((a[1]+(b[1]-a[1])*f, a[2]+(b[2]-a[2])*f, round(v,1), a[0], b[0], round(km+d,1)))
    km += D
rows += [(ST[-1][1],ST[-1][2],0.0,ST[-1][0],ST[-1][0],round(km,1))]*8
pd.DataFrame(rows, columns=["lat","lon","speed_kmph","prev_station","next_station","km"]).round(5).to_csv("data/route.csv", index_label="t")
print("route rows:", len(rows), "total km:", round(km))
