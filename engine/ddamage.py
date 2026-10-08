"""Detection x Damage tab: tighten a run's detection thresholds offline and read the damage it would have done.

No new simulation. Every storm end of an archived run (IS_KILL_STORM) belongs to an episode (the days since the cell's previous
storm end, at most 60); the episode is kept if one of its days passes the stricter setting, read in the daily output:
  peak  STORM_PEAK_RATIO >= X            and   WIND_SUM >= S and DAILY_MAX_WIND_MOD >= V (same day)
Settings can only be stricter than the run's, and removing an episode does not change the stands it would have damaged.
For each setting:
  volume   rho = model / reference wind volume on the calibration events: (country, year) with >= MIN_EVENT_M3 of reference
           volume and a catalogued storm reported in that country. Model volume = felled wood of the country's cells on damage
           days within the storm windows; the reference is scaled by d, the forest-weighted share of the storm's reported
           cells where the model ended a storm (effective detection). Median over events, held-out events listed apart.
  area     model storm + bark-beetle damaged area (AREA_DAMAGED_STORM + AREA_DAMAGED_PEST over FOREST_AREA) against the
           disturbance raster (EFDA agent 1), % of forest per decade, July-June seasons, Europe and each region.
  quiet    share of the storm-damaged area in quiet cell-seasons (protocol.absences).
  ends     storm ends per cell and decade.
"""
import datetime as dt, itertools, os

import numpy as np
from netCDF4 import Dataset

from . import damage, orchidee
from .util import log


def _rd(d, v):
    x = np.ma.filled(d[v][:].astype("f8"), 0.0); x[~np.isfinite(x) | (np.abs(x) > 1e30)] = 0.0
    return x


def daily_fields(cfg, run, y0, y1):
    out = {k: [] for k in ("K", "X", "S", "W")}; yd = []
    for y in range(y0, y1 + 1):
        with Dataset(orchidee.path(cfg, "daily", run, y)) as d:
            g = lambda v: (np.where(np.abs(x := np.ma.filled(d[v][:].astype("f8"), 0.0)) > 1e30, 0.0, x) if v in d.variables else None)
            k = g("IS_KILL_STORM") > 0.5
            out["K"].append(k); out["X"].append(g("STORM_PEAK_RATIO")); out["S"].append(g("WIND_SUM")); out["W"].append(g("DAILY_MAX_WIND_MOD"))
            yd += [y] * k.shape[0]
    return {k: (np.concatenate(v) if v[0] is not None else None) for k, v in out.items()}, np.array(yd)


def keep_mask(Dd, yd, cond, y0, y1):
    K = Dd["K"]; ok = cond(Dd); P = np.zeros(K.shape, bool); last = np.full(K.shape[1:], -1)
    for t in np.nonzero(K.any(axis=(1, 2)))[0]:
        for i, j in zip(*np.nonzero(K[t])):
            a = max(last[i, j] + 1, t - 60); P[t, i, j] = ok[a:t + 1, i, j].any(); last[i, j] = t
    return {y: P[yd == y] for y in range(y0, y1 + 1)}


def cond_of(rule, s):
    if rule == "peak":
        return lambda D: D["X"] >= s["X"] - 1e-9
    return lambda D: (D["S"] >= s["S"] - 1e-9) & (D["W"] >= s["V"] - 1e-9)


def model_area(cfg, run, ii, jj, seasons, y0, y1):
    ns, nc = len(seasons), len(ii)
    st, pe, fo = np.zeros((ns, nc)), np.zeros((ns, nc)), []
    for y in range(y0, y1 + 1):
        with Dataset(orchidee.path(cfg, "monthly", run, y)) as d:
            s = _rd(d, "AREA_DAMAGED_STORM").sum(1)[:, ii, jj]; p = _rd(d, "AREA_DAMAGED_PEST").sum(1)[:, ii, jj]
            fo.append(_rd(d, "FOREST_AREA").sum(1)[:, ii, jj].mean(0) * 1e6)
        for m in range(12):
            k = y + 1 if m >= 6 else y
            if k in seasons:
                st[seasons.index(k)] += s[m]; pe[seasons.index(k)] += p[m]
    return st, pe, np.mean(fo, axis=0)


