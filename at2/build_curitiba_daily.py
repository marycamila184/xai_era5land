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
BURN_IN = 91  # longest accumulation (90 days) plus the one day shift


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


def past_sum(series, days):
    """Total over t-k to t-1. The shift is what keeps day t out."""
    return series.shift(1).rolling(days).sum()


def build():
    tp = read_daily("tp")
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
    state["ssrd_wm2"] = ssrd.ssrd / DAY_SECONDS
    state["t2m"] = temp.t2m - 273.15
    state["t2m_min"] = temp.t2m_min - 273.15
    state["t2m_max"] = temp.t2m_max - 273.15
    state["d2m"] = temp.d2m - 273.15
    state["dpd"] = state.t2m - state.d2m

    wind = wind.reindex(state.index)
    state["wind_speed"] = wind.wind_speed
    derived = derive_wind(wind.u10, wind.v10, wind.wind_speed)
    for name in ("wind_const", "wind_dir_sin", "wind_dir_cos"):
        state[name] = derived[name]

    # One shift moves the whole block from day t to day t-1.
    df = state.shift(1)
    for k in (2, 3):
        df[f"dpd_lag{k}"] = state.dpd.shift(k)
        df[f"d2m_lag{k}"] = state.d2m.shift(k)

    df.insert(0, "tp_mm", tp.tp * 1000)
    for k in (1, 2, 3):
        df[f"tp_lag{k}"] = df.tp_mm.shift(k)
    for k in (7, 30, 90):
        df[f"tp_sum{k}"] = past_sum(df.tp_mm, k)

    # Divide by the length of the year the day is in, so every year closes the
    # circle exactly. A fixed 365.25 drifts the phase across the leap cycle.
    n_days = np.where(df.index.is_leap_year, 366, 365)
    ang = 2 * np.pi * (df.index.dayofyear - 1) / n_days
    df["day_sin"] = np.sin(ang).astype("float32")
    df["day_cos"] = np.cos(ang).astype("float32")

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
