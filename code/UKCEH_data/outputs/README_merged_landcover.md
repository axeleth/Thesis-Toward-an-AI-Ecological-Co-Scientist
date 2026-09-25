# Merged UK land-cover composition (3 km)

Two coarser-granularity land-cover composition datasets, both derived by merging
the 21-class canonical composition into fewer habitat classes. Built so a
downstream fingerprint pipeline can run at two granularities and be compared.

**Primary scheme: Strategy 2 (UKCEH aggregate, 9 classes).** It is the default
scheme the pipeline runs on; Strategy 3 (broad, 6 classes) is retained as a
coarser secondary/comparison view.

**Provenance:** derived from `ukceh_landcover_composition_3km_wide_adjusted.csv`
(itself from UKCEH LCM 2023). Built by `../merge_landcover_classes.py`.

Each merged percentage column is the **row-wise sum** of its member canonical
columns — no percentage mass is created or lost, and every canonical class is
used exactly once per scheme. One row per 3 km cell; `cell_id, x, y, total_pct`
are carried through unchanged. Sea/empty cells (`total_pct == 0`) keep the input
convention: `dominant_class` / `dominant_name` = `Undocumented`.

## Files

| File | Scheme | Merged classes | Role |
|------|--------|----------------|------|
| `ukceh_landcover_composition_3km_strategy2_aggregate9.csv` | Strategy 2 (UKCEH aggregate) | 9 | **primary** |
| `ukceh_landcover_composition_3km_strategy3_broad6.csv` | Strategy 3 (broad) | 6 | secondary |

### 1 km member list (individual squares)

`ukceh_landcover_composition_1km_strategy2_aggregate9.csv` — the individual 1 km
UKCEH squares that the 3 km reference mean-aggregates, kept as their own records
(Strategy 2, 9 classes; GB land only, 242,707 rows). Built by
`../build_landcover_1km_members.R` directly from the 21-class 1 km target raster.

- Same 9 `pct_` columns as the 3 km Strategy 2 file, plus a `parent_cell_id`
  column giving the 3 km reference cell each 1 km square rolls up into.
- `parent_cell_id` is derived from the **identical** 3 km template the reference
  uses, so it joins to the 3 km `cell_id` exactly. Every one of the 28,107
  documented 3 km cells has ≥1 member (median ~9 per parent); no 1 km member
  points to a non-existent 3 km cell.
- Sea/no-data 1 km cells (all-zero) are dropped, so this file has no
  `Undocumented` rows — it is land only.
- `cell_id` here is the **1 km** cell centroid (`{round(x)}_{round(y)}`); columns:
  `cell_id, x, y, parent_cell_id, <9 pct_ columns>, total_pct, dominant_class, dominant_name`.

### 3 km per-type counts (how many 1 km squares of each type)

`ukceh_landcover_composition_3km_strategy2_typecounts.csv` — for each 3 km cell,
the **integer count** of its constituent 1 km squares that are *dominantly* each
of the 9 Strategy 2 classes (28,107 rows, one per documented 3 km cell). Built by
`../build_landcover_3km_type_counts.R` from the 1 km member list.

- Columns: `cell_id, x, y, n_woodland, n_arable, n_improved_grassland,
  n_seminat_grassland, n_mountain_heath_bog, n_saltwater, n_freshwater,
  n_coastal, n_builtup, n_1km_members`.
- The nine `n_` columns sum to `n_1km_members` (the number of 1 km land squares
  in that 3 km cell, ~9; min 1 at coasts, max 16). `cell_id` matches the 3 km
  reference exactly (join back for the mean-percentage view).
- This is a **count**, distinct from the mean-percentage `pct_` columns in
  `..._strategy2_aggregate9.csv`. Each 1 km square is assigned to a single
  dominant class before counting, so it is not the same as summing percentages.

## Column structure (the two 3 km percentage files)

`cell_id, x, y, <merged pct_ columns>, total_pct, dominant_class, dominant_name`

- `dominant_class` — label of the merged class with the highest percentage in the
  row (e.g. `mountain_heath_bog`), or `Undocumented` for sea/empty cells.
- `dominant_name` — human-readable version (e.g. `Mountain, heath and bog`).

## Strategy 2 — UKCEH aggregate, 9 classes (primary)

| Merged column | Human name | Canonical members |
|---------------|-----------|-------------------|
| `pct_woodland` | Woodland | broadleaf, conifer |
| `pct_arable` | Arable | arable |
| `pct_improved_grassland` | Improved grassland | improved_grass |
| `pct_seminat_grassland` | Semi-natural grassland | neutral_grass, calcareous_grass, acid_grass, fen |
| `pct_mountain_heath_bog` | Mountain, heath and bog | heather, heather_grass, bog, inland_rock |
| `pct_saltwater` | Saltwater | saltwater |
| `pct_freshwater` | Freshwater | freshwater |
| `pct_coastal` | Coastal | supralittoral_rock, supralittoral_sed, littoral_rock, littoral_sed, saltmarsh |
| `pct_builtup` | Built-up | urban, suburban |

## Strategy 3 — broad, 6 classes (secondary)

| Merged column | Human name | Canonical members |
|---------------|-----------|-------------------|
| `pct_woodland` | Woodland | broadleaf, conifer |
| `pct_farmland` | Farmland | arable, improved_grass |
| `pct_seminat_grassland` | Semi-natural grassland | neutral_grass, calcareous_grass, acid_grass |
| `pct_upland` | Upland, heath and montane | heather, heather_grass, bog, inland_rock |
| `pct_wetland_coastal` | Wetland, freshwater and coastal | fen, saltwater, freshwater, supralittoral_rock, supralittoral_sed, littoral_rock, littoral_sed, saltmarsh |
| `pct_builtup` | Built-up | urban, suburban |

## Judgment calls

- **fen** differs between schemes (intentional): it is **wetland** in Strategy 3
  (`pct_wetland_coastal`) but **semi-natural grassland** in Strategy 2
  (`pct_seminat_grassland`), following the UKCEH aggregate grouping.
- **woodland** merges broadleaf + conifer in both schemes (structure over
  leaf-type distinction).
- **farmland** (Strategy 3) merges arable + improved_grass into one agricultural
  class; Strategy 2 keeps them separate (`pct_arable`, `pct_improved_grassland`).

Mappings are the source of truth from
`Decisions/2026-07-11 - Land-cover merge strategies (test aggregate vs broad).md`.
