"""Validation sets: for each storm, the list of forest cells where damage is known, by four kinds of source.

  reports   forest wind damage reported by region (NUTS 2021 code, or a lat/lon circle), each report checked by a verifier.
            A report counts if its verdict is 'confirmed' or 'plausible_unreachable', or 'level_overstated' / 'wrong_region'
            with a correction (applied); and its level is 'major' or 'moderate'. A cell counts for a storm when the region of a
            counting report covers >= F_CELL of the cell's land, or lies >= F_POLY inside the cell. Weight 1 (major) or 0.5.
  polygons  damage polygons with a storm name, a country and a date (FORWIND v2): cells with >= n polygons (centroids), or
            whose polygons cover >= 1 % of the cell's forest.
  boxes     lon/lat boxes per storm (e.g. French IFN regions).
  raster    an annual disturbance raster on the cell grid (EFDA agent 1): cells whose disturbed share in the storm's year is
            >= 3 x its median over the other years and >= 0.5 %; a storm from July on is looked up in the next year.
Every source is optional: a missing file skips that set with a warning.
"""
import csv, datetime as dt, json, os

import numpy as np

from .util import cell_key, log

COUNT_VERDICTS = {"confirmed", "plausible_unreachable"}
COUNT_LEVELS = {"major", "moderate"}
FIXABLE = {"level_overstated", "wrong_region"}


# --------------------------------------------------------------------------------------------- reported damage
def _load_regions(nuts_dir):
    from shapely.geometry import shape
    from shapely.ops import unary_union
    geo = {}
    for lev in (2, 3):
        for f in json.load(open(os.path.join(nuts_dir, f"NUTS_RG_10M_2021_4326_LEVL_{lev}.geojson")))["features"]:
            geo[f["properties"]["NUTS_ID"]] = shape(f["geometry"]).buffer(0)
    land = unary_union([g for k, g in geo.items() if len(k) == 4])
    return geo, land


def _circle(lat, lon, r_km):
    from shapely.geometry import Polygon
    t = np.linspace(0, 2 * np.pi, 65)
    return Polygon(np.column_stack([lon + r_km / (111.0 * np.cos(np.radians(lat))) * np.cos(t), lat + r_km / 111.0 * np.sin(t)]))


def project_reports(rc, clon, clat, res):
    """{storm name: {date, cells, weight, n_reports, countries, searched_none, reports}} on the given cells."""
    from shapely.geometry import box
    from shapely.prepared import prep
    geo, land = _load_regions(rc["regions_dir"])
    plan, h = prep(land), res / 2
    cells = [box(x - h, y - h, x + h, y + h) for x, y in zip(clon, clat)]
    cland = [c.intersection(land) if plan.intersects(c) else c for c in cells]
    carea = np.array([max(c.area, 1e-9) for c in cland])
    out = {}
    for b in json.load(open(rc["file"])):
        ver_id = {}
        for v in (b.get("verdicts") or []):
            ver_id.setdefault(v["id"], []).append(v)
        for s in b["storms"]:
            lev_max, nrep, ctry, flat = {}, 0, set(), []
            for r in s["reports"]:
                cand = ver_id.get(r["id"], [])
                v = next((c for c in cand if c["storm"] == s["storm"]), cand[0] if cand else {})
                verdict = v.get("verdict", "unverified")
                nid = v.get("corrected_nuts_id") or r.get("nuts_id")
                lev = v.get("corrected_damage_level") or r["damage_level"]
                if nid and nid in geo:
                    poly = geo[nid]
                elif r.get("lat") is not None and r.get("lon") is not None:
                    poly = _circle(r["lat"], r["lon"], r.get("radius_km") or 25.0)
                else:
                    poly = None
                fixed = verdict in FIXABLE and (v.get("corrected_nuts_id") or v.get("corrected_damage_level"))
                ok = verdict in COUNT_VERDICTS or (fixed and not rc.get("strict", False))
                if not (ok and lev in COUNT_LEVELS and poly is not None):
                    continue
                pp = prep(poly)
                for k, c in enumerate(cland):
                    if not pp.intersects(cells[k]):
                        continue
                    a = poly.intersection(c).area
                    if a / carea[k] >= rc.get("f_cell", 0.10) or a / max(poly.area, 1e-9) >= rc.get("f_poly", 0.50):
                        lev_max[k] = max(lev_max.get(k, 0.0), 1.0 if lev == "major" else 0.5)
                nrep += 1; ctry.add(r["country"])
                flat.append([r["country"], r["region_name"], lev, r["source_type"], (r["source_title"] or "")[:140],
                             r["source_url"]])
            ks = sorted(lev_max)
            out[s["storm"]] = {"date": s["date"], "cells": ks, "weight": [lev_max[k] for k in ks], "n_reports": nrep,
                               "countries": sorted(ctry), "searched_none": s.get("countries_searched_no_forest_damage", []),
                               "reports": flat}
    return out


