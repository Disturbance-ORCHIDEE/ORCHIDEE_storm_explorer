"""Base map (land outlines and country borders) clipped to the box and simplified, from Natural Earth shapefiles.

Without the shapefiles the bundled basemap_europe.json is used (Natural Earth 1:50m, public domain, box 12W-34E x 33-72N).
"""
import json, os

import numpy as np

from .util import log

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def rings(path, box):
    import pyogrio, shapely
    clip = shapely.box(box[0] - 0.5, box[2] - 0.5, box[1] + 0.5, box[3] + 0.5)
    _, _, g, _ = pyogrio.raw.read(path)
    out = []
    for geo in shapely.from_wkb(g):
        geo = shapely.intersection(geo, clip).simplify(0.04)
        if geo.is_empty:
            continue
        for part in getattr(geo, "geoms", [geo]):
            if part.geom_type == "Polygon":
                out.append(np.round(np.asarray(part.exterior.coords), 2).tolist())
            elif part.geom_type in ("LineString", "LinearRing"):
                out.append(np.round(np.asarray(part.coords), 2).tolist())
    return out


def build(bc, box):
    land, borders = bc.get("land"), bc.get("borders")
    if land and borders and os.path.exists(land) and os.path.exists(borders):
        try:
            return {"land": rings(land, box), "borders": rings(borders, box)}
        except ImportError as e:
            log(f"  basemap: {e}, bundled map used")
    log("  basemap: Natural Earth shapefiles not found, bundled basemap_europe.json used")
    return json.load(open(os.path.join(HERE, "basemap_europe.json")))
