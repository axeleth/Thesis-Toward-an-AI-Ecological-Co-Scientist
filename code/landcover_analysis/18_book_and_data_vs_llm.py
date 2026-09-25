#!/usr/bin/env python3
"""18_book_and_data_vs_llm.py  --  Book and Data each scored against the LLM

Pivots the comparison. 17_llm_and_data_vs_book_scores.py treated the RSPB Handbook
as ground truth and scored the data and the LLM against it. Here the **LLM is the
reference**, and the Handbook and the data are each scored against it as two
independent comparisons:

    BOOK vs LLM   TP FP FN TN  P R F1 Acc
    DATA vs LLM   TP FP FN TN  P R F1 Acc

which answers "which source does the LLM agree with more, and where do they part
company?" rather than "which source best reproduces the Handbook".

WHAT CHANGES WHEN THE REFERENCE MOVES
-------------------------------------
The four confusion cells are not symmetric under swapping which side is "truth":
TP and TN are unchanged, but FP and FN trade places. So precision and recall swap
roles and change meaning:

    reference = Book :  precision = "of what the source claims, how much the Book confirms"
    reference = LLM  :  precision = "of what the source claims, how much the LLM confirms"
                        recall    = "of what the LLM claims, how much the source recovers"

F1 is unchanged by the swap (it is symmetric in P and R), and accuracy is
unchanged (TP + TN is invariant). This is worth stating plainly, because an F1
that does not move when the reference changes can look like a bug and is not.

    TP  both say yes                  FP  source says yes, LLM says no
    FN  source says no, LLM says yes  TN  both say no

    Precision = TP / (TP + FP)      Recall   = TP / (TP + FN)
    F1        = 2PR / (P + R)       Accuracy = (TP + TN) / 9

Precision is undefined when a source flags nothing, recall when the LLM flags
nothing; both are reported as N/A, never as 0.

THREE-SOURCE VERDICTS
---------------------
Also emits the per-species verdicts of all three sources side by side, with each
habitat call labelled by its agreement pattern:

    all3        Book, Data and LLM all say yes
    llm_data    LLM and Data agree, Book dissents
    llm_book    LLM and Book agree, Data dissents
    book_data   Book and Data agree, LLM dissents
    book_only / data_only / llm_only    exactly one source claims it
    none        no source claims it

Inputs:
    outputs/landcover_analysis/selection_corrected/aggregate9_presence_corrected.csv
    outputs/habitat_agents/blind_presence_matrix.csv
    alignment_adjusted.xlsx  (Book column)

Outputs:
    outputs/landcover_analysis/selection_corrected/vs_llm_per_species.csv
    outputs/landcover_analysis/selection_corrected/vs_llm_overall.csv
    outputs/landcover_analysis/selection_corrected/vs_llm_per_class.csv
    outputs/landcover_analysis/selection_corrected/three_source_verdicts.csv
    outputs/landcover_analysis/selection_corrected/three_source_agreement_summary.csv
    outputs/landcover_analysis/selection_corrected/VS_LLM_SUMMARY.md

Usage:
    python code/landcover_analysis/18_book_and_data_vs_llm.py
"""

from __future__ import annotations

import os
import re
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "habitat_agents"))
import _agent_common as ac  # noqa: E402

CODE_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
_m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", CODE_ROOT)
DATA_ROOT = _m.group(1) if _m else CODE_ROOT

SEL_DIR = os.path.join(DATA_ROOT, "outputs", "landcover_analysis", "selection_corrected")
DATA_CSV = os.path.join(SEL_DIR, "aggregate9_presence_corrected.csv")
LLM_CSV = os.path.join(DATA_ROOT, "outputs", "habitat_agents",
                       "blind_presence_matrix.csv")
ALIGNMENT_XLSX = os.path.join(DATA_ROOT, "alignment_adjusted.xlsx")

OUT_PER_SPECIES = os.path.join(SEL_DIR, "vs_llm_per_species.csv")
OUT_OVERALL = os.path.join(SEL_DIR, "vs_llm_overall.csv")
OUT_PER_CLASS = os.path.join(SEL_DIR, "vs_llm_per_class.csv")
OUT_VERDICTS = os.path.join(SEL_DIR, "three_source_verdicts.csv")
OUT_AGREE = os.path.join(SEL_DIR, "three_source_agreement_summary.csv")
OUT_MD = os.path.join(SEL_DIR, "VS_LLM_SUMMARY.md")

