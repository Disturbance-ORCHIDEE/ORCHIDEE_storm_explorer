"""Storm Detection Explorer -- THE ONLY FILE TO EDIT.

Everything the build reads (input paths, forcings, storms, rules, ORCHIDEE runs) and everything the page says (title, labels,
notes) is set here. Paths may contain {year}, {run}, {storm} or {name} where stated. A missing input is skipped with a
warning: the page is built with what is there (a forcing without gust files has no gust rule, no ORCHIDEE run means no
Damage tabs, and so on).
The values below are those of the D5.2 storm work on ISIMIP, EURO-CORDEX and ERA5 (Science-Partners / LSCE).
"""
import datetime as _dt

# ------------------------------------------------------------------------------------------------ page and output
TITLE = "Storm Detection Explorer"
INTRO = ("Which ORCHIDEE storm-onset rule switches cells to <code>is_storm</code> where storms actually struck? Three rules, "
         "compared at the <b>same onset rate</b>: the original AND rule, the peak rule on the forcing wind, and the peak rule on "
         "the ERA5 daily maximum gust. Pick a storm, a validation set and a forcing.")
OUTPUT_HTML = "storm_explorer.html"
OUTPUT_DATA = "storm_explorer_data.js"     # intermediate, rebuilt by build_data.py
CACHE_DIR = "cache"                         # preprocessed forcing (can be large for hourly forcings: ~10 GB for ERA5 0.25 deg)
NPROC = 12                                  # processes for the forcing preprocessing and the equal-rate replays

# ------------------------------------------------------------------------------------------------ domain and timing
BOX = (-12, 33, 34, 72)        # lon min, lon max, lat min, lat max (deg)
FIRST_YEAR = 1990              # scores and onset rates from this year on; earlier years fill the rule's 5-year references
STORM_WINDOW = (-2, 3)         # a cell is detected if in storm state from date-2 to date+3 days
CALM_DAYS = 5                  # a cell leaves storm state after 5 calm days (as in ORCHIDEE)
LEVELS = [round(0.5 + 0.1 * i, 2) for i in range(26)]   # onset rates of the slider (onsets per cell and decade)

# forest cells: forest pixel count raster (one pixel per forcing cell) x pixel_ha >= min_ha_per_deg2 x res^2
FOREST = dict(pixel_ha=0.09, min_ha_per_deg2=1e4)

