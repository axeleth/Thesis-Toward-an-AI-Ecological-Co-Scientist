#!/usr/bin/env python3
"""16_data_vs_book_matrix.py  --  side-by-side Data vs Book verdict matrix

Builds a WIDE matrix: the availability-corrected DATA verdicts (SR >= 1) beside
the RSPB Handbook BOOK verdicts, over the 41 focal redlist species x 9 aggregate-9
classes, plus per-species precision / recall / accuracy scored against the Book.

    | Species | DATA: 9 class cols | BOOK: 9 class cols | TP FP FN TN | P R Acc |

SCORING -- the Book is GROUND TRUTH, Data is the prediction:
    TP  Data says yes, Book says yes        FP  Data says yes, Book says no
    FN  Data says no,  Book says yes        TN  Data says no,  Book says no

    Precision = TP / (TP + FP)   of the habitats Data flagged, how many are real
    Recall    = TP / (TP + FN)   of the habitats the Book lists, how many Data found
    Accuracy  = (TP + TN) / 9    correct cells over all nine classes

Precision is N/A when Data flags nothing (0/0), recall is N/A when the Book lists
nothing; those are undefined, not zero, and are reported as such.

SPECIES WITH NO BOOK ENTRY are kept as rows -- the Data half is real, the
Book half is blank (written as "" in the CSV, hatched grey in the figure) and all
scores are N/A. A missing Handbook entry is NOT the Handbook saying "no habitat":
collapsing the two would silently manufacture 9 true negatives per species and
inflate accuracy. They are excluded from every aggregate.

Both MACRO and MICRO averages are reported, because they answer different
questions and can disagree:
    macro = mean of the per-species scores      (every species counts equally)
    micro = pooled TP/FP/FN across all species  (every habitat call counts equally)

Inputs:
    outputs/landcover_analysis/selection_corrected/aggregate9_presence_corrected.csv
    alignment_adjusted.xlsx  (Book column, canonicalised by normalise_book_column.py)

Outputs (new files only):
    outputs/landcover_analysis/selection_corrected/aggregate9_data_vs_book_matrix.csv
    outputs/landcover_analysis/selection_corrected/aggregate9_data_vs_book.png
    outputs/landcover_analysis/selection_corrected/DATA_VS_BOOK_SUMMARY.md

Usage:
    python code/landcover_analysis/16_data_vs_book_matrix.py
"""

from __future__ import annotations

import os
import re
import sys

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Patch

# Canonical labels live with the habitat agents; reuse so wording matches.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "habitat_agents"))
import _agent_common as ac  # noqa: E402

# The canonical 41-species study set lives in code/focal_species.json; import its
# loader from the code/ directory (this script lives in code/landcover_analysis/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import focal_species  # noqa: E402

CODE_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
_m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", CODE_ROOT)
DATA_ROOT = _m.group(1) if _m else CODE_ROOT

SEL_DIR = os.path.join(DATA_ROOT, "outputs", "landcover_analysis", "selection_corrected")
CORRECTED_MATRIX = os.path.join(SEL_DIR, "aggregate9_presence_corrected.csv")
ALIGNMENT_XLSX = os.path.join(DATA_ROOT, "alignment_adjusted.xlsx")

OUT_CSV = os.path.join(SEL_DIR, "aggregate9_data_vs_book_matrix.csv")
OUT_PNG = os.path.join(SEL_DIR, "aggregate9_data_vs_book.png")
OUT_MD = os.path.join(SEL_DIR, "DATA_VS_BOOK_SUMMARY.md")

CATEGORIES = ac.CATEGORIES
LABELS = ac.CATEGORY_LABELS
N_CLASSES = len(CATEGORIES)

# NOTE: the species roster is inherited from aggregate9_presence_corrected.csv,
# which 15_selection_ratio_correction.py filters to the 41 focal species. Those
# 41 are defined once, canonically, in `code/focal_species.json` (loaded via
# code/focal_species.py); script 15 reads that file and this script inherits the
# result. To change which species appear here, edit code/focal_species.json and
# re-run script 15 before this one -- do not filter separately, or the two would
# drift apart.
#
# The check below is a guard, not a second filter: it re-reads the canonical file
# and fails loudly if what we inherited is not exactly those 41 species.

