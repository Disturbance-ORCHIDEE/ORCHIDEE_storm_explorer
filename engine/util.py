"""Small shared helpers: logging, config loading, encodings used by the page."""
import base64, datetime as dt, gzip, importlib.util, json, os, sys

import numpy as np


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def load_config(path):
    spec = importlib.util.spec_from_file_location("storm_explorer_config", path)
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    return cfg


def missing(*paths):
    """the paths (patterns with {year} are checked for their first year by the caller) that do not exist."""
    return [p for p in paths if p and not os.path.exists(p)]


def b64_bits(a):
    """boolean array -> base64 of its bits, little-endian bit order (decoded by the page)."""
    return base64.b64encode(np.packbits(np.asarray(a, bool).ravel(), bitorder="little").tobytes()).decode()


def b64_rate(fa, step=0.05):
    """onsets per decade -> base64 of uint8 steps of 0.05 (decoded by the page)."""
    return base64.b64encode(np.clip(np.round(np.asarray(fa) / step), 0, 255).astype(np.uint8).tobytes()).decode()


def b64_gzip_json(obj):
    return base64.b64encode(gzip.compress(json.dumps(obj, separators=(",", ":")).encode(), 9)).decode()


def ordinal(d):
    return dt.date.fromisoformat(d).toordinal() if isinstance(d, str) else d.toordinal()


def nearest_index(points, values):
    """index of the nearest point for each value (1-D)."""
    points = np.asarray(points)
    return [int(np.argmin(abs(points - v))) for v in values]


def cell_key(res, lon0, lat0):
    """function (x, y) -> (i, j) of the nearest cell centre on a regular grid of step res whose centres include (lon0, lat0)."""
    return lambda x, y: (int(round((x - lon0) / res)), int(round((y - lat0) / res)))
