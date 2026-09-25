# 00_create_landcover_reference.R
# ONE-TIME SCRIPT: Generate land cover composition reference for all UK 3km grid cells
#
# Purpose: Create a reusable lookup table of habitat composition for every 3km cell in UK
# This file is generated once and reused for all species analyses
#
# Output: ukceh_landcover_composition_3km_wide.csv
# Columns: cell_id, x, y, pct_broadleaf, pct_conifer, ..., pct_suburban,
#          total_pct, dominant_class, dominant_name

library(terra)
library(sf)
library(dplyr)
library(tidyr)
library(readr)
library(here)

cat("=== Land Cover Reference Generator ===\n")
cat("Creating one-time lookup table for UK 3km grid cells\n\n")

# === Configuration ===
# Paths
ukceh_pct_file <- here("..", "UKCEH_data", "data", "gb2023lcm1km_percentage_target.tif")
output_file <- here("..", "UKCEH_data", "outputs", "ukceh_landcover_composition_3km_wide.csv")

# === Land Cover Class Lookup Table ===
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

# === Create UK Grid from UKCEH Extent ===
cat("Creating UK-wide 3km grid from UKCEH extent...\n")

# We'll create the grid directly from UKCEH extent rather than using species template
# This ensures we get ALL UK cells, not just where a species is present
cat("  Loading UKCEH raster to get UK extent...\n")
ukceh_temp <- rast(ukceh_pct_file)
ukceh_ext <- ext(ukceh_temp)

cat(sprintf("  UK extent: %.0f to %.0f (X), %.0f to %.0f (Y)\n",
            ukceh_ext[1], ukceh_ext[2], ukceh_ext[3], ukceh_ext[4]))

# Create 3km grid covering UKCEH extent
cell_size <- 3000  # 3km cells
template_rast <- rast(ukceh_ext, resolution = cell_size, crs = "EPSG:27700")
values(template_rast) <- 1  # Fill all cells with dummy value

cat(sprintf("  Created 3km grid: %d cells\n", ncell(template_rast)))
cat(sprintf("  Resolution: %.0f x %.0f meters\n", res(template_rast)[1], res(template_rast)[2]))
cat(sprintf("  CRS: EPSG:27700\n\n"))

# === Load UKCEH Land Cover ===
cat("Loading UKCEH Land Cover Map 2023 (percentage composition)...\n")
ukceh_pct <- rast(ukceh_pct_file)
cat(sprintf("  Layers: %d (one per habitat class)\n", nlyr(ukceh_pct)))
cat(sprintf("  Resolution: %.0f x %.0f meters\n\n", res(ukceh_pct)[1], res(ukceh_pct)[2]))

# === Convert Template to Polygons ===
cat("Converting UK grid to polygons (this may take a few minutes)...\n")

# Give each cell a unique ID so as.polygons doesn't merge them into one
cat("  Assigning unique IDs to each cell...\n")
values(template_rast) <- 1:ncell(template_rast)

# Convert to polygons
cat("  Creating polygon boundaries for each 3km cell...\n")
grid_poly <- as.polygons(template_rast, values = TRUE, na.rm = FALSE)

# Convert to sf for easier manipulation
grid_sf <- st_as_sf(grid_poly)

# Get centroids for coordinates
cat("  Calculating cell centroids...\n")
centroids <- st_centroid(grid_sf)
coords <- st_coordinates(centroids)

# Add cell identifiers
grid_sf$cell_id <- paste(round(coords[, 1]), round(coords[, 2]), sep = "_")
grid_sf$x <- coords[, 1]
grid_sf$y <- coords[, 2]

cat(sprintf("  Created %d polygons\n\n", nrow(grid_sf)))

# === Extract Land Cover Composition ===
cat("Extracting land cover composition for all UK grid cells...\n")
cat("This will take 10-20 minutes for ~84,000 cells...\n\n")

# Convert sf to SpatVector for terra
grid_vect <- vect(grid_sf)

# Extract percentage values for all 21 layers
# This aggregates the ~9 intersecting 1km UKCEH cells per 3km grid cell
extracted <- terra::extract(ukceh_pct, grid_vect, fun = mean, na.rm = TRUE)

cat("Extraction complete! Formatting output...\n\n")

# === Format Output ===
cat("Creating wide format with all habitat percentages...\n")

