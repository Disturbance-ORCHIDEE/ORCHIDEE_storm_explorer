"""Storm tracks, a display aid (not a validation set).

  published  XWS catalogue tracks (Roberts et al. 2014): CSV, one row per 3-hourly time (date in column 2, lon 3, lat 4,
             value of the centre in column 8), kept from 3 days before to 2 days after the storm date.
  tracked    minimum of mean sea-level pressure in ERA5 netCDF files (6-hourly, 1 deg, around each storm; variable msl in Pa):
             local minima (5x5 neighbourhood, below P_MAX hPa); seed at noon of the storm date = deepest minimum within
             1500 km of the storm's validation cells (nearest within 2500 km otherwise); followed forwards and backwards,
             each step to the minimum nearest the extrapolated position, at most STEP_KM away.
"""
import datetime as dt, glob, os

import numpy as np
from netCDF4 import Dataset, num2date

STEP_KM, P_MAX = 900.0, 1008.0


def km(lo1, la1, lo2, la2):
    p1, p2 = np.radians(la1), np.radians(la2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lo2 - lo1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def _load_msl(files):
    T, P = [], []
    for f in files:
        with Dataset(f) as d:
            tv = d["valid_time"] if "valid_time" in d.variables else d["time"]
            T += [dt.datetime(t.year, t.month, t.day, t.hour) for t in num2date(tv[:], tv.units)]
            P.append(np.asarray(d["msl"][:], "f8") / 100)
            lat, lon = np.asarray(d["latitude"][:]), np.asarray(d["longitude"][:])
    o = np.argsort(T)
    return [T[i] for i in o], np.concatenate(P)[o], lon, lat


def tracked(files, d0, seed_lon, seed_lat):
    from scipy.ndimage import minimum_filter
    T, P, lon, lat = _load_msl(files)
    L2, A2 = np.meshgrid(lon, lat); mins = []
    for p in P:
        m = (p == minimum_filter(p, size=5, mode="nearest")) & (p < P_MAX)
        m[0, :] = m[-1, :] = m[:, 0] = m[:, -1] = False
        mins.append(list(zip(L2[m], A2[m], p[m])))
    t0 = min(range(len(T)), key=lambda i: abs((T[i] - dt.datetime(d0.year, d0.month, d0.day, 12)).total_seconds()))
    cand = mins[t0]
    if not cand:
        return []
    dist = [km(seed_lon, seed_lat, c[0], c[1]) for c in cand]
    near_ = [c for c, d_ in zip(cand, dist) if d_ <= 1500]
    if near_:
        start = min(near_, key=lambda c: c[2])
    elif min(dist) <= 2500:
        start = cand[int(np.argmin(dist))]
    else:
        return []
    pts = {t0: start}
    for direction in (1, -1):
        prev, prev2, i = start, None, t0 + direction
        while 0 <= i < len(T) and mins[i]:
            ex = prev if prev2 is None else (2 * prev[0] - prev2[0], 2 * prev[1] - prev2[1])
            dd = [km(ex[0], ex[1], c[0], c[1]) for c in mins[i]]
            j = int(np.argmin(dd))
            if km(prev[0], prev[1], mins[i][j][0], mins[i][j][1]) > STEP_KM:
                break
            pts[i] = mins[i][j]; prev2, prev = prev, mins[i][j]; i += direction
    return [[round(float(pts[i][0]), 2), round(float(pts[i][1]), 2), T[i].strftime("%Y-%m-%d %H"), round(float(pts[i][2]), 1)]
            for i in sorted(pts)]


def published(path, d0):
    pts = []
    for line in open(path):
        c = [x.strip().strip('"') for x in line.split(",")]
        try:
            t = dt.datetime.strptime(c[1], "%Y-%m-%d %H:%M:%S")
        except (ValueError, IndexError):
            continue
        if not (-3 <= (t.date() - d0).days <= 2):
            continue
        lo = float(c[2]); lo = lo - 360 if lo > 180 else lo
        pts.append([round(lo, 2), round(float(c[3]), 2), t.strftime("%Y-%m-%d %H"), round(float(c[7]), 1)])
    return pts


def build(tc, storms, val, clon, clat):
    """{storm id: {'era5': [...], 'xws': [...], 'xws2': [...]}}; sources whose files are missing are left out."""
    out = {}
    for s in storms:
        d0 = dt.date.fromisoformat(s["date"]); v = val[s["id"]]
        ks = next((v[vs]["obs"] for vs in ("rep", "fw5", "ifn", "fw1") if vs in v and v[vs]["obs"]), [])
        sl, sa = (float(np.mean(clon[ks])), float(np.mean(clat[ks]))) if ks else tc.get("default_seed", (5.0, 50.0))
        rec = {}
        files = sorted(glob.glob(tc["tracked"].format(storm=s["id"]))) if tc.get("tracked") else []
        rec["era5"] = tracked(files, d0, sl, sa) if files else []
        for k, (name, m) in enumerate([(n, m) for m in s["members"] for n in m.get("xws", [])]):
            p = tc.get("published", "").format(name=name)
            if p and os.path.exists(p):
                rec["xws" if k == 0 else f"xws{k + 1}"] = published(p, dt.date.fromisoformat(m["date"]))
        out[s["id"]] = rec
    return out
