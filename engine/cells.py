"""Forest cells of a forcing grid: land points inside the box whose forest area reaches the threshold.

The forest map is a raster on the forcing grid (one pixel per cell, centred on the forcing points) holding a count of forest
pixels; area = count x pixel_ha. Threshold = min_ha_per_deg2 x res^2, so the same forest SHARE is required at every
resolution. Without a forest raster every land point of the box is a cell and forest areas are reported as 0.
"""
import os

import numpy as np

from . import forcing
from .util import log


def forest_cells(fc, cfg):
    box = cfg.BOX
    plo, pla, handle = forcing.grid_points(fc, box, cfg.CACHE_DIR, cfg.RATIO_THRESHOLDS, cfg.NPROC)
    inbox = (plo >= box[0]) & (plo <= box[1]) & (pla >= box[2]) & (pla <= box[3])
    fr = fc.get("forest_raster")
    if fr and os.path.exists(fr):
        import rasterio
        with rasterio.open(fr) as r:
            fp = np.nan_to_num(r.read(1)); h, w = fp.shape
            rc = [r.index(a, b) for a, b in zip(plo, pla)]
        px = np.array([fp[i, j] if 0 <= i < h and 0 <= j < w else 0.0 for i, j in rc])
        fha = px * cfg.FOREST["pixel_ha"]
        keep = inbox & (fha >= cfg.FOREST["min_ha_per_deg2"] * fc["res"] ** 2)
    else:
        log(f"  {fc['id']}: no forest raster, every land point of the box is a cell")
        px = fha = np.zeros(len(plo)); keep = inbox
    sel = np.where(keep)[0]
    return {"sel": sel, "lon": plo[sel], "lat": pla[sel], "forest_ha": fha[sel], "forest_px": px[sel], "handle": handle}
