#!/usr/bin/env python3
"""Build the data of the Storm Detection Explorer from the inputs declared in storm_explorer_config.py.

For each forcing: forest cells, validation sets, rule inputs, scoring protocol, rank codes, equal-rate grids, and (main forcing)
the storm states of the ORCHIDEE runs. Then the storm tracks and the two damage tabs. Writes OUTPUT_DATA, one JavaScript file
read by the page (the main forcing in clear, the other forcings as gzip + base64).
Usage: python build_data.py [--config storm_explorer_config.py] [--only isimip,cordex05] [--skip damage,ddamage,tracks]
"""
import argparse, datetime as dt, json, os, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from engine import basemap, cells, damage, ddamage, detection, forcing, orchidee, protocol, tracks, validation  # noqa: E402
from engine.util import b64_gzip_json, load_config, log  # noqa: E402


def rule_ok(rid, M):
    return M.has(rid)


def one_forcing(cfg, fc, main, rule_ids, skip):
    log(f"\n== {fc['id']}: {fc['label']}")
    # ratio thresholds this forcing needs: its AND scan, the AND rank setting, and (main forcing) the runs' AND setting
    ratios = set(fc["and_ratios"])
    if isinstance(fc["rank"].get("and"), tuple):
        ratios.add(fc["rank"]["and"][0])
    if main:
        ratios |= {b["replay"][0] for b in cfg.ORCHIDEE.get("detection_runs", {}).values() if len(b["replay"]) == 3}
    ratios = sorted(ratios)
    cfg.RATIO_THRESHOLDS = sorted(set(cfg.RATIO_THRESHOLDS) | set(ratios))
    C = cells.forest_cells(fc, cfg)
    clon, clat, fha, nc = C["lon"], C["lat"], C["forest_ha"], len(C["lon"])
    log(f"  {nc} forest cells at {fc['res']} deg")
    storms = [s for s in cfg.STORMS if cfg.FIRST_YEAR <= int(s["date"][:4]) <= fc["years"][1]]

    # ---- validation sets
    V = cfg.VALIDATION; val = {s["id"]: {} for s in storms}
    rp = V.get("reports")
    if rp and os.path.exists(rp["file"]) and os.path.isdir(rp["regions_dir"]):
        proj = validation.project_reports(rp, clon, clat, fc["res"])
        for s in storms:
            r = validation.reported_set(s, proj)
            if r:
                val[s["id"]]["rep"] = r
    else:
        log("  reported damage: inputs missing, set skipped")
    pc = V.get("polygons")
    if pc and os.path.exists(pc["file"]):
        for sid, sets in validation.polygon_sets(pc, storms, clon, clat, fha, fc["res"]).items():
            val[sid].update(sets)
    else:
        log("  damage polygons: file missing, set skipped")
    for s in storms:
        b = validation.box_set(s, clon, clat)
        if b:
            val[s["id"]]["ifn"] = b
    rc = V.get("raster"); FR, ryears = (None, [])
    if rc and fc.get("raster_dir"):
        FR, ryears = validation.raster_fractions(rc, fc["raster_dir"], clon, clat, fha)
        for s in storms:
            r = validation.raster_set(s, FR, ryears, rc)
            if r:
                val[s["id"]]["efda"] = r

    # ---- rule inputs
    inp = forcing.inputs(fc, C["handle"], C["sel"], cfg.BOX, cfg.CACHE_DIR, ratios)
    gust = forcing.gust_peak(fc, clon, clat, fc["years"])
    M = detection.Metrics(inp, gust, ratios)
    rules_on = [r for r in rule_ids if rule_ok(r, M)]
    wins = detection.windows(storms, M.ords, cfg.STORM_WINDOW)
    first_ord = dt.date(cfg.FIRST_YEAR, 1, 1).toordinal()

    # ---- protocol (regions needed)
    proto, AB, seasons, region = None, None, None, None
    if os.path.exists(cfg.REGIONS["file"]):
        region = protocol.regions(cfg.REGIONS, clon, clat)
        proto, AB, seasons = protocol.run(cfg, fc, M, storms, val, wins, region, FR, ryears, rules_on, cfg.CONVECTIVE)
    else:
        log("  regions file missing: no protocol")

    # ---- rank codes, equal-rate grids
    rank = {}
    for rid in rules_on:
        p = fc["rank"].get(rid, cfg.PROTOCOL_CURRENT[rid])
        rank[rid] = tuple(proto[rid]["setting"]) if p == "protocol" and proto else (cfg.PROTOCOL_CURRENT[rid] if p == "protocol" else p)
    codes = {rid: detection.rank_codes(M, rid, rank[rid], storms, wins, first_ord, cfg.CALM_DAYS) for rid in rules_on}
    rep = [np.array(val[s["id"]].get("rep", {}).get("obs", []), int) for s in storms]
    log("  equal-rate grids")
    grid = detection.equal_rate(M, cfg, fc, storms, wins, rep, rules_on, cfg.NPROC)

    # ---- ORCHIDEE storm states (main forcing)
    online = {}
    if main:
        online = orchidee.model_states(cfg, M, clon, clat)
    out_storms = []
    for si, s in enumerate(storms):
        rec = {"id": s["id"], "label": s["label"], "date": s["date"], "codes": {rid: codes[rid][si] for rid in rules_on},
               "val": val[s["id"]]}
        if online:
            rec["online"] = {rid: "".join("1" if x else "0" for x in st[wins[si]].any(0)) for rid, (st, _) in online.items()}
        out_storms.append(rec)
    D = {"forcing": fc["id"], "label": fc["label"], "note": fc["note"], "res": fc["res"], "period": list(fc["years"]),
         "box": list(cfg.BOX),
         "cells": {"lon": np.round(clon, 3).tolist(), "lat": np.round(clat, 3).tolist(),
                   "forest_kha": np.round(fha / 1e3, 2).tolist(), **({"region": region.tolist()} if region is not None else {})},
         "storms": out_storms, "grid": {k: {kk: vv for kk, vv in g.items() if not kk.startswith("_")} for k, g in grid.items()},
         "iso": {"levels": [round(float(x), 2) for x in cfg.LEVELS],
                 "note": "every rule set to the parameters giving L onsets per cell and decade (mean over cells, %d on)" % cfg.FIRST_YEAR},
         "rank_settings": {k: list(v) for k, v in rank.items()}, "nstorm": len(out_storms), "generated": dt.date.today().isoformat()}
    if proto:
        D["protocol"] = proto
    if online:
        R = cfg.ORCHIDEE["detection_runs"]
        D["online"] = {"settings": {k: R[k]["setting"] for k in online}, "runs": {k: R[k]["run"] for k in online},
                       "fa": {k: v[1].tolist() for k, v in online.items()}}
    extra = {"clon": clon, "clat": clat, "fha": fha, "fpx": C["forest_px"], "val": val, "storms": storms, "region": region, "AB": AB, "seasons": seasons}
    return D, extra


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "storm_explorer_config.py"))
    ap.add_argument("--only", default=None, help="comma-separated forcing ids (the main forcing is always built)")
    ap.add_argument("--skip", default="", help="comma-separated parts to skip: tracks, damage, ddamage")
    a = ap.parse_args()
    cfg = load_config(a.config)
    os.chdir(os.path.dirname(os.path.abspath(a.config)))
    skip = set(filter(None, a.skip.split(",")))
    rule_ids = [r["id"] for r in cfg.RULES]
    forcings = [f for i, f in enumerate(cfg.FORCINGS) if i == 0 or not a.only or f["id"] in a.only.split(",")]
    built = {}
    for i, fc in enumerate(forcings):
        try:
            built[fc["id"]] = one_forcing(cfg, fc, i == 0, rule_ids, skip)
        except FileNotFoundError as e:
            if i == 0:
                raise
            log(f"  {fc['id']} skipped: {e}")
    main_id = forcings[0]["id"]
    D, X = built[main_id]
    bm = basemap.build(cfg.BASEMAP, cfg.BOX)
    T = {} if "tracks" in skip else tracks.build(cfg.TRACKS, X["storms"], X["val"], X["clon"], X["clat"])
    DM = None if "damage" in skip else damage.build(cfg, X["storms"], X["clon"], X["clat"])
    DD = None
    if "ddamage" not in skip and X["AB"] is not None:
        DD = ddamage.build(cfg, X["storms"], X["val"], X["clon"], X["clat"], X["fpx"], X["region"], X["AB"], X["seasons"])
    present = {r for d, _ in built.values() for r in d["grid"]}
    conf = {"title": cfg.TITLE, "intro": cfg.INTRO, "first_year": cfg.FIRST_YEAR, "default_storm": cfg.DEFAULT_STORM,
            "rules": [r for r in cfg.RULES if r["id"] in present], "vsets": cfg.VSETS, "forcing_tab_vsets": cfg.FORCING_TAB_VSETS,
            "forcings": [{k: f[k] for k in ("id", "label", "short", "colour_var", "note")} | {"period": list(f["years"])}
                         for f in forcings if f["id"] in built],
            "main": main_id, "notes": cfg.NOTES, "storm_window": list(cfg.STORM_WINDOW),
            "damage": {"agent_labels": cfg.DAMAGE["agent_labels"], "europe_label": cfg.DAMAGE["europe_label"],
                       "reference": cfg.DAMAGE["reference"]["name"]},
            "generated": dt.date.today().isoformat()}
    with open(cfg.OUTPUT_DATA, "w") as f:
        f.write("window.SDE_CONFIG = "); json.dump(conf, f, separators=(",", ":")); f.write(";\n")
        f.write("window.SDE_BASEMAP = "); json.dump({"land": bm["land"], "borders": bm["borders"]}, f, separators=(",", ":")); f.write(";\n")
        f.write("window.STORMDATA = "); json.dump(D, f, separators=(",", ":")); f.write(";\n")
        f.write("window.SDE_FORCINGS = "); json.dump({k: b64_gzip_json(d) for k, (d, _) in built.items() if k != main_id}, f); f.write(";\n")
        f.write("window.STORMTRACKS = "); json.dump(T, f, separators=(",", ":")); f.write(";\n")
        f.write("window.STORMDAMAGE = "); json.dump(DM, f, separators=(",", ":")); f.write(";\n")
        f.write("window.STORMDDAMAGE = "); json.dump(DD, f, separators=(",", ":"), default=float); f.write(";\n")
    log(f"\nwrote {cfg.OUTPUT_DATA} ({os.path.getsize(cfg.OUTPUT_DATA) / 1e6:.1f} MB): forcings {', '.join(built)}; "
        f"tracks {len(T)}, damage {'yes' if DM else 'no'}, detection x damage {'yes' if DD else 'no'}")


if __name__ == "__main__":
    main()
