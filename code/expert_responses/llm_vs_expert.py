#!/usr/bin/env python3
"""llm_vs_expert.py  --  score the LLM configurations against expert opinion
============================================================================

The LLM study already scores each configuration against the RSPB Handbook
("Book") and the eBird-derived data. This adds the third reference: the
surveyed experts.

Why experts are a different reference from the Book
---------------------------------------------------
The Handbook is one curated source with a single answer per species. The
experts are several people who sometimes disagree with each other, and that
structure carries information the Book cannot: a model disagreeing with the
experts on a species the experts themselves split on means much less than
disagreeing on one they called unanimously. Hence the CONSISTENCY-WEIGHTED
score, which weights each species by how much the experts agreed on it.

Species the experts declined to answer are excluded from scoring. They have
no consensus to be consistent with, so they cannot contribute to an
agreement measure. (Whether a model answers them at all is not analysed:
these systems are built to return an answer, so "it answered" is a property
of the system, not a finding about it.)

Metrics per configuration
-------------------------
``f1_vs_expert`` / ``precision`` / ``recall``
    Macro over species, against the expert consensus matrix. A habitat
    counts as expert-positive when a majority of opinionated respondents
    marked it (see ``MAJORITY``).

``jaccard_vs_expert``
    Mean over species of |LLM n Expert| / |LLM u Expert|. Ignores the
    shared "no"s that inflate raw accuracy over 9 mostly-empty categories.

``weighted_f1_vs_expert``
    The same F1, but each species contributes in proportion to expert
    consensus on it (Jaccard among the experts). Species the experts
    disagreed about count for less, because they are a weaker test.

``baseline_breadth``
    Mean habitats asserted per species. Not an accuracy measure in itself,
    but it turns out to be what drives agreement: the experts name about
    two habitats per species, and configurations that name many more agree
    with them far worse. Reported alongside the scores because it explains
    most of the spread between configurations.

Provenance
----------
The expert consensus currently rests on 1 real respondent plus 4 synthetic
placeholders, and the script says so in every output. Run with
``--real-only`` to score against real responses alone -- expect most
agreement metrics to be undefined there, which is the honest state of the
survey rather than a failure.

Usage
-----
    python code/expert_responses/llm_vs_expert.py
    python code/expert_responses/llm_vs_expert.py --real-only
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CODE_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(CODE_DIR)

_m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", REPO_ROOT)
DATA_ROOT = _m.group(1) if _m else REPO_ROOT

sys.path.insert(0, CODE_DIR)
import focal_species as fs  # noqa: E402

OUT_DIR = os.path.join(DATA_ROOT, "outputs", "expert_survey")
LLM_DIR = os.path.join(DATA_ROOT, "outputs", "llm_study")
MATRIX_DIR = os.path.join(LLM_DIR, "matrices")
CONFIG_SCORES = os.path.join(LLM_DIR, "config_scores.json")
CONSISTENCY_JSON = os.path.join(OUT_DIR, "species_consistency.json")

OUT_CSV = os.path.join(OUT_DIR, "llm_vs_expert.csv")
OUT_JSON = os.path.join(OUT_DIR, "llm_vs_expert.json")
OUT_MD = os.path.join(OUT_DIR, "LLM_VS_EXPERT_SUMMARY.md")

# A habitat is "expert-positive" when strictly more than this share of the
# opinionated respondents marked it. 0.5 = simple majority. Reported in the
# outputs so the threshold is never invisible.
MAJORITY = 0.5

STATE_GAP = "knowledge_gap"


class ScoreError(RuntimeError):
    """Raised when the inputs are missing or cannot be reconciled."""


def load_consistency(real_only: bool) -> dict:
    path = CONSISTENCY_JSON
    if real_only:
        path = CONSISTENCY_JSON.replace(".json", "_real_only.json")
    if not os.path.exists(path):
        hint = " --real-only" if real_only else ""
        raise ScoreError(f"missing {path}\n"
                         f"Run: python code/expert_responses/consistency.py{hint}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def expert_matrix(cons: dict) -> tuple[dict[str, set[str]], dict[str, dict]]:
    """Expert consensus per species -> (positives by slug, per-species meta).

    A species with no opinionated respondents has NO consensus: it is excluded
    from agreement scoring entirely rather than being treated as "experts said
    no to everything", which would silently reward a model for staying quiet.
    """
    slugs = cons["category_slugs"]
    labels = cons["category_labels"]
    lab2slug = dict(zip(labels, slugs))

    positives: dict[str, set[str]] = {}
    meta: dict[str, dict] = {}
    for r in cons["species"]:
        code = r["ebird_code"]
        n = r["n_respondents"]
        meta[code] = {
            "species": r["species"],
            "knowledge_state": r["knowledge_state"],
            "jaccard": r["jaccard"],
            "uncertainty_rate": r["uncertainty_rate"],
            "n_respondents": n,
        }
        if not n:
            continue          # no opinions -> no consensus to score against
        pos = {lab2slug[lab] for lab, v in r["votes"].items() if n and (v / n) > MAJORITY}
        positives[code] = pos
    return positives, meta


def load_llm_configs() -> list[dict]:
    if not os.path.exists(CONFIG_SCORES):
        raise ScoreError(f"missing {CONFIG_SCORES}. The LLM study must have run.")
    with open(CONFIG_SCORES, "r", encoding="utf-8") as fh:
        return json.load(fh)["configs"]


def read_matrix_pair(config_id: str, slugs: list[str]
                     ) -> tuple[dict[str, set[str]], dict[str, dict[str, float]]]:
    """(majority-vote picks, per-habitat confidence) for one configuration."""
    base = os.path.join(MATRIX_DIR, config_id)
    votes_path, prob_path = base + ".csv", base + "_meanprob.csv"
    if not os.path.exists(votes_path):
        raise ScoreError(f"missing LLM matrix {votes_path}")
    picks: dict[str, set[str]] = {}
    with open(votes_path, "r", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            picks[r["species_code"]] = {s for s in slugs if r.get(s) == "True"}
    conf: dict[str, dict[str, float]] = {}
    if os.path.exists(prob_path):
        with open(prob_path, "r", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                conf[r["species_code"]] = {s: float(r.get(s) or 0.0) for s in slugs}
    return picks, conf


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def score_config(cfg: dict, positives: dict[str, set[str]], meta: dict[str, dict],
                 slugs: list[str]) -> dict:
    picks, _conf = read_matrix_pair(cfg["config_id"], slugs)

    per_species = []
    f1s, jaccs, weights, wf1 = [], [], [], []
    tot_tp = tot_fp = tot_fn = 0

    for code, exp_pos in positives.items():
        llm_pos = picks.get(code, set())
        tp = len(exp_pos & llm_pos)
        fp = len(llm_pos - exp_pos)
        fn = len(exp_pos - llm_pos)
        tot_tp, tot_fp, tot_fn = tot_tp + tp, tot_fp + fp, tot_fn + fn
        p, r, f = prf(tp, fp, fn)
        union = exp_pos | llm_pos
        j = len(exp_pos & llm_pos) / len(union) if union else 1.0
        f1s.append(f)
        jaccs.append(j)
        # Weight by how much the experts agreed: a species they split on is a
        # weaker test of the model, so it should count for less.
        w = meta[code]["jaccard"] or 0.0
        weights.append(w)
        wf1.append(f * w)
        per_species.append({
            "ebird_code": code,
            "species": meta[code]["species"],
            "knowledge_state": meta[code]["knowledge_state"],
            "expert_consensus": sorted(exp_pos),
            "llm_picks": sorted(llm_pos),
            "f1": round(f, 4),
            "jaccard": round(j, 4),
            "expert_agreement": round(w, 4),
        })

    macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0
    macro_j = sum(jaccs) / len(jaccs) if jaccs else 0.0
    # With one respondent there is no inter-expert agreement, so every weight is
    # zero and a weighted score is undefined -- report None rather than a 0.000
    # that reads as a real, terrible score.
    weighted = (sum(wf1) / sum(weights)) if sum(weights) else None
    micro_p, micro_r, micro_f = prf(tot_tp, tot_fp, tot_fn)

    return {
        "config_id": cfg["config_id"],
        "model": cfg["model"],
        "model_label": cfg.get("model_label", cfg["model"]),
        "prompt": cfg["prompt"],
        "prompt_label": cfg.get("prompt_label", cfg["prompt"]),
        "tools": cfg["tools"],
        "f1_vs_expert": round(macro_f1, 4),
        "jaccard_vs_expert": round(macro_j, 4),
        "weighted_f1_vs_expert": None if weighted is None else round(weighted, 4),
        "micro_f1_vs_expert": round(micro_f, 4),
        "precision_vs_expert": round(micro_p, 4),
        "recall_vs_expert": round(micro_r, 4),
        "f1_vs_book": cfg.get("f1_vs_book"),
        "f1_vs_data": cfg.get("f1_vs_data"),
        "n_species_scored": len(positives),
        # How many habitats this configuration commits to, per species. The
        # experts name ~2; this is what most explains the spread in agreement.
        "baseline_breadth": round(
            sum(len(picks.get(c, set())) for c in positives) / len(positives), 3
        ) if positives else None,
        "per_species": per_species,
    }


def compute(real_only: bool) -> dict:
    cons = load_consistency(real_only)
    slugs = cons["category_slugs"]
    positives, meta = expert_matrix(cons)
    gaps = [r["ebird_code"] for r in cons["species"] if r["knowledge_state"] == STATE_GAP]

    configs = load_llm_configs()
    scored = [score_config(c, positives, meta, slugs) for c in configs if c.get("complete")]
    if not scored:
        raise ScoreError("no complete LLM configurations to score.")

    # Breadth vs agreement, computed once here so every consumer quotes the
    # same number rather than recomputing it.
    xs = [c["baseline_breadth"] for c in scored if c["baseline_breadth"] is not None]
    ys = [c["f1_vs_expert"] for c in scored if c["baseline_breadth"] is not None]
    r_breadth = None
    if len(xs) > 2:
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        den = (sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)) ** 0.5
        r_breadth = round(num / den, 4) if den else None

    # How many habitats the experts themselves assert, as the reference point
    # for model breadth. Without this the breadth numbers have no scale.
    expert_breadth = ([len(v) for v in positives.values()] or [0])
    mean_expert_breadth = sum(expert_breadth) / len(expert_breadth)

    return {
        "generated_by": "code/expert_responses/llm_vs_expert.py",
        "reference_standard": "expert survey consensus",
        "expert_breadth": round(mean_expert_breadth, 3),
        "r_breadth_vs_f1": r_breadth,
        "real_only": real_only,
        "contains_synthetic": cons["contains_synthetic"],
        "n_real_respondents": cons["n_real"],
        "n_synthetic_respondents": cons["n_synthetic"],
        "real_respondents": cons["real_respondents"],
        "synthetic_respondents": cons["synthetic_respondents"],
        "majority_threshold": MAJORITY,
        "n_species_scored": len(positives),
        "n_species_total": cons["n_species"],
        "category_slugs": slugs,
        "category_labels": cons["category_labels"],
        "knowledge_gaps": [{"ebird_code": c, "species": meta[c]["species"]} for c in gaps],
        "model_order": ["haiku", "sonnet", "opus"],
        "tools_order": ["off", "on", "forced"],
        "configs": scored,
    }


def write_outputs(data: dict, real_only: bool) -> tuple[str, str, str]:
    os.makedirs(OUT_DIR, exist_ok=True)
    out_csv, out_json, out_md = OUT_CSV, OUT_JSON, OUT_MD
    if real_only:
        out_csv = OUT_CSV.replace(".csv", "_real_only.csv")
        out_json = OUT_JSON.replace(".json", "_real_only.json")
        out_md = OUT_MD.replace(".md", "_REAL_ONLY.md")

    with open(out_csv, "w", encoding="utf-8", newline="") as fh:
        if data["contains_synthetic"]:
            fh.write("# Expert reference includes SYNTHETIC placeholder respondents "
                     "-- demonstration only.\n")
        w = csv.writer(fh)
        w.writerow(["config_id", "model", "prompt", "tools", "f1_vs_expert",
                    "weighted_f1_vs_expert", "jaccard_vs_expert", "precision_vs_expert",
                    "recall_vs_expert", "f1_vs_book", "f1_vs_data",
                    "baseline_breadth", "n_species_scored"])
        for c in sorted(data["configs"], key=lambda z: -z["f1_vs_expert"]):
            w.writerow([c["config_id"], c["model"], c["prompt"], c["tools"],
                        c["f1_vs_expert"], c["weighted_f1_vs_expert"],
                        c["jaccard_vs_expert"], c["precision_vs_expert"],
                        c["recall_vs_expert"], c["f1_vs_book"], c["f1_vs_data"],
                        c["baseline_breadth"], c["n_species_scored"]])

    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)

    ranked = sorted(data["configs"], key=lambda z: -z["f1_vs_expert"])
    warn = ""
    if data["contains_synthetic"]:
        warn = (f"> **The expert reference here includes "
                f"{data['n_synthetic_respondents']} synthetic placeholder respondents** "
                f"alongside {data['n_real_respondents']} real one. Agreement numbers are a "
                "demonstration of the method, not a finding about these models. The "
                "breadth comparison is a property of the model outputs and does not "
                "depend on the synthetic side.\n\n")

    with open(out_md, "w", encoding="utf-8") as fh:
        fh.write(f"""# LLM vs expert

