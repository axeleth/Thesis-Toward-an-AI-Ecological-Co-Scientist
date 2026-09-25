#!/usr/bin/env python3
"""Merge the 21-class UKCEH land-cover composition into two coarser schemes.

Reads the canonical 21-class 3 km composition once and writes two drop-in
compatible CSVs at different habitat granularities so a downstream fingerprint
pipeline can run at both and be compared:

  * Strategy 3 - broad, 6 classes
  * Strategy 2 - UKCEH aggregate, 9 classes

Each merged percentage column is the row-wise SUM of its member canonical
columns. `cell_id, x, y, total_pct` are carried through unchanged. No
percentage mass is created or lost (every canonical column is used exactly
once per scheme).

Mappings are the source of truth from
`Decisions/2026-07-11 - Land-cover merge strategies (test aggregate vs broad).md`.

Provenance: derived from `ukceh_landcover_composition_3km_wide_adjusted.csv`
(UKCEH LCM 2023).
"""

from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------
# Paths (resolved relative to this script so it works from any checkout)
# --------------------------------------------------------------------------
OUTPUTS_DIR = Path(__file__).resolve().parent / "outputs"
INPUT_CSV = OUTPUTS_DIR / "ukceh_landcover_composition_3km_wide_adjusted.csv"

STRATEGY3_CSV = OUTPUTS_DIR / "ukceh_landcover_composition_3km_strategy3_broad6.csv"
STRATEGY2_CSV = OUTPUTS_DIR / "ukceh_landcover_composition_3km_strategy2_aggregate9.csv"

# --------------------------------------------------------------------------
# The 21 canonical UKCEH percentage columns (source of truth)
# --------------------------------------------------------------------------
CANONICAL_COLS = [
    "pct_broadleaf",
    "pct_conifer",
    "pct_arable",
    "pct_improved_grass",
    "pct_neutral_grass",
    "pct_calcareous_grass",
    "pct_acid_grass",
    "pct_fen",
    "pct_heather",
    "pct_heather_grass",
    "pct_bog",
    "pct_inland_rock",
    "pct_saltwater",
    "pct_freshwater",
    "pct_supralittoral_rock",
    "pct_supralittoral_sed",
    "pct_littoral_rock",
    "pct_littoral_sed",
    "pct_saltmarsh",
    "pct_urban",
    "pct_suburban",
]

PASS_THROUGH_COLS = ["cell_id", "x", "y", "total_pct"]
UNDOCUMENTED_LABEL = "Undocumented"

# --------------------------------------------------------------------------
# Merge mappings. Each entry maps a merged column -> its canonical members.
# The dict order defines the output column order. Keep these in sync with the
# Decisions doc; they are the source of truth.
# --------------------------------------------------------------------------

# Strategy 3 - broad, 6 classes
STRATEGY3_MAP = {
    "pct_woodland": ["pct_broadleaf", "pct_conifer"],
    "pct_farmland": ["pct_arable", "pct_improved_grass"],
    "pct_seminat_grassland": ["pct_neutral_grass", "pct_calcareous_grass", "pct_acid_grass"],
    "pct_upland": ["pct_heather", "pct_heather_grass", "pct_bog", "pct_inland_rock"],
    "pct_wetland_coastal": [
        "pct_fen",
        "pct_saltwater",
        "pct_freshwater",
        "pct_supralittoral_rock",
        "pct_supralittoral_sed",
        "pct_littoral_rock",
        "pct_littoral_sed",
        "pct_saltmarsh",
    ],
    "pct_builtup": ["pct_urban", "pct_suburban"],
}

# Human-readable names for the Strategy 3 merged classes (drop the "pct_" prefix
# to get the `dominant_class` label).
STRATEGY3_NAMES = {
    "pct_woodland": "Woodland",
    "pct_farmland": "Farmland",
    "pct_seminat_grassland": "Semi-natural grassland",
    "pct_upland": "Upland, heath and montane",
    "pct_wetland_coastal": "Wetland, freshwater and coastal",
    "pct_builtup": "Built-up",
}

# Strategy 2 - UKCEH aggregate, 9 classes
STRATEGY2_MAP = {
    "pct_woodland": ["pct_broadleaf", "pct_conifer"],
    "pct_arable": ["pct_arable"],
    "pct_improved_grassland": ["pct_improved_grass"],
    "pct_seminat_grassland": [
        "pct_neutral_grass",
        "pct_calcareous_grass",
        "pct_acid_grass",
        "pct_fen",
    ],
    "pct_mountain_heath_bog": ["pct_heather", "pct_heather_grass", "pct_bog", "pct_inland_rock"],
    "pct_saltwater": ["pct_saltwater"],
    "pct_freshwater": ["pct_freshwater"],
    "pct_coastal": [
        "pct_supralittoral_rock",
        "pct_supralittoral_sed",
        "pct_littoral_rock",
        "pct_littoral_sed",
        "pct_saltmarsh",
    ],
    "pct_builtup": ["pct_urban", "pct_suburban"],
}