CATEGORIES = ac.CATEGORIES
LABELS = ac.CATEGORY_LABELS
N_CLASSES = len(CATEGORIES)

PATTERNS = ["all3", "llm_data", "llm_book", "book_data",
            "book_only", "data_only", "llm_only", "none"]
PATTERN_LABEL = {
    "all3": "All three agree (yes)",
    "llm_data": "LLM + Data (Book dissents)",
    "llm_book": "LLM + Book (Data dissents)",
    "book_data": "Book + Data (LLM dissents)",
    "book_only": "Book only",
    "data_only": "Data only",
    "llm_only": "LLM only",
    "none": "No source (all say no)",
}


def norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", str(s).lower())


CANON = {norm(LABELS[s]): s for s in CATEGORIES}
CANON.update({norm(s): s for s in CATEGORIES})


def load_book() -> dict:
    from openpyxl import load_workbook

    wb = load_workbook(ALIGNMENT_XLSX, data_only=True)
    ws = wb["alignment"]
    header = {str(c.value).strip(): c.column for c in ws[1] if c.value is not None}
    bc, cc = header.get("Book"), header.get("species_code")
    if not bc or not cc:
        sys.exit(f"ERROR: need 'Book' and 'species_code'; found {sorted(header)}")
    out = {}
    for r in range(2, ws.max_row + 1):
        code = ws.cell(row=r, column=cc).value
        if not code:
            continue
        cell = ws.cell(row=r, column=bc).value
        if cell is None or str(cell).strip() == "":
            out[str(code).strip()] = None
            continue
        slugs = set()
        for part in str(cell).split(";"):
            k = norm(part)
            if k in CANON:
                slugs.add(CANON[k])
            elif k:
                for cand, slug in CANON.items():
                    if cand and cand in k:
                        slugs.add(slug)
                        break
                else:
                    print(f"  WARNING: unrecognised Book fragment {part.strip()!r}")
        out[str(code).strip()] = slugs
    return out


def load_pred(path: str, label: str) -> dict:
    df = pd.read_csv(path)
    df["species_code"] = df["species_code"].astype(str).str.strip()
    missing = [c for c in CATEGORIES if c not in df.columns]
    if missing:
        sys.exit(f"ERROR: {label} missing columns: {', '.join(missing)}")
    return {r["species_code"]: {c for c in CATEGORIES if bool(r[c])}
            for _, r in df.iterrows()}


def confusion(source: set, reference: set) -> tuple[int, int, int, int]:
    """TP/FP/FN/TN with `reference` (the LLM) as the truth side."""
    tp = len(source & reference)
    fp = len(source - reference)
    fn = len(reference - source)
    tn = N_CLASSES - tp - fp - fn
    return tp, fp, fn, tn


def scores(tp: int, fp: int, fn: int, tn: int):
    p = tp / (tp + fp) if (tp + fp) else None
    r = tp / (tp + fn) if (tp + fn) else None
    if p is None or r is None or (p + r) == 0:
        f = 0.0 if (p is not None or r is not None) else None
    else:
        f = 2 * p * r / (p + r)
    return p, r, f, (tp + tn) / N_CLASSES


def jaccard(a: set, b: set) -> float:
    u = a | b
    return 1.0 if not u else len(a & b) / len(u)


def kappa(tp: int, fp: int, fn: int, tn: int) -> float | None:
    """Cohen's kappa for two binary raters over the 9 classes."""
    n = tp + fp + fn + tn
    if n == 0:
        return None
    po = (tp + tn) / n
    p_yes = ((tp + fp) / n) * ((tp + fn) / n)
    p_no = ((fn + tn) / n) * ((fp + tn) / n)
    pe = p_yes + p_no
    return None if pe >= 1.0 else (po - pe) / (1 - pe)


def fmt(v) -> str:
    return "N/A" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.3f}"


def pattern_of(b: bool, d: bool, l: bool) -> str:
    if b and d and l:
        return "all3"
    if l and d and not b:
        return "llm_data"
    if l and b and not d:
        return "llm_book"
    if b and d and not l:
        return "book_data"
    if b and not d and not l:
        return "book_only"
    if d and not b and not l:
        return "data_only"
    if l and not b and not d:
        return "llm_only"
    return "none"