SHEET = "alignment"
BOOK_COL_NAME = "Book"
CODE_COL_NAME = "species_code"


def norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", str(s).lower())


# Canonical label -> slug. The Book column is already canonicalised, so an exact
# match is expected; the normalised form guards against stray whitespace/case.
CANON = {norm(LABELS[s]): s for s in CATEGORIES}
CANON.update({norm(s): s for s in CATEGORIES})


def parse_book(cell) -> set[str] | None:
    """Semicolon-separated canonical labels -> slug set. None means NO ENTRY.

    None (no Handbook entry) is deliberately distinct from set() (the Handbook
    was consulted and lists none of the nine classes).
    """
    if cell is None or str(cell).strip() == "":
        return None
    out: set[str] = set()
    for part in str(cell).split(";"):
        key = norm(part)
        if not key:
            continue
        if key in CANON:
            out.add(CANON[key])
        else:
            # Fall back to substring so an unexpected edit still resolves.
            for cand, slug in CANON.items():
                if cand and cand in key:
                    out.add(slug)
                    break
            else:
                print(f"  WARNING: unrecognised Book fragment {part.strip()!r} -- ignored")
    return out


def load_book() -> dict[str, set[str] | None]:
    from openpyxl import load_workbook

    if not os.path.exists(ALIGNMENT_XLSX):
        sys.exit(f"ERROR: workbook not found:\n  {ALIGNMENT_XLSX}")
    wb = load_workbook(ALIGNMENT_XLSX, data_only=True)
    ws = wb[SHEET]

    header = {}
    for cell in ws[1]:
        if cell.value is not None:
            header[str(cell.value).strip()] = cell.column
    book_col = header.get(BOOK_COL_NAME)
    code_col = header.get(CODE_COL_NAME)
    if not book_col or not code_col:
        sys.exit(f"ERROR: need '{BOOK_COL_NAME}' and '{CODE_COL_NAME}' columns; "
                 f"found {sorted(header)}")

    out: dict[str, set[str] | None] = {}
    for r in range(2, ws.max_row + 1):
        code = ws.cell(row=r, column=code_col).value
        if not code:
            continue
        out[str(code).strip()] = parse_book(ws.cell(row=r, column=book_col).value)
    return out


def safe_div(num: int, den: int) -> float | None:
    """None when undefined (0/0), rather than a misleading 0.0."""
    return None if den == 0 else num / den


def fmt_score(v: float | None) -> str:
    return "N/A" if v is None else f"{v:.3f}"


