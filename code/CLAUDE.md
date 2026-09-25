# CLAUDE.md

Guidance for working with code in this repository (development notes kept from the project; see the root `README.md` for an overview).

## What this repo is

Code for the MSc thesis "An AI Ecological Co-Scientist" (EAICS). It asks how well a large language model can say which habitats UK red-listed birds are "commonly found in", by building the same **41 species x 9 habitat** presence matrix from four sources and comparing them:

- **Data**: eBird Status 2023 modelled abundance joined to UKCEH Land Cover Map 2023, availability-corrected (selection ratio >= 1).
- **Book**: habitat associations hand-coded from the RSPB Handbook of British Birds.
- **LLM**: a parameter study over models x prompts x web-search tools x repeats.
- **Experts**: a survey of seven ornithologists.

Terminology follows the RSPB Handbook: "commonly found in [habitat]", not "most abundant in [habitat]".

### The study species set

The canonical study set is the **41 focal species in `code/focal_species.json`** (loader: `code/focal_species.py`, which asserts the count). It is the single source of truth shared by every source — eBird data, RSPB Handbook coding, the LLM study and the expert survey — so they cannot drift apart. Note `ebirdst/bocc_birds/red_list.json` is a 70-entry name-only BoCC reference and the `red_list_available` group in `ebirdst/species_list.json` is a 50-species availability set — **neither is the study set**; do not use them as a species source.

The 9 habitat categories are frozen in `code/llm_study/categories.json`; every matrix joins on those slugs.

## Directory structure

```
code/
├── focal_species.json / .py         # CANONICAL 41-species study set + loader
├── ebirdst/                         # eBird Status download, UK crop, land-cover reference
│   ├── pull_and_map.R               # Download a species' 2023 weekly abundance, crop to UK, save TIFs/PNGs
│   ├── download_ebird.R, download_accipitridae.R, demo_download_eursta_local.R  # download helpers
│   ├── 00_create_landcover_reference.R  # ONE-TIME: build the UK-wide land-cover reference
│   ├── adjust_landcover.py          # Post-process the composition reference
│   ├── 04_extract_habitat.R, 05_visualize_habitat.py  # early per-cell extraction + plots (legacy)
│   ├── species_list.json            # Species groups
│   └── bocc_birds/red_list.json     # BoCC red-list reference (names only)
├── UKCEH_data/                      # land-cover grid building and class merging
│   ├── build_landcover_1km_members.R, build_landcover_3km_type_counts.R
│   ├── merge_landcover_classes.py   # Build the merged (Strategy 2 / Strategy 3) composition CSVs
│   └── outputs/README_merged_landcover.md  # merge data dictionary
├── landcover_analysis/              # numbered in run order
│   ├── 01, 03-06                    # early broad-6 abundance summaries (superseded)
│   ├── 07-10                        # aggregate-9, dominant-class attribution (secondary)
│   ├── 11-14                        # aggregate-9, 1 km-weighted attribution
│   ├── 15_selection_ratio_correction.py  # PRIMARY Data matrix: availability-corrected selection ratios
│   ├── 16_data_vs_book_matrix.py    # Data vs Book side by side, scored
│   ├── 17-19                        # LLM and Data scored against the Book; every LLM configuration scored
│   ├── 20-22                        # breadth analysis and the thesis results figures
│   └── _archive_selection_experiments/  # sensitivity checks behind the selection-ratio choice
├── habitat_agents/                  # single-condition LLM agent + the hand-coded Book column (alignment xlsx)
├── prompts/habitat_blind_assessment.md  # prompt used by habitat_agents/
├── llm_study/                       # LLM parameter study (models x prompts x tools x repeats)
│   ├── config.yaml                  # model IDs + pricing, repeats, species source, synonyms
│   ├── categories.json              # the 9 frozen habitat slugs/labels
│   ├── run_study.py / parse.py / aggregate.py   # generate -> parse -> matrices (parsing is separate + re-runnable)
│   ├── prompts/                     # p2_scoped / p3_informed / p4_engineered + category_definitions.md
│   └── README.md, RUN_GUIDE.md      # design notes; cheap-first run order
├── expert_responses/                # tidy the expert survey, inter-expert consistency, LLM vs expert
├── haduk/                           # HadUK-Grid temperature processing (secondary, not in final results)
└── API_KEY_SETUP.md                 # eBird key setup
```

