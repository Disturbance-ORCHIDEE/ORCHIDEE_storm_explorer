"""Forcing readers: the daily rule inputs (wpeak, pmean, rs_r) as ORCHIDEE would see them, cached on disk.

Two kinds of forcing (FORCINGS[...]['kind'] in the config):
  daily     one value per day (e.g. ISIMIP), placed at noon and interpolated to 30 min (rules.wpeak_daily, ...).
            The whole box is read once and cached as <cache>/<id>_daily.npz.
  subdaily  N-hourly samples (e.g. EURO-CORDEX 3-hourly, ERA5 hourly), linearly interpolated to the 48 half-hour steps of
            each day from their own time stamps; one cache file per year, <cache>/<id>/<year>.npz, for the land points.
Readers ('reader'): 'netcdf' (wind or u/v and pressure variables, CF time axis) and 'grib1_era5' (ERA5 GRIB1 files holding
parameters 165, 166 and 134, simple packing only; convert other GRIB files to netCDF first).
The gust (optional) is read from daily-maximum netCDF files and taken on each cell by nearest point or by maximum.
"""
import datetime as dt, os
from concurrent.futures import ProcessPoolExecutor
import numpy as np
from netCDF4 import Dataset

from . import rules
from .util import log


# --------------------------------------------------------------------------------------------- low-level readers
def _time_axis(var):
    unit = var.units
    base = unit.split("since ")[1].strip()[:19]
    t0 = dt.datetime.fromisoformat(base.replace("T", " ") if len(base) > 10 else base + " 00:00:00")
    step = {"seconds": 1, "second": 1, "minutes": 60, "hours": 3600, "hour": 3600, "days": 86400, "day": 86400}[unit.split()[0]]
    return [t0 + dt.timedelta(seconds=float(s) * step) for s in np.asarray(var[:])]


def read_netcdf(fc, y, only=None):
    """(times, wind (n, nj, ni), pressure (n, nj, ni), lat, lon) of year y."""
    with Dataset(fc["files"].format(year=y)) as d:
        d.set_auto_mask(False)
        ts = _time_axis(d[fc.get("time", "time")])
        if "wind" in fc:
            w = np.asarray(d[fc["wind"]][:], "f4")
        else:
            u, v = (np.asarray(d[k][:], "f4") for k in fc["uv"])
            w = np.sqrt(u * u + v * v)
        p = np.asarray(d[fc["pressure"]][:], "f4")
        lat, lon = np.asarray(d[fc.get("lat", "lat")][:]), np.asarray(d[fc.get("lon", "lon")][:])
    if only is not None:
        k = [i for i, t in enumerate(ts) if t in only]
        ts, w, p = [ts[i] for i in k], w[k], p[k]
    return ts, w, p, lat, lon


def _sm(b):
    v = int.from_bytes(b, "big"); n = 8 * len(b) - 1
    return -(v & ((1 << n) - 1)) if v >> n else v


def _ibm(b):
    s = -1.0 if b[0] & 0x80 else 1.0
    return s * int.from_bytes(b[1:4], "big") / 2 ** 24 * 16.0 ** ((b[0] & 0x7F) - 64)


def read_grib1_era5(fc, y, only=None):
    """ERA5 GRIB1 year file with u10 (165), v10 (166), surface pressure (134); duplicated messages dropped by valid time."""
    raw = open(fc["files"].format(year=y), "rb").read(); pos = 0; seen = {165: {}, 166: {}, 134: {}}; grid = None
    while pos < len(raw):
        L = int.from_bytes(raw[pos + 4:pos + 7], "big"); p = raw[pos + 8:pos + L]
        code = p[8]
        if code in seen:
            t = dt.datetime((p[24] - 1) * 100 + p[12], p[13], p[14], p[15])
            t += dt.timedelta(hours=p[19] if p[20] in (2, 3, 4, 5) else p[18])
            if t not in seen[code] and (only is None or t in only):
                pl = int.from_bytes(p[0:3], "big"); D = _sm(p[26:28]); g = p[pl:]; gl = int.from_bytes(g[0:3], "big")
                ni, nj = int.from_bytes(g[6:8], "big"), int.from_bytes(g[8:10], "big")
                if grid is None:
                    grid = (ni, nj, _sm(g[10:13]) / 1e3, _sm(g[13:16]) / 1e3, _sm(g[17:20]) / 1e3, _sm(g[20:23]) / 1e3)
                b = g[gl:]; E = _sm(b[4:6]); R = _ibm(b[6:10])
                if b[10] != 16 or (b[3] >> 4) & 0x0C or p[7] & 0x40:
                    raise RuntimeError(f"{fc['files'].format(year=y)}: GRIB packing not handled, convert to netCDF")
                x = np.frombuffer(b[11:11 + 2 * ni * nj], ">u2").astype("f4")
                seen[code][t] = ((R + x * 2.0 ** E) / 10.0 ** D).reshape(nj, ni)
        pos += L
    ts = sorted(seen[165])
    if grid is None:
        return [], None, None, None, None
    assert ts == sorted(seen[166]) == sorted(seen[134]), "u, v, sp times differ"
    u = np.stack([seen[165][t] for t in ts]); v = np.stack([seen[166][t] for t in ts])
    lat = np.linspace(grid[2], grid[4], grid[1]); lon = np.linspace(grid[3], grid[5], grid[0])
    return ts, np.sqrt(u * u + v * v), np.stack([seen[134][t] for t in ts]), lat, lon


