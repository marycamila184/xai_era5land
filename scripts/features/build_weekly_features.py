#!/usr/bin/env python3
"""Build the weekly feature table for precipitation modelling.

Reads the points chosen by scripts/utils/sample_points.py, pulls only those points out
of the weekly files, converts units and derives the columns. Writes one parquet
row per point and week, with tp as the target.

Accumulated features cover weeks t-k to t-1, never week t itself, which would
put the target inside the feature. The Features section of the README lists
every column and the reasoning behind the categories.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

WEEKLY = Path("/media/mary-camila/Expansion/era5land/processed_weekly")
POINTS = Path("/media/mary-camila/Expansion/era5land/features/points.parquet")
OUT = Path("/media/mary-camila/Expansion/era5land/features/weekly_features.parquet")

GROUPS = ["tp", "pev", "ssrd", "temp", "wind"]
WEEK_SECONDS = 604800
BURN_IN = 53  # longest accumulation (52 weeks) plus the one week shift


def open_weekly():
    """Open every weekly file as one dataset, after checking the time axis."""
    ds = xr.merge([
        xr.open_mfdataset(sorted((WEEKLY / g).glob(f"{g}_*.nc")), combine="by_coords")
        for g in GROUPS
    ])

    # Rolling windows count steps, not dates. A missing week would shift the
    # window silently and produce a sum over the wrong span, so stop instead.
    steps = np.diff(ds.valid_time.values)
    if not (steps == np.timedelta64(7, "D")).all():
        bad = ds.valid_time.values[:-1][steps != np.timedelta64(7, "D")]
        raise ValueError(f"weekly axis is not contiguous, gaps after: {bad}")
    return ds


def select(ds, points):
    """Read the chosen points only.

    Indexing with DataArrays pairs each latitude with its own longitude, giving
    one point dimension of length 543 instead of the full 411 x 451 grid.
    """
    sel = ds.isel(
        latitude=xr.DataArray(points.lat_idx.values, dims="point"),
        longitude=xr.DataArray(points.lon_idx.values, dims="point"),
    )
    return sel.assign_coords(point=points.point_id.values).load()


def saturation_vapour_pressure(t_celsius):
    """Magnus formula. Returns hPa. Applied to the dewpoint it gives the actual
    vapour pressure, applied to the temperature the saturation value."""
    return 6.112 * np.exp(17.67 * t_celsius / (t_celsius + 243.5))


def past_sum(da, weeks):
    """Sum over weeks t-weeks to t-1. The shift excludes the current week."""
    return da.shift(valid_time=1).rolling(valid_time=weeks).sum()


def features(ds):
    """Convert units and derive every column. See the module docstring for the
    reasoning behind each group."""
    tp = ds.tp * 1000                       # m to mm per week
    pev = ds.pev * 1000                     # mm per week, negative as ECMWF stores it
    ssrd = ds.ssrd / WEEK_SECONDS           # J/m2 per week to W/m2
    t2m = ds.t2m - 273.15                   # K to degrees Celsius
    d2m = ds.d2m - 273.15

    e = saturation_vapour_pressure(d2m)     # actual vapour pressure, hPa
    es = saturation_vapour_pressure(t2m)    # saturation vapour pressure, hPa
    dpd = t2m - d2m                         # dewpoint depression, degrees Celsius
    bal = tp + pev                          # water balance, mm per week

    out = xr.Dataset({
        # target
        "tp": tp,

        # past rainfall
        "tp_lag1": tp.shift(valid_time=1),
        "tp_lag2": tp.shift(valid_time=2),
        "tp_lag3": tp.shift(valid_time=3),
        "tp_sum4": past_sum(tp, 4),
        "tp_sum13": past_sum(tp, 13),
        "tp_sum26": past_sum(tp, 26),
        "tp_sum52": past_sum(tp, 52),

        # moisture
        "dpd": dpd,
        "vpd": es - e,
        "e_hpa": e,
        "dpd_lag1": dpd.shift(valid_time=1),
        "dpd_lag2": dpd.shift(valid_time=2),
        "e_lag1": e.shift(valid_time=1),
        "e_lag2": e.shift(valid_time=2),

        # cloud proxies
        "ssrd": ssrd,
        # a difference in kelvin equals the same difference in degrees Celsius
        "temp_range": ds.t2m_max - ds.t2m_min,

        # wind and moisture transport
        "u10": ds.u10,
        "v10": ds.v10,
        "wind": np.sqrt(ds.u10**2 + ds.v10**2),
        "eu": e * ds.u10,
        "ev": e * ds.v10,

        # water demand, current, and past water balance
        "pev": pev,
        "bal_sum4": past_sum(bal, 4),
        "bal_sum13": past_sum(bal, 13),
    })

    # seasonality
    doy = ds.valid_time.dt.dayofyear
    out["week_sin"] = np.sin(2 * np.pi * doy / 365.25)
    out["week_cos"] = np.cos(2 * np.pi * doy / 365.25)

    return out.isel(valid_time=slice(BURN_IN, None))


def to_table(ds, points):
    """Flatten point and week into rows, and put the identifiers first."""
    df = ds.to_dataframe().reset_index()
    df = df.rename(columns={"point": "point_id", "valid_time": "week"})
    # the grid coordinates ride along with the selection and duplicate lat/lon
    df = df.drop(columns=["latitude", "longitude"])
    df = df.merge(points[["point_id", "lat", "lon", "block"]], on="point_id")

    df["block"] = df["block"].astype("category")  # 543+ repeats of a short string

    keys = ["point_id", "lat", "lon", "block", "week"]
    values = [c for c in df.columns if c not in keys]
    df[values] = df[values].astype("float32")

    return df[keys + values].sort_values(["point_id", "week"], ignore_index=True)


def main():
    points = pd.read_parquet(POINTS)
    print(f"points: {len(points)}")

    ds = open_weekly()
    print(f"weeks: {ds.sizes['valid_time']} "
          f"({ds.valid_time.values[0]} to {ds.valid_time.values[-1]})")

    table = to_table(features(select(ds, points)), points)
    print(f"table: {len(table)} rows x {table.shape[1]} columns")
    print(f"missing values: {int(table.isna().sum().sum())}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(OUT, index=False)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
