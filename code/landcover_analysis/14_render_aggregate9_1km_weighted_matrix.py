#!/usr/bin/env python3
"""14_render_aggregate9_1km_weighted_matrix.py

Render the 1 km-weighted aggregate-9 presence matrix as a print-ready figure
(PDF + PNG).

The 1 km-weighted sibling of 10_render_aggregate9_matrix.py. Same layout and
colours; reads the 1 km-weighted presence matrix so the table and the 1 km-
weighted bar charts (12) read as one system.

Input:  outputs/landcover_analysis/redlist_aggregate9_1km_weighted/redlist_aggregate9_1km_weighted_presence_matrix.csv
Output: outputs/landcover_analysis/redlist_aggregate9_1km_weighted/redlist_aggregate9_1km_weighted_presence_matrix.{pdf,png}
"""

import re
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

# --- Resolve data root (git-ignored outputs live in the main checkout) -------
HERE = Path(__file__).resolve()
CODE_ROOT = HERE.parents[2]
m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", str(CODE_ROOT))
DATA_ROOT = Path(m.group(1)) if m else CODE_ROOT

BASE = DATA_ROOT / "outputs" / "landcover_analysis" / "redlist_aggregate9_1km_weighted"
IN_CSV = BASE / "redlist_aggregate9_1km_weighted_presence_matrix.csv"
OUT_PDF = BASE / "redlist_aggregate9_1km_weighted_presence_matrix.pdf"
OUT_PNG = BASE / "redlist_aggregate9_1km_weighted_presence_matrix.png"

# 9 aggregate categories: canonical order, labels, colours (match the bar charts).
CATS = ["woodland", "arable", "improved_grassland",
        "seminat_grassland", "mountain_heath_bog",
        "saltwater", "freshwater", "coastal", "builtup"]
LABELS = {
    "woodland":           "Woodland",
    "arable":             "Arable",
    "improved_grassland": "Improved\ngrassland",
    "seminat_grassland":  "Semi-natural\ngrassland",
    "mountain_heath_bog": "Mountain,\nheath & bog",
    "saltwater":          "Saltwater",
    "freshwater":         "Freshwater",
    "coastal":            "Coastal",
    "builtup":            "Built-up",
}
COLORS = {
    "woodland":           "#008300",
    "arable":             "#eda100",
    "improved_grassland": "#b58a00",
    "seminat_grassland":  "#1baf7a",
    "mountain_heath_bog": "#4a3aa7",
    "saltwater":          "#1c4f9c",
    "freshwater":         "#2a78d6",
    "coastal":            "#0aa3b0",
    "builtup":            "#eb6834",
}

# Recessive ink tokens (light surface, print-friendly).
SURFACE = "#ffffff"
INK = "#1b1d17"
INK_SOFT = "#5a5d53"
INK_MUTE = "#9a9c90"
HAIR = "#e4e5df"


def rounded_cell(ax, x, y, w, h, color, pad=0.06, radius=0.10):
    """Draw a rounded rectangle centred in the (x,y) grid slot."""
    box = FancyBboxPatch(
        (x + pad, y + pad), w - 2 * pad, h - 2 * pad,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        linewidth=0, facecolor=color, zorder=3,
    )
    ax.add_patch(box)


