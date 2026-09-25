#!/usr/bin/env python3
"""consistency.py  --  per-species inter-expert agreement
========================================================

How much do the surveyed experts AGREE with each other about a species'
habitats? This is an EXPERT-ONLY view: no eBird data, no RSPB Handbook, no
LLM. It answers "which species are clear-cut and which are contested among
the people who know them", which is a prerequisite for reading any later
LLM-vs-expert or data-vs-expert comparison -- a model disagreeing with the
experts means something different on a species the experts themselves split
on.

Input is the species x respondent matrix produced by ``tidy_responses.py``
(or that matrix with synthetic placeholders appended -- see
``make_synthetic_respondents.py``). The metric code neither knows nor cares
how many respondents there are, so it runs unchanged as real responses
replace the synthetic ones.

Metrics, per species
--------------------
``pairwise_agreement``
    Mean over all respondent pairs of the fraction of the 9 categories the
    pair answers identically (both ticked, or both left blank). This is raw
    agreement over a 9-cell boolean vector.

    CAVEAT -- base rate. Experts tick ~2 of 9 categories, so ~7 cells are
    shared "no"s. Two respondents who agree on nothing still score ~0.5
    here just by both saying "not woodland, not arable, ...". Read it with
    ``jaccard``, never alone.

``jaccard``
    Mean over respondent pairs of |A n B| / |A u B| on the habitats each
    marked PRESENT. Shared absences are ignored, so it is not inflated by
    the base rate. Two respondents with no habitat in common score 0 no
    matter how many categories they both declined. This is the honest
    headline; ``pairwise_agreement`` is the familiar-looking companion.

``dice``
    2|A n B| / (|A| + |B|), reported alongside Jaccard. More forgiving when
    respondents tick different NUMBERS of habitats.

``uncertainty_rate``
    Fraction of respondents answering "I don't know" for that species.
    Those respondents are excluded from the agreement metrics, because
    "I don't know" is an absence of an opinion, not an opinion that
    disagrees: folding it in as an empty answer vector would score it as
    agreeing with every other blank cell and silently inflate consensus on
    exactly the species people are least sure about.

    Excluded from agreement is NOT the same as discarded. Uncertainty is a
    measurement in its own right -- it locates where expert knowledge runs
    out -- so it is reported as a second axis, not a footnote.

``knowledge_state``
    Consensus and uncertainty are INDEPENDENT. Collapsing them to a single
    "consistency" ranking loses the distinction the survey exists to
    capture, because these two score alike and mean opposite things:

        Disputed       experts answered confidently and disagree
                       -> a live disagreement about the species
        Knowledge gap  too few experts would answer at all
                       -> a measured absence of expert knowledge

    Each species is placed on the consensus x uncertainty grid as one of
    Settled / Disputed / Uncertain / Knowledge gap. A species nobody would
    answer is a FINDING, and is named as one rather than dropped from the
    ranking with an em dash.

``per_respondent``
    Abstention is a respondent-level trait too: an expert who answers "I
    don't know" freely and one who never does carry different information,
    which a species-level rate alone hides.

``votes``
    Per-habitat counts: how many opinionated respondents ticked each of the
    9 categories. This is where disagreement becomes legible -- a species
    can score mid-range because everyone is mildly split, or because two
    camps each vote solidly for a different habitat, and only the vote
    breakdown separates those.

Validation
----------
With synthetic respondents the consensus gradient is KNOWN by construction
(flip rate rises across the canonical species order). ``--validate`` checks
the recovered ranking against that design: high-consensus species must land
near the top. The check is skipped automatically on real-only data, where no
ground truth exists.

Usage
-----
    python code/expert_responses/consistency.py            # auto-picks input
    python code/expert_responses/consistency.py --real-only # drop SYNTHETIC_ cols
    python code/expert_responses/consistency.py --input PATH
    python code/expert_responses/consistency.py --no-validate

``--real-only`` analyses just the real responses, whatever the input contains.
Synthetic columns are dropped when the matrix is read, so no metric can see
them, and the outputs are written to ``*_real_only.*`` so a one-respondent real
run can never silently overwrite the demonstration outputs the dashboard is
built from. Expect most metrics to be undefined until several real responses
have arrived -- that is the honest answer, not a failure.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from itertools import combinations

HERE = os.path.dirname(os.path.abspath(__file__))
CODE_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(CODE_DIR)

_m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", REPO_ROOT)
DATA_ROOT = _m.group(1) if _m else REPO_ROOT

sys.path.insert(0, CODE_DIR)
import focal_species as fs  # noqa: E402

CATEGORIES_JSON = os.path.join(CODE_DIR, "llm_study", "categories.json")
OUT_DIR = os.path.join(DATA_ROOT, "outputs", "expert_survey")
SYNTHETIC_INPUT = os.path.join(OUT_DIR, "consistency_input_WITH_SYNTHETIC.csv")
REAL_INPUT = os.path.join(HERE, "tidy", "expert_responses_wide.csv")

OUT_CSV = os.path.join(OUT_DIR, "species_consistency.csv")
OUT_JSON = os.path.join(OUT_DIR, "species_consistency.json")
OUT_MD = os.path.join(OUT_DIR, "CONSISTENCY_SUMMARY.md")

SYNTHETIC_PREFIX = "SYNTHETIC_"
DONT_KNOW = "I don't know"

# Agreement needs at least one pair of opinionated respondents.
MIN_RESPONDENTS = 2

# Thresholds for the knowledge-state classification below. Deliberately round
# numbers rather than tuned ones: with a handful of respondents any precision
# here would be spurious. They are reported on the dashboard so a reader can
# see where the boundaries sit.
# Any abstention at all marks a species as carrying uncertainty. With a handful
# of respondents the observed rates are coarse (at n=5 they jump 0.20 -> 0.80,
# so a mid-range cut has nothing to land on), and a single expert declining to
# answer is itself the signal worth surfacing. Raise this once there are enough
# respondents for the rate to be continuous.
UNCERTAIN_AT = 0.15      # >= this share abstaining reads as "experts unsure"
CONSENSUS_AT = 0.50      # >= this mean Jaccard reads as "experts agree"

# The four knowledge states. Consensus and uncertainty are INDEPENDENT axes,
# and collapsing them loses the distinction the survey exists to capture:
# experts confidently disagreeing is a live scientific dispute, whereas experts
# abstaining is an absence of knowledge. Both score "low agreement" and mean
# entirely different things.
STATE_SETTLED = "settled"            # high consensus, low uncertainty
STATE_DISPUTED = "disputed"          # low consensus, low uncertainty  -> real disagreement
STATE_GAP = "knowledge_gap"          # nobody (or almost nobody) would answer
STATE_UNSURE = "uncertain"           # mixed: some abstained, the rest split
STATE_UNSCORED = "unscored"          # too few respondents to compare, but not a gap

STATE_LABELS = {
    STATE_SETTLED: "Settled",
    STATE_DISPUTED: "Disputed",
    STATE_UNSURE: "Uncertain",
    STATE_GAP: "Knowledge gap",
    STATE_UNSCORED: "Too few to compare",
}
STATE_ORDER = [STATE_SETTLED, STATE_DISPUTED, STATE_UNSURE, STATE_GAP, STATE_UNSCORED]
STATE_NOTES = {
    STATE_SETTLED: "Experts agree and are willing to answer.",
    STATE_DISPUTED: "Experts answered confidently but disagree — a live "
                    "disagreement, not an absence of knowledge.",
    STATE_UNSURE: "Some experts abstained and those who answered did not "
                  "converge.",
    STATE_GAP: "Experts declined to answer. Not a missing measurement — a "
               "measured absence of expert knowledge.",
    STATE_UNSCORED: "Fewer than two experts expressed a view, so agreement "
                    "cannot be computed. Says nothing about the species.",
}


def classify(jaccard: float | None, uncertainty: float, n_used: int) -> str:
    """Place a species on the consensus x uncertainty grid.

    A species experts DECLINED to answer is a FINDING (knowledge gap), not a
    row to drop -- that is why this returns a state rather than letting an
    unscorable species fall out of the analysis.

    But "unscorable" and "knowledge gap" are not the same thing, and must not
    be conflated: with a single respondent every species is unscorable while
    almost none is a gap. A gap requires experts to have actually abstained.
    """
    if n_used < MIN_RESPONDENTS:
        # Abstention is what makes it a gap; too few respondents to pair off is
        # a limitation of the sample, not a statement about the species.
        return STATE_GAP if uncertainty >= UNCERTAIN_AT else STATE_UNSCORED
    if uncertainty >= UNCERTAIN_AT:
        return STATE_UNSURE
    if jaccard is not None and jaccard >= CONSENSUS_AT:
        return STATE_SETTLED
    return STATE_DISPUTED


class ConsistencyError(RuntimeError):
    """Raised when the input matrix cannot be read or is unusable."""


def load_categories() -> tuple[list[str], list[str]]:
    with open(CATEGORIES_JSON, "r", encoding="utf-8") as fh:
        cats = json.load(fh)["categories"]
    return [c["slug"] for c in cats], [c["label"] for c in cats]


def split_habitats(raw: str, labels: list[str]) -> tuple[set[str], bool]:
    """Answer cell -> (labels present, dont_know). Longest-first, as the tidier."""
    text = (raw or "").strip()
    if not text:
        return set(), False
    dont_know = DONT_KNOW.lower() in text.lower()
    if dont_know:
        text = re.sub(re.escape(DONT_KNOW), "", text, flags=re.I)
    found: set[str] = set()
    for lab in sorted(labels, key=len, reverse=True):
        if lab.lower() in text.lower():
            found.add(lab)
            text = re.sub(re.escape(lab), "", text, flags=re.I)
    leftover = [t for t in re.split(r"[,]", text) if t.strip()]
    if leftover:
        raise ConsistencyError(
            f"unrecognised habitat label(s) {leftover} in {raw!r}. The 9 categories "
            "are frozen in llm_study/categories.json."
        )
    return found, dont_know


def pick_input(explicit: str | None) -> str:
    if explicit:
        if not os.path.exists(explicit):
            raise ConsistencyError(f"input not found: {explicit}")
        return explicit
    # Prefer the synthetic-augmented matrix while it exists; fall back to the
    # real tidied matrix, so deleting the synthetic file is all it takes to
    # switch the analysis onto real data only.
    if os.path.exists(SYNTHETIC_INPUT):
        return SYNTHETIC_INPUT
    if os.path.exists(REAL_INPUT):
        return REAL_INPUT
    raise ConsistencyError(
        "no input matrix found. Run:\n"
        "  python code/expert_responses/tidy_responses.py\n"
        "and optionally:\n"
        "  python code/expert_responses/make_synthetic_respondents.py"
    )


def read_matrix(path: str, labels: list[str], real_only: bool = False
                ) -> tuple[list[str], dict[str, list[tuple[set[str], bool]]]]:
    """Read species x respondent -> (respondent columns, {code: [(picks, dk)]}).

    ``real_only`` drops every SYNTHETIC_ column at the point of reading, so no
    downstream metric has to know synthetic respondents ever existed. Filtering
    here rather than per-metric is deliberate: it means there is no code path
    by which a fabricated answer can reach a "real only" result.
    """
    with open(path, "r", encoding="utf-8", newline="") as fh:
        # Skip the '#' banner the synthetic writer prepends.
        lines = [ln for ln in fh if not ln.startswith("#")]
    rows = list(csv.reader(lines))
    if not rows:
        raise ConsistencyError(f"{path} is empty.")
    header, body = rows[0], rows[1:]
    cols = header[2:]
    if not cols:
        raise ConsistencyError(f"{path} has no respondent columns.")

    keep = list(range(len(cols)))
    if real_only:
        keep = [i for i, c in enumerate(cols) if not c.startswith(SYNTHETIC_PREFIX)]
        if not keep:
            raise ConsistencyError(
                f"--real-only leaves no respondents: every column in {path} is "
                "synthetic. Run tidy_responses.py to produce a real matrix."
            )
        cols = [cols[i] for i in keep]

    out: dict[str, list[tuple[set[str], bool]]] = {}
    for r in body:
        if not r or not r[0].strip():
            continue
        r = r + [""] * (len(header) - len(r))
        out[r[0]] = [split_habitats(r[2 + i], labels) for i in keep]
    return cols, out


def metrics_for(answers: list[tuple[set[str], bool]], labels: list[str]) -> dict:
    """Per-species metrics from one species' list of (picks, dont_know)."""
    n_total = len(answers)
    n_dk = sum(1 for _, dk in answers if dk)
    # Opinionated = expressed a view. "I don't know" is excluded here and
    # counted only in uncertainty_rate.
    opinions = [p for p, dk in answers if not dk and p]
    n_used = len(opinions)

    votes = {lab: sum(1 for p in opinions if lab in p) for lab in labels}

    unc = (n_dk / n_total) if n_total else 0.0

    if n_used < MIN_RESPONDENTS:
        return {
            "pairwise_agreement": None,
            "jaccard": None,
            "dice": None,
            "n_respondents": n_used,
            "n_dont_know": n_dk,
            "n_total": n_total,
            "uncertainty_rate": unc,
            "votes": votes,
            "n_pairs": 0,
            "knowledge_state": classify(None, unc, n_used),
        }

    agrees, jaccs, dices = [], [], []
    for a, b in combinations(opinions, 2):
        same = sum(1 for lab in labels if (lab in a) == (lab in b))
        agrees.append(same / len(labels))
        union = a | b
        inter = a & b
        jaccs.append(len(inter) / len(union) if union else 1.0)
        denom = len(a) + len(b)
        dices.append(2 * len(inter) / denom if denom else 1.0)

    jac = sum(jaccs) / len(jaccs)
    return {
        "pairwise_agreement": sum(agrees) / len(agrees),
        "jaccard": jac,
        "dice": sum(dices) / len(dices),
        "n_respondents": n_used,
        "n_dont_know": n_dk,
        "n_total": n_total,
        "uncertainty_rate": unc,
        "votes": votes,
        "n_pairs": len(agrees),
        "knowledge_state": classify(jac, unc, n_used),
    }


