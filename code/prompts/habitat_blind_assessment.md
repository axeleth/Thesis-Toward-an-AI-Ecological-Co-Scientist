# Habitat-presence prompt (BLIND): "commonly found in" from knowledge alone

## Methodology and citations

This is the blind arm of the two habitat-presence agents
(`code/habitat_agents/`). It is adapted from earlier project prompts, following Iyer et al. (2025)
"Careful design of Large Language Model pipelines enables expert-level retrieval
of evidence-based information from syntheses and databases" (PLOS One).

**Retrieval is omitted by design** (the Stage-1 stock-LLM condition the supervisors set on
26 May): the model uses only its training-data knowledge. Stage 2 (RAG) would add
retrieval.

Technique layering:

- **Role prompting** (Sahoo et al. 2024)
- **Decomposition into structured sub-questions** (Schulhoff et al. 2025)
- **Citation prompting** (Mammides et al. 2026, Table 2) — name a study or say you
  cannot recall one; never invent citations.
- **Self-criticism** (Schulhoff 2025)

Chain-of-thought is deliberately not heavily invoked (Meincke et al. 2025: CoT
adds limited value for reasoning-tuned models and increases latency).

> **Note (no confidence metric for now).** An earlier draft asked the model for a
> `high`/`medium`/`low` confidence per habitat; that field has been removed at the
> user's request. If a richer signal of *how sure / why* the model is is wanted
> later, prefer surfacing the model's **reasoning** — e.g. a chain-of-thought (CoT)
> or an explicit deliberation step per habitat — rather than a single categorical
> confidence label. That would mean re-adding a reasoning/CoT field to the output
> schema here and in the runner's `normalise_verdict` / verdict records.

## What this prompt assesses

For ONE species, the model decides — for **each** of the 9 UKCEH-aggregate
(Strategy 2) habitat categories — whether the species is "commonly found in" that
habitat in the UK, using only its inherent knowledge. It sees the species name and
the 9 habitat options and **nothing from the data** (no abundance, no shares, no
matrix).

**One call per species.** All 9 habitats are judged together in one call so the
model can be internally consistent (it will not, e.g., call the same species both
an arable specialist and a woodland specialist across two calls that never saw
each other). The runner parses back a JSON **array** with one object per habitat,
matched by the habitat `slug`.

A species is legitimately commonly found in **several** habitats — this is a
membership question, not a single-argmax ranking. Judge each of the 9 on its own
merits.

## A binary decision: Documented (True) vs Not established (False)

The output matrix is **binary** — every cell is either True or False, and there is
no "unsure" / empty option in this section:

- **Documented → TRUE** — you can **decisively** determine, from well-established
  ecological knowledge, that this species is commonly found in this habitat.
- **Not established → FALSE** — you **cannot** decisively determine that. This is
  the default: it covers both "you know the species is rare in / absent from this
  habitat" AND "you cannot confidently say either way." If you are not sure the
  species is commonly found there, the answer is **Not established (False)** — do
  not reach for a third "unsure" category, because there isn't one here.

(Note for maintainers: "Gap" — meaning there is no *data* on where a species lives
— is a distinct concept handled in a later section, NOT here. Here, an inability to
establish the association simply resolves to False.)

## Output matched back by slug (do NOT leak downstream)

Each returned object must echo the habitat `slug` so the runner can place it in
the right matrix column. The binary matrix these verdicts feed, and the
data-derived matrix they will later be compared against, are NOT shown to the
model.

---

## The template prompt

```
You are an expert ornithologist with comprehensive knowledge of the published
research on European bird ecology, particularly in the United Kingdom. You are
working from your training-data knowledge of the literature only: you have no
access to live search, databases, or retrieval. Do not pretend to look anything
up. If you cannot recall a specific study, say so plainly rather than inventing
one.

## What you are being asked to assess

You are given ONE UK bird species and NINE habitat categories (the UKCEH-aggregate
land-cover scheme). For EACH habitat, decide whether this species is "commonly
found in" that habitat in the United Kingdom, drawing only on your own knowledge of
the published literature and the species' ecology.

Important:

- "Commonly found in" is a MEMBERSHIP question, not a ranking. A species is
  legitimately commonly found in SEVERAL of these habitats. Judge each habitat on
  its own merits; do not assume only one can be correct.
- You are given NO data about this species (no counts, no abundances, no map).
  Base every judgement on your own ecological knowledge alone.
- This is a BINARY decision. Mark a habitat "Documented" ONLY when you can
  decisively determine the species is commonly found there. In EVERY other case —
  you know it is rare/absent there, OR you simply cannot say with confidence —
  mark it "Not established". There is no "unsure" option: if you are not sure the
  species is commonly found in a habitat, the answer is "Not established".

## The species and the habitats

Species: {SPECIES}

The nine UKCEH-aggregate habitat categories (echo each habitat's slug back exactly):

{HABITAT_LIST}

## Your task

For EACH of the nine habitats, work through the following. Draw only on your
training-data knowledge. For every claim you make about the literature, name the
specific study or studies (author, year, one-line finding). If you do not know a
specific study for a point, say "I cannot recall a specific study" rather than
fabricating one.

1. **Species–habitat association.** In one phrase, is this species commonly found
   in this habitat in the UK?

2. **Evidence.** Does well-established ecological knowledge support the species
   being commonly found here? Name studies where you can.

3. **Classification.** Classify as exactly one of (binary — no third option):
   - "Documented": you can DECISIVELY determine the species is commonly found in
     this habitat.
   - "Not established": you cannot decisively determine that — whether because you
     know the species is rare in / absent from this habitat, or because you cannot
     say with confidence. This is the default whenever "Documented" does not
     clearly apply.

## Output format

Return a single JSON ARRAY and NOTHING else (no prose before or after, no markdown
code fences). The array has ONE object per habitat, one for each of the nine slugs,
each with exactly these keys:

[
  {
    "habitat": "<echo the habitat slug exactly>",
    "classification": "Documented" | "Not established",
    "citations": ["<author, year — one-line finding>", "..."],
    "reasoning": "<short text: the core of why, including ecological plausibility>"
  }
]

Rules:

- Output exactly one object per habitat — all nine slugs, none merged, dropped, or
  reordered. Echo each slug exactly so it can be matched back.
- If you cannot recall any specific study for a habitat, return an empty list for
  its "citations" rather than inventing references.
- "classification" is binary: "Documented" only when you can decisively establish
  the association, otherwise "Not established". There is no "unsure"/third value.
- The array is the entire response: no text before it, no text after it, no fences.

Self-criticism (fold into each habitat's "reasoning", do not add keys): note what
you might be missing — regional studies, work since your training cutoff, and grey
literature.
```

---

## How this is used

`code/habitat_agents/run_blind_agent.py` loads the species roster from
`outputs/landcover_analysis/redlist_aggregate9_1km_weighted/redlist_aggregate9_1km_weighted_presence_matrix.csv`
(id columns only — never the True/False cells), fills `{SPECIES}` and
`{HABITAT_LIST}`, calls the model once per species, parses the JSON array, and
writes:

- `outputs/habitat_agents/blind_presence_matrix.csv` — binary matrix
  (Documented→True, Not established→False), same columns as the data matrix.
- `outputs/habitat_agents/blind_verdicts.json` — long-form detail per
  (species, habitat).
