#!/usr/bin/env python3
"""Aggregate daily ERA5-Land files into weekly files.

Weeks are 7-day bins anchored to Monday (ISO weeks), labelled by their Monday
and written one file per year -- a week belongs to the year of its Monday, so
building a year also needs January of the next one. Accumulated variables
(tp, pev, ssrd) are summed, instantaneous ones averaged. Weeks with fewer than
7 daily values are dropped, so every weekly value covers a full week.
"""

from pathlib import Path

import xarray as xr

DAILY = Path("/media/mary-camila/Expansion/era5land/processed_daily")
OUT = Path("/media/mary-camila/Expansion/era5land/processed_weekly")

ACCUMULATED = ["tp", "pev", "ssrd"]
INSTANTANEOUS = ["temp", "wind"]
GROUPS = ACCUMULATED + INSTANTANEOUS
YEARS = range(1980, 2026)


def open_year(group, year):
    months = [(year, m) for m in range(1, 13)] + [(year + 1, 1)]
    paths = [DAILY / group / f"{group}_{y}_{m:02d}.nc" for y, m in months]

    missing = [p.name for p in paths if not p.exists()]
    if missing:
        print(f"  warning: missing {', '.join(missing)}")

    paths = [p for p in paths if p.exists()]
    if not paths:
        return None
    return xr.open_mfdataset(paths, combine="by_coords", chunks={})


def weeks(obj):
    # W-MON bin edges are Mondays; closed/label left makes each bin Mon-Sun,
    # labelled by its Monday
    return obj.resample(valid_time="W-MON", closed="left", label="left")


def aggregate(ds, group):
    # skipna=False keeps the ocean mask: an all-NaN cell stays NaN, not 0
    if group in ACCUMULATED:
        return weeks(ds).sum(skipna=False)

    out = weeks(ds).mean(skipna=False)
    if "t2m_min" in ds:
        out["t2m_min"] = weeks(ds.t2m_min).min(skipna=False)
        out["t2m_max"] = weeks(ds.t2m_max).max(skipna=False)
    return out


def process(group, year):
    path = OUT / group / f"{group}_{year}.nc"
    if path.exists():
        return

    ds = open_year(group, year)
    if ds is None:
        print(f"  missing: no daily files for {group} {year}")
        return

    print(f"  {path.name}")
    weekly = aggregate(ds, group)

    n_days = weeks(xr.ones_like(ds.valid_time, dtype=float)).sum()
    weekly = weekly.isel(valid_time=((n_days == 7) & (n_days.valid_time.dt.year == year)).values)
    if weekly.sizes["valid_time"] == 0:
        print(f"  warning: no complete week in {year}, nothing written")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = {v: {"zlib": True, "complevel": 4, "dtype": "float32"} for v in weekly.data_vars}
    weekly.to_netcdf(path, encoding=encoding)


def main():
    xr.set_options(keep_attrs=True)
    for group in GROUPS:
        print(group)
        for year in YEARS:
            process(group, year)


if __name__ == "__main__":
    main()