def compute(path: str, real_only: bool = False) -> dict:
    slugs, labels = load_categories()
    cols, matrix = read_matrix(path, labels, real_only=real_only)
    species = fs.load_species()

    synthetic = [c for c in cols if c.startswith(SYNTHETIC_PREFIX)]
    real = [c for c in cols if not c.startswith(SYNTHETIC_PREFIX)]

    rows = []
    for rank, s in enumerate(species):
        code = s["ebird_code"]
        answers = matrix.get(code)
        if answers is None:
            raise ConsistencyError(
                f"species {code} ({s.get('common_name')}) is missing from {path}. "
                "The matrix must cover all 41 canonical species."
            )
        m = metrics_for(answers, labels)
        m.update({
            "ebird_code": code,
            "species": s.get("red_list_name") or s.get("common_name", ""),
            "canonical_rank": rank,
        })
        rows.append(m)

    # Abstention is also a RESPONDENT-level trait, not only a species-level one:
    # one expert who answers "I don't know" freely and one who never does carry
    # different information, and a species-level rate alone hides that.
    per_respondent = []
    for i, col in enumerate(cols):
        n_dk = sum(1 for code in (s["ebird_code"] for s in species)
                   if matrix.get(code) and matrix[code][i][1])
        n_ans = sum(1 for code in (s["ebird_code"] for s in species)
                    if matrix.get(code) and matrix[code][i][0])
        picks = [len(matrix[code][i][0]) for code in (s["ebird_code"] for s in species)
                 if matrix.get(code) and matrix[code][i][0]]
        per_respondent.append({
            "respondent": col,
            "is_synthetic": col.startswith(SYNTHETIC_PREFIX),
            "n_dont_know": n_dk,
            "n_answered": n_ans,
            "abstention_rate": n_dk / len(species) if species else 0.0,
            "mean_habitats_per_species": (sum(picks) / len(picks)) if picks else 0.0,
        })

    state_counts = {st: sum(1 for r in rows if r["knowledge_state"] == st)
                    for st in STATE_ORDER}

    return {
        "generated_from": os.path.relpath(path, DATA_ROOT),
        "real_only": real_only,
        "respondents": cols,
        "real_respondents": real,
        "synthetic_respondents": synthetic,
        "n_respondents": len(cols),
        "n_real": len(real),
        "n_synthetic": len(synthetic),
        "contains_synthetic": bool(synthetic),
        "category_slugs": slugs,
        "category_labels": labels,
        "n_species": len(rows),
        "species": rows,
        "per_respondent": per_respondent,
        "state_counts": state_counts,
        "state_order": STATE_ORDER,
        "state_labels": STATE_LABELS,
        "state_notes": STATE_NOTES,
        "thresholds": {"uncertain_at": UNCERTAIN_AT, "consensus_at": CONSENSUS_AT},
        "mean_uncertainty": (sum(r["uncertainty_rate"] for r in rows) / len(rows)) if rows else 0.0,
    }


