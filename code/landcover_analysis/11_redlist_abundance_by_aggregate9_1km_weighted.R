# 11_redlist_abundance_by_aggregate9_1km_weighted.R
# Total (yearly-summed) eBird Status abundance per UKCEH-aggregate land-cover
# category (Strategy 2, 9 classes) for the 50 BoCC red-list species — but
# attributed to categories by the 1 km land-cover MIX inside each 3 km cell,
# NOT by the single dominant class.
#
# This is the 1 km-weighted sibling of 07_redlist_abundance_by_aggregate9.R.
# Everything is identical (species set, reference grid, abundance stacking and
# resampling, cell_id join) EXCEPT the attribution rule:
#
#   07 (dominant): each 3 km cell is assigned to its ONE dominant class and its
#       whole yearly abundance is summed into that class only.
#
#   11 (this, 1 km-weighted): each 3 km cell is made of ~9 one-km squares, each
#       with its own dominant class (from the typecounts file). A cell's yearly
#       abundance is SPLIT PROPORTIONALLY across the classes its 1 km squares
#       represent. If a cell has abundance A and n_c one-km squares of class c
#       out of N = n_1km_members total, then class c receives:
#             A * (n_c / N)
#       These per-class shares sum back to A (abundance is conserved, not
#       double-counted). A cell can be all one class (all of A to that class) or
#       up to 9 different classes (A split among them by square count).
#
# Reported value per (species, category):
#   sum over land cells of  [ cell yearly abundance * (n_category / n_1km_members) ]
#
# Inputs:
#   - /Volumes/Other/ebirdst_outputs/<species_code>/tif/<code>_week_NN_uk_abundance.tif (52 wks)
#   - code/ebirdst/species_list.json  (red_list_available -> 50 species_codes)
#   - code/UKCEH_data/outputs/ukceh_landcover_composition_3km_strategy2_typecounts.csv
#       (per 3 km cell: n_<class> counts of its 1 km squares + n_1km_members)
#   - code/UKCEH_data/data/gb2023lcm1km_percentage_target.tif  (reference-grid extent)
#
# Outputs (outputs/landcover_analysis/redlist_aggregate9_1km_weighted/):
#   - redlist_abundance_by_aggregate9_1km_weighted_wide.csv  (50 rows: weighted sums per category)
#   - redlist_abundance_by_aggregate9_1km_weighted_long.csv  (450 rows: species x 9 categories, tidy)
#   - processing_log.csv                                     (per-species status / matched cells)

library(terra)
library(dplyr)
library(tidyr)
library(readr)
library(jsonlite)
library(here)

# === Configuration ===
external_drive_base <- "/Volumes/Other/ebirdst_outputs"

# The large UKCEH data files are git-ignored (local-only) and therefore absent
# from git worktrees. Resolve the data root to the MAIN checkout: if we are running
# inside .claude/worktrees/<name>/, strip that suffix to get the real repo root.
here_root <- here()
if (grepl("/\\.claude/worktrees/[^/]+/?$", here_root)) {
  data_root <- sub("/\\.claude/worktrees/[^/]+/?$", "", here_root)
} else {
  data_root <- here_root
}
data_path <- function(...) file.path(data_root, ...)
cat(sprintf("Code root: %s\nData root: %s\n\n", here_root, data_root))

# species_list.json is git-ignored (local-only) -> read from the data root.
species_list_file <- data_path("code", "ebirdst", "species_list.json")

# The typecounts CSV and UKCEH raster are git-ignored -> read from the data root.
# typecounts: per 3 km cell, how many of its 1 km squares are each of the 9
# classes (n_<class>) plus n_1km_members. This is the 1 km mix we weight by.
typecounts_file <- data_path("code", "UKCEH_data", "outputs",
                             "ukceh_landcover_composition_3km_strategy2_typecounts.csv")

# UKCEH percentage raster: used only to rebuild the EXACT 3 km BNG reference grid
# that the composition CSV was generated on (irregular ~3004 m spacing from the
# UKCEH extent split into 3 km cells). Resampling abundance onto this identical
# grid is what makes the round_coords() cell_ids line up on the join.
ukceh_raster_file <- data_path("code", "UKCEH_data", "data",
                               "gb2023lcm1km_percentage_target.tif")

