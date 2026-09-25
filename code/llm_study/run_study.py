#!/usr/bin/env python3
"""run_study.py  --  the LLM parameter-study grid runner
========================================================

Runs the cross product

    MODEL (3 Claude tiers) x PROMPT (every template in prompts/)
      x TOOLS (on/off) x SPECIES (41) x REPEATS (N)

and appends one JSON object per call to `outputs/llm_study/raw_calls.jsonl`.

This module ONLY generates and records. It does not parse: the raw response is
stored verbatim and `parse.py` turns it into a 9-boolean vector separately, so
parsing can be improved and re-run without spending another cent.

Properties that matter at this scale
------------------------------------
* Resumable / idempotent on (model, prompt_id, tools, species, repeat_index).
  Completed cells are read back from raw_calls.jsonl at startup and skipped.
* Written as it goes -- append + flush per call. Killing the run loses nothing
  but the in-flight call, and nothing is buffered in memory.
* Transient API errors retried with exponential backoff + jitter; the retry
  count is recorded per call.
* --dry-run resolves the whole grid and prints an ESTIMATED cost without ever
  touching the API. Any non-trivial run then requires --go.

Usage
-----
    python code/llm_study/run_study.py --dry-run
    python code/llm_study/run_study.py --models haiku --prompts naive_stub \\
        --limit 2 --repeats 1 --tools on,off --go
    python code/llm_study/run_study.py --go              # the full grid
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _study_common as sc  # noqa: E402
import tools as T  # noqa: E402

# A run larger than this many calls needs --go.
TRIVIAL_CALL_BUDGET = 8


# ---------------------------------------------------------------------------
# Grid construction
# ---------------------------------------------------------------------------

def build_grid(cfg, model_keys, templates, tool_settings, roster, repeats):
    """Every cell of the cross product, in a stable order."""
    cells = []
    for mk in model_keys:
        for tpl in templates:
            for ts in tool_settings:
                for sp in roster:
                    for r in range(repeats):
                        cells.append(
                            {
                                "model_key": mk,
                                "prompt": tpl,
                                "tools": ts,
                                "species": sp,
                                "repeat_index": r,
                            }
                        )
    return cells


def load_done_keys(raw_path: str) -> set[str]:
    """Recover completed cell keys from a previous run (resumability).

    A cell counts as done only if it recorded no error -- a failed call is
    retried on the next run rather than silently left as a hole.
    """
    done: set[str] = set()
    if not os.path.exists(raw_path):
        return done
    with open(raw_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate a torn final line from a killed run
            if rec.get("error"):
                continue
            done.add(
                sc.cell_key(
                    rec.get("model_key", ""),
                    rec.get("prompt_id", ""),
                    rec.get("tools", ""),
                    rec.get("species_code", ""),
                    int(rec.get("repeat_index", 0)),
                )
            )
    return done


# ---------------------------------------------------------------------------
# The API call
# ---------------------------------------------------------------------------

def is_retryable(exc) -> bool:
    """Transient failures worth another attempt (429, 5xx, connection)."""
    import anthropic

    if isinstance(
        exc,
        (
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.InternalServerError,
        ),
    ):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code >= 500 or exc.status_code == 429
    return False


def call_model(client, model: sc.ModelSpec, provider, prompt: str, cfg):
    """One Messages API call. Returns (response, retries).

    Retries transient errors ourselves so `api_retries` is truthful -- the SDK's
    own retry is disabled at client construction for the same reason.
    """
    import anthropic

    max_attempts = int(cfg.retry.get("max_attempts", 5))
    base = float(cfg.retry.get("base_delay_seconds", 1.0))
    cap = float(cfg.retry.get("max_delay_seconds", 60.0))
    jitter = bool(cfg.retry.get("jitter", True))

    kwargs = {
        "model": model.id,
        "max_tokens": cfg.max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    # Sonnet 5 / Opus 5 reject `temperature` outright (HTTP 400); only send it
    # to models that accept it.
    if model.supports_temperature:
        kwargs["temperature"] = cfg.temperature

    tool_defs = provider.tool_definitions()
    if tool_defs:
        kwargs["tools"] = tool_defs

    retries = 0
    for attempt in range(max_attempts):
        try:
            return client.messages.create(**kwargs), retries
        except anthropic.BadRequestError as e:
            # Defensive: if a model rejects temperature despite config saying
            # otherwise, drop it and retry once rather than losing the cell.
            if "temperature" in str(e).lower() and "temperature" in kwargs:
                kwargs.pop("temperature")
                retries += 1
                continue
            raise
        except Exception as e:  # noqa: BLE001 -- classified by is_retryable
            if attempt >= max_attempts - 1 or not is_retryable(e):
                raise
            delay = min(base * (2**attempt), cap)
            if jitter:
                delay += random.uniform(0, base)
            time.sleep(delay)
            retries += 1
    raise RuntimeError("unreachable: retry loop exhausted")


def response_text(response) -> str:
    """Concatenate the text blocks of a response."""
    parts = []
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Cost estimation (--dry-run)
# ---------------------------------------------------------------------------

def estimate_cost(cfg, cells) -> tuple[float, dict]:
    """Estimated USD for a grid, from token guesses x the pricing table."""
    est = cfg.dry_run_estimate
    in_tok = float(est.get("input_tokens_per_call", 400))
    out_tok = float(est.get("output_tokens_per_call", 600))
    tools_mult = float(est.get("tools_on_input_multiplier", 4.0))

    total = 0.0
    per_model: dict[str, dict] = {}
    for c in cells:
        m = cfg.models[c["model_key"]]
        i = in_tok * (tools_mult if c["tools"] == "on" else 1.0)
        cost = m.cost_usd(int(i), int(out_tok))
        total += cost
        slot = per_model.setdefault(c["model_key"], {"calls": 0, "usd": 0.0})
        slot["calls"] += 1
        slot["usd"] += cost
    return total, per_model


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    ap.add_argument(
        "--models", default=None,
        help="comma-separated subset of model keys (default: all in config)",
    )
    ap.add_argument(
        "--prompts", default=None,
        help="comma-separated prompt ids (filename stems); default all",
    )
    ap.add_argument(
        "--tools", default=None,
        help="comma-separated tool settings: off, on, or 'on,off' (default both)",
    )
    ap.add_argument("--limit", type=int, default=None, help="first N species only")
    ap.add_argument("--repeats", type=int, default=None, help="override config repeats")
    ap.add_argument(
        "--concurrency", type=int, default=None,
        help="parallel in-flight calls (default 1; capped by config)",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="resolve the grid and print estimated cost WITHOUT calling the API",
    )
    ap.add_argument(
        "--go", action="store_true",
        help=f"required to actually run more than {TRIVIAL_CALL_BUDGET} calls",
    )
    ap.add_argument("--out", default=None, help="override raw_calls.jsonl path")
    args = ap.parse_args()

    cfg = sc.load_config(args.config)
    slugs, labels = sc.load_categories(cfg)
    roster = sc.load_species(cfg)
    templates = sc.load_prompt_templates(cfg)
    definitions = sc.load_category_definitions(cfg)

    # --- axis filters ---
    model_keys = list(cfg.models.keys())
    if args.models:
        want = [m.strip() for m in args.models.split(",") if m.strip()]
        unknown = [m for m in want if m not in cfg.models]
        if unknown:
            sys.exit(f"ERROR: unknown model key(s) {unknown}. Known: {model_keys}")
        model_keys = want

    if args.prompts:
        want = [p.strip() for p in args.prompts.split(",") if p.strip()]
        by_id = {t.prompt_id: t for t in templates}
        unknown = [p for p in want if p not in by_id]
        if unknown:
            sys.exit(
                f"ERROR: unknown prompt id(s) {unknown}. Known: {sorted(by_id)}"
            )
        templates = [by_id[p] for p in want]

    tool_settings = list(T.TOOL_SETTINGS)
    if args.tools:
        want = [t.strip().lower() for t in args.tools.split(",") if t.strip()]
        unknown = [t for t in want if t not in T.TOOL_SETTINGS]
        if unknown:
            sys.exit(f"ERROR: unknown tools setting(s) {unknown}. Use 'on' and/or 'off'.")
        tool_settings = want

    if args.limit is not None:
        roster = roster[: args.limit]
    repeats = args.repeats if args.repeats is not None else cfg.repeats

    cells = build_grid(cfg, model_keys, templates, tool_settings, roster, repeats)

    out_dir = sc.ensure_output_dir(cfg)
    raw_path = args.out or os.path.join(out_dir, sc.RAW_CALLS_FILENAME)
    done = load_done_keys(raw_path)
    todo = [
        c
        for c in cells
        if sc.cell_key(
            c["model_key"], c["prompt"].prompt_id, c["tools"],
            c["species"]["species_code"], c["repeat_index"],
        )
        not in done
    ]

    # --- report the resolved grid ---
    est_total, per_model = estimate_cost(cfg, todo)
    print("LLM parameter study -- resolved grid")
    print(f"  models   : {', '.join(f'{k} ({cfg.models[k].id})' for k in model_keys)}")
    print(f"  prompts  : {', '.join(t.prompt_id for t in templates)}")
    print(f"  tools    : {', '.join(tool_settings)}")
    print(f"  species  : {len(roster)}")
    print(f"  repeats  : {repeats}")
    print(f"  cells    : {len(cells)} total")
    print(f"  already done (skipped): {len(cells) - len(todo)}")
    print(f"  to run   : {len(todo)}")
    print()
    print(f"  ESTIMATED COST: ${est_total:.2f} USD")
    for mk, v in per_model.items():
        print(f"    {mk:<8} {v['calls']:>6} calls  ~${v['usd']:.2f}")
    print("  (estimate only -- token guesses x pricing table in config.yaml)")
    print()

    if args.dry_run:
        print("--dry-run: no API calls made.")
        return

    if not todo:
        print("Nothing to do: every cell is already complete.")
        return

    if len(todo) > TRIVIAL_CALL_BUDGET and not args.go:
        sys.exit(
            f"REFUSING to run {len(todo)} calls without --go.\n"
            f"(Anything over {TRIVIAL_CALL_BUDGET} calls needs the explicit flag. "
            "Review the estimated cost above, then re-run with --go.)"
        )

    # --- live run ---
    import anthropic

    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit(
            "ERROR: ANTHROPIC_API_KEY is not set. Add it to the repo-root .env "
            "(see code/API_KEY_SETUP.md) or export it in your shell."
        )
    # max_retries=0: we own the retry loop so api_retries is truthful.
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=0)

    categories_block = sc.format_category_list(slugs, labels)
    providers = {ts: T.get_tool_provider(ts, cfg.tool_config) for ts in tool_settings}

    max_conc = int(cfg.concurrency.get("max", 8))
    conc = args.concurrency or int(cfg.concurrency.get("default", 1))
    conc = max(1, min(conc, max_conc))

    write_lock = threading.Lock()
    counters = {"done": 0, "errors": 0, "cost": 0.0}
    total = len(todo)

    fh = open(raw_path, "a", encoding="utf-8")

    def run_cell(cell) -> None:
        model = cfg.models[cell["model_key"]]
        tpl = cell["prompt"]
        provider = providers[cell["tools"]]
        sp = cell["species"]
        species_name = sc.species_display_name(sp, cfg)
        prompt = tpl.render(species_name, categories_block, definitions)

        started = time.time()
        error = None
        raw_text = ""
        in_tok = out_tok = 0
        retries = 0
        tool_usage = {"tool_calls_count": 0, "tool_tokens": None}

        try:
            resp, retries = call_model(client, model, provider, prompt, cfg)
            raw_text = response_text(resp)
            usage = getattr(resp, "usage", None)
            in_tok = int(getattr(usage, "input_tokens", 0) or 0)
            out_tok = int(getattr(usage, "output_tokens", 0) or 0)
            tool_usage = provider.extract_usage(resp)
        except Exception as e:  # noqa: BLE001 -- recorded, run continues
            error = f"{e.__class__.__name__}: {e}"

        elapsed = time.time() - started
        cost = model.cost_usd(in_tok, out_tok)

        record = {
            "model_key": cell["model_key"],
            "model_id": model.id,
            "model_tier": model.tier,
            "prompt_id": tpl.prompt_id,
            "prompt_label": tpl.label,
            "guidance_level": tpl.guidance_level,
            "tools": cell["tools"],
            "species_code": sp["species_code"],
            "common_name": sp.get("common_name", ""),
            "red_list_name": sp.get("red_list_name", ""),
            "species_prompt_name": species_name,
            "repeat_index": cell["repeat_index"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw_response": raw_text,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "tool_calls_count": tool_usage.get("tool_calls_count", 0),
            "tool_tokens": tool_usage.get("tool_tokens"),
            "wall_clock_seconds": round(elapsed, 3),
            "cost_usd": round(cost, 8),
            "api_retries": retries,
            "error": error,
        }

        # Write immediately; never buffer the run in memory.
        with write_lock:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            counters["done"] += 1
            counters["cost"] += cost
            if error:
                counters["errors"] += 1
            n = counters["done"]
            status = "ERROR" if error else f"{elapsed:.1f}s"
            print(
                f"[{n}/{total}] {cell['model_key']:<7} {tpl.prompt_id:<12} "
                f"tools-{cell['tools']:<3} r{cell['repeat_index']} "
                f"{species_name[:28]:<28} {status}"
            )
            if error:
                print(f"         {error}")

    try:
        if conc == 1:
            for cell in todo:
                run_cell(cell)
        else:
            from concurrent.futures import ThreadPoolExecutor

            print(f"(concurrency: {conc})")
            with ThreadPoolExecutor(max_workers=conc) as pool:
                list(pool.map(run_cell, todo))
    finally:
        fh.close()

    print()
    print(f"Wrote {counters['done']} call(s) to {raw_path}")
    print(f"  actual cost this run: ${counters['cost']:.4f} USD")
    if counters["errors"]:
        print(
            f"  ⚠️  {counters['errors']} call(s) errored -- re-run the same command "
            "to retry just those cells."
        )
    print("\nNext: python code/llm_study/parse.py && python code/llm_study/aggregate.py")


if __name__ == "__main__":
    sc.load_dotenv_if_present()
    main()
