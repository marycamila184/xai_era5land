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
ECMWF: hourly, on a regular 0.1° × 0.1° grid (~9 km), over land points only,
from 1950 to present. Our subset covers **1980-01 to 2025-12** over South
America (6°N–35°S, 75°W–30°W; 411 × 451 grid points).

### Raw data

```
/media/mary-camila/Expansion/era5land/raw/
├── pev/    pev_YYYY_MM.nc     pev       — potential evaporation
├── ssrd/   ssrd_YYYY_MM.nc    ssrd      — surface solar radiation downwards
├── temp/   temp_YYYY_MM.nc    t2m, d2m  — 2 m temperature and dewpoint
├── tp/     tp_YYYY_MM.nc      tp        — total precipitation (target)
└── wind/   wind_YYYY_MM.nc    u10, v10  — 10 m wind components
```

One NetCDF file per group per month, hourly (552 files per folder, ~597 GB in
total). Note that `temp` and `wind` each hold **two** variables.

| Folder | Variable(s) | ECMWF name | Units | Type |
|--------|-------------|------------|-------|------|
| `tp`   | `tp`         | Total precipitation | m | accumulated |
| `pev`  | `pev`        | Potential evaporation | m | accumulated |
| `ssrd` | `ssrd`       | Surface solar radiation downwards | J m⁻² | accumulated |
| `temp` | `t2m`, `d2m` | 2 m temperature, 2 m dewpoint temperature | K | instantaneous |
| `wind` | `u10`, `v10` | 10 m u- and v-component of wind | m s⁻¹ | instantaneous |

#### `tp` — total precipitation

Rain plus snow reaching the surface, as a **depth of water in metres**; the sum
of large-scale and convective precipitation, excluding fog, dew, and rain that
evaporates before landing. This is the **prediction target**. Multiply by 1000
for millimetres.

#### `pev` — potential evaporation

The evaporation that *would* occur if water were not limiting — atmospheric
demand for water, in **metres**.

- **Sign**: ECMWF treats downward fluxes as positive, so evaporation is
  **negative**. Negate it (`-pev`) for a positive demand predictor; do *not*
  use `abs()`. About 0.1% of land cells are genuinely positive (condensation),
  and `abs()` would silently flip those into demand.
- **Magnitude**: in ERA5-Land `pev` is an **open-water (pan) evaporation**,
  computed differently from ERA5 and *not* FAO-56 reference ET. It averages
  ~9.6 mm/day over this domain, well above reference ET, and ECMWF warn it "can
  give unrealistic results in arid conditions". Use it as a relative demand
  index, not in a water balance expecting realistic ET.

With `tp` it gives an aridity signal (`tp` + `pev`, since `pev` is negative).

#### `ssrd` — surface solar radiation downwards

Direct plus diffuse solar radiation reaching the surface after the atmosphere —
mainly clouds — has modified it. Accumulated energy per area, in **J m⁻²**.