# The 9 aggregate categories, in a fixed order (matches STRATEGY2_MAP / 07).
agg9_categories <- c("woodland", "arable", "improved_grassland",
                     "seminat_grassland", "mountain_heath_bog",
                     "saltwater", "freshwater", "coastal", "builtup")
agg9_labels <- c(
  woodland           = "Woodland",
  arable             = "Arable",
  improved_grassland = "Improved grassland",
  seminat_grassland  = "Semi-natural grassland",
  mountain_heath_bog = "Mountain, heath and bog",
  saltwater          = "Saltwater",
  freshwater         = "Freshwater",
  coastal            = "Coastal",
  builtup            = "Built-up"
)
n_cols <- paste0("n_", agg9_categories)  # count columns in the typecounts file

out_dir <- here("outputs", "landcover_analysis", "redlist_aggregate9_1km_weighted")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
out_wide <- file.path(out_dir, "redlist_abundance_by_aggregate9_1km_weighted_wide.csv")
out_long <- file.path(out_dir, "redlist_abundance_by_aggregate9_1km_weighted_long.csv")
out_log  <- file.path(out_dir, "processing_log.csv")

cat("════════════════════════════════════════════════════════════════════════\n")
cat("Redlist abundance by aggregate-9, 1 km-weighted (proportional split)\n")
cat("════════════════════════════════════════════════════════════════════════\n\n")

# === Round coordinates to match cell_id format (matches existing scripts) ===
round_coords <- function(x, y) {
  paste0(round(x), "_", round(y))
}

# === Check external drive ===
if (!dir.exists(external_drive_base)) {
  stop(sprintf("External drive not mounted: %s. Mount the 'Other' drive and retry.",
               external_drive_base))
}

# === Load the 50 red_list_available species ===
cat("Loading red_list_available species...\n")
species_json <- fromJSON(species_list_file, simplifyDataFrame = FALSE)
if (is.null(species_json[["red_list_available"]])) {
  stop("Key 'red_list_available' not found in species_list.json")
}
rla <- species_json[["red_list_available"]][["species"]]
species_df <- do.call(rbind, lapply(rla, function(s) {
  data.frame(
    species_code    = s$species_code,
    common_name     = s$common_name,
    scientific_name = ifelse(is.null(s$scientific_name), NA, s$scientific_name),
    red_list_name   = ifelse(is.null(s$red_list_name), NA, s$red_list_name),
    stringsAsFactors = FALSE
  )
}))
cat(sprintf("  %d species\n", nrow(species_df)))

# === Load the 1 km typecounts and build per-class WEIGHTS per 3 km cell ===
# weight_c = n_c / n_1km_members  (fraction of the cell's 1 km squares that are
# class c). Rows sum to 1 across the 9 classes. This is the proportional split.
cat("\nLoading 1 km typecounts and computing per-cell class weights...\n")
tc <- read_csv(typecounts_file, show_col_types = FALSE)
stopifnot(all(c("cell_id", "n_1km_members", n_cols) %in% names(tc)))
stopifnot(all(tc$n_1km_members > 0))  # no divide-by-zero

weights <- tc[, c("cell_id", n_cols, "n_1km_members")]
w_cols <- paste0("w_", agg9_categories)
for (k in seq_along(agg9_categories)) {
  weights[[w_cols[k]]] <- weights[[n_cols[k]]] / weights[["n_1km_members"]]
}
# sanity: weights sum to ~1 per row
wsum <- rowSums(weights[w_cols])
cat(sprintf("  %d cells; per-cell weight sums in [%.6f, %.6f] (should be ~1)\n",
            nrow(weights), min(wsum), max(wsum)))
stopifnot(max(abs(wsum - 1)) < 1e-9)
weights_join <- weights[, c("cell_id", w_cols)]