# Add cell metadata
extracted_with_meta <- extracted %>%
  mutate(
    cell_id = grid_sf$cell_id[ID],
    x = grid_sf$x[ID],
    y = grid_sf$y[ID]
  ) %>%
  select(-ID)

# Rename percentage columns to human-readable names
wide_data <- extracted_with_meta %>%
  rename_with(
    ~ gsub("gb2023lcm1km_percentage_target_", "pct_", .x),
    starts_with("gb2023lcm1km_percentage_target_")
  ) %>%
  rename_with(
    ~ case_when(
      .x == "pct_1" ~ "pct_broadleaf",
      .x == "pct_2" ~ "pct_conifer",
      .x == "pct_3" ~ "pct_arable",
      .x == "pct_4" ~ "pct_improved_grass",
      .x == "pct_5" ~ "pct_neutral_grass",
      .x == "pct_6" ~ "pct_calcareous_grass",
      .x == "pct_7" ~ "pct_acid_grass",
      .x == "pct_8" ~ "pct_fen",
      .x == "pct_9" ~ "pct_heather",
      .x == "pct_10" ~ "pct_heather_grass",
      .x == "pct_11" ~ "pct_bog",
      .x == "pct_12" ~ "pct_inland_rock",
      .x == "pct_13" ~ "pct_saltwater",
      .x == "pct_14" ~ "pct_freshwater",
      .x == "pct_15" ~ "pct_supralittoral_rock",
      .x == "pct_16" ~ "pct_supralittoral_sed",
      .x == "pct_17" ~ "pct_littoral_rock",
      .x == "pct_18" ~ "pct_littoral_sed",
      .x == "pct_19" ~ "pct_saltmarsh",
      .x == "pct_20" ~ "pct_urban",
      .x == "pct_21" ~ "pct_suburban",
      TRUE ~ .x
    ),
    starts_with("pct_")
  )

# Calculate dominant class and total percentage
col_to_class <- c(
  pct_broadleaf = 1, pct_conifer = 2, pct_arable = 3, pct_improved_grass = 4,
  pct_neutral_grass = 5, pct_calcareous_grass = 6, pct_acid_grass = 7, pct_fen = 8,
  pct_heather = 9, pct_heather_grass = 10, pct_bog = 11, pct_inland_rock = 12,
  pct_saltwater = 13, pct_freshwater = 14, pct_supralittoral_rock = 15,
  pct_supralittoral_sed = 16, pct_littoral_rock = 17, pct_littoral_sed = 18,
  pct_saltmarsh = 19, pct_urban = 20, pct_suburban = 21
)

pct_cols <- names(col_to_class)

wide_data <- wide_data %>%
  rowwise() %>%
  mutate(
    total_pct = sum(c_across(all_of(pct_cols)), na.rm = TRUE),
    dominant_col = pct_cols[which.max(c_across(all_of(pct_cols)))],
    dominant_class = as.integer(col_to_class[dominant_col]),
    dominant_name = landcover_names[as.character(dominant_class)]
  ) %>%
  ungroup() %>%
  select(-dominant_col) %>%
  select(cell_id, x, y, all_of(pct_cols), total_pct, dominant_class, dominant_name)

# === Validation ===
cat("=== Validation ===\n")
cat(sprintf("Total cells: %d\n", nrow(wide_data)))
cat(sprintf("Mean total_pct: %.1f%%\n", mean(wide_data$total_pct, na.rm = TRUE)))
cat(sprintf("Cells with total_pct < 95%%: %d (likely coastal/offshore)\n",
            sum(wide_data$total_pct < 95, na.rm = TRUE)))

# Dominant habitat distribution
dominant_summary <- wide_data %>%
  group_by(dominant_name) %>%
  summarise(n_cells = n(), .groups = "drop") %>%
  arrange(desc(n_cells))

cat("\nDominant habitat distribution:\n")
print(dominant_summary, n = 21)

# === Write Output ===
cat("\n=== Writing Output ===\n")
write_csv(wide_data, output_file)
cat(sprintf("✓ Saved: %s\n", output_file))
cat(sprintf("  Rows: %d\n", nrow(wide_data)))
cat(sprintf("  Columns: %d\n", ncol(wide_data)))
cat(sprintf("  File size: %.1f MB\n", file.size(output_file) / 1024^2))

cat("\n=== Complete ===\n")
cat("This reference file can now be joined with any species' abundance data using 'cell_id'\n")
cat("Example join in R:\n")
cat("  abundance_data %>% left_join(landcover_ref, by = 'cell_id')\n")
