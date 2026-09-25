# Run guide — LLM parameter study

How to work through the grid without spending more than the question needs.
The headline rule: **run everything with tools OFF first, look at the results,
and only then decide whether tools-on is worth it.**

## Why cheap-first

The end-to-end test run measured tools-on at roughly **20× the cost** and
**2.5× the latency** of tools-off, because every web search pulls its results
back into the input context:

| | mean $/species | mean latency |
|---|---:|---:|
| tools-off | $0.0006 | 2.5 s |
| tools-on | $0.0121 | 6.2 s |

(Haiku, 2 species, 1 repeat each — indicative, not a benchmark.)

Tools-off across the whole grid is therefore cheap enough to run without much
thought, and it answers the model-size and prompt-design questions on its own.
Tools-on only needs to run where those results say it might change the answer.

## Always dry-run first

`--dry-run` resolves the whole grid and prices it without calling the API:

```bash
python code/llm_study/run_study.py --dry-run
```

Anything over 8 calls refuses to run without `--go`, so the cost is always shown
before it is spent. Check the call count and estimate look right before adding
the flag.

## Step 1 — the main sweep: all models × all prompts, tools OFF

This is the substantive run. 3 models × 3 prompts × 41 species × 3 repeats
= **1,107 calls**.

```bash
python code/llm_study/run_study.py --tools off --dry-run     # check the estimate
python code/llm_study/run_study.py --tools off --go
python code/llm_study/parse.py
python code/llm_study/aggregate.py
```

`repeats: 3` is the default in `config.yaml` and should stay there: these models
are non-deterministic, and per-cell variance is one of the things the study
measures. The majority vote across the 3 repeats produces the boolean matrix and
the `_meanprob` sibling records how split the repeats were.

### Before going further, inspect

Open `outputs/llm_study/SUMMARY.md` and the matrices, and check:

1. **Invalid-output rate per configuration.** Expect it to be highest for the
   least-guided prompt (`p2_scoped`) and for the smallest model. If any cell is
   alarmingly high, improve `parse.py` and re-run it — parsing is a separate
   pass over `raw_calls.jsonl` and costs **nothing** to redo. Do not re-run the
   API for a parsing problem.
2. **Mean habitats selected per species.** A configuration selecting ~9 or ~1 of
   9 categories is a red flag about the prompt, not a finding.
3. **The `_meanprob` matrices.** Cells at 0.33 or 0.67 are where the model
   disagreed with itself across repeats — the stochastic variance the repeats
   exist to expose.
4. **Spot-check a few raw responses** in `raw_calls.jsonl` against the parsed
   vectors, especially any flagged `low_confidence_flag` (the ambiguous
   "farmland" rule).

## Step 2 — tools ON, only if warranted

Add tools-on when the tools-off results leave a question it could answer — for
example if the smaller models look knowledge-limited rather than
instruction-limited. Start with **one** model and **one** prompt rather than the
full sweep:

```bash
python code/llm_study/run_study.py --tools on --models haiku --prompts p3_informed \
    --dry-run
python code/llm_study/run_study.py --tools on --models haiku --prompts p3_informed --go
```

Compare that against the same cell with tools off before widening. The full
tools-on sweep is another 1,107 calls at ~20× the per-call cost, so it should be
a deliberate decision, not the default.

## Cheaper still, while iterating

- `--limit N` — first N species only.
- `--repeats 1` — single repeat while checking plumbing (never for real results).
- `--models haiku` — Haiku is ~5× cheaper than Opus per token.
- `--prompts p2_scoped` — one prompt at a time.

## Resuming

The runner is idempotent on `(model, prompt, tools, species, repeat)`. Re-running
the same command skips completed cells and retries only the ones that errored, so
an interrupted sweep is resumed by simply running it again:

```bash
python code/llm_study/run_study.py --tools off --go     # picks up where it stopped
```

## After any run

```bash
python code/llm_study/parse.py        # raw -> 9-boolean vectors (no API calls)
python code/llm_study/aggregate.py    # matrices, manifest, SUMMARY.md
```

Both are safe to re-run at any time; `parse.py` in particular is meant to be
re-run whenever the parser improves.
