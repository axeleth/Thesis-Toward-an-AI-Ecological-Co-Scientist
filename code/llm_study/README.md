# LLM parameter study

Asks a stock LLM which of the **9 UKCEH-aggregate habitat categories** each
red-list bird species is "commonly found in", across a **grid of configurations**,
and records the answer plus its cost, latency and invalid-output rate.

This generalises the single-condition agent in `code/habitat_agents/`
(one model, one prompt, no tools, one repeat) into a parameter sweep:

```
MODEL (haiku | sonnet | opus)
  x PROMPT (every template in prompts/ -- the naive-to-guided axis)
  x TOOLS  (off = model knowledge only | on = server-side web search)
  x SPECIES (41)
  x REPEATS (default 3, to measure stochastic variance)
```

Downstream (**not** this module) each per-configuration matrix is scored against
three sources of truth: the eBird-derived data matrix, the RSPB Handbook, and
the expert survey.

## Quick start

```bash
# 1. offline parser unit cases -- no API, no files touched
python code/llm_study/parse.py --self-test

# 2. resolve the full grid and see the estimated cost -- no API calls
python code/llm_study/run_study.py --dry-run

# 3. a cheap subset (Haiku only, 2 species, 1 repeat, both tool settings)
python code/llm_study/run_study.py --models haiku --prompts p2_scoped \
    --limit 2 --repeats 1 --tools on,off --go

# 4. parse the raw responses, then build matrices + summary
python code/llm_study/parse.py
python code/llm_study/aggregate.py
```

Anything over 8 calls refuses to run without `--go`, after printing the
estimated cost.

## Generation and parsing are separate, on purpose

`run_study.py` stores the **raw** response verbatim and nothing else.
`parse.py` turns raw responses into 9-boolean vectors as a separate pass over
`raw_calls.jsonl`. So the parser can be improved and re-run over an existing run
**at zero API cost** — which matters, because the naive prompts are the ones
whose output is hardest to parse and most expensive to regenerate.

The parser is deliberately the only place that absorbs format messiness. **Do
not add a format instruction to a naive prompt to make parsing easier** — that
would contaminate the naive condition, which is exactly the thing being measured.

### How parsing works

One consistent method for structured and free-text answers alike:

1. **JSON** — if the response contains valid JSON naming categories, use it.
   Handles bare lists, `{slug: bool}` maps, wrapper keys, and per-habitat
   objects (including the `{"habitat":..., "classification":"Documented"}` shape
   the existing `habitat_agents` prompt produces).
2. **Names, then synonyms** — case-insensitive whole-word matching against the
   nine category names, then the synonym map in `config.yaml`. Simple plurals
   are matched ("estuaries" finds "estuary").
3. **Neither** → the call is flagged `invalid`. Invalid rates are reported per
   configuration, since invalid-output rate is known to differ by model.

Two behaviours worth knowing:

- **Negation is not presence.** "It is *not* found in woodland; it prefers
  coastal cliffs" yields coastal only. Negated spans are stripped before matching.
- **"farmland" is ambiguous.** It spans Arable *and* Improved Grassland, so with
  no finer detail it maps to **both** and the call is flagged
  `low_confidence_flag` for review. If the text also says something
  arable-specific or grassland-specific, that finer evidence wins and no flag is
  raised.

## Configuration

Everything tunable lives in **`config.yaml`** — model IDs and per-model pricing,
temperature, repeats, the species source, prompt/output paths, retry and
concurrency settings, the web-search tool version, and the synonym map. No model
ID or price is hardcoded in the Python.

`categories.json` holds the 9 habitat slugs and labels. **They are frozen**:
byte-identical to `13_aggregate9_1km_weighted_presence_matrix.py`,
`15_selection_ratio_correction.py`, `habitat_agents/_agent_common.py` and the
R-generated long CSV. Downstream scoring joins on these strings, and a mismatch
produces a silently empty column rather than an error — so don't rename them.

### Species: the 41 study set

Loaded from **`code/focal_species.json`** — the canonical single source of
truth, via the shared loader `code/focal_species.py`. The eBird analysis
(scripts 15/16), the RSPB Handbook coding, this study and the expert survey all
read that same file, which is what keeps the four sources on the same species.
The loader asserts exactly **41** and exits otherwise.

Species are shown to the model by their **British**
vernacular name (`red_list_name`, e.g. "Slavonian grebe"), not the eBird
American form ("Horned Grebe"), because the study is about UK literature.

> Note: `code/ebirdst/bocc_birds/red_list.json` holds **70** name-only entries
> and the `red_list_available` group in `species_list.json` holds **50** (those
> with downloaded eBird rasters). Neither is the study set.

## Prompt templates