class Events:
    """calibration events of the volume test, built once on the run grid."""

    def __init__(self, cfg, storms, val, clon, clat, lat, lon, forest_px, y0, y1):
        DD = cfg.DDAMAGE; self.win1 = DD["window"][1]
        self.cg = damage.country_grid(cfg.DAMAGE["countries"], lat, lon)
        self.gi = lambda lo, la: (int(np.argmin(abs(lat - la))), int(np.argmin(abs(lon - lo))))
        # Guillaume M. -- Forest weight in double precision from the pixel count, as the volume test was calibrated.
        fmap = {(round(float(a), 3), round(float(b), 3)): float(f) * cfg.FOREST["pixel_ha"] for a, b, f in zip(clon, clat, forest_px)}
        self.forest = lambda lo, la: fmap.get((round(float(lo), 3), round(float(la), 3)), 0.0)
        rf = cfg.DAMAGE["reference"]; self.dfde = {}
        for r in damage.read_xlsx(rf["file"]):
            if rf["agents"].get(r["disturbance_driver"]) != "wind":
                continue
            c = rf.get("aliases", {}).get(r["country"], r["country"]); y = int(r["Year"])
            try:
                self.dfde[(c, y)] = self.dfde.get((c, y), 0.0) + float(r["Expert_GapFilled_m3"] or 0)
            except ValueError:
                pass
        self.cy = {}
        for s in storms:
            if s["id"] in cfg.CONVECTIVE:
                continue
            d0 = dt.date.fromisoformat(s["date"])
            if not (y0 <= d0.year <= y1) or d0.toordinal() + self.win1 > dt.date(y1, 12, 31).toordinal():
                continue
            v = val[s["id"]]
            ks = v.get("rep", {}).get("obs") or v.get("fw5", {}).get("obs", [])
            for k in ks:
                lo, la = clon[k], clat[k]; i, j = self.gi(lo, la); c = self.cg[i, j]
                if c:
                    self.cy.setdefault((c, d0.year), {}).setdefault(s["id"], (d0, set()))[1].add((lo, la))
        self.valid = {tuple(x) for x in DD["held_out"]}
        self.min_m3 = DD["min_event_m3"]

    def rows(self, V, K, O):
        out = []
        for (c, y), storms in sorted(self.cy.items()):
            vobs = self.dfde.get((c, y), 0.0)
            if vobs < self.min_m3:
                continue
            days = np.zeros(len(O), bool)
            for d0, _ in storms.values():
                days |= (O >= d0.toordinal() - 2) & (O <= d0.toordinal() + self.win1)
            vmod = float(V[days][:, self.cg == c].sum())
            num = den = 0.0
            for d0, cells in storms.values():
                w = (O >= d0.toordinal() - 2) & (O <= d0.toordinal() + self.win1)
                for lo, la in cells:
                    i, j = self.gi(lo, la); fw = self.forest(lo, la)
                    den += fw; num += fw * float(K[w, i, j].any())
            d = num / den if den > 0 else 0.0
            out.append({"country": c, "year": y, "rho": vmod / (vobs * d) if d > 0 and vobs > 0 else None, "valid": (c, y) in self.valid})
        return out


