import math, pandas as pd
def haversine(a, b, c, d):
    R = 6371.0; r = math.radians
    x = math.sin(r(c-a)/2)**2 + math.cos(r(a))*math.cos(r(c))*math.sin(r(d-b)/2)**2
    return 2*R*math.asin(math.sqrt(x))
class Stations:
    def __init__(self, path="data/stations.csv"): self.df = pd.read_csv(path).fillna("")
    def nearest(self, lat, lon):
        d = self.df.apply(lambda r: haversine(lat, lon, r.lat, r.lon), axis=1); i = d.idxmin()
        r = self.df.loc[i]; return r.to_dict(), float(d[i])
class Route:
    """Simulated GPS: loops over data/route.csv, one row per second."""
    def __init__(self, path="data/route.csv"): self.df = pd.read_csv(path)
    def at(self, elapsed):
        return self.df.iloc[int(elapsed) % len(self.df)].to_dict()