# === Build the exact UKCEH 3 km BNG reference template once ===
cat("\nBuilding UKCEH 3 km reference grid template...\n")
if (!file.exists(ukceh_raster_file)) {
  stop(sprintf("UKCEH raster needed to rebuild the reference grid not found: %s",
               ukceh_raster_file))
}
ukceh_ref <- rast(ukceh_raster_file)
template <- rast(ext(ukceh_ref), resolution = 3000, crs = "EPSG:27700")
cat(sprintf("  Template: res %.1f x %.1f m, %d cells\n",
            res(template)[1], res(template)[2], ncell(template)))

# === Per-species processing ===
process_species <- function(species_code) {
  tif_dir <- file.path(external_drive_base, species_code, "tif")
  if (!dir.exists(tif_dir)) stop(sprintf("TIF dir not found: %s", tif_dir))

  tif_pattern <- sprintf("%s_week_\\d{2}_uk_abundance\\.tif$", species_code)
  tif_files <- sort(list.files(tif_dir, pattern = tif_pattern, full.names = TRUE))
  if (length(tif_files) == 0) stop("No weekly TIF files found")

  # Stack the weekly rasters and SUM across weeks per cell (yearly total).
  weekly_stack <- rast(lapply(tif_files, rast))
  annual_abundance <- sum(weekly_stack, na.rm = TRUE)

  # Reproject/resample onto the UKCEH reference grid if not already BNG.
  current_crs <- crs(annual_abundance, describe = TRUE)$code
  if (is.na(current_crs) || current_crs != "27700") {
    annual_abundance <- project(annual_abundance, template, method = "bilinear")
  }

  # Convert to points (cell centroids); build the cell_id join key.
  abundance_points <- as.points(annual_abundance, values = TRUE, na.rm = TRUE)
  abundance_df <- as.data.frame(abundance_points, geom = "XY")
  names(abundance_df)[names(abundance_df) == "sum"] <- "annual_sum_abundance"
  if (!"annual_sum_abundance" %in% names(abundance_df)) {
    val_col <- setdiff(names(abundance_df), c("x", "y"))[1]
    names(abundance_df)[names(abundance_df) == val_col] <- "annual_sum_abundance"
  }
  abundance_df$cell_id <- round_coords(abundance_df$x, abundance_df$y)
  n_abund <- nrow(abundance_df)

  # Diagnostic: coordinates should sit within the UK BNG extent.
  x_range <- range(abundance_df$x); y_range <- range(abundance_df$y)
  if (x_range[1] < -10000 || x_range[2] > 800000 ||
      y_range[1] < -10000 || y_range[2] > 1400000) {
    stop(sprintf("Coordinates outside UK extent (x: %.0f-%.0f, y: %.0f-%.0f)",
                 x_range[1], x_range[2], y_range[1], y_range[2]))
  }

  # Join to the per-cell class WEIGHTS (only land cells have weights, so this
  # inner join also applies the land mask).
  merged <- abundance_df %>%
    select(cell_id, annual_sum_abundance) %>%
    inner_join(weights_join, by = "cell_id")
  n_matched <- nrow(merged)
  if (n_matched == 0) stop("No cells matched between abundance and typecounts")

  # Proportional attribution: for each class, sum abundance * weight over cells.
  # (weighted column-wise product then colSums — abundance is conserved: the
  #  9 class totals sum to the total matched abundance.)
  wmat <- as.matrix(merged[, w_cols])
  contrib <- wmat * merged$annual_sum_abundance          # cell x class contributions
  weighted_sums <- colSums(contrib, na.rm = TRUE)
  names(weighted_sums) <- agg9_categories

  agg <- tibble(
    dominant_class   = agg9_categories,
    weighted_abundance = as.numeric(weighted_sums[agg9_categories])
  )

  list(agg = agg, n_weeks = length(tif_files),
       n_abund = n_abund, n_matched = n_matched,
       total_matched_abundance = sum(merged$annual_sum_abundance, na.rm = TRUE))
}

cat("\n")
cat("════════════════════════════════════════════════════════════════════════\n")
cat("PROCESSING 50 SPECIES\n")
cat("════════════════════════════════════════════════════════════════════════\n\n")