# ------------------------------------------------------------------------------------------------ forcings
# kind 'daily' (one value a day, placed at noon) or 'subdaily' (N-hourly, interpolated from its time stamps).
# The FIRST forcing is the main one: it carries the ORCHIDEE runs and the Damage tabs.
EFDA = "/scratch/gmarie/EFDA"
FORCINGS = [
    dict(id="isimip", label="ISIMIP obsclim 1°", short="ISIMIP 1°", colour_var="--fc-isimip",
         note="ISIMIP obsclim (GSWP3-W5E5), 1° daily, 1984-2018; ORCHIDEE bench runs available.",
         kind="daily", res=1.0, years=(1984, 2018),
         files="/data/gmarie/DATA/SRF/METEO/ISIMIP3B.v2/onedeg/obsclim/gswp3-w5e5/gswp3-w5e5_historical_onedeg_{year}.nc",
         wind="Wind", pressure="PSurf", lon="longitude", lat="latitude", land=dict(var="contfrac"),
         forest_raster=f"{EFDA}/Europe_1deg_v2/forest_pixels_europe.tif", raster_dir=f"{EFDA}/Europe_1deg_v2",
         gust=dict(files="/data/gmarie/ERA5/gust_daymax/1/gust_daymax_1_{year}.nc", var="gust_max", regrid="nearest"),
         and_ratios=[1.2, 1.4, 1.6, 1.8, 2.0, 2.3],
         rank=dict(peak=(1.25,), gust=(1.30,), **{"and": (2.3, 96.0, 8.0)})),
    dict(id="cordex05", label="EURO-CORDEX 0.5°", short="EURO-CORDEX 0.5°", colour_var="--fc-cordex",
         note="SMHI-RCA4 driven by ERA-Interim (evaluation), 3-hourly",
         kind="subdaily", reader="netcdf", res=0.5, years=(1984, 2011), preprocess_from=1979,
         files="/data/gmarie/DATA/SRF/METEO/EUROCORDEX/evaluation/ECMWF-ERAINT/EUR-11_ECMWF-ERAINT_evaluation_r1i1p1_SMHI-RCA4_v1_3hr_0p5_{year}.nc",
         time="time", wind="Wind", pressure="PSurf", lon="lon", lat="lat",
         land=dict(file="/data/gmarie/DATA/SRF/METEO/EUROCORDEX/evaluation/ECMWF-ERAINT/EUR-11_ECMWF-ERAINT_evaluation_r1i1p1_SMHI-RCA4_v1_3hr_0p5_2005.nc",
                   var="Contfrac"),
         forest_raster=f"{EFDA}/Europe_0p5degC_v2/forest_pixels_europe.tif", raster_dir=f"{EFDA}/Europe_0p5degC_v2",
         gust=dict(files="/data/gmarie/ERA5/gust_daymax/0p25/gust_daymax_0p25_{year}.nc", var="gust_max", regrid="max"),
         and_ratios=[1.2, 1.4, 1.6, 1.8, 2.0, 2.3, 2.6, 3.0, 3.5],
         rank=dict(peak="protocol", gust=(1.30,), **{"and": "protocol"})),
    dict(id="era5025", label="ERA5 0.25°", short="ERA5 0.25°", colour_var="--fc-era5",
         note="ERA5 hourly 10 m wind and surface pressure",
         kind="subdaily", reader="grib1_era5", res=0.25, years=(1984, 2018),
         files="/data/gmarie/ERA5/{year}/data.grib",
         land=dict(file="/data/gmarie/ERA5/land_sea_mask_0p25.nc", var="lsm", lat="latitude", lon="longitude", threshold=0.5),
         forest_raster=f"{EFDA}/Europe_0p25degC_v2/forest_pixels_europe.tif", raster_dir=f"{EFDA}/Europe_0p25degC_v2",
         gust=dict(files="/data/gmarie/ERA5/gust_daymax/0p25/gust_daymax_0p25_{year}.nc", var="gust_max", regrid="max"),
         and_ratios=[1.2, 1.4, 1.6, 1.8, 2.0, 2.3, 2.6, 3.0, 3.5],
         rank=dict(peak="protocol", gust=(1.30,), **{"and": "protocol"})),
]

# ------------------------------------------------------------------------------------------------ rules
# id: and | peak | gust (gust needs the forcing's gust files). 'fmt' formats a setting for the page.
RULES = [
    {"id": "and", "name": "Original AND rule", "short": "AND", "colour_var": "--c-and", "dash": [2, 3],
     "fmt": "ratio > {0}, sum ≥ {1:.0f}, 3-day max ≥ {2:.1f} m/s", "fmt_short": "r > {0}, S ≥ {1:.0f}, V ≥ {2:.1f}"},
    {"id": "peak", "name": "Peak rule", "short": "Peak, forcing wind", "colour_var": "--c-peak", "dash": [7, 4],
     "fmt": "X* ≥ {0:.3f}", "fmt_short": "X* ≥ {0:.3f}"},
    {"id": "gust", "name": "Peak rule, ERA5 gust", "short": "Peak, ERA5 gust", "colour_var": "--c-gust", "dash": [],
     "fmt": "X* ≥ {0:.3f}", "fmt_short": "X* ≥ {0:.3f}"},
]
# equal-rate scans: X* on np.arange(*X); AND: S(L) interpolated from np.geomspace(*S) for each (ratio, V)
RULE_SCAN = {"peak": {"X": (1.0, 2.2001, 0.005)}, "gust": {"X": (1.0, 2.2001, 0.005)},
             "and": {"S": (12, 4000, 32), "V": [5.0, 6.0, 7.0, 7.8, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0]}}