def validate(data: dict) -> tuple[bool, list[str]]:
    """Check the recovered ranking against the DESIGNED consensus gradient.

    The synthetic generator raises the flip rate linearly across the canonical
    species order, so consistency should fall as canonical_rank rises. If it
    does not, the metric is not measuring agreement and every number on the
    dashboard is suspect.
    """
    msgs: list[str] = []
    scored = [r for r in data["species"] if r["jaccard"] is not None]
    if not data["contains_synthetic"]:
        msgs.append("SKIPPED: no synthetic respondents, so there is no designed "
                    "gradient to validate against. Metrics are reported as-is.")
        return True, msgs
    if len(scored) < 4:
        msgs.append("SKIPPED: too few scored species to validate.")
        return True, msgs

    n = len(scored)
    third = max(1, n // 3)
    by_rank = sorted(scored, key=lambda r: r["canonical_rank"])
    designed_high = by_rank[:third]      # built to agree
    designed_low = by_rank[-third:]      # built to be contested

    hi = sum(r["jaccard"] for r in designed_high) / len(designed_high)
    lo = sum(r["jaccard"] for r in designed_low) / len(designed_low)

    # Spearman between canonical rank and consistency: should be strongly negative.
    def ranks(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        out = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    xs = ranks([r["canonical_rank"] for r in scored])
    ys = ranks([r["jaccard"] for r in scored])
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = (sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)) ** 0.5
    rho = num / den if den else 0.0

    ok_gap = hi > lo
    ok_rho = rho < -0.5
    msgs.append(f"designed-consensus third  mean Jaccard = {hi:.3f}")
    msgs.append(f"designed-contested third  mean Jaccard = {lo:.3f}")
    msgs.append(f"gap (should be positive)                = {hi - lo:+.3f}   "
                f"[{'PASS' if ok_gap else 'FAIL'}]")
    msgs.append(f"Spearman rho(canonical rank, Jaccard)   = {rho:+.3f}   "
                f"(expect strongly negative) [{'PASS' if ok_rho else 'FAIL'}]")

    # The top of the table should be species built to agree, not contested ones.
    top5 = sorted(scored, key=lambda r: -r["jaccard"])[:5]
    bot5 = sorted(scored, key=lambda r: r["jaccard"])[:5]
    top_from_high = sum(1 for r in top5 if r["canonical_rank"] < n / 2)
    bot_from_low = sum(1 for r in bot5 if r["canonical_rank"] >= n / 2)
    ok_top = top_from_high >= 4
    ok_bot = bot_from_low >= 4
    msgs.append(f"top-5 consensus species drawn from the agreeing half: "
                f"{top_from_high}/5 [{'PASS' if ok_top else 'FAIL'}]")
    msgs.append(f"bottom-5 species drawn from the contested half:       "
                f"{bot_from_low}/5 [{'PASS' if ok_bot else 'FAIL'}]")

    return all([ok_gap, ok_rho, ok_top, ok_bot]), msgs


def write_outputs(data: dict, real_only: bool = False) -> tuple[str, str, str]:
    os.makedirs(OUT_DIR, exist_ok=True)
    labels = data["category_labels"]

    # A real-only run writes to its own files. Sharing filenames would let a
    # 1-respondent real run silently replace the demonstration outputs the
    # dashboard is built from (or the reverse), which is exactly the confusion
    # the synthetic labelling exists to prevent.
    out_csv, out_json, out_md = (OUT_CSV, OUT_JSON, OUT_MD)
    if real_only:
        out_csv = OUT_CSV.replace(".csv", "_real_only.csv")
        out_json = OUT_JSON.replace(".json", "_real_only.json")
        out_md = OUT_MD.replace(".md", "_REAL_ONLY.md")
    with open(out_csv, "w", encoding="utf-8", newline="") as fh:
        if data["contains_synthetic"]:
            fh.write("# CONTAINS SYNTHETIC PLACEHOLDER RESPONDENTS -- "
                     "demonstration only, not real results.\n"
                     f"# real: {', '.join(data['real_respondents'])} | "
                     f"synthetic: {', '.join(data['synthetic_respondents'])}\n")
        w = csv.writer(fh)
        w.writerow(["ebird_code", "species", "knowledge_state", "pairwise_agreement",
                    "jaccard", "dice", "uncertainty_rate", "n_respondents",
                    "n_dont_know", "n_pairs"]
                   + [f"votes_{l}" for l in labels])
        for r in sorted(data["species"], key=lambda z: (z["jaccard"] is None, -(z["jaccard"] or 0))):
            w.writerow([
                r["ebird_code"], r["species"], r["knowledge_state"],
                "" if r["pairwise_agreement"] is None else f"{r['pairwise_agreement']:.4f}",
                "" if r["jaccard"] is None else f"{r['jaccard']:.4f}",
                "" if r["dice"] is None else f"{r['dice']:.4f}",
                f"{r['uncertainty_rate']:.4f}", r["n_respondents"], r["n_dont_know"], r["n_pairs"],
            ] + [r["votes"][l] for l in labels])

    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)

    scored = [r for r in data["species"] if r["jaccard"] is not None]
    ranked = sorted(scored, key=lambda r: -r["jaccard"])
    mean_j = sum(r["jaccard"] for r in scored) / len(scored) if scored else 0.0
    mean_a = sum(r["pairwise_agreement"] for r in scored) / len(scored) if scored else 0.0
    unsure = [r for r in data["species"] if r["uncertainty_rate"] > 0]

    warn = ""
    if data["contains_synthetic"]:
        warn = (f"> **These numbers include {data['n_synthetic']} SYNTHETIC placeholder "
                f"respondents** alongside {data['n_real']} real one"
                f"({'s' if data['n_real'] != 1 else ''}). They demonstrate the pipeline; "
                "they are not findings. See `README_SYNTHETIC.md`.\n\n")

    with open(out_md, "w", encoding="utf-8") as fh:
        fh.write(f"""# Expert consistency summary

{warn}How much do respondents agree with each other about each species' habitats?
Expert-only: no eBird data, no Handbook, no LLM.

**Respondents:** {data['n_respondents']} ({data['n_real']} real, {data['n_synthetic']} synthetic)
**Species:** {data['n_species']}
**Source:** `{data['generated_from']}`

## Headline

| Metric | Mean across species |
|---|---|
| Jaccard (habitats marked present) | **{mean_j:.3f}** |
| Pairwise agreement (all 9 cells) | {mean_a:.3f} |

Read **Jaccard** as the headline. Pairwise agreement counts the ~7 categories
both respondents leave blank, so it starts around 0.5 even for respondents who
share no habitat at all. The two columns diverging is the signal that raw
agreement is being carried by shared absences.

## Most agreed

| Species | Jaccard | Pairwise | Respondents |
|---|---|---|---|
""")
        for r in ranked[:8]:
            fh.write(f"| {r['species']} | {r['jaccard']:.3f} | "
                     f"{r['pairwise_agreement']:.3f} | {r['n_respondents']} |\n")
        fh.write("\n## Most contested\n\n| Species | Jaccard | Pairwise | Respondents |\n|---|---|---|---|\n")
        for r in ranked[-8:][::-1]:
            fh.write(f"| {r['species']} | {r['jaccard']:.3f} | "
                     f"{r['pairwise_agreement']:.3f} | {r['n_respondents']} |\n")
        gaps = [r for r in data["species"] if r["knowledge_state"] == STATE_GAP]
        disputed = [r for r in data["species"] if r["knowledge_state"] == STATE_DISPUTED]
        fh.write(f"""
## Knowledge state

Consensus and uncertainty are independent axes. Collapsing them into one
ranking loses the distinction this survey exists to capture: **disputed**
species (experts answered and disagree) and **knowledge gaps** (experts would
not answer) both score low and mean opposite things.

| State | Species | Meaning |
|---|---|---|
""")
        for st in STATE_ORDER:
            fh.write(f"| {STATE_LABELS[st]} | {data['state_counts'][st]} | {STATE_NOTES[st]} |\n")
        fh.write(f"""
Split at Jaccard {CONSENSUS_AT:.2f} and {UNCERTAIN_AT:.0%} abstaining. With few
respondents the observed abstention rates are coarse, so the uncertainty
threshold is deliberately low -- one expert declining to answer is itself the
signal. Raise it once the rate is continuous.

**Knowledge gaps ({len(gaps)}):** {', '.join(r['species'] for r in gaps) or 'none'}.
These are a measured result about where expert knowledge runs out, not rows with
missing data. They are the species where a confident model answer would be
hardest to check against human expertise -- which makes them the most
informative species in any later LLM comparison, not the least.

**Disputed ({len(disputed)}):** experts answered but did not converge. Unlike a
gap, the knowledge exists and is contested.

## Uncertainty

{len(unsure)} species drew at least one "I don't know". Those respondents are
excluded from the agreement metrics -- "I don't know" is the absence of an
opinion, not an opinion that disagrees, and treating it as an empty answer would
score it as agreeing with every other blank cell and inflate consensus on
exactly the species people are least sure about.

Excluded from scoring is not discarded: uncertainty is reported as its own axis
above, and per respondent below.

""")
        if unsure:
            fh.write("| Species | Uncertainty rate | Opinionated respondents |\n|---|---|---|\n")
            for r in sorted(unsure, key=lambda z: -z["uncertainty_rate"]):
                fh.write(f"| {r['species']} | {r['uncertainty_rate']:.2f} | {r['n_respondents']} |\n")
        fh.write("\n## Who abstains\n\nAbstention is a respondent-level trait as "
                 "well as a species-level one.\n\n"
                 "| Respondent | Abstained | Rate | Mean habitats/species |\n|---|---|---|---|\n")
        for pr in data["per_respondent"]:
            tag = " *(synthetic)*" if pr["is_synthetic"] else ""
            fh.write(f"| {pr['respondent']}{tag} | {pr['n_dont_know']} of {data['n_species']} "
                     f"| {pr['abstention_rate']:.0%} | {pr['mean_habitats_per_species']:.2f} |\n")
        fh.write("""
## Caveats

* **Base rate.** With 9 categories and ~2 ticked per species, raw agreement is
  dominated by shared "no"s. Jaccard and Dice ignore those.
* **Small n.** Every metric here is a mean over respondent pairs. With few
  respondents a single unusual answer moves a species a long way.
* **Not a truth claim.** High consensus means the experts agree, not that they
  are right. Comparing expert consensus against the data or the Handbook is a
  separate question, deliberately left to a later view.

Generated by `code/expert_responses/consistency.py`.
""")

    return out_csv, out_json, out_md