def main() -> None:
    print("=" * 78)
    print("16_data_vs_book_matrix.py -- Data vs Book verdicts, scored on the Book")
    print("=" * 78)
    print("\nResolved inputs:")
    for label, p in [("corrected Data matrix", CORRECTED_MATRIX),
                     ("Book column (workbook)", ALIGNMENT_XLSX)]:
        print(f"  [{'OK' if os.path.exists(p) else 'MISSING':>7}] {label:<24} {p}")
    print()

    if not os.path.exists(CORRECTED_MATRIX):
        sys.exit("ERROR: run 15_selection_ratio_correction.py first.")

    data = pd.read_csv(CORRECTED_MATRIX)

    # Guard (not a second filter): what we inherited from script 15 must be
    # exactly the canonical 41 focal species. If script 15 was run with a stale
    # or edited roster, fail here rather than silently scoring a different set.
    inherited = [str(c).strip() for c in data["species_code"]]
    canonical = focal_species.load_codes()
    if set(inherited) != set(canonical):
        only_here = sorted(set(inherited) - set(canonical))
        only_canon = sorted(set(canonical) - set(inherited))
        sys.exit(
            "ERROR: the inherited roster does not match code/focal_species.json.\n"
            f"  inherited {len(inherited)} species from {os.path.basename(CORRECTED_MATRIX)}\n"
            f"  canonical {len(canonical)} species in code/focal_species.json\n"
            f"  only in inherited: {only_here}\n"
            f"  only in canonical: {only_canon}\n"
            "Re-run 15_selection_ratio_correction.py to regenerate the matrix."
        )

    book = load_book()

    rows = []
    for _, r in data.iterrows():
        code = str(r["species_code"]).strip()
        d_set = {c for c in CATEGORIES if bool(r[c])}
        b_set = book.get(code, None)
        has_book = b_set is not None

        rec: dict = {
            "species_code": code,
            "species": r.get("common_name", code),
            "red_list_name": r.get("red_list_name", ""),
        }
        for c in CATEGORIES:
            rec[f"data_{c}"] = bool(c in d_set)
        for c in CATEGORIES:
            # "" (not False) when there is no Handbook entry to report.
            rec[f"book_{c}"] = (bool(c in b_set) if has_book else "")

        if has_book:
            tp = len(d_set & b_set)
            fp = len(d_set - b_set)
            fn = len(b_set - d_set)
            tn = N_CLASSES - tp - fp - fn
            prec = safe_div(tp, tp + fp)
            rec_ = safe_div(tp, tp + fn)
            acc = (tp + tn) / N_CLASSES
            rec.update({
                "has_book": True, "TP": tp, "FP": fp, "FN": fn, "TN": tn,
                "precision": prec, "recall": rec_, "accuracy": acc,
            })
        else:
            rec.update({
                "has_book": False, "TP": "", "FP": "", "FN": "", "TN": "",
                "precision": None, "recall": None, "accuracy": None,
            })
        rows.append(rec)

    df = pd.DataFrame(rows)

    # --- CSV ---------------------------------------------------------------
    cols = (["species_code", "species", "red_list_name"]
            + [f"data_{c}" for c in CATEGORIES]
            + [f"book_{c}" for c in CATEGORIES]
            + ["has_book", "TP", "FP", "FN", "TN", "precision", "recall", "accuracy"])
    out = df[cols].copy()
    for c in ("precision", "recall", "accuracy"):
        out[c] = out[c].map(lambda v: "N/A" if v is None or pd.isna(v) else f"{v:.4f}")
    os.makedirs(SEL_DIR, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)

    scored = df[df["has_book"]]
    n_scored, n_total = len(scored), len(df)
    unscored = df[~df["has_book"]]

    # --- aggregates --------------------------------------------------------
    # Macro: mean of per-species scores, skipping undefined ones.
    p_vals = [v for v in scored["precision"] if v is not None]
    r_vals = [v for v in scored["recall"] if v is not None]
    a_vals = [v for v in scored["accuracy"] if v is not None]
    macro_p = float(np.mean(p_vals)) if p_vals else float("nan")
    macro_r = float(np.mean(r_vals)) if r_vals else float("nan")
    macro_a = float(np.mean(a_vals)) if a_vals else float("nan")

    # Micro: pool the cell counts, so every habitat call weighs the same.
    TP = int(scored["TP"].sum()); FP = int(scored["FP"].sum())
    FN = int(scored["FN"].sum()); TN = int(scored["TN"].sum())
    micro_p = safe_div(TP, TP + FP)
    micro_r = safe_div(TP, TP + FN)
    micro_a = (TP + TN) / (n_scored * N_CLASSES) if n_scored else float("nan")
    micro_f1 = (2 * micro_p * micro_r / (micro_p + micro_r)
                if micro_p and micro_r and (micro_p + micro_r) > 0 else None)

    # Per-class breakdown: where does Data over- or under-call?
    per_class = []
    for c in CATEGORIES:
        d = scored[f"data_{c}"].astype(bool).to_numpy()
        b = scored[f"book_{c}"].astype(bool).to_numpy()
        tp = int((d & b).sum()); fp = int((d & ~b).sum())
        fn = int((~d & b).sum()); tn = int((~d & ~b).sum())
        per_class.append({
            "class": LABELS[c], "TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "precision": safe_div(tp, tp + fp),
            "recall": safe_div(tp, tp + fn),
            "accuracy": (tp + tn) / n_scored if n_scored else None,
        })

    # --- figure ------------------------------------------------------------
    plot_matrix(df, OUT_PNG)

    # --- stdout ------------------------------------------------------------
    print(f"Species: {n_total} total, {n_scored} with a Book entry, "
          f"{len(unscored)} without (scored N/A).")
    if len(unscored):
        print("  No Book entry: "
              + ", ".join(str(s) for s in unscored["species"].tolist()))

    print("\n" + "=" * 78)
    print("SCORED AGAINST THE BOOK (ground truth)")
    print("=" * 78)
    print(f"\nMacro (mean of per-species scores, n={n_scored}):")
    print(f"  Precision {macro_p:.3f}   Recall {macro_r:.3f}   Accuracy {macro_a:.3f}")
    print(f"\nMicro (pooled over {n_scored * N_CLASSES} habitat calls):")
    print(f"  Precision {fmt_score(micro_p)}   Recall {fmt_score(micro_r)}   "
          f"Accuracy {micro_a:.3f}" + (f"   F1 {micro_f1:.3f}" if micro_f1 else ""))
    print(f"  TP {TP}   FP {FP}   FN {FN}   TN {TN}")

    print("\nPer class (Data vs Book):")
    print(f"  {'Class':<24} {'TP':>3} {'FP':>3} {'FN':>3} {'TN':>3} "
          f"{'Prec':>6} {'Rec':>6} {'Acc':>6}")
    for pc in per_class:
        print(f"  {pc['class']:<24} {pc['TP']:>3} {pc['FP']:>3} {pc['FN']:>3} "
              f"{pc['TN']:>3} {fmt_score(pc['precision']):>6} "
              f"{fmt_score(pc['recall']):>6} {fmt_score(pc['accuracy']):>6}")

    best = scored.nlargest(5, "accuracy")[["species", "precision", "recall", "accuracy"]]
    worst = scored.nsmallest(5, "accuracy")[["species", "precision", "recall", "accuracy"]]
    print("\nBest agreement:")
    for _, r in best.iterrows():
        print(f"  {str(r['species'])[:28]:<28} P {fmt_score(r['precision']):>5} "
              f"R {fmt_score(r['recall']):>5} Acc {r['accuracy']:.3f}")
    print("\nWorst agreement:")
    for _, r in worst.iterrows():
        print(f"  {str(r['species'])[:28]:<28} P {fmt_score(r['precision']):>5} "
              f"R {fmt_score(r['recall']):>5} Acc {r['accuracy']:.3f}")

    write_summary(df, scored, unscored, per_class,
                  (macro_p, macro_r, macro_a),
                  (micro_p, micro_r, micro_a, micro_f1),
                  (TP, FP, FN, TN), n_scored, n_total)

    print(f"\nWrote:\n  {OUT_CSV}\n  {OUT_PNG}\n  {OUT_MD}")
    print("\n" + "=" * 78)
    print("HEADLINE")
    print("=" * 78)
    print(f"  Data vs Book, {n_scored}/{n_total} species scored "
          f"({len(unscored)} have no Handbook entry -> N/A)")
    print(f"  Macro: P {macro_p:.3f}  R {macro_r:.3f}  Acc {macro_a:.3f}")
    print(f"  Micro: P {fmt_score(micro_p)}  R {fmt_score(micro_r)}  Acc {micro_a:.3f}")
    print("=" * 78)


