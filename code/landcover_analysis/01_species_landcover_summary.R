# 01_species_landcover_summary.R
# Per-species landcover analysis: fingerprint across UKCEH classes and heterogeneity response
#
# For each species with processed TIFs on the external drive:
#   1. Aggregates 52 weekly abundance TIFs to annual mean
#   2. Joins to UKCEH landcover composition by BNG coordinates
#   3. Computes fingerprint (mean/sd abundance per landcover class)
#   4. Computes heterogeneity response (correlation with Shannon diversity)
#
# Inputs:
#   - /Volumes/Other/ebirdst_outputs/<species_code>/tif/*.tif (52 weekly abundance layers)
#   - code/UKCEH_data/outputs/ukceh_landcover_composition_3km_wide_adjusted.csv
#
# Outputs:
#   - outputs/landcover_analysis/<species_code>/fingerprint.csv
#   - outputs/landcover_analysis/<species_code>/heterogeneity.csv
#   - outputs/landcover_analysis/<species_code>/merged.csv
#   - outputs/landcover_analysis/all_species_fingerprint.csv
#   - outputs/landcover_analysis/all_species_heterogeneity.csv
#   - outputs/landcover_analysis/processing_summary.csv

library(terra)
library(dplyr)
library(readr)
library(here)
library(ebirdst)  # For species name resolution

# === Configuration ===
dominance_threshold <- 50  # Percentage threshold for class dominance
heterogeneity_metric <- "shannon"  # Options: "shannon", "patch_density", "class_count" (only shannon implemented)
abundance_aggregation <- "annual_mean"  # Options: "annual_mean" (only this implemented for now)

# External drive path
external_drive_base <- "/Volumes/Other/ebirdst_outputs"

# UKCEH landcover composition file
landcover_file <- here("code", "UKCEH_data", "outputs", "ukceh_landcover_composition_3km_wide_adjusted.csv")

# Output directory
out_dir_base <- here("outputs", "landcover_analysis")
dir.create(out_dir_base, recursive = TRUE, showWarnings = FALSE)

# === Check external drive ===
cat("\n")
cat("╔════════════════════════════════════════════════════════════════════════════╗\n")
cat("║                                                                            ║\n")
cat("║         Species Landcover Analysis: Fingerprint & Heterogeneity           ║\n")
cat("║                                                                            ║\n")
cat("╚════════════════════════════════════════════════════════════════════════════╝\n")
cat("\n")

cat("Checking external drive...\n")
if (!dir.exists(external_drive_base)) {
  stop(sprintf("External drive not mounted. Please mount the 'Other' drive and ensure %s exists.",
               external_drive_base))
}
if (!file.access(external_drive_base, 4) == 0) {  # 4 = read permission
  stop(sprintf("Cannot read from external drive at %s. Check permissions.", external_drive_base))
}
cat("  ✓ External drive accessible\n\n")

# === Discover species on external drive ===
cat("Discovering species on external drive...\n")
species_dirs <- list.dirs(external_drive_base, full.names = FALSE, recursive = FALSE)
species_codes <- species_dirs[species_dirs != ""]  # Remove empty entries

# Filter to only those with tif subdirectory
species_with_tifs <- character()
for (code in species_codes) {
  tif_dir <- file.path(external_drive_base, code, "tif")
  if (dir.exists(tif_dir)) {
    tif_files <- list.files(tif_dir, pattern = "_week_\\d{2}_uk_abundance\\.tif$", full.names = FALSE)
    if (length(tif_files) > 0) {
      species_with_tifs <- c(species_with_tifs, code)
    }
  }
}

if (length(species_with_tifs) == 0) {
  stop("No species found with weekly TIF files on external drive")
}

cat(sprintf("  Found %d species with TIF data: %s\n",
            length(species_with_tifs),
            paste(head(species_with_tifs, 5), collapse = ", ")))
