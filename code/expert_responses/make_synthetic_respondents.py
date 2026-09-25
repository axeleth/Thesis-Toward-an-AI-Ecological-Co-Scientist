#!/usr/bin/env python3
"""make_synthetic_respondents.py  --  FABRICATED placeholder respondents
=======================================================================

!!  EVERY RESPONDENT THIS SCRIPT PRODUCES IS FAKE.  !!

The expert survey has ONE real response so far (Expert A). One
respondent cannot disagree with anyone, so every inter-expert agreement
metric is undefined on the real data alone. To build and demo the
consistency analysis before the real responses arrive, this script
fabricates 4 extra respondents with a KNOWN, DESIGNED consensus gradient.

They exist to prove the metric behaves, nothing else. They are:

  * **labelled** -- every synthetic column name starts with ``SYNTHETIC_``,
    which the analysis and the dashboard both key off to mark them.
  * **isolated** -- written only to ``consistency_input_WITH_SYNTHETIC.csv``,
    whose name and header say so. The tidier's own outputs are never touched.
  * **removable** -- delete that one file (and this script) and nothing real
    is lost. ``consistency.py`` reads whatever respondent columns it finds,
    so when real people reply it runs unchanged on the real matrix.

How the gradient is built
-------------------------
Each synthetic respondent starts from the real respondent's 9-category
answer vector for a species and flips a controlled number of those cells.
The flip probability is driven by the species' position in the canonical
41-species order, so the set spans a designed consensus gradient:

    rank 0  ->  p_flip = 0.00   (perfect consensus: nobody deviates)
    rank 40 ->  p_flip = 0.42   (heavily contested)

That gradient is the ground truth Part B validates against: species early
in the canonical order MUST score near the top of the consistency ranking
and late ones near the bottom. If that check fails, the metric is wrong.

Two respondents carry an extra, deliberate behaviour:

  * ``SYNTHETIC_dummy_3_unsure``  answers "I don't know" on 5 species, so
    ``uncertainty_rate`` has something to measure and the agreement metrics
    have a respondent to exclude.
  * ``SYNTHETIC_dummy_4_outlier`` disagrees hard on 5 species (its answer
    is replaced with an almost-disjoint habitat set), so the per-habitat
    vote breakdown has genuine splits to display.

Determinism: a fixed seed and a private ``random.Random`` instance, so the
output is byte-identical on every run and unaffected by any other code
that touches the global RNG.

Usage
-----
    python code/expert_responses/make_synthetic_respondents.py
    python code/expert_responses/make_synthetic_respondents.py --seed 7
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CODE_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(CODE_DIR)

# Inside a git worktree the data lives in the main checkout, not the worktree.
_m = re.search(r"(.*)/\.claude/worktrees/[^/]+$", REPO_ROOT)
DATA_ROOT = _m.group(1) if _m else REPO_ROOT

sys.path.insert(0, CODE_DIR)
import focal_species as fs  # noqa: E402

TIDY_WIDE = os.path.join(HERE, "tidy", "expert_responses_wide.csv")
CATEGORIES_JSON = os.path.join(CODE_DIR, "llm_study", "categories.json")
OUT_DIR = os.path.join(DATA_ROOT, "outputs", "expert_survey")
OUT_CSV = os.path.join(OUT_DIR, "consistency_input_WITH_SYNTHETIC.csv")
OUT_README = os.path.join(OUT_DIR, "README_SYNTHETIC.md")

SYNTHETIC_PREFIX = "SYNTHETIC_"
DONT_KNOW = "I don't know"
DEFAULT_SEED = 20260811

# The designed consensus gradient, as flip probability per category cell.
P_FLIP_MIN = 0.00
P_FLIP_MAX = 0.42

# How many species get the special behaviours.
N_DONT_KNOW = 5
N_OUTLIER = 5

SYNTHETIC_NAMES = [
    "SYNTHETIC_dummy_1",
    "SYNTHETIC_dummy_2",
    "SYNTHETIC_dummy_3_unsure",
    "SYNTHETIC_dummy_4_outlier",
]

BANNER = (
    "# !! SYNTHETIC PLACEHOLDER DATA -- NOT REAL EXPERT RESPONSES !!\n"
    "# Columns prefixed SYNTHETIC_ are FABRICATED by "
    "code/expert_responses/make_synthetic_respondents.py\n"
    "# for pipeline testing and dashboard demonstration ONLY. They are not data,\n"
    "# carry no ecological meaning, and must never be reported as findings.\n"
    "# Delete this file to remove them; the analysis re-runs unchanged on real responses.\n"
)


class SyntheticError(RuntimeError):
    """Raised when the inputs are not in the expected shape."""


def load_categories() -> list[str]:
    with open(CATEGORIES_JSON, "r", encoding="utf-8") as fh:
        return [c["label"] for c in json.load(fh)["categories"]]


def split_habitats(raw: str, labels: list[str]) -> tuple[set[str], bool]:
    """Split a tidier answer cell into (labels present, dont_know).

    Longest-first, because "Mountain, heath and bog" contains a comma and a
    naive split on "," would shred it. Same rule the tidier uses.
    """
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
        raise SyntheticError(f"unrecognised habitat label(s) {leftover} in {raw!r}")
    return found, dont_know


def read_real_matrix(path: str, labels: list[str]) -> tuple[list[str], dict[str, set[str]], dict[str, bool]]:
    """Read the tidier's wide output -> (real column names, picks, dont_know)."""
    if not os.path.exists(path):
        raise SyntheticError(
            f"tidied matrix not found at {path}. Run first:\n"
            "  python code/expert_responses/tidy_responses.py"
        )
    with open(path, "r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    header, body = rows[0], rows[1:]
    real_cols = header[2:]
    if not real_cols:
        raise SyntheticError(f"{path} has no respondent columns.")
    if any(c.startswith(SYNTHETIC_PREFIX) for c in real_cols):
        raise SyntheticError(
            f"{path} already contains SYNTHETIC_ columns. It must hold only real "
            "responses -- re-run tidy_responses.py to regenerate it."
        )
    # Only the FIRST real respondent seeds the base vector, so adding real
    # respondents later does not silently change the synthetic answers.
    picks: dict[str, set[str]] = {}
    dk: dict[str, bool] = {}
    for r in body:
        code = r[0]
        p, d = split_habitats(r[2], labels)
        picks[code], dk[code] = p, d
    return real_cols, picks, dk


def p_flip_for_rank(rank: int, n: int) -> float:
    """Linear consensus gradient over the canonical species order."""
    if n <= 1:
        return P_FLIP_MIN
    return P_FLIP_MIN + (P_FLIP_MAX - P_FLIP_MIN) * (rank / (n - 1))


def build(seed: int) -> dict:
    labels = load_categories()
    species = fs.load_species()
    real_cols, real_picks, real_dk = read_real_matrix(TIDY_WIDE, labels)

    rng = random.Random(seed)
    codes = [s["ebird_code"] for s in species]

    # Species chosen for the special behaviours, drawn from the CONTESTED half
    # so they do not corrupt the high-consensus end the validation checks.
    contested = codes[len(codes) // 2:]
    dk_species = set(rng.sample(contested, N_DONT_KNOW))
    outlier_species = set(rng.sample(contested, N_OUTLIER))

    answers: dict[str, dict[str, tuple[set[str], bool]]] = {n: {} for n in SYNTHETIC_NAMES}

    for rank, s in enumerate(species):
        code = s["ebird_code"]
        base = real_picks.get(code, set())
        base_dk = real_dk.get(code, False)
        p = p_flip_for_rank(rank, len(species))

        for name in SYNTHETIC_NAMES:
            if name.endswith("_unsure") and code in dk_species:
                answers[name][code] = (set(), True)
                continue
            if name.endswith("_outlier") and code in outlier_species:
                # Almost-disjoint: take categories the base did NOT pick.
                pool = [l for l in labels if l not in base]
                k = min(2, len(pool))
                answers[name][code] = (set(rng.sample(pool, k)) if pool else set(), False)
                continue

            # A real "I don't know" propagates rather than being invented over.
            if base_dk:
                answers[name][code] = (set(), True)
                continue

            picks = set(base)
            for lab in labels:
                if rng.random() < p:
                    if lab in picks:
                        picks.discard(lab)
                    else:
                        picks.add(lab)
            # Never emit an all-empty answer: that reads as "did not answer"
            # rather than a disagreement, and would distort n_respondents.
            if not picks:
                picks = {rng.choice(labels)}
            answers[name][code] = (picks, False)

    return {
        "labels": labels,
        "species": species,
        "real_cols": real_cols,
        "real_picks": real_picks,
        "real_dk": real_dk,
        "answers": answers,
        "dk_species": dk_species,
        "outlier_species": outlier_species,
        "seed": seed,
    }


def cell(picks: set[str], dk: bool, labels: list[str]) -> str:
    """Render one answer back into the tidier's comma-joined cell format."""
    out = [l for l in labels if l in picks]
    if dk:
        out.append(DONT_KNOW)
    return ", ".join(out)


def write_outputs(b: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    labels, species = b["labels"], b["species"]

    with open(OUT_CSV, "w", encoding="utf-8", newline="") as fh:
        fh.write(BANNER)
        w = csv.writer(fh)
        w.writerow(["ebird_code", "species"] + b["real_cols"] + SYNTHETIC_NAMES)
        for s in species:
            code = s["ebird_code"]
            row = [code, s.get("red_list_name") or s.get("common_name", "")]
            row.append(cell(b["real_picks"].get(code, set()), b["real_dk"].get(code, False), labels))
            for name in SYNTHETIC_NAMES:
                picks, dk = b["answers"][name][code]
                row.append(cell(picks, dk, labels))
            w.writerow(row)

    n_real = len(b["real_cols"])
    codes = [s["ebird_code"] for s in species]
    name_of = {s["ebird_code"]: (s.get("red_list_name") or s.get("common_name", "")) for s in species}
    with open(OUT_README, "w", encoding="utf-8") as fh:
        fh.write(f"""# SYNTHETIC placeholder respondents

**The `SYNTHETIC_*` columns in `consistency_input_WITH_SYNTHETIC.csv` are
fabricated. They are not expert responses and must never be reported as
results.**

The expert survey currently has **{n_real} real respondent**
({', '.join(b['real_cols'])}). Agreement between experts is undefined with a
single respondent, so {len(SYNTHETIC_NAMES)} synthetic respondents were generated to exercise
and demonstrate the consistency pipeline before real responses arrive.

## How they were made

Generated by `code/expert_responses/make_synthetic_respondents.py`
(seed `{b['seed']}`, deterministic). Each synthetic respondent starts from the
real respondent's answer for a species and flips a controlled fraction of the
9 habitat cells. The flip probability rises linearly across the canonical
41-species order, from **{P_FLIP_MIN:.2f}** for the first species to
**{P_FLIP_MAX:.2f}** for the last, producing a designed consensus gradient
from near-unanimous to heavily contested.

| Column | Behaviour |
|---|---|
| `SYNTHETIC_dummy_1` | flip rate follows the gradient |
| `SYNTHETIC_dummy_2` | flip rate follows the gradient (independent draws) |
| `SYNTHETIC_dummy_3_unsure` | as above, plus "I don't know" on {N_DONT_KNOW} species |
| `SYNTHETIC_dummy_4_outlier` | as above, plus strong disagreement on {N_OUTLIER} species |

"I don't know" species: {', '.join(sorted(name_of[c] for c in b['dk_species']))}.
Outlier species: {', '.join(sorted(name_of[c] for c in b['outlier_species']))}.

## Why the gradient matters

It is the ground truth for validation. `consistency.py` checks that species
early in the canonical order (built to agree) rank near the top of the
consistency table and late ones near the bottom. That check is what confirms
the metric measures what it claims to.

## Removing them

Delete `consistency_input_WITH_SYNTHETIC.csv`. Nothing real is lost. When real
responses arrive, re-run the tidier and point `consistency.py` at
`code/expert_responses/tidy/expert_responses_wide.csv` instead -- the analysis
is agnostic about how many respondent columns it finds and runs unchanged.
""")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED,
                    help=f"RNG seed (default {DEFAULT_SEED}); output is deterministic per seed")
    args = ap.parse_args()

    b = build(args.seed)
    write_outputs(b)

    n_real = len(b["real_cols"])
    print("=" * 74)
    print("SYNTHETIC RESPONDENTS GENERATED -- FABRICATED PLACEHOLDER DATA, NOT REAL")
    print("=" * 74)
    print(f"real respondent(s)      : {n_real} ({', '.join(b['real_cols'])})")
    print(f"synthetic respondent(s) : {len(SYNTHETIC_NAMES)} ({', '.join(SYNTHETIC_NAMES)})")
    print(f"seed                    : {b['seed']} (deterministic)")
    print(f"designed flip gradient  : {P_FLIP_MIN:.2f} -> {P_FLIP_MAX:.2f} across "
          f"{len(b['species'])} species in canonical order")
    name_of = {s["ebird_code"]: (s.get("red_list_name") or s.get("common_name", ""))
               for s in b["species"]}
    print(f"'I don't know' species  : {', '.join(sorted(name_of[c] for c in b['dk_species']))}")
    print(f"outlier species         : {', '.join(sorted(name_of[c] for c in b['outlier_species']))}")
    print()
    print(f"wrote {OUT_CSV}")
    print(f"wrote {OUT_README}")
    print()
    print("Delete the CSV to remove the synthetic respondents entirely.")


if __name__ == "__main__":
    try:
        main()
    except (SyntheticError, fs.FocalSpeciesError) as exc:
        sys.exit(f"error: {exc}")
