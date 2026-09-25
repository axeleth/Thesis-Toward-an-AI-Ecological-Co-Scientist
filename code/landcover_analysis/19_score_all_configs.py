#!/usr/bin/env python3
"""19_score_all_configs.py  --  every LLM study configuration, scored

Generalises 17_llm_and_data_vs_book_scores.py from ONE matrix to the whole
parameter-study grid. Script 17 scores a single old matrix
(`outputs/habitat_agents/blind_presence_matrix.csv`, a separate earlier "blind
agent" run); this script loops over the per-configuration majority-vote matrices
produced by `code/llm_study/aggregate.py` and scores each one against BOTH
references, then joins in that configuration's cost, latency and invalid rate.

17 and 18 are left untouched and keep their own outputs; nothing here overwrites
them.

SCOPE -- THE FULL GRID
----------------------
Both arms are scored: `tools-off` (the model answers from memory alone) and
`tools-on` (server-side web search). The tools-on run completed on 2026-08-10,
so TOOLS_FILTER is None and all 18 cells (3 models x 3 prompts x 2 tools
settings) are covered.

TOOLS_FILTER still exists as a guard: set it to "off" or "on" to score one arm
in isolation. It is applied at BOTH ends -- matrix discovery (the filename must
end `__tools-<arm>`) and the raw-call join -- so a partial arm cannot leak in
while it is still being generated.

COMPLETENESS
------------
A configuration is scored only if it is COMPLETE: all 41 focal species present
with the full number of repeats (3) and no errored calls. Partial configurations
are reported and skipped rather than silently scored on fewer species, which
would make their metrics incomparable to the rest of the grid.

REFERENCES (both, per configuration)
------------------------------------
    BOOK  the RSPB Handbook coding, `Book` column of alignment_adjusted.xlsx.
          The REFERENCE STANDARD -- the headline metric is F1 vs Book.
    DATA  the availability-corrected selection ratio, SR >= 1
          (aggregate9_presence_corrected.csv, from 15_selection_ratio_correction.py)

Both are the same references scripts 16-18 use, so the numbers here are directly
comparable to theirs.

    TP  config says yes, reference says yes    FP  config says yes, reference says no
    FN  config says no,  reference says yes    TN  config says no,  reference says no

    Precision = TP / (TP + FP)      Recall   = TP / (TP + FN)
    F1        = 2PR / (P + R)       Accuracy = (TP + TN) / 9
    Cohen's kappa -- chance-corrected agreement (identical definition to 18).

Precision is undefined when a configuration flags nothing, recall when the
reference lists nothing. Reported as N/A / null, never as 0.

MACRO vs MICRO. Both are emitted, for the reason 17 gives: macro means the
per-species scores (every species counts equally), micro pools TP/FP/FN/TN
across species (every habitat call counts equally). The headline `f1_vs_book`
column is the MACRO F1, matching script 17's headline convention.

Inputs:
    outputs/llm_study/matrices/<model>__<prompt>__tools-<on|off>.csv
    outputs/llm_study/raw_calls.jsonl                          (cost / latency)
    outputs/llm_study/parsed_calls.jsonl                       (invalid flags)
    outputs/landcover_analysis/selection_corrected/aggregate9_presence_corrected.csv
    alignment_adjusted.xlsx  (Book column)

Outputs:
    outputs/llm_study/config_scores.csv
    outputs/llm_study/config_scores.json        (embedded into the dashboard)
    outputs/llm_study/config_scores_per_class.csv
    outputs/llm_study/CONFIG_SCORES.md

Usage:
    python code/landcover_analysis/19_score_all_configs.py
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "habitat_agents"))
import _agent_common as ac  # noqa: E402

CODE_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
_m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", CODE_ROOT)
DATA_ROOT = _m.group(1) if _m else CODE_ROOT

# Which tools arm to score: "off", "on", or None for both. The tools-on run
# completed on 2026-08-10, so this now covers the full 18-cell grid.
TOOLS_FILTER = None

SEL_DIR = os.path.join(DATA_ROOT, "outputs", "landcover_analysis", "selection_corrected")
DATA_CSV = os.path.join(SEL_DIR, "aggregate9_presence_corrected.csv")
ALIGNMENT_XLSX = os.path.join(DATA_ROOT, "alignment_adjusted.xlsx")

STUDY_DIR = os.path.join(DATA_ROOT, "outputs", "llm_study")
MATRIX_DIR = os.path.join(STUDY_DIR, "matrices")
RAW_CALLS = os.path.join(STUDY_DIR, "raw_calls.jsonl")
PARSED_CALLS = os.path.join(STUDY_DIR, "parsed_calls.jsonl")

OUT_CSV = os.path.join(STUDY_DIR, "config_scores.csv")
OUT_JSON = os.path.join(STUDY_DIR, "config_scores.json")
OUT_PER_CLASS = os.path.join(STUDY_DIR, "config_scores_per_class.csv")
OUT_MD = os.path.join(STUDY_DIR, "CONFIG_SCORES.md")

CATEGORIES = ac.CATEGORIES
LABELS = ac.CATEGORY_LABELS
N_CLASSES = len(CATEGORIES)

EXPECTED_SPECIES = 41
EXPECTED_REPEATS = 3

# Presentation order for the two grid axes.
MODEL_ORDER = ["haiku", "sonnet", "opus"]
PROMPT_ORDER = ["p2_scoped", "p3_informed", "p4_engineered"]
PROMPT_LABELS = {
    "p2_scoped": "P2 scoped",
    "p3_informed": "P3 informed",
    "p4_engineered": "P4 engineered",
}
MODEL_LABELS = {"haiku": "Haiku", "sonnet": "Sonnet", "opus": "Opus"}
# Presentation order for the tools axis: no tool, tool offered, tool demanded.
TOOLS_ORDER = ["off", "on", "forced"]
TOOLS_LABELS = {
    "off": "Off (memory only)",
    "on": "On (search offered, model chooses)",
    "forced": "Forced (search demanded by the prompt)",
}


# ---------------------------------------------------------------------------
# Metrics -- definitions identical to 17 / 18 so the numbers stay comparable
# ---------------------------------------------------------------------------
def confusion(pred: set, truth: set) -> tuple[int, int, int, int]:
    tp = len(pred & truth)
    fp = len(pred - truth)
    fn = len(truth - pred)
    tn = N_CLASSES - tp - fp - fn
    return tp, fp, fn, tn


def scores(tp: int, fp: int, fn: int, tn: int):
    """(precision, recall, f1, accuracy); None where undefined."""
    p = tp / (tp + fp) if (tp + fp) else None
    r = tp / (tp + fn) if (tp + fn) else None
    if p is None or r is None or (p + r) == 0:
        f = 0.0 if (p is not None or r is not None) else None
    else:
        f = 2 * p * r / (p + r)
    return p, r, f, (tp + tn) / N_CLASSES


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


def jnum(v):
    """JSON-safe number: None for undefined/NaN/inf, else a rounded float."""
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (int, np.integer)):
        return int(v)
    return round(float(v), 4)


def norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", str(s).lower())


CANON = {norm(LABELS[s]): s for s in CATEGORIES}
CANON.update({norm(s): s for s in CATEGORIES})


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_book() -> dict:
    """The RSPB Handbook coding -- same reader as 17/18."""
    from openpyxl import load_workbook

    wb = load_workbook(ALIGNMENT_XLSX, data_only=True)
    ws = wb["alignment"]
    header = {str(c.value).strip(): c.column for c in ws[1] if c.value is not None}
    bc, cc = header.get("Book"), header.get("species_code")
    if not bc or not cc:
        sys.exit(f"ERROR: need 'Book' and 'species_code' columns; found {sorted(header)}")
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
        sys.exit(f"ERROR: {label} matrix missing columns: {', '.join(missing)}")
    return {r["species_code"]: {c for c in CATEGORIES if bool(r[c])}
            for _, r in df.iterrows()}


def discover_configs() -> list[dict]:
    """Config matrices on disk: TOOLS-OFF only, majority-vote (not _meanprob)."""
    found = []
    for path in sorted(glob.glob(os.path.join(MATRIX_DIR, "*.csv"))):
        stem = os.path.basename(path)[:-4]
        if stem.endswith("_meanprob"):
            continue
        parts = stem.split("__")
        if len(parts) != 3 or not parts[2].startswith("tools-"):
            print(f"  WARNING: skipping unrecognised matrix name {stem!r}")
            continue
        model, prompt, tools = parts[0], parts[1], parts[2][len("tools-"):]
        if TOOLS_FILTER is not None and tools != TOOLS_FILTER:
            continue          # the tools-on run is live -- never score it here
        found.append({"config_id": stem, "model": model, "prompt": prompt,
                      "tools": tools, "path": path})
    return found


def load_call_stats() -> dict:
    """Per-config cost / latency / invalid rate from the raw + parsed call logs.

    The raw log is append-only and shared with the live tools-on run, so it is
    read line-by-line, tools-on records are dropped immediately, and a torn
    final line (a record caught mid-write) is tolerated rather than crashing.
    """
    if not os.path.exists(RAW_CALLS):
        sys.exit(f"ERROR: missing {RAW_CALLS}")

    agg: dict[tuple, dict] = defaultdict(
        lambda: {"calls": 0, "cost": 0.0, "latency": 0.0, "errors": 0,
                 "species": set(), "repeats": defaultdict(set),
                 "in_tok": 0, "out_tok": 0, "searched": 0, "searches": 0,
                 # Per-call values, kept so medians can be taken. Cost is also
                 # accumulated per species (a species = `repeats` calls), because
                 # the headline cost figure is per species, not per call.
                 "lat_each": [], "cost_by_species": defaultdict(float)}
    )
    torn = 0
    with open(RAW_CALLS, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                torn += 1        # live appender caught mid-write; ignore
                continue
            if TOOLS_FILTER is not None and r.get("tools") != TOOLS_FILTER:
                continue
            k = (r["model_key"], r["prompt_id"], r["tools"])
            a = agg[k]
            a["calls"] += 1
            c_usd = float(r.get("cost_usd") or 0)
            lat_s = float(r.get("wall_clock_seconds") or 0)
            a["cost"] += c_usd
            a["latency"] += lat_s
            a["lat_each"].append(lat_s)
            a["cost_by_species"][r["species_code"]] += c_usd
            a["in_tok"] += int(r.get("input_tokens") or 0)
            a["out_tok"] += int(r.get("output_tokens") or 0)
            # Tool availability is not tool use: record how often a call that
            # COULD search actually did. Zero for the tools-off arm by design.
            n_srch = int(r.get("tool_calls_count") or 0)
            a["searches"] += n_srch
            if n_srch:
                a["searched"] += 1
            if r.get("error"):
                a["errors"] += 1
            a["species"].add(r["species_code"])
            a["repeats"][r["species_code"]].add(r.get("repeat_index"))
    if torn:
        print(f"  NOTE: {torn} unparseable line(s) in raw_calls.jsonl skipped "
              "(live run mid-write).")

    # Invalid flags live in the parsed log, not the raw one.
    invalid: dict[tuple, int] = defaultdict(int)
    parsed_n: dict[tuple, int] = defaultdict(int)
    if os.path.exists(PARSED_CALLS):
        with open(PARSED_CALLS, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if TOOLS_FILTER is not None and r.get("tools") != TOOLS_FILTER:
                    continue
                k = (r["model_key"], r["prompt_id"], r["tools"])
                parsed_n[k] += 1
                if r.get("invalid_flag"):
                    invalid[k] += 1
    else:
        print(f"  NOTE: no parsed call log at {PARSED_CALLS}; invalid rate unavailable.")

    out = {}
    for k, a in agg.items():
        n_species = len(a["species"])
        n = a["calls"]
        reps = {len(v) for v in a["repeats"].values()}
        out[k] = {
            "n_calls": n,
            "n_species_seen": n_species,
            "min_repeats": min(reps) if reps else 0,
            "max_repeats": max(reps) if reps else 0,
            "n_errors": a["errors"],
            "total_cost_usd": round(a["cost"], 6),
            "mean_cost_per_species": round(a["cost"] / n_species, 6) if n_species else None,
            "mean_latency_s": round(a["latency"] / n, 3) if n else None,
            # HEADLINE figures. Medians, because both distributions are skewed by
            # a minority of calls: retry backoff inflates latency (opus/p4 forced
            # is 93.9 s mean vs 18.4 s median, from 6 retried calls of 123), and
            # configurations that search on only some species inflate cost. The
            # mean there describes no call that actually happened.
            "median_cost_per_species": (
                round(float(np.median(list(a["cost_by_species"].values()))), 6)
                if a["cost_by_species"] else None),
            "median_latency_s": (round(float(np.median(a["lat_each"])), 3)
                                 if a["lat_each"] else None),
            "total_input_tokens": a["in_tok"],
            "total_output_tokens": a["out_tok"],
            "invalid_rate": (round(invalid[k] / parsed_n[k], 4)
                             if parsed_n.get(k) else None),
            "n_invalid": invalid.get(k, 0),
            "search_rate": round(a["searched"] / n, 4) if n else None,
            "n_searched": a["searched"],
            "mean_searches_per_call": round(a["searches"] / n, 3) if n else None,
        }
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score_against(pred_sets: dict, ref_sets: dict, codes: list[str]) -> dict:
    """Macro + micro scores of one configuration against one reference."""
    per_species = []
    TP = FP = FN = TN = 0
    for code in codes:
        p = pred_sets.get(code, set())
        t = ref_sets.get(code, set())
        tp, fp, fn, tn = confusion(p, t)
        TP += tp; FP += fp; FN += fn; TN += tn
        pr, rc, f1, acc = scores(tp, fp, fn, tn)
        per_species.append({"precision": pr, "recall": rc, "f1": f1,
                            "accuracy": acc, "kappa": kappa(tp, fp, fn, tn)})

    def mac(col):
        v = [x[col] for x in per_species if x[col] is not None and not pd.isna(x[col])]
        return float(np.mean(v)) if v else None

    mip, mir, mif, _ = scores(TP, FP, FN, TN)
    n = len(codes)
    return {
        "TP": TP, "FP": FP, "FN": FN, "TN": TN,
        "macro_precision": mac("precision"), "macro_recall": mac("recall"),
        "macro_f1": mac("f1"), "macro_accuracy": mac("accuracy"),
        "macro_kappa": mac("kappa"),
        "micro_precision": mip, "micro_recall": mir, "micro_f1": mif,
        "micro_accuracy": (TP + TN) / (n * N_CLASSES) if n else None,
        "pooled_kappa": kappa(TP, FP, FN, TN),
    }


def per_class_rows(cfg, pred_sets, book, data_sets, codes) -> list[dict]:
    """One row per (config, class): the confusion vs Book and vs Data."""
    P = np.array([[c in pred_sets.get(k, set()) for c in CATEGORIES] for k in codes],
                 dtype=bool)
    B = np.array([[c in book.get(k, set()) for c in CATEGORIES] for k in codes],
                 dtype=bool)
    D = np.array([[c in data_sets.get(k, set()) for c in CATEGORIES] for k in codes],
                 dtype=bool)
    n = len(codes)
    rows = []
    for j, c in enumerate(CATEGORIES):
        rec = {
            "config_id": cfg["config_id"], "model": cfg["model"],
            "prompt": cfg["prompt"], "tools": cfg["tools"],
            "class": c, "class_label": LABELS[c],
            "n_book_true": int(B[:, j].sum()),
            "n_data_true": int(D[:, j].sum()),
            "n_config_true": int(P[:, j].sum()),
        }
        for tag, M in (("book", B), ("data", D)):
            tp = int((P[:, j] & M[:, j]).sum())
            fp = int((P[:, j] & ~M[:, j]).sum())
            fn = int((~P[:, j] & M[:, j]).sum())
            tn = int((~P[:, j] & ~M[:, j]).sum())
            p, r_, f, _ = scores(tp, fp, fn, tn)
            rec.update({
                f"vs_{tag}_TP": tp, f"vs_{tag}_FP": fp, f"vs_{tag}_FN": fn,
                f"vs_{tag}_TN": tn, f"vs_{tag}_precision": p, f"vs_{tag}_recall": r_,
                f"vs_{tag}_f1": f, f"vs_{tag}_accuracy": (tp + tn) / n if n else None,
                f"vs_{tag}_kappa": kappa(tp, fp, fn, tn),
            })
        rows.append(rec)
    return rows


def efficiency_frontier(df) -> list[str]:
    """Config ids on the cost/accuracy Pareto front (cheaper is better, F1 higher).

    A configuration is on the frontier when nothing else is both no more
    expensive AND at least as accurate (with one of the two strictly better).
    """
    front = []
    recs = [r for r in df.to_dict(orient="records")
            if r.get("median_cost_per_species") is not None
            and r.get("f1_vs_book") is not None]
    for r in recs:
        dominated = any(
            o["median_cost_per_species"] <= r["median_cost_per_species"]
            and o["f1_vs_book"] >= r["f1_vs_book"]
            and (o["median_cost_per_species"] < r["median_cost_per_species"]
                 or o["f1_vs_book"] > r["f1_vs_book"])
            for o in recs if o["config_id"] != r["config_id"]
        )
        if not dominated:
            front.append(r["config_id"])
    return front


# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 86)
    print("19_score_all_configs.py -- every LLM configuration scored on Book and Data")
    print("=" * 86)
    if TOOLS_FILTER is not None:
        print(f"\nSCOPE: tools-{TOOLS_FILTER} configurations ONLY "
              "(the tools-on arm is excluded by design).")

    print("\nResolved inputs:")
    for lbl, p in [("Config matrices", MATRIX_DIR), ("Raw calls", RAW_CALLS),
                   ("DATA (SR >= 1)", DATA_CSV), ("Book (reference)", ALIGNMENT_XLSX)]:
        print(f"  [{'OK' if os.path.exists(p) else 'MISSING':>7}] {lbl:<18} {p}")
    for p in (MATRIX_DIR, RAW_CALLS, DATA_CSV, ALIGNMENT_XLSX):
        if not os.path.exists(p):
            sys.exit(f"\nERROR: missing {p}")

    book_raw = load_book()
    book = {k: v for k, v in book_raw.items() if v is not None}
    data_sets = load_pred(DATA_CSV, "DATA")
    stats = load_call_stats()
    configs = discover_configs()
    if not configs:
        sys.exit(f"\nERROR: no tools-{TOOLS_FILTER} matrices found in {MATRIX_DIR}")

    # Score on the species that have a Book entry, in canonical roster order.
    roster = pd.read_csv(DATA_CSV)
    roster["species_code"] = roster["species_code"].astype(str).str.strip()
    codes = [c for c in roster["species_code"] if c in book]
    no_book = [c for c in roster["species_code"] if c not in book]
    if no_book:
        print(f"\nNOTE: {len(no_book)} species have no Book entry, excluded: "
              f"{', '.join(no_book)}")
    print(f"\nFound {len(configs)} tools-{TOOLS_FILTER} configuration(s). Scoring on "
          f"{len(codes)} species x {N_CLASSES} classes = "
          f"{len(codes) * N_CLASSES} habitat calls each.\n")

    rows, pc_rows, skipped = [], [], []
    for cfg in configs:
        pred = load_pred(cfg["path"], cfg["config_id"])
        st = stats.get((cfg["model"], cfg["prompt"], cfg["tools"]), {})

        # Completeness: full roster in the matrix AND full repeats in the log.
        n_matrix = len([c for c in codes if c in pred])
        n_log = st.get("n_species_seen", 0)
        min_rep = st.get("min_repeats", 0)
        n_err = st.get("n_errors", 0)
        complete = (n_matrix == len(codes)
                    and n_log >= EXPECTED_SPECIES
                    and min_rep >= EXPECTED_REPEATS
                    and n_err == 0)
        if not complete:
            skipped.append(
                f"{cfg['config_id']} (matrix species {n_matrix}/{len(codes)}, "
                f"log species {n_log}/{EXPECTED_SPECIES}, min repeats "
                f"{min_rep}/{EXPECTED_REPEATS}, errors {n_err})"
            )
            continue

        vs_book = score_against(pred, book, codes)
        vs_data = score_against(pred, data_sets, codes)
        pc_rows.extend(per_class_rows(cfg, pred, book, data_sets, codes))

        rows.append({
            "config_id": cfg["config_id"],
            "model": cfg["model"], "prompt": cfg["prompt"], "tools": cfg["tools"],
            "model_label": MODEL_LABELS.get(cfg["model"], cfg["model"]),
            "prompt_label": PROMPT_LABELS.get(cfg["prompt"], cfg["prompt"]),
            "complete": True,
            "n_species_complete": n_matrix,
            "n_calls": st.get("n_calls"),
            # --- headline: macro, matching how 17 reports ---
            "f1_vs_book": vs_book["macro_f1"],
            "f1_vs_data": vs_data["macro_f1"],
            "kappa_vs_book": vs_book["macro_kappa"],
            "kappa_vs_data": vs_data["macro_kappa"],
            "accuracy_vs_book": vs_book["macro_accuracy"],
            "accuracy_vs_data": vs_data["macro_accuracy"],
            "precision_vs_book": vs_book["macro_precision"],
            "recall_vs_book": vs_book["macro_recall"],
            "precision_vs_data": vs_data["macro_precision"],
            "recall_vs_data": vs_data["macro_recall"],
            # --- micro / pooled ---
            "micro_f1_vs_book": vs_book["micro_f1"],
            "micro_f1_vs_data": vs_data["micro_f1"],
            "micro_accuracy_vs_book": vs_book["micro_accuracy"],
            "pooled_kappa_vs_book": vs_book["pooled_kappa"],
            "pooled_kappa_vs_data": vs_data["pooled_kappa"],
            "TP_vs_book": vs_book["TP"], "FP_vs_book": vs_book["FP"],
            "FN_vs_book": vs_book["FN"], "TN_vs_book": vs_book["TN"],
            "TP_vs_data": vs_data["TP"], "FP_vs_data": vs_data["FP"],
            "FN_vs_data": vs_data["FN"], "TN_vs_data": vs_data["TN"],
            # --- economics ---
            "median_cost_per_species": st.get("median_cost_per_species"),
            "median_latency_s": st.get("median_latency_s"),
            "mean_cost_per_species": st.get("mean_cost_per_species"),
            "mean_latency_s": st.get("mean_latency_s"),
            "total_cost_usd": st.get("total_cost_usd"),
            "invalid_rate": st.get("invalid_rate"),
            "n_invalid": st.get("n_invalid"),
            "search_rate": st.get("search_rate"),
            "n_searched": st.get("n_searched"),
            "mean_searches_per_call": st.get("mean_searches_per_call"),
            "total_input_tokens": st.get("total_input_tokens"),
            "total_output_tokens": st.get("total_output_tokens"),
        })

    if skipped:
        print("SKIPPED as incomplete (not scored):")
        for s in skipped:
            print(f"  - {s}")
        print()
    if not rows:
        sys.exit("ERROR: no complete configuration to score.")

    df = pd.DataFrame(rows)
    df["_m"] = df["model"].map(lambda m: MODEL_ORDER.index(m) if m in MODEL_ORDER else 99)
    df["_p"] = df["prompt"].map(lambda p: PROMPT_ORDER.index(p) if p in PROMPT_ORDER else 99)
    df["_t"] = df["tools"].map(lambda t: TOOLS_ORDER.index(t) if t in TOOLS_ORDER else 99)
    df = df.sort_values(["_m", "_p", "_t"]).drop(columns=["_m", "_p", "_t"]).reset_index(drop=True)

    frontier = efficiency_frontier(df)
    df["on_frontier"] = df["config_id"].isin(frontier)

    df.to_csv(OUT_CSV, index=False)
    pc = pd.DataFrame(pc_rows)
    pc.to_csv(OUT_PER_CLASS, index=False)

    # --- JSON sibling, embedded into the dashboard -------------------------
    id_cols = ("config_id", "model", "prompt", "tools", "model_label",
               "prompt_label", "complete", "on_frontier")
    num_cols = [c for c in df.columns if c not in id_cols]
    payload = {
        "generated_by": "code/landcover_analysis/19_score_all_configs.py",
        "scope": (f"tools-{TOOLS_FILTER} configurations only"
                  if TOOLS_FILTER else "all configurations"),
        "tools_on_status": "The tools-on (web search) arm is a separate run and is "
                           "deliberately excluded from this file.",
        "reference_standard": "RSPB Handbook (Book)",
        "references": {
            "book": "RSPB Handbook coding, Book column of alignment_adjusted.xlsx "
                    "(the reference standard)",
            "data": "Availability-corrected selection ratio SR >= 1 "
                    "(aggregate9_presence_corrected.csv), shown alongside",
        },
        "metric_note": "Headline f1/kappa/accuracy/precision/recall columns are MACRO "
                       "(mean of per-species scores), matching script 17.",
        "n_species": len(codes),
        "n_classes": N_CLASSES,
        "n_repeats": EXPECTED_REPEATS,
        "model_order": MODEL_ORDER,
        "prompt_order": PROMPT_ORDER,
        "tools_order": [t for t in TOOLS_ORDER
                        if any(c["tools"] == t for c in df.to_dict(orient="records"))],
        "tools_labels": TOOLS_LABELS,
        "model_labels": MODEL_LABELS,
        "prompt_labels": PROMPT_LABELS,
        "class_labels": [{"slug": c, "label": LABELS[c]} for c in CATEGORIES],
        "efficiency_frontier": frontier,
        "configs": [
            {**{k: r[k] for k in id_cols if k in r},
             **{k: jnum(r[k]) for k in num_cols}}
            for r in df.to_dict(orient="records")
        ],
        "per_class": [
            {
                "config_id": r["config_id"], "model": r["model"],
                "prompt": r["prompt"], "tools": r["tools"],
                "class": r["class"], "class_label": r["class_label"],
                "n_book_true": int(r["n_book_true"]),
                "n_config_true": int(r["n_config_true"]),
                "vs_book_f1": jnum(r["vs_book_f1"]),
                "vs_book_TP": int(r["vs_book_TP"]), "vs_book_FP": int(r["vs_book_FP"]),
                "vs_book_FN": int(r["vs_book_FN"]), "vs_book_TN": int(r["vs_book_TN"]),
                "vs_data_f1": jnum(r["vs_data_f1"]),
            }
            for r in pc.to_dict(orient="records")
        ],
        "skipped_incomplete": skipped,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    # --- leaderboard to stdout ---------------------------------------------
    print("=" * 86)
    print("LEADERBOARD  (reference standard = RSPB Handbook; sorted by F1 vs Book)")
    print("=" * 86)
    lb = df.sort_values("f1_vs_book", ascending=False)
    print(f"\n  {'Model':<8} {'Prompt':<14} {'Tools':<6} {'F1 Book':>8} {'F1 Data':>8} "
          f"{'k Book':>7} {'Acc':>6} {'med $/sp':>10} {'med lat':>8} {'Inval':>6}  EF")
    print("  " + "-" * 84)
    for _, r in lb.iterrows():
        inval = "N/A" if r["invalid_rate"] is None else f"{r['invalid_rate'] * 100:.1f}%"
        print(f"  {r['model']:<8} {r['prompt']:<14} {r['tools']:<6} {fmt(r['f1_vs_book']):>8} "
              f"{fmt(r['f1_vs_data']):>8} {fmt(r['kappa_vs_book']):>7} "
              f"{fmt(r['accuracy_vs_book']):>6} ${r['median_cost_per_species']:>9.4f} "
              f"{r['median_latency_s']:>8.2f} {inval:>6}  "
              f"{'*' if r['on_frontier'] else ''}")
    print("\n  EF * = on the cost/accuracy efficiency frontier.")
    print("  Cost and latency are MEDIANS (per species / per call): both are skewed by a")
    print("  minority of slow or search-heavy calls, so the mean overstates the typical call.")

    print("\n" + "=" * 86)
    print("F1 vs BOOK by model x prompt x tools")
    print("=" * 86)
    piv = df.pivot_table(index=["model", "tools"], columns="prompt",
                         values="f1_vs_book")
    piv = piv.reindex(columns=[p for p in PROMPT_ORDER if p in piv.columns])
    piv = piv.reindex([(m, t) for m in MODEL_ORDER for t in ("off", "on")
                       if (m, t) in piv.index])
    print()
    print(piv.round(3).to_string())

    # The tools axis, isolated: the paired off->on delta for each cell.
    if df["tools"].nunique() > 1:
        print("\n" + "=" * 86)
        print("TOOLS EFFECT  (F1 vs Book, tools-on minus tools-off)")
        print("=" * 86)
        print(f"\n  {'Model':<8} {'Prompt':<14} {'off':>7} {'on':>7} {'delta':>8} "
              f"{'x cost':>8}")
        print("  " + "-" * 56)
        deltas = []
        for m in MODEL_ORDER:
            for p in PROMPT_ORDER:
                a = df[(df.model == m) & (df.prompt == p) & (df.tools == "off")]
                b = df[(df.model == m) & (df.prompt == p) & (df.tools == "on")]
                if a.empty or b.empty:
                    continue
                f_off = a.iloc[0]["f1_vs_book"]; f_on = b.iloc[0]["f1_vs_book"]
                c_off = a.iloc[0]["mean_cost_per_species"]
                c_on = b.iloc[0]["mean_cost_per_species"]
                d = f_on - f_off
                deltas.append(d)
                mult = (c_on / c_off) if c_off else float("nan")
                print(f"  {m:<8} {p:<14} {f_off:>7.3f} {f_on:>7.3f} {d:>+8.3f} "
                      f"{mult:>7.1f}x")
        if deltas:
            print(f"\n  Mean delta {np.mean(deltas):+.3f} over {len(deltas)} paired "
                  f"cells; {sum(1 for d in deltas if d > 0)} improved, "
                  f"{sum(1 for d in deltas if d < 0)} got worse.")

    write_summary(df, pc, len(codes), skipped, frontier)
    print(f"\nWrote:\n  {OUT_CSV}\n  {OUT_JSON}\n  {OUT_PER_CLASS}\n  {OUT_MD}")


def write_summary(df, pc, n_species, skipped, frontier):
    L = []
    L.append("# LLM study configurations scored against the Handbook and the data\n")
    if TOOLS_FILTER is not None:
        L.append(f"**Scope: tools-{TOOLS_FILTER} configurations only.** The tools-on "
                 "(web search) arm of the study is a separate run and is excluded "
                 "here.\n")
    L.append("Every complete configuration of the parameter-study grid "
             "(model tier x prompt), scored against the same two references scripts "
             "16-18 use, so these numbers are directly comparable to theirs.\n")
    L.append("- **Book** — the RSPB Handbook coding. **The reference standard**; the "
             "headline metric is F1 vs Book.")
    L.append("- **Data** — the availability-corrected selection ratio (SR ≥ 1), shown "
             "alongside as a second point of comparison, not as truth.\n")
    L.append("```")
    L.append("Precision = TP / (TP + FP)     Recall   = TP / (TP + FN)")
    L.append("F1        = 2PR / (P + R)      Accuracy = (TP + TN) / 9")
    L.append("Cohen's kappa -- chance-corrected agreement")
    L.append("```\n")
    L.append(f"Scored on {n_species} species x {N_CLASSES} classes, "
             f"{EXPECTED_REPEATS} repeats per cell aggregated by majority vote. "
             "Reported scores are MACRO (the mean of the per-species scores), "
             "matching script 17's headline convention.\n")
    if skipped:
        L.append("Skipped as incomplete (not scored):\n")
        for s in skipped:
            L.append(f"- `{s}`")
        L.append("")

    L.append("## Leaderboard\n")
    L.append("| Model | Prompt | Tools | F1 vs Book | F1 vs Data | kappa vs Book | "
             "Accuracy | median $/species | median latency (s) | Invalid | Frontier |")
    L.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|:--:|")
    for _, r in df.sort_values("f1_vs_book", ascending=False).iterrows():
        inval = "N/A" if r["invalid_rate"] is None else f"{r['invalid_rate'] * 100:.1f}%"
        L.append(f"| {r['model_label']} | {r['prompt_label']} | {r['tools']} | "
                 f"{fmt(r['f1_vs_book'])} | {fmt(r['f1_vs_data'])} | "
                 f"{fmt(r['kappa_vs_book'])} | {fmt(r['accuracy_vs_book'])} | "
                 f"${r['median_cost_per_species']:.4f} | {r['median_latency_s']:.2f} | "
                 f"{inval} | {'★' if r['on_frontier'] else ''} |")
    L.append("")

    # The tools axis, isolated.
    if df["tools"].nunique() > 1:
        L.append("## The tools axis\n")
        L.append("Each cell run twice: answering from memory (`off`) and with "
                 "server-side web search (`on`). Delta is F1 vs Book, on minus off.\n")
        L.append("| Model | Prompt | F1 off | F1 on | Delta | Cost off | Cost on | "
                 "Cost multiple |")
        L.append("|---|---|---:|---:|---:|---:|---:|---:|")
        deltas = []
        for m in MODEL_ORDER:
            for p in PROMPT_ORDER:
                a = df[(df.model == m) & (df.prompt == p) & (df.tools == "off")]
                b = df[(df.model == m) & (df.prompt == p) & (df.tools == "on")]
                if a.empty or b.empty:
                    continue
                ar, br = a.iloc[0], b.iloc[0]
                d = br["f1_vs_book"] - ar["f1_vs_book"]
                deltas.append(d)
                c_off, c_on = ar["mean_cost_per_species"], br["mean_cost_per_species"]
                mult = f"{c_on / c_off:.1f}x" if c_off else "N/A"
                L.append(f"| {MODEL_LABELS.get(m, m)} | {PROMPT_LABELS.get(p, p)} | "
                         f"{fmt(ar['f1_vs_book'])} | {fmt(br['f1_vs_book'])} | "
                         f"{d:+.3f} | ${c_off:.4f} | ${c_on:.4f} | {mult} |")
        if deltas:
            L.append("")
            L.append(f"Mean delta **{np.mean(deltas):+.3f}** over {len(deltas)} paired "
                     f"cells: {sum(1 for d in deltas if d > 0)} improved, "
                     f"{sum(1 for d in deltas if d < 0)} got worse.")
        L.append("")
    L.append("Cost and latency are **medians** -- cost per species (each species is "
             "`repeats` calls), latency per call. Both distributions are skewed by a "
             "minority of slow or search-heavy calls, so the mean describes no typical "
             "call; the means are retained in `config_scores.csv` as "
             "`mean_cost_per_species` / `mean_latency_s`.\n")
    L.append(f"Efficiency frontier (cheapest at each accuracy level): "
             f"{', '.join('`' + c + '`' for c in frontier) if frontier else 'none'}.\n")

    L.append("## F1 vs Book, by model and prompt (mean over both tools settings)\n")
    piv = df.pivot_table(index="model", columns="prompt", values="f1_vs_book")
    piv = piv.reindex(index=[m for m in MODEL_ORDER if m in piv.index],
                      columns=[p for p in PROMPT_ORDER if p in piv.columns])
    L.append("| Model | " + " | ".join(PROMPT_LABELS.get(c, c) for c in piv.columns) + " |")
    L.append("|---|" + "---:|" * len(piv.columns))
    for m, row in piv.iterrows():
        L.append(f"| {MODEL_LABELS.get(m, m)} | " + " | ".join(fmt(v) for v in row) + " |")
    L.append("")
    L.append("Generated by `code/landcover_analysis/19_score_all_configs.py`.")

    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))


if __name__ == "__main__":
    main()