READERS = {"netcdf": read_netcdf, "grib1_era5": read_grib1_era5}


def land_mask(fc, lat, lon, sample_year):
    """land points of the forcing grid: a variable of the forcing file (> 0) or a separate mask file (> threshold)."""
    lm = fc["land"]
    with Dataset(lm.get("file", fc["files"]).format(year=sample_year)) as d:
        d.set_auto_mask(False)
        m = np.asarray(d[lm["var"]][:]).squeeze()
        if m.shape == (len(lat), len(lon)) and "file" not in lm:
            return m > lm.get("threshold", 0.0)
        la, lo = np.asarray(d[lm.get("lat", "lat")][:]), np.asarray(d[lm.get("lon", "lon")][:])
    if m.shape == (len(lat), len(lon)) and np.allclose(la, lat) and np.allclose(lo, lon):
        return m > lm.get("threshold", 0.0)
    ii = [int(np.argmin(abs(la - b))) for b in lat]; jj = [int(np.argmin(abs(lo - a))) for a in lon]
    return m[np.ix_(ii, jj)] > lm.get("threshold", 0.0)


# --------------------------------------------------------------------------------------------- daily forcing
def _daily_box(fc, box, cache):
    """wind, pressure (days, lat, lon) in the box, lon, lat, land, day ordinals; cached."""
    p = os.path.join(cache, f"{fc['id']}_daily.npz")
    if os.path.exists(p):
        z = np.load(p); return z["W"], z["PS"], z["lon"], z["lat"], z["land"], z["ords"]
    W, PS, ords = [], [], []
    for y in range(fc["years"][0], fc["years"][1] + 1):
        with Dataset(fc["files"].format(year=y)) as d:
            d.set_auto_mask(False)
            lon, lat = np.asarray(d[fc.get("lon", "lon")][:]), np.asarray(d[fc.get("lat", "lat")][:])
            jj = np.where((lon >= box[0]) & (lon <= box[1]))[0]; ii = np.where((lat >= box[2]) & (lat <= box[3]))[0]
            sl = (slice(None), slice(ii.min(), ii.max() + 1), slice(jj.min(), jj.max() + 1))
            W.append(np.asarray(d[fc["wind"]][sl], "f4")); PS.append(np.asarray(d[fc["pressure"]][sl], "f4"))
            land = np.asarray(d[fc["land"]["var"]][sl[1:]], "f4") > fc["land"].get("threshold", 0.0)
            ords += [dt.date(y, 1, 1).toordinal() + k for k in range(W[-1].shape[0])]
        log(f"  {fc['id']}: read {y}")
    lon, lat = lon[jj.min():jj.max() + 1], lat[ii.min():ii.max() + 1]
    W, PS = np.concatenate(W), np.concatenate(PS)
    W = np.where((W > 0) & (W < 1e3), W, np.nan); PS = np.where((PS > 1e4) & (PS < 2e5), PS, np.nan)
    os.makedirs(cache, exist_ok=True)
    np.savez_compressed(p, W=W, PS=PS, lon=lon, lat=lat, land=land, ords=np.array(ords))
    return W, PS, lon, lat, land, np.array(ords)


