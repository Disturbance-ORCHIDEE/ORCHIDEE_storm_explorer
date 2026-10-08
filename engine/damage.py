"""Damage tab: wood felled by storms in the ORCHIDEE runs, per storm and per country, against a national reference (DFDE).

Per storm: felled volume and damage flag per cell in the window [date + WINDOW[0], date + WINDOW[1]] days (only when the run
covers the whole window). Per country, calendar year and agent: model wood lost (wind: WIND_DAMAGE_WOODVOL of every event;
bark beetle: Beetle_damage_woodvol; fire: wood of the burnt stands, an upper bound) and the reference volume.
Reference: the Database of European Forest Disturbances (Patacca et al. 2023) as .xlsx, read without openpyxl (zip + XML);
its expert flag gives a status per country-year-agent: r reported, z judged complete (no damage), g gap-filled, e no data.
"""
import csv, datetime as dt, re, zipfile
import xml.etree.ElementTree as ET

import numpy as np
from netCDF4 import Dataset

from . import orchidee
from .util import log

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def read_xlsx(path):
    """rows of the first sheet as dicts keyed by the header row."""
    z = zipfile.ZipFile(path)
    ss = [''.join(t.itertext()) for t in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', NS)]
    table = []
    for row in ET.fromstring(z.read('xl/worksheets/sheet1.xml')).find('m:sheetData', NS):
        vals = {}
        for c in row:
            col = re.match(r'[A-Z]+', c.get('r')).group(0)
            v = c.find('m:v', NS); v = None if v is None else v.text
            if c.get('t') == 's' and v is not None:
                v = ss[int(v)]
            vals[col] = v
        table.append(vals)
    head = table[0]
    return [{head[k]: r.get(k) for k in head} for r in table[1:]]


def country_grid(cc, lat, lon):
    """country name of each grid point: nearest coded point of a country mask within 1.5 deg."""
    d = Dataset(cc["mask"])
    code, clat, clon = d[cc.get("var", "country_code")][:].filled(0), d["lat"][:], d["lon"][:]
    names = {int(r["code"]): r["name"] for r in csv.DictReader(open(cc["codes"])) if r["name"]}
    yy, xx = np.nonzero(code)
    out = np.full((len(lat), len(lon)), "", dtype=object)
    for i, la in enumerate(lat):
        for j, lo in enumerate(lon):
            dd = (clat[yy] - la) ** 2 + (clon[xx] - lo) ** 2
            k = int(np.argmin(dd))
            if dd[k] <= cc.get("max_deg", 1.5) ** 2:
                out[i, j] = names.get(int(code[yy[k], xx[k]]), "")
    return out


def reference(rf, years):
    """{(country, agent, year): volume}, {(country, agent, year): status code}."""
    vol, stat = {}, {}
    for r in read_xlsx(rf["file"]):
        ag = rf["agents"].get(r["disturbance_driver"])
        if ag is None:
            continue
        nm = rf.get("aliases", {}).get(r["country"], r["country"]); y = int(r["Year"])
        code = "r" if r["Reported_m3"] not in (None, "", "NA") else \
            {"complete": "z", "uncomplete": "g", "empty": "e"}.get(r["Expert_interpretation"], "g")
        stat.setdefault((nm, ag, y), set()).add(code)
        if years[0] <= y <= years[1]:
            try:
                v = float(r["Expert_GapFilled_m3"] or 0)
            except ValueError:
                continue
            vol[(nm, ag, y)] = vol.get((nm, ag, y), 0) + round(v)
    st = {k: ("g" if "g" in c else "e" if "e" in c else "r" if "r" in c else "z") for k, c in stat.items()}
    return vol, st


def build(cfg, storms, clon, clat):
    """window.STORMDAMAGE record, or None when no run is found."""
    DM = cfg.DAMAGE
    agents = list(DM["reference"]["agents"].values())
    agents = list(dict.fromkeys(agents))
    out = {"agents": agents, "rules": [{"id": r["rule"], "name": r["name"], "col": r["colour_var"], "run": r["run"]} for r in DM["runs"]],
           "settings": {r["rule"]: r["setting"] for r in DM["runs"]}, "window_days": list(DM["window"]), "storms": {},
           "countries": {}, "years": {}, "period": list(DM["years"])}
    cgrid = ij = None; standing = np.zeros(len(clon)); nstand = 0; daily = {}
    for R in DM["runs"]:
        rule, run = R["rule"], R["run"]
        years = orchidee.run_years(cfg, run, *DM["years"])
        out["years"][rule] = years
        vols, kills, ords, ctry = [], [], [], {}
        for y in years:
            r = orchidee.year_volumes(cfg, run, y)
            if r is None:
                continue
            vol, kill, stand, lat, lon, other = r
            if ij is None:
                ij = [(int(np.argmin(abs(lat - b))), int(np.argmin(abs(lon - a)))) for a, b in zip(clon, clat)]
                cgrid = country_grid(DM["countries"], lat, lon)
                out["cell_country"] = [cgrid[i, j] for i, j in ij]
            if stand is not None and R.get("standing_volume"):
                standing += np.array([stand[i, j] for i, j in ij]); nstand += 1
            for name in set(cgrid.ravel()) - {""}:
                ctry[(name, y, "wind")] = float(vol[:, cgrid == name].sum())
                for ag, a2 in other.items():
                    ctry[(name, y, ag)] = float(a2[cgrid == name].sum())
            vols.append(np.array([vol[:, i, j] for i, j in ij]).T); kills.append(np.array([kill[:, i, j] for i, j in ij]).T)
            ords += [dt.date(y, 1, 1).toordinal() + k for k in range(vol.shape[0])]
            log(f"    damage {rule} {y}: {vol.sum() / 1e6:.1f} Mm3")
        if not vols:
            continue
        daily[rule] = (np.concatenate(vols), np.concatenate(kills), np.array(ords))
        for (name, y, ag), v in ctry.items():
            C = out["countries"].setdefault(name, {a: {"model": {}, "dfde": {}} for a in agents})
            C[ag]["model"].setdefault(rule, {})[str(y)] = round(v)
    if not daily:
        return None
    w0, w1 = DM["window"]
    for s in storms:
        d0 = dt.date.fromisoformat(s["date"]); rec = {}
        for rule, (V, K, O) in daily.items():
            w = (O >= d0.toordinal() + w0) & (O <= d0.toordinal() + w1)
            if not w.any() or O[w].max() < d0.toordinal() + w1:
                continue
            v = V[w].sum(0); k = K[w].any(0)
            cells = [int(c) for c in np.where((v > 0) | k)[0]]
            rec[rule] = {"cells": cells, "vol": [round(float(v[c])) for c in cells], "kill": [int(k[c]) for c in cells]}
        if rec:
            out["storms"][s["id"]] = rec
    try:
        vol, st = reference(DM["reference"], DM["years"])
    except (FileNotFoundError, KeyError) as e:
        log(f"  reference table not read ({e}): model only"); vol, st = {}, {}
    for (nm, ag, y), v in vol.items():
        if nm in out["countries"]:
            dd = out["countries"][nm][ag]["dfde"]; dd[str(y)] = dd.get(str(y), 0) + v
    for (nm, ag, y), c in st.items():
        if nm in out["countries"] and DM["years"][0] <= y <= DM["years"][1]:
            out["countries"][nm][ag].setdefault("status", {})[str(y)] = c
    out["standing_m3"] = [round(float(s / max(nstand, 1))) for s in standing]
    out["generated"] = dt.date.today().isoformat()
    return out
