# ERA5-Land Precipitation Prediction with XAI

Precipitation prediction from ERA5-Land reanalysis data, with a focus on
explainable (XAI) modelling.

**Authors**

- Osmary Camila Bortoncello Glober
- Vitor Gabriel Pignatari 
- Israel Matias
- Anderson Ara

## Data

The dataset is stored outside this repository, on an external drive.

ERA5-Land is the land-surface component of the ERA5 reanalysis, produced by
ECMWF. It is available hourly on a regular 0.1° × 0.1° grid (~9 km), over land
points only, from 1950 to present. Our subset covers **1980-01 to 2025-12** over
South America (6°N–35°S, 75°W–30°W; 411 × 451 grid points).

### Raw data

```
/media/mary-camila/Expansion/era5land/raw/
├── pev/    pev_YYYY_MM.nc     pev       — potential evaporation
├── ssrd/   ssrd_YYYY_MM.nc    ssrd      — surface solar radiation downwards
├── temp/   temp_YYYY_MM.nc    t2m, d2m  — 2 m temperature and dewpoint
├── tp/     tp_YYYY_MM.nc      tp        — total precipitation (target)
└── wind/   wind_YYYY_MM.nc    u10, v10  — 10 m wind components
```

One NetCDF file per group per month, hourly, covering 1980-01 to 2025-12
(552 files per folder, ~597 GB in total). Note that the `temp` and `wind` files
each contain **two** variables.

| Folder | Variable(s) | ECMWF name | Units | Type |
|--------|-------------|------------|-------|------|
| `tp`   | `tp`         | Total precipitation | m | accumulated |
| `pev`  | `pev`        | Potential evaporation | m | accumulated |
| `ssrd` | `ssrd`       | Surface solar radiation downwards | J m⁻² | accumulated |
| `temp` | `t2m`, `d2m` | 2 m temperature, 2 m dewpoint temperature | K | instantaneous |
| `wind` | `u10`, `v10` | 10 m u- and v-component of wind | m s⁻¹ | instantaneous |

#### `tp` — Total precipitation

Accumulated liquid + frozen water (rain + snow) that falls to the Earth's
surface, expressed as a **depth of water in metres**. It is the sum of
large-scale and convective precipitation, and does not include fog, dew or
precipitation that evaporates before reaching the ground.

This is the **prediction target** of the project. Multiply by 1000 to obtain
millimetres, the usual unit in hydrology.

#### `pev` — Potential evaporation

An indication of the maximum evaporation that *would* occur if water were not
limiting — i.e. the atmospheric demand for water, in **metres** (the CDS
variable table lists `pev` as `m`, not `m of water equivalent`).

In the general ECMWF model, `pev` comes from a second call to the surface energy
balance with vegetation set to "crops/mixed farming" and no soil-moisture
stress. **ERA5-Land overrides this**: here `pev` is an open-water (pan)
evaporation. Both assume the atmosphere is unaffected by the artificial surface
condition, which ECMWF note "may not always be realistic".

Sign convention: ECMWF treats downward fluxes as positive, so evaporation
appears as **negative** values. **Negate it** (`-pev`) to get a positive
water-demand predictor — do *not* use `abs()`. A small fraction of values is
genuinely positive (0.1% of land cells in a sample month), meaning the
potential flux is downward, i.e. condensation/dew rather than evaporation;
`abs()` would silently flip those into demand.

Magnitude caveat: in ERA5-Land `pev` is computed as an **open-water (pan)
evaporation** — which is *different from how ERA5 computes it* — and it is not
FAO-56 reference evapotranspiration. ECMWF warn that the method "can give
unrealistic results in arid conditions due to too strong evaporation forced by
dry air". It runs ~9.6 mm/day on average over this domain (~3500 mm/year), well
above reference ET. Use it as a relative atmospheric-demand index; do not
compare it with reference-ET products or put it in a water balance expecting
realistic ET.

Like `tp` and `ssrd`, `pev` is **accumulated** from the start of the forecast to
the end of the step, so it takes the same last-step-of-day aggregation.

Together with `tp` it gives a simple water-balance / aridity signal
(`tp` + `pev`, since `pev` is already negative), often a strong feature for
precipitation modelling.