## The pipeline, end to end

1. **Download + crop (R).** `ebirdst/pull_and_map.R` resolves a species to its eBird code, downloads 2023 weekly abundance at 3 km only, crops/masks to the UK, and writes 52 weekly TIFs to `ebirdst/outputs/{code}/tif/{code}_week_NN_uk_abundance.tif`.
2. **Land-cover reference (R, one-time).** `ebirdst/00_create_landcover_reference.R` reads the UKCEH LCM 2023 percentage raster (21 classes, 1 km, EPSG:27700) and produces the UK-wide composition table `UKCEH_data/outputs/ukceh_landcover_composition_3km_wide.csv` (one row per 3 km cell, named `pct_*` columns, `total_pct`, `dominant_class`, `dominant_name`). `adjust_landcover.py` produces the `_adjusted` version used downstream.
3. **Merge land-cover classes (Python).** `UKCEH_data/merge_landcover_classes.py` collapses the 21 classes into the 9-class `strategy2_aggregate9` scheme (primary) and a 6-class `strategy3_broad6` scheme (comparison). The `build_landcover_*` R scripts produce the 1 km type counts per 3 km cell used for 1 km weighting.
4. **Per-habitat abundance (R + Python).** `landcover_analysis/11_redlist_abundance_by_aggregate9_1km_weighted.R` sums each species' 52 weekly TIFs per cell and splits each 3 km cell's yearly abundance across the 9 classes in proportion to its 1 km composition (`w_c = n_c / n_1km_members`, abundance conserved). 12-14 plot and render it. 07-10 are the dominant-class alternative and 03-06 the broad-6 version, kept for reference.
5. **Data matrix (Python).** `15_selection_ratio_correction.py` corrects abundance for habitat availability: a species is "commonly found in" a habitat when its selection ratio (share of abundance / share of available area) is >= 1. This is the Data matrix used in the thesis.
6. **Book matrix.** The RSPB Handbook verdicts were hand-entered into `alignment.xlsx` (built by `habitat_agents/build_alignment_xlsx.py`, patched with the corrected Data by `build_alignment_adjusted_xlsx.py`, labels canonicalised by `normalise_book_column.py`). `16_data_vs_book_matrix.py` puts Data and Book side by side.
7. **LLM matrices (Python).** `llm_study/run_study.py` -> `parse.py` -> `aggregate.py` produce one 41 x 9 matrix per configuration (model x prompt x tools). See `llm_study/README.md` and `RUN_GUIDE.md`.
8. **Expert matrix (Python).** `expert_responses/tidy_responses.py` -> `consistency.py` -> `llm_vs_expert.py`. See `expert_responses/README.md`.
9. **Scoring and figures (Python).** `17`-`19` score LLM and Data against the Book (19 covers every LLM configuration); `20_breadth_vs_verdict.py` tests whether habitat breadth drives verdicts; `21_results_figures.py` and `22_new_aggregate_figures.py` write the thesis tables and figures to `Results figures/` at the repo root.

## Land-cover class schemes

The UKCEH LCM 2023 has **21 target classes** (columns `pct_broadleaf, pct_conifer, pct_arable, pct_improved_grass, pct_neutral_grass, pct_calcareous_grass, pct_acid_grass, pct_fen, pct_heather, pct_heather_grass, pct_bog, pct_inland_rock, pct_saltwater, pct_freshwater, pct_supralittoral_rock, pct_supralittoral_sed, pct_littoral_rock, pct_littoral_sed, pct_saltmarsh, pct_urban, pct_suburban`).

