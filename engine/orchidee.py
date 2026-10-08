"""Reading archived ORCHIDEE runs: the storm states the model produced, and the wood it felled.

Files (paths in ORCHIDEE['daily'] / ['monthly'] of the config, with {run} and {year}):
  daily    storm_daily output: IS_KILL_STORM (storm end with damage), WIND_DAMAGE_WOODVOL (m3 per m2 of PFT),
           STORM_PEAK_RATIO, WIND_SUM, DAILY_MAX_WIND_MOD
  monthly  stomate_history: VEGET_MAX, Areas, CONTFRAC, WOOD_VOL, Beetle_damage_woodvol, AREA_BURNT_PFT,
           AREA_DAMAGED_STORM, AREA_DAMAGED_PEST, FOREST_AREA
Model storm states: the model writes storm ENDS, not states. Each offline replay episode at the run's own setting is kept if the
model ended a storm in that cell within one day of the episode's end; model ends without a matching episode get the six days
before the end (1-2 % of them).
"""
import datetime as dt, os

import numpy as np
from netCDF4 import Dataset

from . import rules
from .util import log


def path(cfg, kind, run, year):
    return cfg.ORCHIDEE[kind].format(run=run, year=year)


def kill_flags(cfg, run, years, clon, clat, ords):
    """IS_KILL_STORM on the cells, aligned on ords (False outside the run); None if the run is missing."""
    o0 = int(np.searchsorted(ords, dt.date(years[0], 1, 1).toordinal()))
    kills = []; bij = None
    for y in range(years[0], years[1] + 1):
        p = path(cfg, "daily", run, y)
        if not os.path.exists(p):
            log(f"  ORCHIDEE run {run}: {p} missing, model detections skipped")
            return None
        with Dataset(p) as d_:
            if bij is None:
                blat, blon = np.asarray(d_["lat"][:]), np.asarray(d_["lon"][:])
                bij = [(int(np.argmin(abs(blat - b))), int(np.argmin(abs(blon - a)))) for a, b in zip(clon, clat)]
            kk = np.ma.filled(d_["IS_KILL_STORM"][:], 0.0) > 0.5
        kills.append(np.array([kk[:, i, j] for i, j in bij]).T)
    KL = np.zeros((len(ords), len(clon)), bool); KC = np.concatenate(kills)
    KL[o0:o0 + len(KC)] = KC[:len(ords) - o0]
    return KL, o0


def model_states(cfg, M, clon, clat):
    """{rule: (state (days, cells), storm ends per cell and decade)} for the rules with a bench run."""
    out = {}
    for rid, b in cfg.ORCHIDEE.get("detection_runs", {}).items():
        if not M.has(rid):
            continue
        r = kill_flags(cfg, b["run"], b["years"], clon, clat, M.ords)
        if r is None:
            continue
        KL, o0 = r
        stb, _ = rules.run_states(M.trigger(rid, b["replay"]), cfg.CALM_DAYS)
        nd, nc = stb.shape
        on_st = np.zeros_like(stb)
        for k in range(nc):
            col = stb[:, k]; used = np.zeros(nd, bool)
            ends = np.where(col[:-1] & ~col[1:])[0] + 1
            starts = np.where(~np.r_[False, col[:-1]] & col)[0]
            for a_, e_ in zip(starts, ends):
                hitk = np.where(KL[max(e_ - 1, 0):e_ + 2, k])[0]
                if len(hitk):
                    on_st[a_:e_, k] = True; used[max(e_ - 1, 0) + hitk[0]] = True
            for e_ in np.where(KL[:, k] & ~used)[0]:
                if not used[max(e_ - 1, 0):e_ + 2].any():
                    on_st[max(e_ - 6, 0):e_, k] = True
        fa = np.round(KL[o0:].sum(0) / ((nd - o0) / 3652.5), 2)
        out[rid] = (on_st, fa)
        log(f"    ORCHIDEE {rid} ({b['run']}): {int(KL.sum())} model storm ends")
    return out


def year_volumes(cfg, run, year):
    """daily felled volume (days, lat, lon) m3, damage flag, standing volume (lat, lon) m3, lat, lon, other agents; None if absent."""
    fd, fm = path(cfg, "daily", run, year), path(cfg, "monthly", run, year)
    if not (os.path.exists(fd) and os.path.exists(fm)):
        return None
    with Dataset(fm) as m:
        vm = np.ma.filled(m["VEGET_MAX"][:], 0.0)
        area = np.ma.filled(m["Areas"][:], 0.0) * np.ma.filled(m["CONTFRAC"][:], 0.0)
        wv = np.ma.filled(m["WOOD_VOL"][:], 0.0) if "WOOD_VOL" in m.variables else None
        lat, lon = m["lat"][:], m["lon"][:]
        other = {}
        if "Beetle_damage_woodvol" in m.variables:
            bw = np.ma.filled(m["Beetle_damage_woodvol"][:], 0.0)
            other["beetle"] = (bw * vm).sum(axis=1).max(axis=0) * area          # computed once a year: monthly maximum
        if "AREA_BURNT_PFT" in m.variables and wv is not None:
            ab = np.ma.filled(m["AREA_BURNT_PFT"][:], 0.0); ab = np.where(np.abs(ab) < 1e30, ab, 0.0)
            ndm = np.array([(dt.date(year + (mo == 12), mo % 12 + 1, 1) - dt.date(year, mo, 1)).days for mo in range(1, 13)])
            other["fire"] = np.einsum("m,mvij,mvij->ij", ndm, ab * 1e4, wv)  # wood of the burnt stands: upper bound
    with Dataset(fd) as d:
        wd = np.ma.filled(d["WIND_DAMAGE_WOODVOL"][:], 0.0)
        kill = np.ma.filled(d["IS_KILL_STORM"][:], 0.0) > 0.5
    nd = wd.shape[0]
    month = np.array([(dt.date(year, 1, 1) + dt.timedelta(k)).month - 1 for k in range(nd)])
    vol = np.einsum("tvij,tvij->tij", wd, vm[month]) * area[None]
    stand = np.einsum("mvij,mvij->ij", wv, vm) / 12.0 * area if wv is not None and wv.ndim == 4 else None
    return vol, kill, stand, np.asarray(lat), np.asarray(lon), other


def run_years(cfg, run, y0=None, y1=None):
    """years of a run for which both daily and monthly files exist."""
    lo, hi = (y0, y1) if y0 else cfg.ORCHIDEE.get("years", (1900, 2100))
    return [y for y in range(lo, hi + 1) if os.path.exists(path(cfg, "daily", run, y)) and os.path.exists(path(cfg, "monthly", run, y))]
