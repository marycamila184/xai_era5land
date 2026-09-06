# AT2 — Daily precipitation table for Curitiba (ERA5-Land)

Coursework for the XAI class. One row per day, one grid cell, built to forecast tomorrow's rain in Curitiba and then explain the model.

Wind statistics come from [`scripts/utils/wind_stats.py`](../scripts/utils/wind_stats.py) at the repository root, the same code the main pipeline uses.

## The setup

**Point** — the ERA5-Land cell nearest Praça Tiradentes (−25.4284, −49.2733), which lands on **−25.4, −49.3**. A cell is ~9 km across, so it is already a model average over ~81 km², centred on the city. Six cells cover Curitiba; averaging them damps the extremes, which are the cases a rainfall model exists for. The series represents the centre and runs slightly drier than the municipality as a whole.

**Day** — the UTC day. In Curitiba (UTC−3) day D runs from 21:00 local on D−1. A late-afternoon storm lands on the right day; rain after midnight falls into the previous one. Worth remembering when comparing against INMET stations, which use the local civil day.

**Timing** — `tp_mm` is the only column from day t. Everything else describes **t−1 or earlier**, so the table is an honest t+1 forecast: nothing in a row was unknowable when the forecast would have been made. `_lagk` means day t−k.

## Build

```bash
uv sync --group dev
uv run python -m at2.build_curitiba_daily   # data/curitiba_daily.parquet
uv run python -m at2.plot_month 2025-01     # ../figures/curitiba_2025_01.png
uv run python -m at2.animate_month 2025-01  # ../figures/curitiba_map_2025_01.gif
```

