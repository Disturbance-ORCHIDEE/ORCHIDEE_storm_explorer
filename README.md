# ORCHIDEE Storm Detection Explorer — portable toolkit

Builds a **self-contained HTML file** (`storm_explorer.html`) that answers one question: *which storm-onset rule
of ORCHIDEE switches forest cells to storm state where storms actually struck?* No server, no account, no
network: the data travel inside the file, which opens by double-click in a recent browser and can be shared by
e-mail.

The page has four tabs:

| tab | what it shows |
|---|---|
| **Detection** | for each catalogued storm, one map per rule: which forest cells the rule puts in storm state around the storm date, against a validation set (reported damage, FORWIND polygons, inventory regions, a disturbance-raster anomaly); the rank of the storm among each cell's events; a table over all storms. One slider sets **every rule at the same background onset rate**. Where ORCHIDEE runs exist, the storm states the model actually produced are shown instead of the offline replay. |
| **Damage** | wood felled per storm in the ORCHIDEE runs (maps and table), and annual wood loss per country and agent (wind, bark beetle, fire) against a national reference (DFDE). |
| **Detection × Damage** | tighten a run's detection thresholds offline and read what it does to the felled volume (against DFDE), the disturbed forest area (against a disturbance raster), the damage falling outside storms, and the trigger rate. |
| **Forcings** | the same detection test on several forcings (e.g. ISIMIP 1° daily, EURO-CORDEX 0.5° 3-hourly, ERA5 0.25° hourly), rule by rule, against the onset rate. |

A tab whose inputs are missing is simply not shown.

## Requirements

- **Building the data** (`build_data.py`): Python ≥ 3.9 with `numpy`, `netCDF4`, `scipy`, and for the validation
  sets and base map `shapely`, `pyogrio`, `rasterio`.
- **Assembling the page** (`assemble.py`): Python 3 only — whoever receives `storm_explorer_data.js` can rebuild
  the page.
- **Viewing**: a recent Firefox, Chrome, Edge or Safari (≥ 16.4: the extra forcings are gunzipped in the browser).

## Usage

1. Edit **`storm_explorer_config.py`** — the only file to touch.
2. `python build.py` (or `python build_data.py` then `python assemble.py`).
3. Open `storm_explorer.html`.

`build_data.py --only isimip,cordex05` builds a subset of the forcings (the first, main forcing always);
`--skip tracks,damage,ddamage` leaves parts out. The first build of an hourly forcing preprocesses it once into
`cache/` (ERA5 0.25° over Europe, 35 years: a few hours and about 10 GB); later builds read the cache.

## The files

| file | role |
|---|---|
| **`storm_explorer_config.py`** | **the whole configuration**: forcings, storms, rules, validation sets, ORCHIDEE runs, every text of the page |
| `build_data.py` | engine driver: one pass per forcing, then tracks and the damage tabs; writes `storm_explorer_data.js` |
| `engine/rules.py` | the onset rules as ORCHIDEE codes them (peak ratio X, pressure anomaly Z, AND sums), storm states, episodes |
| `engine/forcing.py` | forcing readers (netCDF, ERA5 GRIB1), the daily rule inputs as the model sees them, cache |
| `engine/cells.py` | forest cells of a grid |
| `engine/validation.py` | the four kinds of validation set |
| `engine/detection.py` | rank codes and the equal-onset-rate settings |
| `engine/protocol.py` | Peirce skill score with one region left out (rank setting of secondary forcings, quiet cell-seasons) |
| `engine/orchidee.py`, `damage.py`, `ddamage.py` | reading the ORCHIDEE runs; the two damage tabs |
| `engine/tracks.py`, `basemap.py` | storm tracks and base map (display aids) |
| `assemble.py`, `build.py` | page assembly; both steps in one command, on any platform |
| `web/` | the page template and its view scripts; every label comes from the configuration |
| `basemap_europe.json` | fallback base map (Natural Earth 1:50m, public domain) |

## Inputs