# --------------------------------------------------------------------------------------------- sub-daily forcing
def _samples(fc, y, land):
    """samples of year y plus the last of y-1 and the first of y+1 (so the first and last steps interpolate)."""
    read = READERS[fc.get("reader", "netcdf")]
    ts, w, p, _, _ = read(fc, y)
    T = [(t - dt.datetime(y, 1, 1)).total_seconds() / 86400 for t in ts]
    W = [w[:, land]]; Pp = [p[:, land]]
    edge = (dt.datetime(y - 1, 12, 31, 23), dt.datetime(y + 1, 1, 1, 0)) if fc.get("reader") == "grib1_era5" else None
    for yy, k in ((y - 1, -1), (y + 1, 0)):
        try:
            t2, w2, p2, _, _ = read(fc, yy, only={edge[0 if k == -1 else 1]} if edge else None)
        except (FileNotFoundError, OSError, AssertionError):
            continue
        if not len(t2):
            continue
        tt = (t2[k] - dt.datetime(y, 1, 1)).total_seconds() / 86400
        if k == -1:
            T = [tt] + T; W = [w2[-1:, land]] + W; Pp = [p2[-1:, land]] + Pp
        else:
            T = T + [tt]; W = W + [w2[:1, land]]; Pp = Pp + [p2[:1, land]]
    return np.array(T), np.concatenate(W).astype("f4"), np.concatenate(Pp).astype("f4")


def _interp_hh(T, x, nd):
    tk = (np.arange(nd * 48) + 0.5) / 48.0
    i = np.clip(np.searchsorted(T, tk) - 1, 0, len(T) - 2)
    a = np.clip((tk - T[i]) / (T[i + 1] - T[i]), 0, 1).astype("f4")[:, None]
    return (x[i] * (1 - a) + x[i + 1] * a).reshape(nd, 48, -1)


def _pass1(args):
    fc, y, land, out = args
    T, w, p = _samples(fc, y, land)
    nd = (dt.date(y + 1, 1, 1) - dt.date(y, 1, 1)).days
    hh = _interp_hh(T, w, nd); ph = _interp_hh(T, p, nd)
    np.savez(f"{out}/{y}_p1.npz", wpeak=hh.max(1), wmean=hh.mean(1), pmean=ph.mean(1))
    return y


def _pass2(args):
    fc, y, land, lt, ratios, out = args
    T, w, _ = _samples(fc, y, land)
    nd = (dt.date(y + 1, 1, 1) - dt.date(y, 1, 1)).days
    r = _interp_hh(T, w, nd) / lt[None, None, :]
    z = dict(np.load(f"{out}/{y}_p1.npz"))
    for thr in ratios:
        z[f"rs_{thr}"] = np.where(r > thr, r, 0).sum(1).astype("f4")
    np.savez(f"{out}/{y}.npz", **z)
    os.remove(f"{out}/{y}_p1.npz")
    return y


def _subdaily_cache(fc, ratios, cache, nproc):
    """grid (lat, lon, land) and the per-year daily inputs of a sub-daily forcing, computed once."""
    out = os.path.join(cache, fc["id"])
    os.makedirs(out, exist_ok=True)
    # Guillaume M. -- Years before the window ('preprocess_from') only feed the 5-year mean wind of the first years.
    years = list(range(fc.get("preprocess_from", fc["years"][0]), fc["years"][1] + 1))
    if not os.path.exists(f"{out}/grid.npz"):
        _, _, _, lat, lon = READERS[fc.get("reader", "netcdf")](fc, years[0])
        np.savez(f"{out}/grid.npz", lat=lat, lon=lon, land=land_mask(fc, lat, lon, years[0]))
    g = np.load(f"{out}/grid.npz"); land = g["land"]
    todo = [y for y in years if not os.path.exists(f"{out}/{y}.npz")
            or any(f"rs_{r}" not in np.load(f"{out}/{y}.npz").files for r in ratios)]
    if todo:
        log(f"  {fc['id']}: preprocessing {len(todo)} years ({land.sum()} land points, {nproc} processes)")
        with ProcessPoolExecutor(nproc) as ex:
            for y in ex.map(_pass1, [(fc, y, land, out) for y in todo]):
                log(f"    pass 1 {y}")
        # the 5-year mean wind needs every year's daily mean: years already cached give theirs too
        ym = {y: np.load(f"{out}/{y}_p1.npz" if y in todo else f"{out}/{y}.npz")["wmean"].mean(0) for y in years}
        lts = {y: np.mean([ym[k] for k in range(y - 5, y) if k in ym] or [ym[y]], axis=0) for y in years}
        with ProcessPoolExecutor(nproc) as ex:
            for y in ex.map(_pass2, [(fc, y, land, lts[y], ratios, out) for y in todo]):
                log(f"    pass 2 {y}")
    return g["lat"], g["lon"], land


