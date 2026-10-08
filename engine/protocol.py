"""Scoring protocol of a rule's settings: Peirce skill score PSS = H - F, chosen on all regions, validated leaving one out.

  events    (storm, cell) pairs of the reported set (weight 1 major, 0.5 moderate) and of the polygon set (weight 1), convective
            storms excluded; H = weighted share detected.
  absences  cell-seasons (July-June) with no catalogued storm in any set and no raster anomaly; F = share with an onset.
  regions   each cell gets a region from a lon/lat table of 1 deg cells, grouped (e.g. biogeographic -> North, West, ...).
The setting with the best PSS on all regions is kept (ties: fewest false onsets, then closest to the current setting);
leave-one-region-out folds give the out-of-region score shown by the page.
"""
import csv, datetime as dt

import numpy as np

from . import rules
from .util import log


def season_of(d):
    return d.year + (1 if d.month >= 7 else 0)


def regions(rc, clon, clat):
    """region group of each cell; cells without one get the nearest named neighbour among the 9 closest."""
    reg = {(float(r["lon"]), float(r["lat"])): r["region"] for r in csv.DictReader(open(rc["file"]))}
    keys = np.array(list(reg)); names = list(reg.values()); out = []
    for a, b in zip(clon, clat):
        r = reg.get((np.floor(a) + 0.5, np.floor(b) + 0.5))
        if r is None or r == "NA":
            dd = (keys[:, 0] - a) ** 2 + (keys[:, 1] - b) ** 2
            for i in np.argsort(dd)[:9]:
                if names[i] != "NA":
                    r = names[i]; break
        out.append(rc["groups"].get(r, "NA"))
    return np.array(out)


def absences(storms, val, nc, seasons, FR, ryears, rc):
    """quiet cell-seasons: no catalogued storm in any set, no raster anomaly; the last season is never quiet."""
    from .validation import anomaly
    touched = np.zeros((nc, len(seasons)), bool)
    for s in storms:
        y = season_of(dt.date.fromisoformat(s["date"]))
        if y in seasons:
            for vs in ("rep", "fw5", "fw1", "ifn"):
                for k in val[s["id"]].get(vs, {}).get("obs", []):
                    touched[k, seasons.index(y)] = True
    anom = np.zeros((nc, len(seasons)), bool)
    if FR is not None:
        for k, y in enumerate(seasons):
            if y in ryears:
                anom[:, k] = anomaly(FR, ryears, y, rc)
    AB = ~touched & ~anom; AB[:, -1] = False
    return AB


def families(cfg, fc, M, rules_on):
    P = cfg.PROTOCOL_SCAN; out = {}
    for rid in rules_on:
        if rid == "and":
            out[rid] = ({"r": fc["and_ratios"], "S": P["S"], "V": P["V"]}, lambda r, s, v: M.trigger("and", (r, s, v)))
        else:
            out[rid] = ({"X": P["X"]}, lambda x, rid=rid: M.trigger(rid, (x,)))
    return out


def combos_of(params):
    out = [()]
    for k in params:
        out = [c + (v,) for c in out for v in params[k]]
    return out


def run(cfg, fc, M, storms, val, wins, region, FR, ryears, rules_on, convective):
    """{rule: protocol record}, plus the absence mask (cells, seasons) and the seasons."""
    nc = M.X.shape[1]; y1 = int(M.yrs.max())
    seasons = list(range(cfg.FIRST_YEAR, y1 + 2))
    season_idx = np.array([season_of(dt.date.fromordinal(int(o))) for o in M.ords])
    sel = M.yrs >= cfg.FIRST_YEAR; nyrs = len(np.unique(M.yrs[sel]))
    Wt = np.zeros((len(storms), nc))
    for si, s in enumerate(storms):
        if s["id"] in convective:
            continue
        v = val[s["id"]]
        if "rep" in v:
            for k, wl in zip(v["rep"]["obs"], v["rep"].get("weight", [1.0] * len(v["rep"]["obs"]))):
                Wt[si, k] = max(Wt[si, k], wl)
        for k in v.get("fw5", {}).get("obs", []):
            Wt[si, k] = 1.0
    AB = absences(storms, val, nc, seasons, FR, ryears, cfg.VALIDATION["raster"])
    allm = np.isin(region, cfg.REGIONS["names"])

    def score(det, ons, m):
        Wm = Wt * m[None]; A = AB & m[:, None]
        H = (det * Wm[None]).sum(axis=(1, 2)) / max(Wm.sum(), 1e-9); F = (ons & A[None]).sum(axis=(1, 2)) / max(A.sum(), 1)
        return H - F, H, F

    def pick(pss, F, cb, cur):
        best = pss.max(); cand = [i for i in range(len(cb)) if pss[i] >= best - 1e-12]
        cand.sort(key=lambda i: (F[i], np.linalg.norm((np.array(cb[i]) - np.array(cur)) / (np.abs(np.array(cur)) + 1e-9))))
        return cand[0]

    proto = {}
    for rid, (params, trig) in families(cfg, fc, M, rules_on).items():
        cb = combos_of(params)
        det = np.zeros((len(cb), len(wins), nc), bool); ons = np.zeros((len(cb), nc, len(seasons)), bool)
        fa = np.zeros((len(cb), nc), "f4")
        step = max(1, int(4e5 // nc))
        for c0 in range(0, len(cb), step):
            chunk = cb[c0:c0 + step]
            st, on = rules.run_states(np.concatenate([trig(*c) for c in chunk], axis=1), cfg.CALM_DAYS)
            for j in range(len(chunk)):
                s_ = slice(j * nc, (j + 1) * nc)
                for si, wi in enumerate(wins):
                    det[c0 + j, si] = st[wi, s_].any(0)
                for k, y in enumerate(seasons):
                    ons[c0 + j, :, k] = on[season_idx == y, s_].any(0)
                fa[c0 + j] = on[sel, s_].sum(0) / nyrs * 10
        cur = cfg.PROTOCOL_CURRENT[rid]
        pss, H, F = score(det, ons, allm); ib = pick(pss, F, cb, cur)
        folds = []
        for r in cfg.REGIONS["names"]:
            tr = np.isin(region, [x for x in cfg.REGIONS["names"] if x != r]); te = region == r
            p_tr, _, F_tr = score(det, ons, tr); i_f = pick(p_tr, F_tr, cb, cur)
            p_te, H_te, F_te = score(det, ons, te)
            folds.append({"region": r, "setting": list(cb[i_f]), "pss": float(p_te[i_f]), "H": float(H_te[i_f]), "F": float(F_te[i_f])})
        proto[rid] = {"setting": list(cb[ib]), "pss_all": float(pss[ib]), "H_all": float(H[ib]), "F_all": float(F[ib]),
                      "loro": float(np.mean([x["pss"] for x in folds])), "folds": folds, "onsets_median": float(np.median(fa[ib]))}
        log(f"    protocol {rid}: best {cb[ib]} PSS {pss[ib]:.3f}, out-of-region {proto[rid]['loro']:.3f}")
    return proto, AB, seasons