def reported_set(storm, proj):
    """validation record of one storm (merged storms: the union of their members' reports)."""
    names = [n for m in storm["members"] for n in m.get("reports", [])]
    recs = [proj[n] for n in names if n in proj]
    if not recs:
        return None
    w = {}
    for r in recs:
        for k, wl in zip(r["cells"], r["weight"]):
            w[k] = max(w.get(k, 0.0), wl)
    none = sorted({c for r in recs for c in r["searched_none"]})
    ctry = sorted({c for r in recs for c in r["countries"]})
    note = f"{sum(r['n_reports'] for r in recs)} verified reports ({', '.join(ctry) or 'none'})" \
        + (f"; searched, nothing found: {', '.join(none)}" if none else "")
    return {"obs": sorted(w), "weight": [w[k] for k in sorted(w)], "note": note,
            "reports": sorted(map(list, {tuple(x) for r in recs for x in r["reports"]}))}


# --------------------------------------------------------------------------------------------- damage polygons
def polygon_sets(pc, storms, clon, clat, fha, res):
    """{storm id: {'fw5': ..., 'fw1': ...}} from a polygon file with storm name, country, date and area fields."""
    import pyogrio, shapely
    meta, _, geom, fields = pyogrio.raw.read(pc["file"])
    F = {k: v for k, v in zip(meta["fields"], fields)}
    cen = shapely.centroid(shapely.from_wkb(geom)); gx, gy = shapely.get_x(cen), shapely.get_y(cen)
    dates = np.array([str(s)[:10].replace("/", "-") for s in F[pc.get("date_field", "EventDate")]])
    names, ctrys, areas = F[pc.get("name_field", "StormName")], F[pc.get("country_field", "Country")], F[pc.get("area_field", "Area")]
    key = cell_key(res, clon[0], clat[0])
    index = {key(a, b): k for k, (a, b) in enumerate(zip(clon, clat))}
    nmin = max(1, int(round(pc.get("min_polygons_per_deg2", 5) * res * res)))
    out = {}
    for s in storms:
        sel = [x for m in s["members"] for x in m.get("polygons", [])]
        if not sel:
            continue
        m = np.zeros(len(gx), bool)
        for name, ctry, dd in sel:
            mm = (names == name) & (ctrys == ctry)
            if dd:
                mm &= dates == dd
            m |= mm
        npoly = np.zeros(len(clon), int); area = np.zeros(len(clon))
        for x_, y_, a_ in zip(gx[m], gy[m], areas[m]):
            k = index.get(key(x_, y_))
            if k is not None:
                npoly[k] += 1; area[k] += max(float(a_), 0.0)
        pct = 100 * area / np.where(fha > 0, fha, np.inf)
        note = f"{int(m.sum())} polygons ({', '.join(sorted({c for _, c, _ in sel}))}); {int((npoly > 0).sum())} cells with >= 1 polygon"
        out[s["id"]] = {"fw5": {"obs": [int(k) for k in np.where(npoly >= nmin)[0]], "n": npoly.tolist(), "pct": np.round(pct, 2).tolist(),
                                "note": note + (f" (threshold {nmin} polygon(s) at {res:g} deg)" if nmin != 5 else "")},
                        "fw1": {"obs": [int(k) for k in np.where(pct >= pc.get("min_forest_pct", 1.0))[0]], "n": npoly.tolist(),
                                "pct": np.round(pct, 2).tolist(), "note": note}}
    return out


# --------------------------------------------------------------------------------------------- boxes
def box_set(storm, clon, clat):
    boxes = {k: v for m in storm["members"] for k, v in m.get("boxes", {}).items()}
    if not boxes:
        return None
    obs = sorted({k for k in range(len(clon)) for (x0, x1, y0, y1) in boxes.values() if x0 <= clon[k] <= x1 and y0 <= clat[k] <= y1})
    return {"obs": obs, "note": "regions (lon/lat boxes): " + ", ".join(boxes)}


# --------------------------------------------------------------------------------------------- disturbance raster
def raster_fractions(rc, raster_dir, clon, clat, fha):
    """disturbed share of the cell's forest per raster year (years, cells), and the years; None if the files are missing."""
    import rasterio
    years = list(range(rc["years"][0], rc["years"][1] + 1))
    paths = [os.path.join(raster_dir, rc["pattern"].format(year=y)) for y in years]
    if not all(os.path.exists(p) for p in paths):
        log(f"  disturbance raster missing in {raster_dir}, set skipped")
        return None, years
    with rasterio.open(paths[0]) as r:
        rcix = [r.index(a, b) for a, b in zip(clon, clat)]
    ii, jj = np.array([p[0] for p in rcix]), np.array([p[1] for p in rcix])
    FR = np.array([np.nan_to_num(rasterio.open(p).read(1))[ii, jj] * rc.get("pixel_ha", 0.09) / np.where(fha > 0, fha, np.inf)
                   for p in paths])
    return FR, years


def raster_year(date, rc):
    d0 = dt.date.fromisoformat(date)
    return d0.year + (1 if d0.month >= rc.get("next_year_from_month", 7) else 0)


def anomaly(FR, years, y, rc):
    k = years.index(y); med = np.median(np.delete(FR, k, axis=0), axis=0)
    return (FR[k] >= rc.get("factor", 3.0) * med) & (FR[k] >= rc.get("min_share", 0.005))


def raster_set(storm, FR, years, rc):
    y = raster_year(storm["date"], rc)
    if FR is None or y not in years:
        return None
    return {"obs": [int(k) for k in np.where(anomaly(FR, years, y, rc))[0]], "note": f"{rc.get('name', 'raster')} year {y}"}
