#!/usr/bin/env python3
"""search_forcing_test.py  --  does the model search when told to?
===================================================================

A BEHAVIOURAL PROBE, not a scored run. It measures ONE thing: how often each
(model x prompt) pair actually calls the web search tool when the prompt
explicitly instructs it to. Nothing here is parsed into a habitat matrix and
nothing is scored against the Handbook or the data.

WHY
---
The main tools-on arm shows that having the tool available is not the same as
using it. Search rates over that run:

    opus/p3_informed      0% of calls searched   (0 of 123)
    opus/p4_engineered    0% of calls searched   (0 of 123)
    sonnet/p4_engineered  29%                    (36 of 123)
    sonnet/p3_informed    38%                    (47 of 123)
    haiku/p3_informed     95%   opus/p2_scoped   95%
    haiku/p2, haiku/p4, sonnet/p2   100%

So two of the nine tools-on configurations never searched at all, and two more
searched on a minority of species. That leaves an important ambiguity, and it is
exactly what this probe resolves:

    (a) the model was OFFERED the tool and DECLINED it -- a real finding about
        how prompt wording interacts with tool use; or
    (b) the tool was never properly wired up for those cells -- a bug, which
        would mean part of the tools-on arm is invalid.

If a strongly-worded search instruction pushes opus/p3 and opus/p4 from 0% to a
high rate, the wiring is fine and (a) holds: the models were choosing not to
search. If they stay at 0% even when told to search, that points at (b) and the
tools-on arm needs re-examining before any tools claim goes in the thesis.

DOES NOT DISTURB THE MAIN RUN
-----------------------------
Everything is written under `outputs/llm_study/search_forcing_test/`. This
script never opens the main run's files for writing -- not raw_calls.jsonl, not
matrices/, not SUMMARY.md -- and it imports the harness read-only. It does not
modify run_study.py, tools.py, _study_common.py, config.yaml or the prompts.
The one main-run file it may READ is raw_calls.jsonl, to print the baseline
column; that read is line-buffered and tolerant of a torn final line, so it is
safe alongside a live appender, and it is skipped entirely with --no-baseline.

Usage
-----
    python code/llm_study/search_forcing_test.py --dry-run   # price it, no API
    python code/llm_study/search_forcing_test.py             # 90 calls
    python code/llm_study/search_forcing_test.py --limit 9   # 1 species/config
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _study_common as sc          # noqa: E402  (read-only)
import run_study as rs              # noqa: E402  (read-only: call_model/response_text)
from tools import WebSearchTools    # noqa: E402  (read-only: the same extractor)

# ---------------------------------------------------------------------------
# Knobs
# ---------------------------------------------------------------------------
# Species sample: the first N of the canonical 41, so every configuration is
# probed on an IDENTICAL set and the rates are directly comparable.
N_SPECIES = 10
REPEATS = 1

# The forcing block, PREPENDED to each existing prompt (the templates are never
# replaced -- the model x prompt structure has to stay intact for the comparison
# to mean anything). Reword freely; this is the independent variable.
FORCING_INSTRUCTION = (
    "IMPORTANT: You have a web search tool available. Before you answer, you "
    "MUST use it to look up this species and its habitats in the UK. Do not "
    "answer from your own knowledge alone; search the web first and base your "
    "answer on what you find."
)

OUT_DIRNAME = os.path.join("outputs", "llm_study", "search_forcing_test")
CALLS_FILENAME = "calls.jsonl"
RATES_FILENAME = "search_rates.csv"
SUMMARY_FILENAME = "SUMMARY.md"

MODEL_ORDER = ["haiku", "sonnet", "opus"]
PROMPT_ORDER = ["p2_scoped", "p3_informed", "p4_engineered"]


# ---------------------------------------------------------------------------
def out_dir() -> str:
    d = sc.data_path(OUT_DIRNAME)
    os.makedirs(d, exist_ok=True)
    return d


def baseline_rates(tools_value: str = "on") -> dict[tuple[str, str], dict]:
    """Search rates from the MAIN run, for the side-by-side column.

    Read-only and defensive: the main log is append-only and may be being
    written by a live run, so it is streamed line by line and a torn final
    line is skipped rather than raising.
    """
    path = sc.data_path(os.path.join("outputs", "llm_study", "raw_calls.jsonl"))
    if not os.path.exists(path):
        return {}
    agg: dict[tuple[str, str], dict] = collections.defaultdict(
        lambda: {"n": 0, "searched": 0, "searches": 0}
    )
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue           # live appender caught mid-write
                if r.get("tools") != tools_value:
                    continue
                k = (r.get("model_key"), r.get("prompt_id"))
                n = int(r.get("tool_calls_count") or 0)
                a = agg[k]
                a["n"] += 1
                a["searches"] += n
                if n >= 1:
                    a["searched"] += 1
    except OSError:
        return {}
    return {k: v for k, v in agg.items()}


def build_cells(cfg, templates, species, models):
    """Every (model, prompt, species, repeat) cell of the probe."""
    by_id = {t.prompt_id: t for t in templates}
    prompts = [p for p in PROMPT_ORDER if p in by_id] + \
              [t.prompt_id for t in templates if t.prompt_id not in PROMPT_ORDER]
    cells = []
    for mk in [m for m in MODEL_ORDER if m in models] + \
              [m for m in models if m not in MODEL_ORDER]:
        for pid in prompts:
            for sp in species:
                for rep in range(REPEATS):
                    cells.append((mk, by_id[pid], sp, rep))
    return cells


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None, help="path to config.yaml")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve and price the calls, make no API calls")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap the total number of calls (smoke test)")
    ap.add_argument("--species", type=int, default=N_SPECIES,
                    help=f"species per configuration (default {N_SPECIES})")
    ap.add_argument("--no-baseline", action="store_true",
                    help="skip reading the main run's search rates")
    args = ap.parse_args()

    cfg = sc.load_config(args.config)
    slugs, labels = sc.load_categories(cfg)
    categories_block = sc.format_category_list(slugs, labels)
    definitions = sc.load_category_definitions(cfg)
    templates = sc.load_prompt_templates(cfg)
    roster = sc.load_species(cfg)

    species = roster[: max(1, args.species)]
    cells = build_cells(cfg, templates, species, cfg.models)
    if args.limit is not None:
        cells = cells[: max(1, args.limit)]

    n_cfgs = len({(m, t.prompt_id) for m, t, _, _ in cells})
    print("=" * 78)
    print("search_forcing_test.py -- does the model search when told to?")
    print("=" * 78)
    print(f"\nBehavioural probe only: search FREQUENCY. Nothing is parsed or scored.")
    print(f"  configurations : {n_cfgs} ({len(cfg.models)} models x "
          f"{len(templates)} prompts)")
    print(f"  species        : {len(species)} (first {len(species)} of "
          f"{len(roster)}, identical for every configuration)")
    print(f"  repeats        : {REPEATS}")
    print(f"  tools          : ON for every call (web search must be available)")
    print(f"  total calls    : {len(cells)}")
    print(f"  output dir     : {out_dir()}")

    # --- cost estimate, from the same pricing table as the main run --------
    est = cfg.dry_run_estimate
    in_tok = float(est.get("input_tokens_per_call", 400))
    out_tok = float(est.get("output_tokens_per_call", 600))
    mult = float(est.get("tools_on_input_multiplier", 4.0))
    total = 0.0
    per_model: dict[str, float] = collections.defaultdict(float)
    for mk, _t, _sp, _r in cells:
        m = cfg.models[mk]
        c = m.cost_usd(int(in_tok * mult), int(out_tok))
        total += c
        per_model[mk] += c
    print(f"\nEstimated cost (tools-on token guesses x pricing table):")
    for mk in [m for m in MODEL_ORDER if m in per_model]:
        print(f"    {mk:<8} ${per_model[mk]:.4f}")
    print(f"    {'TOTAL':<8} ${total:.4f} USD")

    if args.dry_run:
        print("\n--dry-run: no API calls made, nothing written.")
        return

    # --- run ---------------------------------------------------------------
    sc.load_dotenv_if_present()
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ERROR: ANTHROPIC_API_KEY not set. See code/API_KEY_SETUP.md")
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=0)

    provider = WebSearchTools(cfg.tool_config)   # the SAME wiring as the main run
    d = out_dir()
    calls_path = os.path.join(d, CALLS_FILENAME)
    records: list[dict] = []

    print(f"\nRunning {len(cells)} call(s)...\n")
    with open(calls_path, "w", encoding="utf-8") as fh:
        for i, (mk, tpl, sp, rep) in enumerate(cells, 1):
            model = cfg.models[mk]
            name = sc.species_display_name(sp, cfg)
            base = tpl.render(name, categories_block, definitions)
            prompt = f"{FORCING_INSTRUCTION}\n\n{base}"

            t0 = time.time()
            err = None
            try:
                resp, retries = rs.call_model(client, model, provider, prompt, cfg)
            except Exception as e:  # noqa: BLE001 -- recorded, probe continues
                err, resp, retries = f"{type(e).__name__}: {e}", None, 0
            elapsed = time.time() - t0

            if resp is not None:
                usage = provider.extract_usage(resp)      # identical extractor
                n_searches = int(usage.get("tool_calls_count") or 0)
                in_t = int(getattr(resp.usage, "input_tokens", 0) or 0)
                out_t = int(getattr(resp.usage, "output_tokens", 0) or 0)
                text = rs.response_text(resp)
            else:
                n_searches, in_t, out_t, text = 0, 0, 0, ""

            rec = {
                "model_key": mk, "model_id": model.id,
                "prompt_id": tpl.prompt_id, "prompt_label": tpl.label,
                "guidance_level": tpl.guidance_level,
                "tools": "on", "forced": True,
                "species_code": sp.get("species_code"),
                "species_prompt_name": name,
                "repeat_index": rep,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "searched": bool(n_searches >= 1),
                "n_searches": n_searches,
                "input_tokens": in_t, "output_tokens": out_t,
                "cost_usd": round(model.cost_usd(in_t, out_t), 6),
                "wall_clock_seconds": round(elapsed, 3),
                "api_retries": retries,
                "error": err,
                "raw_response": text,
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            records.append(rec)

            flag = "ERROR" if err else ("search" if n_searches else "  --  ")
            print(f"  [{i:3d}/{len(cells)}] {mk:<7} {tpl.prompt_id:<14} "
                  f"{name[:22]:<22} {flag:<7} {n_searches} "
                  f"{elapsed:6.2f}s ${rec['cost_usd']:.4f}")

    write_outputs(records, d, args.no_baseline)


def write_outputs(records: list[dict], d: str, no_baseline: bool) -> None:
    """Aggregate per (model, prompt) -> CSV + SUMMARY.md + stdout table."""
    agg: dict[tuple[str, str], dict] = collections.defaultdict(
        lambda: {"n": 0, "searched": 0, "searches": 0, "lat": 0.0,
                 "cost": 0.0, "errors": 0}
    )
    for r in records:
        a = agg[(r["model_key"], r["prompt_id"])]
        a["n"] += 1
        a["searches"] += r["n_searches"]
        a["lat"] += r["wall_clock_seconds"]
        a["cost"] += r["cost_usd"]
        if r["searched"]:
            a["searched"] += 1
        if r["error"]:
            a["errors"] += 1

    base = {} if no_baseline else baseline_rates("on")

    rows = []
    keys = sorted(agg, key=lambda k: (MODEL_ORDER.index(k[0]) if k[0] in MODEL_ORDER else 99,
                                      PROMPT_ORDER.index(k[1]) if k[1] in PROMPT_ORDER else 99))
    for k in keys:
        a = agg[k]
        n = a["n"]
        b = base.get(k)
        rows.append({
            "model": k[0], "prompt": k[1],
            "n_calls": n,
            "pct_searched": round(a["searched"] / n * 100, 1) if n else 0.0,
            "n_searched": a["searched"],
            "mean_searches_per_call": round(a["searches"] / n, 2) if n else 0.0,
            "mean_latency_s": round(a["lat"] / n, 2) if n else 0.0,
            "mean_cost_per_call": round(a["cost"] / n, 6) if n else 0.0,
            "errors": a["errors"],
            "baseline_pct_searched": (round(b["searched"] / b["n"] * 100, 1)
                                      if b and b["n"] else None),
            "baseline_n_calls": (b["n"] if b else None),
            "delta_pct_points": (round(a["searched"] / n * 100 - b["searched"] / b["n"] * 100, 1)
                                 if n and b and b["n"] else None),
        })

    csv_path = os.path.join(d, RATES_FILENAME)
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    has_base = any(r["baseline_pct_searched"] is not None for r in rows)
    print("\n" + "=" * 94)
    print("SEARCH FREQUENCY under a forcing instruction  (tools ON for every call)")
    print("=" * 94)
    hdr = (f"\n  {'model':<8} {'prompt':<15} {'calls':>5} {'searched':>9} "
           f"{'srch/call':>10} {'latency':>8} {'$/call':>9}")
    if has_base:
        hdr += f"  {'baseline':>9} {'delta':>8}"
    print(hdr)
    print("  " + "-" * (90 if has_base else 70))
    for r in rows:
        line = (f"  {r['model']:<8} {r['prompt']:<15} {r['n_calls']:>5} "
                f"{r['pct_searched']:>8.1f}% {r['mean_searches_per_call']:>10.2f} "
                f"{r['mean_latency_s']:>7.2f}s ${r['mean_cost_per_call']:>8.4f}")
        if has_base:
            bp = r["baseline_pct_searched"]
            dp = r["delta_pct_points"]
            line += (f"  {bp:>8.1f}%" if bp is not None else f"  {'n/a':>9}")
            line += (f" {dp:>+7.1f}" if dp is not None else f" {'':>8}")
        print(line)
    if has_base:
        print("\n  baseline = the same (model, prompt) in the main tools-on run, where the "
              "tool\n  was available but not demanded. delta = forced minus baseline, "
              "percentage points.")

    write_summary(rows, records, d, has_base)
    print(f"\nWrote:\n  {os.path.join(d, CALLS_FILENAME)}\n  {csv_path}\n"
          f"  {os.path.join(d, SUMMARY_FILENAME)}")


def write_summary(rows, records, d: str, has_base: bool) -> None:
    n_err = sum(1 for r in records if r["error"])
    L = []
    L.append("# Search forcing test -- does the model search when told to?\n")
    L.append(f"Generated {datetime.now(timezone.utc).isoformat()}\n")
    L.append("A **behavioural probe**, not a scored run. It measures one thing: how "
             "often each (model x prompt) pair actually calls the web search tool when "
             "the prompt explicitly instructs it to. Nothing is parsed into a habitat "
             "matrix and nothing is scored.\n")
    L.append("## Why\n")
    L.append("In the main tools-on run, having the tool available was not the same as "
             "using it -- `opus/p3_informed` and `opus/p4_engineered` made **zero** "
             "searches across all 123 calls each, and both Sonnet's guided prompts "
             "searched on a minority of species. This probe separates two explanations:\n")
    L.append("1. the model was offered the tool and **declined** it (a real finding "
             "about prompt wording vs tool use); or")
    L.append("2. the tool was **never wired up** for those cells (a bug that would "
             "invalidate part of the tools-on arm).\n")
    L.append("A jump from 0% to a high rate under forcing supports (1). Staying at 0% "
             "points at (2).\n")
    L.append("## The forcing instruction\n")
    L.append("Prepended to each of the three existing prompt templates (the templates "
             "themselves are unchanged, so the model x prompt structure is intact):\n")
    L.append("```")
    L.append(FORCING_INSTRUCTION)
    L.append("```\n")
    L.append(f"Sample: the first {len({r['species_code'] for r in records})} species of "
             f"the canonical set, identical for every configuration; "
             f"{REPEATS} repeat(s); tools ON for every call.")
    if n_err:
        L.append(f"\n**{n_err} call(s) errored** and count as not-searched; see "
                 "`calls.jsonl`.")
    L.append("")
    L.append("## Search rates\n")
    head = ("| Model | Prompt | Calls | Searched | Searches/call | Latency (s) | "
            "$/call |")
    sep = "|---|---|---:|---:|---:|---:|---:|"
    if has_base:
        head += " Baseline searched | Delta (pp) |"
        sep += "---:|---:|"
    L.append(head)
    L.append(sep)
    for r in rows:
        line = (f"| {r['model']} | {r['prompt']} | {r['n_calls']} | "
                f"{r['pct_searched']:.1f}% | {r['mean_searches_per_call']:.2f} | "
                f"{r['mean_latency_s']:.2f} | ${r['mean_cost_per_call']:.4f} |")
        if has_base:
            bp, dp = r["baseline_pct_searched"], r["delta_pct_points"]
            line += (f" {bp:.1f}% |" if bp is not None else " n/a |")
            line += (f" {dp:+.1f} |" if dp is not None else " |")
        L.append(line)
    L.append("")
    if has_base:
        L.append("**Baseline** is the same (model, prompt) in the main tools-on run, "
                 "where the tool was available but not demanded. **Delta** is forced "
                 "minus baseline, in percentage points.\n")
    L.append("Search counts come from `WebSearchTools.extract_usage` in "
             "`code/llm_study/tools.py` -- the same extractor the main run uses, so "
             "these numbers are directly comparable to it.\n")
    L.append("Generated by `code/llm_study/search_forcing_test.py`.")
    with open(os.path.join(d, SUMMARY_FILENAME), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))


if __name__ == "__main__":
    main()
