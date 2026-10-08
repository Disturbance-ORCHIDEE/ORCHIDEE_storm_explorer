"""Detection of the catalogued storms by each rule, on one forcing.

For every rule the page shows the storm state at the SAME background onset rate L (onsets per cell and decade, mean over the
cells, seasons from FIRST_YEAR on), L = LEVELS: comparing rules at their own optimum would mix how well a rule separates
storms with how often it fires.
  peak, gust  one threshold X*: the onset rate is scanned on X_SCAN, X*(L) interpolated, then replayed at X*(L).
  and         three thresholds (ratio r, sum S, max V): for each (r, V), S(L) is interpolated (log scale) from S_SCAN; among the
              (r, V, S(L)) the one detecting most reported storm-cells is kept (this choice uses the validation set).
A cell is detected for a storm if it is in storm state within STORM_WINDOW days of the storm date. Its rank is the rank of the
strongest episode in that window among the cell's declustered episodes (>= 5 days apart), on the rule's rank metric.
"""
import datetime as dt, multiprocessing as mp

import numpy as np

from . import rules
from .util import b64_bits, b64_rate, log

_T = {}      # replay context inherited by the forked workers


class Metrics:
    """the daily rule inputs of one forcing on its cells."""

    def __init__(self, inp, gust, ratios):
        self.ords, self.yrs = inp["ords"], inp["yrs"]
        self.X, self.Z = rules.online(inp["wpeak"], inp["pmean"], self.yrs)
        self.ST = {r: rules.three_day(inp["rs"][r], inp["wpeak"]) for r in ratios}
        self.Xg = rules.online(gust, inp["pmean"], self.yrs)[0] if gust is not None else None

    def trigger(self, rule, p):
        if rule == "and":
            S3, M3 = self.ST[p[0]]; return (S3 >= p[1]) & (M3 >= p[2])
        return (self.X if rule == "peak" else self.Xg) >= p[0] - 1e-9

    def rank_metric(self, rule, p):
        if rule == "and":
            S3, M3 = self.ST[p[0]]; return np.minimum(S3 / p[1], M3 / p[2])
        return self.X if rule == "peak" else self.Xg

    def has(self, rule):
        return rule != "gust" or self.Xg is not None


def windows(storms, ords, win):
    return [np.where((ords >= dt.date.fromisoformat(s["date"]).toordinal() + win[0]) &
                     (ords <= dt.date.fromisoformat(s["date"]).toordinal() + win[1]))[0] for s in storms]


def rank_codes(M, rule, p, storms, wins, first_ord, ncalm):
    """per storm: one digit per cell = 2 x rank class + detected at the rank setting."""
    st, _ = rules.run_states(M.trigger(rule, p), ncalm)
    met = M.rank_metric(rule, p)
    eps = [rules.episodes(met[:, k], M.ords, first_ord) for k in range(met.shape[1])]
    out = []
    for wi in wins:
        ws = set(wi.tolist()); det = st[wi].any(0); ch = []
        for k in range(met.shape[1]):
            r = 61
            for n_, d in enumerate(eps[k]):
                if d in ws:
                    r = n_ + 1; break
            ch.append(str(rules.bucket(r) * 2 + int(det[k])))
        out.append("".join(ch))
    return out


# --------------------------------------------------------------------------------------------- parallel replay
def _work(a):
    c0, c1, need = a; T = _T; nc = T["nc"]
    st, on = rules.run_states(np.concatenate([t() for t in T["trigs"][c0:c1]], axis=1), T["ncalm"])
    out = []
    for j in range(c1 - c0):
        s_ = slice(j * nc, (j + 1) * nc)
        fc = on[T["sel"], s_].sum(0) / T["nyrs"] * 10
        dj = np.array([st[w, s_].any(0) for w in T["wins"]])
        out.append((float(fc.mean()), fc.astype("f4"), dj if need else None,
                    int(sum(dj[si, T["rep"][si]].sum() for si in range(len(T["wins"]))))))
    return out