Drop any `.md` file into `prompts/` and it becomes part of the grid. Placeholders
substituted wherever they appear (a simple template may use only `{SPECIES}`):

| Placeholder | Filled with |
|---|---|
| `{SPECIES}` | the species common name |
| `{CATEGORIES}` | the nine category names, newline-joined |
| `{CATEGORY_DEFINITIONS}` | a short gloss per category, from `prompts/category_definitions.md` if present (else empty) |

If the markdown contains a fenced ``` block, only that block is sent to the
model and the surrounding prose is treated as methodology notes (matching
`code/prompts/habitat_blind_assessment.md`). A file with no fence is sent whole.

Record each template in **`prompts/manifest.csv`** (`filename,label,guidance_level`)
for reporting. A template absent from the manifest defaults to label = filename
stem and guidance level `unspecified`.

The three installed templates form the naive-to-guided axis:

| template | label | guidance |
|---|---|---|
| `p2_scoped.md` | Scoped | low — bare question, no format instruction |
| `p3_informed.md` | Informed | moderate — expert framing, definitions, guidance |
| `p4_engineered.md` | Engineered | high — role, reasoning steps, JSON output contract |

`category_definitions.md` supplies `{CATEGORY_DEFINITIONS}` for p3 and p4. Its
category names are **byte-identical to `categories.json`** — the parser matches
exact names first, so any drift there would silently cost recall.

## Tools axis

`tools.py` defines a small `ToolProvider` interface with two implementations:
`NoTools` (send no tools) and `WebSearchTools` (Anthropic **server-side** web
search — no client-side execution loop needed).

To swap in a fixed-literature-corpus retriever later, add one class implementing
`name`, `tool_definitions()` and `extract_usage()`, and point `config.yaml` at
it. The runner, parser and aggregator do not change.

The web-search tool `type` is version-pinned in config. The installed
`anthropic` SDK (0.75.0) ships `web_search_20250305`; the newer
`web_search_20260209` with dynamic filtering needs a much newer SDK — bump the
config value after upgrading.

## Cost control and robustness

- **Resumable / idempotent** on `(model, prompt_id, tools, species, repeat_index)`.
  Completed cells are recovered from `raw_calls.jsonl` at startup and skipped, so
  a killed run resumes exactly where it stopped. Cells that **errored** are not
  treated as done — re-running the same command retries just those.
- **Written as it goes** — append + flush per call. Nothing is buffered in
  memory, so nothing is lost if the run dies.
- **Retries** transient errors (429 / 5xx / connection) with exponential backoff
  and jitter, recording `api_retries` per call. The SDK's own retry is disabled
  (`max_retries=0`) so that count is truthful.
- **`--dry-run`** resolves the whole grid and prints an estimated cost without
  touching the API. **`--go`** is required for any run over 8 calls.
- **Axis filters** — `--models`, `--prompts`, `--tools`, plus `--limit` and
  `--repeats` — so a cheap subset can be run first (Opus and web search are the
  expensive combinations).
- **Concurrency** is off by default (`--concurrency N`, capped in config).

`temperature` is sent only to models whose config says they accept it — Sonnet 5
and Opus 5 reject the parameter outright (HTTP 400).

## Outputs (`outputs/llm_study/`)

| File | What it is |
|---|---|
| `raw_calls.jsonl` | **the audit trail** — one object per call, appended as it happens, with the verbatim response and all telemetry |
| `parsed_calls.jsonl` | the same rows plus `parsed_vector`, `invalid_flag`, `low_confidence_flag`, `parse_method` |
| `results_long.csv` | tidy long form for analysis |
| `matrices/<model>__<prompt>__tools-<on\|off>.csv` | **the deliverable** — species × 9 boolean matrix, majority vote over repeats |
| `matrices/<...>_meanprob.csv` | same cells as the fraction of repeats saying present |
| `run_manifest.json` | configs run, the 41 species + codes, per-config counts, invalid rates, totals, model IDs and pricing used |
| `SUMMARY.md` | per-configuration table (also printed to stdout) |

Invalid calls are **excluded** from the majority vote — a response the parser
couldn't map is not evidence of absence. A cell with no valid repeats is `False`
in the boolean matrix and blank in the mean-prob matrix.

`outputs/` is gitignored, so study outputs are local-only.

## Files

| File | Role |
|---|---|
| `config.yaml` | every tunable: models + pricing, repeats, paths, synonyms, tools |
| `categories.json` | the 9 frozen habitat slugs and labels |
| `_study_common.py` | worktree-aware paths, config/category/roster/prompt loading, cell key |
| `tools.py` | the pluggable tool-provider interface |
| `run_study.py` | the grid runner (generation only) |
| `parse.py` | raw → 9-boolean vector, standalone and re-runnable |
| `aggregate.py` | matrices, manifest, summary |