RATIO_THRESHOLDS = [1.2, 1.4, 1.6, 1.8, 2.0, 2.3, 2.6, 3.0, 3.5]   # every ratio any rule setting uses

# scoring protocol (Peirce skill score, leave one region out): rank setting of 'protocol' forcings, header note, quiet seasons
PROTOCOL_SCAN = {"X": [round(1.0 + 0.025 * i, 3) for i in range(33)], "S": [48, 96, 150, 190, 250, 350, 500],
                 "V": [5.0, 6.0, 7.0, 7.8, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0]}
PROTOCOL_CURRENT = {"peak": (1.30,), "gust": (1.30,), "and": (1.2, 350, 8.0)}   # tie-break: closest to these
REGIONS = dict(file="/scratch/gmarie/postprocess/cell_regions.csv",             # lon, lat (1 deg centres), region
               groups={"Boreal": "North", "Arctic": "North", "Atlantic": "West", "Continental": "Central", "Alpine": "Central",
                       "Pannonian": "Central", "Mediterranean": "South", "Steppic": "South", "BlackSea": "South",
                       "Anatolian": "South"},
               names=["North", "West", "Central", "South"])

# ------------------------------------------------------------------------------------------------ validation sets
VALIDATION = dict(
    reports=dict(file="/scratch/gmarie/obs/storm_damage_reports/workflow_result_wf_a43d897a-945.json",
                 regions_dir="/scratch/gmarie/obs/nuts", f_cell=0.10, f_poly=0.50, strict=False),
    polygons=dict(file="/scratch/gmarie/FORWIND/FORWIND_v2.shp", min_polygons_per_deg2=5, min_forest_pct=1.0),
    raster=dict(name="EFDA", pattern="agent1_pixels_{year}.tif", years=(1985, 2023), pixel_ha=0.09,
                factor=3.0, min_share=0.005, next_year_from_month=7),
)
# how the page names each set; 'out' = label of a detected cell outside the set
VSETS = [
    {"id": "rep", "name": "Reported damage (literature, agencies, press)", "short": "Reported damage", "out": "no verified report"},
    {"id": "fw5", "name": "FORWIND ≥ 5 polygons", "short": "FORWIND ≥ 5", "out": "not confirmed"},
    {"id": "fw1", "name": "FORWIND ≥ 1 % forest", "short": "FORWIND ≥ 1 %", "out": "not confirmed"},
    {"id": "ifn", "name": "IFN 2003 regions", "short": "IFN 2003", "out": "outside the regions"},
    {"id": "efda", "name": "EFDA agent 1 (annual)", "short": "EFDA agent-1 anomaly", "out": "outside anomaly"},
]
FORCING_TAB_VSETS = ["rep", "efda"]           # sets offered in the Forcings tab

# ------------------------------------------------------------------------------------------------ storm catalogue
# id, label, date; members = the events shown as this storm (several for a merged storm), each with its own date and its keys
# in the sources: reports (storm names in the reports file), polygons ((name, country, date or None) in the polygon file),
# boxes ({region: (lon0, lon1, lat0, lat1)}), xws (published track names).
def _s(sid, label, date, **m):
    return {"id": sid, "label": label, "date": date, "members": [dict(date=date, **m)]}


