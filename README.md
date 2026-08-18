# XAI - ERA5-Land — ERA5-Land Precipitation Prediction

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
limiting — i.e. the atmospheric demand for water, in **metres of water
equivalent**. ERA5-Land computes it by running the evaporation calculation over
a hypothetical well-watered grass surface under the same atmospheric conditions.

Sign convention: ECMWF treats downward fluxes as positive, so evaporation
appears as **negative** values. Take the absolute value (or negate) when using
it as a water-demand predictor.

Together with `tp` it gives a simple water-balance / aridity signal
(`tp` − |`pev`|), often a strong feature for precipitation modelling.

#### `ssrd` — Surface solar radiation downwards

Shortwave (solar) radiation reaching the surface, both direct and diffuse,
after being modified by the atmosphere — mainly by clouds. Accumulated energy
per unit area, in **J m⁻²**.

Divide by 3600 to convert an hourly accumulation to a mean flux in W m⁻². Low
`ssrd` relative to the clear-sky maximum is effectively a cloud-cover proxy,
which is why it is informative for precipitation.

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

## Repository layout

```
.
├── notebooks/               exploration, modelling and XAI notebooks
├── pyproject.toml           dependencies (uv)
├── scripts/
│   └── processing/
│       └── daily_aggregation.py   hourly raw → daily processed_daily
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

The full archive is ~597 GB, so a complete run takes a couple of hours. It is
resumable — files that already exist are skipped, so the script can be stopped
and restarted, and rebuilding a file just means deleting it first. The variables
and years to process are the `GROUPS` and `YEARS` constants at the top of the
script.

**4. Explore and model.**

```bash
uv run jupyter lab
```

Notebooks live in `notebooks/` and read the daily files, for example:

```python
import xarray as xr

tp = xr.open_mfdataset(
    "/media/mary-camila/Expansion/era5land/processed_daily/tp/tp_*.nc"
).tp * 1000  # mm/day
```

## Notes

Raw and processed data are not versioned in git — only code and notebooks are.

ECMWF, *ERA5-Land hourly data from 1950 to present*, Copernicus Climate Data
Store — https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land
