#!/usr/bin/env Rscript
# 19_occupied_range_availability.R
#
# Per-species OCCUPIED-RANGE availability for the aggregate-9 (1 km-weighted) scheme.
#
# WHY
# ---
# 15_selection_ratio_correction.py divides each species' habitat use by a UK-WIDE
# availability denominator. That penalises range-restricted birds: a grebe
# wintering on Scottish sea lochs is scored against Kent arable it will never
# encounter. Because Saltwater is only 1.13% of UK land, dividing by that national
# share inflates its selection ratio mechanically.
#
# The ceiling test (18_ceiling_test.py) made this concrete: species where the data
# over-calls a marine class got WORSE under the correction at a rate of 0.667 vs
# 0.290 otherwise -- exactly the group a UK-wide denominator distorts. Meanwhile a
# blind LLM agent reaches F1 0.699 against the Handbook where the data reaches
# 0.501, so the headroom is real.
#
# THE FIX
# -------
# Restrict availability to each species' OCCUPIED RANGE -- the cells where it
# actually occurs -- so the denominator describes the landscape the bird could
# plausibly have chosen from:
#
#   used[s,h]  = sum over OCCUPIED cells of ( abundance[s,cell] * w_h[cell] )
#   avail[s,h] = sum over OCCUPIED cells of ( w_h[cell] )        <- NO abundance term
#
# Both sums run over the same cells with the same weights; they differ only by the
# abundance factor. That is exactly the "same basis" requirement from script 15,
# now applied per species rather than nationally.
#
# OCCUPANCY THRESHOLD. A cell counts as occupied when annual summed abundance
# exceeds OCC_QUANTILE of the species' own non-zero abundance distribution.
# A strict > 0 rule would sweep in the long tail of near-zero modelled abundance
# that eBird produces almost everywhere, which would drag the denominator back
# toward UK-wide and defeat the purpose. Several thresholds are emitted so the
# downstream scorer can test sensitivity rather than trusting one choice.
#
# This script ONLY writes per-species tables; it computes no selection ratios.
# 20_selection_ratio_occupied.py consumes these and does the scoring.
#
# INPUT  : /Volumes/Other/ebirdst_outputs/<code>/tif/<code>_week_NN_uk_abundance.tif
#          code/UKCEH_data/outputs/ukceh_landcover_composition_3km_strategy2_typecounts.csv
# OUTPUT : outputs/landcover_analysis/selection_corrected/occupied_range/
#            occupied_used_wide.csv        used[s,h] per occupancy threshold
#            occupied_avail_wide.csv       avail[s,h] per occupancy threshold
#            occupied_range_log.csv        per-species diagnostics
#
# Usage: Rscript code/landcover_analysis/19_occupied_range_availability.R

suppressPackageStartupMessages({
  library(terra); library(dplyr); library(readr); library(jsonlite)
})

# --- Occupancy thresholds: quantiles of each species' non-zero abundance ------
# 0.00 = every cell with any abundance at all (closest to the old behaviour).
OCC_QUANTILES <- c(0.00, 0.10, 0.25, 0.50)

agg9_categories <- c("woodland", "arable", "improved_grassland",
                     "seminat_grassland", "mountain_heath_bog",
                     "saltwater", "freshwater", "coastal", "builtup")
n_cols <- paste0("n_", agg9_categories)
w_cols <- paste0("w_", agg9_categories)

external_drive_base <- "/Volumes/Other/ebirdst_outputs"

# Worktree-aware: git-ignored data lives in the MAIN checkout.
args_all <- commandArgs(trailingOnly = FALSE)
file_arg <- sub("^--file=", "", args_all[grep("^--file=", args_all)])
script_dir <- normalizePath(dirname(file_arg))
code_root <- normalizePath(file.path(script_dir, "..", "..", ".."))
m <- regmatches(code_root, regexec("^(.*)/\\.claude/worktrees/[^/]+$", code_root))[[1]]
data_root <- if (length(m) == 2) m[2] else code_root
data_path <- function(...) file.path(data_root, ...)

species_list_file <- data_path("code", "ebirdst", "species_list.json")
typecounts_file <- data_path("code", "UKCEH_data", "outputs",
                             "ukceh_landcover_composition_3km_strategy2_typecounts.csv")