`plot_month` draws one month of the table itself. `animate_month` steps through the same month on the **full grid** around the city, reading the gridded files rather than the table, with the municipal boundary and state lines from [IBGE](https://servicodados.ibge.gov.br/api/docs/malhas?versao=3) cached in `data/boundaries/`. A second argument sets the half-width of the map window in degrees, default 2:

```bash
uv run python -m at2.animate_month 2025-01 0.6   # metropolitan zoom
```

The grid is 0.1° and Curitiba spans about 0.2° × 0.3°, so below ~0.5° there is no spatial variation left to see.

The wind is read from the hourly raw files, which is slow, so it is cached in `data/wind_daily.parquet` — delete that file to redo it. Everything else comes from `processed_daily/`.

```python
import pandas as pd
df = pd.read_parquet("at2/data/curitiba_daily.parquet")
```

## Columns

Target: **`tp_mm`**, day t's rainfall in mm. 22 features, no missing values; the record runs 1981-01-01 to 2025-12-30, 16,435 rows.

| Column | Unit | From | How it is computed |
|---|---|---|---|
| `date` | — | t | the UTC day being forecast; not a model input |
| **`tp_mm`** | mm | **t** | ERA5 `tp` × 1000 — **the target** |
| `tp_lag1..3` | mm | t−1..3 | `tp_mm` shifted 1, 2, 3 days |
| `tp_sum7/30/90` | mm | t−k..t−1 | `tp_mm.shift(1).rolling(k).sum()` |
| `t2m`, `t2m_min`, `t2m_max` | °C | t−1 | ERA5 `t2m` − 273.15 (daily mean, min, max) |
| `d2m`, `d2m_lag2`, `d2m_lag3` | °C | t−1..3 | ERA5 `d2m` − 273.15, the dewpoint |
| `dpd`, `dpd_lag2`, `dpd_lag3` | °C | t−1..3 | `t2m − d2m` |
| `ssrd_wm2` | W m⁻² | t−1 | ERA5 `ssrd` ÷ 86400 |
| `wind_speed` | m s⁻¹ | t−1 | `mean(√(u²+v²))` over the 24 hourly steps |
| `wind_const` | 0–1 | t−1 | `√(ū²+v̄²) / wind_speed` |
| `wind_dir_sin` | — | t−1 | `sin(θ)`, `θ = (270° − atan2(v̄, ū)) mod 360°` |
| `wind_dir_cos` | — | t−1 | `cos(θ)`, same `θ` |
| `day_sin`, `day_cos` | — | t | `sin`/`cos` of `2π × day_of_year / 365.25` |

### Humidity

`d2m` is the dewpoint, the temperature at which the air would saturate, so it measures the vapour actually present. `dpd` is how many degrees short of saturating the air is.

### Cloud

`ssrd` is stored as accumulated energy (J m⁻²). Dividing by the accumulation window in seconds turns it into mean power, W m⁻²; a UTC day is 86400 s. This makes daily and weekly values comparable and lets the number be read against the solar constant, ~1361 W m⁻². Dividing by a fixed 3600 is the usual mistake and gives about five times that.

### Wind

A daily mean of `u10`/`v10` is a **vector** mean, and it misleads on exactly the interesting days. Twelve hours of westerly at 4 m s⁻¹ followed by twelve hours of easterly at 4 m s⁻¹ average to zero: the model reads "no wind" when the wind blew all day and swung around — which is what a front looks like. So the table carries the **scalar** mean beside the vector one, and their ratio:

- **`wind_speed`** — how hard it blew.
- **`wind_const`** — how steady the direction was. 1 means one bearing all day, real advection of moisture; near 0 means it cancelled itself out. The scalar mean is never below the vector one, so the ratio sits in [0, 1].
- **`wind_dir_sin` / `wind_dir_cos`** — where it came from. In degrees the direction jumps from 359 to 0, putting two nearly identical winds at opposite ends of the scale; the sine/cosine pair has no such seam. The convention is meteorological: the bearing the wind blows **from**.

On a low-constancy day the direction is poorly defined. That is the point — `wind_const` tells the model how much the direction is worth.

## What the table leaves out, and why

- **Anything from day t.** Same-day cloud and temperature would be partly a *consequence* of the rain.
- **`u10` and `v10`.** They are an exact function of the wind columns above.
- **`temp_range`**, `t2m_max − t2m_min`, since both parents are present.
- **`pev`.** The potential evaporation closely mirrors `ssrd_wm2` and carries little about the target on its own.
- **The first 91 days**, the burn-in `tp_sum90` needs plus the one-day shift.

## Does it look like Curitiba?

Climatology over the record: **1556 mm a year**, wettest in January (220 mm), driest in August (82 mm), no genuinely dry season — the Cfb regime the city has. Worth checking against INMET's published normals before quoting numbers.

## References

- **EPA-454/R-99-005**, *Meteorological Monitoring Guidance for Regulatory Modeling Applications* (2000). [PDF](https://www.epa.gov/sites/default/files/2020-10/documents/mmgrma_0.pdf) — §6.2.1 for the scalar mean speed, §6.2.2 (eqs. 6.2.13–6.2.16) for the mean components and the resultant speed and direction.
- **Singer, I. A. (1967).** *Steadiness of the Wind.* J. Appl. Meteor. 6(6), 1033–1038. [AMS](https://journals.ametsoc.org/view/journals/apme/6/6/1520-0450_1967_006_1033_sotw_2_0_co_2.xml) — the definition of constancy, mean vector wind over mean scalar wind. ⚠ Verified from the abstract only; confirm authorship and pages before quoting.
- *Circular mean.* [Wikipedia](https://en.wikipedia.org/wiki/Circular_mean) — why a direction is carried as sine and cosine rather than degrees.
- *Antecedent moisture.* [Wikipedia](https://en.wikipedia.org/wiki/Antecedent_moisture) — past rainfall as a proxy for how wet the ground already is, the job of `tp_sum7` … `tp_sum90`.
- **INMET climatological normals.** [portal.inmet.gov.br/normais](https://portal.inmet.gov.br/normais) — the Curitiba monthly totals, to check the climatology above.
- **IBGE mesh API.** [Documentation](https://servicodados.ibge.gov.br/api/docs/malhas?versao=3) — the `municipios` and `estados` endpoints `animate_month` draws.

ERA5-Land source and accumulation conventions: see the [main README](../README.md#source-and-citation).