All paths are set in the configuration; `{year}`, `{run}`, `{storm}`, `{name}` are filled by the engine.

- **Forcings** (`FORCINGS`): yearly netCDF files with wind speed (or u and v) and surface pressure, any time step.
  `kind="daily"` means one value per day, placed at noon as ORCHIDEE does; `kind="subdaily"` means N-hourly samples
  interpolated from their own time stamps. Both are interpolated to ORCHIDEE's 30-minute step before the rules are
  applied. ERA5 GRIB1 files with parameters 165/166/134 are read directly (`reader="grib1_era5"`). A land mask
  (variable of the forcing or separate file) and, for the forest cells, a raster on the forcing grid counting forest
  pixels. Optional: daily maximum gust files (`gust`) for the gust rule.
- **Validation sets** (`VALIDATION`):
  - reported damage: a JSON list of batches `{key, storms: [{storm, date, reports: [{id, country, nuts_id or lat/lon/radius_km, region_name, damage_level, source_type, source_title, source_url}]}], verdicts: [{id, storm, verdict, corrected_nuts_id, corrected_damage_level}]}` and the NUTS 2021 GeoJSON files (levels 2 and 3);
  - damage polygons: a shapefile with storm name, country, event date and area fields (FORWIND v2);
  - lon/lat boxes per storm, in the storm catalogue;
  - an annual disturbance raster on the forcing grid (EFDA agent 1), one file per year.
- **Storm catalogue** (`STORMS`): id, label, date, and for each event the keys under which the sources know it.
  Several events can be shown as one storm (`members`).
- **ORCHIDEE runs** (`ORCHIDEE`, `DAMAGE`, `DDAMAGE`): archived outputs `storm_daily` (daily) and `stomate_history`
  (monthly) of runs on the main forcing.
- **Regions** (`REGIONS`): a CSV of 1° cells with a region name, grouped into a few regions for the protocol.
- **Tracks and base map**: XWS track CSV files, ERA5 mean sea-level pressure files per storm, Natural Earth
  shapefiles — all optional.

## Reading the numbers honestly

- **Equal onset rate, not equal optimum.** Each rule is shown at the setting that gives the same background
  number of onsets per cell and decade. Detection differences are then differences of skill, not of trigger
  frequency. The AND rule has three thresholds; at each rate its combination is the one that detects most
  *reported* damage — a choice that uses the validation set and favours that rule.
- **Reported is not observed.** An unreported cell is not necessarily undamaged; large administrative regions
  (Nordic counties) mark whole cells from one report. FORWIND covers about 30 % of damaging events: a detected
  cell without a polygon is *not confirmed*, not a false alarm.
- **The disturbance raster merges agents** (EFDA agent 1 = wind and bark beetle) and its year runs from summer to
  summer: a storm from July on is looked up in the next year.
- **Grids differ.** A finer grid has more, smaller cells under each storm and a cell's onset rate counts events in a
  smaller area: detection shares compare across grids, onset rates only roughly.
- **The offline replay is the model's input, not the model.** It reproduces about 99 % of the storm ends of an
  ORCHIDEE run because it uses the forcing as the model sees it; where runs exist, the page shows the model's own
  storm states.
- **Detection × Damage is an approximation**: thresholds can only be tightened, and removing a damage episode does not
  change the stands it would have damaged. Confirm the chosen setting with a run.
- **Volumes**: the model counts above-ground stem wood, DFDE merchantable volume; a daily forcing misses storms whose
  peak winds last only hours.

## Licence and credits

CeCILL v2.1 (see `LICENSE`), © Guillaume Marie, Science-Partners. Data sources to cite when publishing results:
ISIMIP3 (GSWP3-W5E5), EURO-CORDEX, ERA5 (Copernicus Climate Change Service), FORWIND v2 (Forzieri et al. 2020),
EFDA (European Forest Disturbance Atlas), DFDE (Patacca et al. 2023), XWS (Roberts et al. 2014), NUTS 2021
(Eurostat/GISCO), Natural Earth.