STRATEGY2_NAMES = {
    "pct_woodland": "Woodland",
    "pct_arable": "Arable",
    "pct_improved_grassland": "Improved grassland",
    "pct_seminat_grassland": "Semi-natural grassland",
    "pct_mountain_heath_bog": "Mountain, heath and bog",
    "pct_saltwater": "Saltwater",
    "pct_freshwater": "Freshwater",
    "pct_coastal": "Coastal",
    "pct_builtup": "Built-up",
}


def check_mapping_partitions_canonical(merge_map, scheme_name):
    """Assert every canonical column is used exactly once (no drop/double-count)."""
    used = [c for members in merge_map.values() for c in members]
    seen = {}
    for c in used:
        seen[c] = seen.get(c, 0) + 1

    missing = [c for c in CANONICAL_COLS if c not in seen]
    duplicated = {c: n for c, n in seen.items() if n > 1}
    unknown = [c for c in seen if c not in CANONICAL_COLS]

    ok = not missing and not duplicated and not unknown
    print(f"  [{scheme_name}] every canonical column used exactly once: {ok}")
    if missing:
        print(f"    MISSING (dropped): {missing}")
    if duplicated:
        print(f"    DUPLICATED (double-counted): {duplicated}")
    if unknown:
        print(f"    UNKNOWN columns in mapping: {unknown}")
    assert ok, f"Mapping for {scheme_name} does not partition the 21 canonical columns"


def build_scheme(df, merge_map, names, scheme_name):
    """Return a drop-in compatible merged DataFrame for one scheme."""
    merged_cols = list(merge_map.keys())

    out = pd.DataFrame()
    for col in PASS_THROUGH_COLS:
        out[col] = df[col]

    # Row-wise sum of each merged class's members.
    for merged, members in merge_map.items():
        out[merged] = df[members].sum(axis=1)

    # Dominant merged class = the merged pct column with the highest value.
    merged_matrix = out[merged_cols]
    dominant_col = merged_matrix.idxmax(axis=1)          # e.g. "pct_wetland_coastal"
    row_max = merged_matrix.max(axis=1)

    # Sea/empty rows: total_pct == 0 or all merged pct == 0 -> Undocumented.
    is_empty = (df["total_pct"] == 0) | (row_max == 0)

    label_from_col = dominant_col.str.removeprefix("pct_")   # "wetland_coastal"
    name_from_col = dominant_col.map(names)

    out["dominant_class"] = label_from_col.where(~is_empty, UNDOCUMENTED_LABEL)
    out["dominant_name"] = name_from_col.where(~is_empty, UNDOCUMENTED_LABEL)

    # Final column order: pass-through id/coords, merged pcts, then trailing meta.
    ordered = ["cell_id", "x", "y"] + merged_cols + ["total_pct", "dominant_class", "dominant_name"]
    return out[ordered]


def validate(df_in, df_out, merge_map, scheme_name):
    """Print a short validation report for one output scheme."""
    print(f"\n=== Validation: {scheme_name} ===")

    # 1. No cells lost.
    same_rows = len(df_out) == len(df_in)
    print(f"  row count {len(df_out)} == input {len(df_in)}: {same_rows}")
    assert same_rows

    # 2. Percentage mass preserved (merged sum == canonical sum) on a sample.
    merged_cols = list(merge_map.keys())
    sample = df_in.sample(n=min(500, len(df_in)), random_state=0)
    canon_sum = sample[CANONICAL_COLS].sum(axis=1)
    merged_sum = df_out.loc[sample.index, merged_cols].sum(axis=1)
    max_diff = (canon_sum - merged_sum).abs().max()
    print(f"  max |canonical_sum - merged_sum| over {len(sample)} sampled rows: {max_diff:.3e}")
    assert max_diff < 1e-6, "Percentage mass not preserved"

    # 3. Cells per dominant merged class.
    print("  cells per dominant merged class:")
    counts = df_out["dominant_class"].value_counts()
    for label, n in counts.items():
        print(f"    {label:<24} {n}")

    # 4. Mapping partitions the canonical columns.
    check_mapping_partitions_canonical(merge_map, scheme_name)


def main():
    print(f"Reading {INPUT_CSV}")
    df_in = pd.read_csv(INPUT_CSV)
    print(f"  {len(df_in)} rows, {len(df_in.columns)} columns")

    # Sanity: all 21 canonical columns present.
    missing = [c for c in CANONICAL_COLS if c not in df_in.columns]
    assert not missing, f"Input missing canonical columns: {missing}"

    schemes = [
        ("Strategy 3 (broad, 6 classes)", STRATEGY3_MAP, STRATEGY3_NAMES, STRATEGY3_CSV),
        ("Strategy 2 (UKCEH aggregate, 9 classes)", STRATEGY2_MAP, STRATEGY2_NAMES, STRATEGY2_CSV),
    ]

    for scheme_name, merge_map, names, out_csv in schemes:
        # Audit the mapping before using it.
        check_mapping_partitions_canonical(merge_map, scheme_name)
        df_out = build_scheme(df_in, merge_map, names, scheme_name)
        df_out.to_csv(out_csv, index=False)
        print(f"\nWrote {out_csv}  ({len(df_out)} rows, {len(df_out.columns)} columns)")
        validate(df_in, df_out, merge_map, scheme_name)

    print("\nDone.")


if __name__ == "__main__":
    main()
