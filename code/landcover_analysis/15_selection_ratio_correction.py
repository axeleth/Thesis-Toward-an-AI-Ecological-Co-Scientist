#!/usr/bin/env python3
"""15_selection_ratio_correction.py

Availability-corrected habitat SELECTION for the 41 focal redlist species x 9
UKCEH aggregate classes (1 km-weighted scheme only; broad-6 is not used here).

WHY
---
The naive "commonly found in" matrix (13_aggregate9_1km_weighted_presence_matrix.py)
ranks classes by summed abundance and keeps the cumulative-80% "vital few".
Because Arable and Improved Grassland dominate the UK's land AREA, nearly every
species' abundance piles up there, so the result measures habitat AVAILABILITY
rather than habitat ASSOCIATION -- farmland gets flagged for almost every
species, which disagrees with the reference literature.

This script divides use by availability, so a class only counts as "selected"
when a species uses it MORE than its share of the landscape would predict.

BASIS (this is the part that has to be right)
---------------------------------------------
The used totals from the 11_ pipeline are 1 km-composition-weighted: each 3 km
cell's yearly abundance was split across the 9 classes in proportion to the
cell's 1 km land-cover mix, then summed. So

    used[s,h]      = sum over cells of ( abundance[s,cell] * frac_h[cell] )

Availability must be measured on the SAME composition basis, otherwise the ratio
mixes units. So availability is the summed composition percentage over land
cells -- the total "amount" of class h in the landscape:

    availability[h] = sum over land cells of pct_h[cell]

Land cells only: rows with total_pct == 0 or dominant_name == "Undocumented"
(sea / no data) are excluded.

METRICS (per species s, class h)
--------------------------------
    p_use[s,h]  = used[s,h] / sum_h used[s,h]            share of the bird's use
    p_avail[h]  = avail[h]  / sum_h avail[h]             share of the landscape
    SR[s,h]     = p_use / p_avail                        selection ratio, >1 = preferred
    D[s,h]      = (p_use - p_avail)                      Jacobs' D, range -1..1
                  / (p_use + p_avail - 2*p_use*p_avail)

"Commonly found in", availability-corrected: SR >= SR_THRESHOLD (default 1.0).
A stricter SR >= SR_STRONG_THRESHOLD (default 2.0) is written as a sensitivity check.

SPECIES SCOPE
-------------
FOCAL_SPECIES restricts every output to the 41 species under active study. Set it
to None to process all species in the input.

CAVEAT: availability is UK-WIDE
-------------------------------
A species present only in, say, northern Scotland is scored against the whole-UK
landscape, which inflates SR for habitats concentrated in its range.

The obvious refinement -- restricting availability to each species' occupied range
-- WAS BUILT AND TESTED, and it does NOT work: macro F1 against the RSPB Handbook
fell 0.501 -> 0.493, and kept falling as the range was tightened further. The
occupied range is defined by where the bird is, so a specialist's habitat becomes
a large share of its own denominator and normalises itself away (Coastal is 1.61%
of the UK but 21.3% of the Puffin's range, collapsing its coastal SR from 29.26 to
2.21 and its saltwater SR below the threshold entirely).

See code/landcover_analysis/_archive_selection_experiments/ for that work. The
UK-wide denominator is retained deliberately, not by omission.

Inputs (read-only; printed at startup so the basis is auditable):
  outputs/landcover_analysis/redlist_aggregate9_1km_weighted/redlist_abundance_by_aggregate9_1km_weighted_wide.csv
  code/UKCEH_data/outputs/ukceh_landcover_composition_3km_strategy2_aggregate9.csv
  outputs/landcover_analysis/redlist_aggregate9_1km_weighted/redlist_aggregate9_1km_weighted_presence_matrix.csv

Outputs (all new; nothing existing is modified):
  outputs/landcover_analysis/selection_corrected/aggregate9_selection_ratio.csv
  outputs/landcover_analysis/selection_corrected/aggregate9_jacobs.csv
  outputs/landcover_analysis/selection_corrected/aggregate9_presence_corrected.csv
  outputs/landcover_analysis/selection_corrected/aggregate9_presence_corrected_strong.csv
  outputs/landcover_analysis/selection_corrected/aggregate9_availability.csv
  outputs/landcover_analysis/selection_corrected/aggregate9_naive_vs_corrected_diff.csv
  outputs/landcover_analysis/selection_corrected/aggregate9_corrected_presence.png
  outputs/landcover_analysis/selection_corrected/aggregate9_naive_vs_corrected_diff.png
  outputs/landcover_analysis/selection_corrected/SUMMARY.md
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Patch

# The canonical 41-species study set lives in code/focal_species.json; import its
# loader from the code/ directory (this script lives in code/landcover_analysis/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import focal_species  # noqa: E402

# --- Tunable constants ------------------------------------------------------
SR_THRESHOLD = 1.0        # SR >= this  -> "commonly found in" (availability-corrected)
SR_STRONG_THRESHOLD = 2.0  # SR >= this  -> "strong association" sensitivity check

# The focal species: the 41 under active study, loaded from the canonical
# single source of truth `code/focal_species.json` (see code/focal_species.py).
# Every source -- eBird data, RSPB Handbook coding, the LLM study and the expert
# survey -- reads that same file, so the species sets cannot drift apart.
# Matched on species_code; any other species in the input is dropped from every
# output. Set to None to use all species in the input.
#
# ORDER IS SIGNIFICANT: the outputs below are sorted by this order and the
# downstream matrices are row-aligned to it, so the file's order is preserved.
FOCAL_SPECIES = focal_species.load_codes()

# The 9 aggregate categories in canonical order (same order as scripts 11-14).
CATEGORIES = ["woodland", "arable", "improved_grassland",
              "seminat_grassland", "mountain_heath_bog",
              "saltwater", "freshwater", "coastal", "builtup"]

CATEGORY_LABELS = {
    "woodland": "Woodland",
    "arable": "Arable",
    "improved_grassland": "Improved grassland",
    "seminat_grassland": "Semi-natural grassland",
    "mountain_heath_bog": "Mountain, heath, bog",
    "saltwater": "Saltwater",
    "freshwater": "Freshwater",
    "coastal": "Coastal",
    "builtup": "Built-up",
}

# Species picked to illustrate the fix: wetland/coastal specialists that should
# GAIN their specialist habitat and LOSE farmland, plus a genuine farmland
# generalist that should KEEP farmland. Resolved by species_code, with a
# common-name fallback so a code change does not silently drop a row.
ILLUSTRATIVE = [
    ("compoc", "Common Pochard"),        # freshwater duck -> expect freshwater, lose farmland
    ("comgol", "Common Goldeneye"),      # freshwater duck -> expect freshwater
    ("atlpuf", "Atlantic Puffin"),       # seabird -> expect coastal / saltwater
    ("eurcur", "Eurasian Curlew"),       # wader, coastal + upland
    ("grypar", "Gray Partridge"),        # genuine farmland bird -> should KEEP arable
    ("corbun1", "Corn Bunting"),         # genuine farmland bird -> should KEEP arable
]

# --- Resolve data root (git-ignored inputs live in the main checkout) --------
HERE = Path(__file__).resolve()
CODE_ROOT = HERE.parents[2]  # the checkout root holding code/ and outputs/
m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", str(CODE_ROOT))
DATA_ROOT = Path(m.group(1)) if m else CODE_ROOT

WEIGHTED_BASE = DATA_ROOT / "outputs" / "landcover_analysis" / "redlist_aggregate9_1km_weighted"
USED_CSV = WEIGHTED_BASE / "redlist_abundance_by_aggregate9_1km_weighted_wide.csv"
NAIVE_CSV = WEIGHTED_BASE / "redlist_aggregate9_1km_weighted_presence_matrix.csv"
COMPOSITION_CSV = (DATA_ROOT / "code" / "UKCEH_data" / "outputs"
                   / "ukceh_landcover_composition_3km_strategy2_aggregate9.csv")

OUT_DIR = DATA_ROOT / "outputs" / "landcover_analysis" / "selection_corrected"
OUT_SR = OUT_DIR / "aggregate9_selection_ratio.csv"
OUT_JACOBS = OUT_DIR / "aggregate9_jacobs.csv"
OUT_PRESENCE = OUT_DIR / "aggregate9_presence_corrected.csv"
OUT_PRESENCE_STRONG = OUT_DIR / "aggregate9_presence_corrected_strong.csv"
OUT_AVAIL = OUT_DIR / "aggregate9_availability.csv"
OUT_DIFF = OUT_DIR / "aggregate9_naive_vs_corrected_diff.csv"
OUT_PNG_PRESENCE = OUT_DIR / "aggregate9_corrected_presence.png"
OUT_PNG_DIFF = OUT_DIR / "aggregate9_naive_vs_corrected_diff.png"
OUT_SUMMARY = OUT_DIR / "SUMMARY.md"

ID_COLS = ["species_code", "common_name", "red_list_name"]


# --- Availability -----------------------------------------------------------

def compute_availability():
    """Summed composition percentage per class over land cells.

    Same composition basis as the 1 km-weighted `used` numerator: `used` sums
    abundance x composition-fraction, so availability sums composition alone.
    Returns (availability Series, diagnostics dict).
    """
    comp = pd.read_csv(COMPOSITION_CSV)
    n_all = len(comp)

    missing = [c for c in CATEGORIES if f"pct_{c}" not in comp.columns]
    if missing:
        raise SystemExit(
            f"Composition CSV is missing expected columns: "
            f"{', '.join('pct_' + c for c in missing)}"
        )

    land = comp[(comp["total_pct"] > 0) & (comp["dominant_name"] != "Undocumented")]
    n_land = len(land)

    availability = pd.Series(
        {c: float(land[f"pct_{c}"].sum()) for c in CATEGORIES},
        dtype=float,
    )

    diag = {
        "n_cells_total": n_all,
        "n_cells_land": n_land,
        "n_cells_excluded": n_all - n_land,
    }
    return availability, diag


# --- Metrics ----------------------------------------------------------------

def compute_metrics(used_df, availability):
    """Selection ratio and Jacobs' D per species x class.

    Returns (sr_df, jacobs_df, p_use_df, dropped) where the frames carry the ID
    columns plus one column per category, and `dropped` lists species whose use
    total was zero (they carry no habitat signal, so they are excluded).
    """
    used_cols = [f"weighted_{c}" for c in CATEGORIES]
    missing = [c for c in used_cols if c not in used_df.columns]
    if missing:
        raise SystemExit(f"Used-totals CSV is missing columns: {', '.join(missing)}")

    used = used_df[used_cols].to_numpy(dtype=float)
    used = np.nan_to_num(used, nan=0.0)

    totals = used.sum(axis=1)
    keep = totals > 0
    dropped = used_df.loc[~keep, ID_COLS].copy() if (~keep).any() else pd.DataFrame(columns=ID_COLS)

    used = used[keep]
    totals = totals[keep]
    ids = used_df.loc[keep, ID_COLS].reset_index(drop=True)

    # Share of each species' use per class. totals > 0 by construction.
    p_use = used / totals[:, None]

    avail = availability.reindex(CATEGORIES).to_numpy(dtype=float)
    avail_total = avail.sum()
    if avail_total <= 0:
        raise SystemExit("Total availability is zero -- check the composition CSV land mask.")
    p_avail = avail / avail_total

    # Classes with zero availability are undefined for SR/D: mask them out
    # rather than dividing by zero.
    zero_avail = p_avail <= 0
    safe_avail = np.where(zero_avail, np.nan, p_avail)

    sr = p_use / safe_avail[None, :]

    denom = p_use + p_avail[None, :] - 2.0 * p_use * p_avail[None, :]
    jacobs = np.where(denom > 0, (p_use - p_avail[None, :]) / np.where(denom > 0, denom, 1.0), np.nan)
    jacobs[:, zero_avail] = np.nan

    def frame(mat):
        out = pd.DataFrame(mat, columns=CATEGORIES)
        return pd.concat([ids, out], axis=1)

    return frame(sr), frame(jacobs), frame(p_use), dropped, p_avail, zero_avail


# --- Figures ----------------------------------------------------------------

def plot_presence(presence_df, out_path):
    """Binary heatmap of the corrected presence matrix (species x class)."""
    mat = presence_df[CATEGORIES].to_numpy(dtype=float)
    labels = presence_df["red_list_name"].tolist()

    fig, ax = plt.subplots(figsize=(9, max(8.0, 0.28 * len(labels))))
    cmap = ListedColormap(["#f2f2f2", "#2b7a4b"])
    ax.imshow(mat, cmap=cmap, vmin=0, vmax=1, aspect="auto", interpolation="nearest")

    ax.set_xticks(range(len(CATEGORIES)))
    ax.set_xticklabels([CATEGORY_LABELS[c] for c in CATEGORIES],
                       rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=7)

    ax.set_xticks(np.arange(-0.5, len(CATEGORIES), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(labels), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=0.8)
    ax.tick_params(which="minor", length=0)

    ax.set_title(
        f"Availability-corrected 'commonly found in' (SR >= {SR_THRESHOLD:g})\n"
        "Redlist species x UKCEH aggregate-9 classes, 1 km-weighted",
        fontsize=11, pad=12,
    )
    ax.legend(
        handles=[Patch(facecolor="#2b7a4b", label="Selected"),
                 Patch(facecolor="#f2f2f2", edgecolor="#cccccc", label="Not selected")],
        loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=False, fontsize=9,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_diff(naive_df, corrected_df, out_path):
    """Heatmap of how each cell changed: lost, unchanged, or gained."""
    naive = naive_df[CATEGORIES].to_numpy(dtype=bool)
    corr = corrected_df[CATEGORIES].to_numpy(dtype=bool)
    labels = corrected_df["red_list_name"].tolist()

    # -1 lost (naive True -> corrected False), 0 unchanged, +1 gained.
    diff = corr.astype(int) - naive.astype(int)

    fig, ax = plt.subplots(figsize=(9, max(8.0, 0.28 * len(labels))))
    cmap = ListedColormap(["#c0392b", "#f2f2f2", "#2471a3"])
    norm = BoundaryNorm([-1.5, -0.5, 0.5, 1.5], cmap.N)
    ax.imshow(diff, cmap=cmap, norm=norm, aspect="auto", interpolation="nearest")

    ax.set_xticks(range(len(CATEGORIES)))
    ax.set_xticklabels([CATEGORY_LABELS[c] for c in CATEGORIES],
                       rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=7)

    ax.set_xticks(np.arange(-0.5, len(CATEGORIES), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(labels), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=0.8)
    ax.tick_params(which="minor", length=0)

    ax.set_title(
        "Naive (Pareto-80 abundance) vs availability-corrected "
        f"(SR >= {SR_THRESHOLD:g})\nRedlist species x aggregate-9 classes",
        fontsize=11, pad=12,
    )
    ax.legend(
        handles=[Patch(facecolor="#2471a3", label="Gained (corrected only)"),
                 Patch(facecolor="#c0392b", label="Lost (naive only)"),
                 Patch(facecolor="#f2f2f2", edgecolor="#cccccc", label="Unchanged")],
        loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=False, fontsize=9,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


# --- Main -------------------------------------------------------------------

def main():
    print("=" * 78)
    print("15_selection_ratio_correction.py -- availability-corrected habitat selection")
    print("=" * 78)
    print("\nResolved input paths (auditable basis):")
    for label, path in [("used totals (1 km-weighted)", USED_CSV),
                        ("composition / availability", COMPOSITION_CSV),
                        ("naive presence matrix", NAIVE_CSV)]:
        status = "OK" if path.exists() else "MISSING"
        print(f"  [{status:>7}] {label:<28} {path}")
    print(f"\nOutput directory: {OUT_DIR}")
    print(f"Thresholds: SR >= {SR_THRESHOLD:g} (selected), SR >= {SR_STRONG_THRESHOLD:g} (strong)\n")

    for path in (USED_CSV, COMPOSITION_CSV, NAIVE_CSV):
        if not path.exists():
            raise SystemExit(
                f"Input not found: {path}\n"
                "Run the 11_/13_ aggregate-9 1 km-weighted pipeline first."
            )

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Availability -------------------------------------------------------
    availability, diag = compute_availability()
    p_avail_series = availability / availability.sum()

    print("Availability (summed composition %, land cells only):")
    print(f"  cells: {diag['n_cells_total']:,} total, {diag['n_cells_land']:,} land, "
          f"{diag['n_cells_excluded']:,} excluded (sea / undocumented)")
    for c in CATEGORIES:
        print(f"    {CATEGORY_LABELS[c]:<24} {availability[c]:>14,.0f}  "
              f"({100 * p_avail_series[c]:>5.2f}% of land)")
    print()

    avail_out = pd.DataFrame({
        "category": CATEGORIES,
        "category_label": [CATEGORY_LABELS[c] for c in CATEGORIES],
        "availability_sum_pct": [availability[c] for c in CATEGORIES],
        "p_avail": [p_avail_series[c] for c in CATEGORIES],
    })
    avail_out.to_csv(OUT_AVAIL, index=False)

    # 2. Metrics ------------------------------------------------------------
    used_df = pd.read_csv(USED_CSV)
    print(f"Loaded {len(used_df)} species from {USED_CSV.name}")

    if FOCAL_SPECIES:
        used_df["species_code"] = used_df["species_code"].astype(str).str.strip()
        missing = [c for c in FOCAL_SPECIES if c not in set(used_df["species_code"])]
        if missing:
            raise SystemExit(
                "FOCAL_SPECIES codes not present in the used totals: "
                + ", ".join(missing)
            )
        order = {c: i for i, c in enumerate(FOCAL_SPECIES)}
        used_df = (used_df[used_df["species_code"].isin(order)]
                   .assign(_o=lambda d: d["species_code"].map(order))
                   .sort_values("_o").drop(columns="_o").reset_index(drop=True))
        print(f"  filtered to the {len(used_df)} focal species")

    sr_df, jacobs_df, p_use_df, dropped, p_avail, zero_avail = compute_metrics(
        used_df, availability
    )

    if zero_avail.any():
        skipped = [CATEGORY_LABELS[c] for c, z in zip(CATEGORIES, zero_avail) if z]
        print(f"  NOTE: classes with zero availability skipped (SR/D = NaN): {', '.join(skipped)}")
    if len(dropped):
        print(f"  NOTE: {len(dropped)} species dropped for zero total use:")
        for _, r in dropped.iterrows():
            print(f"    - {r['red_list_name']} ({r['species_code']})")
    print(f"  {len(sr_df)} species carried forward\n")

    sr_df.to_csv(OUT_SR, index=False)
    jacobs_df.to_csv(OUT_JACOBS, index=False)

    # 3. Corrected presence -------------------------------------------------
    presence = sr_df.copy()
    presence[CATEGORIES] = (sr_df[CATEGORIES] >= SR_THRESHOLD).fillna(False)
    presence.to_csv(OUT_PRESENCE, index=False)

    presence_strong = sr_df.copy()
    presence_strong[CATEGORIES] = (sr_df[CATEGORIES] >= SR_STRONG_THRESHOLD).fillna(False)
    presence_strong.to_csv(OUT_PRESENCE_STRONG, index=False)

    # 4. Naive vs corrected -------------------------------------------------
    naive_df = pd.read_csv(NAIVE_CSV)
    # Align on species_code so row order differences cannot silently mis-pair.
    naive_aligned = (presence[["species_code"]]
                     .merge(naive_df, on="species_code", how="left", validate="one_to_one"))
    if naive_aligned[CATEGORIES].isna().any().any():
        missing_codes = naive_aligned.loc[
            naive_aligned[CATEGORIES].isna().any(axis=1), "species_code"].tolist()
        raise SystemExit(
            "Species present in the corrected matrix but absent from the naive "
            f"matrix: {', '.join(map(str, missing_codes))}"
        )

    diff_records = []
    for i in range(len(presence)):
        for c in CATEGORIES:
            n = bool(naive_aligned.iloc[i][c])
            k = bool(presence.iloc[i][c])
            diff_records.append({
                "species_code": presence.iloc[i]["species_code"],
                "common_name": presence.iloc[i]["common_name"],
                "red_list_name": presence.iloc[i]["red_list_name"],
                "category": c,
                "category_label": CATEGORY_LABELS[c],
                "naive": n,
                "corrected": k,
                "changed": n != k,
                "change_type": ("unchanged" if n == k else ("gained" if k else "lost")),
                "selection_ratio": float(sr_df.iloc[i][c]),
                "jacobs_d": float(jacobs_df.iloc[i][c]),
            })
    diff = pd.DataFrame.from_records(diff_records)
    diff.to_csv(OUT_DIFF, index=False)

    # 5. Figures ------------------------------------------------------------
    plot_presence(presence, OUT_PNG_PRESENCE)
    plot_diff(naive_aligned, presence, OUT_PNG_DIFF)

    # 6. Headline numbers ---------------------------------------------------
    n_species = len(presence)
    naive_counts = {c: int(naive_aligned[c].astype(bool).sum()) for c in CATEGORIES}
    corr_counts = {c: int(presence[c].astype(bool).sum()) for c in CATEGORIES}
    strong_counts = {c: int(presence_strong[c].astype(bool).sum()) for c in CATEGORIES}

    naive_per_species = naive_aligned[CATEGORIES].astype(bool).sum(axis=1)
    corr_per_species = presence[CATEGORIES].astype(bool).sum(axis=1)

    n_cells = n_species * len(CATEGORIES)
    n_changed = int(diff["changed"].sum())
    n_gained = int((diff["change_type"] == "gained").sum())
    n_lost = int((diff["change_type"] == "lost").sum())
    pct_changed = 100.0 * n_changed / n_cells
    pct_agree = 100.0 - pct_changed

    # Illustrative species, resolved by code with a common-name fallback.
    illustrative_rows = []
    for code, name in ILLUSTRATIVE:
        hit = sr_df[sr_df["species_code"] == code]
        if hit.empty:
            hit = sr_df[sr_df["common_name"].str.lower() == name.lower()]
        if hit.empty:
            print(f"  NOTE: illustrative species not found, skipped: {name} ({code})")
            continue
        idx = hit.index[0]
        illustrative_rows.append(idx)

    # --- stdout summary ----------------------------------------------------
    print("=" * 78)
    print("RESULTS")
    print("=" * 78)

    print("\n1. FARMLAND FLAGS -- naive vs availability-corrected "
          f"(n = {n_species} species)")
    for c in ("arable", "improved_grassland"):
        drop = naive_counts[c] - corr_counts[c]
        print(f"   {CATEGORY_LABELS[c]:<22} naive {naive_counts[c]:>2d}/{n_species}"
              f"  ->  corrected {corr_counts[c]:>2d}/{n_species}"
              f"   (drop of {drop}; strong SR>={SR_STRONG_THRESHOLD:g}: {strong_counts[c]})")

    print("\n   All classes:")
    print(f"   {'Class':<24} {'naive':>6} {'corrected':>10} {'strong':>7} {'p_avail':>9}")
    for c in CATEGORIES:
        print(f"   {CATEGORY_LABELS[c]:<24} {naive_counts[c]:>6d} {corr_counts[c]:>10d} "
              f"{strong_counts[c]:>7d} {100 * p_avail_series[c]:>8.2f}%")

    print("\n2. HABITATS SELECTED PER SPECIES")
    print(f"   naive     mean {naive_per_species.mean():.2f}  "
          f"(median {naive_per_species.median():.1f}, "
          f"range {naive_per_species.min()}-{naive_per_species.max()})")
    print(f"   corrected mean {corr_per_species.mean():.2f}  "
          f"(median {corr_per_species.median():.1f}, "
          f"range {corr_per_species.min()}-{corr_per_species.max()})")

    print("\n3. AGREEMENT BETWEEN MATRICES")
    print(f"   {n_changed}/{n_cells} cells changed ({pct_changed:.1f}%) -- "
          f"{pct_agree:.1f}% agreement")
    print(f"   gained (corrected only): {n_gained}    lost (naive only): {n_lost}")

    print("\n4. ILLUSTRATIVE SPECIES (selection ratios; * = selected, SR >= "
          f"{SR_THRESHOLD:g})")
    for idx in illustrative_rows:
        row = sr_df.loc[idx]
        print(f"\n   {row['red_list_name']} ({row['species_code']})")
        order = sorted(CATEGORIES, key=lambda c: -(0 if pd.isna(row[c]) else row[c]))
        for c in order:
            v = row[c]
            star = "*" if (not pd.isna(v) and v >= SR_THRESHOLD) else " "
            was = "naive-TRUE " if bool(naive_aligned.iloc[idx][c]) else "           "
            print(f"     {star} {CATEGORY_LABELS[c]:<24} SR {v:>7.2f}   "
                  f"D {jacobs_df.loc[idx, c]:>6.2f}   {was}")

    # --- SUMMARY.md --------------------------------------------------------
    lines = []
    lines.append("# Availability-corrected habitat selection (aggregate-9, 1 km-weighted)\n")
    lines.append(
        "The naive \"commonly found in\" matrix ranks land-cover classes by summed "
        "abundance and keeps the cumulative-80% \"vital few\". Because Arable and "
        "Improved Grassland dominate the UK's land area, almost every species' "
        "abundance accumulates there, so that matrix largely measures habitat "
        "**availability** rather than habitat **association**.\n"
    )
    lines.append(
        "This analysis divides each species' habitat use by how much of that habitat "
        "exists, so a class counts as selected only when it is used more than its "
        "share of the landscape would predict.\n"
    )

    lines.append("## Method\n")
    lines.append(
        "The used totals from `11_redlist_abundance_by_aggregate9_1km_weighted.R` are "
        "1 km-composition-weighted: each 3 km cell's yearly abundance was split across "
        "the 9 classes by the cell's 1 km land-cover mix, then summed. Availability is "
        "computed on the **same composition basis** — the summed composition percentage "
        "of each class over land cells — so numerator and denominator share units.\n"
    )
    lines.append("```")
    lines.append("used[s,h]      = sum over cells of ( abundance[s,cell] * frac_h[cell] )")
    lines.append("availability[h] = sum over land cells of pct_h[cell]")
    lines.append("p_use[s,h]      = used[s,h] / sum_h used[s,h]")
    lines.append("p_avail[h]      = availability[h] / sum_h availability[h]")
    lines.append("SR[s,h]         = p_use / p_avail                    (>1 = used more than available)")
    lines.append("Jacobs' D[s,h]  = (p_use - p_avail) / (p_use + p_avail - 2*p_use*p_avail)   (-1..1)")
    lines.append("```\n")
    lines.append(
        f"Land cells only ({diag['n_cells_land']:,} of {diag['n_cells_total']:,}; "
        f"{diag['n_cells_excluded']:,} sea/undocumented cells excluded). "
        f"Selected = `SR >= {SR_THRESHOLD:g}`; the strong-association sensitivity check "
        f"uses `SR >= {SR_STRONG_THRESHOLD:g}`.\n"
    )
    if len(dropped):
        names = ", ".join(f"{r['red_list_name']} ({r['species_code']})"
                          for _, r in dropped.iterrows())
        lines.append(f"Species dropped for zero total use: {names}.\n")
    else:
        lines.append("No species were dropped (all had non-zero total use).\n")

    lines.append("### Caveat: availability is UK-wide\n")
    lines.append(
        "Availability here is the whole-UK landscape. A species restricted to part of "
        "the country is still scored against the national composition, which inflates "
        "SR for habitats concentrated in its range and deflates it for habitats "
        "concentrated outside it. The documented refinement — not applied here — is to "
        "restrict the availability sum to each species' occupied range (cells with "
        "abundance > 0), which requires the per-cell abundance tables rather than the "
        "per-species totals used in this script.\n"
    )

    lines.append("## 1. Farmland flags: naive vs corrected\n")
    lines.append(f"| Class | Naive | Corrected (SR≥{SR_THRESHOLD:g}) | Change | Strong (SR≥{SR_STRONG_THRESHOLD:g}) | % of UK land |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for c in ("arable", "improved_grassland"):
        d = corr_counts[c] - naive_counts[c]
        lines.append(f"| **{CATEGORY_LABELS[c]}** | {naive_counts[c]}/{n_species} | "
                     f"{corr_counts[c]}/{n_species} | {d:+d} | {strong_counts[c]} | "
                     f"{100 * p_avail_series[c]:.2f}% |")
    lines.append("")
    lines.append("All nine classes:\n")
    lines.append(f"| Class | Naive | Corrected (SR≥{SR_THRESHOLD:g}) | Change | Strong (SR≥{SR_STRONG_THRESHOLD:g}) | % of UK land |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for c in CATEGORIES:
        d = corr_counts[c] - naive_counts[c]
        lines.append(f"| {CATEGORY_LABELS[c]} | {naive_counts[c]} | {corr_counts[c]} | "
                     f"{d:+d} | {strong_counts[c]} | {100 * p_avail_series[c]:.2f}% |")
    lines.append("")

    lines.append("## 2. Habitats selected per species\n")
    lines.append("| Matrix | Mean | Median | Range |")
    lines.append("|---|---:|---:|---:|")
    lines.append(f"| Naive | {naive_per_species.mean():.2f} | {naive_per_species.median():.1f} | "
                 f"{naive_per_species.min()}–{naive_per_species.max()} |")
    lines.append(f"| Corrected | {corr_per_species.mean():.2f} | {corr_per_species.median():.1f} | "
                 f"{corr_per_species.min()}–{corr_per_species.max()} |")
    lines.append("")

    lines.append("## 3. Agreement between the two matrices\n")
    lines.append(f"- Cells compared: **{n_cells}** ({n_species} species × {len(CATEGORIES)} classes)")
    lines.append(f"- Changed: **{n_changed} ({pct_changed:.1f}%)** — agreement **{pct_agree:.1f}%**")
    lines.append(f"- Gained (corrected only): **{n_gained}**")
    lines.append(f"- Lost (naive only): **{n_lost}**\n")

    lines.append("## 4. Illustrative species\n")
    lines.append(
        "Selection ratios per class. **Bold** = selected under the corrected rule "
        f"(SR ≥ {SR_THRESHOLD:g}); the *Naive* column shows what the old matrix flagged.\n"
    )
    for idx in illustrative_rows:
        row = sr_df.loc[idx]
        lines.append(f"### {row['red_list_name']} (`{row['species_code']}`)\n")
        lines.append("| Class | SR | Jacobs' D | Corrected | Naive |")
        lines.append("|---|---:|---:|:--:|:--:|")
        order = sorted(CATEGORIES, key=lambda c: -(0 if pd.isna(row[c]) else row[c]))
        for c in order:
            v = row[c]
            sel = (not pd.isna(v)) and v >= SR_THRESHOLD
            label = f"**{CATEGORY_LABELS[c]}**" if sel else CATEGORY_LABELS[c]
            lines.append(
                f"| {label} | {v:.2f} | {jacobs_df.loc[idx, c]:.2f} | "
                f"{'✓' if sel else '·'} | "
                f"{'✓' if bool(naive_aligned.iloc[idx][c]) else '·'} |"
            )
        lines.append("")

    lines.append("## 5. Figures\n")
    lines.append(f"- `{OUT_PNG_PRESENCE.name}` — corrected presence matrix (species × class).")
    lines.append(f"- `{OUT_PNG_DIFF.name}` — diff vs the naive matrix (gained / lost / unchanged).\n")

    lines.append("## Files\n")
    for p, desc in [
        (OUT_SR, "selection ratios (species × class)"),
        (OUT_JACOBS, "Jacobs' D (species × class)"),
        (OUT_PRESENCE, f"corrected presence, SR ≥ {SR_THRESHOLD:g}"),
        (OUT_PRESENCE_STRONG, f"strong-association presence, SR ≥ {SR_STRONG_THRESHOLD:g}"),
        (OUT_AVAIL, "availability per class"),
        (OUT_DIFF, "long-format naive vs corrected comparison"),
    ]:
        lines.append(f"- `{p.name}` — {desc}")
    lines.append("")
    lines.append("Generated by `code/landcover_analysis/15_selection_ratio_correction.py`.")

    OUT_SUMMARY.write_text("\n".join(lines))

    print("\n" + "=" * 78)
    print("Wrote:")
    for p in (OUT_SR, OUT_JACOBS, OUT_PRESENCE, OUT_PRESENCE_STRONG, OUT_AVAIL,
              OUT_DIFF, OUT_PNG_PRESENCE, OUT_PNG_DIFF, OUT_SUMMARY):
        print(f"  {p}")

    print("\n" + "=" * 78)
    print("HEADLINE")
    print("=" * 78)
    print(f"  Arable            : naive {naive_counts['arable']}/{n_species}"
          f"  ->  corrected {corr_counts['arable']}/{n_species}")
    print(f"  Improved grassland: naive {naive_counts['improved_grassland']}/{n_species}"
          f"  ->  corrected {corr_counts['improved_grassland']}/{n_species}")
    print(f"  Habitats/species  : naive {naive_per_species.mean():.2f}"
          f"  ->  corrected {corr_per_species.mean():.2f}")
    print(f"  Matrix agreement  : {pct_agree:.1f}%  ({n_changed}/{n_cells} cells changed;"
          f" {n_gained} gained, {n_lost} lost)")
    print("=" * 78)


if __name__ == "__main__":
    main()
