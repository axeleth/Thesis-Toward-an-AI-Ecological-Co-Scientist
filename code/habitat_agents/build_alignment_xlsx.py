#!/usr/bin/env python3
"""build_alignment_xlsx.py  --  three-way alignment scaffold (Data vs Agent vs Book)

Builds `alignment.xlsx`, one row per red-list species, comparing WHICH habitats
each source says the bird is "commonly found in":

    | Species | Data | Agent | Data–LLM | Book | Data–Book |

- **Data**   : ALL habitats in the data's Pareto-80 "commonly found in" set (the
               True columns of the data presence matrix), listed.
- **Agent**  : ALL habitats the BLIND agent marks "Documented" (True), listed.
- **Data–LLM**: how aligned the two SETS are, as a Jaccard overlap percentage --
                 |Data ∩ Agent| / |Data ∪ Agent| × 100. 100% = identical sets,
                 0% = no habitat in common. Blank ("—") when the agent verdict for
                 that species is missing (e.g. the blind run hasn't reached it).
- **Book**   : BLANK -- manual entry from the physical RSPB Handbook of British
               Birds (the independent human validation anchor).
- **Data–Book**: BLANK -- Axel fills by hand once Book is entered.

Data source is the PRIMARY aggregate-9 (1 km-weighted) presence matrix. The Agent
is the blind habitat agent (knowledge only, no data shown). Re-run this after the
blind agent finishes to fill any species the run had not yet reached.

Usage:
    python code/habitat_agents/build_alignment_xlsx.py
    python code/habitat_agents/build_alignment_xlsx.py --out /path/to/alignment.xlsx
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys

# Reuse the canonical category order + labels so wording matches the rest of the
# project (Woodland, Arable, ...). _agent_common lives next to this file.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _agent_common as ac  # noqa: E402

# --- Paths (worktree-aware; git-ignored outputs live in the MAIN checkout) ----
HERE = os.path.dirname(os.path.abspath(__file__))
CODE_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))  # holds code/ + outputs/
_m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", CODE_ROOT)
DATA_ROOT = _m.group(1) if _m else CODE_ROOT

AGG9_DIR = os.path.join(
    DATA_ROOT, "outputs", "landcover_analysis", "redlist_aggregate9_1km_weighted"
)
# Data ground truth: the Pareto-80 presence matrix (True/False per habitat).
DATA_MATRIX = os.path.join(
    AGG9_DIR, "redlist_aggregate9_1km_weighted_presence_matrix.csv"
)
BLIND_MATRIX = os.path.join(
    DATA_ROOT, "outputs", "habitat_agents", "blind_presence_matrix.csv"
)
DEFAULT_OUT = os.path.join(DATA_ROOT, "alignment.xlsx")

CATEGORIES = ac.CATEGORIES               # 9 slugs, canonical order
LABELS = ac.CATEGORY_LABELS              # slug -> human label


def _true_slugs(row: dict) -> list[str]:
    """The habitat slugs marked True in a presence-matrix row, canonical order."""
    return [c for c in CATEGORIES if str(row.get(c, "")).strip().lower() == "true"]


def load_data_sets() -> tuple[list[dict], dict[str, list[str]]]:
    """Return (roster, {species_code -> [True habitat slugs]}) from the data matrix.

    roster preserves file order and carries species_code/common_name/red_list_name.
    """
    if not os.path.exists(DATA_MATRIX):
        sys.exit(
            f"ERROR: data presence matrix not found:\n  {DATA_MATRIX}\n"
            "Run code/landcover_analysis/"
            "13_aggregate9_1km_weighted_presence_matrix.py first."
        )
    roster: list[dict] = []
    data_sets: dict[str, list[str]] = {}
    with open(DATA_MATRIX, "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            code = row["species_code"]
            roster.append(
                {
                    "species_code": code,
                    "common_name": row["common_name"],
                    "red_list_name": row.get("red_list_name", ""),
                }
            )
            data_sets[code] = _true_slugs(row)
    return roster, data_sets


def load_agent_sets() -> tuple[dict[str, list[str]], set[str]]:
    """Return ({species_code -> [Documented habitat slugs]}, set_of_codes_present).

    Species absent from the matrix (partial live run) are simply not in the dict /
    present-set.
    """
    if not os.path.exists(BLIND_MATRIX):
        sys.exit(
            f"ERROR: blind agent matrix not found:\n  {BLIND_MATRIX}\n"
            "Run code/habitat_agents/run_blind_agent.py first."
        )
    agent_sets: dict[str, list[str]] = {}
    present: set[str] = set()
    with open(BLIND_MATRIX, "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            code = row["species_code"]
            present.add(code)
            agent_sets[code] = _true_slugs(row)
    return agent_sets, present


def jaccard_pct(a: list[str], b: list[str]) -> int:
    """|a ∩ b| / |a ∪ b| as a rounded percentage.

    Both empty -> 100 (they agree the bird is commonly found nowhere). One empty and
    the other not -> 0.
    """
    sa, sb = set(a), set(b)
    union = sa | sb
    if not union:
        return 100
    return round(100 * len(sa & sb) / len(union))


def fmt_set(slugs: list[str]) -> str:
    """Comma-separated human labels for a habitat set (canonical order); '—' if none."""
    if not slugs:
        return "—"
    return ", ".join(LABELS.get(s, s) for s in slugs)


def build_rows() -> list[dict]:
    roster, data_sets = load_data_sets()
    agent_sets, present = load_agent_sets()

    n_missing = sum(1 for sp in roster if sp["species_code"] not in present)
    if n_missing:
        print(
            f"NOTE: {n_missing}/{len(roster)} species have no blind-agent verdict "
            f"yet (live run in progress?). Their Agent cell and Data–LLM are blank. "
            f"Re-run this script once the blind agent finishes."
        )

    rows = []
    for sp in roster:
        code = sp["species_code"]
        d = data_sets.get(code, [])
        a = agent_sets.get(code, [])
        a_present = code in present
        rows.append(
            {
                "species_code": code,
                "Species": sp["common_name"],
                "Data": fmt_set(d),
                "Agent": fmt_set(a) if a_present else "",
                "Data–LLM": f"{jaccard_pct(d, a)}%" if a_present else "",
                "Book": "",          # manual entry (RSPB Handbook)
                "Data–Book": "",     # manual entry
            }
        )
    return rows


COLUMNS = ["Species", "Data", "Agent", "Data–LLM", "Book", "Data–Book", "species_code"]


def write_xlsx(rows: list[dict], out_path: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "alignment"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="4A3AA7")  # project violet
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    manual_fill = PatternFill("solid", fgColor="FFF6E5")  # tint the manual columns

    # Header
    for j, col in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=j, value=col)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center

    marker_cols = {"Data–LLM", "Data–Book"}
    manual_cols = {"Book", "Data–Book"}
    set_cols = {"Data", "Agent", "Book"}     # may hold multi-habitat lists -> wrap

    for i, r in enumerate(rows, start=2):
        for j, col in enumerate(COLUMNS, start=1):
            cell = ws.cell(row=i, column=j, value=r.get(col, ""))
            if col in marker_cols:
                cell.alignment = center
            elif col in set_cols:
                cell.alignment = left        # wrap the habitat lists
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")
            if col in manual_cols:
                cell.fill = manual_fill

    # Column widths (wider Data/Agent/Book since they list multiple habitats).
    widths = {
        "Species": 26, "Data": 34, "Agent": 34, "Data–LLM": 10,
        "Book": 34, "Data–Book": 11, "species_code": 12,
    }
    for j, col in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(j)].width = widths.get(col, 16)

    ws.freeze_panes = "A2"  # keep header visible while scrolling

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    wb.save(out_path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=DEFAULT_OUT, help="Output .xlsx path.")
    args = ap.parse_args()

    rows = build_rows()
    write_xlsx(rows, args.out)

    # Console summary: distribution of the Jaccard alignment across species.
    n = len(rows)
    scored = [r["Data–LLM"] for r in rows if r["Data–LLM"]]
    if scored:
        vals = [int(s.rstrip("%")) for s in scored]
        n_full = sum(1 for v in vals if v == 100)
        n_zero = sum(1 for v in vals if v == 0)
        mean = round(sum(vals) / len(vals))
        print(f"\nWrote {args.out}")
        print(f"  {n} species x {len(COLUMNS)} columns (agent = blind)")
        print(
            f"  Data–LLM Jaccard overlap: mean {mean}%  "
            f"(identical={n_full}, no-overlap={n_zero}, scored={len(vals)}/{n})"
        )
    else:
        print(f"\nWrote {args.out}\n  {n} species (no agent verdicts scored yet)")
    print("  Book and Data–Book left blank for manual RSPB-Handbook entry.")


if __name__ == "__main__":
    main()
