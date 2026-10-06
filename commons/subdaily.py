#!/usr/bin/env python3
"""Sub-daily extremes the point pipeline computes and then discards.

`scripts.utils.wind_stats.daily_wind` already returns `wind_max`, the daily
maximum of the scalar speed, and `build_curitiba_daily.read_hourly_wind` drops it
on the way to the cache:

    wind = pd.concat(months)[["u10", "v10", "wind_speed"]]

A 24 h mean speed is the wrong summary for heavy rain: a front crosses in a few
hours and the mean averages the gust away, which is the same reason the table
already carries `t2m_max` beside `t2m`. This module keeps the maximum, and the
dewpoint range for the same reason -- a dewpoint that swings several degrees in a
day is an airmass change, which a daily mean cannot show.

    wind_max    daily maximum of sqrt(u10^2 + v10^2), m/s
    d2m_range   daily max minus min of the 2 m dewpoint, degrees C

Reading the hourly files is slow -- 552 of them, one cell each -- so the result
is written once and joined like any other table. Nothing here touches
`curitiba_daily.parquet` or its wind cache.

TIMING -- both columns describe **t-1**, matching `curitiba_daily.parquet`, where
`ssrd_wm2` and `d2m` are already yesterday's (see the AT2 README: "tp_mm is the
only column from day t"). The shift is applied here rather than left to the
caller: a join without it would put the same day's gust against the same day's
rain, which leaks the answer and looks like a brilliant result.

    sub = pd.read_parquet("commons/data/curitiba_subdaily.parquet")
    tabela = tabela.join(sub, on="date")      # no shift needed

Run from the repository root:  uv run python -m commons.subdaily
"""

import sys
from pathlib import Path

import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.utils.wind_stats import daily_wind  # noqa: E402

RAW = Path("/media/mary-camila/Expansion/era5land/raw")
DATA = Path(__file__).resolve().parent / "data"
OUT = DATA / "curitiba_subdaily.parquet"

LAT, LON = -25.4284, -49.2733
YEARS = range(1980, 2026)


def _at_point(ds):
    return ds.sel(latitude=LAT, longitude=LON, method="nearest")


def _to_daily_frame(ds):
    df = ds.to_dataframe().drop(
        columns=["latitude", "longitude", "number", "expver"], errors="ignore")
    return df.set_index(pd.DatetimeIndex(df.index).normalize().rename("date"))


def month(year, mon):
    """wind_max and d2m_range for one month, or None if either file is missing."""
    wind_path = RAW / "wind" / f"wind_{year}_{mon:02d}.nc"
    temp_path = RAW / "temp" / f"temp_{year}_{mon:02d}.nc"
    if not (wind_path.exists() and temp_path.exists()):
        return None

    with xr.open_dataset(wind_path) as dw:
        wind = _to_daily_frame(daily_wind(_at_point(dw)[["u10", "v10"]]).load())

    with xr.open_dataset(temp_path) as dt:
        d2m = _at_point(dt)[["d2m"]].load().d2m.resample(valid_time="1D")
        rng = (d2m.max(skipna=False) - d2m.min(skipna=False)).rename("d2m_range")
        temp = _to_daily_frame(rng.to_dataset())

    return wind[["wind_max"]].join(temp)


def build():
    frames = []
    for year in YEARS:
        got = [month(year, m) for m in range(1, 13)]
        frames += [f for f in got if f is not None]
        print(f"  {year}: {sum(f is not None for f in got)} months", flush=True)
    if not frames:
        raise FileNotFoundError(f"no raw files under {RAW} -- is the drive mounted?")

    df = pd.concat(frames).sort_index()

    # The shift that makes both columns describe t-1. A gap in the daily axis
    # would make it mean t-2 or worse, so check before relying on it.
    steps = df.index.to_series().diff().dropna()
    if not (steps == pd.Timedelta("1D")).all():
        gaps = df.index[:-1][(steps != pd.Timedelta("1D")).values]
        raise ValueError(f"daily axis is not contiguous, {len(gaps)} gaps, "
                         f"first after {gaps[0]:%Y-%m-%d}")

    return df.shift(1).dropna()


def main():
    df = build()
    DATA.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT)

    print(f"\nwrote {OUT}")
    print(f"{len(df):,} rows x {df.shape[1]} columns, "
          f"{df.index.min():%Y-%m-%d} to {df.index.max():%Y-%m-%d}")
    print(f"missing values: {int(df.isna().sum().sum())}")
    print()
    print(df.describe().T.to_string(float_format=lambda x: f"{x:10.3f}"))


if __name__ == "__main__":
    main()
