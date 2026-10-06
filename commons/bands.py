#!/usr/bin/env python3
"""Replace the nested rain accumulations with disjoint bands.

`build_curitiba_daily` writes tp_sum7, tp_sum30 and tp_sum90, each covering
t-k to t-1. They are nested: tp_sum30 contains the seven days of tp_sum7 and
tp_sum90 contains the thirty of tp_sum30, so last week's rain is counted in all
three. That is collinear by construction, and a Shapley value cannot split
credit between features that carry the same days (Aas, Jullum & Loland 2021).

The bands below cover the same 90 days with no overlap:

    tp_d1_7     t-7  to t-1    7 days  (identical to tp_sum7)
    tp_d8_30    t-30 to t-8   23 days
    tp_d31_90   t-90 to t-31  60 days

Differencing the nested sums is exact, so this reads the finished table rather
than the gridded files. Day t stays out, as it was already out of the parents.

Run from the repository root:  uv run python -m commons.bands
"""

from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
IN = DATA / "curitiba_daily.parquet"
OUT = DATA / "curitiba_daily_bands.parquet"

NESTED = ["tp_sum7", "tp_sum30", "tp_sum90"]
BANDS = ["tp_d1_7", "tp_d8_30", "tp_d31_90"]


def add_bands(df, drop_nested=True):
    """Add the three disjoint bands, optionally dropping their nested parents."""
    df = df.copy()
    df["tp_d1_7"] = df.tp_sum7
    df["tp_d8_30"] = df.tp_sum30 - df.tp_sum7
    df["tp_d31_90"] = df.tp_sum90 - df.tp_sum30
    return df.drop(columns=NESTED) if drop_nested else df


def main():
    df = pd.read_parquet(IN)
    out = add_bands(df)

    # The bands must add back up to the parents, and rain cannot be negative.
    both = add_bands(df, drop_nested=False)
    assert (both.tp_d1_7 + both.tp_d8_30).sub(both.tp_sum30).abs().max() < 1e-3
    assert (both[BANDS].sum(axis=1)).sub(both.tp_sum90).abs().max() < 1e-3
    assert (out[BANDS] >= -1e-6).all().all(), "negative rain in a band"

    out.to_parquet(OUT, index=False)
    print(f"wrote {OUT}")
    print(f"{len(out):,} rows x {out.shape[1]} columns")

    # The point of the change: the bands no longer share days, so they no
    # longer share information.
    print("\nSpearman between the accumulations")
    for name, cols in [("nested", NESTED), ("bands ", BANDS)]:
        c = both[cols].corr("spearman")
        off = [float(c.iloc[i, j]) for i in range(3) for j in range(i + 1, 3)]
        pairs = "  ".join(f"{v:.2f}" for v in off)
        print(f"  {name}  pairwise {pairs}   mean {sum(off)/3:.3f}")

    # Nested windows hide the decay: tp_sum90 only looked informative because
    # it contained last week.
    print("\nSpearman against tp_mm")
    for n, b in zip(NESTED, BANDS):
        print(f"  {n:9s} {both.tp_mm.corr(both[n], 'spearman'): .3f}"
              f"    {b:10s} {both.tp_mm.corr(both[b], 'spearman'): .3f}")


if __name__ == "__main__":
    main()