def build(cfg, storms, val, clon, clat, forest_px, region, AB, ab_seasons):
    DD = cfg.DDAMAGE; y0, y1 = DD["years"]
    seasons = list(range(y0 + 1, y1 + 1))
    first = next(iter(DD["versions"].values()))["runs"]; run0 = next(iter(first.values()))
    if not os.path.exists(orchidee.path(cfg, "monthly", run0, y0)):
        log("  Detection x Damage: runs missing, tab skipped"); return None
    with Dataset(orchidee.path(cfg, "monthly", run0, y0)) as d:
        la, lo = np.asarray(d["lat"][:]), np.asarray(d["lon"][:])
    ii = np.array([int(np.argmin(abs(la - b))) for b in clat]); jj = np.array([int(np.argmin(abs(lo - a))) for a in clon])
    quiet = AB[:, [ab_seasons.index(y) for y in seasons]].T
    import rasterio
    rc = cfg.VALIDATION["raster"]; rdir = cfg.FORCINGS[0]["raster_dir"]
    with rasterio.open(cfg.FORCINGS[0]["forest_raster"]) as r:
        rcx = [r.index(a, b) for a, b in zip(clon, clat)]; fp = np.nan_to_num(r.read(1))
    pix_m2 = rc.get("pixel_ha", 0.09) * 1e4
    efor = np.array([fp[i, j] for i, j in rcx]) * pix_m2
    eag = np.array([[np.nan_to_num(rasterio.open(os.path.join(rdir, rc["pattern"].format(year=y))).read(1))[i, j] * pix_m2
                     for i, j in rcx] for y in seasons])
    names = cfg.REGIONS["names"]
    masks = {"Europe": np.isin(region, names), **{r: region == r for r in names}}
    dec = 10.0 / len(seasons)
    obs = {k: 100 * eag[:, m].sum() / efor[m].sum() * dec for k, m in masks.items()}
    ev = Events(cfg, storms, val, clon, clat, la, lo, forest_px, y0, y1)
    data = {"efda": obs, "regions": list(masks), "period": [y0, y1], "versions": {}, "generated": dt.date.today().isoformat(),
            "ref_name": DD.get("reference_name", "reference")}
    for vid, V in DD["versions"].items():
        keys = list(V["params"]); combos = list(itertools.product(*[V["params"][k] for k in keys]))
        rec = {"label": V["label"], "rule": V["rule"], "base": V["base"], "params": V["params"], "keys": keys,
               "tunes": list(V["runs"]), "res": {}}
        for t, run in V["runs"].items():
            if not all(os.path.exists(orchidee.path(cfg, k, run, y)) for k in ("daily", "monthly") for y in range(y0, y1 + 1)):
                log(f"  Detection x Damage: run {run} incomplete, skipped"); continue
            Dd, yd = daily_fields(cfg, run, y0, y1)
            yv = {y: orchidee.year_volumes(cfg, run, y) for y in range(y0, y1 + 1)}
            st_m = {}
            for y in range(y0, y1 + 1):
                with Dataset(orchidee.path(cfg, "monthly", run, y)) as d:
                    st_m[y] = _rd(d, "AREA_DAMAGED_STORM").sum(1)
            _, pe, fo = model_area(cfg, run, ii, jj, seasons, y0, y1)
            O = np.array([dt.date(y, 1, 1).toordinal() + k for y in range(y0, y1 + 1) for k in range(yv[y][0].shape[0])])
            rows = []
            for c in combos:
                s = dict(zip(keys, c))
                keep = keep_mask(Dd, yd, cond_of(V["rule"], s), y0, y1)
                Vk = np.concatenate([yv[y][0] * keep[y] for y in range(y0, y1 + 1)])
                Kk = np.concatenate([yv[y][1] & keep[y] for y in range(y0, y1 + 1)])
                allrows = ev.rows(Vk, Kk, O)
                cal = [r for r in allrows if not r["valid"] and r["rho"] and r["rho"] > 0]
                lr = np.log10([r["rho"] for r in cal]) if cal else np.array([np.nan])
                vrow = {f"{r['country']} {r['year']}": r["rho"] for r in allrows if r["valid"]}
                st = np.zeros((len(seasons), len(clon))); nend = 0
                for y in range(y0, y1 + 1):
                    vol = yv[y][0]; nd = vol.shape[0]
                    month = np.array([(dt.date(y, 1, 1) + dt.timedelta(k)).month - 1 for k in range(nd)])
                    sm = st_m[y].copy()
                    for m in range(12):
                        v = vol[month == m]; tot = v.sum(0)
                        sm[m] *= np.where(tot > 0, (v * keep[y][month == m]).sum(0) / np.where(tot > 0, tot, 1), 1.0)
                    sm = sm[:, ii, jj]; nend += int(keep[y][:, ii, jj].sum())
                    for m in range(12):
                        kk = y + 1 if m >= 6 else y
                        if kk in seasons:
                            st[seasons.index(kk)] += sm[m]
                area = {k: [round(100 * st[:, mm].sum() / fo[mm].sum() * dec, 3), round(100 * pe[:, mm].sum() / fo[mm].sum() * dec, 3)]
                        for k, mm in masks.items()}
                rows.append({"rho": None if not cal else round(float(10 ** np.median(lr)), 3), "n": len(cal),
                             "iqr": None if not cal else [round(float(10 ** np.percentile(lr, 25)), 3), round(float(10 ** np.percentile(lr, 75)), 3)],
                             "valid": {k: (round(v, 3) if v else None) for k, v in vrow.items()},
                             "area": area, "quiet": round(float(st[quiet].sum() / max(st.sum(), 1e-9)), 3),
                             "ends": round(nend / len(clon) / (y1 - y0 + 1) * 10, 2)})
            rec["res"][str(t)] = rows
            log(f"    Detection x Damage {vid} {t}: {len(rows)} settings")
        if rec["res"]:
            data["versions"][vid] = rec
    return data if data["versions"] else None