def plot_matrix(df: pd.DataFrame, out_path: str) -> None:
    """Data block beside Book block, shared species rows.

    Cells are coloured by agreement so the eye lands on the disagreements:
    both / data-only (false positive) / book-only (false negative) / neither.
    """
    n = len(df)
    labels = [str(s) for s in df["species"]]

    # Codes: 0 neither, 1 both, 2 data-only, 3 book-only, 4 no Book entry.
    grid = np.zeros((n, N_CLASSES * 2), dtype=int)
    for i in range(n):
        has_book = bool(df.iloc[i]["has_book"])
        for j, c in enumerate(CATEGORIES):
            d = bool(df.iloc[i][f"data_{c}"])
            if not has_book:
                grid[i, j] = 1 if d else 0          # Data half still real
                grid[i, N_CLASSES + j] = 4          # Book half unknown
                continue
            b = bool(df.iloc[i][f"book_{c}"])
            code = 1 if (d and b) else (2 if d else (3 if b else 0))
            grid[i, j] = code if d else 0
            grid[i, N_CLASSES + j] = code if b else 0

    cmap = ListedColormap(["#f4f4f4",   # 0 neither
                           "#1f7a4d",   # 1 both agree
                           "#d98032",   # 2 data only (FP)
                           "#7b52c4",   # 3 book only (FN)
                           "#d8d8d8"])  # 4 no Book entry
    norm_ = BoundaryNorm([-.5, .5, 1.5, 2.5, 3.5, 4.5], cmap.N)

    fig, ax = plt.subplots(figsize=(15, max(9.0, 0.30 * n)))
    ax.imshow(grid, cmap=cmap, norm=norm_, aspect="auto", interpolation="nearest")

    xt = [LABELS[c] for c in CATEGORIES] * 2
    ax.set_xticks(range(N_CLASSES * 2))
    ax.set_xticklabels(xt, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(n))
    ax.set_yticklabels(labels, fontsize=7)

    ax.set_xticks(np.arange(-0.5, N_CLASSES * 2, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, n, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=0.7)
    ax.tick_params(which="minor", length=0)

    # Hard divider between the two blocks.
    ax.axvline(N_CLASSES - 0.5, color="black", linewidth=2.5)
    ax.text(N_CLASSES / 2 - 0.5, -1.4, "DATA  (selection-corrected, SR ≥ 1)",
            ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.text(N_CLASSES * 1.5 - 0.5, -1.4, "BOOK  (RSPB Handbook)",
            ha="center", va="bottom", fontsize=11, fontweight="bold")

    ax.legend(handles=[
        Patch(facecolor="#1f7a4d", label="Both agree (TP)"),
        Patch(facecolor="#d98032", label="Data only (FP)"),
        Patch(facecolor="#7b52c4", label="Book only (FN)"),
        Patch(facecolor="#f4f4f4", edgecolor="#cccccc", label="Neither (TN)"),
        Patch(facecolor="#d8d8d8", label="No Book entry (N/A)"),
    ], loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=False, fontsize=9)

    ax.set_title("Availability-corrected DATA vs RSPB Handbook BOOK verdicts\n"
                 "Redlist species × aggregate-9 classes",
                 fontsize=12, pad=34)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def write_summary(df, scored, unscored, per_class, macro, micro, cells,
                  n_scored, n_total) -> None:
    macro_p, macro_r, macro_a = macro
    micro_p, micro_r, micro_a, micro_f1 = micro
    TP, FP, FN, TN = cells

    L = []
    L.append("# Data vs Book: availability-corrected verdicts against the RSPB Handbook\n")
    L.append("Side-by-side matrix of the availability-corrected **Data** verdicts "
             "(selection ratio ≥ 1) and the **Book** verdicts hand-entered from the "
             "RSPB Handbook, over the redlist species × the 9 aggregate-9 classes.\n")

    L.append("## How it is scored\n")
    L.append("The Book is treated as **ground truth**; the Data verdict is the "
             "prediction being tested.\n")
    L.append("| | Book: yes | Book: no |")
    L.append("|---|---|---|")
    L.append("| **Data: yes** | TP | FP |")
    L.append("| **Data: no** | FN | TN |\n")
    L.append("```")
    L.append("Precision = TP / (TP + FP)    of the habitats Data flagged, how many the Book confirms")
    L.append("Recall    = TP / (TP + FN)    of the habitats the Book lists, how many Data found")
    L.append("Accuracy  = (TP + TN) / 9     correct cells across all nine classes")
    L.append("```\n")
    L.append("Precision is undefined (N/A) when Data flags nothing, recall when the "
             "Book lists nothing — reported as N/A rather than 0, which would be a "
             "different claim.\n")

    L.append("### Species without a Handbook entry\n")
    L.append(f"{len(unscored)} of {n_total} species have no Book entry. They are kept "
             "as rows — their Data verdicts are real — but the Book half is blank and "
             "every score is **N/A**. They are excluded from all aggregates.\n")
    L.append("A missing entry is *not* the Handbook saying \"none of these habitats\". "
             "Treating blank as all-False would invent 9 true negatives per species and "
             "inflate accuracy by roughly the share of unscored rows.\n")
    if len(unscored):
        L.append("Unscored: " + ", ".join(f"{r['species']}" for _, r in unscored.iterrows()) + "\n")

    L.append("## Headline\n")
    L.append(f"Scored on **{n_scored}** species ({n_scored * N_CLASSES} habitat calls).\n")
    L.append("| Averaging | Precision | Recall | Accuracy |")
    L.append("|---|---:|---:|---:|")
    L.append(f"| **Macro** (mean of per-species scores) | {macro_p:.3f} | {macro_r:.3f} | {macro_a:.3f} |")
    L.append(f"| **Micro** (pooled habitat calls) | {fmt_score(micro_p)} | "
             f"{fmt_score(micro_r)} | {micro_a:.3f} |")
    L.append("")
    L.append(f"Pooled cells: **TP {TP}, FP {FP}, FN {FN}, TN {TN}**"
             + (f" (micro F1 {micro_f1:.3f})" if micro_f1 else "") + "\n")
    L.append("Macro weights every species equally; micro weights every habitat call "
             "equally. They diverge when species differ in how many habitats they use, "
             "so both are reported.\n")

    L.append("## Per class\n")
    L.append("| Class | TP | FP | FN | TN | Precision | Recall | Accuracy |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for pc in per_class:
        L.append(f"| {pc['class']} | {pc['TP']} | {pc['FP']} | {pc['FN']} | {pc['TN']} | "
                 f"{fmt_score(pc['precision'])} | {fmt_score(pc['recall'])} | "
                 f"{fmt_score(pc['accuracy'])} |")
    L.append("")
    L.append("High FP means Data over-calls that habitat; high FN means Data misses it.\n")

    L.append("## Per species\n")
    L.append("| Species | Data habitats | Book habitats | TP | FP | FN | Precision | Recall | Accuracy |")
    L.append("|---|---|---|---:|---:|---:|---:|---:|---:|")
    for _, r in df.iterrows():
        d = "; ".join(LABELS[c] for c in CATEGORIES if bool(r[f"data_{c}"])) or "—"
        if r["has_book"]:
            b = "; ".join(LABELS[c] for c in CATEGORIES if bool(r[f"book_{c}"])) or "—"
            L.append(f"| {r['species']} | {d} | {b} | {r['TP']} | {r['FP']} | {r['FN']} | "
                     f"{fmt_score(r['precision'])} | {fmt_score(r['recall'])} | "
                     f"{fmt_score(r['accuracy'])} |")
        else:
            L.append(f"| {r['species']} | {d} | *(no entry)* | — | — | — | N/A | N/A | N/A |")
    L.append("")

    L.append("## Files\n")
    L.append(f"- `{os.path.basename(OUT_CSV)}` — wide matrix: "
             "`data_*` block, `book_*` block, cell counts and scores")
    L.append(f"- `{os.path.basename(OUT_PNG)}` — side-by-side heatmap, coloured by "
             "agreement (both / data-only / book-only)\n")
    L.append("Generated by `code/landcover_analysis/16_data_vs_book_matrix.py`.")

    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))


if __name__ == "__main__":
    main()
