# AT2 — Daily precipitation table for Curitiba (ERA5-Land)

Coursework for the XAI class. One row per day, one grid cell, built to forecast
tomorrow's rain in Curitiba and then explain the model.

The wind statistics come from
[`scripts/utils/wind_stats.py`](../scripts/utils/wind_stats.py) at the
repository root, the same code the main pipeline uses.

## The setup

**Point** — the ERA5-Land cell nearest Praça Tiradentes (−25.4284, −49.2733),
which lands on **−25.4, −49.3**. A cell is ~9 km across, so it is already a
model average over ~81 km² — about a fifth of the municipality, centred on the
city. Six cells cover Curitiba; averaging them instead would raise the annual
total by ~65 mm (4%) and cut the wettest day from 79.9 to 75.9 mm, while
correlating 0.989 day to day. The single cell is kept: averaging averages only
damps the extremes, which are the cases a rainfall model exists for. Note in
any write-up that the series represents the centre and runs slightly drier than
the municipality as a whole.

**Day** — the UTC day. In Curitiba (UTC−3) that means day D runs from 21:00
local on D−1. A late-afternoon storm lands on the right day; rain after
midnight falls into the previous one. Worth remembering when comparing against
INMET stations, which use the local civil day.

**Timing** — `tp_mm` is the only column from day t. Everything else describes
**t−1 or earlier**, so the table is an honest t+1 forecast: nothing in a row
was unknowable when the forecast would have been made. `_lagk` in a name means
day t−k.

## Build

```bash
uv sync --group dev
uv run python -m at2.build_curitiba_daily   # data/curitiba_daily.parquet
uv run python -m at2.plot_month 2025-01     # ../figures/curitiba_2025_01.png
uv run python -m at2.animate_month 2025-01  # ../figures/curitiba_map_2025_01.gif
```

`plot_month` draws one month of the table itself — rain, temperature, wind.
`animate_month` steps through the same month on the **full grid** around the
city, so you can see the weather the point sits inside; it reads the gridded
files, not the table, and draws the municipal boundary and state lines from
[IBGE](https://servicodados.ibge.gov.br/api/docs/malhas?versao=3) (downloaded once and
cached in `data/boundaries/`).

A second argument sets the half-width of the map window in degrees, default 2:

```bash
uv run python -m at2.animate_month 2025-01 0.6   # metropolitan zoom
```

Do not go much tighter. The grid is 0.1° and Curitiba's boundary spans about
0.2° × 0.3°, so the city itself is roughly six cells — below ~0.5° there is no
spatial variation left to see.

The wind is rebuilt from the hourly raw files, which is slow, so it is cached
in `data/wind_daily.parquet` — delete that file to redo it. Everything else
comes from `processed_daily/`.

```python
import pandas as pd
df = pd.read_parquet("at2/data/curitiba_daily.parquet")
```

## Columns

Target: **`tp_mm`**, day t's rainfall total in mm. All 16,435 rows are
complete; the record runs 1981-01-01 to 2025-12-30.

| Column | Unit | From | How it is computed |
|---|---|---|---|
| `date` | — | t | the UTC day being forecast; not a model input |
| **`tp_mm`** | mm | **t** | ERA5 `tp` × 1000 — **the target** |
| `tp_lag1..3` | mm | t−1..3 | `tp_mm` shifted 1, 2, 3 days |
| `tp_sum7/30/90/365` | mm | t−k..t−1 | `tp_mm.shift(1).rolling(k).sum()` |
| `t2m`, `t2m_min`, `t2m_max` | °C | t−1 | ERA5 `t2m` − 273.15 (daily mean, min, max) |
| `d2m` | °C | t−1 | ERA5 `d2m` − 273.15 |
| `temp_range` | °C | t−1 | `t2m_max − t2m_min` |
| `dpd`, `dpd_lag2`, `dpd_lag3` | °C | t−1..3 | `t2m − d2m` |
| `e_hpa`, `e_lag2`, `e_lag3` | hPa | t−1..3 | `es(d2m)` |
| `vpd` | hPa | t−1 | `es(t2m) − es(d2m)` |
| `ssrd_wm2` | W m⁻² | t−1 | ERA5 `ssrd` ÷ 86400 |
| `pev_mm` | mm | t−1 | ERA5 `pev` × 1000, negative as ECMWF stores it |
| `wind_speed` | m s⁻¹ | t−1 | `mean(√(u²+v²))` over the 24 hourly steps |
| `wind_const` | 0–1 | t−1 | `√(ū²+v̄²) / wind_speed` |
| `wind_dir_sin` | — | t−1 | `sin(θ)`, `θ = (270° − atan2(v̄, ū)) mod 360°` |
| `wind_dir_cos` | — | t−1 | `cos(θ)`, same `θ` |
| `day_sin`, `day_cos` | — | t | `sin`/`cos` of `2π × day_of_year / 365.25` |