def main() -> None:
    print("=" * 78)
    print("18_book_and_data_vs_llm.py -- Book and Data scored against the LLM")
    print("=" * 78)
    print("\nResolved inputs:")
    for lbl, p in [("DATA (SR >= 1)", DATA_CSV), ("LLM (reference)", LLM_CSV),
                   ("Book", ALIGNMENT_XLSX)]:
        print(f"  [{'OK' if os.path.exists(p) else 'MISSING':>7}] {lbl:<18} {p}")
    for p in (DATA_CSV, LLM_CSV, ALIGNMENT_XLSX):
        if not os.path.exists(p):
            sys.exit(f"\nERROR: missing {p}")
    print()

    data_sets = load_pred(DATA_CSV, "DATA")
    llm_sets = load_pred(LLM_CSV, "LLM")
    book = load_book()

    roster = pd.read_csv(DATA_CSV)
    roster["species_code"] = roster["species_code"].astype(str).str.strip()

    rows, no_book, no_llm = [], [], []
    for _, r in roster.iterrows():
        code = r["species_code"]
        name = r.get("common_name", code)
        b = book.get(code)
        if b is None:
            no_book.append(name)
            continue
        if code not in llm_sets:
            no_llm.append(name)
        d = data_sets.get(code, set())
        l = llm_sets.get(code, set())

        btp, bfp, bfn, btn = confusion(b, l)      # Book scored against LLM
        dtp, dfp, dfn, dtn = confusion(d, l)      # Data scored against LLM
        bp, br, bf1, bacc = scores(btp, bfp, bfn, btn)
        dp, dr, df1, dacc = scores(dtp, dfp, dfn, dtn)

        rows.append({
            "species_code": code, "species": name,
            "llm_habitats": "; ".join(LABELS[c] for c in CATEGORIES if c in l),
            "book_habitats": "; ".join(LABELS[c] for c in CATEGORIES if c in b),
            "data_habitats": "; ".join(LABELS[c] for c in CATEGORIES if c in d),
            "book_TP": btp, "book_FP": bfp, "book_FN": bfn, "book_TN": btn,
            "book_precision": bp, "book_recall": br, "book_f1": bf1,
            "book_accuracy": bacc, "book_jaccard": jaccard(b, l),
            "book_kappa": kappa(btp, bfp, bfn, btn),
            "data_TP": dtp, "data_FP": dfp, "data_FN": dfn, "data_TN": dtn,
            "data_precision": dp, "data_recall": dr, "data_f1": df1,
            "data_accuracy": dacc, "data_jaccard": jaccard(d, l),
            "data_kappa": kappa(dtp, dfp, dfn, dtn),
        })

    df = pd.DataFrame(rows)
    n = len(df)
    if no_book:
        print(f"NOTE: {len(no_book)} species excluded (no Book entry): {', '.join(no_book)}")
    if no_llm:
        print(f"NOTE: {len(no_llm)} species absent from the LLM matrix: {', '.join(no_llm)}")
    print(f"Scored {n} species x {N_CLASSES} classes = {n * N_CLASSES} habitat calls.")
    print("Reference = LLM (blind agent). Book and Data are each scored against it.\n")

    out = df.copy()
    for c in [c for c in out.columns
              if c.endswith(("precision", "recall", "f1", "accuracy", "jaccard", "kappa"))]:
        out[c] = out[c].map(lambda v: "N/A" if v is None or pd.isna(v) else f"{v:.4f}")
    out.to_csv(OUT_PER_SPECIES, index=False)

    # --- overall -----------------------------------------------------------
    overall = []
    for tag, label in (("book", "BOOK vs LLM"), ("data", "DATA vs LLM")):
        TP = int(df[f"{tag}_TP"].sum()); FP = int(df[f"{tag}_FP"].sum())
        FN = int(df[f"{tag}_FN"].sum()); TN = int(df[f"{tag}_TN"].sum())
        mip, mir, mif, _ = scores(TP, FP, FN, TN)

        def mac(col):
            v = [x for x in df[f"{tag}_{col}"] if x is not None and not pd.isna(x)]
            return float(np.mean(v)) if v else float("nan")

        overall.append({
            "comparison": label, "n_species": n, "n_calls": n * N_CLASSES,
            "TP": TP, "FP": FP, "FN": FN, "TN": TN,
            "macro_precision": mac("precision"), "macro_recall": mac("recall"),
            "macro_f1": mac("f1"), "macro_accuracy": mac("accuracy"),
            "micro_precision": mip, "micro_recall": mir, "micro_f1": mif,
            "micro_accuracy": (TP + TN) / (n * N_CLASSES),
            "mean_jaccard": mac("jaccard"), "mean_kappa": mac("kappa"),
            "pooled_kappa": kappa(TP, FP, FN, TN),
        })
    ov = pd.DataFrame(overall)
    ov.to_csv(OUT_OVERALL, index=False)

    print("=" * 78)
    print("OVERALL -- reference is the LLM")
    print("=" * 78)
    print(f"\n  {'Comparison':<14} {'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4}   "
          f"{'macroP':>7} {'macroR':>7} {'macroF1':>7} {'macroAcc':>8}")
    for _, r in ov.iterrows():
        print(f"  {r['comparison']:<14} {r['TP']:>4} {r['FP']:>4} {r['FN']:>4} {r['TN']:>4}   "
              f"{r['macro_precision']:>7.3f} {r['macro_recall']:>7.3f} "
              f"{r['macro_f1']:>7.3f} {r['macro_accuracy']:>8.3f}")
    print(f"\n  {'Comparison':<14} {'':>4} {'':>4} {'':>4} {'':>4}   "
          f"{'microP':>7} {'microR':>7} {'microF1':>7} {'microAcc':>8}")
    for _, r in ov.iterrows():
        print(f"  {r['comparison']:<14} {'':>4} {'':>4} {'':>4} {'':>4}   "
              f"{r['micro_precision']:>7.3f} {r['micro_recall']:>7.3f} "
              f"{r['micro_f1']:>7.3f} {r['micro_accuracy']:>8.3f}")
    print(f"\n  {'Comparison':<14} {'meanJaccard':>12} {'meanKappa':>10} {'pooledKappa':>12}")
    for _, r in ov.iterrows():
        print(f"  {r['comparison']:<14} {r['mean_jaccard']:>12.3f} "
              f"{r['mean_kappa']:>10.3f} {r['pooled_kappa']:>12.3f}")

    b_f1, d_f1 = ov.iloc[0]["macro_f1"], ov.iloc[1]["macro_f1"]
    print(f"\n  The LLM agrees more with the "
          f"{'BOOK' if b_f1 > d_f1 else 'DATA'} "
          f"(macro F1 {max(b_f1, d_f1):.3f} vs {min(b_f1, d_f1):.3f}, "
          f"gap {abs(b_f1 - d_f1):.3f}).")

    # --- per class ---------------------------------------------------------
    B = np.array([[c in book[r["species_code"]] for c in CATEGORIES]
                  for _, r in df.iterrows()], dtype=bool)
    D = np.array([[c in data_sets.get(r["species_code"], set()) for c in CATEGORIES]
                  for _, r in df.iterrows()], dtype=bool)
    Lm = np.array([[c in llm_sets.get(r["species_code"], set()) for c in CATEGORIES]
                   for _, r in df.iterrows()], dtype=bool)

    pc_rows = []
    for j, c in enumerate(CATEGORIES):
        rec = {"class": LABELS[c], "n_llm_true": int(Lm[:, j].sum()),
               "n_book_true": int(B[:, j].sum()), "n_data_true": int(D[:, j].sum())}
        for tag, M in (("book", B), ("data", D)):
            tp = int((M[:, j] & Lm[:, j]).sum()); fp = int((M[:, j] & ~Lm[:, j]).sum())
            fn = int((~M[:, j] & Lm[:, j]).sum()); tn = int((~M[:, j] & ~Lm[:, j]).sum())
            p, r_, f, _ = scores(tp, fp, fn, tn)
            rec.update({f"{tag}_TP": tp, f"{tag}_FP": fp, f"{tag}_FN": fn,
                        f"{tag}_TN": tn, f"{tag}_precision": p, f"{tag}_recall": r_,
                        f"{tag}_f1": f, f"{tag}_accuracy": (tp + tn) / n})
        pc_rows.append(rec)
    pc = pd.DataFrame(pc_rows)
    pc.to_csv(OUT_PER_CLASS, index=False)

    print("\n" + "=" * 78)
    print("PER CLASS -- agreement with the LLM")
    print("=" * 78)
    print(f"\n  {'Class':<24} {'LLM':>4} | {'BOOK TP/FP/FN/TN':>17} {'F1':>6} | "
          f"{'DATA TP/FP/FN/TN':>17} {'F1':>6}")
    for _, r in pc.iterrows():
        bc = f"{r['book_TP']}/{r['book_FP']}/{r['book_FN']}/{r['book_TN']}"
        dc = f"{r['data_TP']}/{r['data_FP']}/{r['data_FN']}/{r['data_TN']}"
        print(f"  {r['class']:<24} {r['n_llm_true']:>4} | {bc:>17} "
              f"{fmt(r['book_f1']):>6} | {dc:>17} {fmt(r['data_f1']):>6}")

    # --- three-source verdicts --------------------------------------------
    vrows, counts = [], {p: 0 for p in PATTERNS}
    for i, (_, r) in enumerate(df.iterrows()):
        for j, c in enumerate(CATEGORIES):
            pat = pattern_of(bool(B[i, j]), bool(D[i, j]), bool(Lm[i, j]))
            counts[pat] += 1
            vrows.append({
                "species_code": r["species_code"], "species": r["species"],
                "class": LABELS[c], "class_slug": c,
                "book": bool(B[i, j]), "data": bool(D[i, j]), "llm": bool(Lm[i, j]),
                "pattern": pat, "pattern_label": PATTERN_LABEL[pat],
            })
    verdicts = pd.DataFrame(vrows)
    verdicts.to_csv(OUT_VERDICTS, index=False)

    total = n * N_CLASSES
    agree = pd.DataFrame([{"pattern": p, "label": PATTERN_LABEL[p],
                           "n_calls": counts[p], "pct": 100 * counts[p] / total}
                          for p in PATTERNS])
    agree.to_csv(OUT_AGREE, index=False)

    print("\n" + "=" * 78)
    print("THREE-SOURCE AGREEMENT")
    print("=" * 78)
    print(f"\n  {'Pattern':<32} {'calls':>6} {'pct':>7}")
    for _, r in agree.iterrows():
        print(f"  {r['label']:<32} {r['n_calls']:>6} {r['pct']:>6.1f}%")
    pos = total - counts["none"]
    print(f"\n  {pos} of {total} calls have at least one source claiming the habitat.")
    print(f"  All three agree on {counts['all3']} "
          f"({100 * counts['all3'] / pos:.1f}% of those).")
    print(f"  LLM sides with DATA against BOOK: {counts['llm_data']}")
    print(f"  LLM sides with BOOK against DATA: {counts['llm_book']}")
    print(f"  BOOK and DATA agree, LLM dissents: {counts['book_data']}")

    write_summary(df, ov, pc, agree, counts, n, total, no_book)

    print(f"\nWrote:\n  {OUT_PER_SPECIES}\n  {OUT_OVERALL}\n  {OUT_PER_CLASS}\n"
          f"  {OUT_VERDICTS}\n  {OUT_AGREE}\n  {OUT_MD}")


