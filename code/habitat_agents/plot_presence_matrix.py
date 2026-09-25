#!/usr/bin/env python3
"""plot_presence_matrix.py  --  render a presence matrix as a styled PNG
========================================================================

Reproduces the look of
`outputs/landcover_analysis/redlist_aggregate9_1km_weighted/redlist_aggregate9_1km_weighted_presence_matrix.png`
for ANY presence matrix with the same column shape
(`species_code, common_name, red_list_name` + the 9 aggregate-habitat boolean
columns): the data-derived matrix OR the blind agent matrix.

For each (species, habitat) cell:
  - a filled, rounded rectangle in the habitat's fixed colour  -> True
  - a small muted dot                                          -> False

Habitat colours, the ink tokens, and the canonical category order are taken
verbatim from `code/landcover_analysis/12_plot_redlist_aggregate9_1km_weighted_bars.py`
so every figure in the project shares one palette.

Usage
-----
    # the blind agent matrix (default) -> blind_*.png/.pdf
    python code/habitat_agents/plot_presence_matrix.py

    # a specific matrix + custom title
    python code/habitat_agents/plot_presence_matrix.py \
        --matrix outputs/habitat_agents/blind_presence_matrix.csv \
        --title "Blind agent — habitat presence (Documented = filled)"

Outputs sit next to each input CSV: `<name>.png` and `<name>.pdf`.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _agent_common as ac  # noqa: E402  (CATEGORIES, CATEGORY_LABELS, paths)

# ---------------------------------------------------------------------------
# Palette + ink tokens (verbatim from 12_plot_redlist_aggregate9_1km_weighted_bars.py)
# ---------------------------------------------------------------------------
COLORS = {
    "woodland":           "#008300",  # green
    "arable":             "#eda100",  # yellow
    "improved_grassland": "#b58a00",  # gold
    "seminat_grassland":  "#1baf7a",  # aqua
    "mountain_heath_bog": "#4a3aa7",  # violet
    "saltwater":          "#1c4f9c",  # deep blue
    "freshwater":         "#2a78d6",  # blue
    "coastal":            "#0aa3b0",  # teal
    "builtup":            "#eb6834",  # orange
}
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#8a8985"
ROW_SHADE = "#f2f1ee"   # alternating-row band

# Two-line column headers (matches the aggregate-9 bar/matrix figures' wrapping).
HEADER_LABELS = {
    "woodland": "Woodland",
    "arable": "Arable",
    "improved_grassland": "Improved\ngrassland",
    "seminat_grassland": "Semi-natural\ngrassland",
    "mountain_heath_bog": "Mountain,\nheath & bog",
    "saltwater": "Saltwater",
    "freshwater": "Freshwater",
    "coastal": "Coastal",
    "builtup": "Built-up",
}

# Default per-file titles/subtitles when plotting the blind agent matrix.
DEFAULT_META = {
    "blind_presence_matrix.csv": (
        "Blind agent — bird × aggregate-9 land cover — presence matrix",
        "50 UK red-list species  ·  9 aggregate habitats  ·  knowledge only, no data shown",
        "Filled = the agent decisively determined the species is commonly found in that "
        "habitat (True).  Dot = Not established (False).",
    ),
}
GENERIC_META = (
    "Bird × aggregate-9 land cover — presence matrix",
    "50 UK red-list species  ·  9 aggregate habitats",
    "Filled = present (True).  Dot = absent (False).",
)


def _truthy(v) -> bool:
    """Read a matrix cell as boolean. Handles True/False, "True"/"False",
    1/0, and blanks/NaN (blank -> False)."""
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in ("true", "1", "1.0", "yes", "t")


def plot_matrix(csv_path: str, title: str, subtitle: str, caption: str) -> list[str]:
    """Render one presence-matrix CSV to a PNG + PDF beside it. Returns paths."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    import pandas as pd

    df = pd.read_csv(csv_path)
    missing = [c for c in ac.CATEGORIES if c not in df.columns]
    if missing:
        sys.exit(
            f"ERROR: {csv_path} is missing habitat column(s): {missing}. "
            "Expected the 9 aggregate-habitat columns of a presence matrix."
        )

    n = len(df)
    cats = ac.CATEGORIES
    # True-count per habitat column (shown under each header, like the reference).
    col_counts = {c: int(sum(_truthy(v) for v in df[c])) for c in cats}

    # --- Geometry (data coordinates: x over columns, y over species rows) ------
    # Species text block occupies x in [SPECIES_X, 0); habitat columns start at x0.
    SPECIES_X = -4.2              # left edge of the species text block
    x0 = 1.0                      # first habitat column centre
    col_dx = 1.4                  # spacing between habitat columns (wide enough
                                  # that the two-line headers never collide)
    col_x = {c: x0 + i * col_dx for i, c in enumerate(cats)}
    x_right = x0 + (len(cats) - 1) * col_dx + 0.9
    row_h = 1.0
    top_pad = 3.2                 # space above row 0 for title/subtitle/headers
    bot_pad = 1.4                 # space below last row for the caption

    fig_w = 11.5
    fig_h = 1.15 + 0.42 * n       # scales with species count (~3430px at 50 rows)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=170)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_xlim(SPECIES_X, x_right)
    ax.set_ylim(n + top_pad, -bot_pad)   # inverted: row 0 at top
    ax.axis("off")

    def row_y(i: int) -> float:
        return i + 0.5            # row-i centre

    # --- Alternating row shading ----------------------------------------------
    for i in range(n):
        if i % 2 == 1:
            ax.add_patch(
                plt.Rectangle(
                    (SPECIES_X, i), x_right - SPECIES_X, row_h,
                    facecolor=ROW_SHADE, edgecolor="none", zorder=0,
                )
            )

    # --- Title + subtitle ------------------------------------------------------
    ax.text(SPECIES_X, -bot_pad - 1.75, title, fontsize=17, fontweight="bold",
            color=INK_PRIMARY, ha="left", va="top")
    ax.text(SPECIES_X, -bot_pad - 0.95, subtitle, fontsize=10.5,
            color=INK_MUTED, ha="left", va="top")

    # --- Column headers (coloured label + underline + True-count) -------------
    header_y = -0.05
    for c in cats:
        x = col_x[c]
        ax.text(x, header_y - 0.95, HEADER_LABELS[c], fontsize=9.6,
                fontweight="bold", color=COLORS[c], ha="center", va="top",
                linespacing=1.15)
        ax.plot([x - 0.34, x + 0.34], [header_y + 0.12, header_y + 0.12],
                color=COLORS[c], linewidth=2.4, solid_capstyle="round", zorder=3)
        ax.text(x, header_y + 0.45, str(col_counts[c]), fontsize=10,
                fontweight="bold", color=INK_SECONDARY, ha="center", va="top")

    # "Species" column header + the rule under the whole header band.
    ax.text(SPECIES_X, header_y - 0.4, "Species", fontsize=11, fontweight="bold",
            color=INK_PRIMARY, ha="left", va="center")
    ax.plot([SPECIES_X, x_right], [0.02, 0.02],
            color=INK_PRIMARY, linewidth=1.3, zorder=3)

    # --- Rows: species labels + True/False glyphs -----------------------------
    for i, (_, r) in enumerate(df.iterrows()):
        y = row_y(i)
        common = str(r.get("common_name", "") or "")
        rl = str(r.get("red_list_name", "") or "")
        code = str(r.get("species_code", "") or "")
        ax.text(SPECIES_X, y - 0.16, common, fontsize=10.5, fontweight="bold",
                color=INK_PRIMARY, ha="left", va="center")
        ax.text(SPECIES_X, y + 0.24, f"{rl}  ·  {code}", fontsize=8,
                color=INK_MUTED, ha="left", va="center")

        for c in cats:
            x = col_x[c]
            if _truthy(r[c]):
                # Filled rounded rectangle in the habitat colour = True.
                bw, bh = 0.62, 0.44
                ax.add_patch(
                    FancyBboxPatch(
                        (x - bw / 2, y - bh / 2), bw, bh,
                        boxstyle="round,pad=0.0,rounding_size=0.12",
                        facecolor=COLORS[c], edgecolor=SURFACE, linewidth=1.3,
                        mutation_aspect=0.9, zorder=2,
                    )
                )
            else:
                # Small muted dot = False.
                ax.plot(x, y, marker="o", markersize=4.5,
                        markerfacecolor="#d7d6d2", markeredgecolor="none", zorder=2)

    # --- Footer caption --------------------------------------------------------
    ax.text(SPECIES_X, n + 0.55, caption, fontsize=9, color=INK_SECONDARY,
            ha="left", va="top", wrap=True)
    ax.text(SPECIES_X, n + 1.35,
            "eBird Status 2023 × UKCEH aggregate-9 land cover.  One model call per "
            "species; binary True/False (no abstention).",
            fontsize=8.5, color=INK_MUTED, ha="left", va="top")

    fig.subplots_adjust(left=0.005, right=0.995, top=0.999, bottom=0.001)

    base = os.path.splitext(csv_path)[0]
    png_path, pdf_path = base + ".png", base + ".pdf"
    fig.savefig(png_path, facecolor=SURFACE, bbox_inches="tight", pad_inches=0.25)
    fig.savefig(pdf_path, facecolor=SURFACE, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    return [png_path, pdf_path]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matrix",
        default=None,
        help="Path to a presence-matrix CSV. If omitted, plots both agent "
        "matrices in outputs/habitat_agents/.",
    )
    parser.add_argument("--title", default=None, help="Override the figure title.")
    parser.add_argument(
        "--subtitle", default=None, help="Override the subtitle line."
    )
    parser.add_argument(
        "--caption", default=None, help="Override the footer caption."
    )
    args = parser.parse_args()

    if args.matrix:
        targets = [args.matrix]
    else:
        targets = [
            os.path.join(ac.OUTPUT_DIR, "blind_presence_matrix.csv"),
        ]

    any_done = False
    for csv_path in targets:
        if not os.path.exists(csv_path):
            print(f"skip (not found): {csv_path}")
            continue
        name = os.path.basename(csv_path)
        d_title, d_subtitle, d_caption = DEFAULT_META.get(name, GENERIC_META)
        title = args.title or d_title
        subtitle = args.subtitle or d_subtitle
        caption = args.caption or d_caption
        outs = plot_matrix(csv_path, title, subtitle, caption)
        print(f"wrote: {'  '.join(outs)}")
        any_done = True

    if not any_done:
        sys.exit(
            "No matrices plotted. Run the blind agent first "
            "(run_blind_agent.py) or pass --matrix <path>."
        )


if __name__ == "__main__":
    main()
