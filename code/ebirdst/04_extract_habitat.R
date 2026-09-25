# 04_extract_habitat.R
# Extract dominant land cover class for species abundance rasters
#
# Purpose: For each grid cell in weekly/seasonal abundance rasters,
#          extract the dominant land cover class using polygon-based aggregation
#          of ~9 intersecting 1km UKCEH cells per 3km eBird cell
#
# Architecture:
#   - Land cover composition is stored separately in UKCEH_data/outputs/ukceh_landcover_composition_3km_wide.csv
#     (generated once using 00_create_landcover_reference.R)
#   - This script creates lightweight species-specific files with only:
#     period, cell_id, x, y, abundance, dominant_class, dominant_name
#
# Outputs:
#   - {species_code}_abundance_weekly.csv - Species abundance with dominant habitat
#   - {species_code}_habitat_extraction_log.csv - Processing log
#
# Note: For full habitat composition percentages, join output with
#       UKCEH_data/outputs/ukceh_landcover_composition_3km_wide.csv using cell_id

library(terra)
library(sf)
library(dplyr)
library(tidyr)
library(readr)
library(here)

# === Configuration ===
species_code <- "wlwwar"  # Willow Warbler

# Time period options:
# For seasonal data: c("breeding", "nonbreeding", "prebreeding_migration", "postbreeding_migration")
# For weekly data: sprintf("week_%02d", 1:52)

# TEST MODE: Set to TRUE to process only first 3 weeks for testing
TEST_MODE <- FALSE

# LONG FORMAT: Set to FALSE to disable long format generation (saves time and space)
# Long format is currently DISABLED (commented out in code)
# To re-enable, uncomment the long format sections in extract_composition() and output writing
GENERATE_LONG_FORMAT <- FALSE

# Willow Warbler weekly data
if (TEST_MODE) {
  time_periods <- sprintf("week_%02d", 20:22)  # Test with breeding season weeks (May)
  cat("*** TEST MODE: Processing weeks 20-22 (breeding season) ***\n\n")
} else {
  time_periods <- sprintf("week_%02d", 1:52)  # Full 52 weeks
}

# Input paths
ebird_dir <- here("outputs", "tif")
ukceh_dom_file <- here("..", "UKCEH_data", "data", "gb2023lcm1km_dominant_target.tif")
ukceh_pct_file <- here("..", "UKCEH_data", "data", "gb2023lcm1km_percentage_target.tif")

# Output paths
out_dir <- here("outputs")
out_abundance <- file.path(out_dir, paste0(species_code, "_abundance_weekly.csv"))
out_log <- file.path(out_dir, paste0(species_code, "_habitat_extraction_log.csv"))

# === Land Cover Class Lookup Table ===
# UKCEH Land Cover Map 2023 - 21 Target Classes
landcover_names <- c(
  "1" = "Broadleaved woodland",
  "2" = "Coniferous woodland",
  "3" = "Arable",
  "4" = "Improved grassland",
  "5" = "Neutral grassland",
  "6" = "Calcareous grassland",
  "7" = "Acid grassland",
  "8" = "Fen, Marsh and Swamp",
  "9" = "Heather and shrub",
  "10" = "Heather grassland",
  "11" = "Bog",
  "12" = "Inland rock",
  "13" = "Saltwater",
  "14" = "Freshwater",
  "15" = "Supralittoral rock",
  "16" = "Supralittoral sediment",
  "17" = "Littoral rock",
  "18" = "Littoral sediment",
  "19" = "Saltmarsh",
  "20" = "Urban",
  "21" = "Suburban"
)

cat("=== Habitat Extraction Pipeline ===\n")
cat(sprintf("Species: %s\n", species_code))
cat(sprintf("Time periods to process: %d\n", length(time_periods)))
cat(sprintf("UKCEH dominant file: %s\n", basename(ukceh_dom_file)))
cat(sprintf("UKCEH percentage file: %s\n", basename(ukceh_pct_file)))
cat("\n")

# === Load UKCEH Land Cover Rasters ===
cat("Loading UKCEH Land Cover Map 2023...\n")

# Load dominant class raster (for legacy point-based extraction)
cat("  Loading dominant class raster...\n")
ukceh_dom <- rast(ukceh_dom_file)
cat(sprintf("    CRS: %s\n", crs(ukceh_dom, describe = TRUE)$code))
cat(sprintf("    Resolution: %.0f x %.0f meters\n", res(ukceh_dom)[1], res(ukceh_dom)[2]))

