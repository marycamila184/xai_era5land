#!/usr/bin/env python3
"""Aggregate hourly ERA5-Land files into daily files.

Accumulated variables (tp, pev, ssrd) reset at 01 UTC, so the daily total of
day D is the value stamped 00 UTC of day D+1 (read from the next month's file
when D is the last day of the month). Instantaneous variables are averaged --
except the wind, which also keeps the scalar mean and the daily maximum of the
speed, since a vector mean alone hides a day of shifting direction. See
scripts/utils/wind_stats.py.
"""

import sys
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.utils.wind_stats import daily_wind  # noqa: E402

RAW = Path("/media/mary-camila/Expansion/era5land/raw")
OUT = Path("/media/mary-camila/Expansion/era5land/processed_daily")

ACCUMULATED = ["tp", "pev", "ssrd"]
INSTANTANEOUS = ["temp", "wind"]
GROUPS = ACCUMULATED + INSTANTANEOUS
YEARS = range(1980, 2026)


def open_month(group, year, month):
    path = RAW / group / f"{group}_{year}_{month:02d}.nc"
    if not path.exists():
        return None
    ds = xr.open_dataset(path, chunks={})
    return ds.drop_vars(["number", "expver"], errors="ignore")


def daily_total(ds, group, year, month):
    nxt = open_month(group, year + (month == 12), month % 12 + 1)
    if nxt is None:
        print(f"  warning: no next month, last day of {year}-{month:02d} skipped")
    else:
        ds = xr.concat([ds, nxt.isel(valid_time=[0])], dim="valid_time")

    daily = ds.isel(valid_time=(ds.valid_time.dt.hour == 0).values)
    daily["valid_time"] = daily.valid_time - np.timedelta64(1, "D")
    return daily.sel(valid_time=f"{year}-{month:02d}")


def daily_mean(ds):
    out = ds.resample(valid_time="1D").mean()
    if "t2m" in ds:
        out["t2m_min"] = ds.t2m.resample(valid_time="1D").min()
        out["t2m_max"] = ds.t2m.resample(valid_time="1D").max()
    return out


def aggregate(ds, group, year, month):
    if group in ACCUMULATED:
        return daily_total(ds, group, year, month)
    if group == "wind":
        return daily_wind(ds)
    return daily_mean(ds)


def process(group, year, month):
    path = OUT / group / f"{group}_{year}_{month:02d}.nc"
    if path.exists():
        return
    
    ds = open_month(group, year, month)
    if ds is None:
        print(f"  missing: {group}_{year}_{month:02d}.nc")
        return

    print(f"  {path.name}")
    daily = aggregate(ds, group, year, month)

    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = {v: {"zlib": True, "complevel": 4, "dtype": "float32"} for v in daily.data_vars}
    daily.to_netcdf(path, encoding=encoding)


def main():
    xr.set_options(keep_attrs=True)
    for group in GROUPS:
        print(group)
        for year in YEARS:
            for month in range(1, 13):
                process(group, year, month)


if __name__ == "__main__":
    main()
