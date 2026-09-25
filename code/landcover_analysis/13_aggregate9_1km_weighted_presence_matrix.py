#!/usr/bin/env python3
"""13_aggregate9_1km_weighted_presence_matrix.py

Boolean "commonly found in" matrix for the redlist-50 species x 9 UKCEH-aggregate
land-cover categories, from the 1 km-weighted eBird abundance summary.

The 1 km-weighted sibling of 09_aggregate9_presence_matrix.py. Same cumulative-80%
(Pareto) rule, but reads the 1 km-weighted shares (`weighted_<cat>`), where each
3 km cell's abundance is split across classes by its 1 km land-cover mix, instead
of the dominant-class totals.

  1. For each species, take the 1 km-weighted abundance in each of the 9
     categories and convert to that category's SHARE of the species' total.
  2. Sort the 9 categories descending by share.
  3. The "vital few" are the fewest top categories whose cumulative share first
     reaches 80% -- TRUE; the rest FALSE. Matches the red line in the plots (12).

Input:  outputs/landcover_analysis/redlist_aggregate9_1km_weighted/redlist_abundance_by_aggregate9_1km_weighted_wide.csv
Output: outputs/landcover_analysis/redlist_aggregate9_1km_weighted/redlist_aggregate9_1km_weighted_presence_matrix.csv
"""

import re
from pathlib import Path

import pandas as pd

# --- Resolve data root (git-ignored inputs live in the main checkout) --------
HERE = Path(__file__).resolve()
CODE_ROOT = HERE.parents[2]  # the checkout root holding code/ and outputs/
m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", str(CODE_ROOT))
DATA_ROOT = Path(m.group(1)) if m else CODE_ROOT

BASE = DATA_ROOT / "outputs" / "landcover_analysis" / "redlist_aggregate9_1km_weighted"
IN_CSV = BASE / "redlist_abundance_by_aggregate9_1km_weighted_wide.csv"
OUT_CSV = BASE / "redlist_aggregate9_1km_weighted_presence_matrix.csv"

# The 9 aggregate categories in canonical order (matches the plot's tie-breaking).
CATEGORIES = ["woodland", "arable", "improved_grassland",
              "seminat_grassland", "mountain_heath_bog",
              "saltwater", "freshwater", "coastal", "builtup"]

PARETO = 80.0  # cumulative-percent threshold, identical to the plot


def cumulative_split_index(pcts):
    """Number of top classes whose cumulative % first reaches 80.

    `pcts` sorted descending. Identical to
    12_plot_redlist_aggregate9_1km_weighted_bars.py so the boolean matrix and the
    red Pareto line always agree.
    """
    cum = 0.0
    for i, p in enumerate(pcts):
        cum += p
        if cum >= PARETO:
            return i + 1
    return len(pcts)


def presence_for_row(row):
    """Return {category: bool} for one species using the Pareto-80 rule."""
    sums = {c: float(row[f"weighted_{c}"]) for c in CATEGORIES}
    total = sum(sums.values())

    if total <= 0:
        return {c: False for c in CATEGORIES}

    pct = {c: 100.0 * sums[c] / total for c in CATEGORIES}
    order = sorted(CATEGORIES, key=lambda c: (-pct[c], CATEGORIES.index(c)))
    ordered_pcts = [pct[c] for c in order]

    k = cumulative_split_index(ordered_pcts)  # top-k hold >=80%
    top_set = set(order[:k])
    return {c: (c in top_set) for c in CATEGORIES}


def main():
    if not IN_CSV.exists():
        raise SystemExit(
            f"Input not found: {IN_CSV}\n"
            "Run 11_redlist_abundance_by_aggregate9_1km_weighted.R first."
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
        for c in CATEGORIES:
            rec[c] = bool(presence[c])
        records.append(rec)

    out = pd.DataFrame.from_records(
        records,
        columns=["species_code", "common_name", "red_list_name"] + CATEGORIES,
    )
    out.to_csv(OUT_CSV, index=False)

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
