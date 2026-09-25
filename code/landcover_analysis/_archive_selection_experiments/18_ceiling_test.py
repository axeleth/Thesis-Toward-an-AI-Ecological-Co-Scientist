#!/usr/bin/env python3
"""18_ceiling_test.py  --  is the ~0.5 ceiling in the DATA or in the GROUND TRUTH?

The availability-corrected data scores macro F1 ~0.50 against the RSPB Handbook,
and 17_sr_threshold_sweep.py showed that no threshold tuning beats that -- a
data-free rule that always names the five commonest habitats scores 0.498, a
statistical tie. So the ceiling is not a tuning failure. This script asks which
of two very different things it is:

  (a) THE DATA is the bottleneck -- the eBird/UKCEH signal genuinely fails to
      recover published habitat associations. Fixing the availability denominator
      (occupied-range rather than UK-wide) should then raise the score.

  (b) THE GROUND TRUTH is the bottleneck -- the Handbook's qualitative prose does
      not project cleanly onto a 9-class partition of UK land cover, so ~0.5 is
      roughly the best ANY source can score. No denominator fix would move it.

THE TEST. Score the BLIND LLM AGENT against the same Book, with the same metric,
on the same species. The agent has read the literature and never saw the data, so
it is a proxy for "an informed source doing its best". If the agent also ceilings
near 0.5, the limit is the Book-to-9-class mapping (b). If it scores far higher,
the headroom is real and belongs to the data (a).

The agent is not a perfect ceiling -- it is one model's knowledge, it can be
wrong, and it may share vocabulary conventions with the hand-entered Book that
the data cannot. It bounds the mapping loosely, not exactly. Read it as evidence,
not proof.

ALSO REPORTED
  - Agent vs Data agreement (do two independent sources converge?)
  - The 15 species that got WORSE under the availability correction: do they share
    a trait (marine, range-restricted) that would predict the occupied-range fix?
  - An oracle bound: the best achievable F1 if you could pick the ideal number of
    habitats per species from the SR ranking -- the headroom top-K leaves on the
    table.

Inputs:
    outputs/landcover_analysis/selection_corrected/aggregate9_selection_ratio.csv
    outputs/landcover_analysis/selection_corrected/aggregate9_presence_corrected.csv
    outputs/landcover_analysis/redlist_aggregate9_1km_weighted/
        redlist_aggregate9_1km_weighted_presence_matrix.csv   (naive, for the regression check)
    outputs/habitat_agents/blind_presence_matrix.csv
    alignment_adjusted.xlsx  (Book column)

Outputs (new files only):
    outputs/landcover_analysis/selection_corrected/ceiling_test.csv
    outputs/landcover_analysis/selection_corrected/ceiling_test.png
    outputs/landcover_analysis/selection_corrected/CEILING_TEST_SUMMARY.md
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "habitat_agents"))
import _agent_common as ac  # noqa: E402

CODE_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
_m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", CODE_ROOT)
DATA_ROOT = _m.group(1) if _m else CODE_ROOT

SEL_DIR = os.path.join(DATA_ROOT, "outputs", "landcover_analysis", "selection_corrected")
SR_CSV = os.path.join(SEL_DIR, "aggregate9_selection_ratio.csv")
CORRECTED_CSV = os.path.join(SEL_DIR, "aggregate9_presence_corrected.csv")
NAIVE_CSV = os.path.join(
    DATA_ROOT, "outputs", "landcover_analysis", "redlist_aggregate9_1km_weighted",
    "redlist_aggregate9_1km_weighted_presence_matrix.csv")
AGENT_CSV = os.path.join(DATA_ROOT, "outputs", "habitat_agents",
                         "blind_presence_matrix.csv")
ALIGNMENT_XLSX = os.path.join(DATA_ROOT, "alignment_adjusted.xlsx")

OUT_CSV = os.path.join(SEL_DIR, "ceiling_test.csv")
OUT_PNG = os.path.join(SEL_DIR, "ceiling_test.png")
OUT_MD = os.path.join(SEL_DIR, "CEILING_TEST_SUMMARY.md")

CATEGORIES = ac.CATEGORIES
LABELS = ac.CATEGORY_LABELS
N_CLASSES = len(CATEGORIES)

# Marine / coastal-obligate classes: used to test whether the species that got
# worse under the correction are the ones a UK-wide denominator would distort.
MARINE = {"saltwater", "coastal"}


def norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", str(s).lower())


CANON = {norm(LABELS[s]): s for s in CATEGORIES}
CANON.update({norm(s): s for s in CATEGORIES})


def load_book() -> dict[str, set[str] | None]:
    from openpyxl import load_workbook

    wb = load_workbook(ALIGNMENT_XLSX, data_only=True)
    ws = wb["alignment"]
    header = {str(c.value).strip(): c.column for c in ws[1] if c.value is not None}
    bc, cc = header.get("Book"), header.get("species_code")
    out: dict[str, set[str] | None] = {}
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
        out[str(code).strip()] = slugs
    return out


def bool_matrix(path: str, codes: list[str]) -> np.ndarray | None:
    """Presence matrix as bool rows aligned to `codes`; None if a code is absent."""
    df = pd.read_csv(path)
    df["species_code"] = df["species_code"].astype(str).str.strip()
    idx = df.set_index("species_code")
    missing = [c for c in codes if c not in idx.index]
    if missing:
        print(f"  WARNING: {os.path.basename(path)} missing {len(missing)} species: "
              f"{', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}")
    rows = []
    for c in codes:
        if c in idx.index:
            r = idx.loc[c]
            rows.append([bool(r[cat]) for cat in CATEGORIES])
        else:
            rows.append([False] * N_CLASSES)
    return np.array(rows, dtype=bool)


def prf_rows(pred: np.ndarray, truth: np.ndarray):
    """Per-species (precision, recall, f1, accuracy); None where undefined."""
    out = []
    for i in range(pred.shape[0]):
        d, b = pred[i], truth[i]
        tp = int((d & b).sum()); fp = int((d & ~b).sum())
        fn = int((~d & b).sum()); tn = int((~d & ~b).sum())
        p = tp / (tp + fp) if (tp + fp) else None
        r = tp / (tp + fn) if (tp + fn) else None
        if p is None and r is None:
            f = None
        else:
            pp, rr = (p or 0.0), (r or 0.0)
            f = 2 * pp * rr / (pp + rr) if (pp + rr) > 0 else 0.0
        out.append((p, r, f, (tp + tn) / N_CLASSES, tp, fp, fn, tn))
    return out


def macro(rows, i):
    vals = [r[i] for r in rows if r[i] is not None]
    return float(np.mean(vals)) if vals else float("nan")


def micro(pred, truth):
    tp = int((pred & truth).sum()); fp = int((pred & ~truth).sum())
    fn = int((~pred & truth).sum())
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return p, r, f


def jaccard_rows(a: np.ndarray, b: np.ndarray) -> list[float]:
    out = []
    for i in range(a.shape[0]):
        u = int((a[i] | b[i]).sum())
        out.append(1.0 if u == 0 else int((a[i] & b[i]).sum()) / u)
    return out


def main() -> None:
    print("=" * 78)
    print("18_ceiling_test.py -- is the ~0.5 ceiling in the data or the ground truth?")
    print("=" * 78)
    print("\nResolved inputs:")
    for label, p in [("selection ratios", SR_CSV), ("corrected presence", CORRECTED_CSV),
                     ("naive presence", NAIVE_CSV), ("blind agent", AGENT_CSV),
                     ("Book (workbook)", ALIGNMENT_XLSX)]:
        print(f"  [{'OK' if os.path.exists(p) else 'MISSING':>7}] {label:<20} {p}")
    for p in (SR_CSV, CORRECTED_CSV, NAIVE_CSV, AGENT_CSV, ALIGNMENT_XLSX):
        if not os.path.exists(p):
            sys.exit(f"\nERROR: required input missing: {p}")
    print()

    book = load_book()
    sr_df = pd.read_csv(SR_CSV)
    sr_df["species_code"] = sr_df["species_code"].astype(str).str.strip()

    codes, names = [], []
    for _, r in sr_df.iterrows():
        c = r["species_code"]
        if book.get(c) is not None:
            codes.append(c)
            names.append(r.get("common_name", c))

    TRUTH = np.array([[cat in book[c] for cat in CATEGORIES] for c in codes], dtype=bool)
    DATA = bool_matrix(CORRECTED_CSV, codes)
    NAIVE = bool_matrix(NAIVE_CSV, codes)
    AGENT = bool_matrix(AGENT_CSV, codes)
    SR = sr_df.set_index("species_code").loc[codes][CATEGORIES].to_numpy(dtype=float)

    n = len(codes)
    print(f"Scoring {n} species with a Book entry (all sources aligned on species_code).")
    print(f"Book habitats/species  {TRUTH.sum(1).mean():.2f}")
    print(f"Data habitats/species  {DATA.sum(1).mean():.2f}")
    print(f"Agent habitats/species {AGENT.sum(1).mean():.2f}\n")

    rows_data = prf_rows(DATA, TRUTH)
    rows_agent = prf_rows(AGENT, TRUTH)
    rows_naive = prf_rows(NAIVE, TRUTH)

    # --- headline comparison ----------------------------------------------
    print("=" * 78)
    print("CEILING TEST -- both scored against the Handbook, same species, same metric")
    print("=" * 78)
    print(f"\n  {'Source':<34} {'Prec':>6} {'Rec':>6} {'F1':>6} {'Acc':>6}")
    for label, rows, mat in [
        ("DATA  (availability-corrected)", rows_data, DATA),
        ("DATA  (naive Pareto-80)", rows_naive, NAIVE),
        ("AGENT (blind LLM, knowledge only)", rows_agent, AGENT),
    ]:
        print(f"  {label:<34} {macro(rows,0):>6.3f} {macro(rows,1):>6.3f} "
              f"{macro(rows,2):>6.3f} {macro(rows,3):>6.3f}")

    mp_d, mr_d, mf_d = micro(DATA, TRUTH)
    mp_a, mr_a, mf_a = micro(AGENT, TRUTH)
    print(f"\n  micro F1: data {mf_d:.3f}   agent {mf_a:.3f}")

    agent_f1, data_f1 = macro(rows_agent, 2), macro(rows_data, 2)
    gap = agent_f1 - data_f1
    print(f"\n  AGENT - DATA gap: {gap:+.3f} macro F1")

    # Paired bootstrap: is the gap distinguishable from zero on 40 species?
    rng = np.random.default_rng(0)
    d_f = np.array([r[2] if r[2] is not None else 0.0 for r in rows_data])
    a_f = np.array([r[2] if r[2] is not None else 0.0 for r in rows_agent])
    diffs = []
    for _ in range(10000):
        idx = rng.integers(0, n, n)
        diffs.append(a_f[idx].mean() - d_f[idx].mean())
    diffs = np.array(diffs)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    p_gt0 = float((diffs > 0).mean())
    print(f"  paired bootstrap 95% CI [{lo:+.3f}, {hi:+.3f}], "
          f"P(agent > data) = {p_gt0:.3f}")

    # --- interpretation ----------------------------------------------------
    print("\n" + "-" * 78)
    if agent_f1 < 0.60:
        verdict = "GROUND TRUTH"
        msg = ("The informed agent also ceilings near 0.5. The limit is mostly the "
               "Book-to-9-class mapping, NOT the data. An occupied-range denominator "
               "would not be expected to move the score much.")
    elif gap > 0.15:
        verdict = "DATA"
        msg = ("The agent scores well above the data, so the Handbook IS reproducible "
               "at this resolution and the headroom belongs to the data. The "
               "occupied-range denominator is the right next build.")
    else:
        verdict = "MIXED"
        msg = ("The agent is somewhat better but not dramatically so. Some headroom is "
               "real, but a large part of the ceiling is the mapping.")
    print(f"VERDICT: the bottleneck is mostly the {verdict}.")
    print(msg)
    print("-" * 78)

    # --- agent vs data convergence ----------------------------------------
    jac_ad = jaccard_rows(AGENT, DATA)
    jac_ab = jaccard_rows(AGENT, TRUTH)
    jac_db = jaccard_rows(DATA, TRUTH)
    print(f"\nPairwise agreement (mean Jaccard over {n} species):")
    print(f"  agent vs book {np.mean(jac_ab):.3f}")
    print(f"  data  vs book {np.mean(jac_db):.3f}")
    print(f"  agent vs data {np.mean(jac_ad):.3f}")
    print("  Two independent sources agreeing with each other more than either "
          "agrees\n  with the Book would point at the Book as the odd one out.")

    # --- did the correction help or hurt, per species? --------------------
    f_naive = np.array([r[2] if r[2] is not None else 0.0 for r in rows_naive])
    improved = d_f > f_naive
    worsened = d_f < f_naive
    print(f"\nCorrection effect vs naive: {int(improved.sum())} improved, "
          f"{int(worsened.sum())} worsened, {int((d_f == f_naive).sum())} unchanged")

    # Does "worsened" track marine habitat use? That is what a UK-wide
    # denominator would distort most, so it is a direct test of fix #1.
    marine_idx = [CATEGORIES.index(c) for c in MARINE]
    book_marine = TRUTH[:, marine_idx].any(axis=1)
    data_marine = DATA[:, marine_idx].any(axis=1)
    over_marine = data_marine & ~book_marine  # data invented a marine habitat

    def rate(mask):
        return float(worsened[mask].mean()) if mask.sum() else float("nan")

    print("\nDoes the correction hurt the species a UK-wide denominator would distort?")
    print(f"  worsened rate | data over-calls marine : {rate(over_marine):.3f} "
          f"(n={int(over_marine.sum())})")
    print(f"  worsened rate | it does not            : {rate(~over_marine):.3f} "
          f"(n={int((~over_marine).sum())})")
    print(f"  worsened rate | Book says marine       : {rate(book_marine):.3f} "
          f"(n={int(book_marine.sum())})")
    print(f"  worsened rate | Book says non-marine   : {rate(~book_marine):.3f} "
          f"(n={int((~book_marine).sum())})")

    # --- oracle bound on the SR ranking -----------------------------------
    # Best possible F1 if an oracle chose the ideal k per species from the SR
    # ranking. Bounds how much any rank-based rule could ever achieve.
    oracle = []
    for i in range(n):
        order = np.argsort(-np.where(np.isnan(SR[i]), -np.inf, SR[i]))
        best = 0.0
        for k in range(1, N_CLASSES + 1):
            p = np.zeros(N_CLASSES, dtype=bool)
            p[order[:k]] = True
            tp = int((p & TRUTH[i]).sum()); fp = int((p & ~TRUTH[i]).sum())
            fn = int((~p & TRUTH[i]).sum())
            pr = tp / (tp + fp) if (tp + fp) else 0.0
            rc = tp / (tp + fn) if (tp + fn) else 0.0
            best = max(best, 2 * pr * rc / (pr + rc) if (pr + rc) > 0 else 0.0)
        oracle.append(best)
    print(f"\nOracle bound on the SR ranking (ideal k per species): "
          f"F1 {np.mean(oracle):.3f}")
    print("  The most any rank rule could extract from these selection ratios.")

    # --- write outputs -----------------------------------------------------
    recs = []
    for i, c in enumerate(codes):
        recs.append({
            "species_code": c, "species": names[i],
            "book_habitats": "; ".join(LABELS[cat] for j, cat in enumerate(CATEGORIES) if TRUTH[i, j]),
            "data_habitats": "; ".join(LABELS[cat] for j, cat in enumerate(CATEGORIES) if DATA[i, j]),
            "agent_habitats": "; ".join(LABELS[cat] for j, cat in enumerate(CATEGORIES) if AGENT[i, j]),
            "data_f1": round(d_f[i], 4), "agent_f1": round(a_f[i], 4),
            "naive_f1": round(f_naive[i], 4),
            "agent_minus_data": round(a_f[i] - d_f[i], 4),
            "correction_helped": bool(improved[i]),
            "oracle_f1": round(oracle[i], 4),
            "book_marine": bool(book_marine[i]),
            "data_over_calls_marine": bool(over_marine[i]),
        })
    out = pd.DataFrame(recs).sort_values("agent_minus_data", ascending=False)
    out.to_csv(OUT_CSV, index=False)

    plot_ceiling(rows_data, rows_agent, rows_naive, d_f, a_f, oracle,
                 np.mean(jac_ab), np.mean(jac_db), np.mean(jac_ad), OUT_PNG)

    write_summary(n, rows_data, rows_agent, rows_naive, agent_f1, data_f1, gap,
                  lo, hi, p_gt0, verdict, msg, jac_ab, jac_db, jac_ad,
                  improved, worsened, oracle, out, TRUTH, DATA, AGENT,
                  rate, over_marine, book_marine, mf_d, mf_a)

    print(f"\nWrote:\n  {OUT_CSV}\n  {OUT_PNG}\n  {OUT_MD}")
    print("\n" + "=" * 78)
    print("HEADLINE")
    print("=" * 78)
    print(f"  DATA  vs Book : macro F1 {data_f1:.3f}")
    print(f"  AGENT vs Book : macro F1 {agent_f1:.3f}   (gap {gap:+.3f}, "
          f"95% CI [{lo:+.3f}, {hi:+.3f}])")
    print(f"  Oracle on SR  : macro F1 {np.mean(oracle):.3f}")
    print(f"  -> bottleneck is mostly the {verdict}")
    print("=" * 78)


def plot_ceiling(rows_data, rows_agent, rows_naive, d_f, a_f, oracle,
                 jab, jdb, jad, out_path):
    fig, axes = plt.subplots(1, 3, figsize=(16.5, 5.2))

    ax = axes[0]
    labels = ["Naive\ndata", "Corrected\ndata", "Blind\nagent", "Oracle on\nSR ranking"]
    vals = [macro(rows_naive, 2), macro(rows_data, 2), macro(rows_agent, 2),
            float(np.mean(oracle))]
    colors = ["#b0b0b0", "#1f7a4d", "#4A3AA7", "#d98032"]
    bars = ax.bar(labels, vals, color=colors, alpha=.9)
    ax.axhline(0.498, color="black", ls="--", lw=1.3)
    ax.text(3.45, 0.505, "prevalence baseline (0.498)", fontsize=8, ha="right")
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + .012, f"{v:.3f}",
                ha="center", fontsize=9, fontweight="bold")
    ax.set_ylabel("Macro F1 vs Handbook"); ax.set_ylim(0, 1)
    ax.set_title("How well can anything reproduce the Handbook?", fontsize=11)
    ax.grid(axis="y", alpha=.25)

    ax = axes[1]
    ax.scatter(d_f, a_f, s=42, color="#4A3AA7", alpha=.75, edgecolor="white", lw=.6)
    ax.plot([0, 1], [0, 1], color="black", ls="--", lw=1.2)
    ax.set_xlabel("Data F1 (per species)"); ax.set_ylabel("Agent F1 (per species)")
    ax.set_xlim(-.03, 1.03); ax.set_ylim(-.03, 1.03)
    ax.set_title("Per species: agent vs data\n(above the line = agent better)",
                 fontsize=11)
    ax.grid(alpha=.25)

    ax = axes[2]
    pairs = ["agent\nvs book", "data\nvs book", "agent\nvs data"]
    pv = [jab, jdb, jad]
    bars = ax.bar(pairs, pv, color=["#4A3AA7", "#1f7a4d", "#d98032"], alpha=.9)
    for b, v in zip(bars, pv):
        ax.text(b.get_x() + b.get_width() / 2, v + .012, f"{v:.3f}",
                ha="center", fontsize=9, fontweight="bold")
    ax.set_ylabel("Mean Jaccard"); ax.set_ylim(0, 1)
    ax.set_title("Pairwise agreement between the three sources", fontsize=11)
    ax.grid(axis="y", alpha=.25)

    fig.suptitle("Ceiling test: is the ~0.5 limit in the data or in the ground truth?",
                 fontsize=12.5, y=1.02)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def write_summary(n, rows_data, rows_agent, rows_naive, agent_f1, data_f1, gap,
                  lo, hi, p_gt0, verdict, msg, jac_ab, jac_db, jac_ad,
                  improved, worsened, oracle, out, TRUTH, DATA, AGENT,
                  rate, over_marine, book_marine, mf_d, mf_a):
    L = []
    L.append("# Ceiling test: is the ~0.5 limit in the data or in the ground truth?\n")
    L.append("The availability-corrected data scores macro F1 ≈ 0.50 against the RSPB "
             "Handbook, and the threshold sweep showed no tuning beats that — a "
             "data-free rule naming the five commonest habitats scores 0.498. So the "
             "ceiling is not a tuning failure. This test asks whether it is the "
             "**data** or the **ground truth**.\n")
    L.append("The blind LLM agent has read the literature and never saw the data. It "
             "stands in for *an informed source doing its best*. If it also ceilings "
             "near 0.5, the limit is the Handbook-to-9-class mapping; if it scores far "
             "higher, the headroom is real and belongs to the data.\n")

    L.append("## Result\n")
    L.append(f"| Source | Precision | Recall | F1 | Accuracy |")
    L.append("|---|---:|---:|---:|---:|")
    L.append(f"| Naive data (Pareto-80) | {macro(rows_naive,0):.3f} | "
             f"{macro(rows_naive,1):.3f} | {macro(rows_naive,2):.3f} | "
             f"{macro(rows_naive,3):.3f} |")
    L.append(f"| **Corrected data** (SR ≥ 1) | {macro(rows_data,0):.3f} | "
             f"{macro(rows_data,1):.3f} | **{macro(rows_data,2):.3f}** | "
             f"{macro(rows_data,3):.3f} |")
    L.append(f"| **Blind agent** (knowledge only) | {macro(rows_agent,0):.3f} | "
             f"{macro(rows_agent,1):.3f} | **{macro(rows_agent,2):.3f}** | "
             f"{macro(rows_agent,3):.3f} |")
    L.append(f"| Prevalence baseline (data-free) | — | — | 0.498 | — |")
    L.append(f"| Oracle on the SR ranking | — | — | {np.mean(oracle):.3f} | — |")
    L.append("")
    L.append(f"Agent − data gap: **{gap:+.3f}** macro F1 "
             f"(paired bootstrap 95% CI [{lo:+.3f}, {hi:+.3f}], "
             f"P(agent > data) = {p_gt0:.3f}). Micro F1: data {mf_d:.3f}, "
             f"agent {mf_a:.3f}.\n")

    L.append(f"### Verdict: the bottleneck is mostly the **{verdict}**\n")
    L.append(msg + "\n")

    L.append("## Pairwise agreement\n")
    L.append("| Pair | Mean Jaccard |")
    L.append("|---|---:|")
    L.append(f"| Agent vs Book | {np.mean(jac_ab):.3f} |")
    L.append(f"| Data vs Book | {np.mean(jac_db):.3f} |")
    L.append(f"| Agent vs Data | {np.mean(jac_ad):.3f} |")
    L.append("")
    L.append("If two independent sources agreed with each other more than either "
             "agreed with the Book, that would point at the Book as the outlier.\n")

    L.append("## Does the correction hurt the species a UK-wide denominator distorts?\n")
    L.append("The occupied-range fix would most change species whose availability "
             "denominator is badly wrong — marine and range-restricted birds. If the "
             "species that got *worse* under the correction are concentrated there, "
             "that fix is well targeted.\n")
    L.append("| Subgroup | n | Worsened rate |")
    L.append("|---|---:|---:|")
    L.append(f"| Data over-calls a marine class | {int(over_marine.sum())} | "
             f"{rate(over_marine):.3f} |")
    L.append(f"| It does not | {int((~over_marine).sum())} | {rate(~over_marine):.3f} |")
    L.append(f"| Book says marine | {int(book_marine.sum())} | {rate(book_marine):.3f} |")
    L.append(f"| Book says non-marine | {int((~book_marine).sum())} | "
             f"{rate(~book_marine):.3f} |")
    L.append("")
    L.append(f"Overall: {int(improved.sum())} species improved under the correction, "
             f"{int(worsened.sum())} worsened.\n")

    L.append("## Oracle bound\n")
    L.append(f"If an oracle picked the ideal number of habitats per species from the SR "
             f"ranking, macro F1 would be **{np.mean(oracle):.3f}**. That is the most "
             "any rank-based rule could extract from these selection ratios — the gap "
             "between it and top-K (0.538) is what a better *cutoff rule* could win; "
             "the gap between it and 1.0 is what the ranking itself cannot express.\n")

    L.append("## Where agent and data diverge most\n")
    L.append("| Species | Book | Data | Agent | Data F1 | Agent F1 |")
    L.append("|---|---|---|---|---:|---:|")
    for _, r in out.head(10).iterrows():
        L.append(f"| {r['species']} | {r['book_habitats'] or '—'} | "
                 f"{r['data_habitats'] or '—'} | {r['agent_habitats'] or '—'} | "
                 f"{r['data_f1']:.3f} | {r['agent_f1']:.3f} |")
    L.append("")

    L.append("## Caveats\n")
    L.append("- The agent is **one model's knowledge**, not a true ceiling. It can be "
             "wrong, and it may share phrasing conventions with the hand-entered Book "
             "that the data cannot. It bounds the mapping loosely.\n")
    L.append(f"- {n} species is a small sample; the bootstrap CI on the gap is wide.\n")
    L.append("- The agent and the Book are not fully independent if the Handbook is "
             "part of the literature the model learned from — which would flatter the "
             "agent and make this a conservative test of the data.\n")
    L.append("Generated by `code/landcover_analysis/18_ceiling_test.py`.")

    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))


if __name__ == "__main__":
    main()
