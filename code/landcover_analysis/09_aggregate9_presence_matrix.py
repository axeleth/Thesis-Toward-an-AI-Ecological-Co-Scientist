#!/usr/bin/env python3
"""09_aggregate9_presence_matrix.py

Boolean "commonly found in" matrix for the redlist-50 species x 9 UKCEH-aggregate
land-cover categories, derived from the eBird abundance summary.

The 9-class sibling of 05_broad6_presence_matrix.py. Reproduces EXACTLY the
cumulative-80% (Pareto) rule that the per-species bar charts
(08_plot_redlist_aggregate9_bars.py) draw as a dashed red line:

  1. For each species, take the summed relative abundance in each of the 9
     categories and convert to that category's SHARE of the species' total.
  2. Sort the 9 categories descending by share.
  3. The "vital few" are the fewest top categories whose cumulative share first
     reaches 80% -- these are the bars to the LEFT of (and including) the red
     line on the plot. Every such category gets TRUE; the rest get FALSE.

A category is therefore TRUE iff its abundance contributes to the top 80% of the
species' total abundance, matching what a reader sees in the plots.

Input:  outputs/landcover_analysis/redlist_aggregate9/redlist_abundance_by_aggregate9_wide.csv
Output: outputs/landcover_analysis/redlist_aggregate9/redlist_aggregate9_presence_matrix.csv
          (50 rows x 9 boolean category columns, plus species id columns)

Note: this is the eBird-derived ground truth. The parallel research-agent verdicts
(whether a species is documented in each habitat) will be produced separately and
compared against this matrix.
"""

import re
from pathlib import Path

import pandas as pd

# --- Resolve data root (git-ignored inputs live in the main checkout) --------
HERE = Path(__file__).resolve()
CODE_ROOT = HERE.parents[2]  # the checkout root holding code/ and outputs/
m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", str(CODE_ROOT))
DATA_ROOT = Path(m.group(1)) if m else CODE_ROOT

IN_CSV = DATA_ROOT / "outputs" / "landcover_analysis" / "redlist_aggregate9" / \
    "redlist_abundance_by_aggregate9_wide.csv"
OUT_CSV = DATA_ROOT / "outputs" / "landcover_analysis" / "redlist_aggregate9" / \
    "redlist_aggregate9_presence_matrix.csv"

# The 9 aggregate categories in canonical order (matches the plot's tie-breaking).
CATEGORIES = ["woodland", "arable", "improved_grassland",
              "seminat_grassland", "mountain_heath_bog",
              "saltwater", "freshwater", "coastal", "builtup"]

PARETO = 80.0  # cumulative-percent threshold, identical to the plot


def cumulative_split_index(pcts):
    """Number of top classes whose cumulative % first reaches 80.

    `pcts` is sorted descending. Identical to 08_plot_redlist_aggregate9_bars.py
    so the boolean matrix and the red Pareto line always agree.
    """
    cum = 0.0
    for i, p in enumerate(pcts):
        cum += p
        if cum >= PARETO:
            return i + 1
    return len(pcts)


def presence_for_row(row):
    """Return {category: bool} for one species using the Pareto-80 rule."""
    sums = {c: float(row[f"sum_{c}"]) for c in CATEGORIES}
    total = sum(sums.values())

    if total <= 0:
        # Degenerate species (no modelled abundance) -> nothing is "common".
        return {c: False for c in CATEGORIES}

    pct = {c: 100.0 * sums[c] / total for c in CATEGORIES}

    # Sort descending, canonical order breaks ties -- matches the plot exactly.
    order = sorted(CATEGORIES, key=lambda c: (-pct[c], CATEGORIES.index(c)))
    ordered_pcts = [pct[c] for c in order]

    k = cumulative_split_index(ordered_pcts)  # top-k hold >=80%
    top_set = set(order[:k])
    return {c: (c in top_set) for c in CATEGORIES}


def main():
    if not IN_CSV.exists():
        raise SystemExit(
            f"Input not found: {IN_CSV}\n"
            "Run 07_redlist_abundance_by_aggregate9.R first."
        )
    df = pd.read_csv(IN_CSV)
    print(f"Loaded {len(df)} species from {IN_CSV.name}")

    records = []
    for _, row in df.iterrows():
        presence = presence_for_row(row)
        rec = {
            "species_code": row["species_code"],
            "common_name": row["common_name"],
            "red_list_name": row["red_list_name"],
        }
        # One boolean column per aggregate category, in canonical order.
        for c in CATEGORIES:
            rec[c] = bool(presence[c])
        records.append(rec)

    out = pd.DataFrame.from_records(
        records,
        columns=["species_code", "common_name", "red_list_name"] + CATEGORIES,
    )
    out.to_csv(OUT_CSV, index=False)

    # --- Console summary -----------------------------------------------------
    print(f"Wrote {OUT_CSV}")
    print(f"  {len(out)} species (rows) x {len(CATEGORIES)} category columns\n")
    print("  TRUE counts per category (how many species commonly use it):")
    for c in CATEGORIES:
        print(f"    {c:<20} {int(out[c].sum()):>3d} / {len(out)}")
    print("\n  Categories held per species (distribution):")
    per_species = out[CATEGORIES].sum(axis=1)
    for n in range(1, len(CATEGORIES) + 1):
        cnt = int((per_species == n).sum())
        if cnt:
            print(f"    {n} categorie(s): {cnt} species")


if __name__ == "__main__":
    main()
