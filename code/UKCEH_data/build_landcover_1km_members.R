# build_landcover_1km_members.R
# Build a 1 km land-cover member list (Strategy 2, 9 classes) for GB.
#
# WHY: the 3 km reference (00_create_landcover_reference.R) mean-aggregates the
# ~9 intersecting 1 km UKCEH squares into each 3 km cell. This script keeps those
# individual 1 km squares as their own records so they remain available later,
# while still recording which 3 km cell each one rolls up into (`parent_cell_id`),
# using the IDENTICAL 3 km template so the parent join matches the existing
# reference exactly.
#
# Resolution: 1 km (native UKCEH). Coverage: Great Britain only (matches the
# existing 3 km reference; the NI raster is intentionally excluded).
# Class scheme: Strategy 2 (9 classes) = UKCEH official 10-class aggregate with
# broadleaf + conifer merged into Woodland. Derived by SUMMING the 21 target
# classes (same source of truth as merge_landcover_classes.py), NOT by reading
# the UKCEH aggregate raster.
#
# Output: UKCEH_data/outputs/ukceh_landcover_composition_1km_strategy2_aggregate9.csv
# Columns: cell_id, x, y, parent_cell_id,
#          pct_woodland, pct_arable, pct_improved_grassland, pct_seminat_grassland,
#          pct_mountain_heath_bog, pct_saltwater, pct_freshwater, pct_coastal,
#          pct_builtup, total_pct, dominant_class, dominant_name
#
# Provenance: gb2023lcm1km_percentage_target.tif (UKCEH LCM 2023, 21-class, 1 km,
# EPSG:27700).

suppressWarnings(suppressMessages({
  library(terra)
  library(sf)
  library(dplyr)
  library(tidyr)
  library(readr)
}))

cat("=== 1 km land-cover member list (Strategy 2, 9 classes, GB) ===\n\n")

# --- Paths ------------------------------------------------------------------
# Resolve relative to THIS script's own location (code/UKCEH_data/) so it runs
# from any working directory / checkout.
this_script <- tryCatch(
  normalizePath(sub("^--file=", "",
                    grep("^--file=", commandArgs(FALSE), value = TRUE)[1])),
  error = function(e) NA_character_
)
script_dir <- if (!is.na(this_script)) dirname(this_script) else getwd()

ukceh_pct_file <- file.path(script_dir, "data",
                            "gb2023lcm1km_percentage_target.tif")
output_file    <- file.path(script_dir, "outputs",
                            "ukceh_landcover_composition_1km_strategy2_aggregate9.csv")

# --- 21 canonical target class names (band order = class id 1..21) ----------
canonical_cols <- c(
  "pct_broadleaf", "pct_conifer", "pct_arable", "pct_improved_grass",
  "pct_neutral_grass", "pct_calcareous_grass", "pct_acid_grass", "pct_fen",
  "pct_heather", "pct_heather_grass", "pct_bog", "pct_inland_rock",
  "pct_saltwater", "pct_freshwater", "pct_supralittoral_rock",
  "pct_supralittoral_sed", "pct_littoral_rock", "pct_littoral_sed",
  "pct_saltmarsh", "pct_urban", "pct_suburban"
)

# --- Strategy 2 mapping: merged class -> canonical members ------------------
# Source of truth = merge_landcover_classes.py STRATEGY2_MAP. Order defines the
# output column order.
strategy2_map <- list(
  pct_woodland           = c("pct_broadleaf", "pct_conifer"),
  pct_arable             = c("pct_arable"),
  pct_improved_grassland = c("pct_improved_grass"),
  pct_seminat_grassland  = c("pct_neutral_grass", "pct_calcareous_grass",
                             "pct_acid_grass", "pct_fen"),
  pct_mountain_heath_bog = c("pct_heather", "pct_heather_grass", "pct_bog",
                             "pct_inland_rock"),
  pct_saltwater          = c("pct_saltwater"),
  pct_freshwater         = c("pct_freshwater"),
  pct_coastal            = c("pct_supralittoral_rock", "pct_supralittoral_sed",
                             "pct_littoral_rock", "pct_littoral_sed",
                             "pct_saltmarsh"),
  pct_builtup            = c("pct_urban", "pct_suburban")
)

strategy2_names <- c(
  pct_woodland           = "Woodland",
  pct_arable             = "Arable",
  pct_improved_grassland = "Improved grassland",
  pct_seminat_grassland  = "Semi-natural grassland",
  pct_mountain_heath_bog = "Mountain, heath and bog",
  pct_saltwater          = "Saltwater",
  pct_freshwater         = "Freshwater",
  pct_coastal            = "Coastal",
  pct_builtup            = "Built-up"
)

merged_cols <- names(strategy2_map)

# Audit: every canonical column used exactly once.
used <- unlist(strategy2_map, use.names = FALSE)
stopifnot(
  "every canonical column used exactly once" =
    setequal(used, canonical_cols) && length(used) == length(canonical_cols)
)

# --- Load the 1 km target raster (21 bands) ---------------------------------
cat("Loading UKCEH 1 km percentage raster (21 classes)...\n")
ukceh_pct <- rast(ukceh_pct_file)
stopifnot("expected 21 bands" = nlyr(ukceh_pct) == 21)
names(ukceh_pct) <- canonical_cols
cat(sprintf("  bands: %d   resolution: %.0f x %.0f m   CRS: %s\n\n",
            nlyr(ukceh_pct), res(ukceh_pct)[1], res(ukceh_pct)[2],
            crs(ukceh_pct, describe = TRUE)$code))

