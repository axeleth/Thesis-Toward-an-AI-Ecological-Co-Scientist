# 07_redlist_abundance_by_aggregate9.R
# Total (yearly-summed) eBird Status abundance per UKCEH-aggregate land-cover
# category (Strategy 2, 9 classes) for the 50 BoCC red-list species that have
# abundance rasters downloaded.
#
# This is the 9-class sibling of 03_redlist_abundance_by_broad6.R. Same method,
# same reference grid, same join — only the land-cover scheme differs (Strategy 2
# aggregate9 instead of Strategy 3 broad6), and outputs go to a separate folder.
#
# For each of the 50 species in the `red_list_available` group of
# code/ebirdst/species_list.json:
#   1. Stack the 52 weekly abundance TIFs and SUM them per cell
#      (yearly total abundance per cell, NOT the mean of the weeks).
#   2. Reproject/resample onto the exact UKCEH 3 km BNG reference grid.
#   3. Convert to points, join to the 9-class (Strategy 2 "aggregate9") landcover
#      composition by cell_id.
#   4. Assign each cell to its single dominant land-cover class (dominant_class),
#      then SUM the per-cell yearly totals within each of the 9 categories.
#
# Reported value per (species, category):
#   sum over cells whose dominant_class == category of
#     [ sum over the 52 weeks of that cell's abundance ]
#
# Inputs:
#   - /Volumes/Other/ebirdst_outputs/<species_code>/tif/<code>_week_NN_uk_abundance.tif (52 wks)
#   - code/ebirdst/species_list.json  (red_list_available -> 50 species_codes)
#   - code/UKCEH_data/outputs/ukceh_landcover_composition_3km_strategy2_aggregate9.csv
#   - code/UKCEH_data/data/gb2023lcm1km_percentage_target.tif  (reference-grid extent)
#
# Outputs (outputs/landcover_analysis/redlist_aggregate9/):
#   - redlist_abundance_by_aggregate9_wide.csv  (50 rows: sums + cell counts per category)
#   - redlist_abundance_by_aggregate9_long.csv  (450 rows: species x 9 categories, tidy)
#   - processing_log.csv                        (per-species status / matched cells / errors)

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

# The composition CSV and UKCEH raster are git-ignored -> read from the data root.
landcover_file <- data_path("code", "UKCEH_data", "outputs",
                            "ukceh_landcover_composition_3km_strategy2_aggregate9.csv")

# UKCEH percentage raster: used only to rebuild the EXACT 3 km BNG reference grid
# that the composition CSV was generated on (irregular ~3004 m spacing from the
# UKCEH extent split into 3 km cells). Resampling abundance onto this identical
# grid is what makes the round_coords() cell_ids line up on the join.
ukceh_raster_file <- data_path("code", "UKCEH_data", "data",
                               "gb2023lcm1km_percentage_target.tif")

# The 9 aggregate categories, in a fixed order. These are the `dominant_class`
# slugs in the aggregate9 CSV (col `dominant_class`); the order matches the
# STRATEGY2_MAP dict order in merge_landcover_classes.py. `dominant_name` holds
# the human-readable versions, kept only for a readable label in the long output.
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

out_dir <- here("outputs", "landcover_analysis", "redlist_aggregate9")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
out_wide <- file.path(out_dir, "redlist_abundance_by_aggregate9_wide.csv")
out_long <- file.path(out_dir, "redlist_abundance_by_aggregate9_long.csv")
out_log  <- file.path(out_dir, "processing_log.csv")

cat("════════════════════════════════════════════════════════════════════════\n")
cat("Redlist abundance by UKCEH-aggregate 9 land-cover category (yearly sum)\n")
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

# === Load UKCEH aggregate-9 composition, mask sea/empty cells ===
cat("\nLoading UKCEH aggregate-9 landcover composition...\n")
landcover <- read_csv(landcover_file, show_col_types = FALSE)
land_mask <- landcover$total_pct > 0 & landcover$dominant_class != "Undocumented"
landcover_land <- landcover[land_mask, c("cell_id", "x", "y", "dominant_class")]
cat(sprintf("  %d land cells (excluded %d sea/empty cells)\n",
            nrow(landcover_land), nrow(landcover) - nrow(landcover_land)))

# Sanity: the dominant_class values should be exactly our 9 categories
dc_vals <- sort(unique(landcover_land$dominant_class))
cat(sprintf("  dominant_class values present: %s\n", paste(dc_vals, collapse = ", ")))
unexpected <- setdiff(dc_vals, agg9_categories)
if (length(unexpected) > 0) {
  warning(sprintf("Unexpected dominant_class values (not in the 9 categories): %s",
                  paste(unexpected, collapse = ", ")))
}

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
  # Fallback if the layer name is not "sum"
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

  # Join to landcover -> each cell gets one dominant_class (one of the 9 classes).
  merged <- abundance_df %>%
    select(cell_id, annual_sum_abundance) %>%
    inner_join(landcover_land, by = "cell_id")
  n_matched <- nrow(merged)
  if (n_matched == 0) stop("No cells matched between abundance and landcover")

  # Aggregate: sum the per-cell yearly totals within each dominant class.
  agg <- merged %>%
    group_by(dominant_class) %>%
    summarise(summed_abundance = sum(annual_sum_abundance, na.rm = TRUE),
              n_cells = n(), .groups = "drop")

  # Ensure all 9 categories present (fill missing with 0).
  agg <- tibble(dominant_class = agg9_categories) %>%
    left_join(agg, by = "dominant_class") %>%
    mutate(summed_abundance = tidyr::replace_na(summed_abundance, 0),
           n_cells = tidyr::replace_na(n_cells, 0L))

  list(agg = agg, n_weeks = length(tif_files),
       n_abund = n_abund, n_matched = n_matched)
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
                            "summed_abundance", "n_cells")]

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
# rename dominant_class -> category for the tidy output
long_df <- long_df %>% rename(category = dominant_class)
# fixed category ordering
long_df$category <- factor(long_df$category, levels = agg9_categories)
long_df <- long_df %>% arrange(species_code, category)
# put a readable label column right after the slug
long_df <- long_df[, c("species_code", "common_name", "red_list_name",
                       "category", "category_label", "summed_abundance", "n_cells")]
write_csv(long_df, out_long)
cat(sprintf("Wrote %s (%d rows)\n", out_long, nrow(long_df)))

# Wide: one row per species with sum_<cat> and n_<cat> columns.
wide_sum <- long_df %>%
  select(species_code, common_name, red_list_name, category, summed_abundance) %>%
  pivot_wider(names_from = category, values_from = summed_abundance,
              names_prefix = "sum_", names_expand = TRUE)
wide_n <- long_df %>%
  select(species_code, category, n_cells) %>%
  pivot_wider(names_from = category, values_from = n_cells,
              names_prefix = "n_", names_expand = TRUE)
wide_df <- wide_sum %>%
  left_join(wide_n, by = "species_code") %>%
  mutate(
    total_summed_abundance = rowSums(across(starts_with("sum_")), na.rm = TRUE),
    total_cells = rowSums(across(starts_with("n_")), na.rm = TRUE)
  )
# Column order: id cols, the 9 sum cols, the 9 n cols, totals
sum_cols <- paste0("sum_", agg9_categories)
n_cols   <- paste0("n_",   agg9_categories)
wide_df <- wide_df[, c("species_code", "common_name", "red_list_name",
                       sum_cols, n_cols,
                       "total_summed_abundance", "total_cells")]
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