IFN_LOTHAR = {"Lorraine": (5, 7.5, 48, 50), "Champagne-Ardenne": (3.5, 5.5, 47.5, 50)}
IFN_MARTIN = {"Aquitaine": (-2, 1, 43, 46), "Poitou-Charentes": (-1.5, 1, 45.5, 47)}
STORMS = [
    _s("vivian", "Vivian-Wiebke 1990", "1990-02-27", xws=["Vivian"],
       reports=["1990 storm series: Vivian (26-27 Feb) and Wiebke (28 Feb-1 Mar), with Daria (25 Jan) and Herta (3 Feb)"]),
    {"id": "lothar_martin", "label": "Lothar + Martin", "date": "1999-12-26", "members": [
        dict(date="1999-12-26", reports=["Lothar"], boxes=IFN_LOTHAR, xws=["Lothar"]),
        dict(date="1999-12-27", reports=["Martin"], boxes=IFN_MARTIN, xws=["Martin"])]},
    _s("pyry", "Pyry-Janika 2001", "2001-11-15", reports=["Pyry and Janika (November 2001 storms)"]),
    _s("jeanett", "Jeanett", "2002-10-27", xws=["Jeanette"], reports=["Jeanett (October 2002 windstorm, CZ)"]),
    _s("uschi", "Uschi (foehn)", "2002-11-16", reports=["Uschi (föhn storm, Alps)"]),
    _s("tatra", "Tatra (SK)", "2004-11-19", reports=["Tatra bora windstorm (SK/PL)"], polygons=[("unknown", "SK", "2004-11-19")]),
    _s("gudrun", "Gudrun", "2005-01-08", xws=["Erwin_Gudrun"], reports=["Gudrun (Erwin)"], polygons=[("Gudrun", "SE", None)]),
    _s("per", "Per", "2007-01-14", reports=["Per (January storm 2007)"]),
    _s("kyrill", "Kyrill", "2007-01-18", xws=["Kyrill"], reports=["Kyrill"], polygons=[("Kyrill", "DE", None), ("Kyrill", "CZ", None)]),
    _s("paula", "Paula", "2008-01-26", reports=["Paula"]),
    _s("emma", "Emma", "2008-03-01", xws=["Emma"], reports=["Emma"]),
    _s("klaus", "Klaus", "2009-01-24", xws=["Klaus"], reports=["Klaus"], polygons=[("Klaus", "FR", None)]),
    _s("xynthia", "Xynthia", "2010-02-28", xws=["Xynthia"], reports=["Xynthia"], polygons=[("Xhynthia", "FR", None)]),
    _s("asta", "Asta (summer 2010)", "2010-07-30", reports=["Asta (with Veera, Lahja, Sylvi) summer derecho series 2010"]),
    _s("joachim", "Joachim", "2011-12-16", xws=["u20111216"], reports=["Joachim"]),
    _s("dagmar", "Dagmar", "2011-12-26", xws=["Dagmar_Patrick"], reports=["Dagmar (Tapani in Finland, with Hannu)"]),
    _s("christian", "Christian", "2013-10-28", reports=["Christian (St Jude, Allan, Simone)"]),
    _s("hilde", "Hilde", "2013-11-16", reports=["Hilde (Eino in Finland)"]),
    _s("xaver", "Xaver", "2013-12-05", reports=["Xaver (Bodil, Sven)"]),
    _s("ivar", "Ivar", "2013-12-13", reports=["Ivar"]),
    _s("pl2013", "Poland 24 Dec 2013", "2013-12-24", reports=["Poland/Baltic storm of 24 Dec 2013 (Dirk)"],
       polygons=[("unknown", "PL", "2013-12-24")]),
    _s("darwin", "Darwin (IE)", "2014-02-12", reports=["Darwin (Tini) Ireland"], polygons=[("unknown", "IR", "2014-02-12")]),
    _s("zofia", "Zofia (SK)", "2014-05-14", reports=["Zofia/Yvette (SK, PL, CZ)"], polygons=[("Zofia", "SK", None)]),
    _s("egon", "Egon", "2015-01-10", reports=["Egon"]),
    _s("tuscany", "Tuscany Mar 2015", "2015-03-05", reports=["Tuscany/central Italy foehn windstorm"],
       polygons=[("unknown", "IT", "2015-03-05")]),
    _s("niklas", "Niklas", "2015-03-31", reports=["Niklas"]),
    _s("gorm", "Gorm", "2015-11-29", reports=["Gorm"]),
    _s("pl2017", "Poland derecho Aug 2017", "2017-08-11", reports=["Poland derecho of 11-12 August 2017"]),
    _s("xavier", "Xavier", "2017-10-05", reports=["Xavier"], polygons=[("Xavier", "DE", None), ("unknown", "DE", "2017-11-10")]),
    _s("herwart", "Herwart", "2017-10-29", reports=["Herwart (Grzegorz in PL)"]),
    _s("burglind", "Burglind", "2018-01-03", reports=["Burglind (Eleanor)"]),
    _s("friederike", "Friederike", "2018-01-18", reports=["Friederike (David)"], polygons=[("Friederike", "DE", None)]),
    _s("vaia", "Vaia", "2018-10-29", reports=["Vaia (Adrian)"], polygons=[("Vaia", "IT", None), ("Vaia", "AU", None)]),
]
DEFAULT_STORM = "kyrill"
CONVECTIVE = {"asta", "pl2017"}               # summer convective events: excluded from the protocol and the volume test

