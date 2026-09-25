#!/usr/bin/env python3
"""aggregate.py  --  parsed calls -> matrices, manifest and summary
===================================================================

Reads `parsed_calls.jsonl` (from parse.py) and writes the study's deliverables:

  matrices/<model>__<prompt_id>__tools-<on|off>.csv
      species x 9 categories, BOOLEAN, aggregated over repeats by MAJORITY VOTE.
      These are the per-configuration answer matrices downstream scoring
      consumes. Column shape matches every other matrix in the repo
      (species_code, common_name, red_list_name, then the 9 slugs) so they diff
      cell-for-cell against the data / Handbook / survey matrices.

  matrices/<...>_meanprob.csv
      the same cells as the FRACTION of repeats that said present (0.0-1.0),
      kept for downstream flexibility -- majority vote throws that away.

  results_long.csv    tidy long form, one row per call.
  run_manifest.json   configs run, species + codes, per-config counts, invalid
                      rates, totals, model IDs and pricing used.
  SUMMARY.md          per-configuration table, also printed to stdout.

Usage
-----
    python code/llm_study/aggregate.py
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _study_common as sc  # noqa: E402


def load_parsed(path: str) -> list[dict]:
    if not os.path.exists(path):
        sys.exit(
            f"ERROR: no parsed calls at {path}\n"
            "Run: python code/llm_study/parse.py"
        )
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        sys.exit(f"ERROR: {path} is empty.")
    return rows


def config_id(row: dict) -> str:
    """Filename-safe id for one configuration cell of the grid."""
    return f"{row['model_key']}__{row['prompt_id']}__tools-{row['tools']}"


def write_matrices(rows, slugs, roster_order, out_dir) -> list[str]:
    """Majority-vote boolean matrix + mean-probability sibling per configuration.

    Invalid calls are EXCLUDED from the vote -- a call the parser could not map
    is not evidence of absence. A cell with no valid repeats is False in the
    boolean matrix and blank in the mean-prob matrix (no evidence either way).
    """
    mdir = os.path.join(out_dir, sc.MATRICES_DIRNAME)
    os.makedirs(mdir, exist_ok=True)

    # (config, species_code, slug) -> [bools from valid repeats]
    votes: dict[tuple[str, str, str], list[bool]] = defaultdict(list)
    species_meta: dict[str, dict] = {}
    configs: set[str] = set()

    for r in rows:
        cid = config_id(r)
        configs.add(cid)
        code = r["species_code"]
        species_meta.setdefault(
            code,
            {
                "species_code": code,
                "common_name": r.get("common_name", ""),
                "red_list_name": r.get("red_list_name", ""),
            },
        )
        if r.get("invalid_flag"):
            continue
        vec = r.get("parsed_vector") or {}
        for s in slugs:
            votes[(cid, code, s)].append(bool(vec.get(s, False)))

    written: list[str] = []
    header = ["species_code", "common_name", "red_list_name"] + slugs
    # Preserve the canonical roster order so matrices are row-aligned to the
    # data / Handbook matrices; species never seen in this run are omitted.
    ordered_codes = [c for c in roster_order if c in species_meta]

    for cid in sorted(configs):
        bool_path = os.path.join(mdir, f"{cid}.csv")
        prob_path = os.path.join(mdir, f"{cid}_meanprob.csv")

        with open(bool_path, "w", encoding="utf-8", newline="") as bf, open(
            prob_path, "w", encoding="utf-8", newline=""
        ) as pf:
            bw = csv.DictWriter(bf, fieldnames=header)
            pw = csv.DictWriter(pf, fieldnames=header)
            bw.writeheader()
            pw.writeheader()

            for code in ordered_codes:
                brow = dict(species_meta[code])
                prow = dict(species_meta[code])
                for s in slugs:
                    v = votes.get((cid, code, s), [])
                    if not v:
                        brow[s] = False
                        prow[s] = ""     # no valid repeats -> no evidence
                        continue
                    frac = sum(1 for x in v if x) / len(v)
                    brow[s] = frac > 0.5           # strict majority
                    prow[s] = round(frac, 4)
                bw.writerow(brow)
                pw.writerow(prow)

        written.extend([bool_path, prob_path])
    return written


def write_results_long(rows, slugs, path) -> None:
    """Tidy long form of every call, for analysis."""
    header = [
        "model_key", "model_id", "model_tier", "prompt_id", "prompt_label",
        "guidance_level", "tools", "species_code", "common_name", "red_list_name",
        "repeat_index", "timestamp", "invalid_flag", "low_confidence_flag",
        "parse_method", "input_tokens", "output_tokens", "tool_calls_count",
        "tool_tokens", "wall_clock_seconds", "cost_usd", "api_retries", "error",
        "n_habitats_selected",
    ] + slugs + ["raw_response"]

    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        for r in rows:
            vec = r.get("parsed_vector") or {}
            out = {k: r.get(k, "") for k in header if k not in slugs}
            for s in slugs:
                out[s] = bool(vec.get(s, False))
            out["n_habitats_selected"] = sum(1 for s in slugs if vec.get(s))
            w.writerow(out)


def summarise(rows, slugs) -> list[dict]:
    """Per-configuration aggregates for SUMMARY.md and the manifest."""
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[config_id(r)].append(r)

    out = []
    for cid in sorted(by):
        rs = by[cid]
        n = len(rs)
        n_invalid = sum(1 for r in rs if r.get("invalid_flag"))
        n_lowconf = sum(1 for r in rs if r.get("low_confidence_flag"))
        n_err = sum(1 for r in rs if r.get("error"))
        valid = [r for r in rs if not r.get("invalid_flag")]
        habitats = [
            sum(1 for s in slugs if (r.get("parsed_vector") or {}).get(s)) for r in valid
        ]
        species = {r["species_code"] for r in rs}
        first = rs[0]
        out.append(
            {
                "config_id": cid,
                "model_key": first["model_key"],
                "model_id": first["model_id"],
                "prompt_id": first["prompt_id"],
                "guidance_level": first.get("guidance_level", ""),
                "tools": first["tools"],
                "calls": n,
                "species": len(species),
                "errors": n_err,
                "invalid": n_invalid,
                "invalid_rate": round(n_invalid / n, 4) if n else 0.0,
                "low_confidence": n_lowconf,
                "mean_latency_s": round(
                    sum(float(r.get("wall_clock_seconds") or 0) for r in rs) / n, 2
                ) if n else 0.0,
                "total_cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in rs), 6),
                "mean_cost_per_species_usd": round(
                    sum(float(r.get("cost_usd") or 0) for r in rs) / max(len(species), 1), 6
                ),
                "mean_habitats_selected": round(sum(habitats) / len(habitats), 2)
                if habitats else 0.0,
                "total_input_tokens": sum(int(r.get("input_tokens") or 0) for r in rs),
                "total_output_tokens": sum(int(r.get("output_tokens") or 0) for r in rs),
                "total_tool_calls": sum(int(r.get("tool_calls_count") or 0) for r in rs),
            }
        )
    return out


def render_summary_table(summary: list[dict]) -> str:
    """The per-configuration table, as markdown (also printed to stdout)."""
    head = (
        "| configuration | calls | mean latency (s) | mean $/species | "
        "invalid rate | mean habitats/species |\n"
        "|---|---:|---:|---:|---:|---:|\n"
    )
    body = "".join(
        f"| `{s['config_id']}` | {s['calls']} | {s['mean_latency_s']:.2f} | "
        f"${s['mean_cost_per_species_usd']:.4f} | {s['invalid_rate'] * 100:.1f}% | "
        f"{s['mean_habitats_selected']:.2f} |\n"
        for s in summary
    )
    return head + body


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    ap.add_argument("--parsed", default=None, help="path to parsed_calls.jsonl")
    args = ap.parse_args()

    cfg = sc.load_config(args.config)
    slugs, _labels = sc.load_categories(cfg)
    roster = sc.load_species(cfg)
    roster_order = [r["species_code"] for r in roster]

    out_dir = sc.ensure_output_dir(cfg)
    parsed_path = args.parsed or os.path.join(out_dir, sc.PARSED_CALLS_FILENAME)
    rows = load_parsed(parsed_path)

    matrices = write_matrices(rows, slugs, roster_order, out_dir)
    long_path = os.path.join(out_dir, sc.RESULTS_LONG_FILENAME)
    write_results_long(rows, slugs, long_path)
    summary = summarise(rows, slugs)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "species": {
            "source": cfg.species_source,
            "count": len(roster),
            "note": (
                "The 41-species study set (FOCAL_SPECIES in "
                "code/landcover_analysis/15_selection_ratio_correction.py). Only the "
                "id columns are read; the habitat cells are never shown to the model."
            ),
            "roster": roster,
        },
        "categories": slugs,
        "models_used": {
            k: {
                "id": m.id,
                "tier": m.tier,
                "input_usd_per_mtok": m.input_usd_per_mtok,
                "output_usd_per_mtok": m.output_usd_per_mtok,
            }
            for k, m in cfg.models.items()
        },
        "call_parameters": {
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "repeats": cfg.repeats,
        },
        "tools": cfg.tool_config,
        "configurations": summary,
        "totals": {
            "calls": len(rows),
            "errors": sum(1 for r in rows if r.get("error")),
            "invalid": sum(1 for r in rows if r.get("invalid_flag")),
            "low_confidence": sum(1 for r in rows if r.get("low_confidence_flag")),
            "input_tokens": sum(int(r.get("input_tokens") or 0) for r in rows),
            "output_tokens": sum(int(r.get("output_tokens") or 0) for r in rows),
            "cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in rows), 6),
            "wall_clock_seconds": round(
                sum(float(r.get("wall_clock_seconds") or 0) for r in rows), 2
            ),
        },
        "outputs": {
            "matrices": [os.path.relpath(p, out_dir) for p in matrices],
            "results_long": sc.RESULTS_LONG_FILENAME,
            "raw_calls": sc.RAW_CALLS_FILENAME,
            "parsed_calls": sc.PARSED_CALLS_FILENAME,
        },
    }
    manifest_path = os.path.join(out_dir, sc.MANIFEST_FILENAME)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    table = render_summary_table(summary)
    t = manifest["totals"]
    summary_md = f"""# LLM parameter study -- run summary