# Load percentage composition raster (for new polygon-based extraction)
cat("  Loading percentage composition raster...\n")
ukceh_pct <- rast(ukceh_pct_file)
cat(sprintf("    Layers: %d (one per habitat class)\n", nlyr(ukceh_pct)))
cat(sprintf("    CRS: %s\n", crs(ukceh_pct, describe = TRUE)$code))
cat(sprintf("    Resolution: %.0f x %.0f meters\n", res(ukceh_pct)[1], res(ukceh_pct)[2]))

# Get unique land cover classes present in the data
unique_classes <- unique(values(ukceh_dom, na.rm = TRUE))
cat(sprintf("    Unique land cover classes: %d\n", length(unique_classes)))
cat(sprintf("    Class range: %d to %d\n", min(unique_classes), max(unique_classes)))
cat("\n")

# === Define Dominant Habitat Extraction Function ===
# Extracts dominant land cover class for each eBird grid cell
# by aggregating the ~9 intersecting 1km UKCEH cells at cell centroids

extract_dominant_habitat <- function(ebird_raster, ukceh_pct_raster, period_name) {
  # Filter raster to only cells with abundance > 0 BEFORE conversion
  cat("    Filtering to cells with abundance > 0...\n")
  ebird_filtered <- ebird_raster
  ebird_filtered[ebird_filtered <= 0] <- NA

  n_cells_total <- sum(!is.na(values(ebird_raster)))
  n_cells_filtered <- sum(!is.na(values(ebird_filtered)))
  cat(sprintf("    Cells with data: %d, Cells with abundance > 0: %d\n",
              n_cells_total, n_cells_filtered))

  # Handle case where no cells have abundance > 0 (e.g., winter weeks for migrants)
  if (n_cells_filtered == 0) {
    cat("    No cells with abundance > 0 - skipping period\n")
    return(tibble(
      period = character(),
      cell_id = character(),
      x = numeric(),
      y = numeric(),
      abundance = numeric(),
      dominant_class = integer(),
      dominant_name = character()
    ))
  }

  # Convert to points (cell centroids) to preserve individual cells
  cat("    Converting to points (cell centroids)...\n")
  ebird_points <- as.points(ebird_filtered, values = TRUE, na.rm = TRUE)

  # Convert to sf for easier manipulation
  ebird_sf <- st_as_sf(ebird_points)
  colnames(ebird_sf)[1] <- "abundance"  # Rename first column to abundance

  # Get coordinates from point geometries
  coords <- st_coordinates(ebird_sf)

  ebird_sf$x <- coords[, 1]
  ebird_sf$y <- coords[, 2]
  ebird_sf$cell_id <- paste(round(ebird_sf$x), round(ebird_sf$y), sep = "_")

  cat(sprintf("    Created %d individual cell points\n", nrow(ebird_sf)))

  # Extract percentage values for all 21 layers at each point
  # Use terra::extract explicitly to avoid conflict with tidyr::extract
  cat("    Extracting land cover percentages (this may take a few minutes)...\n")
  extracted <- terra::extract(ukceh_pct_raster, vect(ebird_sf), na.rm = TRUE)

  # Calculate dominant class from the 21 percentage layers
  cat("    Calculating dominant habitat class...\n")

  # Find which layer has the maximum value for each cell (rows)
  pct_matrix <- as.matrix(extracted[, -1])  # Remove ID column, keep only percentages
  dominant_class <- apply(pct_matrix, 1, which.max)  # Returns class 1-21

  # Create lightweight output dataframe with only essential columns
  result <- tibble(
    period = period_name,
    cell_id = ebird_sf$cell_id,
    x = ebird_sf$x,
    y = ebird_sf$y,
    abundance = ebird_sf$abundance,
    dominant_class = dominant_class,
    dominant_name = landcover_names[as.character(dominant_class)]
  )

  return(result)
}

# === Process Each Week ===
all_abundance <- list()
log_list <- list()