TRACKS = dict(published="/scratch/gmarie/XWS/{name}_track.csv",
              tracked="/data/gmarie/ERA5/storm_tracks_mslp/{storm}_*.nc", default_seed=(5.0, 50.0))
BASEMAP = dict(land="/home/gmarie/.local/share/cartopy/shapefiles/natural_earth/physical/ne_50m_land.shp",
               borders="/home/gmarie/.local/share/cartopy/shapefiles/natural_earth/cultural/ne_50m_admin_0_boundary_lines_land.shp")

# ------------------------------------------------------------------------------------------------ ORCHIDEE runs (main forcing)
_A = "/scratch/gmarie/IGCM_OUT/OL2/PROD/aedspinup"
ORCHIDEE = dict(
    daily=_A + "/{run}/SBG/Output/DA/{run}_{year}0101_{year}1231_1D_storm_daily.nc",
    monthly=_A + "/{run}/SBG/Output/MO/{run}_{year}0101_{year}1231_1M_stomate_history.nc",
    # storm states of the model, per rule: run, years, the run's own setting (replayed to rebuild the states)
    detection_runs={"and": dict(run="i1dmand", years=(1990, 2018), replay=(1.2, 350.0, 8.0),
                                setting="ratio > 1.2, sum >= 350, 3-day max >= 8 m/s"),
                    "peak": dict(run="i1dmpk", years=(1990, 2018), replay=(1.30,), setting="X >= 1.30")},
)

DAMAGE = dict(
    years=(1990, 2018), window=(-2, 40),
    runs=[dict(rule="and", run="i1dmand", name="Original AND rule and law", colour_var="--c-and", standing_volume=True,
               setting="i1dmand: ratio > 1.2, sum >= 350, 3-day max >= 8 m/s; original law, tune 1.45"),
          dict(rule="peak", run="i1kf225", name="Peak rule, current law", colour_var="--c-peak",
               setting="i1kf225: X >= 1.25; area-weighted kill, tune 2.25"),
          dict(rule="gust", run="i1gd95", name="ERA5 gust, dose law", colour_var="--c-gust",
               setting="i1gd95: X >= 1.30 on the ERA5 gust; gust-dose law")],
    countries=dict(mask="/scratch/gmarie/obs/safenet/country_mask.nc", codes="/scratch/gmarie/obs/safenet/country_codes.csv"),
    reference=dict(name="DFDE", file="/scratch/gmarie/EFDA/dfde_patacca.xlsx",
                   agents={"Wind": "wind", "Bark Beetles": "beetle", "Fire": "fire"},
                   aliases={"Czechia": "Czech Republic", "Bosnia & Herzegovina": "Bosnia and Herzegovina"}),
    agent_labels={"wind": ("Wind", "Wind"), "beetle": ("Bark beetle", "Bark Beetles"), "fire": ("Fire", "Fire")},
    europe_label="Europe (DFDE countries)",
)

