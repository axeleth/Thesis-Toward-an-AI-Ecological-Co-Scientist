#!/usr/bin/env python3
"""run_forced_arm.py  --  the FORCED third arm of the tools axis
================================================================

The tools axis was originally binary:

    off     no search tool is sent
    on      the search tool is AVAILABLE -- the model decides whether to use it

The main run showed those are not the two conditions they look like. With the
tool merely available, 38% of calls made no search at all, and two whole
configurations (opus/p3_informed, opus/p4_engineered) never searched once in
123 calls each. So the `on` arm does not measure "answering with web search";
it measures "answering when web search is offered", which is a different and
model-dependent thing.

This script adds the missing condition:

    forced  the search tool is available AND the prompt explicitly demands a
            search before answering

With all three, the tools axis separates two effects that were previously
confounded: whether a model CHOOSES to search (off vs on) and whether searching
HELPS (on vs forced).

WHAT IT RUNS
------------
All 9 model x prompt configurations, 41 species x 3 repeats = 1107 calls,
matching the shape of the other two arms exactly so the three are comparable.
The forcing block is PREPENDED to each existing prompt template; the templates
themselves are untouched, so the model x prompt structure is preserved.

Unlike `search_forcing_test.py` (a 90-call frequency probe that scores nothing),
this arm writes full records suitable for parsing and scoring -- same field
names as the main run -- so `parse.py`, `aggregate.py` and
`19_score_all_configs.py` consume it unchanged.

SAFETY
------
Writes to its OWN log, `outputs/llm_study/forced_arm/raw_calls_forced.jsonl`,
never to the main `raw_calls.jsonl`. Merge deliberately at the end (see
--print-merge-command) rather than appending to the live file mid-run.

RESUMABLE. Every completed call is flushed immediately and the log is re-read on
start; cells already present are skipped. A crash, a Ctrl-C or a rate-limit
wipeout costs only the calls in flight, not the whole spend. Re-running the
same command simply continues.

Usage
-----
    python code/llm_study/run_forced_arm.py --dry-run
    python code/llm_study/run_forced_arm.py --go --concurrency 6
    python code/llm_study/run_forced_arm.py --go            # resumes
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _study_common as sc          # noqa: E402  (read-only)
import run_study as rs              # noqa: E402  (read-only)
from tools import WebSearchTools    # noqa: E402  (read-only)

TOOLS_VALUE = "forced"      # the third value on the tools axis
OUT_DIRNAME = os.path.join("outputs", "llm_study", "forced_arm")
RAW_FILENAME = "raw_calls_forced.jsonl"

# Identical wording to search_forcing_test.py, which took all 9 configs to a
# 100% search rate on a 90-call probe. Keep them in sync if either is reworded.
FORCING_INSTRUCTION = (
    "IMPORTANT: You have a web search tool available. Before you answer, you "
    "MUST use it to look up this species and its habitats in the UK. Do not "
    "answer from your own knowledge alone; search the web first and base your "
    "answer on what you find."
)

MODEL_ORDER = ["haiku", "sonnet", "opus"]
PROMPT_ORDER = ["p2_scoped", "p3_informed", "p4_engineered"]

# Observed $/call from the 90-call probe -- a far better estimate than the
# generic token guesses in config.yaml, which do not know how much the search
# results add to the context.
OBSERVED_COST_PER_CALL = {
    ("haiku", "p2_scoped"): 0.0133, ("haiku", "p3_informed"): 0.0207,
    ("haiku", "p4_engineered"): 0.0251,
    ("sonnet", "p2_scoped"): 0.1298, ("sonnet", "p3_informed"): 0.0707,
    ("sonnet", "p4_engineered"): 0.0912,
    ("opus", "p2_scoped"): 0.1532, ("opus", "p3_informed"): 0.1524,
    ("opus", "p4_engineered"): 0.1475,
}


def out_dir() -> str:
    d = sc.data_path(OUT_DIRNAME)
    os.makedirs(d, exist_ok=True)
    return d


def done_cells(path: str) -> set[tuple]:
    """(model, prompt, species, repeat) already recorded -- for resume."""
    done = set()
    if not os.path.exists(path):
        return done
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue          # torn final line from an interrupted run
            if r.get("error"):
                continue          # failed calls are retried on resume
            done.add((r.get("model_key"), r.get("prompt_id"),
                      r.get("species_code"), r.get("repeat_index")))
    return done


def build_cells(cfg, templates, species):
    by_id = {t.prompt_id: t for t in templates}
    prompts = [p for p in PROMPT_ORDER if p in by_id] + \
              [t.prompt_id for t in templates if t.prompt_id not in PROMPT_ORDER]
    models = [m for m in MODEL_ORDER if m in cfg.models] + \
             [m for m in cfg.models if m not in MODEL_ORDER]
    cells = []
    for mk in models:
        for pid in prompts:
            for sp in species:
                for rep in range(cfg.repeats):
                    cells.append((mk, by_id[pid], sp, rep))
    return cells


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve and price the run; make no API calls")
    ap.add_argument("--go", action="store_true",
                    help="required to actually spend money")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="parallel calls (capped by config.yaml concurrency.max)")
    ap.add_argument("--limit", type=int, default=None, help="cap total calls")
    ap.add_argument("--models", default=None, help="comma-separated subset")
    ap.add_argument("--prompts", default=None, help="comma-separated subset")
    ap.add_argument("--print-merge-command", action="store_true",
                    help="show how to fold this arm into the main log, then exit")
    args = ap.parse_args()

    d = out_dir()
    raw_path = os.path.join(d, RAW_FILENAME)
    main_raw = sc.data_path(os.path.join("outputs", "llm_study", "raw_calls.jsonl"))

    if args.print_merge_command:
        print("# Merge the forced arm into the main log, then re-derive everything.")
        print("# Back up first; this appends to the live log.\n")
        print(f"cp '{main_raw}' '{main_raw}.bak'")
        print(f"cat '{raw_path}' >> '{main_raw}'")
        print("python code/llm_study/parse.py")
        print("python code/llm_study/aggregate.py")
        print("python code/landcover_analysis/19_score_all_configs.py")
        print("python code/llm_study/search_behaviour.py --tools on,forced")
        return

    cfg = sc.load_config(args.config)
    slugs, labels = sc.load_categories(cfg)
    categories_block = sc.format_category_list(slugs, labels)
    definitions = sc.load_category_definitions(cfg)
    templates = sc.load_prompt_templates(cfg)
    species = sc.load_species(cfg)

    if args.models:
        keep = {m.strip() for m in args.models.split(",")}
        cfg.models = {k: v for k, v in cfg.models.items() if k in keep}
    if args.prompts:
        keep = {p.strip() for p in args.prompts.split(",")}
        templates = [t for t in templates if t.prompt_id in keep]

    cells = build_cells(cfg, templates, species)
    already = done_cells(raw_path)
    todo = [c for c in cells
            if (c[0], c[1].prompt_id, c[2].get("species_code"), c[3]) not in already]
    if args.limit is not None:
        todo = todo[: max(1, args.limit)]

    n_cfg = len({(m, t.prompt_id) for m, t, _, _ in cells})
    print("=" * 78)
    print("run_forced_arm.py -- the FORCED third arm (tools available AND demanded)")
    print("=" * 78)
    print(f"\n  configurations : {n_cfg}")
    print(f"  species        : {len(species)}   repeats: {cfg.repeats}")
    print(f"  total cells    : {len(cells)}")
    print(f"  already done   : {len(already)}  (resume skips these)")
    print(f"  to run now     : {len(todo)}")
    print(f"  writes to      : {raw_path}")
    print(f"  main log       : UNTOUCHED ({main_raw})")

    est = sum(OBSERVED_COST_PER_CALL.get((m, t.prompt_id), 0.10) for m, t, _, _ in todo)
    per_model: dict[str, float] = collections.defaultdict(float)
    for m, t, _, _ in todo:
        per_model[m] += OBSERVED_COST_PER_CALL.get((m, t.prompt_id), 0.10)
    print(f"\n  Estimated cost (from the 90-call probe's observed $/call):")
    for m in [x for x in MODEL_ORDER if x in per_model]:
        print(f"    {m:<8} ${per_model[m]:7.2f}")
    print(f"    {'TOTAL':<8} ${est:7.2f} USD")

    if args.dry_run or not args.go:
        print("\n" + ("--dry-run: nothing run." if args.dry_run else
                      "Nothing run. Re-invoke with --go to spend money."))
        return

    sc.load_dotenv_if_present()
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ERROR: ANTHROPIC_API_KEY not set. See code/API_KEY_SETUP.md")
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=0)
    provider = WebSearchTools(cfg.tool_config)

    cap = int((cfg.concurrency or {}).get("max", 8))
    workers = max(1, min(args.concurrency, cap))
    print(f"\nRunning {len(todo)} call(s) at concurrency {workers} (cap {cap})...\n")

    lock = threading.Lock()
    counter = {"n": 0, "searched": 0, "cost": 0.0, "errors": 0}
    fh = open(raw_path, "a", encoding="utf-8")

    def do(cell):
        mk, tpl, sp, rep = cell
        model = cfg.models[mk]
        name = sc.species_display_name(sp, cfg)
        prompt = f"{FORCING_INSTRUCTION}\n\n{tpl.render(name, categories_block, definitions)}"
        t0 = time.time()
        err = None
        try:
            resp, retries = rs.call_model(client, model, provider, prompt, cfg)
        except Exception as e:  # noqa: BLE001
            err, resp, retries = f"{type(e).__name__}: {e}", None, 0
        elapsed = time.time() - t0
        if resp is not None:
            usage = provider.extract_usage(resp)
            n_s = int(usage.get("tool_calls_count") or 0)
            tool_tok = usage.get("tool_tokens")
            in_t = int(getattr(resp.usage, "input_tokens", 0) or 0)
            out_t = int(getattr(resp.usage, "output_tokens", 0) or 0)
            text = rs.response_text(resp)
        else:
            n_s, tool_tok, in_t, out_t, text = 0, None, 0, 0, ""
        # Field names match the main run exactly so parse.py/aggregate.py work.
        rec = {
            "model_key": mk, "model_id": model.id, "model_tier": model.tier,
            "prompt_id": tpl.prompt_id, "prompt_label": tpl.label,
            "guidance_level": tpl.guidance_level,
            "tools": TOOLS_VALUE,
            "species_code": sp.get("species_code"),
            "common_name": sp.get("common_name"),
            "red_list_name": sp.get("red_list_name"),
            "species_prompt_name": name,
            "repeat_index": rep,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw_response": text,
            "input_tokens": in_t, "output_tokens": out_t,
            "tool_calls_count": n_s, "tool_tokens": tool_tok,
            "wall_clock_seconds": round(elapsed, 3),
            "cost_usd": round(model.cost_usd(in_t, out_t), 6),
            "api_retries": retries, "error": err,
            "forced_search": True,
        }
        with lock:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            counter["n"] += 1
            counter["cost"] += rec["cost_usd"]
            if n_s:
                counter["searched"] += 1
            if err:
                counter["errors"] += 1
            i = counter["n"]
            flag = "ERR" if err else ("srch" if n_s else " -- ")
            print(f"  [{i:4d}/{len(todo)}] {mk:<7} {tpl.prompt_id:<14} "
                  f"{name[:20]:<20} {flag:<4} {elapsed:6.2f}s "
                  f"${counter['cost']:7.2f} tot", flush=True)
        return rec

    try:
        if workers == 1:
            for c in todo:
                do(c)
        else:
            with cf.ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(do, todo))
    except KeyboardInterrupt:
        print("\nInterrupted. Progress is saved -- re-run the same command to resume.")
    finally:
        fh.close()

    n = counter["n"]
    print(f"\nDone: {n} call(s), {counter['searched']} searched "
          f"({counter['searched'] / n * 100:.1f}%) " if n else "\nDone: 0 calls")
    print(f"Errors: {counter['errors']}   Spent: ${counter['cost']:.2f}")
    if counter["errors"]:
        print("Re-run the same command to retry the errored cells.")
    print(f"\nLog: {raw_path}")
    print("\nNext: python code/llm_study/run_forced_arm.py --print-merge-command")


if __name__ == "__main__":
    main()
