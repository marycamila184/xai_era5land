#!/usr/bin/env python3
"""Build the daily table for the ERA5-Land grid cell over Curitiba.

One row per UTC day, target tp_mm. Everything but the wind comes from
processed_daily/; the wind is rebuilt from the hourly raw files so the table
carries the scalar mean speed and the constancy, not just the vector mean.

Lags and accumulations cover days t-k to t-1, never day t, which would put the
target inside the feature.

Run from the repository root:  uv run python -m at2.build_curitiba_daily
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.utils.wind_stats import derive_wind  # noqa: E402

RAW = Path("/media/mary-camila/Expansion/era5land/raw")
DAILY = Path("/media/mary-camila/Expansion/era5land/processed_daily")
DATA = Path(__file__).resolve().parent / "data"
OUT = DATA / "curitiba_daily.parquet"
WIND_CACHE = DATA / "wind_daily.parquet"  # the slow read; delete it to redo

# Curitiba, Praca Tiradentes. The nearest ERA5-Land cell is -25.4, -49.3.
LAT, LON = -25.4284, -49.2733
YEARS = range(1980, 2026)
DAY_SECONDS = 86400
BURN_IN = 366  # longest accumulation (365 days) plus the one day shift


def at_point(ds):
    """Collapse the grid to the cell holding Curitiba."""
    return ds.sel(latitude=LAT, longitude=LON, method="nearest")


def to_daily_frame(ds):
    ds = ds.drop_vars(["number", "expver", "latitude", "longitude"], errors="ignore")
    df = ds.to_dataframe()
    return df.set_index(pd.DatetimeIndex(df.index).normalize().rename("date"))


def read_daily(group):
    """One processed_daily group at the point, indexed by day."""
    files = sorted((DAILY / group).glob(f"{group}_*.nc"))
    if not files:
        raise FileNotFoundError(f"no daily files in {DAILY / group}")
    print(f"  daily {group}: {len(files)} files")
    ds = xr.open_mfdataset(files, combine="by_coords")
    return to_daily_frame(at_point(ds).load())


def read_hourly_wind():
    """Daily wind at the point, from the hourly raw files. Same reducer as the
    grid-wide pipeline. Slow -- 552 files, one cell each -- so it is cached."""
    from scripts.utils.wind_stats import daily_wind

    if WIND_CACHE.exists():
        print(f"  wind: reusing {WIND_CACHE.name}")
        return pd.read_parquet(WIND_CACHE)

    months = []
    for year in YEARS:
        for month in range(1, 13):
            path = RAW / "wind" / f"wind_{year}_{month:02d}.nc"
            if not path.exists():
                print(f"  missing: {path.name}")
                continue
            with xr.open_dataset(path) as ds:
                months.append(to_daily_frame(daily_wind(at_point(ds)[["u10", "v10"]]).load()))
        print(f"  wind {year}")

    wind = pd.concat(months)[["u10", "v10", "wind_speed"]]
    DATA.mkdir(parents=True, exist_ok=True)
    wind.to_parquet(WIND_CACHE)
    return wind


def saturation_vapour_pressure(t_celsius):
    """Magnus formula, hPa. On the dewpoint: vapour present. On the
    temperature: the most the air could hold."""
    return 6.112 * np.exp(17.67 * t_celsius / (t_celsius + 243.5))


def past_sum(series, days):
    """Total over t-k to t-1. The shift is what keeps day t out."""
    return series.shift(1).rolling(days).sum()


def build():
    tp = read_daily("tp")
    pev = read_daily("pev")
    ssrd = read_daily("ssrd")
    temp = read_daily("temp")
    wind = read_hourly_wind()

    # A contiguous daily axis is what makes every shift below mean "yesterday".
    steps = tp.index.to_series().diff().dropna()
    if not (steps == pd.Timedelta("1D")).all():
        gaps = tp.index[:-1][(steps != pd.Timedelta("1D")).values]
        raise ValueError(f"daily axis is not contiguous, gaps after: {list(gaps)}")

    # State of the atmosphere on the day each row describes, before any shift.
    state = pd.DataFrame(index=tp.index.copy())
    state["pev_mm"] = pev.pev * 1000
    state["ssrd_wm2"] = ssrd.ssrd / DAY_SECONDS
    state["t2m"] = temp.t2m - 273.15
    state["t2m_min"] = temp.t2m_min - 273.15
    state["t2m_max"] = temp.t2m_max - 273.15
    state["temp_range"] = state.t2m_max - state.t2m_min
    state["d2m"] = temp.d2m - 273.15
    state["dpd"] = state.t2m - state.d2m
    state["e_hpa"] = saturation_vapour_pressure(state.d2m)
    state["vpd"] = saturation_vapour_pressure(state.t2m) - state.e_hpa

    wind = wind.reindex(state.index)
    state["wind_speed"] = wind.wind_speed
    # u10 and v10 are dropped: they are an exact function of the three columns
    # below, and duplicated inputs split the attribution in SHAP.
    derived = derive_wind(wind.u10, wind.v10, wind.wind_speed)
    for name in ("wind_const", "wind_dir_sin", "wind_dir_cos"):
        state[name] = derived[name]

    # One shift moves the whole block from day t to day t-1.
    df = state.shift(1)
    for k in (2, 3):
        df[f"dpd_lag{k}"] = state.dpd.shift(k)
        df[f"e_lag{k}"] = state.e_hpa.shift(k)

    df.insert(0, "tp_mm", tp.tp * 1000)
    for k in (1, 2, 3):
        df[f"tp_lag{k}"] = df.tp_mm.shift(k)
    for k in (7, 30, 90, 365):
        df[f"tp_sum{k}"] = past_sum(df.tp_mm, k)

    doy = df.index.dayofyear
    df["day_sin"] = np.sin(2 * np.pi * doy / 365.25)
    df["day_cos"] = np.cos(2 * np.pi * doy / 365.25)

    # The longest accumulation is undefined over the first year.
    return df.iloc[BURN_IN:].reset_index()


def main():
    df = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(f"\nwrote {OUT}")
    print(f"{len(df):,} rows x {df.shape[1]} columns, "
          f"{df.date.min():%Y-%m-%d} to {df.date.max():%Y-%m-%d}")
    print(f"missing values: {int(df.isna().sum().sum())}")
    print(df.drop(columns="date").describe().T.to_string(float_format=lambda x: f"{x:8.3f}"))


if __name__ == "__main__":
    main()