if (length(species_with_tifs) > 5) {
  cat(sprintf("  ... and %d more\n", length(species_with_tifs) - 5))
}

# === Load eBird species metadata for name resolution ===
cat("\nLoading eBird species metadata...\n")
runs <- ebirdst_runs
cat(sprintf("  ✓ Loaded metadata for %d species\n", nrow(runs)))

# === Load UKCEH landcover composition ===
cat("\nLoading UKCEH landcover composition...\n")
landcover <- read_csv(landcover_file, show_col_types = FALSE)

# Apply land mask: exclude sea cells
land_mask <- landcover$total_pct > 0 & landcover$dominant_name != "Undocumented"
landcover_land <- landcover[land_mask, ]
cat(sprintf("  ✓ Loaded %d land cells (excluded %d sea cells)\n",
            nrow(landcover_land), nrow(landcover) - nrow(landcover_land)))

# Extract percentage columns for Shannon calculation
pct_cols <- grep("^pct_", names(landcover_land), value = TRUE)
# Exclude derived columns
pct_cols <- setdiff(pct_cols, c("pct_woodland"))
cat(sprintf("  Found %d landcover classes: %s\n",
            length(pct_cols),
            paste(gsub("pct_", "", head(pct_cols, 5)), collapse = ", ")))

# === Helper functions ===

# Calculate Shannon diversity index
calc_shannon <- function(proportions) {
  # Convert percentages to proportions (0-1)
  props <- proportions / 100
  # Remove zeros (log(0) is undefined)
  props <- props[props > 0]
  if (length(props) == 0) return(0)
  # Shannon formula: -sum(p * log(p))
  -sum(props * log(props))
}

# Round coordinates to match cell_id format
round_coords <- function(x, y) {
  # Round to nearest integer for cell_id matching
  x_rounded <- round(x)
  y_rounded <- round(y)
  paste0(x_rounded, "_", y_rounded)
}

# === Initialize summary tracking ===
all_fingerprints <- data.frame()
all_heterogeneity <- data.frame()
processing_summary <- data.frame()