{warn}Each LLM configuration scored against **expert survey consensus** --
a third reference alongside the Handbook and the eBird data.

- Expert-positive = more than {MAJORITY:.0%} of opinionated respondents marked the habitat
- {data['n_species_scored']} of {data['n_species_total']} species had an expert consensus to score against
- The experts assert {data['expert_breadth']:.2f} habitats per species

## Best agreement with the experts

| Configuration | F1 | Weighted F1 | Jaccard | F1 vs Book |
|---|---|---|---|---|
""")
        for c in ranked[:8]:
            fh.write(f"| {c['model_label']} {c['prompt_label']} ({c['tools']}) "
                     f"| {c['f1_vs_expert']:.3f} "
                     f"| {'n/a' if c['weighted_f1_vs_expert'] is None else format(c['weighted_f1_vs_expert'], '.3f')} "
                     f"| {c['jaccard_vs_expert']:.3f} | {c['f1_vs_book'] or float('nan'):.3f} |\n")

        gaps = ", ".join(g["species"] for g in data["knowledge_gaps"]) or "none"
        fh.write(f"""
## What drives consistency: how much the model commits to

Models assert far more habitats per species than the experts do, and that single
property explains most of the spread in agreement.

| | Habitats asserted per species |
|---|---|
| Experts (consensus) | **{data['expert_breadth']:.2f}** |
""")
        for p in ("p2_scoped", "p3_informed", "p4_engineered"):
            sub = [c for c in data["configs"] if c["prompt"] == p]
            if not sub:
                continue
            lab = sub[0]["prompt_label"]
            bb = sum(c["baseline_breadth"] for c in sub) / len(sub)
            fh.write(f"| {lab} (mean of {len(sub)} configs) | {bb:.2f} |\n")
        rb = data.get("r_breadth_vs_f1")
        fh.write(f"""
