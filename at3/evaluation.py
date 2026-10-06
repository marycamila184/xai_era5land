#!/usr/bin/env python3
"""Temporal folds and baselines that survive filtering the table by a threshold.

Both helpers exist because the obvious version breaks the moment rows stop
being one per day:

`TimeSeriesSplit(n_splits=5, test_size=365*4)` counts ROWS. On the full table
1460 rows is four years, which is what it was meant to be. On the table filtered
to heavy-rain days 1460 rows is 27 years, so it raises ValueError at five splits
and, worse, silently returns a fold spanning most of the record if anyone lowers
n_splits to make the error go away. `date_folds` splits on the calendar instead.

A day-of-year climatology has ~35 observations per day on the full table and ~5
on the filtered one, where 18% of days of the year have two or fewer and seven
have none. Raw per-day means then range from 10 to 79 mm around an overall 19 mm
— noise, and as a baseline it scores WORSE than a constant. `climatology`
smooths over a circular window so December meets January.

Run from the repository root:  uv run python -m at3.evaluation
"""

from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "commons" / "data"
THRESHOLD_MM = 10.0  # R10mm, the ETCCDI heavy-precipitation day


def date_folds(dates, n_splits=5, val_years=4, end=None):
    """Expanding-window folds over calendar blocks, newest block last.

    Returns a list of (train_idx, val_idx) like a scikit-learn splitter, so it
    drops straight into the loop that used TimeSeriesSplit. Validation blocks
    are val_years of calendar time regardless of how many rows that is; train
    is every row before the block.

    `end` is the exclusive upper edge of the last block. Pass it whenever the
    same folds have to line up across two frames: left to itself it anchors on
    the last row, and the filtered table's last heavy day is not the full
    table's last day, so the blocks would drift apart.
    """
    dates = pd.to_datetime(pd.Series(dates)).reset_index(drop=True)
    end = dates.max().normalize() + pd.Timedelta(days=1) if end is None else pd.Timestamp(end)
    edges = [end - pd.DateOffset(years=val_years * k) for k in range(n_splits + 1)][::-1]
    folds = []
    for start, stop in zip(edges[:-1], edges[1:]):
        train = np.where(dates < start)[0]
        val = np.where((dates >= start) & (dates < stop))[0]
        if len(train) and len(val):
            folds.append((train, val))
    return folds


def climatology(train, by="month", window=31, target="tp_mm"):
    """Mean target by calendar position, fitted on the training rows only.

    `by="month"` is the default because it is how a climatology is published —
    the INMET normals are monthly — and because twelve means are enough. On the
    filtered table it scores within 0.04 mm of the best day-of-year version
    while fitting 12 numbers instead of 366, and it has no window to justify.

    `by="doy"` smooths the daily means over a circular window; tiling the year
    three times before rolling is what makes the window wrap, so 1 January
    averages with late December rather than with nothing. Raw daily means are
    what `window=1` gives, and on the filtered table they are mostly noise.

    Returns a Series indexed by month (1-12) or day of year (1-366), to apply
    with `.map()`.
    """
    when = pd.to_datetime(train.date)
    if by == "month":
        return train.groupby(when.dt.month)[target].mean().rename_axis("month")
    mean = train.groupby(when.dt.dayofyear)[target].mean().reindex(range(1, 367))
    tiled = pd.concat([mean, mean, mean])
    smooth = tiled.rolling(window, center=True, min_periods=1).mean()
    return smooth.iloc[366:732].rename_axis("doy").rename("clim")


def baselines(train, test, target="tp_mm", by="month"):
    """The predictions every model has to beat, all fitted on train only.

    Three questions, not three alternatives: the mean asks whether the model
    learnt anything at all, the climatology whether it knows more than the
    calendar, persistence whether it knows more than "tomorrow equals today".
    The median is here for MAE only -- the mean minimises squared error and the
    median absolute error by definition, so comparing them on one metric
    measures arithmetic rather than weather.
    """
    clim = climatology(train, by=by, target=target)
    when = pd.to_datetime(test.date)
    key = when.dt.month if by == "month" else when.dt.dayofyear
    return {
        "climatology": key.map(clim).fillna(train[target].mean()).to_numpy(),
        "mean": np.full(len(test), train[target].mean()),
        "median": np.full(len(test), train[target].median()),
        "persistence": test.tp_lag1.to_numpy(),
    }


def main():
    from sklearn.metrics import mean_absolute_error, mean_squared_error

    df = pd.read_parquet(DATA / "curitiba_daily_bands.parquet")
    df = df.sort_values("date").reset_index(drop=True)

    for name, d in [("full table", df), (f"tp_mm >= {THRESHOLD_MM:g} mm", df[df.tp_mm >= THRESHOLD_MM])]:
        d = d.reset_index(drop=True)
        dev = d[d.date.dt.year <= 2014].reset_index(drop=True)
        test = d[d.date.dt.year >= 2015].reset_index(drop=True)

        print(f"\n{'='*70}\n{name}  —  {len(dev)} dev rows, {len(test)} test rows\n{'='*70}")
        for k, (tr, va) in enumerate(date_folds(dev.date, end="2015-01-01"), 1):
            span = (dev.date[va[-1]] - dev.date[va[0]]).days / 365.25
            print(f"  fold {k}: val {dev.date[va[0]]:%Y-%m-%d} to {dev.date[va[-1]]:%Y-%m-%d}"
                  f"  {span:.1f} yr, {len(va):5d} rows   train {len(tr):5d} rows")

        print(f"\n  baselines on the test years, target sd {test.tp_mm.std():.3f} mm")
        for label, pred in baselines(dev, test).items():
            print(f"    {label:12s} RMSE {mean_squared_error(test.tp_mm, pred)**.5:7.3f}"
                  f"   MAE {mean_absolute_error(test.tp_mm, pred):7.3f}")


if __name__ == "__main__":
    main()