#### `ssrd` — Surface solar radiation downwards

Shortwave (solar) radiation reaching the surface, both direct and diffuse,
after being modified by the atmosphere — mainly by clouds. Accumulated energy
per unit area, in **J m⁻²**.

Per ECMWF, "the accumulated values should be divided by the accumulation
period expressed in seconds" to convert to W m⁻² — so divide by the **length of
the accumulation window**, not by a fixed 3600. Because the raw values
accumulate from 00 UTC (see
[Accumulated vs. instantaneous](#accumulated-vs-instantaneous)), a raw value is
*not* a one-hour accumulation, and dividing it by 3600 gives nonsense: at the
00 UTC end-of-day step it yields ~7000 W m⁻², five times the solar constant.

| Value | To W m⁻² |
|-------|----------|
| raw hourly, after `.diff('valid_time')` | ÷ 3600 |
| `processed_daily` (daily total) | ÷ 86400 |
| `processed_weekly` (weekly total) | ÷ 604800 |

Low `ssrd` relative to the clear-sky maximum is effectively a cloud-cover proxy,
which is why it is informative for precipitation.

To a good approximation `ssrd` is the model equivalent of a **pyranometer**
reading, which makes it the natural field to validate against station data — but
ECMWF caution that observations are local in space and time, whereas this is an
average over a ~9 km grid box and a model time step.

Not to be confused with **surface net solar radiation** (`ssr`), a separate CDS
variable whose description differs by "minus the amount reflected by the Earth's
surface". `ssr` has albedo folded in and is a weaker cloud proxy; this project
uses the downward flux `ssrd`.

#### `t2m` — 2 metre temperature

Air temperature at 2 m above the surface, in **kelvin**. Computed by
interpolating between the lowest model level and the surface, accounting for
atmospheric stability. Subtract 273.15 for °C.

#### `d2m` — 2 metre dewpoint temperature

The temperature to which the air at 2 m would have to be cooled, at constant
pressure and humidity, for saturation to occur. Also in **kelvin**.

Combined with `t2m` it gives the humidity of the near-surface air: the dewpoint
depression (`t2m` − `d2m`) approaches zero when the air is saturated, and
relative or specific humidity can be derived from the pair. Moisture
availability is a direct physical precursor of precipitation, so this pair is
usually more informative than `t2m` alone.

#### `u10`, `v10` — 10 metre wind components

Horizontal wind at 10 m above the surface, in **m s⁻¹**.

- `u10` — eastward component (positive = wind blowing towards the east)
- `v10` — northward component (positive = wind blowing towards the north)

Usually converted to speed and direction:

```python
speed = np.sqrt(u10**2 + v10**2)
direction = (270 - np.degrees(np.arctan2(v10, u10))) % 360  # meteorological
```

Wind direction carries the moisture-transport signal (which air mass is
arriving), so keep `u10`/`v10` as components — or speed plus the sine and cosine
of direction — rather than feeding a raw direction in degrees to a model.

### Processed data

Raw files are aggregated to a **daily** resolution and written to:

```
/media/mary-camila/Expansion/era5land/processed_daily/
├── pev/
├── ssrd/
├── temp/
├── tp/
└── wind/
```

The folder structure and file naming mirror the raw data, so any raw path maps
to its processed counterpart by swapping `raw` for `processed_daily`.

Generated by `scripts/processing/daily_aggregation.py` (see
[How to run](#how-to-run)).

The daily files are in turn aggregated to **weekly** ones in
`processed_weekly/`, described under
[Weekly aggregation](#weekly-aggregation) below.

#### Accumulated vs. instantaneous

This distinction determines how each variable must be aggregated to daily
values.

**Instantaneous** variables (`t2m`, `d2m`, `u10`, `v10`) are snapshots valid at
the timestamp. Daily aggregation is a plain **mean** (min/max are also
meaningful for `t2m`).

**Accumulated** variables (`tp`, `pev`, `ssrd`) are accumulated **from 00 UTC of
the same day**, not over the preceding hour. The value at 06 UTC is therefore
the total for 00–06 UTC, and values grow through the day before resetting.
Consequences:

- **Summing the 24 hourly values badly overcounts.** The daily total is the
  accumulation of the *last* step of the day — i.e. the value stamped 00 UTC of
  the *following* day.
- To recover true hourly rates, difference consecutive steps within the day
  (`x.diff('valid_time')`), keeping the 01 UTC value as-is since it starts the
  accumulation.
- Because the accumulation window is fixed to UTC days, the resulting "day" is a
  UTC day. For a region far from the Greenwich meridian, consider whether a
  local-time definition of the day matters for the analysis.

Aggregation rule per file:

| File | Variable(s) | Daily aggregation |
|------|-------------|-------------------|
| `tp`   | `tp`         | last accumulated step of the day (00 UTC of the next day) |
| `pev`  | `pev`        | last accumulated step of the day |
| `ssrd` | `ssrd`       | last accumulated step of the day |
| `temp` | `t2m`, `d2m` | mean, plus `t2m_min` and `t2m_max` |
| `wind` | `u10`, `v10` | mean |

The daily total of the last day of a month is read from the first timestep of
the next month's file. For the final month of the archive (2025-12) that file
does not exist, so its last day is skipped and a warning is printed.

#### Weekly aggregation

The daily files are aggregated to **ISO weeks** (Monday–Sunday) and written to:

```
/media/mary-camila/Expansion/era5land/processed_weekly/
├── pev/    pev_YYYY.nc
├── ssrd/   ssrd_YYYY.nc
├── temp/   temp_YYYY.nc
├── tp/     tp_YYYY.nc
└── wind/   wind_YYYY.nc
```

The group folders mirror the raw data, but because weeks cross month
boundaries there is **one file per year** rather than per month. Each week is
labelled by its Monday and belongs to the year holding that Monday, so building
one year also reads January of the next; no week is split or written twice.

Aggregation is over the daily values, which already hold true daily totals:

| File | Variable(s) | Weekly aggregation |
|------|-------------|--------------------|
| `tp`   | `tp`         | sum of the 7 daily totals |
| `pev`  | `pev`        | sum of the 7 daily totals |
| `ssrd` | `ssrd`       | sum of the 7 daily totals |
| `temp` | `t2m`, `d2m` | mean; `t2m_min` = min of daily minima, `t2m_max` = max of daily maxima |
| `wind` | `u10`, `v10` | mean |

`pev` keeps its negative ECMWF sign, as in the daily files.

Weeks with fewer than 7 daily values are **dropped**, so every weekly value
covers a full week and the accumulated sums stay comparable. In practice this
removes 1980-01-01 to 01-06 (the archive starts on a Tuesday) and the last days
of 2025-12.

Generated by `scripts/processing/weekly_aggregation.py`.

## Features

The weekly files are turned into a flat table for modelling:

```
/media/mary-camila/Expansion/era5land/features/
├── points.parquet            the sampled grid points
└── weekly_features.parquet   one row per point and week
```

### Sampling

A model reads a table, not a grid, so one row is one grid point in one week.
The full grid over the archive would be 411 × 451 × 2399 ≈ 445 million rows.
Since neighbouring points are ~9 km apart and nearly identical,
`scripts/utils/sample_points.py` draws a spread out subset instead:

- **land only** — ERA5-Land is NaN over the ocean;
- **stratified in 5° × 5° blocks**, `POINTS_PER_BLOCK` each, so the sample does
  not follow area and let the Amazon basin dominate it;
- **at least 5 cells (0.5°, ~55 km) apart**, so no two points are near
  duplicates.

The defaults give **3,507 points in 62 blocks**. The spacing rule is what binds,
not the quota: a full block saturates at ~75 points, and blocks holding little
land yield fewer. The seed is fixed, so the draw is reproducible. The land mask
does not depend on the time resolution, so the same points can serve a daily
table later.

Going much denser is not worth it. Below ~0.3° the points start to be near
duplicates, which inflates the apparent sample size without adding information
and makes validation look better than it is.

Every week of every sampled point is kept, so the lags and accumulations below
are well defined. Each run also redraws `figures/sampled_points.png`, a map of
the draw over the land mask with the block grid, so the coverage can be checked
by eye.

### The table

`build_weekly_features.py` reads only the sampled points, converts units and
derives the columns: **8,227,422 rows × 32 columns** (3,507 points × 2,346
weeks), 862 MB on disk and 1.06 GB in memory, no missing values, covering
1981-01-12 to 2025-12-22. The target is `tp`, the weekly precipitation total in
mm.

| Category | Columns | Units | Definition |
|----------|---------|-------|------------|
| key | `point_id`, `lat`, `lon`, `block`, `week` | — | identifiers, not model inputs |
| target | `tp` (total precipitation) | mm/week | weekly precipitation total |
| past rainfall | `tp_lag1`, `tp_lag2`, `tp_lag3` | mm/week | `tp` at t−1, t−2, t−3 |
| past rainfall | `tp_sum4`, `tp_sum13`, `tp_sum26`, `tp_sum52` | mm | `tp` summed over t−k to t−1, k = 4, 13, 26, 52 |
| moisture | `dpd` (dewpoint depression), `dpd_lag1`, `dpd_lag2` | °C | `t2m` − `d2m`, zero when the air is saturated |
| moisture | `e_hpa` (vapour pressure), `e_lag1`, `e_lag2` | hPa | `es(d2m)`, how much water the air holds |
| moisture | `vpd` (vapour pressure deficit) | hPa | `es(t2m)` − `es(d2m)`, how much more it could hold before saturating |
| cloud | `ssrd` (surface solar radiation downwards) | W m⁻² | weekly solar radiation ÷ 604800, reduced by clouds |
| cloud | `temp_range` (diurnal temperature range) | °C | `t2m_max` − `t2m_min`, also reduced by clouds |
| wind | `u10`, `v10` | m s⁻¹ | eastward and northward components, as stored |
| wind | `wind` | m s⁻¹ | `√(u10² + v10²)`, the speed |
| wind | `eu`, `ev` (moisture flux components) | hPa m s⁻¹ | `e_hpa` × `u10` and `e_hpa` × `v10`, a moisture transport proxy |
| water demand | `pev` (potential evaporation) | mm/week | evaporative demand, negative as ECMWF stores it |
| water demand | `bal_sum4`, `bal_sum13` (water balance sums) | mm | `tp` + `pev` summed over t−k to t−1, k = 4, 13 |
| seasonality | `week_sin`, `week_cos` | — | `sin` and `cos` of 2π × d ⁄ 365.25, where d is the day of year of the week's Monday |

#### `es(T)`

- **Saturation vapour pressure**: the most vapour air at `T` can hold, in hPa.
  Depends only on temperature, and grows about 7% per °C.
- Magnus formula: `es(T) = 6.112 * exp(17.67 * T / (T + 243.5))`, `T` in °C.
- `es(d2m)` = vapour present (`e_hpa`, vapour pressure); `es(t2m)` = the
  ceiling; the difference = `vpd`, the vapour pressure deficit.
- `vpd` is not `dpd` (dewpoint depression) restated: a 5 °C gap is 10.8 hPa at
  30 °C, 2.6 hPa at 5 °C.

#### Why these

- Accumulations beat distant lags: weekly rainfall autocorrelation decays fast,
  while a long sum tracks how wet the soil is.
- `ssrd` and `temp_range` are two independent cloud proxies.
- Wind stays in components, since a direction in degrees jumps from 359 to 0.
- `e_hpa` instead of specific humidity, which needs surface pressure.
- Day of year instead of ISO week number, since years hold 52 or 53 ISO weeks.

### Target leakage

- Accumulations cover weeks **t − k to t − 1** and exclude week t, which would
  otherwise put the target inside the feature.
- The current week's water balance is not a column: it is `tp` + `pev`, so it
  would hand over the target. Only `pev` represents that week.
- The first 53 weeks of each point are dropped, since the longest accumulation
  needs 52 weeks plus the shift.

### Planned, not yet implemented

- **Climatology and anomalies** — `tp_clim`, `tp_anom4`, `ssrd_anom`. Usually
  strong predictors, and they separate "drier than normal for this time of year"
  from "it is simply winter". Base period 1980–2015 only, so the held out
  2016–2025 stays clean.
- **Neighbourhood** — `tp` and `e_hpa` averaged over a 9 × 9 window (~80 km).
  The only group that needs the full grid.
- **Specific humidity** — needs `surface_pressure` from the CDS.
- **Forecast setting** — the moisture, cloud and wind columns are contemporaneous
  with the target. For a t+1 forecast, shift them by one week.

## Repository layout

```
.
├── figures/                 maps and animations, versioned
├── notebooks/               exploration, modelling and XAI notebooks
├── pyproject.toml           dependencies (uv)
├── scripts/
│   ├── processing/
│   │   ├── daily_aggregation.py     hourly raw → daily processed_daily
│   │   └── weekly_aggregation.py    daily → weekly processed_weekly
│   ├── features/
│   │   └── build_weekly_features.py weekly → feature table for modelling
│   └── utils/
│       └── sample_points.py         draw the grid points to model on
└── README.md
```

## Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/) (Python >= 3.12):

```bash
uv sync
```

Core packages: `xarray`, `netCDF4`, `dask`, `numpy`, `pandas`; the `dev` group
adds `jupyterlab` and `matplotlib` (`uv sync --group dev`).

## How to run

**1. Check the external drive is mounted.** Everything reads from and writes to
`/media/mary-camila/Expansion/era5land/`; the paths are set at the top of
`scripts/processing/daily_aggregation.py`.

```bash
ls /media/mary-camila/Expansion/era5land/raw
```

**2. Install the environment.**

```bash
uv sync --group dev
```

**3. Build the daily dataset.** This reads the hourly raw files and writes the
daily ones to `processed_daily/`.

```bash
uv run python scripts/processing/daily_aggregation.py
```

**4. Build the weekly dataset.** This reads `processed_daily/` and writes the
weekly files to `processed_weekly/`.

```bash
uv run python scripts/processing/weekly_aggregation.py
```

Both scripts skip files that already exist, so a re-run only fills in what is
missing.

**5. Build the feature table.** The first script draws the grid points, the
second turns the weekly files into one row per point and week. The points file
must exist before the features are built.

```bash
uv run python scripts/utils/sample_points.py
uv run python scripts/features/build_weekly_features.py
```

Both overwrite their output, so a re-run rebuilds from scratch. The sample is
seeded, so the same points come out every time. To change the sample size, edit
`POINTS_PER_BLOCK` and `MIN_DIST_CELLS` at the top of `sample_points.py` and run
both scripts again. Row count scales linearly with the number of points, and a
gradient boosting fit needs roughly four times the table in memory.

**6. Explore and model.**

```bash
uv run jupyter lab
```

Notebooks live in `notebooks/` and read the daily files, for example:

```python
import xarray as xr

tp = xr.open_mfdataset(
    "/media/mary-camila/Expansion/era5land/processed_daily/tp/tp_*.nc"
).tp * 1000  # mm/day

tp_weekly = xr.open_mfdataset(
    "/media/mary-camila/Expansion/era5land/processed_weekly/tp/tp_*.nc"
).tp * 1000  # mm/week
```

The feature table is read with pandas:

```python
import pandas as pd

df = pd.read_parquet(
    "/media/mary-camila/Expansion/era5land/features/weekly_features.parquet"
)
```

## Notes

Raw and processed data are not versioned in git — only code and notebooks are.

## Source and citation

The raw data is the gridded **ERA5-Land hourly** dataset from the Copernicus
Climate Data Store. Its overview page carries the authoritative list of all 50
available variables with their units and full descriptions; this project uses
the six listed under [Raw data](#raw-data).

- Dataset: [ERA5-Land hourly data from 1950 to present](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land?tab=overview)
  — DOI [10.24381/cds.e2161bac](https://doi.org/10.24381/cds.e2161bac), CC-BY licence
- Documentation: [ERA5-Land: data documentation](https://confluence.ecmwf.int/display/CKB/ERA5-Land%3A+data+documentation)
  (ECMWF Confluence) — accumulation conventions, known issues
- Reference paper: Muñoz-Sabater, J., Dutra, E., Agustí-Panareda, A., et al.,
  *ERA5-Land: A state-of-the-art global reanalysis dataset for land
  applications*, Earth Syst. Sci. Data, 13, 4349–4383, 2021.
  <https://doi.org/10.5194/essd-13-4349-2021>