Generated {manifest['generated_at']}

- **Species:** {len(roster)} (`{cfg.species_source}`)
- **Categories:** {len(slugs)}
- **Calls:** {t['calls']}  (errors {t['errors']}, invalid {t['invalid']}, low-confidence {t['low_confidence']})
- **Tokens:** {t['input_tokens']:,} in / {t['output_tokens']:,} out
- **Total cost:** ${t['cost_usd']:.4f} USD
- **Total wall clock:** {t['wall_clock_seconds']:.1f} s

## Per configuration

{table}
### Column meanings

- **mean latency** -- wall-clock seconds per call.
- **mean $/species** -- total configuration cost divided by species covered
  (so it is comparable across different repeat counts).
- **invalid rate** -- share of calls the parser could not confidently map.
  Worth watching per model: invalid-output rate is known to differ by model.
- **mean habitats/species** -- mean number of the 9 categories marked present,
  over valid calls only.

Matrices are in `{sc.MATRICES_DIRNAME}/`; each configuration has a boolean
majority-vote matrix and a `_meanprob` sibling giving the fraction of repeats
that said present.
"""
    summary_path = os.path.join(out_dir, sc.SUMMARY_FILENAME)
    with open(summary_path, "w", encoding="utf-8") as fh:
        fh.write(summary_md)

    print(f"Configurations: {len(summary)}   Calls: {t['calls']}")
    print()
    print(table)
    print(f"Total cost: ${t['cost_usd']:.4f} USD")
    print()
    print("Wrote:")
    print(f"  {summary_path}")
    print(f"  {manifest_path}")
    print(f"  {long_path}")
    print(f"  {len(matrices)} matrix file(s) in {os.path.join(out_dir, sc.MATRICES_DIRNAME)}")


if __name__ == "__main__":
    main()