def write_summary(df, ov, pc, agree, counts, n, total, no_book):
    L = []
    L.append("# Book and Data, each scored against the LLM\n")
    L.append("The **LLM (blind habitat agent)** is the reference. The RSPB Handbook "
             "(**Book**) and the availability-corrected selection ratio (**Data**) are "
             "each scored against it as two independent comparisons, then compared to "
             "each other.\n")
    L.append("This answers *which source does the LLM agree with more, and where do "
             "they part company* — not *which source best reproduces the Handbook*.\n")

    L.append("## How the reference swap changes the numbers\n")
    L.append("The confusion cells are not symmetric under swapping the truth side: TP "
             "and TN are unchanged, but **FP and FN trade places**. So precision and "
             "recall swap roles and meaning:\n")
    L.append("```")
    L.append("TP  both say yes                  FP  source says yes, LLM says no")
    L.append("FN  source says no, LLM says yes  TN  both say no")
    L.append("")
    L.append("Precision = TP / (TP + FP)   of what the source claims, how much the LLM confirms")
    L.append("Recall    = TP / (TP + FN)   of what the LLM claims, how much the source recovers")
    L.append("```\n")
    L.append("**F1 and accuracy are unchanged by the swap** — F1 is symmetric in P and "
             "R, and TP + TN is invariant. An F1 that does not move when the reference "
             "changes is correct, not a bug.\n")
    if no_book:
        L.append(f"Excluded for having no Book entry: {', '.join(no_book)}.\n")
    else:
        L.append(f"All {n} focal species carry a Book entry; none excluded.\n")

    L.append("## Overall\n")
    L.append("| Comparison | Avg | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in ov.iterrows():
        L.append(f"| **{r['comparison']}** | macro | {r['TP']} | {r['FP']} | {r['FN']} | "
                 f"{r['TN']} | {r['macro_precision']:.3f} | {r['macro_recall']:.3f} | "
                 f"{r['macro_f1']:.3f} | {r['macro_accuracy']:.3f} |")
        L.append(f"| {r['comparison']} | micro | {r['TP']} | {r['FP']} | {r['FN']} | "
                 f"{r['TN']} | {r['micro_precision']:.3f} | {r['micro_recall']:.3f} | "
                 f"{r['micro_f1']:.3f} | {r['micro_accuracy']:.3f} |")
    L.append("")
    L.append("Chance-corrected agreement, which does not designate a truth side:\n")
    L.append("| Comparison | Mean Jaccard | Mean κ | Pooled κ |")
    L.append("|---|---:|---:|---:|")
    for _, r in ov.iterrows():
        L.append(f"| {r['comparison']} | {r['mean_jaccard']:.3f} | "
                 f"{r['mean_kappa']:.3f} | {r['pooled_kappa']:.3f} |")
    L.append("")
    b, d = ov.iloc[0], ov.iloc[1]
    winner = "Book" if b["macro_f1"] > d["macro_f1"] else "Data"
    L.append(f"**The LLM agrees more with the {winner}** — macro F1 "
             f"{max(b['macro_f1'], d['macro_f1']):.3f} against "
             f"{min(b['macro_f1'], d['macro_f1']):.3f}, a gap of "
             f"{abs(b['macro_f1'] - d['macro_f1']):.3f}.\n")

    L.append("## Per class\n")
    L.append("| Class | LLM-true | BOOK TP/FP/FN/TN | BOOK P | BOOK R | BOOK F1 | "
             "DATA TP/FP/FN/TN | DATA P | DATA R | DATA F1 |")
    L.append("|---|---:|:--:|---:|---:|---:|:--:|---:|---:|---:|")
    for _, r in pc.iterrows():
        L.append(f"| {r['class']} | {r['n_llm_true']} | "
                 f"{r['book_TP']}/{r['book_FP']}/{r['book_FN']}/{r['book_TN']} | "
                 f"{fmt(r['book_precision'])} | {fmt(r['book_recall'])} | "
                 f"{fmt(r['book_f1'])} | "
                 f"{r['data_TP']}/{r['data_FP']}/{r['data_FN']}/{r['data_TN']} | "
                 f"{fmt(r['data_precision'])} | {fmt(r['data_recall'])} | "
                 f"{fmt(r['data_f1'])} |")
    L.append("")

    L.append("## Three-source agreement\n")
    L.append(f"Every one of the {total} habitat calls, classified by which sources "
             "claim it:\n")
    L.append("| Pattern | Calls | % of all |")
    L.append("|---|---:|---:|")
    for _, r in agree.iterrows():
        L.append(f"| {r['label']} | {r['n_calls']} | {r['pct']:.1f}% |")
    L.append("")
    pos = total - counts["none"]
    L.append(f"{pos} calls have at least one source claiming the habitat; all three "
             f"agree on {counts['all3']} of them ({100 * counts['all3'] / pos:.1f}%).\n")
    L.append(f"- LLM sides with **Data** against the Book: **{counts['llm_data']}**")
    L.append(f"- LLM sides with **Book** against the Data: **{counts['llm_book']}**")
    L.append(f"- Book and Data agree, **LLM dissents**: **{counts['book_data']}**\n")

    L.append("## Per species\n")
    L.append("| Species | LLM habitats | BOOK TP/FP/FN/TN | BOOK F1 | DATA TP/FP/FN/TN | DATA F1 |")
    L.append("|---|---|:--:|---:|:--:|---:|")
    for _, r in df.iterrows():
        L.append(f"| {r['species']} | {r['llm_habitats'] or '—'} | "
                 f"{r['book_TP']}/{r['book_FP']}/{r['book_FN']}/{r['book_TN']} | "
                 f"{fmt(r['book_f1'])} | "
                 f"{r['data_TP']}/{r['data_FP']}/{r['data_FN']}/{r['data_TN']} | "
                 f"{fmt(r['data_f1'])} |")
    L.append("")
    L.append("Generated by `code/landcover_analysis/18_book_and_data_vs_llm.py`.")

    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))


if __name__ == "__main__":
    main()