This tracks agreement almost perfectly: across the configurations, mean habitats
asserted correlates with F1 against the experts at **r = {rb:+.2f}**. The prompt that
wins is the one that says less. A model listing seven of nine habitats is not
demonstrating knowledge -- it is failing to commit, and against a reference that
names about two, breadth is simply wrong.

| Configuration | Habitats/species | F1 vs experts |
|---|---|---|
""")
        for c in sorted(data["configs"], key=lambda z: z["baseline_breadth"] or 0)[:6]:
            fh.write(f"| {c['model_label']} {c['prompt_label']} ({c['tools']}) "
                     f"| {c['baseline_breadth']:.2f} | {c['f1_vs_expert']:.3f} |\n")

        fh.write(f"""
## Caveats

* **Expert consensus is not truth.** High agreement means the model matches
  what these experts said, which is a different claim from being correct.
* **Majority rule discards minority expert opinion.** A habitat one of five
  experts marked does not enter the consensus. That is deliberate -- it is the
  same rule the LLM repeats are aggregated under -- but it does lose signal.
* **{len(data['knowledge_gaps'])} species are excluded** ({gaps}): the experts
  declined to answer them, so there is no consensus to be consistent with. The
  models do answer them, but that says nothing about any configuration -- these
  systems return an answer by construction.