Two merged schemes are produced for comparison (exact mappings in `UKCEH_data/outputs/README_merged_landcover.md`):
- **Strategy 2 (9 classes):** the UKCEH official aggregate scheme, with broadleaf + conifer merged into Woodland.
- **Strategy 3 (6 classes):** broad ecological / RSPB-Handbook grouping (Woodland, Farmland, Semi-natural grassland, Upland, Wetland+freshwater+coastal, Built-up).

Both are drop-in compatible with the downstream pipeline (same `cell_id, x, y, pct_*, total_pct, dominant_class, dominant_name` shape). **Strategy 2 (9 classes) is the primary scheme**; Strategy 3 (6 classes) is retained as a coarser secondary/comparison view.

## Setup and keys

- **eBird Status:** set `EBIRDST_KEY` in `~/.Renviron` (R reads it). Request a key from the Cornell Lab.
- **Anthropic (LLM step):** set `ANTHROPIC_API_KEY` in the repo-root `.env` (Python loads via python-dotenv). `.env` is gitignored.
- See `API_KEY_SETUP.md`. Never commit keys.

**R packages:** ebirdst (v3.x), terra, sf, dplyr, tidyr, ggplot2, rnaturalearth, rnaturalearthdata, here, readr.
**Python:** pandas, numpy; plus anthropic + python-dotenv for the LLM step; matplotlib/seaborn/folium/geopandas for the legacy visualiser.

eBird data cache: `~/Library/Application Support/org.R-project.R/R/ebirdst/{year}/{species_code}/`.

## Key data conventions

- **Join key:** `cell_id` = `{rounded_x}_{rounded_y}` in EPSG:27700. Species abundance joins to land-cover composition on `cell_id`.
- **CRS:** eBird native is Sinusoidal (EPSG:8857); everything is reprojected to British National Grid (EPSG:27700, 3 km) for analysis. UKCEH LCM is native EPSG:27700 at 1 km.
- **Sea/empty cells:** `total_pct == 0` and `dominant_name == "Undocumented"`. Filter these out with a land mask before analysis.
- **eBird abundance definition:** expected count on a 1-hour, 2 km traveling checklist by an expert observer, at optimal time and weather. It is a MODELLED, weather-standardised, climatological estimate for 2023, not a raw count and not weather-responsive. Findings from it are climatological habitat associations, not behavioural claims.

## Critical implementation details (still current)

### Use `as.points()`, never `as.polygons()` (bug fixed 2025-05-26)
`terra::as.polygons()` merges adjacent cells with similar values into a handful of polygons (for Willow Warbler week 20: 20,290 cells collapsed to 7 polygons, 99.97% data loss). `04_extract_habitat.R` uses `terra::as.points()` to convert each raster cell to a centroid point and preserve every cell. Also filter `abundance > 0` before conversion (handles migrants with zero winter cells) and return an empty tibble for zero-observation weeks.

### Point-based habitat extraction
3 km eBird cells vs 1 km UKCEH cells is a 9:1 ratio. Extraction takes the mean of the ~9 intersecting 1 km UKCEH cells per 3 km eBird cell, then determines the dominant class from the aggregated percentages. Use `terra::extract()` explicitly (namespace conflict with `tidyr::extract()`).

### Temperature is a secondary axis
HadUK-Grid tasmax (2023, processed to weekly 3 km) is available but secondary under the land-cover frame. Note eBird Status is weather-standardised, so it cannot capture actual-weather responses regardless of temperature joins. If temperature is ever rejoined, note the eBird-to-HadUK grid offsets differ (asymmetric 3 km offsets: x % 3000 = 2500, y % 3000 = 500).

## Data sources

- **UKCEH Land Cover Map 2023:** 1 km, EPSG:27700, GB, 21 BAP-based target classes. DOI 10.5285/96bc980a-31b4-4d1b-87e9-007d4932a56b. Aggregate scheme and Table 1 in the UKCEH product documentation.
- **eBird Status and Trends 2023:** 3 km native, Sinusoidal (EPSG:8857), 52 weekly layers, relative-abundance units. Key required.
- **HadUK-Grid:** Met Office, 1 km native (aggregated to 3 km), EPSG:27700, tasmax/tasmin, 2023.
