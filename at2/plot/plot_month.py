#!/usr/bin/env python3
"""Plot one month of the Curitiba table: rain, temperature and wind.

    uv run python -m at2.plot.plot_month 2025-01
"""

import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, Normalize

TABLE = Path(__file__).resolve().parents[1] / "data" / "curitiba_daily.parquet"
FIGURES = Path(__file__).resolve().parents[2] / "figures"

RAIN = "#2a78d6"
TEMP = "#eb6834"
WIND = "#1baf7a"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
CONSTANCY = LinearSegmentedColormap.from_list("constancy", ["#dce8f8", RAIN, "#123a68"])

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]


def style(ax):
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))


def load(month):
    df = pd.read_parquet(TABLE)
    df = df[df.date.dt.strftime("%Y-%m") == month]
    if df.empty:
        sys.exit(f"{month} is not in {TABLE.name}")
    return df.reset_index(drop=True)


def plot_rain(ax, df):
    ax.bar(df.date, df.tp_mm, width=0.75, color=RAIN, linewidth=0)
    ax.set_title("Precipitação, o alvo", color=INK, fontsize=11, loc="left", pad=10)
    ax.set_ylabel("mm/dia", color=MUTED, fontsize=9)

    # The wettest day is the one a reader looks for; label it and nothing else.
    peak = df.loc[df.tp_mm.idxmax()]
    ax.annotate(f"{peak.tp_mm:.0f} mm", (peak.date, peak.tp_mm),
                textcoords="offset points", xytext=(0, 6), ha="center",
                fontsize=9, color=INK)
    ax.set_ylim(0, df.tp_mm.max() * 1.25)


def plot_temp(ax, df):
    ax.fill_between(df.date, df.t2m_min, df.t2m_max, color=TEMP, alpha=0.18,
                    linewidth=0, label="mín–máx")
    ax.plot(df.date, df.t2m, color=TEMP, linewidth=2, label="média")
    ax.set_title("Temperatura a 2 m, do dia anterior", color=INK, fontsize=11,
                 loc="left", pad=10)
    ax.set_ylabel("°C", color=MUTED, fontsize=9)
    legend = ax.legend(frameon=False, fontsize=9, loc="lower left", labelcolor=MUTED)
    legend.set_title(None)


def plot_wind(ax, df):
    ax.plot(df.date, df.wind_speed, color=WIND, linewidth=2, zorder=2)
    ax.set_title("Vento a 10 m, do dia anterior", color=INK, fontsize=11,
                 loc="left", pad=10)
    ax.set_ylabel("m s⁻¹ (média escalar)", color=MUTED, fontsize=9)

    top = df.wind_speed.max() * 1.45
    ax.set_ylim(0, top)

    # Direction gets its own strip above the speed line, so neither obscures
    # the other. The stored pair is the bearing the wind blows *from*, so the
    # arrow, which points where it blew to, is its negative. Shading is the
    # constancy: pale means the day cancelled itself out.
    quiver = ax.quiver(
        mdates.date2num(df.date), np.full(len(df), top * 0.9),
        -df.wind_dir_sin, -df.wind_dir_cos, df.wind_const,
        cmap=CONSTANCY, norm=Normalize(0, 1), pivot="middle",
        scale=34, width=0.008, headwidth=3.4, headlength=4, headaxislength=3.4,
        zorder=3,
    )
    ax.text(0.0, 0.985, "direção do dia", transform=ax.transAxes,
            fontsize=9, color=MUTED, va="top")

    bar = ax.figure.colorbar(quiver, ax=ax, orientation="horizontal",
                             pad=0.16, aspect=42, fraction=0.045)
    bar.set_label("constância direcional (0 = vento girou, 1 = firme)",
                  color=MUTED, fontsize=9)
    bar.ax.tick_params(colors=MUTED, labelsize=9, length=0)
    bar.outline.set_visible(False)


def main():
    month = sys.argv[1] if len(sys.argv) > 1 else "2025-01"
    df = load(month)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), constrained_layout=True)
    fig.patch.set_facecolor("#fcfcfb")
    for ax in axes:
        ax.set_facecolor("#fcfcfb")
        style(ax)

    plot_rain(axes[0], df)
    plot_temp(axes[1], df)
    plot_wind(axes[2], df)

    stamp = pd.Timestamp(f"{month}-01")
    fig.suptitle(f"Curitiba (−25.4, −49.3) — {MESES[stamp.month - 1]} de "
                 f"{stamp.year} — alvo em t, preditores em t−1 (dias UTC)",
                 color=INK, fontsize=13, x=0.006, ha="left")

    FIGURES.mkdir(exist_ok=True)
    out = FIGURES / f"curitiba_{month.replace('-', '_')}.png"
    fig.savefig(out, dpi=160, facecolor=fig.get_facecolor(),
                bbox_inches="tight", pad_inches=0.25)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