ukceh_raster_file <- data_path("code", "UKCEH_data", "data",
                               "gb2023lcm1km_percentage_aggregate.tif")

out_dir <- data_path("outputs", "landcover_analysis", "selection_corrected",
                     "occupied_range")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
out_used  <- file.path(out_dir, "occupied_used_wide.csv")
out_avail <- file.path(out_dir, "occupied_avail_wide.csv")
out_log   <- file.path(out_dir, "occupied_range_log.csv")

round_coords <- function(x, y) paste0(round(x), "_", round(y))

cat(strrep("=", 78), "\n")
cat("19_occupied_range_availability.R -- per-species occupied-range denominator\n")
cat(strrep("=", 78), "\n\n")
cat("Resolved paths:\n")
cat(sprintf("  data root   : %s\n", data_root))
cat(sprintf("  TIF source  : %s\n", external_drive_base))
cat(sprintf("  typecounts  : %s\n", typecounts_file))
cat(sprintf("  output dir  : %s\n\n", out_dir))

if (!dir.exists(external_drive_base)) {
  stop(sprintf("External drive not mounted: %s. Mount 'Other' and retry.",
               external_drive_base))
}
if (!file.exists(typecounts_file)) stop(sprintf("Missing typecounts: %s", typecounts_file))

# === Species roster ===
species_json <- fromJSON(species_list_file, simplifyDataFrame = FALSE)
rla <- species_json[["red_list_available"]][["species"]]
species_df <- do.call(rbind, lapply(rla, function(s) {
  data.frame(species_code = s$species_code,
             common_name  = s$common_name,
             red_list_name = ifelse(is.null(s$red_list_name), NA, s$red_list_name),
             stringsAsFactors = FALSE)
}))
cat(sprintf("Species: %d\n", nrow(species_df)))

# === Per-cell class weights (identical construction to script 11) ===
cat("Loading 1 km typecounts -> per-cell class weights...\n")
tc <- read_csv(typecounts_file, show_col_types = FALSE)
stopifnot(all(c("cell_id", "n_1km_members", n_cols) %in% names(tc)))
stopifnot(all(tc$n_1km_members > 0))
weights <- tc[, c("cell_id", n_cols, "n_1km_members")]
for (k in seq_along(agg9_categories)) {
  weights[[w_cols[k]]] <- weights[[n_cols[k]]] / weights[["n_1km_members"]]
}
wsum <- rowSums(weights[w_cols])
stopifnot(max(abs(wsum - 1)) < 1e-9)   # weights must partition the cell
weights_join <- weights[, c("cell_id", w_cols)]
cat(sprintf("  %d land cells with weights (this is also the land mask)\n\n",
            nrow(weights_join)))

# === UKCEH 3 km template (for reprojection when needed) ===
if (!file.exists(ukceh_raster_file)) stop(sprintf("Missing UKCEH raster: %s", ukceh_raster_file))
ukceh_ref <- rast(ukceh_raster_file)
template <- rast(ext(ukceh_ref), resolution = 3000, crs = "EPSG:27700")