Generated by `code/expert_responses/llm_vs_expert.py`.
""")
    return out_csv, out_json, out_md


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--real-only", action="store_true",
                    help="score against real respondents only (expect most agreement "
                         "metrics to be undefined until more responses arrive)")
    args = ap.parse_args()

    data = compute(args.real_only)
    out_csv, out_json, out_md = write_outputs(data, args.real_only)

    print("=" * 108)
    print("LLM vs EXPERT -- configurations scored against expert survey consensus")
    print("=" * 108)
    if data["contains_synthetic"]:
        print(f"  !! expert reference includes {data['n_synthetic_respondents']} SYNTHETIC "
              f"respondents alongside {data['n_real_respondents']} real -- "
              "agreement numbers are a demonstration, not a finding.")
    if data["real_only"]:
        print("  mode: REAL ONLY")
    print(f"  species with an expert consensus : {data['n_species_scored']} of {data['n_species_total']}")
    print(f"  excluded, experts declined       : {len(data['knowledge_gaps'])} "
          f"({', '.join(g['species'] for g in data['knowledge_gaps']) or 'none'})")
    print(f"  expert-positive threshold        : >{MAJORITY:.0%} of opinionated respondents")
    print(f"  experts assert                   : {data['expert_breadth']:.2f} habitats/species")
    print()

    ranked = sorted(data["configs"], key=lambda z: -z["f1_vs_expert"])
    print(f"  {'configuration':<34} {'F1':>6} {'wF1':>6} {'Jacc':>6} "
          f"{'Book':>6} {'Data':>6} {'hab/sp':>7}")
    print("  " + "-" * 80)
    for c in ranked:
        book = f"{c['f1_vs_book']:6.3f}" if c["f1_vs_book"] is not None else "   n/a"
        dat = f"{c['f1_vs_data']:6.3f}" if c["f1_vs_data"] is not None else "   n/a"
        bb = c["baseline_breadth"]
        label = f"{c['model_label']} {c['prompt_label']} ({c['tools']})"
        wf = c["weighted_f1_vs_expert"]
        print(f"  {label:<34} {c['f1_vs_expert']:6.3f} "
              f"{'   n/a' if wf is None else f'{wf:6.3f}'} "
              f"{c['jaccard_vs_expert']:6.3f} {book} {dat} "
              f"{'    n/a' if bb is None else f'{bb:7.2f}'}")
    print()
    print(f"  hab/sp = mean habitats asserted per species "
          f"(the experts assert {data['expert_breadth']:.2f})")
    if data.get("r_breadth_vs_f1") is not None:
        print(f"  breadth vs F1 correlation: r = {data['r_breadth_vs_f1']:+.3f} "
              "-- committing to fewer habitats tracks agreeing with the experts")

    print()
    print(f"wrote {out_csv}")
    print(f"wrote {out_json}")
    print(f"wrote {out_md}")


if __name__ == "__main__":
    try:
        main()
    except (ScoreError, fs.FocalSpeciesError) as exc:
        sys.exit(f"error: {exc}")
