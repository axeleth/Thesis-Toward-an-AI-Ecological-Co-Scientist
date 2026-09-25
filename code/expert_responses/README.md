# Expert survey

The expert reference for the thesis: a survey of seven practising ornithologists
who said, for each of the 41 focal species, which of the 9 habitat categories the
species is commonly found in. The responses themselves are not included in this
repository. This folder holds the code that turns them into a species × habitat
matrix and analyses them.

## How the survey was set up

- **Platform:** a Google Form, exported to CSV via *Responses → Download responses (.csv)*.
- **One question per species**, in the canonical order of `code/focal_species.json`
  (41 questions). Each question is titled `<Species name> [i/41]` and asks:
  > Tick all the habitats where this bird spends a significant proportion of its time.
  > Tick "I don't know" if you are unsure.
- **Answer options (checkboxes, multiple allowed):** the 9 frozen categories from
  `code/llm_study/categories.json`, plus **"I don't know"**:
  Woodland · Arable · Improved grassland · Semi-natural grassland · Mountain, heath and bog ·
  Saltwater · Freshwater · Coastal · Built-up · I don't know
- **Other questions:** name, email address, how long the form took to fill in, and any
  problems met while filling it in.

"I don't know" is kept as its own signal. It is not treated as "no habitats", and it is
excluded from the agreement and consensus calculations (see `consistency.py`).

## Input file format

`tidy_responses.py` reads the raw Google Form CSV export. It needs:

| Column(s) | Header (matched by) | Content |
| --- | --- | --- |
| Timestamp | starts with `Timestamp` | submission time |
| Name | contains `name` | used only to label the respondent's column |
| Email | contains `email` | fallback label if name is blank |
| 41 species columns | `<Species name> [i/41]` (any text after, including newlines) | comma-joined ticks, e.g. `Arable, Improved grassland` or `I don't know` |
| Duration | contains `how long` | free text (kept as metadata) |
| Problems | contains `problems` | free text (kept as metadata) |

One row per respondent. Species names are matched against `common_name`, `red_list_name`
and `scientific_name` in `focal_species.json`, plus a small alias table
(`FORM_NAME_ALIASES`). Habitat labels are matched case-insensitively against
`categories.json`, plus `EXTRA_LABEL_ALIASES` (the deployed form misspelt "heath" as
"heat"). An unknown species or habitat label is a hard error rather than a silent drop.

The question headers contain embedded newlines, so the export looks broken in a plain text
viewer. It isn't: any CSV parser reads it correctly.

## Scripts, in run order

```bash
# 1. Put the Form export in this folder (the newest *.csv is picked up), or pass --csv PATH
python3 code/expert_responses/tidy_responses.py
#    -> code/expert_responses/tidy/expert_responses_wide.csv    species x respondent (raw ticks)
#    -> code/expert_responses/tidy/expert_responses_matrix.csv  species x 9 habitat vote counts
#       (--long also writes one row per species/respondent/habitat tick)

# 2. Per-species inter-expert agreement (Jaccard, Dice, uncertainty rate, knowledge state)
python3 code/expert_responses/consistency.py --real-only
#    -> outputs/expert_survey/species_consistency_real_only.{csv,json} + CONSISTENCY_SUMMARY

# 3. Score every LLM configuration against the expert consensus
#    (needs the LLM study matrices in outputs/llm_study/; see code/llm_study/)
python3 code/expert_responses/llm_vs_expert.py --real-only
#    -> outputs/expert_survey/llm_vs_expert_real_only.{csv,json,md}
```

A habitat counts as **expert-positive** when more than half of the respondents who gave an
opinion on that species ticked it (`MAJORITY = 0.5` in `llm_vs_expert.py`).

`make_synthetic_respondents.py` is a development aid from before all responses had arrived.
It generates clearly labelled fake respondents (`SYNTHETIC_*` columns) with a known
consensus gradient, to check that the consistency metric behaves. It plays no part in the
thesis results. Always use `--real-only` in steps 2 and 3, which drops any synthetic columns.

## Privacy

The raw export and the `tidy/` outputs contain respondents' names (and the raw export
their email addresses), because respondent columns are labelled by name. Both are
gitignored. Keep them out of anything you publish, and pseudonymise respondent labels
before sharing any outputs.