def print_table(data: dict) -> None:
    rows = sorted(data["species"], key=lambda r: (r["jaccard"] is None, -(r["jaccard"] or 0)))
    print()
    print(f"{'#':>3}  {'species':<24} {'state':<14} {'jaccard':>8} {'dice':>7} "
          f"{'pairwise':>9} {'unsure':>7} {'n':>3}  top habitats (votes)")
    print("-" * 128)
    for i, r in enumerate(rows, 1):
        j = "  n/a  " if r["jaccard"] is None else f"{r['jaccard']:7.3f}"
        d = "  n/a " if r["dice"] is None else f"{r['dice']:6.3f}"
        p = "   n/a  " if r["pairwise_agreement"] is None else f"{r['pairwise_agreement']:8.3f}"
        top = sorted(r["votes"].items(), key=lambda kv: -kv[1])
        top = [f"{k} {v}" for k, v in top if v > 0][:3]
        st = STATE_LABELS.get(r["knowledge_state"], r["knowledge_state"])
        print(f"{i:>3}  {r['species'][:24]:<24} {st:<14} {j} {d} {p} "
              f"{r['uncertainty_rate']:7.2f} {r['n_respondents']:>3}  {', '.join(top)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", help="species x respondent matrix (default: synthetic if present, else real)")
    ap.add_argument("--no-validate", dest="validate", action="store_false",
                    help="skip the designed-gradient validation check")
    ap.add_argument("--real-only", action="store_true",
                    help="drop every SYNTHETIC_ respondent and analyse only real "
                         "responses. Writes *_real_only.{csv,json,md} so the "
                         "demonstration outputs are never overwritten.")
    args = ap.parse_args()

    path = pick_input(args.input)
    data = compute(path, real_only=args.real_only)
    out_csv, out_json, out_md = write_outputs(data, real_only=args.real_only)

    print("=" * 118)
    print("EXPERT CONSISTENCY -- per-species inter-expert agreement")
    print("=" * 118)
    print(f"input       : {path}")
    if data.get("real_only"):
        print("mode        : REAL ONLY -- synthetic respondents dropped at read time")
    print(f"respondents : {data['n_respondents']} "
          f"({data['n_real']} real: {', '.join(data['real_respondents'])})")
    if data["contains_synthetic"]:
        print(f"              {data['n_synthetic']} SYNTHETIC (fabricated placeholders, "
              "NOT real): " + ", ".join(data["synthetic_respondents"]))
        print()
        print("  !! Results below include fabricated respondents and are for pipeline")
        print("     demonstration only. They are not expert findings.")
    print_table(data)

    # Uncertainty gets its own reporting block. It is a result about the state
    # of expert knowledge, not bookkeeping about which rows could be scored.
    print()
    print("=" * 128)
    print("KNOWLEDGE STATE -- consensus and uncertainty are independent axes")
    print("=" * 128)
    th = data["thresholds"]
    print(f"  thresholds: uncertain at >= {th['uncertain_at']:.0%} abstaining, "
          f"consensus at >= {th['consensus_at']:.2f} mean Jaccard")
    for st in data["state_order"]:
        n = data["state_counts"][st]
        members = [r["species"] for r in data["species"] if r["knowledge_state"] == st]
        shown = ", ".join(members[:6]) + (" ..." if len(members) > 6 else "")
        print(f"  {STATE_LABELS[st]:<14} {n:>3} species   {shown}")
    print()
    print(f"  {STATE_LABELS[STATE_DISPUTED]} vs {STATE_LABELS[STATE_GAP]} is the "
          "distinction a bare consistency ranking loses:")
    print(f"    - {STATE_LABELS[STATE_DISPUTED]}: {STATE_NOTES[STATE_DISPUTED]}")
    print(f"    - {STATE_LABELS[STATE_GAP]}: {STATE_NOTES[STATE_GAP]}")

    print()
    width = max(24, max(len(pr["respondent"]) for pr in data["per_respondent"]) + 12)
    print(f"  {'respondent':<{width}} {'abstained':>10} {'rate':>7} {'mean habitats/sp':>18}")
    print("  " + "-" * (width + 38))
    for pr in data["per_respondent"]:
        tag = " [SYNTHETIC]" if pr["is_synthetic"] else ""
        print(f"  {pr['respondent'] + tag:<{width}} "
              f"{pr['n_dont_know']:>10} {pr['abstention_rate']:>6.0%} "
              f"{pr['mean_habitats_per_species']:>18.2f}")

    if args.validate:
        ok, msgs = validate(data)
        print()
        print("=" * 118)
        print("VALIDATION -- does the metric recover the DESIGNED consensus gradient?")
        print("=" * 118)
        for m in msgs:
            print("  " + m)
        print()
        # A skipped check has nothing to report. Printing "PASS" when no
        # comparison ran would assert a validation that never happened.
        ran = not any(m.startswith("SKIPPED") for m in msgs)
        if ran:
            print("  RESULT: " + ("PASS -- the metric ranks the species as designed."
                                  if ok else
                                  "FAIL -- the metric does not recover the designed gradient."))
        else:
            print("  RESULT: n/a -- no validation performed.")
        if not ok:
            sys.exit(1)

    print()
    print(f"wrote {out_csv}")
    print(f"wrote {out_json}")
    print(f"wrote {out_md}")


if __name__ == "__main__":
    try:
        main()
    except (ConsistencyError, fs.FocalSpeciesError) as exc:
        sys.exit(f"error: {exc}")
