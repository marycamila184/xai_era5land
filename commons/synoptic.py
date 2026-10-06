#!/usr/bin/env python3
"""Synoptic predictors for the Curitiba table, from era5_synoptic/raw.

The AT2 table describes the surface at one cell: temperature, dewpoint,
radiation, wind. None of it says whether the atmosphere was *unstable*, how much
water the whole column held, or what the flow was doing above the friction
layer -- and those are the quantities the literature puts first for heavy
precipitation: CAPE ahead of total column water vapour, ahead of mid-level flow.

Two sources, both 6-hourly (00, 06, 12, 18 UTC) on a 0.25 deg grid, read at the
nearest cell with the same `sel(method="nearest")` the rest of the pipeline uses.
No spatial derivatives: moisture flux convergence is the physically richer
predictor, but it needs a neighbourhood, metric factors and a smoothing choice,
and a sign error in any of them is invisible in the output.

`single`  -> cape, tcwv, msl

    cape_max, cape_mean   convective available potential energy, J/kg: the energy
                          a lifted parcel gains from buoyancy. 18 UTC is 15:00 in
                          Curitiba, near peak heating, so the daily max is in
                          practice the afternoon value -- the one that matters
    tcwv_max, tcwv_mean   total column water vapour, kg/m2: all the water in the
                          column, where `d2m` only sees 2 m of it
    msl_min               lowest mean sea level pressure of the day, Pa
    msl_tend              24 h change in daily mean msl, Pa. Falling pressure is
                          the classic frontal signature
    tcwv_tend             24 h change in tcwv, kg/m2: is the column moistening
    cape_tend             24 h change in cape_max, J/kg

`plev850` -> t, q, u, v at 850 hPa, above the friction layer

    q850_mean             specific humidity, kg/kg. Measured, not derived from
                          dewpoint at an assumed pressure
    wind850_speed_mean/max, wind850_const, wind850_dir_sin/cos
                          the steering flow, by the same scalar/vector treatment
                          `scripts.utils.wind_stats` applies to the 10 m wind.
                          The 10 m wind near the Serra do Mar is terrain and
                          friction; 850 hPa is the flow that carries moisture

The two tendency columns matter out of proportion to their size: they are the
only predictors here whose value changes from one day to the next (autocorrelation
0.03 for tcwv_tend against 0.79 for tcwv_mean). A feature that is nearly constant
between neighbouring days can explain a season but never *this* day, which is
what a local explanation has to do.

TIMING -- read this before joining. Every column here describes **t-1**, matching
the convention of `curitiba_daily.parquet`, where `ssrd_wm2` and `d2m` are
already yesterday's (see the AT2 README: "tp_mm is the only column from day t").
The shift is applied here, on purpose: leaving it to the caller invites a join
that silently puts same-day CAPE against same-day rain, which would leak the
answer and look like a brilliant result. The `_lag3` columns are t-3.

    syn = pd.read_parquet("commons/data/curitiba_synoptic.parquet")
    tabela = tabela.join(syn, on="date")      # no shift needed

Run from the repository root:  uv run python -m commons.synoptic
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.utils.wind_stats import derive_wind  # noqa: E402

SYNOPTIC = Path("/media/mary-camila/Expansion/era5_synoptic/raw")
DATA = Path(__file__).resolve().parent / "data"
OUT = DATA / "curitiba_synoptic.parquet"

LAT, LON = -25.4284, -49.2733  # Praca Tiradentes; the 0.25 deg cell is -25.5, -49.25
YEARS = range(1980, 2026)


def _point(ds, keep):
    """The nearest cell, loaded, with the length-1 pressure_level axis removed."""
    out = ds[keep].sel(latitude=LAT, longitude=LON, method="nearest").load()
    return out.squeeze(drop=True)


def _frame(ds):
    return (ds.to_dataframe()
              .drop(columns=["latitude", "longitude", "number", "expver",
                             "pressure_level"], errors="ignore"))


def month(year, mon):
    """One month of synoptic columns on the day-t axis, or None if a file is absent."""
    paths = {g: SYNOPTIC / g / f"{g}_{year}_{mon:02d}.nc" for g in ("single", "plev850")}
    if not all(p.exists() for p in paths.values()):
        return None

    with xr.open_dataset(paths["single"]) as ds:
        sfc = _point(ds, ["cape", "tcwv", "msl"])
    with xr.open_dataset(paths["plev850"]) as ds:
        lev = _point(ds, ["q", "u", "v"])

    day = sfc.resample(valid_time="1D")
    hi, lo, mu = day.max(skipna=False), day.min(skipna=False), day.mean(skipna=False)
    out = xr.Dataset({"cape_max": hi.cape, "cape_mean": mu.cape,
                      "tcwv_max": hi.tcwv, "tcwv_mean": mu.tcwv,
                      "msl_min": lo.msl, "msl_mean": mu.msl})

    # 850 hPa wind by the same treatment as the 10 m wind: the vector mean for
    # direction, the scalar mean for how hard it blew, the ratio for steadiness.
    speed = np.sqrt(lev.u**2 + lev.v**2)
    lday = lev.resample(valid_time="1D")
    u_bar = lday.mean(skipna=False).u
    v_bar = lday.mean(skipna=False).v
    scalar = speed.resample(valid_time="1D").mean(skipna=False)
    out["q850_mean"] = lday.mean(skipna=False).q
    out["wind850_speed_mean"] = scalar
    out["wind850_speed_max"] = speed.resample(valid_time="1D").max(skipna=False)
    derived = derive_wind(u_bar, v_bar, scalar)
    out["wind850_const"] = derived["wind_const"]
    out["wind850_dir_sin"] = derived["wind_dir_sin"]
    out["wind850_dir_cos"] = derived["wind_dir_cos"]

    df = _frame(out)
    return df.set_index(pd.DatetimeIndex(df.index).normalize().rename("date"))


def build():
    frames = []
    for year in YEARS:
        got = [month(year, m) for m in range(1, 13)]
        frames += [f for f in got if f is not None]
        print(f"  {year}: {sum(f is not None for f in got)} months", flush=True)
    if not frames:
        raise FileNotFoundError(f"no files under {SYNOPTIC} -- is the drive mounted?")

    df = pd.concat(frames).sort_index()

    # A tendency needs a contiguous daily axis, or a gap reads as a 24 h change
    # when it is really several days.
    steps = df.index.to_series().diff().dropna()
    if not (steps == pd.Timedelta("1D")).all():
        gaps = df.index[:-1][(steps != pd.Timedelta("1D")).values]
        raise ValueError(f"daily axis is not contiguous, {len(gaps)} gaps, "
                         f"first after {gaps[0]:%Y-%m-%d}")

    df["msl_tend"] = df.msl_mean.diff()
    df["tcwv_tend"] = df.tcwv_mean.diff()
    df["cape_tend"] = df.cape_max.diff()
    df = df.drop(columns="msl_mean")

    # Three days back, kept because inside the heavy-rain days they carry more
    # than the t-1 level does -- heavier rain follows a drier airmass, the
    # signature of a front arriving rather than a persistently moist regime.
    # Only a candidate: let the cross-validation decide, it is 2 more columns.
    for c in ("cape_max", "tcwv_mean"):
        df[f"{c}_lag3"] = df[c].shift(2)   # shift(1) below makes this t-3

    # Here is the shift that makes every column describe t-1.
    return df.shift(1).dropna()


def main():
    df = build()
    DATA.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT)

    print(f"\nwrote {OUT}")
    print(f"{len(df):,} rows x {df.shape[1]} columns, "
          f"{df.index.min():%Y-%m-%d} to {df.index.max():%Y-%m-%d}")
    print(f"missing values: {int(df.isna().sum().sum())}")
    print("\nevery column describes t-1 (the _lag3 ones t-3): join without shifting")
    print()
    print(df.describe().T.to_string(float_format=lambda x: f"{x:12.3f}"))


if __name__ == "__main__":
    main()
