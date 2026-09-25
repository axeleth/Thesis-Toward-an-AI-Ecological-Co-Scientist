#!/usr/bin/env python3
"""search_behaviour.py  --  which calls actually used the web search tool?
=========================================================================

Read-only analysis of the tools axis. Having the search tool available is not
the same as using it, and the main run shows the gap is large: across the
tools-on arm, 421 of 1107 calls (38%) made ZERO searches, and two whole
configurations (opus/p3_informed, opus/p4_engineered) never searched once.

This script exposes that per call, so "tools on" can be reported honestly as
"tools offered" alongside the rate at which they were actually used.

Outputs (all under outputs/llm_study/search_behaviour/):

  per_call.csv        one row per tools-on call: model, prompt, species,
                      repeat, n_searches, searched, cost, latency.
  per_config.csv      per (model, prompt, tools): calls, % searched, mean
                      searches/call, and the per-species consistency split.
  per_species.csv     per (model, prompt, species): the repeat pattern
                      (e.g. "SSS", "...", ".S.") and how many repeats
                      searched -- shows whether the decision is species-driven
                      or stochastic.
  SUMMARY.md          the tables above, rendered.

Nothing here calls the API and nothing is scored; it only reads the existing
call log. Safe to run at any time -- the log is opened read-only and a torn
final line (from a live appender) is skipped.

Usage:
    python code/llm_study/search_behaviour.py
    python code/llm_study/search_behaviour.py --tools on,forced
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _study_common as sc  # noqa: E402

OUT_DIRNAME = os.path.join("outputs", "llm_study", "search_behaviour")
MODEL_ORDER = ["haiku", "sonnet", "opus"]
PROMPT_ORDER = ["p2_scoped", "p3_informed", "p4_engineered"]


def load_calls(path: str, arms: set[str]) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue          # tolerate a torn line from a live appender
            if r.get("tools") in arms:
                rows.append(r)
    return rows


def order_key(model: str, prompt: str):
    return (MODEL_ORDER.index(model) if model in MODEL_ORDER else 99,
            PROMPT_ORDER.index(prompt) if prompt in PROMPT_ORDER else 99)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=None, help="path to raw_calls.jsonl")
    ap.add_argument("--tools", default="on,forced",
                    help="comma-separated tools arms to analyse (default on,forced)")
    args = ap.parse_args()

    raw = args.raw or sc.data_path(os.path.join("outputs", "llm_study",
                                                "raw_calls.jsonl"))
    if not os.path.exists(raw):
        sys.exit(f"ERROR: missing {raw}")
    arms = {a.strip() for a in args.tools.split(",") if a.strip()}
    calls = load_calls(raw, arms)
    if not calls:
        sys.exit(f"ERROR: no calls with tools in {sorted(arms)} found in {raw}")

    out = sc.data_path(OUT_DIRNAME)
    os.makedirs(out, exist_ok=True)

    # --- per call ----------------------------------------------------------
    per_call = []
    for r in calls:
        n = int(r.get("tool_calls_count") or 0)
        per_call.append({
            "model": r.get("model_key"), "prompt": r.get("prompt_id"),
            "tools": r.get("tools"),
            "species_code": r.get("species_code"),
            "species_name": r.get("species_prompt_name") or r.get("common_name"),
            "repeat_index": r.get("repeat_index"),
            "n_searches": n, "searched": bool(n >= 1),
            "cost_usd": r.get("cost_usd"),
            "wall_clock_seconds": r.get("wall_clock_seconds"),
        })
    per_call.sort(key=lambda x: (order_key(x["model"], x["prompt"]), x["tools"],
                                 str(x["species_code"]), x["repeat_index"] or 0))
    write_csv(os.path.join(out, "per_call.csv"), per_call)

    # --- per species (the repeat pattern) ----------------------------------
    bysp: dict[tuple, dict[int, int]] = collections.defaultdict(dict)
    names: dict[str, str] = {}
    for c in per_call:
        bysp[(c["model"], c["prompt"], c["tools"], c["species_code"])][
            c["repeat_index"] or 0] = c["n_searches"]
        names[c["species_code"]] = c["species_name"] or ""
    per_species = []
    for (m, p, t, sp), reps in bysp.items():
        idx = sorted(reps)
        pattern = "".join("S" if reps[i] else "." for i in idx)
        per_species.append({
            "model": m, "prompt": p, "tools": t,
            "species_code": sp, "species_name": names.get(sp, ""),
            "n_repeats": len(idx),
            "n_repeats_searched": sum(1 for i in idx if reps[i]),
            "pattern": pattern,
            "total_searches": sum(reps.values()),
        })
    per_species.sort(key=lambda x: (order_key(x["model"], x["prompt"]), x["tools"],
                                    str(x["species_code"])))
    write_csv(os.path.join(out, "per_species.csv"), per_species)

    # --- per config --------------------------------------------------------
    agg: dict[tuple, dict] = collections.defaultdict(
        lambda: {"n": 0, "searched": 0, "searches": 0, "always": 0,
                 "never": 0, "mixed": 0, "species": 0})
    for c in per_call:
        a = agg[(c["model"], c["prompt"], c["tools"])]
        a["n"] += 1
        a["searches"] += c["n_searches"]
        if c["searched"]:
            a["searched"] += 1
    for s in per_species:
        a = agg[(s["model"], s["prompt"], s["tools"])]
        a["species"] += 1
        if s["n_repeats_searched"] == 0:
            a["never"] += 1
        elif s["n_repeats_searched"] == s["n_repeats"]:
            a["always"] += 1
        else:
            a["mixed"] += 1

    per_config = []
    for k in sorted(agg, key=lambda k: (order_key(k[0], k[1]), k[2])):
        a = agg[k]
        n = a["n"]
        per_config.append({
            "model": k[0], "prompt": k[1], "tools": k[2],
            "n_calls": n,
            "n_searched": a["searched"],
            "pct_searched": round(a["searched"] / n * 100, 1) if n else 0.0,
            "mean_searches_per_call": round(a["searches"] / n, 2) if n else 0.0,
            "n_species": a["species"],
            "species_always_searched": a["always"],
            "species_never_searched": a["never"],
            "species_mixed": a["mixed"],
        })
    write_csv(os.path.join(out, "per_config.csv"), per_config)

    # --- stdout ------------------------------------------------------------
    print("=" * 92)
    print("SEARCH BEHAVIOUR  --  how often was the available search tool actually used?")
    print("=" * 92)
    print(f"\n  {'model':<8} {'prompt':<15} {'tools':<7} {'calls':>6} {'searched':>9} "
          f"{'srch/call':>10} | per species: {'always':>6} {'never':>6} {'mixed':>6}")
    print("  " + "-" * 88)
    for r in per_config:
        print(f"  {r['model']:<8} {r['prompt']:<15} {r['tools']:<7} {r['n_calls']:>6} "
              f"{r['pct_searched']:>8.1f}% {r['mean_searches_per_call']:>10.2f} | "
              f"{'':12s} {r['species_always_searched']:>6} "
              f"{r['species_never_searched']:>6} {r['species_mixed']:>6}")
    tot = sum(r["n_calls"] for r in per_config)
    ts = sum(r["n_searched"] for r in per_config)
    print(f"\n  Overall: {ts}/{tot} calls searched ({ts / tot * 100:.1f}%); "
          f"{tot - ts} made none.")
    print("\n  always/never/mixed = species where every / no / some repeats searched.")
    print("  'mixed' means the decision was stochastic for that species; a high "
          "'never'\n  with low 'mixed' means it was driven by the species itself.")

    write_summary(per_config, per_species, out, tot, ts)
    print(f"\nWrote:\n  {os.path.join(out, 'per_call.csv')}\n"
          f"  {os.path.join(out, 'per_species.csv')}\n"
          f"  {os.path.join(out, 'per_config.csv')}\n"
          f"  {os.path.join(out, 'SUMMARY.md')}")


def write_csv(path: str, rows: list[dict]) -> None:
    if not rows:
        return
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def write_summary(per_config, per_species, out: str, tot: int, ts: int) -> None:
    L = []
    L.append("# Search behaviour -- was the available tool actually used?\n")
    L.append(f"Generated {datetime.now(timezone.utc).isoformat()}\n")
    L.append("Having the web search tool available is not the same as the model using "
             "it. This is the per-call record of which calls actually searched.\n")
    L.append(f"**Overall: {ts} of {tot} calls searched ({ts / tot * 100:.1f}%); "
             f"{tot - ts} made no search at all.**\n")
    L.append("## Per configuration\n")
    L.append("| Model | Prompt | Tools | Calls | Searched | Searches/call | "
             "Species always | never | mixed |")
    L.append("|---|---|---|---:|---:|---:|---:|---:|---:|")
    for r in per_config:
        L.append(f"| {r['model']} | {r['prompt']} | {r['tools']} | {r['n_calls']} | "
                 f"{r['pct_searched']:.1f}% | {r['mean_searches_per_call']:.2f} | "
                 f"{r['species_always_searched']} | {r['species_never_searched']} | "
                 f"{r['species_mixed']} |")
    L.append("")
    L.append("`always` / `never` / `mixed` count species where every, no, or only some "
             "repeats searched. A high `never` with low `mixed` means the choice was "
             "driven by the species; a high `mixed` means it was stochastic.\n")
    L.append("## Files\n")
    L.append("- `per_call.csv` -- one row per call, with `n_searches` and `searched`.")
    L.append("- `per_species.csv` -- the repeat `pattern` per species "
             "(`SSS` = searched on all three repeats, `...` = never, `.S.` = mixed).")
    L.append("- `per_config.csv` -- the table above.\n")
    L.append("Search counts come from `tool_calls_count`, written by "
             "`WebSearchTools.extract_usage` in `code/llm_study/tools.py`.\n")
    L.append("Generated by `code/llm_study/search_behaviour.py`.")
    with open(os.path.join(out, "SUMMARY.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))


if __name__ == "__main__":
    main()