Per ECMWF the accumulated value is divided by **the length of its accumulation
window** in seconds, not by a fixed 3600. The raw values accumulate from 00 UTC
(see [Accumulated vs. instantaneous](#accumulated-vs-instantaneous)), so
dividing a raw value by 3600 gives nonsense — ~7000 W m⁻² at the end-of-day
step, five times the solar constant.

| Value | To W m⁻² |
|-------|----------|
| raw hourly, after `.diff('valid_time')` | ÷ 3600 |
| `processed_daily` (daily total) | ÷ 86400 |
| `processed_weekly` (weekly total) | ÷ 604800 |

Low `ssrd` against the clear-sky maximum is a cloud-cover proxy, which is why
it informs precipitation. Not to be confused with **surface net solar
radiation** (`ssr`), which has albedo folded in and is a weaker cloud proxy.

#### `t2m`, `d2m` — 2 m temperature and dewpoint

Both in **kelvin**; subtract 273.15 for °C. `d2m` is the temperature at which
the air at 2 m would saturate. The pair gives near-surface humidity: the
dewpoint depression (`t2m` − `d2m`) goes to zero as the air saturates. Moisture
availability is a direct precursor of precipitation, so the pair is more
informative than `t2m` alone.

#### `u10`, `v10` — 10 m wind components

Horizontal wind at 10 m, in **m s⁻¹**: `u10` eastward, `v10` northward.

Averaging these two alone over a day or a week is a **vector mean**, and it
misleads on exactly the interesting days: twelve hours of westerly at 4 m s⁻¹
followed by twelve hours of easterly at 4 m s⁻¹ average to `u10 = 0`, reading
as "no wind" when in fact the wind blew all day and the direction swung — what
a frontal passage looks like. The pipeline therefore also stores the **scalar**
mean speed and the period maximum, and the feature tables derive the rest:

| Column | Formula | What it measures |
|--------|---------|------------------|
| `u10`, `v10` | mean of the components | the mean vector |
| `wind_speed` | mean of √(u²+v²) | how hard it actually blew |
| `wind_max` | max of √(u²+v²) | the peak, a frontal-passage marker |
| `wind_res` | √(ū² + v̄²) | the net transport |
| `wind_const` | `wind_res` / `wind_speed` | how steady the direction was |
| `wind_dir_sin`, `wind_dir_cos` | sin/cos of the resultant direction | direction, without the 359 → 0 jump |

`wind_const` is 1 when the wind held one direction all period (real moisture
advection) and ~0 when it cancelled itself out; since `wind_speed ≥ wind_res`
always, it stays in [0, 1], and it is NaN on a dead calm. It is the classical
*constancy* or *steadiness* of the wind (Singer 1967); scalar, directional and
vector statistics carry non-redundant information about a wind field (Klink
1998). The formulas live in
[scripts/utils/wind_stats.py](scripts/utils/wind_stats.py), used by both the
daily and the weekly pipeline, and are covered by
[tests/test_wind_stats.py](tests/test_wind_stats.py).

### Processed data

Raw files are aggregated to **daily** files in `processed_daily/`, mirroring
the raw folder structure and naming, so any raw path maps to its processed
counterpart by swapping `raw` for `processed_daily`. Generated by
[scripts/processing/daily_aggregation.py](scripts/processing/daily_aggregation.py).

#### Accumulated vs. instantaneous

This distinction determines how each variable must be aggregated.

**Instantaneous** variables (`t2m`, `d2m`, `u10`, `v10`) are snapshots valid at
the timestamp, so they are averaged.

**Accumulated** variables (`tp`, `pev`, `ssrd`) accumulate **from 00 UTC of the
same day**, not over the preceding hour: the value at 06 UTC is the total for
00–06 UTC, growing through the day and resetting. So:

- **Summing the 24 hourly values badly overcounts.** The daily total is the
  *last* step of the day — the value stamped 00 UTC of the following day.
- To recover hourly rates, difference consecutive steps within the day
  (`x.diff('valid_time')`), keeping the 01 UTC value as-is.
- The resulting day is a **UTC day**. Far from Greenwich this matters: in
  Curitiba (UTC−3) the day starts at 21 h local time of the previous day.

| File | Variable(s) | Daily aggregation |
|------|-------------|-------------------|
| `tp`, `pev`, `ssrd` | `tp`, `pev`, `ssrd` | last accumulated step of the day (00 UTC of the next day) |
| `temp` | `t2m`, `d2m` | mean, plus `t2m_min` and `t2m_max` |
| `wind` | `u10`, `v10` | vector mean, plus `wind_speed` and `wind_max` |

The daily total of the last day of a month is read from the first timestep of
the next month's file. For 2025-12 that file does not exist, so its last day is
skipped and a warning is printed.

#### Weekly aggregation

Daily files are aggregated to **ISO weeks** (Monday–Sunday) in
`processed_weekly/`, by
[scripts/processing/weekly_aggregation.py](scripts/processing/weekly_aggregation.py).
The group folders mirror the raw data, but because weeks cross month boundaries
there is **one file per year** (`tp_YYYY.nc`) rather than per month. Each week
is labelled by its Monday and belongs to the year holding that Monday, so
building one year also reads January of the next; no week is split or written
twice.

| File | Variable(s) | Weekly aggregation |
|------|-------------|--------------------|
| `tp`, `pev`, `ssrd` | `tp`, `pev`, `ssrd` | sum of the 7 daily totals |
| `temp` | `t2m`, `d2m` | mean; `t2m_min` = min of daily minima, `t2m_max` = max of daily maxima |
| `wind` | `u10`, `v10`, `wind_speed` | mean; `wind_max` = max of daily maxima |

Every day carries the same 24 hours, so the mean of the daily means is the mean
over the week — for the scalar speed as much as for the components.

Weeks with fewer than 7 daily values are **dropped**, so every weekly value
covers a full week. In practice this removes 1980-01-01 to 01-06 (the archive
starts on a Tuesday) and the last days of 2025-12. `pev` keeps its negative
ECMWF sign throughout.

## AT2 — Curitiba daily table

The XAI coursework activity lives in [at2/](at2/): a single ERA5-Land grid cell
over Curitiba, one row per UTC day, set up as a t+1 forecast — the target is
day t's rain and every predictor comes from t−1 or earlier. It has its own
[README](at2/README.md) with the column dictionary and the references.

## Repository layout

```
.
├── at2/                     Curitiba daily table (XAI coursework)
│   ├── build_curitiba_daily.py
│   ├── plot_month.py        one month of the table, three panels
│   ├── animate_month.py     the same month as maps around the city
│   ├── data/                curitiba_daily.parquet
│   └── README.md
├── figures/                 maps and animations, versioned
├── notebooks/               exploration, modelling and XAI notebooks
├── scripts/
│   ├── processing/
│   │   ├── daily_aggregation.py     hourly raw → processed_daily
│   │   └── weekly_aggregation.py    daily → processed_weekly
│   └── utils/
│       └── wind_stats.py            wind aggregation, shared by both
├── tests/
├── pyproject.toml           dependencies (uv)
└── README.md
```

## Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/) (Python >= 3.12):

```bash
uv sync --group dev
```

Core packages: `xarray`, `netCDF4`, `dask`, `numpy`, `pandas`, `pyarrow`; the
`dev` group adds `jupyterlab` and `pytest`.

## How to run

**1. Check the external drive is mounted.** Everything reads from and writes to
`/media/mary-camila/Expansion/era5land/`; the paths sit at the top of each
script.

```bash
ls /media/mary-camila/Expansion/era5land/raw
```

**2. Build the daily dataset**, then the weekly one.

```bash
uv run python scripts/processing/daily_aggregation.py
uv run python scripts/processing/weekly_aggregation.py
```

Both skip files that already exist, so a re-run only fills in what is missing.
**After a change to the wind aggregation this means the old wind files must be
deleted by hand**, or they will be kept as they are:

```bash
rm -r /media/mary-camila/Expansion/era5land/processed_daily/wind
rm -r /media/mary-camila/Expansion/era5land/processed_weekly/wind
```

**3. Build the Curitiba table.**

```bash
uv run python -m at2.build_curitiba_daily
uv run python -m at2.plot_month 2025-01
uv run python -m at2.animate_month 2025-01
```

**4. Run the tests.**

```bash
uv run python -m pytest
```

**5. Explore and model.**

```bash
uv run jupyter lab
```

Notebooks live in `notebooks/`:

```python
import xarray as xr
import pandas as pd

tp = xr.open_mfdataset(
    "/media/mary-camila/Expansion/era5land/processed_daily/tp/tp_*.nc"
).tp * 1000  # mm/day

curitiba = pd.read_parquet("at2/data/curitiba_daily.parquet")
```

## Notes

Data is not versioned in git — that includes `at2/data/curitiba_daily.parquet`,
which `.gitignore` excludes through the `data/` rule. It is 2.9 MB and rebuilds
in a few minutes; add `!at2/data/` to `.gitignore` if the coursework should
carry the table with it. `tests/` is also excluded.

## Source and citation

The raw data is the gridded **ERA5-Land hourly** dataset from the Copernicus
Climate Data Store. Its overview page carries the authoritative list of all 50
available variables with units and full descriptions; this project uses the six
listed under [Raw data](#raw-data).

- Dataset: [ERA5-Land hourly data from 1950 to present](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land?tab=overview)
  — DOI [10.24381/cds.e2161bac](https://doi.org/10.24381/cds.e2161bac), CC-BY licence
- Documentation: [ERA5-Land: data documentation](https://confluence.ecmwf.int/display/CKB/ERA5-Land%3A+data+documentation)
  (ECMWF Confluence) — accumulation conventions, known issues
- Reference paper: Muñoz-Sabater, J., Dutra, E., Agustí-Panareda, A., et al.,
  *ERA5-Land: A state-of-the-art global reanalysis dataset for land
  applications*, Earth Syst. Sci. Data, 13, 4349–4383, 2021.
  <https://doi.org/10.5194/essd-13-4349-2021>
- Wind aggregation: Singer, I. A., *Steadiness of the Wind*, J. Appl. Meteor.,
  6, 1033–1038, 1967; Klink, K., *Complementary Use of Scalar, Directional, and
  Vector Statistics with an Application to Surface Winds*, The Professional
  Geographer, 50(1), 3–13, 1998. Full list in [at2/README.md](at2/README.md#references).