def replay(trigs, need_det, nproc):
    """mean onsets per cell and decade, onsets per cell, detection bits (if asked) and reported hits, for each trigger."""
    _T["trigs"] = trigs
    step = max(1, int(2e5 // _T["nc"]))
    jobs = [(c0, min(c0 + step, len(trigs)), need_det) for c0 in range(0, len(trigs), step)]
    if nproc > 1 and len(jobs) > 1:
        with mp.get_context("fork").Pool(min(nproc, len(jobs))) as pool:
            res = [r for part in pool.map(_work, jobs) for r in part]
    else:
        res = [r for j in jobs for r in _work(j)]
    return (np.array([r[0] for r in res]), [r[1] for r in res], [r[2] for r in res] if need_det else [],
            np.array([r[3] for r in res]))


def _interp_level(levels, xs, rate, log_x=False):
    """parameter giving each level (the rate decreases with the parameter); NaN where out of reach."""
    r, x = rate[::-1], (np.log(xs) if log_x else np.asarray(xs, float))[::-1]
    r, keep = np.maximum.accumulate(r), np.r_[True, np.diff(np.maximum.accumulate(r)) > 0]
    r, x = r[keep], x[keep]
    out = np.where((levels >= r[0]) & (levels <= r[-1]), np.interp(levels, r, x), np.nan)
    return np.exp(out) if log_x else out


def equal_rate(M, cfg, fc, storms, wins, rep, rules_on, nproc):
    """{rule: grid record of the page} at the levels of cfg.LEVELS."""
    levels = np.round(np.asarray(cfg.LEVELS, float), 2)
    sel = M.yrs >= cfg.FIRST_YEAR
    _T.update(nc=M.X.shape[1], wins=wins, sel=sel, nyrs=len(np.unique(M.yrs[sel])), rep=rep, ncalm=cfg.CALM_DAYS)
    out = {}
    for rid in rules_on:
        R = cfg.RULE_SCAN[rid]
        if rid in ("peak", "gust"):
            xs = np.round(np.arange(*R["X"]), 4)
            rate, _, _, _ = replay([lambda x=x, r=rid: M.trigger(r, (x,)) for x in xs], False, nproc)
            xl = _interp_level(levels, xs, rate); ok = ~np.isnan(xl)
            mean, fa, det, hits = replay([lambda x=x, r=rid: M.trigger(r, (x,)) for x in xl[ok]], True, nproc)
            setting = [[round(float(x), 4)] for x in xl[ok]]
        else:
            SS = np.round(np.geomspace(*R["S"]), 1)
            pairs = [(r, V) for r in fc["and_ratios"] for V in R["V"]]
            rate_all, _, _, _ = replay([lambda r=r, V=V, s=s: M.trigger("and", (r, s, V)) for r, V in pairs for s in SS], False, nproc)
            cand = {k: [] for k in range(len(levels))}
            for ip, (r, V) in enumerate(pairs):
                sl = _interp_level(levels, SS, rate_all[ip * len(SS):(ip + 1) * len(SS)], log_x=True)
                for k, s in enumerate(sl):
                    if not np.isnan(s):
                        cand[k].append((r, round(float(s), 1), V))
            flat = sorted(set(c for k in cand for c in cand[k]))
            _, _, _, h = replay([lambda c=c: M.trigger("and", c) for c in flat], False, nproc)
            H = dict(zip(flat, h))
            best = [max(cand[k], key=lambda c: (H[c], -c[1])) if cand[k] else None for k in range(len(levels))]
            ok = np.array([b is not None for b in best]); bb = [b for b in best if b is not None]
            mean, fa, det, hits = replay([lambda c=c: M.trigger("and", c) for c in bb], True, nproc)
            setting = [list(b) for b in bb]
        out[rid] = {"params": {"L": [round(float(x), 2) for x in levels[ok]]}, "n": int(ok.sum()), "settings": setting,
                    "means": [round(float(x), 3) for x in mean], "bits": b64_bits(np.array(det, bool)),
                    "fa": b64_rate(np.array(fa)), "_det": np.array(det, bool), "_fa": np.array(fa)}
        log(f"    {rid}: levels {levels[ok].min() if ok.any() else '-'}-{levels[ok].max() if ok.any() else '-'}")
    return out