# --------------------------------------------------------------------------------------------- public API
def grid_points(fc, box, cache, ratios, nproc):
    """forcing land points: lon, lat (1-D, one per point) and an opaque handle used by inputs()."""
    if fc["kind"] == "daily":
        W, PS, lon, lat, land, ords = _daily_box(fc, box, cache)
        LA, LO = np.meshgrid(lat, lon, indexing="ij")
        return LO[land], LA[land], ("daily", np.nonzero(land))
    lat, lon, land = _subdaily_cache(fc, ratios, cache, nproc)
    LA, LO = np.meshgrid(lat, lon, indexing="ij")
    return LO[land], LA[land], ("subdaily", None)


def inputs(fc, handle, sel, box, cache, ratios):
    """for the selected points sel (indices into grid_points): dict wpeak, pmean, rs {r: array}, ords, yrs."""
    if handle[0] == "daily":
        W, PS, lon, lat, land, ords = _daily_box(fc, box, cache)
        ii, jj = handle[1][0][sel], handle[1][1][sel]
        w = W[:, ii, jj].astype("f8"); p = PS[:, ii, jj].astype("f8")
        yrs = np.array([dt.date.fromordinal(int(o)).year for o in ords])
        return {"wpeak": rules.wpeak_daily(w), "pmean": rules.pmean_daily(p),
                "rs": {r: rules.ratio_sums_daily(w, yrs, r) for r in ratios}, "ords": ords, "yrs": yrs}
    out = os.path.join(cache, fc["id"])
    Z = {k: [] for k in ["wpeak", "pmean"] + [f"rs_{r}" for r in ratios]}
    for y in range(fc["years"][0], fc["years"][1] + 1):
        z = np.load(f"{out}/{y}.npz")
        for k in Z:
            Z[k].append(z[k][:, sel])
    Z = {k: np.concatenate(v).astype("f8") for k, v in Z.items()}
    ords = np.arange(dt.date(fc["years"][0], 1, 1).toordinal(), dt.date(fc["years"][1] + 1, 1, 1).toordinal())
    yrs = np.array([dt.date.fromordinal(int(o)).year for o in ords])
    return {"wpeak": Z["wpeak"], "pmean": Z["pmean"], "rs": {r: Z[f"rs_{r}"] for r in ratios}, "ords": ords, "yrs": yrs}


def gust_peak(fc, clon, clat, years):
    """daily maximum gust on the cells (days, cells), or None when the files are missing. regrid 'nearest' takes the
    nearest point (it must coincide with the cell centre), 'max' the maximum over the points inside the closed cell box."""
    g = fc.get("gust")
    if not g:
        return None
    res, out = fc["res"], []
    for y in range(years[0], years[1] + 1):
        path = g["files"].format(year=y)
        if not os.path.exists(path):
            log(f"  {fc['id']}: gust file missing ({path}), gust rule skipped")
            return None
        with Dataset(path) as d:
            la, lo, x = np.asarray(d[g.get("lat", "lat")][:]), np.asarray(d[g.get("lon", "lon")][:]), np.asarray(d[g["var"]][:])
        if g.get("regrid", "nearest") == "nearest":
            gi = [int(np.argmin(abs(la - b))) for b in clat]; gj = [int(np.argmin(abs(lo - a))) for a in clon]
            assert max(np.max(abs(la[gi] - clat)), np.max(abs(lo[gj] - clon))) < 1e-3, "gust grid does not match the cells"
            out.append(x[:, gi, gj])
        else:
            h = res / 2 + 1e-6; col = []
            for a, b in zip(clon, clat):
                ii = np.where(abs(la - b) <= h)[0]; jj = np.where(abs(lo - a) <= h)[0]
                col.append(x[:, ii][:, :, jj].reshape(x.shape[0], -1).max(1))
            out.append(np.stack(col, 1))
    return np.concatenate(out).astype("f8")