# === Main processing loop ===
cat("\n")
cat("════════════════════════════════════════════════════════════════════════════\n")
cat("PROCESSING SPECIES\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

for (i in seq_along(species_with_tifs)) {
  species_code <- species_with_tifs[i]

  cat(sprintf("[%d/%d] Processing %s\n", i, length(species_with_tifs), species_code))

  # Track processing status
  status <- "started"
  error_msg <- NA
  n_cells <- 0

  tryCatch({
    # Get species names from metadata
    species_info <- runs[runs$species_code == species_code, ]
    if (nrow(species_info) > 0) {
      common_name <- species_info$common_name[1]
      scientific_name <- species_info$scientific_name[1]
    } else {
      common_name <- species_code  # Fallback
      scientific_name <- ""
    }
    cat(sprintf("  Species: %s (%s)\n", common_name, scientific_name))

    # Create species output directory
    species_out_dir <- file.path(out_dir_base, species_code)
    dir.create(species_out_dir, recursive = TRUE, showWarnings = FALSE)

    # === Load and aggregate weekly TIFs ===
    cat("  Loading weekly abundance TIFs...\n")
    tif_dir <- file.path(external_drive_base, species_code, "tif")

    # Find all weekly TIFs
    tif_pattern <- sprintf("%s_week_\\d{2}_uk_abundance\\.tif$", species_code)
    tif_files <- list.files(tif_dir, pattern = tif_pattern, full.names = TRUE)

    # Sort to ensure week order
    tif_files <- sort(tif_files)
    n_weeks <- length(tif_files)

    if (n_weeks == 0) {
      stop("No weekly TIF files found")
    }

    cat(sprintf("    Found %d weekly TIF files\n", n_weeks))

    # Load all weeks and stack
    weekly_rasters <- lapply(tif_files, rast)
    weekly_stack <- rast(weekly_rasters)

    # Compute annual mean
    cat("  Computing annual mean abundance...\n")
    if (abundance_aggregation == "annual_mean") {
      annual_abundance <- mean(weekly_stack, na.rm = TRUE)
    } else {
      stop(sprintf("Aggregation method '%s' not implemented", abundance_aggregation))
    }

    # === Reproject to British National Grid if needed ===
    current_crs <- crs(annual_abundance, describe = TRUE)$code
    if (is.na(current_crs)) {
      # Try to get CRS string if code is NA
      current_crs_str <- crs(annual_abundance)
      cat(sprintf("    Current CRS: %s\n", current_crs_str))
    } else {
      cat(sprintf("    Current CRS: EPSG:%s\n", current_crs))
    }

    # Check if reprojection is needed (BNG is EPSG:27700)
    if (is.na(current_crs) || current_crs != "27700") {
      cat("  Reprojecting to British National Grid (EPSG:27700)...\n")

      # Create a template raster with exact 3km resolution aligned to the landcover grid
      # Use extent from landcover data to ensure alignment
      landcover_extent <- c(
        xmin = floor(min(landcover_land$x) / 3000) * 3000,
        xmax = ceiling(max(landcover_land$x) / 3000) * 3000,
        ymin = floor(min(landcover_land$y) / 3000) * 3000,
        ymax = ceiling(max(landcover_land$y) / 3000) * 3000
      )

      template <- rast(
        xmin = landcover_extent["xmin"],
        xmax = landcover_extent["xmax"],
        ymin = landcover_extent["ymin"],
        ymax = landcover_extent["ymax"],
        resolution = 3000,
        crs = "EPSG:27700"
      )

      # Project and resample to align with the template grid
      annual_abundance <- project(annual_abundance, template, method = "bilinear")
      cat("    ✓ Reprojection complete\n")
    }

    # === Convert to points for joining ===
    cat("  Converting to points for spatial join...\n")

    # Convert raster to points (cell centroids)
    abundance_points <- as.points(annual_abundance, values = TRUE, na.rm = TRUE)
    abundance_df <- as.data.frame(abundance_points, geom = "XY")
    names(abundance_df)[names(abundance_df) == "mean"] <- "annual_mean_abundance"

    # Create cell_id for joining
    abundance_df$cell_id <- round_coords(abundance_df$x, abundance_df$y)

    cat(sprintf("    %d cells with non-NA abundance\n", nrow(abundance_df)))

    # Check coordinate ranges (diagnostic for non-UK species)
    x_range <- range(abundance_df$x)
    y_range <- range(abundance_df$y)

    # UK extent in BNG: roughly x: 0-700000, y: 0-1300000
    if (x_range[1] < -10000 || x_range[2] > 800000 ||
        y_range[1] < -10000 || y_range[2] > 1400000) {
      cat(sprintf("    WARNING: Coordinates outside UK range (x: %.0f-%.0f, y: %.0f-%.0f)\n",
                  x_range[1], x_range[2], y_range[1], y_range[2]))
      cat("    This species may not have UK coverage. Skipping.\n")
      stop("Species coordinates outside UK extent")
    }

    # === Join with landcover ===
    cat("  Joining with UKCEH landcover composition...\n")

    # Join by cell_id
    merged <- abundance_df %>%
      inner_join(landcover_land, by = "cell_id", suffix = c("", "_landcover"))

    # Check for coordinate mismatches (diagnostic)
    if ("x_landcover" %in% names(merged)) {
      coord_diff_x <- abs(merged$x - merged$x_landcover)
      coord_diff_y <- abs(merged$y - merged$y_landcover)
      max_diff <- max(c(max(coord_diff_x), max(coord_diff_y)))
      if (max_diff > 1500) {  # Half a cell width
        warning(sprintf("Large coordinate differences detected (max: %.1f m). Check alignment.", max_diff))
      }
      # Clean up duplicate columns
      merged <- merged %>% select(-x_landcover, -y_landcover)
    }

    n_cells <- nrow(merged)
    cat(sprintf("    Matched %d of %d cells (%.1f%%)\n",
                n_cells, nrow(abundance_df),
                100 * n_cells / nrow(abundance_df)))

    if (n_cells == 0) {
      # Diagnostic: show sample coordinates from both datasets
      cat("    DEBUG: Sample abundance coordinates:\n")
      sample_abd <- head(abundance_df, 3)
      for (j in 1:nrow(sample_abd)) {
        cat(sprintf("      cell_id: %s, x: %.1f, y: %.1f\n",
                    sample_abd$cell_id[j], sample_abd$x[j], sample_abd$y[j]))
      }

      cat("    DEBUG: Sample landcover coordinates:\n")
      sample_lc <- head(landcover_land, 3)
      for (j in 1:nrow(sample_lc)) {
        cat(sprintf("      cell_id: %s, x: %.1f, y: %.1f\n",
                    sample_lc$cell_id[j], sample_lc$x[j], sample_lc$y[j]))
      }

      stop("No cells matched between abundance and landcover data")
    }

    # === Calculate heterogeneity score ===
    cat("  Computing heterogeneity scores...\n")

    if (heterogeneity_metric == "shannon") {
      # Calculate Shannon diversity for each cell
      merged$heterogeneity_score <- apply(
        merged[, pct_cols], 1, calc_shannon
      )
    } else {
      stop(sprintf("Heterogeneity metric '%s' not implemented", heterogeneity_metric))
    }

    # === Save merged data ===
    merged_file <- file.path(species_out_dir, "merged.csv")
    write_csv(merged, merged_file)
    cat(sprintf("    Saved merged data (%d cells)\n", nrow(merged)))

    # === Compute fingerprint ===
    cat("  Computing landcover fingerprint...\n")

    fingerprint_rows <- list()

    for (pct_col in pct_cols) {
      # Extract class name from column
      class_name <- gsub("pct_", "", pct_col)
      class_name <- gsub("_", " ", class_name)
      class_name <- paste0(toupper(substring(class_name, 1, 1)), substring(class_name, 2))

      # Find cells where this class exceeds dominance threshold
      dominant_cells <- merged[merged[[pct_col]] > dominance_threshold, ]

      if (nrow(dominant_cells) > 0) {
        mean_abundance <- mean(dominant_cells$annual_mean_abundance, na.rm = TRUE)
        sd_abundance <- sd(dominant_cells$annual_mean_abundance, na.rm = TRUE)
        n_dominant <- nrow(dominant_cells)
      } else {
        mean_abundance <- NA
        sd_abundance <- NA
        n_dominant <- 0
      }

      fingerprint_rows[[pct_col]] <- data.frame(
        ukceh_class_id = which(pct_cols == pct_col),
        ukceh_class_name = class_name,
        pct_column_name = pct_col,
        mean_abundance = mean_abundance,
        sd_abundance = sd_abundance,
        n_cells = n_dominant,
        dominance_threshold = dominance_threshold,
        stringsAsFactors = FALSE
      )
    }

    fingerprint <- do.call(rbind, fingerprint_rows)
    fingerprint_file <- file.path(species_out_dir, "fingerprint.csv")
    write_csv(fingerprint, fingerprint_file)
    cat(sprintf("    Computed fingerprint for %d classes\n", nrow(fingerprint)))

    # Add species info for master table
    fingerprint$species_code <- species_code
    fingerprint$common_name <- common_name
    all_fingerprints <- rbind(all_fingerprints, fingerprint)

    # === Compute heterogeneity correlation ===
    cat("  Computing heterogeneity correlation...\n")

    # Pearson correlation
    pearson_test <- cor.test(merged$annual_mean_abundance,
                             merged$heterogeneity_score,
                             method = "pearson")

    # Spearman correlation
    spearman_test <- cor.test(merged$annual_mean_abundance,
                              merged$heterogeneity_score,
                              method = "spearman")

    heterogeneity_result <- data.frame(
      species_code = species_code,
      common_name = common_name,
      scientific_name = scientific_name,
      heterogeneity_metric = heterogeneity_metric,
      pearson_r = pearson_test$estimate,
      pearson_p = pearson_test$p.value,
      spearman_r = spearman_test$estimate,
      spearman_p = spearman_test$p.value,
      n_cells = n_cells,
      stringsAsFactors = FALSE
    )

    heterogeneity_file <- file.path(species_out_dir, "heterogeneity.csv")
    write_csv(heterogeneity_result, heterogeneity_file)
    cat(sprintf("    Heterogeneity: Pearson r=%.3f (p=%.3e), Spearman r=%.3f (p=%.3e)\n",
                heterogeneity_result$pearson_r, heterogeneity_result$pearson_p,
                heterogeneity_result$spearman_r, heterogeneity_result$spearman_p))

    all_heterogeneity <- rbind(all_heterogeneity, heterogeneity_result)

    status <- "success"
    cat(sprintf("  ✓ Completed %s\n", species_code))

  }, error = function(e) {
    cat(sprintf("  ✗ ERROR: %s\n", e$message))
    status <- "failed"
    error_msg <- as.character(e$message)
  })

  # Add to processing summary
  processing_summary <- rbind(processing_summary, data.frame(
    species_code = species_code,
    common_name = ifelse(exists("common_name"), common_name, NA),
    status = status,
    n_cells = n_cells,
    error = error_msg,
    stringsAsFactors = FALSE
  ))

  # Clean up memory after each species
  if (exists("weekly_stack")) rm(weekly_stack)
  if (exists("annual_abundance")) rm(annual_abundance)
  if (exists("merged")) rm(merged)
  gc()

  cat("\n")
}

# === Save master tables ===
cat("════════════════════════════════════════════════════════════════════════════\n")
cat("SAVING MASTER TABLES\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

# All species fingerprint
if (nrow(all_fingerprints) > 0) {
  all_fingerprints <- all_fingerprints %>%
    select(species_code, common_name, everything())
  all_fingerprints_file <- file.path(out_dir_base, "all_species_fingerprint.csv")
  write_csv(all_fingerprints, all_fingerprints_file)
  cat(sprintf("Saved all_species_fingerprint.csv (%d rows)\n", nrow(all_fingerprints)))
}

# All species heterogeneity
if (nrow(all_heterogeneity) > 0) {
  all_heterogeneity_file <- file.path(out_dir_base, "all_species_heterogeneity.csv")
  write_csv(all_heterogeneity, all_heterogeneity_file)
  cat(sprintf("Saved all_species_heterogeneity.csv (%d species)\n", nrow(all_heterogeneity)))
}

# Processing summary
summary_file <- file.path(out_dir_base, sprintf("processing_summary_%s.csv",
                                                format(Sys.time(), "%Y%m%d_%H%M%S")))
write_csv(processing_summary, summary_file)
cat(sprintf("Saved processing summary (%d species)\n", nrow(processing_summary)))

# === Final summary ===
cat("\n")
cat("════════════════════════════════════════════════════════════════════════════\n")
cat("PROCESSING COMPLETE\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

cat("Summary:\n")
status_table <- table(processing_summary$status)
for (s in names(status_table)) {
  cat(sprintf("  %s: %d species\n", s, status_table[s]))
}

if (sum(processing_summary$status == "failed") > 0) {
  cat("\nFailed species:\n")
  failed <- processing_summary[processing_summary$status == "failed", ]
  for (i in 1:nrow(failed)) {
    cat(sprintf("  %s: %s\n", failed$species_code[i], failed$error[i]))
  }
}

cat(sprintf("\nOutput directory: %s\n", out_dir_base))
cat("\nDone.\n")