DDAMAGE = dict(
    years=(1995, 2010), window=(-2, 40), min_event_m3=1e6, reference_name="DFDE",
    held_out=[("France", 1999), ("Sweden", 2005), ("France", 2009)],
    versions={
        "peak_kf": dict(label="Peak rule (ISIMIP 1°), new kill (area-weighted)", rule="peak",
                        runs={2.25: "i1kf225", 2.81: "i1kf281", 3.52: "i1kf352", 4.39: "i1kf439", 5.49: "i1kf549"},
                        params={"X": [round(1.25 + 0.025 * i, 3) for i in range(15)]}, base="X >= 1.25"),
        "peak": dict(label="Peak rule (ISIMIP 1°), old kill", rule="peak", runs={1.45: "i1dmpk"},
                     params={"X": [round(1.30 + 0.025 * i, 3) for i in range(13)]}, base="X >= 1.30"),
        "and": dict(label="Original AND rule (ISIMIP 1°), old kill", rule="and", runs={1.45: "i1dmand"},
                    params={"S": [350, 400, 450, 500, 600, 700, 850, 1000], "V": [round(11.6 + 0.6 * i, 3) for i in range(15)]},
                    base="ratio > 1.2, sum >= 350, wind x tune >= 11.6"),
        "gust": dict(label="Peak rule on the ERA5 gust, gust-dose law", rule="peak", runs={"dose law": "i1gd95"},
                     params={"X": [round(1.30 + 0.025 * i, 3) for i in range(13)]}, base="X >= 1.30 on the gust"),
    },
)

