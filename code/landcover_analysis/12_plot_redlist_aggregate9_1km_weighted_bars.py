#!/usr/bin/env python3
"""12_plot_redlist_aggregate9_1km_weighted_bars.py

One bar chart per species from the 1 km-weighted redlist aggregate-9 summary.

The 1 km-weighted sibling of 08_plot_redlist_aggregate9_bars.py. Identical in
every way (same 9 categories, colours, cumulative-80% Pareto line) EXCEPT it
reads the 1 km-weighted abundance (`weighted_<cat>` columns), where each 3 km
cell's abundance is split across classes by its 1 km land-cover mix, instead of
the dominant-class totals (`sum_<cat>`).

For each of the 50 red_list_available species, plot the 9 UKCEH-aggregate land-
cover categories as a PERCENTAGE of that species' total (1 km-weighted) abundance,
sorted DECREASING, with the dashed red cumulative-80% (Pareto) line.

Input:  outputs/landcover_analysis/redlist_aggregate9_1km_weighted/redlist_abundance_by_aggregate9_1km_weighted_wide.csv
Output: outputs/landcover_analysis/redlist_aggregate9_1km_weighted/bar_charts/<species_code>.png (x50)

Note: eBird abundance is modelled relative-abundance density, not counts. Here a
class's share reflects the 1 km habitat mix within each cell (a cell's abundance
is distributed proportionally to how many of its 1 km squares are each habitat),
so shares are no longer winner-takes-all by dominant class.
"""

import re
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

# --- Resolve data root (git-ignored inputs live in the main checkout) ---
HERE = Path(__file__).resolve()
CODE_ROOT = HERE.parents[2]  # the checkout root holding code/ and outputs/
m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", str(CODE_ROOT))
DATA_ROOT = Path(m.group(1)) if m else CODE_ROOT

BASE = DATA_ROOT / "outputs" / "landcover_analysis" / "redlist_aggregate9_1km_weighted"
IN_CSV = BASE / "redlist_abundance_by_aggregate9_1km_weighted_wide.csv"
OUT_DIR = BASE / "bar_charts"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# --- The 9 aggregate categories: canonical order, fixed labels, fixed colours ---
# Colours match 08/10 so all aggregate-9 charts read as one system.
CATEGORIES = ["woodland", "arable", "improved_grassland",
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

# Recessive ink tokens (light surface)
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#8a8985"
LINE_RED = "#d03b3b"  # status 'critical' — the 80/20 divider

PARETO = 80.0  # cumulative-percent threshold
NCAT = len(CATEGORIES)


def cumulative_split_index(pcts):
    """Return the number of top classes whose cumulative % first reaches 80."""
    cum = 0.0
    for i, p in enumerate(pcts):
        cum += p
        if cum >= PARETO:
            return i + 1  # include this class in the "top"
    return len(pcts)


def plot_species(row):
    code = row["species_code"]
    common = row["common_name"]
    redname = row["red_list_name"]

    sums = {c: float(row[f"weighted_{c}"]) for c in CATEGORIES}
    total = sum(sums.values())

    if total <= 0:
        pct = {c: 0.0 for c in CATEGORIES}
    else:
        pct = {c: 100.0 * sums[c] / total for c in CATEGORIES}

    order = sorted(CATEGORIES, key=lambda c: (-pct[c], CATEGORIES.index(c)))
    ordered_pcts = [pct[c] for c in order]

    k = cumulative_split_index(ordered_pcts)  # top-k classes hold >=80%
    cum_at_k = sum(ordered_pcts[:k])

    fig, ax = plt.subplots(figsize=(9.6, 4.8), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    x = range(len(order))
    bars = ax.bar(
        x, ordered_pcts,
        color=[COLORS[c] for c in order],
        width=0.72, zorder=3,
        edgecolor=SURFACE, linewidth=1.5,
    )

    for rect, p in zip(bars, ordered_pcts):
        ax.text(rect.get_x() + rect.get_width() / 2,
                rect.get_height() + 1.2,
                f"{p:.0f}%", ha="center", va="bottom",
                fontsize=8.5, color=INK_SECONDARY, zorder=4)

    if 0 < k < len(order):
        line_x = k - 0.5
        ax.axvline(line_x, color=LINE_RED, linestyle="--", linewidth=1.8,
                   zorder=5)
        ax.text(line_x, ax.get_ylim()[1] * 0.98,
                f"  cumulative {cum_at_k:.0f}%\n  (top {k} of {NCAT})",
                ha="left", va="top", fontsize=8.5, color=LINE_RED, zorder=6)
    elif k >= len(order):
        ax.text(0.99, 0.98, "no 80/20 split\n(even spread)",
                transform=ax.transAxes, ha="right", va="top",
                fontsize=8.5, color=INK_MUTED, zorder=6)

    ax.set_xticks(list(x))
    ax.set_xticklabels([LABELS[c] for c in order], fontsize=8.0,
                       color=INK_SECONDARY)
    ax.set_ylabel("Share of total abundance (1 km-weighted)", fontsize=9.5,
                  color=INK_SECONDARY)
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=100))
    ax.set_ylim(0, max(100, max(ordered_pcts) * 1.15) if ordered_pcts else 100)

    title = f"{common}  —  {redname}"
    ax.set_title(title, fontsize=12, color=INK_PRIMARY, pad=26, loc="left",
                 fontweight="bold")
    ax.text(0, 1.045,
            f"Relative abundance by UKCEH-aggregate land cover, 1 km-weighted  "
            f"({code}, all 52 weeks summed)",
            transform=ax.transAxes, fontsize=8.5, color=INK_MUTED,
            va="bottom")

    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK_MUTED)
        ax.spines[s].set_linewidth(0.8)
    ax.tick_params(colors=INK_SECONDARY, length=0)
    ax.grid(axis="y", color="#e6e5e1", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

    fig.tight_layout()
    out = OUT_DIR / f"{code}.png"
    fig.savefig(out, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return out, k, cum_at_k


def main():
    if not IN_CSV.exists():
        raise SystemExit(f"Input not found: {IN_CSV}\n"
                         "Run 11_redlist_abundance_by_aggregate9_1km_weighted.R first.")
    df = pd.read_csv(IN_CSV)
    print(f"Loaded {len(df)} species from {IN_CSV.name}")
    print(f"Writing PNGs to {OUT_DIR}\n")

    n = 0
    for _, row in df.iterrows():
        out, k, cum = plot_species(row)
        n += 1
        print(f"  [{n:2d}/{len(df)}] {row['species_code']:<10} "
              f"{row['common_name']:<28} top {k}/{NCAT} hold {cum:.0f}%  -> {out.name}")

    print(f"\nDone. Wrote {n} charts to {OUT_DIR}")


if __name__ == "__main__":
    main()