long_rows <- list()
log_rows <- list()

for (i in seq_len(nrow(species_df))) {
  sc <- species_df$species_code[i]
  cn <- species_df$common_name[i]
  rn <- species_df$red_list_name[i]
  cat(sprintf("[%2d/%d] %-10s %-28s ", i, nrow(species_df), sc, cn))

  res <- tryCatch(process_species(sc), error = function(e) e)

  if (inherits(res, "error")) {
    cat(sprintf("✗ %s\n", conditionMessage(res)))
    log_rows[[i]] <- data.frame(
      species_code = sc, common_name = cn, red_list_name = rn,
      status = "failed", n_weeks = NA_integer_,
      n_abund_cells = NA_integer_, n_matched_cells = NA_integer_,
      match_pct = NA_real_, error = conditionMessage(res),
      stringsAsFactors = FALSE)
    next
  }

  agg <- res$agg
  agg$species_code    <- sc
  agg$common_name     <- cn
  agg$red_list_name   <- rn
  agg$category_label  <- unname(agg9_labels[agg$dominant_class])
  long_rows[[i]] <- agg[, c("species_code", "common_name", "red_list_name",
                            "dominant_class", "category_label",
                            "weighted_abundance")]

  match_pct <- 100 * res$n_matched / res$n_abund
  cat(sprintf("✓ %d wks, %d/%d cells matched (%.1f%%)\n",
              res$n_weeks, res$n_matched, res$n_abund, match_pct))

  log_rows[[i]] <- data.frame(
    species_code = sc, common_name = cn, red_list_name = rn,
    status = "success", n_weeks = res$n_weeks,
    n_abund_cells = res$n_abund, n_matched_cells = res$n_matched,
    match_pct = match_pct, error = NA_character_,
    stringsAsFactors = FALSE)
}

# === Assemble outputs ===
cat("\n════════════════════════════════════════════════════════════════════════\n")
cat("WRITING OUTPUTS\n")
cat("════════════════════════════════════════════════════════════════════════\n\n")

long_df <- bind_rows(long_rows)
long_df <- long_df %>% rename(category = dominant_class)
long_df$category <- factor(long_df$category, levels = agg9_categories)
long_df <- long_df %>% arrange(species_code, category)
long_df <- long_df[, c("species_code", "common_name", "red_list_name",
                       "category", "category_label", "weighted_abundance")]
write_csv(long_df, out_long)
cat(sprintf("Wrote %s (%d rows)\n", out_long, nrow(long_df)))

# Wide: one row per species with weighted_<cat> columns + total.
wide_df <- long_df %>%
  select(species_code, common_name, red_list_name, category, weighted_abundance) %>%
  pivot_wider(names_from = category, values_from = weighted_abundance,
              names_prefix = "weighted_", names_expand = TRUE) %>%
  mutate(total_weighted_abundance =
           rowSums(across(starts_with("weighted_")), na.rm = TRUE))
weighted_cols <- paste0("weighted_", agg9_categories)
wide_df <- wide_df[, c("species_code", "common_name", "red_list_name",
                       weighted_cols, "total_weighted_abundance")]
write_csv(wide_df, out_wide)
cat(sprintf("Wrote %s (%d rows)\n", out_wide, nrow(wide_df)))

log_df <- bind_rows(log_rows)
write_csv(log_df, out_log)
cat(sprintf("Wrote %s (%d rows)\n", out_log, nrow(log_df)))

# === Summary ===
cat("\n────────────────────────────────────────────────────────────────────────\n")
n_ok <- sum(log_df$status == "success")
n_fail <- sum(log_df$status == "failed")
cat(sprintf("Success: %d   Failed: %d\n", n_ok, n_fail))
if (n_fail > 0) {
  cat("Failed species:\n")
  fdf <- log_df[log_df$status == "failed", ]
  for (k in seq_len(nrow(fdf))) {
    cat(sprintf("  %-10s %s\n", fdf$species_code[k], fdf$error[k]))
  }
}
cat("\nDone.\n")