# ------------------------------------------------------------------------------------------------ notes shown under each tab
NOTES = {
    "detection": [
        "<b>Detected</b>: the cell is in storm state at least once within &minus;2 to +3 days of the storm date. <b>Rank</b>: rank of "
        "the strongest episode in that window among the cell's episodes since {first_year} (peaks at least 5 days apart), each rule "
        "on its own metric. A storm ranked 1st is the strongest event of the period in that cell.",
        "<b>ORCHIDEE (bench runs)</b>, the default where runs exist: the storm states the model actually produced (one run per rule, "
        "at the run's setting shown on each map). Each replay episode is kept only if the model ended a storm in that cell within "
        "one day of the episode's end (<code>IS_KILL_STORM</code>); model storm ends without a matching episode get the six days "
        "before the end. Background = model storm ends per cell and decade. A rule without a run shows the offline replay. "
        "<b>Offline replay</b> uses the wind and pressure ORCHIDEE sees (daily forcing placed at noon and interpolated to 30 min).",
        "<b>One slider, one onset rate</b>: the rules are always shown at the same background rate, from 0.5 to 3.0 onsets per cell "
        "and decade. For each rate and forcing, each rule's parameters were replayed in advance so that the rule fires exactly that "
        "often (peak rules: one threshold X*; AND rule: the ratio, sum and maximum combination that detects most reported damage at "
        "that rate, a choice that favours it). Each map shows the setting used. At equal rate the false alarms are about equal and "
        "the detections compare skill. The rank colour uses the rule's rank metric.",
        "<b>Onsets per decade</b> is each rule's background trigger rate: how many times a cell switches from calm to storm state, "
        "true storms included, per decade. It uses no observation. <b>Reference &asymp; 0.9</b> damaging storms per cell and decade "
        "(named storms of 1991-2015 on the calibration cells, a lower bound). Colour code: <span class=\"pill under\">&lt; 0.9 "
        "under-triggers</span> <span class=\"pill ok\">0.9&ndash;2 plausible</span> <span class=\"pill over\">&gt; 2 over-triggers</span>.",
        "<b>Reported damage</b>: forest wind damage reported for each storm across Europe (peer-reviewed papers, forest-agency and "
        "inventory reports, national and local press), each report with its source and checked by a verifier. A forest cell counts "
        "when a verified major or moderate report's NUTS region covers at least 10 % of the cell or lies at least 50 % inside it. "
        "Reported, not observed: an unreported cell is not necessarily undamaged, and large Nordic counties mark whole cells from a "
        "single report. <b>FORWIND v2</b> (Forzieri et al. 2020): polygons of wind damage, about 30 % of damaging events 2000-2018; a "
        "detected cell without polygons is <i>not confirmed</i>, not a false alarm. <b>IFN 2003</b>: French regions with about 10 % "
        "of standing volume felled, as lon/lat boxes. <b>EFDA agent 1</b>: Landsat stand-replacing disturbance anomaly (wind and bark "
        "beetle merged) in the storm's EFDA year; a storm from July on is looked up in the following year.",
        "<b>Forcing menu</b>: every test redone on each forcing with the same rules, windows, validation sets and protocol; each "
        "forcing has its own settings for each onset rate. Sub-daily forcings are read as ORCHIDEE would see them (interpolated to 30 "
        "minutes), so they keep the storm peaks a daily forcing smooths out. On a finer grid the forest threshold scales with the "
        "cell area, reported damage is re-projected with the same rule and the FORWIND polygon threshold scales with the cell area.",
        "<b>Peak rule on the ERA5 gust</b>: same rule and X formula, but the day's peak is the daily maximum of the ERA5 10 m gust, "
        "regridded to the forcing cells by maximum. The daily mean wind dilutes storms whose peak lasts a few hours; the gust keeps it.",
        "<b>Storm track</b>: solid line = published XWS track (Roberts et al. 2014); dashed line = sea-level pressure minimum followed "
        "in ERA5 (6-hourly, 1&deg;). Display aid only; it fails when the damage comes from a secondary wave of the parent low.",
    ],
    "damage": [
        "<b>ORCHIDEE simulations</b> on the main forcing, one per rule: see the run and its setting in the table header.",
        "<b>Felled volume</b> of a cell = sum over plant types of <code>WIND_DAMAGE_WOODVOL</code> &times; <code>VEGET_MAX</code> "
        "&times; cell land area; <b>% of standing volume</b> divides by the cell's standing stem volume (<code>WOOD_VOL</code>). A dot "
        "marks a cell where the model ended a storm in the window. Outlined cells carry reported forest damage for that storm.",
        "<b>Other agents</b> (annual chart only): bark beetle = <code>Beetle_damage_woodvol</code> against DFDE &ldquo;Bark Beetles&rdquo;; "
        "fire = wood volume of the burnt stands (<code>AREA_BURNT_PFT</code> &times; <code>WOOD_VOL</code>), an upper bound, against "
        "DFDE &ldquo;Fire&rdquo;.",
        "<b>DFDE status</b> (strip under the annual chart): <i>Reported</i>: a national value exists (zero included). <i>No damage</i>: "
        "nothing reported but the national series is judged complete. <i>Gap-filled</i>: the year was estimated. <i>No national "
        "data</i>: expert estimate. Estimated bars are hatched; for Europe a year takes the least certain status of its countries.",
        "<b>Reading the numbers</b>: the model counts stem wood above ground, DFDE merchantable volume, and a daily forcing misses "
        "storms whose peak winds last only hours.",
    ],
    "ddamage": [
        "<b>Purpose</b>: choose the detection setting and <code>DAILY_MAX_TUNE</code> together. A setting can match the felled volume "
        "of the big storms and still disturb far too much forest over decades, or damage stands where no storm occurred.",
        "<b>Method</b>: no new simulation. Each damage episode of the archived run (from one storm end to the next in a cell) is kept "
        "only if one of its days passes the stricter thresholds, read in the daily output: peak X (<code>STORM_PEAK_RATIO</code>), wind "
        "sum S (<code>WIND_SUM</code>) and model wind V (<code>DAILY_MAX_WIND_MOD</code>). Thresholds can only be tightened, and "
        "removing an episode does not change the stands it would have damaged: an approximation, to be confirmed by a run.",
        "<b>Volume</b>: median of model / DFDE wind volume on the calibration storms; the held-out events are listed apart. "
        "<b>Area</b>: model <code>AREA_DAMAGED_STORM</code> + <code>AREA_DAMAGED_PEST</code> against EFDA agent 1 (wind and bark beetle "
        "merged). <b>Outside storms</b>: share of the storm-damaged area in cell-seasons with no catalogued storm and no EFDA anomaly.",
    ],
    "forcings": [
        "Each forcing is scored on its own grid at the same onset rate for every rule. 'Common' keeps the storms present on every "
        "forcing (a forcing ending earlier drops the later storms).",
    ],
}
