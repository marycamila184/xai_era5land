#!/usr/bin/env python3
"""Choose the grid points that feature tables are built on.

Draws a spread out subset of land points: stratified in 5 degree blocks, at
least MIN_DIST_CELLS apart, with a fixed seed. See the Features section of the
README for why the full grid is not used.

The land mask does not depend on the time resolution, so the same points serve
the weekly table and any daily one. It is read from a weekly file only because
that file is small.

Writes one parquet row per chosen point, and a map of the draw to figures/.
"""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import xarray as xr

matplotlib.use("Agg")  # write the figure to a file, no display needed
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402

WEEKLY = Path("/media/mary-camila/Expansion/era5land/processed_weekly")
OUT = Path("/media/mary-camila/Expansion/era5land/features/points.parquet")
# the map is small and worth versioning, so it goes in the repo, not the drive
FIGURE = Path(__file__).resolve().parents[2] / "figures" / "sampled_points.png"

MASK_YEAR = 2000        # the land mask does not change, so any year works
BLOCK_DEG = 5.0         # size of a stratum, in degrees
POINTS_PER_BLOCK = 80   # a 5 degree block holds at most ~100 points at 0.5 degrees apart
MIN_DIST_CELLS = 5      # 5 cells of 0.1 degree = 0.5 degrees
SEED = 42


def land_mask():
    """Grid points that have data in every week of MASK_YEAR."""
    tp = xr.open_dataset(WEEKLY / "tp" / f"tp_{MASK_YEAR}.nc").tp
    return tp.notnull().all("valid_time")


def block_id(lat, lon):
    """Name of the 5 degree block a coordinate falls in, from its lower corner."""
    lat0 = np.floor(lat / BLOCK_DEG) * BLOCK_DEG
    lon0 = np.floor(lon / BLOCK_DEG) * BLOCK_DEG
    return f"{lat0:+.0f}_{lon0:+.0f}"


def draw(mask):
    """Draw points block by block, skipping any candidate that is too close.

    Distances are measured in grid cells against every point accepted so far,
    including points from other blocks, so the rule also holds across block
    borders. A block with little land yields fewer points than the quota.
    """
    lat = mask.latitude.values
    lon = mask.longitude.values
    i_idx, j_idx = np.nonzero(mask.values)

    blocks = np.array([block_id(lat[i], lon[j]) for i, j in zip(i_idx, j_idx)])

    rng = np.random.default_rng(SEED)

    # Accepted positions live in a preallocated array so each candidate costs
    # one vectorised distance pass instead of rebuilding a list every time.
    limit = POINTS_PER_BLOCK * len(set(blocks))
    acc = np.empty((limit, 2), dtype=float)
    acc_block = []
    n = 0

    for block in sorted(set(blocks)):
        candidates = np.nonzero(blocks == block)[0]
        rng.shuffle(candidates)

        taken = 0
        for c in candidates:
            if taken == POINTS_PER_BLOCK:
                break
            i, j = i_idx[c], j_idx[c]
            if n and np.hypot(acc[:n, 0] - i, acc[:n, 1] - j).min() < MIN_DIST_CELLS:
                continue
            acc[n] = (i, j)
            acc_block.append(block)
            n += 1
            taken += 1

        print(f"  {block}: {taken} of {len(candidates)} land points")

    i_sel = acc[:n, 0].astype(int)
    j_sel = acc[:n, 1].astype(int)
    return pd.DataFrame({
        "point_id": np.arange(n, dtype="int32"),
        "lat": lat[i_sel].astype("float32"),
        "lon": lon[j_sel].astype("float32"),
        "block": pd.Categorical(acc_block),
        # grid positions, so the feature script can read the points directly
        "lat_idx": i_sel.astype("int32"),
        "lon_idx": j_sel.astype("int32"),
    })


def plot(mask, points):
    """Map of the draw: land in grey, the block grid, and the chosen points."""
    lon = mask.longitude.values
    lat = mask.latitude.values
    extent = [lon.min(), lon.max(), lat.min(), lat.max()]

    fig, ax = plt.subplots(figsize=(7, 7.4), dpi=150)
    ax.imshow(mask.where(mask), extent=extent, origin="upper",
              cmap=ListedColormap(["#dcdcd8"]), interpolation="nearest")

    # the strata, so the stratification is visible rather than asserted
    for x in np.arange(np.floor(lon.min() / BLOCK_DEG) * BLOCK_DEG,
                       lon.max() + BLOCK_DEG, BLOCK_DEG):
        ax.axvline(x, color="#ffffff", lw=0.8, zorder=2)
    for y in np.arange(np.floor(lat.min() / BLOCK_DEG) * BLOCK_DEG,
                       lat.max() + BLOCK_DEG, BLOCK_DEG):
        ax.axhline(y, color="#ffffff", lw=0.8, zorder=2)

    ax.scatter(points.lon, points.lat, s=4, c="#1a6ba8", linewidths=0, zorder=3)

    ax.set_xlim(lon.min(), lon.max())
    ax.set_ylim(lat.min(), lat.max())
    ax.set_aspect("equal")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.tick_params(labelsize=9, colors="#555555")
    for side in ax.spines.values():
        side.set_visible(False)

    ax.set_title("Sampled grid points", fontsize=13, loc="left", pad=30)
    ax.text(0, 1.015,
            f"{len(points):,} points in {points.block.nunique()} blocks of "
            f"{BLOCK_DEG:.0f}\u00b0, at least {MIN_DIST_CELLS / 10:.1f}\u00b0 apart",
            transform=ax.transAxes, fontsize=9.5, color="#666666")

    fig.tight_layout()
    fig.savefig(FIGURE, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main():
    mask = land_mask()
    print(f"land points: {int(mask.sum())} of {mask.size}")

    points = draw(mask)
    print(f"sampled {len(points)} points in {points.block.nunique()} blocks")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    FIGURE.parent.mkdir(parents=True, exist_ok=True)
    points.to_parquet(OUT, index=False)
    print(f"wrote {OUT}")

    plot(mask, points)
    print(f"wrote {FIGURE}")


if __name__ == "__main__":
    main()
