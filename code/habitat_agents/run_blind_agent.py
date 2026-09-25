#!/usr/bin/env python3
"""run_blind_agent.py  --  BLIND habitat-presence agent
=======================================================

For each of the 50 red-list species, asks a stock LLM (no retrieval) which of the
9 UKCEH-aggregate (Strategy 2) habitat categories the species is "commonly found
in", using ONLY the model's inherent knowledge. The model sees the species name
and the 9 habitat options -- and NOTHING from the data (no abundance, no shares,
no data matrix).

One model call per species (matching the one-row-per-species data matrix). The
model returns a JSON array of 9 verdict objects, one per habitat:

    { "habitat": "<slug>", "classification": "Documented"|"Not established",
      "citations": [...], "reasoning": "..." }

The matrix is BINARY: a habitat is True ONLY when the agent can decisively
determine the species is commonly found there. Anything less -- including "cannot
confidently say" -- is False. There is no "unsure"/empty cell in this section.

Outputs (under outputs/habitat_agents/):
  - blind_presence_matrix.csv  -- BINARY matrix (True/False), same column shape as
      the data matrix redlist_aggregate9_1km_weighted_presence_matrix.csv.
  - blind_verdicts.json        -- long-form detail per (species, habitat).

The blind matrix is column- and row-aligned to the data matrix so the two can be
diffed cell-for-cell later (see build_alignment_xlsx.py).

Usage
-----
    python code/habitat_agents/run_blind_agent.py               # Claude (default)
    python code/habitat_agents/run_blind_agent.py --model gpt-4o
    python code/habitat_agents/run_blind_agent.py --limit 3     # first 3 species
    python code/habitat_agents/run_blind_agent.py --mock        # no API; stub verdicts
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _agent_common as ac  # noqa: E402

PROMPT_TEMPLATE_MD = os.path.join(ac.PROMPTS_DIR, "habitat_blind_assessment.md")
SPECIES_PLACEHOLDER = "{SPECIES}"
HABITAT_LIST_PLACEHOLDER = "{HABITAT_LIST}"

OUT_MATRIX = os.path.join(ac.OUTPUT_DIR, "blind_presence_matrix.csv")
OUT_VERDICTS = os.path.join(ac.OUTPUT_DIR, "blind_verdicts.json")


def build_prompt(template: str, common_name: str) -> str:
    """Fill the template with the species name and the 9-habitat list. No data."""
    prompt = template.replace(SPECIES_PLACEHOLDER, common_name)
    prompt = prompt.replace(HABITAT_LIST_PLACEHOLDER, ac.format_habitat_list())
    return prompt


def mock_backend(prompt: str) -> str:
    """Deterministic offline stub: Documented for improved_grassland (-> True), Not
    established for the rest (-> False) -- exercises both binary cells."""
    import json

    verdicts = []
    for slug in ac.CATEGORIES:
        cls = "Documented" if slug == "improved_grassland" else "Not established"
        verdicts.append(
            {
                "habitat": slug,
                "classification": cls,
                "citations": [],
                "reasoning": "MOCK verdict (no API call).",
            }
        )
    return json.dumps(verdicts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=ac.DEFAULT_MODEL,
        help=f"'{ac.CLAUDE_MODEL}'/'claude' (default) or '{ac.OPENAI_MODEL}'/'gpt-4o'.",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Assess only the first N species."
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Skip the API and emit deterministic stub verdicts (offline smoke test).",
    )
    args = parser.parse_args()

    if args.mock:
        model_name, backend = "mock", mock_backend
    else:
        model_name, backend = ac.get_backend(args.model)

    roster = ac.load_species_roster()
    if args.limit is not None:
        roster = roster[: args.limit]

    template = ac.load_prompt_template(
        PROMPT_TEMPLATE_MD, (SPECIES_PLACEHOLDER, HABITAT_LIST_PLACEHOLDER)
    )

    print(
        f"BLIND habitat agent: {len(roster)} species, model={model_name}, "
        f"temperature={ac.TEMPERATURE}"
    )
    print("(the model sees ONLY the species name and the 9 habitats -- no data)\n")

    matrix_rows: list[dict] = []
    verdict_records: list[dict] = []

    for i, sp in enumerate(roster, start=1):
        common = sp["common_name"]
        print(f"[{i}/{len(roster)}] {common} ... ", end="", flush=True)

        prompt = build_prompt(template, common)
        try:
            by_slug, raw, parse_failed = ac.assess_species(backend, prompt)
        except Exception as e:  # network / API failure -- record & continue
            print(f"ERROR ({e.__class__.__name__})")
            raw = f"API ERROR: {e.__class__.__name__}: {e}"
            by_slug, parse_failed = {}, True

        row = {
            "species_code": sp["species_code"],
            "common_name": common,
            "red_list_name": sp["red_list_name"],
        }
        n_ok = 0
        for slug in ac.CATEGORIES:
            v = by_slug.get(slug)
            if v is None:
                # Habitat not returned, or the whole call failed. Either way the
                # agent did not decisively establish the species here -> False.
                # (A total API/parse failure still records parse_failed below so
                # it stays distinguishable in the verdicts JSON.)
                row[slug] = False
                classification = "Not established" if not parse_failed else None
            else:
                row[slug] = ac.verdict_to_cell(v["classification"])
                classification = v["classification"]
                n_ok += 1
            verdict_records.append(
                {
                    "species_code": sp["species_code"],
                    "common_name": common,
                    "red_list_name": sp["red_list_name"],
                    "habitat": slug,
                    "habitat_label": ac.CATEGORY_LABELS[slug],
                    "classification": classification,
                    "citations": (v or {}).get("citations", []),
                    "reasoning": (v or {}).get("reasoning"),
                    "model": model_name,
                    "parse_failed": parse_failed and v is None,
                    "raw_response": raw,
                }
            )
        matrix_rows.append(row)
        print("PARSE_FAIL" if parse_failed else f"{n_ok}/{len(ac.CATEGORIES)} habitats")

    ac.write_presence_matrix(OUT_MATRIX, matrix_rows)
    ac.write_verdicts_json(OUT_VERDICTS, verdict_records)

    n_fail = sum(1 for r in verdict_records if r.get("parse_failed"))
    print(
        f"\nWrote presence matrix ({len(matrix_rows)} species) to:\n  {OUT_MATRIX}\n"
        f"Wrote {len(verdict_records)} verdict rows to:\n  {OUT_VERDICTS}"
    )
    if n_fail:
        print(f"⚠️  {n_fail} verdict cell(s) had a parse/API failure.")


if __name__ == "__main__":
    ac.load_dotenv_if_present()
    main()