# --- Every 1 km cell -> data frame (centre coords + 21 pct values) ----------
cat("Converting 1 km cells to points (centroids)...\n")
xy  <- xyFromCell(ukceh_pct, 1:ncell(ukceh_pct))   # cell-centre coords
vals <- values(ukceh_pct)                          # ncell x 21 matrix
colnames(vals) <- canonical_cols

df <- as.data.frame(vals)
df$x <- xy[, 1]
df$y <- xy[, 2]

# In this GB 1 km raster, no-data (sea / outside-GB) is encoded as 0 across all
# 21 bands, NOT as NA. Set any stray NA to 0, then drop the sea/no-data cells:
# a cell is land iff its 21 percentages sum to > 0. This mirrors the 3 km
# reference, where sea cells collapse to total_pct == 0 / "Undocumented" and are
# land-masked out before analysis. Keeping only land cells makes this a member
# list of the ~9 land 1 km squares that feed each land 3 km cell.
df[canonical_cols][is.na(df[canonical_cols])] <- 0
land <- rowSums(df[canonical_cols]) > 0
cat(sprintf("  total 1 km cells: %d   sea/no-data (dropped): %d   land (kept): %d\n\n",
            nrow(df), sum(!land), sum(land)))
df <- df[land, , drop = FALSE]

# --- 1 km cell_id + 3 km parent_cell_id -------------------------------------
# 1 km cell_id: rounded centroid, same "{round(x)}_{round(y)}" convention.
df$cell_id <- paste(round(df$x), round(df$y), sep = "_")

# parent_cell_id: which 3 km reference cell does this 1 km cell fall in?
# Rebuild the EXACT 3 km template the reference uses: UKCEH raster extent, 3000 m
# resolution, EPSG:27700. Then take the enclosing 3 km cell's centroid, rounded,
# to reproduce the reference cell_id byte-for-byte.
cat("Building the identical 3 km template to derive parent_cell_id...\n")
template_3km <- rast(ext(ukceh_pct), resolution = 3000, crs = "EPSG:27700")
parent_cell  <- cellFromXY(template_3km, cbind(df$x, df$y))   # 3km cell index
parent_xy    <- xyFromCell(template_3km, parent_cell)         # 3km cell centroid
df$parent_cell_id <- paste(round(parent_xy[, 1]), round(parent_xy[, 2]), sep = "_")

# --- Merge 21 -> 9 (row-wise sums) ------------------------------------------
cat("Merging 21 target classes into the 9 Strategy-2 classes...\n")
for (m in merged_cols) {
  df[[m]] <- rowSums(df[strategy2_map[[m]]])
}

# total_pct = sum of the 9 merged (== sum of the 21 canonical, no mass change).
df$total_pct <- rowSums(df[merged_cols])

# dominant class = merged class with the highest percentage; ties -> first.
merged_mat <- as.matrix(df[merged_cols])
dom_idx    <- max.col(merged_mat, ties.method = "first")
dom_col    <- merged_cols[dom_idx]
row_max    <- merged_mat[cbind(seq_len(nrow(merged_mat)), dom_idx)]

is_empty <- df$total_pct == 0 | row_max == 0
df$dominant_class <- ifelse(is_empty, "Undocumented", sub("^pct_", "", dom_col))
df$dominant_name  <- ifelse(is_empty, "Undocumented",
                            unname(strategy2_names[dom_col]))

# --- Final column order ------------------------------------------------------
out <- df[, c("cell_id", "x", "y", "parent_cell_id", merged_cols,
              "total_pct", "dominant_class", "dominant_name")]

# --- Validation report -------------------------------------------------------
cat("\n=== Validation ===\n")
cat(sprintf("1 km member rows written: %d\n", nrow(out)))

# mass preservation on a sample: merged sum == canonical sum
set.seed(0)
s <- sample(seq_len(nrow(df)), min(1000, nrow(df)))
canon_sum  <- rowSums(df[s, canonical_cols])
merged_sum <- rowSums(df[s, merged_cols])
cat(sprintf("max |canonical_sum - merged_sum| over %d sampled rows: %.3e\n",
            length(s), max(abs(canon_sum - merged_sum))))

# how many distinct 3 km parents, and members-per-parent distribution
mpp <- as.integer(table(out$parent_cell_id[out$dominant_class != "Undocumented"]))
cat(sprintf("distinct 3 km parents referenced (documented cells): %d\n",
            length(unique(out$parent_cell_id[out$dominant_class != "Undocumented"]))))
cat(sprintf("1 km members per 3 km parent: min %d / median %d / max %d (expect ~9)\n",
            min(mpp), as.integer(median(mpp)), max(mpp)))

cat("\ncells per dominant merged class:\n")
print(sort(table(out$dominant_class), decreasing = TRUE))

# --- Write -------------------------------------------------------------------
write_csv(out, output_file)
cat(sprintf("\nWrote %s\n  rows: %d   cols: %d\n",
            output_file, nrow(out), ncol(out)))
cat("\n=== Complete ===\n")
