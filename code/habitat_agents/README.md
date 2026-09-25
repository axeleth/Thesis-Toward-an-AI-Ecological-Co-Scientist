# Habitat-presence research agent (blind)

A stock-LLM (no-retrieval) agent that produces a per-species "commonly found in"
habitat matrix, to be compared against the **data-derived** ground-truth matrix
`outputs/landcover_analysis/redlist_aggregate9_1km_weighted/redlist_aggregate9_1km_weighted_presence_matrix.csv`
(50 red-list species × 9 UKCEH-aggregate habitat categories, 1 km-weighted,
Pareto-80 rule; see `code/landcover_analysis/13_aggregate9_1km_weighted_presence_matrix.py`).

The agent relies **only on the model's inherent knowledge** (no retrieval — the
established Stage-1 condition). One model call per species; the model returns a
JSON array of one verdict per habitat.

> A data-aware "sighted" agent used to exist alongside this one; it has been
> removed. Only the blind agent remains.

## The blind agent (`run_blind_agent.py`)

| | Blind |
|---|---|
| Sees | species name + the 9 habitats (nothing from the data) |
| Decides | Documented / Not established per habitat |
| Matrix built from | its Documented/Not-established verdict |

## The 9 UKCEH-aggregate habitat categories

`woodland`, `arable`, `improved_grassland`, `seminat_grassland`,
`mountain_heath_bog`, `saltwater`, `freshwater`, `coastal`, `builtup` — same slugs
and column order as the data matrix.

## Binary cells (True/False)

Each matrix cell is one of:

- `True`  — **Documented**: the agent can decisively determine the species is
  commonly found in this habitat.
- `False` — **Not established**: the agent cannot decisively determine that —
  whether it knows the species is rare in / absent from the habitat, OR it simply
  cannot say with confidence. "Can't decisively establish it" resolves to False.

There is **no "unsure" / empty cell** in this section. (A "Gap" in the broader
project means there is no *data* on where a species lives — a distinct concept
handled in a later section, not by this agent.)

## Running

```bash
# offline smoke test (no API): writes the output files with deterministic stubs
python code/habitat_agents/run_blind_agent.py   --mock

# live (needs ANTHROPIC_API_KEY in the repo-root .env)
python code/habitat_agents/run_blind_agent.py   --limit 3   # first 3 species
python code/habitat_agents/run_blind_agent.py                # all 50

# OpenAI comparator
python code/habitat_agents/run_blind_agent.py --model gpt-4o
```

Model defaults to Claude Sonnet (`claude-sonnet-4-6`); `--model gpt-4o` switches
backend. Keys are read from the repo-root `.env` (`ANTHROPIC_API_KEY` /
`OPENAI_API_KEY`). All model/temperature constants live
at the top of `_agent_common.py`.

## Plotting the matrix

`plot_presence_matrix.py` renders a presence matrix as a styled PNG + PDF that
matches `outputs/landcover_analysis/redlist_aggregate9_1km_weighted/redlist_aggregate9_1km_weighted_presence_matrix.png`
(same palette, filled-rounded-rectangle-vs-dot encoding, per-column True counts,
alternating rows). It works on the data matrix or the blind agent matrix.

```bash
# the blind agent matrix (default) -> blind_presence_matrix.png/.pdf
python code/habitat_agents/plot_presence_matrix.py

# a specific matrix (e.g. the data-derived ground truth) with a custom title
python code/habitat_agents/plot_presence_matrix.py \
    --matrix outputs/landcover_analysis/redlist_aggregate9_1km_weighted/redlist_aggregate9_1km_weighted_presence_matrix.csv \
    --title "Data (Pareto-80) — habitat presence"
```

Each figure is written next to its input CSV as `<name>.png` and `<name>.pdf`.
Needs `matplotlib` + `pandas`.

## Outputs (under `outputs/habitat_agents/`, git-ignored)

- `blind_presence_matrix.csv` — binary (True/False) matrix, identical column shape
  to the data matrix (directly diffable).
- `blind_verdicts.json` — long-form detail, one row per (species, habitat):
  classification, reasoning, citations, and the raw model response.
- `blind_presence_matrix.png/.pdf` — styled figure from `plot_presence_matrix.py`.

> **No confidence metric (for now).** The agent no longer emits a per-habitat
> `confidence` label. If you later want a signal of *how sure / why* the model is,
> prefer surfacing its **reasoning** — e.g. a chain-of-thought (CoT) or explicit
> per-habitat deliberation step — over a single categorical confidence. See the
> note in the prompt template for where to re-add it.

## Files

- `_agent_common.py` — shared: worktree-aware paths, the 9 categories, Claude/OpenAI
  backends, JSON parsing, roster loader, matrix + verdicts writers.
- `run_blind_agent.py` — the runner.
- `plot_presence_matrix.py` — renders a presence matrix to a styled PNG + PDF.
- `build_alignment_xlsx.py` — builds `alignment.xlsx` (the downstream comparison,
  see below).
- Prompt: `code/prompts/habitat_blind_assessment.md` (the prompt lives in the first
  fenced ``` block; the prose around it never reaches the model).

## Downstream comparison — `alignment.xlsx`

`build_alignment_xlsx.py` builds the three-way cross-check scaffold (one row per
species): **Data** (highest 1 km-weighted abundance share), **Agent** (the blind
agent's single Documented habitat), a **Data–LLM** A/X/? agreement marker, and
blank **Book** / **Data–Book** columns for manual entry from the RSPB Handbook.

```bash
python code/habitat_agents/build_alignment_xlsx.py   # writes alignment.xlsx at the repo root
```

Re-run it after the blind agent finishes so every Agent cell is populated.