def main():
    if not IN_CSV.exists():
        raise SystemExit(f"Input not found: {IN_CSV}\n"
                         "Run 13_aggregate9_1km_weighted_presence_matrix.py first.")
    df = pd.read_csv(IN_CSV)
    n = len(df)
    ncol = len(CATS)

    totals = {c: int(df[c].sum()) for c in CATS}

    label_w = 4.6
    header_h = 2.4
    footer_h = 0.9

    fig_w = 10.5
    cell_px = 0.30
    fig_h = header_h * 0.30 + n * cell_px + footer_h * 0.30 + 1.1

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    total_w = label_w + ncol
    ax.set_xlim(0, total_w)
    ax.set_ylim(0, n + header_h + footer_h)
    ax.invert_yaxis()
    ax.axis("off")

    def row_top(i):
        return header_h + i

    for j, c in enumerate(CATS):
        cx = label_w + j + 0.5
        ax.add_patch(FancyBboxPatch(
            (cx - 0.30, header_h - 0.55), 0.60, 0.16,
            boxstyle="round,pad=0,rounding_size=0.07",
            linewidth=0, facecolor=COLORS[c], zorder=3))
        ax.text(cx, header_h - 0.72, LABELS[c], ha="center", va="bottom",
                fontsize=6.9, color=INK_SOFT, linespacing=1.15, zorder=4)
        ax.text(cx, header_h - 0.30, f"{totals[c]}", ha="center", va="top",
                fontsize=7.0, color=INK_MUTE, fontweight="bold", zorder=4)

    ax.text(0.10, header_h - 0.30, "Species", ha="left", va="top",
            fontsize=8.4, color=INK_SOFT, fontweight="bold")

    ax.plot([0, total_w], [header_h, header_h], color=INK_SOFT,
            linewidth=1.1, zorder=2)

    for i, (_, r) in enumerate(df.iterrows()):
        y = row_top(i)
        if i % 2 == 1:
            ax.add_patch(plt.Rectangle((0, y), total_w, 1.0,
                                       facecolor="#f6f7f4", edgecolor="none",
                                       zorder=0))
        ax.text(0.10, y + 0.42, str(r["common_name"]), ha="left", va="center",
                fontsize=8.0, color=INK, fontweight="600", zorder=4)
        sub = f"{r['red_list_name']}  ·  {r['species_code']}"
        ax.text(0.10, y + 0.78, sub, ha="left", va="center",
                fontsize=6.2, color=INK_MUTE, zorder=4)

        for j, c in enumerate(CATS):
            on = bool(r[c])
            x = label_w + j
            if on:
                rounded_cell(ax, x, y, 1.0, 1.0, COLORS[c], pad=0.20, radius=0.10)
            else:
                ax.add_patch(plt.Circle((x + 0.5, y + 0.5), 0.055,
                                        facecolor="#cfd1c8", edgecolor="none",
                                        zorder=3))
        ax.plot([0, total_w], [y + 1.0, y + 1.0], color=HAIR,
                linewidth=0.5, zorder=1)

    fy = header_h + n + 0.45
    ax.text(0, fy,
            "Filled = habitat is in the species' top 80% of summed relative abundance "
            "(the “vital few”, Pareto rule).  Empty = bottom ≤20%.",
            ha="left", va="top", fontsize=6.6, color=INK_MUTE)
    ax.text(0, fy + 0.55,
            "eBird Status 2023 × UKCEH aggregate-9 land cover.  1 km-weighted: each "
            "3 km cell's abundance is split across habitats by its 1 km land-cover "
            "mix (abundance conserved), not assigned whole to one dominant class.",
            ha="left", va="top", fontsize=6.6, color=INK_MUTE)

    fig.suptitle("Red-list birds × UKCEH-aggregate land cover — presence matrix (1 km-weighted)",
                 x=0.02, y=0.995, ha="left", fontsize=12.5, fontweight="bold",
                 color=INK)
    ax.text(0, 0.55, f"{n} UK red-list species  ·  9 aggregate habitats  ·  "
                     "top-80% (Pareto) rule  ·  1 km-weighted",
            ha="left", va="top", fontsize=7.8, color=INK_MUTE)

    fig.subplots_adjust(left=0.01, right=0.99, top=0.965, bottom=0.01)

    fig.savefig(OUT_PDF, facecolor=SURFACE, bbox_inches="tight")
    fig.savefig(OUT_PNG, facecolor=SURFACE, bbox_inches="tight", dpi=200)
    plt.close(fig)
    print(f"Wrote {OUT_PDF}")
    print(f"Wrote {OUT_PNG}")
    print(f"  {n} species x {ncol} habitats")
    print("  column totals:", {LABELS[c].replace(chr(10), ' '): totals[c] for c in CATS})


if __name__ == "__main__":
    main()
