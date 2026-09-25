# An AI Ecological Co-Scientist (EAICS): code

Code accompanying the MSc thesis *"An AI Ecological Co-Scientist"* by Axel Ehrnrooth (2026).

The thesis will be available on arXiv: *link to be added*.
<!-- TODO: replace the line above with the arXiv link (https://arxiv.org/abs/XXXX.XXXXX) once it is live -->

The project asks whether large language models can say which habitats UK birds are
"commonly found in", and how their answers compare with three other sources:

- **Data**: eBird Status & Trends 2023 modelled abundance, joined to UKCEH Land Cover Map 2023
  and summarised per habitat (selection-ratio corrected);
- **Book**: habitat associations coded from the RSPB Handbook of British Birds;
- **Experts**: a survey of ornithologists.

All four sources are expressed as the same species × habitat matrix over **41 focal species**
(`code/focal_species.json`) and **9 aggregate UKCEH habitat classes**, then compared with each other.

## Repository layout

```
code/
├── focal_species.json / .py   canonical 41-species study set (single source of truth)
├── ebirdst/                   download + crop eBird weekly abundance rasters (R)
├── UKCEH_data/                land-cover reference grid and class merging (R, Python)
├── landcover_analysis/        per-habitat abundance, selection ratios, data-vs-book-vs-LLM
│                              matrices, scoring and thesis figures (numbered in run order)
├── llm_study/                 LLM parameter study: models × prompts × web-search tools × repeats
├── habitat_agents/            the original single-condition LLM habitat agent
├── expert_responses/          tidy the expert survey and measure inter-expert consistency
├── prompts/                   prompt used by habitat_agents/
└── haduk/                     HadUK-Grid temperature processing (secondary, not used in the final results)
```

Each subfolder has its own README with details. `code/CLAUDE.md` is the development
notes file used while building the project, and it describes the full pipeline end to end.

Scripts expect to be run from the repository root and write to an `outputs/` folder next
to `code/`, for example `python3 code/llm_study/run_study.py --dry-run`.

## Data (not included)

Source data and generated outputs are not distributed here because of their size and licensing.
To reproduce the analysis you need:

| Source | Used for | Where to get it |
| --- | --- | --- |
| eBird Status & Trends 2023 (3 km weekly abundance) | species abundance | the [`ebirdst`](https://ebird.github.io/ebirdst/) R package (needs a free access key) |
| UKCEH Land Cover Map 2023 (1 km percentage raster, GB + NI) | habitat composition | [UKCEH / EIDC](https://www.ceh.ac.uk/data/ukceh-land-cover-maps) |
| HadUK-Grid (optional) | temperature | [CEDA Archive](https://catalogue.ceda.ac.uk/) |

The expert survey responses are not included publicly.

## Setup

- **Python 3.11+**: `pip install -r requirements.txt`
- **R 4.x** with `ebirdst`, `terra`, `sf`, `dplyr`, `tidyr`, `readr`, `ggplot2`, `jsonlite`, `here`, `lubridate`, `rnaturalearth`
- **API keys**: put them in a `.env` file at the repository root (gitignored):
  ```
  EBIRDST_KEY=...          # eBird Status & Trends data access (see code/API_KEY_SETUP.md)
  ANTHROPIC_API_KEY=...    # LLM study and habitat agents
  OPENAI_API_KEY=...       # optional comparator runs
  ```

The LLM study is configured entirely from `code/llm_study/config.yaml`. Run
`python3 code/llm_study/run_study.py --dry-run` to see the full grid and its estimated cost
before making any API calls, and see `code/llm_study/RUN_GUIDE.md` for the recommended run order.

## License

Code is released under the MIT License (see `LICENSE`). Third-party data remains under
its providers' licences.
