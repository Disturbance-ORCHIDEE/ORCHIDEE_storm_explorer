"""Storm-onset rules of ORCHIDEE, replayed offline on the wind and pressure the model sees.

ORCHIDEE places each daily forcing value at noon and interpolates linearly to its 30-min time step; a sub-daily forcing is
interpolated the same way from its own time stamps (forcing.py). The rules then work on daily quantities:
  wpeak   daily maximum of the interpolated wind (m/s)
  pmean   daily mean of the interpolated surface pressure (Pa)
  rs_r    sum over the 48 steps of ratio = wind / 5-year mean wind, where ratio > r
Rules (one cell = one column of a (days, cells) array):
  peak    X = wpeak / reference peak; storm when X >= X*. The reference is the mean of the last five yearly
          'NTOP-th highest wpeak' values, as coded (online()).
  gust    the peak rule on a daily maximum gust instead of wpeak.
  and     3-day sum of rs_r >= S AND 3-day maximum of wpeak >= V.
A cell enters storm state on the first triggering day and leaves it after CALM consecutive non-triggering days (run_states).
"""
import numpy as np

NTOP, NDAYS, NLEG = 4, 30, 5        # online(): rank of the reference peak, pressure window, years kept


def _pad(a):
    return np.vstack([a[:1], a, a[-1:]])


def wpeak_daily(w):
    """daily maximum of the noon-centred, linearly interpolated DAILY wind: max(w_d, (w_d-1 + w_d)/2, (w_d + w_d+1)/2)."""
    q = _pad(w)
    return np.maximum.reduce([q[1:-1], (q[:-2] + q[1:-1]) / 2, (q[1:-1] + q[2:]) / 2])


def pmean_daily(p):
    """daily mean of the interpolated DAILY pressure = (p_d-1 + 6 p_d + p_d+1) / 8."""
    q = _pad(p)
    return (q[:-2] + 6 * q[1:-1] + q[2:]) / 8


def five_year_mean(w, yrs):
    """per day, the mean of the previous (at most five) yearly means of w (the current year when there is none)."""
    ym = {y: w[yrs == y].mean(0) for y in np.unique(yrs)}
    lt = np.zeros_like(w)
    for y in np.unique(yrs):
        prev = [ym[k] for k in range(y - 5, y) if k in ym] or [ym[y]]
        lt[yrs == y] = np.mean(prev, axis=0)
    return lt


def ratio_sums_daily(w, yrs, rthr, chunk=64):
    """rs_r of a DAILY forcing: the 48 half-hourly values are interpolated between the noon values."""
    lt = five_year_mean(w, yrs)
    nd, nc = w.shape
    q = _pad(w)
    f = (np.arange(48) + 0.5) / 48.0 - 0.5                      # offset of each step from noon, in days
    rs = np.zeros_like(w)
    for c0 in range(0, nc, chunk):
        sl = slice(c0, c0 + chunk)
        a, b, c = q[:-2, sl], q[1:-1, sl], q[2:, sl]
        hh = np.where(f[None, :, None] < 0, b[:, None] + f[None, :, None] * (b - a)[:, None],
                      b[:, None] + f[None, :, None] * (c - b)[:, None])
        r = hh / lt[:, None, sl]
        rs[:, sl] = np.where(r > rthr, r, 0).sum(axis=1)
    return rs


def three_day(rs, wp):
    """3-day running sum of rs and 3-day running maximum of wpeak (day d with d-1 and d-2)."""
    S3 = rs.copy(); M3 = wp.copy()
    S3[1:] += rs[:-1]; S3[2:] += rs[:-2]
    M3[1:] = np.maximum(M3[1:], wp[:-1]); M3[2:] = np.maximum(M3[2:], wp[:-2])
    return S3, M3


def online(wpeak, pday, years):
    """X (peak ratio) and Z (pressure anomaly in standard deviations) exactly as ORCHIDEE computes them day by day."""
    nd, nc = wpeak.shape
    top = np.zeros((nc, NTOP)); rsave = np.zeros((nc, NLEG))
    hist = np.zeros((nc, NDAYS)); acc = np.zeros((nc, 3)); vsave = np.zeros((nc, NLEG))
    X = np.zeros((nd, nc)); Z = np.zeros((nd, nc))
    for d in range(nd):
        v = wpeak[d].copy()
        for k in range(NTOP):
            sw = v > top[:, k]; top[sw, k], v[sw] = v[sw], top[sw, k]
        h = rsave > 0; ref = np.where(h.any(1), (rsave * h).sum(1) / np.maximum(h.sum(1), 1), 0)
        X[d] = np.where(ref > 0, wpeak[d] / np.where(ref > 0, ref, 1), 0)
        full = (hist > 0).sum(1) == NDAYS; an = pday[d] - hist.mean(1); hv = vsave > 0
        sd = np.sqrt(np.where(hv.any(1), (vsave * hv).sum(1) / np.maximum(hv.sum(1), 1), np.nan))
        Z[d] = np.where(full & hv.any(1), an / sd, 0)
        acc[full] += np.stack([np.ones(full.sum()), an[full], an[full] ** 2], 1)
        hist[:, 1:] = hist[:, :-1].copy(); hist[:, 0] = pday[d]
        if d == nd - 1 or years[d + 1] != years[d]:
            rsave[:, 1:] = rsave[:, :-1].copy(); rsave[:, 0] = top[:, NTOP - 1]; top[:] = 0
            n = acc[:, 0]; var = np.where(n > 1, acc[:, 2] / np.maximum(n, 1) - (acc[:, 1] / np.maximum(n, 1)) ** 2, 0)
            vsave[:, 1:] = vsave[:, :-1].copy(); vsave[:, 0] = np.maximum(var, 0) * (n > 1); acc[:] = 0
    return X, Z


def run_states(m, ncalm):
    """storm state and onsets from a (days, cells) trigger array: onset on a trigger outside storm, exit after ncalm calm days."""
    nd, nc = m.shape; st = np.zeros_like(m); on = np.zeros_like(m)
    storm = np.zeros(nc, bool); calm = np.zeros(nc, int)
    for d in range(nd):
        new = ~storm & m[d]; on[d] = new
        calm = np.where(storm, np.where(m[d], 0, calm + 1), 0)
        storm = (storm & (calm < ncalm)) | new; calm[new] = 0
        st[d] = storm
    return st, on


def episodes(s, ords, first_ordinal, nmax=60, sep=5):
    """declustered episode peaks of the metric s (day indices, strongest first, >= sep days apart), from first_ordinal on."""
    s = np.where(ords >= first_ordinal, np.nan_to_num(s, nan=-np.inf), -np.inf)
    taken = []
    for d in np.argsort(-s):
        if not np.isfinite(s[d]) or s[d] <= 0 or len(taken) >= nmax:
            break
        if all(abs(d - t) >= sep for t in taken):
            taken.append(d)
    return taken


def bucket(r):
    """rank class shown by the page: 1st, 2nd-3rd, 4th-10th, 11th-30th, beyond."""
    return 0 if r == 1 else 1 if r <= 3 else 2 if r <= 10 else 3 if r <= 30 else 4