where `es(T) = 6.112 · exp(17.67·T / (T + 243.5))`, `T` in °C, result in hPa.

### What the derived ones mean

**`es`** is not in the data — it is a function we apply, the Magnus formula for
saturation vapour pressure: the most vapour air can hold at a given
temperature. The dewpoint is by definition the temperature at which the air
saturates, so `es(d2m)` is the vapour **already there** (`e_hpa`), while
`es(t2m)` is the **ceiling**. The gap between them is `vpd`, how far the air is
from saturating. On a day at 25 °C with a dewpoint of 18 °C: 20.6 hPa present,
31.7 hPa possible, `vpd` = 11.1 hPa.

`vpd` and `dpd` are not the same thing said twice: a 5 °C gap is 10.8 hPa at
30 °C but only 2.6 hPa at 5 °C.

**`ssrd_wm2`** — `ssrd` is stored as accumulated energy (J m⁻²). Dividing by
the accumulation window in seconds turns it into mean power, W m⁻². A UTC day
is 86400 s. This is what makes daily and weekly values comparable and lets the
number be read against the solar constant, ~1361 W m⁻². Dividing by a fixed
3600 is the usual mistake and gives about five times that.

`ssrd_wm2` and `temp_range` are two independent cloud proxies: cloud cuts the
sunlight reaching the ground and flattens the day's temperature swing.

## Does it look like Curitiba?

Monthly climatology over 1981–2025, from the table: **1555 mm a year**, wettest
in January (220 mm), driest in August (82 mm), and no genuinely dry season —
the Cfb regime the city has. Worth checking against INMET's published normals
before quoting numbers.

Two facts that shape the modelling: **51% of days fall below 1 mm**, so the
target is strongly zero-inflated and a plain regression will be dominated by
dry days — `log1p`, or a two-stage occurrence-then-amount model, is the usual
answer. And 2.6% of days pass 25 mm, which is where the interest lies. The
wettest day on record here is 193 mm, 7 February 1996.

## The wind

A daily mean of `u10`/`v10` is a **vector** mean, and it misleads on exactly
the interesting days. Twelve hours of westerly at 4 m s⁻¹ followed by twelve
hours of easterly at 4 m s⁻¹ average to zero: the model reads "no wind" when
the wind in fact blew all day and swung around — which is what a front looks
like.

So the table carries the **scalar** mean speed beside the vector one, and their
ratio:

- **`wind_speed`** — how hard it blew.
- **`wind_const`** — how steady the direction was. 1 means the wind held one
  bearing all day, real advection of moisture; near 0 means it cancelled
  itself out. The scalar mean is never below the vector one, so the ratio sits
  in [0, 1]. A dead calm has no direction and gives NaN.
- **`wind_dir_sin` / `wind_dir_cos`** — where it came from. In degrees the
  direction jumps from 359 to 0, which would put two nearly identical winds at
  opposite ends of the scale; the sine/cosine pair has no such seam. The
  convention is meteorological: the bearing the wind blows **from**.

On a low-constancy day the direction is poorly defined. That is the point —
`wind_const` is the column telling the model how much the direction is worth.

`u10` and `v10` themselves are **not** in the table. They are an exact function
of the three columns above, and attribution methods like SHAP split credit
across duplicated inputs, so keeping both would make a real wind signal look
weaker than it is.

## What is kept out, and why

- **Nothing from day t.** Same-day cloud and temperature would be partly a
  *consequence* of the rain — `ssrd` is low because it rained — and SHAP would
  read that backwards, as if darkness caused the storm.
