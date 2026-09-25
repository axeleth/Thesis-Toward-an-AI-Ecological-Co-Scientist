#!/usr/bin/env python3
"""build_alignment_adjusted_xlsx.py  --  alignment.xlsx with availability-corrected Data

Creates `alignment_adjusted.xlsx`: a copy of the hand-annotated `alignment.xlsx`
in which the **Data** column is rebuilt from the availability-corrected habitat
selection matrix (SR >= 1) instead of the naive Pareto-80 abundance matrix.

WHY A COPY-AND-PATCH, NOT A REGENERATE
--------------------------------------
`alignment.xlsx` has been edited by hand since `build_alignment_xlsx.py` produced
it. It now carries work that exists nowhere else:

  - 40 hand-entered `Book` values (RSPB Handbook, the human validation anchor)
  - `Data-Book` entries
  - free-text research notes in unlabelled columns H/I (page refs such as "p199",
    "Notable Disagreement", taxonomic caveats like the Leach's Petrel amber note)

Re-running the generator would destroy all of that. So this script opens the
workbook, copies every cell with its value and formatting, and rewrites ONLY the
`Data` column (plus `Data-LLM`, which is derived from it). Everything else --
including the H/I notes and the manual highlighting -- is carried across byte for
byte. The original file is never modified.

WHAT CHANGES
------------
`Data` switches from the naive presence matrix

    outputs/landcover_analysis/redlist_aggregate9_1km_weighted/
        redlist_aggregate9_1km_weighted_presence_matrix.csv

to the availability-corrected one

    outputs/landcover_analysis/selection_corrected/
        aggregate9_presence_corrected.csv

The naive matrix ranks classes by summed abundance, so Arable and Improved
Grassland -- which dominate the UK's land area -- were flagged for nearly every
species. The corrected matrix divides use by availability (selection ratio) and
keeps a class only where the bird uses it more than the landscape would predict.
See code/landcover_analysis/15_selection_ratio_correction.py.

`Data-LLM` is recomputed as the Jaccard overlap of the NEW Data set against the
existing Agent set, in the same decimal format the live workbook uses (e.g. 0.25).

`Book` and `Data-Book` are left exactly as found -- Data-Book is a manual
judgement and is deliberately NOT recomputed, even where it is blank.

Usage:
    python code/habitat_agents/build_alignment_adjusted_xlsx.py
    python code/habitat_agents/build_alignment_adjusted_xlsx.py --out /path/to/file.xlsx
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from copy import copy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _agent_common as ac  # noqa: E402

# --- Paths (worktree-aware; git-ignored data lives in the MAIN checkout) ------
HERE = os.path.dirname(os.path.abspath(__file__))
CODE_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
_m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", CODE_ROOT)
DATA_ROOT = _m.group(1) if _m else CODE_ROOT

SRC_XLSX = os.path.join(DATA_ROOT, "alignment.xlsx")
DEFAULT_OUT = os.path.join(DATA_ROOT, "alignment_adjusted.xlsx")

# The availability-corrected presence matrix (SR >= 1) -- the new Data source.
CORRECTED_MATRIX = os.path.join(
    DATA_ROOT, "outputs", "landcover_analysis", "selection_corrected",
    "aggregate9_presence_corrected.csv",
)
# The naive matrix, read only to report how many cells the swap changes.
NAIVE_MATRIX = os.path.join(
    DATA_ROOT, "outputs", "landcover_analysis", "redlist_aggregate9_1km_weighted",
    "redlist_aggregate9_1km_weighted_presence_matrix.csv",
)

CATEGORIES = ac.CATEGORIES
LABELS = ac.CATEGORY_LABELS

DATA_COL_NAME = "Data"
AGENT_COL_NAME = "Agent"
LLM_COL_NAME = "Data–LLM"   # en-dash, as written by the generator
CODE_COL_NAME = "species_code"


def _true_slugs(row: dict) -> list[str]:
    """Habitat slugs marked True in a presence-matrix row, canonical order."""
    return [c for c in CATEGORIES if str(row.get(c, "")).strip().lower() == "true"]


def load_matrix(path: str, what: str) -> dict[str, list[str]]:
    if not os.path.exists(path):
        sys.exit(
            f"ERROR: {what} not found:\n  {path}\n"
            "Run code/landcover_analysis/15_selection_ratio_correction.py first."
        )
    out: dict[str, list[str]] = {}
    with open(path, "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["species_code"]] = _true_slugs(row)
    return out


def fmt_set(slugs: list[str]) -> str:
    """Comma-separated human labels, canonical order; em-dash when empty."""
    if not slugs:
        return "—"
    return ", ".join(LABELS.get(s, s) for s in slugs)


def parse_labels(text: str) -> set[str]:
    """Parse an existing Data/Agent cell back into a set of habitat slugs.

    The workbook's Agent cells were written with the same labels this script
    emits, but hand-editing means separators vary (comma or semicolon) and case
    drifts ("Built-Up" vs "Built-up"). Match on a normalised label, and fall back
    to substring matching so a stray "and" ("Mountain, heath and bog") still
    resolves. Unrecognised fragments are ignored rather than guessed at.
    """
    if not text or str(text).strip() in ("", "—", "-"):
        return set()
    raw = str(text)
    norm_raw = re.sub(r"[^a-z]", "", raw.lower())
    found: set[str] = set()
    for slug in CATEGORIES:
        label_key = re.sub(r"[^a-z]", "", LABELS.get(slug, slug).lower())
        slug_key = re.sub(r"[^a-z]", "", slug.lower())
        if label_key and label_key in norm_raw:
            found.add(slug)
        elif slug_key and slug_key in norm_raw:
            found.add(slug)
    return found


def jaccard(a: set[str], b: set[str]) -> float:
    """|a ∩ b| / |a ∪ b|. Both empty -> 1.0 (they agree on 'nowhere')."""
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=DEFAULT_OUT, help="Output .xlsx path.")
    args = ap.parse_args()

    from openpyxl import load_workbook, Workbook

    if not os.path.exists(SRC_XLSX):
        sys.exit(f"ERROR: source workbook not found:\n  {SRC_XLSX}")

    print("=" * 78)
    print("build_alignment_adjusted_xlsx.py -- swap Data to availability-corrected")
    print("=" * 78)
    print("\nResolved paths:")
    for label, p in [("source workbook", SRC_XLSX),
                     ("corrected matrix (new Data)", CORRECTED_MATRIX),
                     ("naive matrix (for diff report)", NAIVE_MATRIX)]:
        print(f"  [{'OK' if os.path.exists(p) else 'MISSING':>7}] {label:<30} {p}")
    print(f"\nOutput: {args.out}\n")

    corrected = load_matrix(CORRECTED_MATRIX, "availability-corrected presence matrix")
    naive = load_matrix(NAIVE_MATRIX, "naive presence matrix")

    src = load_workbook(SRC_XLSX)
    dst = Workbook()
    dst.remove(dst.active)

    n_updated = 0
    n_llm_updated = 0
    changed_species: list[tuple[str, str, str]] = []
    missing_codes: list[str] = []

    for ws in src.worksheets:
        out_ws = dst.create_sheet(title=ws.title)

        # Locate the columns by header text so a layout change cannot silently
        # write into the wrong column.
        header = {}
        for cell in ws[1]:
            if cell.value is not None:
                header[str(cell.value).strip()] = cell.column

        data_col = header.get(DATA_COL_NAME)
        agent_col = header.get(AGENT_COL_NAME)
        llm_col = header.get(LLM_COL_NAME)
        code_col = header.get(CODE_COL_NAME)

        if ws.title == "alignment":
            if not data_col or not code_col:
                sys.exit(
                    f"ERROR: could not find '{DATA_COL_NAME}' and '{CODE_COL_NAME}' "
                    f"columns in sheet '{ws.title}'. Found: {sorted(header)}"
                )

        # --- copy every cell, value + style, then patch Data / Data-LLM ------
        for row in ws.iter_rows():
            for cell in row:
                new = out_ws.cell(row=cell.row, column=cell.column, value=cell.value)
                if cell.has_style:
                    new.font = copy(cell.font)
                    new.fill = copy(cell.fill)
                    new.border = copy(cell.border)
                    new.alignment = copy(cell.alignment)
                    new.number_format = cell.number_format
                    new.protection = copy(cell.protection)

        if ws.title == "alignment" and data_col and code_col:
            for r in range(2, ws.max_row + 1):
                code = ws.cell(row=r, column=code_col).value
                if not code:
                    continue
                code = str(code).strip()
                if code not in corrected:
                    missing_codes.append(code)
                    continue

                old_txt = ws.cell(row=r, column=data_col).value
                new_slugs = corrected[code]
                new_txt = fmt_set(new_slugs)
                out_ws.cell(row=r, column=data_col, value=new_txt)
                n_updated += 1

                if str(old_txt or "").strip() != new_txt:
                    species = ws.cell(row=r, column=1).value or code
                    changed_species.append((str(species), str(old_txt or ""), new_txt))

                # Recompute Data-LLM against the untouched Agent cell, keeping the
                # workbook's existing decimal style. Blank Agent (no verdict yet)
                # stays blank rather than scoring a spurious 0.
                if llm_col and agent_col:
                    agent_raw = ws.cell(row=r, column=agent_col).value
                    if agent_raw is None or str(agent_raw).strip() == "":
                        continue
                    j = jaccard(set(new_slugs), parse_labels(agent_raw))
                    out_cell = out_ws.cell(row=r, column=llm_col)
                    out_cell.value = round(j, 2)
                    n_llm_updated += 1

        # Carry across widths, freeze panes and merges so it opens identically.
        for key, dim in ws.column_dimensions.items():
            out_ws.column_dimensions[key].width = dim.width
            out_ws.column_dimensions[key].hidden = dim.hidden
        for key, dim in ws.row_dimensions.items():
            out_ws.row_dimensions[key].height = dim.height
        # Pin only the header row. The source workbook has freeze_panes = "A27"
        # (set by hand in Excel with the cursor parked on row 27), which locks
        # rows 1-26 in place and makes them unscrollable. Normalise to "A2".
        out_ws.freeze_panes = "A2" if ws.title == "alignment" else ws.freeze_panes
        for rng in ws.merged_cells.ranges:
            out_ws.merge_cells(str(rng))

    dst.save(args.out)

    # --- report ------------------------------------------------------------
    if missing_codes:
        print(f"NOTE: {len(missing_codes)} species in the workbook have no corrected "
              f"row (Data left as-is): {', '.join(missing_codes)}")

    print(f"Rewrote Data for {n_updated} species; "
          f"recomputed Data–LLM for {n_llm_updated}.")
    print(f"Data changed for {len(changed_species)}/{n_updated} species.\n")

    # How the farmland flags moved, the point of the correction.
    for slug in ("arable", "improved_grassland"):
        n_naive = sum(1 for c in naive if slug in naive[c])
        n_corr = sum(1 for c in corrected if slug in corrected[c])
        print(f"  {LABELS.get(slug, slug):<22} naive {n_naive:>2d}/50  ->  "
              f"corrected {n_corr:>2d}/50")

    print("\nExample rows (old Data -> new Data):")
    for species, old, new in changed_species[:6]:
        print(f"  {species}")
        print(f"     was: {old[:70]}")
        print(f"     now: {new[:70]}")

    print(f"\nWrote {args.out}")
    print("  Book, Data–Book and the free-text note columns were copied "
          "unchanged from alignment.xlsx.")


if __name__ == "__main__":
    main()
