"""Wind aggregation that survives a change of direction.

A mean of u10/v10 is a vector mean, so a day whose wind reverses averages to
near zero and reads as "no wind". Keeping the scalar mean speed beside it fixes
that: wind_const = wind_res / wind_speed is 1 for a steady direction and 0 for
one that cancels itself out.

Only STORED goes to disk; DERIVED are exact functions of it.
"""

import numpy as np

__all__ = ["STORED", "DERIVED", "daily_wind", "weekly_wind", "derive_wind"]

STORED = ["u10", "v10", "wind_speed", "wind_max"]
DERIVED = ["wind_res", "wind_const", "wind_dir_sin", "wind_dir_cos"]


def _speed(ds):
    return np.sqrt(ds.u10**2 + ds.v10**2)


def daily_wind(ds):
    """Hourly u10/v10 -> daily STORED. skipna=False keeps the ocean NaN."""
    speed = _speed(ds)
    out = ds[["u10", "v10"]].resample(valid_time="1D").mean(skipna=False)
    out["wind_speed"] = speed.resample(valid_time="1D").mean(skipna=False)
    out["wind_max"] = speed.resample(valid_time="1D").max(skipna=False)
    return out


def weekly_wind(ds, weeks):
    """Daily STORED -> weekly, given a resampler factory.

    Every day holds 24 hours, so the mean of the daily means is the mean over
    the week -- for the scalar speed as much as for the components.
    """
    out = weeks(ds[["u10", "v10", "wind_speed"]]).mean(skipna=False)
    out["wind_max"] = weeks(ds.wind_max).max(skipna=False)
    return out


def derive_wind(u10, v10, wind_speed):
    """DERIVED columns from the stored ones, as a dict. Takes numpy, pandas or
    xarray. Direction is meteorological -- the bearing the wind blows *from* --
    and is carried as sin/cos to avoid the jump from 359 to 0 degrees."""
    resultant = np.sqrt(u10**2 + v10**2)
    # A dead calm has no direction: 0/0 is NaN, and the resultant can never
    # exceed the scalar mean, so this is the only division by zero possible.
    with np.errstate(invalid="ignore", divide="ignore"):
        constancy = resultant / wind_speed
    direction = np.radians((270.0 - np.degrees(np.arctan2(v10, u10))) % 360.0)
    return {
        "wind_res": resultant,
        "wind_const": constancy,
        "wind_dir_sin": np.sin(direction),
        "wind_dir_cos": np.cos(direction),
    }