- **The water balance of the day**, `tp` + `pev`, would hand over the target.
  Only `pev_mm` represents the demand side.
- **The first 366 days**, since `tp_sum365` needs 365 days plus the shift.

## References

Every link opens without a login. Each entry says which part of the source is
actually used here.

**Wind aggregation**

- **EPA-454/R-99-005**, *Meteorological Monitoring Guidance for Regulatory
  Modeling Applications* (2000).
  [PDF](https://www.epa.gov/sites/default/files/2020-10/documents/mmgrma_0.pdf)
  — **used: §6.2.1** for the scalar mean wind speed (`wind_speed`), and
  **§6.2.2, equations 6.2.13–6.2.16** for the mean components `Ve`, `Vn`, the
  resultant speed `URV = (Ve² + Vn²)^½` (the numerator of `wind_const`) and the
  resultant direction `θRV` (what the sin/cos pair carries).
  **Not used**: §6.2.4, the Mitsuta method — it averages the direction *angles*
  with unwrapping, which we avoid by taking the direction of the resultant
  vector; §6.2.7–6.2.9, the Yamartino and Mardia estimates of the direction's
  standard deviation; and §6.2.17–6.2.19, the **unit-vector** average, whose
  components drop the speed weighting. `wind_const` keeps that weighting, so an
  hour of strong wind counts for more than an hour of breeze — the right choice
  when the question is how much moisture moved.
- **Singer, I. A. (1967).** *Steadiness of the Wind.* Journal of Applied
  Meteorology, 6(6), 1033–1038.
  [AMS](https://journals.ametsoc.org/view/journals/apme/6/6/1520-0450_1967_006_1033_sotw_2_0_co_2.xml)
  — **used: the definition of constancy**, the mean vector wind over the mean
  scalar wind, 1 when the direction never changes and 0 for a symmetric
  distribution. The EPA guidance defines the two averages but never names their
  ratio; this paper does, so cite it for the name and the interpretation, not
  for the formulas. ⚠ Verified from the abstract only — AMS blocks automated
  access, so confirm the authorship, pages and wording on the page itself
  before quoting.
- **Frontiers in Marine Science (2025)**, *Role of wind stress directional
  steadiness in modulating mesoscale air-sea interactions in the Western
  Arabian Sea.* [doi](https://doi.org/10.3389/fmars.2025.1619142)
  — **used: §2 Data and methods**, which builds the same ratio under the name
  *directional steadiness*: "the ratio between the vector-averaged wind stress
  and magnitude-averaged wind stress", running 0 to 1, near 1 for stable
  unidirectional wind. Evidence the construction is in current use, though
  applied to wind stress rather than wind.
- *Vector vs. Scalar Averaging of Wind Data.*
  [sodar.com](https://www.sodar.com/FYI/vector_vs_scalar.html) — **used: the
  whole page**, a short plain-language version of the same distinction with
  worked cases.
- *Circular mean.*
  [Wikipedia](https://en.wikipedia.org/wiki/Circular_mean) — **used: the
  definition**, for why a direction is carried as sine and cosine rather than
  degrees: the arithmetic mean of 359° and 1° is 180°, the wrong answer.

**Other columns**

- *Antecedent moisture.*
  [Wikipedia](https://en.wikipedia.org/wiki/Antecedent_moisture) — **used: the
  antecedent precipitation index section**, past rainfall as a proxy for how
  wet the ground already is, which is the job of `tp_sum7` … `tp_sum365`.
- *Vapour-pressure deficit.*
  [Wikipedia](https://en.wikipedia.org/wiki/Vapour-pressure_deficit) — **used:
  the definition**, `es(t2m) − es(d2m)`, and why it differs from the dewpoint
  depression.
- **INMET climatological normals.**
  [portal.inmet.gov.br/normais](https://portal.inmet.gov.br/normais) — **used:
  the Curitiba monthly totals**, to check the climatology above against
  observations.
- **IBGE mesh API.**
  [Documentation](https://servicodados.ibge.gov.br/api/docs/malhas?versao=3) —
  **used: the `municipios` and `estados` endpoints**, the boundaries
  `animate_month` draws.

ERA5-Land source and accumulation conventions: see the
[main README](../README.md#source-and-citation).