for (i in seq_along(time_periods)) {
  period <- time_periods[i]

  cat(sprintf("--- Processing period %d/%d: %s ---\n", i, length(time_periods), period))

  # Build eBird raster filename
  ebird_file <- file.path(ebird_dir, sprintf("%s_%s_uk_abundance.tif", species_code, period))

  # Check if file exists
  if (!file.exists(ebird_file)) {
    cat(sprintf("  ERROR: File not found: %s\n", ebird_file))
    log_list[[i]] <- tibble(period = period, status = "FAIL_FILE_NOT_FOUND", n_cells = 0)
    next
  }

  # Load eBird abundance raster
  cat(sprintf("  Loading: %s\n", basename(ebird_file)))
  ebird <- rast(ebird_file)

  # Check and reproject CRS if needed
  ebird_crs <- crs(ebird, describe = TRUE)$code
  target_crs <- "EPSG:27700"  # British National Grid

  if (is.na(ebird_crs) || ebird_crs != target_crs) {
    cat(sprintf("  Reprojecting from %s to %s...\n",
                ifelse(is.na(ebird_crs), "unknown CRS", ebird_crs),
                target_crs))
    ebird <- project(ebird, target_crs)
  } else {
    cat(sprintf("  CRS already %s, no reprojection needed\n", target_crs))
  }

  # Extract dominant habitat using polygon-based aggregation
  cat("  Extracting dominant habitat (polygon-based)...\n")
  abundance_result <- extract_dominant_habitat(ebird, ukceh_pct, period)

  n_cells <- nrow(abundance_result)
  cat(sprintf("  Extracted %d cells with abundance data\n", n_cells))

  # Summary statistics
  cat("  Dominant habitat distribution:\n")
  class_counts <- abundance_result %>% count(dominant_class, dominant_name, sort = TRUE)
  for (j in 1:min(5, nrow(class_counts))) {
    cat(sprintf("    %2d %-25s: %4d cells (%.1f%%)\n",
                class_counts$dominant_class[j],
                class_counts$dominant_name[j],
                class_counts$n[j],
                100 * class_counts$n[j] / n_cells))
  }
  if (nrow(class_counts) > 5) {
    cat(sprintf("    ... and %d more classes\n", nrow(class_counts) - 5))
  }

  # Store results
  all_abundance[[i]] <- abundance_result
  log_list[[i]] <- tibble(
    period = period,
    status = "OK",
    n_cells = n_cells,
    n_unique_classes = n_distinct(abundance_result$dominant_class)
  )

  cat("\n")
}

# === Write Outputs ===
cat("=== Writing Outputs ===\n")

# Write log
log_df <- bind_rows(log_list)
write_csv(log_df, out_log)
cat(sprintf("Log file: %s\n", out_log))

# Write abundance data with dominant habitat
if (length(all_abundance) > 0) {
  abundance_df <- bind_rows(all_abundance) %>%
    arrange(period, cell_id)

  write_csv(abundance_df, out_abundance)
  cat(sprintf("Weekly abundance data: %s\n", out_abundance))
  cat(sprintf("  Total rows: %d\n", nrow(abundance_df)))
  cat(sprintf("  Unique cells: %d\n", n_distinct(abundance_df$cell_id)))
  cat(sprintf("  Time periods: %d\n", n_distinct(abundance_df$period)))
  cat(sprintf("  File size: %.1f MB\n", file.size(out_abundance) / 1024^2))
  cat("\n")
  cat("Note: For full habitat composition, join with ukceh_landcover_composition_3km_wide.csv using cell_id\n")
  cat("\n")
} else {
  cat("WARNING: No abundance data extracted\n")
}

if (length(all_abundance) > 0) {

  # === Summary Statistics ===
  cat("=== Summary Statistics ===\n")

  # Cells per time period
  cat("\nCells per time period:\n")
  period_summary <- abundance_df %>%
    group_by(period) %>%
    summarise(
      n_cells = n(),
      mean_abundance = mean(abundance, na.rm = TRUE),
      median_abundance = median(abundance, na.rm = TRUE),
      max_abundance = max(abundance, na.rm = TRUE)
    )
  print(period_summary, n = 20)  # Show first 20 periods

  # Mean abundance by dominant habitat (across all time periods)
  cat("\nMean abundance by dominant habitat (all periods combined):\n")
  habitat_summary <- abundance_df %>%
    group_by(dominant_class, dominant_name) %>%
    summarise(
      n_cells = n(),
      mean_abundance = mean(abundance, na.rm = TRUE),
      .groups = "drop"
    ) %>%
    arrange(desc(mean_abundance))
  print(habitat_summary, n = 10)

  cat("\n=== Pipeline Complete ===\n")
  cat(sprintf("Successfully processed %d/%d time periods\n",
              sum(log_df$status == "OK"), length(time_periods)))

} else {
  cat("ERROR: No data extracted for any time period\n")
  cat("Check log file for details\n")
}
