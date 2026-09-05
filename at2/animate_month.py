#!/usr/bin/env python3
"""Animate one month of ERA5-Land over the Curitiba region.

Three maps side by side -- rain, temperature, wind -- one frame per day, with
the grid cell the table is built from marked. Unlike the table, this reads the
full grid, so it shows the weather the point sits inside.

    uv run python -m at2.animate_month 2025-01
    uv run python -m at2.animate_month 2025-01 0.6    # tighter window

The second argument is the half-width of the window in degrees. Curitiba's
municipal boundary spans about 0.2 x 0.3 deg and the grid is 0.1 deg, so the
city itself is only some six cells: below ~0.5 there is nothing left to see.
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from at2 import boundaries  # noqa: E402
from at2.build_curitiba_daily import LAT, LON, RAW, DAILY  # noqa: E402
from scripts.utils.wind_stats import daily_wind  # noqa: E402

FIGURES = Path(__file__).resolve().parents[1] / "figures"
HALF_SPAN = 2.0  # default degrees either side of the point

INK, MUTED, SURFACE = "#0b0b0b", "#52514e", "#fcfcfb"
RAIN = LinearSegmentedColormap.from_list("rain", ["#f4f7fb", "#9dc3ec", "#2a78d6", "#12305c"])
TEMP = LinearSegmentedColormap.from_list("temp", ["#fdf1ea", "#f6b48f", "#eb6834", "#8e2f0d"])
WIND = LinearSegmentedColormap.from_list("wind", ["#f0faf6", "#8fd9be", "#1baf7a", "#0a5137"])


def nice_levels(low, high, count=10):
    """Roughly `count` bins with a round step, so the colourbar reads cleanly."""
    raw = (high - low) / count
    magnitude = 10 ** np.floor(np.log10(raw))
    step = next(m for m in (1, 2, 2.5, 5, 10) if raw <= m * magnitude) * magnitude
    return np.arange(np.floor(low / step) * step, high + step, step)


def box(ds, span):
    return ds.sel(latitude=slice(LAT + span, LAT - span),
                  longitude=slice(LON - span, LON + span))


def load(month, span):
    year, mm = month.split("-")

    def daily(group):
        path = DAILY / group / f"{group}_{year}_{mm}.nc"
        if not path.exists():
            sys.exit(f"missing {path}")
        return box(xr.open_dataset(path), span)

    tp = daily("tp").tp * 1000
    t2m = daily("temp").t2m - 273.15

    # The daily wind files may still hold only the vector mean, so reduce the
    # month's hourly file here -- it is a single file.
    hourly = RAW / "wind" / f"wind_{year}_{mm}.nc"
    if not hourly.exists():
        sys.exit(f"missing {hourly}")
    with xr.open_dataset(hourly) as ds:
        wind = daily_wind(box(ds, span)[["u10", "v10"]]).load()

    n = min(tp.sizes["valid_time"], t2m.sizes["valid_time"], wind.sizes["valid_time"])
    return tp.isel(valid_time=slice(n)), t2m.isel(valid_time=slice(n)), wind.isel(valid_time=slice(n))


def panel(ax, field, cmap, title, unit, levels, geo, city_color=INK):
    """Draw the first frame and return the image, ready to be updated.

    Discrete levels, not a continuous ramp: a GIF holds 256 colours, and a
    smooth ramp quantises into visible banding. They also make a day easy to
    compare against the one before it.
    """
    image = ax.pcolormesh(field.longitude, field.latitude, field.isel(valid_time=0),
                          cmap=cmap, norm=BoundaryNorm(levels, cmap.N),
                          shading="nearest")
    boundaries.draw(ax, *geo, city_color=city_color)
    ax.plot(LON, LAT, marker="*", markersize=11, color=INK,
            markeredgecolor="white", markeredgewidth=0.8, zorder=8)

    # The outlines run far past the window; the data defines the frame.
    ax.set_xlim(float(field.longitude.min()), float(field.longitude.max()))
    ax.set_ylim(float(field.latitude.min()), float(field.latitude.max()))
    ax.set_title(title, color=INK, fontsize=11, loc="left", pad=8)
    ax.set_aspect("equal")
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    for side in ax.spines.values():
        side.set_visible(False)

    bar = ax.figure.colorbar(image, ax=ax, orientation="horizontal",
                             pad=0.06, aspect=28, fraction=0.05,
                             ticks=levels[::2], spacing="uniform")
    bar.set_label(unit, color=MUTED, fontsize=9)
    bar.ax.tick_params(colors=MUTED, labelsize=8, length=0)
    bar.outline.set_visible(False)
    return image


def main():
    month = sys.argv[1] if len(sys.argv) > 1 else "2025-01"
    span = float(sys.argv[2]) if len(sys.argv) > 2 else HALF_SPAN
    tp, t2m, wind = load(month, span)
    speed = wind.wind_speed
    days = tp.valid_time.dt.strftime("%d/%m/%Y").values

    fig, axes = plt.subplots(1, 3, figsize=(13.5, 5.2), constrained_layout=True)
    fig.patch.set_facecolor(SURFACE)
    for ax in axes:
        ax.set_facecolor(SURFACE)

    # Fixed scales across the month, or the colours would mean something new in
    # every frame. Rain gets uneven steps because it is heavily skewed: most
    # days are near zero and one storm would flatten the other thirty.
    rain_levels = np.array([0, 1, 2, 5, 10, 20, 35, 50, 75, 100,
                            max(110, float(np.nanmax(tp)))])
    geo = boundaries.outlines()
    images = [
        panel(axes[0], tp, RAIN, "Chuva do dia", "mm/dia", rain_levels, geo),
        panel(axes[1], t2m, TEMP, "Temperatura a 2 m", "°C",
              nice_levels(float(t2m.min()), float(t2m.max())), geo),
        # White reads better than ink over the dark end of the wind ramp.
        panel(axes[2], speed, WIND, "Vento a 10 m", "m s⁻¹ (média escalar)",
              nice_levels(0, float(speed.max())), geo, city_color="#ffffff"),
    ]

    # Arrows show where the mean wind blew, thinned so they stay readable.
    step = max(1, round(speed.sizes["longitude"] / 12))
    thin = dict(latitude=slice(None, None, step), longitude=slice(None, None, step))
    u, v = wind.u10.isel(**thin), wind.v10.isel(**thin)
    unit = np.hypot(u, v).where(lambda x: x > 0)
    arrows = axes[2].quiver(u.longitude, u.latitude,
                            (u / unit).isel(valid_time=0), (v / unit).isel(valid_time=0),
                            color="white", scale=26, width=0.006, zorder=4)

    title = fig.suptitle("", color=INK, fontsize=13, x=0.006, ha="left")

    def draw(i):
        for image, field in zip(images, (tp, t2m, speed)):
            image.set_array(field.isel(valid_time=i).values.ravel())
        arrows.set_UVC((u / unit).isel(valid_time=i), (v / unit).isel(valid_time=i))
        title.set_text(f"Curitiba e arredores — {days[i]} (dia UTC).  "
                       "Contorno do município e divisas estaduais (IBGE); "
                       "★ é a célula da tabela")
        return [*images, arrows, title]

    anim = FuncAnimation(fig, draw, frames=len(days), interval=450, blit=False)
    FIGURES.mkdir(exist_ok=True)
    suffix = "" if span == HALF_SPAN else f"_{span:g}deg"
    out = FIGURES / f"curitiba_map_{month.replace('-', '_')}{suffix}.gif"
    anim.save(out, writer=PillowWriter(fps=2.2), dpi=110,
              savefig_kwargs={"facecolor": SURFACE})
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