# === Per-species ===
process_species <- function(species_code) {
  tif_dir <- file.path(external_drive_base, species_code, "tif")
  if (!dir.exists(tif_dir)) stop(sprintf("TIF dir not found: %s", tif_dir))
  pat <- sprintf("%s_week_\\d{2}_uk_abundance\\.tif$", species_code)
  tifs <- sort(list.files(tif_dir, pattern = pat, full.names = TRUE))
  if (length(tifs) == 0) stop("No weekly TIFs found")

  annual <- sum(rast(lapply(tifs, rast)), na.rm = TRUE)
  cur <- crs(annual, describe = TRUE)$code
  if (is.na(cur) || cur != "27700") annual <- project(annual, template, method = "bilinear")

  pts <- as.points(annual, values = TRUE, na.rm = TRUE)
  df <- as.data.frame(pts, geom = "XY")
  vcol <- setdiff(names(df), c("x", "y"))[1]
  names(df)[names(df) == vcol] <- "abundance"
  df$cell_id <- round_coords(df$x, df$y)

  merged <- df %>%
    select(cell_id, abundance) %>%
    inner_join(weights_join, by = "cell_id")
  if (nrow(merged) == 0) stop("No cells matched typecounts")

  wmat <- as.matrix(merged[, w_cols])
  nz <- merged$abundance[merged$abundance > 0]

  rows_used <- list(); rows_avail <- list()
  for (q in OCC_QUANTILES) {
    thr <- if (length(nz) == 0) 0 else if (q == 0) 0 else as.numeric(quantile(nz, q))
    occ <- merged$abundance > thr
    n_occ <- sum(occ)
    if (n_occ == 0) {          # degenerate: keep any positive cell
      occ <- merged$abundance > 0
      n_occ <- sum(occ)
    }
    # used   = sum over occupied cells of abundance * weight
    # avail  = sum over the SAME cells of weight alone (no abundance factor)
    used_v  <- colSums(wmat[occ, , drop = FALSE] * merged$abundance[occ], na.rm = TRUE)
    avail_v <- colSums(wmat[occ, , drop = FALSE], na.rm = TRUE)

    rows_used[[as.character(q)]] <- c(list(occ_quantile = q, occ_threshold = thr,
                                           n_occupied_cells = n_occ),
                                      setNames(as.list(used_v), agg9_categories))
    rows_avail[[as.character(q)]] <- c(list(occ_quantile = q, occ_threshold = thr,
                                            n_occupied_cells = n_occ),
                                       setNames(as.list(avail_v), agg9_categories))
  }
  list(used = bind_rows(rows_used), avail = bind_rows(rows_avail),
       n_cells_matched = nrow(merged), n_cells_positive = length(nz))
}

used_all <- list(); avail_all <- list(); log_all <- list()
n <- nrow(species_df)
for (i in seq_len(n)) {
  sc <- species_df$species_code[i]
  cat(sprintf("[%2d/%d] %-28s ", i, n, species_df$common_name[i]))
  res <- tryCatch(process_species(sc), error = function(e) e)
  if (inherits(res, "error")) {
    cat(sprintf("FAILED: %s\n", conditionMessage(res)))
    log_all[[sc]] <- data.frame(species_code = sc,
                                common_name = species_df$common_name[i],
                                status = "failed", n_cells_matched = NA,
                                n_cells_positive = NA,
                                error = conditionMessage(res),
                                stringsAsFactors = FALSE)
    next
  }
  meta <- data.frame(species_code = sc,
                     common_name = species_df$common_name[i],
                     red_list_name = species_df$red_list_name[i],
                     stringsAsFactors = FALSE)
  used_all[[sc]]  <- cbind(meta, res$used)
  avail_all[[sc]] <- cbind(meta, res$avail)
  log_all[[sc]] <- data.frame(species_code = sc,
                              common_name = species_df$common_name[i],
                              status = "success",
                              n_cells_matched = res$n_cells_matched,
                              n_cells_positive = res$n_cells_positive,
                              error = NA, stringsAsFactors = FALSE)
  cat(sprintf("ok  %6d cells, %6d positive\n",
              res$n_cells_matched, res$n_cells_positive))
}

used_df  <- bind_rows(used_all)
avail_df <- bind_rows(avail_all)
log_df   <- bind_rows(log_all)

write_csv(used_df, out_used)
write_csv(avail_df, out_avail)
write_csv(log_df, out_log)

cat("\n", strrep("=", 78), "\n", sep = "")
cat(sprintf("Wrote %s  (%d rows)\n", out_used, nrow(used_df)))
cat(sprintf("Wrote %s  (%d rows)\n", out_avail, nrow(avail_df)))
cat(sprintf("Wrote %s\n", out_log))
cat(sprintf("Success: %d / %d species; thresholds per species: %s\n",
            sum(log_df$status == "success"), n,
            paste(OCC_QUANTILES, collapse = ", ")))

# Sanity: at q=0 the occupied-range used totals should closely track script 11's
# UK-wide used totals (same cells, same weights) -- a drift check on the join.
q0 <- used_df %>% filter(occ_quantile == 0)
cat(sprintf("\nAt q=0: mean occupied cells %.0f (range %.0f-%.0f)\n",
            mean(q0$n_occupied_cells), min(q0$n_occupied_cells),
            max(q0$n_occupied_cells)))
cat("Next: python code/landcover_analysis/20_selection_ratio_occupied.py\n")
