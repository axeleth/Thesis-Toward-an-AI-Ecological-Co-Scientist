# 03_pull_and_map.R
# Pull one species' seasonal abundance, crop to UK, and produce summary stats.
# Edit the configuration block to change what gets pulled.

library(ebirdst)
library(terra)
library(sf)
library(dplyr)
library(ggplot2)
library(rnaturalearth)
library(here)

# === Configuration ===
# ★★★ NOTE: YEAR LIMITATION ★★★
# The current ebirdst package only provides access to 2023 Status data
# To access historical data (2020-2022), you would need older package versions
# For now, this script processes only 2023 data

# ★★★ SPECIES SELECTION ★★★
# Pick ONE of the five modes below by setting `species_mode`.
# - "cache"         : process every species already in the ebirdst cache (DEFAULT;
#                     this is the natural mode after running download_ebird.R)
# - "single"        : run for one species (set focal_species_common below)
# - "scolopacidae"  : run for all 46 Scolopacidae species listed for Great Britain on the eBird Status site
# - "accipitridae"  : run for 5 UK Accipitridae species (hawks, eagles, kites)
# - "custom"        : run for whatever vector you put in `species_list_custom`
species_mode <- "cache"                                      # edit here to choose mode: "cache", "single", "scolopacidae", "accipitridae", or "custom"
focal_species_common <- "Eurasian Curlew"                    # used only in "single" mode

# Custom list (used only in "custom" mode):
# Test Scolopacidae availability
species_list_custom <- c("Eurasian Curlew", "Eurasian Woodcock", "Ruddy Turnstone")  # Test other Scolopacidae

# Scolopacidae (Great Britain, 45 species from the eBird Status site)
# Matched against ebirdst_runs by scientific name for robustness.
gb_scolopacidae_sci <- c(
  "Bartramia longicauda",      # Upland Sandpiper
  "Numenius arquata",          # Eurasian Curlew
  "Limosa lapponica",          # Bar-tailed Godwit
  "Limosa haemastica",         # Hudsonian Godwit
  "Limnodromus griseus",       # Short-billed Dowitcher
  "Limnodromus scolopaceus",   # Long-billed Dowitcher
  "Scolopax rusticola",        # Eurasian Woodcock
  "Gallinago gallinago",       # Common Snipe
  "Gallinago delicata",        # Wilson's Snipe
  "Phalaropus tricolor",       # Wilson's Phalarope
  "Phalaropus fulicarius",     # Grey Phalarope
  "Phalaropus lobatus",        # Red-necked Phalarope
  "Xenus cinereus",            # Terek Sandpiper
  "Actitis hypoleucos",        # Common Sandpiper
  "Actitis macularius",        # Spotted Sandpiper
  "Tringa ochropus",           # Green Sandpiper
  "Tringa solitaria",          # Solitary Sandpiper
  "Tringa brevipes",           # Grey-tailed Tattler
  "Tringa stagnatilis",        # Marsh Sandpiper
  "Tringa glareola",           # Wood Sandpiper
  "Tringa totanus",            # Common Redshank
  "Tringa flavipes",           # Lesser Yellowlegs
  "Tringa nebularia",          # Common Greenshank
  "Tringa melanoleuca",        # Greater Yellowlegs
  "Arenaria interpres",        # Ruddy Turnstone
  "Calidris tenuirostris",     # Great Knot
  "Calidris canutus",          # Red Knot
  "Calidris pugnax",           # Ruff
  "Calidris falcinellus",      # Broad-billed Sandpiper
  "Calidris acuminata",        # Sharp-tailed Sandpiper
  "Calidris ferruginea",       # Curlew Sandpiper
  "Calidris himantopus",       # Stilt Sandpiper
  "Calidris temminckii",       # Temminck's Stint
  "Calidris subminuta",        # Long-toed Stint
  "Calidris ruficollis",       # Red-necked Stint
  "Calidris subruficollis",    # Buff-breasted Sandpiper
  "Calidris alba",             # Sanderling
  "Calidris alpina",           # Dunlin
  "Calidris maritima",         # Purple Sandpiper
  "Calidris bairdii",          # Baird's Sandpiper
  "Calidris minuta",           # Little Stint
  "Calidris fuscicollis",      # White-rumped Sandpiper
  "Calidris minutilla",        # Least Sandpiper
  "Calidris melanotos",        # Pectoral Sandpiper
  "Calidris mauri",            # Western Sandpiper
  "Calidris pusilla"           # Semipalmated Sandpiper
)

# UK Accipitridae (hawks, eagles, and kites)
uk_accipitridae_sci <- c(
  "Circus cyaneus",            # Hen Harrier
  "Aquila chrysaetos",         # Golden Eagle
  "Accipiter nisus",           # Eurasian Sparrowhawk
  "Milvus milvus",             # Red Kite
  "Buteo buteo"                # Common Buzzard
)

# ★★★ CHANGE THIS TO SWAP BETWEEN FORMATS ★★★
time_format <- "weekly"                                     # "seasonal" or "weekly"
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★

# For seasonal format:
season <- "prebreeding_migration"                           # one of: breeding, nonbreeding, prebreeding_migration, postbreeding_migration

# For weekly format - RANGE EXTRACTION:
week_ranges <- list(
  full_year = 1:52                                          # Download ALL 52 weeks of the year
)

# Save outputs to external drive
out_dir_base <- "/Volumes/Other/ebirdst_outputs"

# === Build the species list according to the chosen mode ===
runs <- ebirdst_runs

if (species_mode == "cache") {
  # Discover every species code that has a subdirectory in the ebirdst cache,
  # then resolve those codes to common names via ebirdst_runs.
  cache_dir <- ebirdst::ebirdst_data_dir()
  all_subdirs <- list.dirs(cache_dir, recursive = TRUE, full.names = FALSE)
  cached_codes <- intersect(basename(all_subdirs), runs$species_code)
  cached_codes <- unique(cached_codes)
  if (length(cached_codes) == 0) {
    stop(sprintf("Cache mode: no species found in cache at %s. Run download_ebird.R first.",
                 cache_dir))
  }
  species_list <- runs$common_name[match(cached_codes, runs$species_code)]
  cat(sprintf("Cache mode: found %d species in cache at %s\n",
              length(species_list), cache_dir))
} else if (species_mode == "single") {
  species_list <- c(focal_species_common)
} else if (species_mode == "scolopacidae") {
  target_runs <- runs[runs$scientific_name %in% gb_scolopacidae_sci, ]
  species_list <- target_runs$common_name
  cat(sprintf("Scolopacidae mode: matched %d of %d species\n",
              nrow(target_runs), length(gb_scolopacidae_sci)))
  missing <- setdiff(gb_scolopacidae_sci, runs$scientific_name)
  if (length(missing) > 0) {
    cat("Missing (probable taxonomy mismatch, will be skipped):\n")
    print(missing)
  }
} else if (species_mode == "accipitridae") {
  target_runs <- runs[runs$scientific_name %in% uk_accipitridae_sci, ]
  species_list <- target_runs$common_name
  cat(sprintf("Accipitridae mode: matched %d of %d species\n",
              nrow(target_runs), length(uk_accipitridae_sci)))
  missing <- setdiff(uk_accipitridae_sci, runs$scientific_name)
  if (length(missing) > 0) {
    cat("Missing (probable taxonomy mismatch, will be skipped):\n")
    print(missing)
  }
} else if (species_mode == "custom") {
  species_list <- species_list_custom
} else {
  stop(sprintf("Invalid species_mode '%s'. Use 'cache', 'single', 'scolopacidae', 'accipitridae', or 'custom'.",
               species_mode))
}

cat(sprintf("Will process %d species:\n", length(species_list)))
print(species_list)

# === Create summary log ===
summary_log <- data.frame()
data_year <- 2023  # Current ebirdst package provides 2023 data

# === Main loop: process each species ===
for (focal_species_common in species_list) {

  cat(sprintf("\n============================================================\n"))
  cat(sprintf("Processing: %s (Data Year: %d)\n", focal_species_common, data_year))
  cat(sprintf("============================================================\n"))

  # Track processing status
  process_status <- "started"
  error_message <- NA

# === Resolve species code from common name ===
match_row <- runs[runs$common_name == focal_species_common, ]
if (nrow(match_row) == 0) {
  cat(sprintf("Species '%s' not found in ebirdst_runs. Skipping.\n",
              focal_species_common))
  next
}
focal_species_code <- match_row$species_code[1]
cat(sprintf("Resolved species: %s (code: %s)\n",
            focal_species_common, focal_species_code))

# === Create species-specific output directories ===
  out_dir <- file.path(out_dir_base, focal_species_code)
  out_dir_tif <- file.path(out_dir, "tif")

dir.create(out_dir_tif, recursive = TRUE, showWarnings = FALSE)
cat(sprintf("Output directories created: %s\n", out_dir))

# === Download and load based on time_format ===
  tryCatch({
    if (time_format == "seasonal") {
      # Cache-only mode: no download attempt. Assumes the seasonal 3km
      # abundance file is already in the ebirdst cache. To pull missing
      # files, run diagnose_species_access.R (which has the retry loop for
      # Cornell's intermittent 500 errors) on the species first.
      cat("Cache-only mode: skipping download. Using cached files only.\n")

      # Load the raster - returns a SpatRaster with one layer per season
      abd <- load_raster(focal_species_code,
                       product = "abundance",
                       period  = "seasonal",
                       metric  = "mean")
        cat("Layers in loaded raster:\n")
        print(names(abd))

        # Pick the requested season
        if (!(season %in% names(abd))) {
          stop(sprintf("Season '%s' not in raster. Available: %s",
                     season, paste(names(abd), collapse = ", ")))
        }
        time_layer <- abd[[season]]
        time_label <- season

    } else if (time_format == "weekly") {
      # Cache-only mode: no download attempt. Assumes the weekly 3km
      # abundance file is already in the ebirdst cache. To pull missing
      # files, run diagnose_species_access.R (which has the retry loop for
      # Cornell's intermittent 500 errors) on the species first.
      cat("Cache-only mode: skipping download. Using cached files only.\n")

      # Load the raster - returns a SpatRaster with 52 layers (one per week)
      abd <- load_raster(focal_species_code,
                       product = "abundance",
                       period  = "weekly",
                       metric  = "median")
        cat(sprintf("Loaded weekly raster with %d layers\n", nlyr(abd)))

  # Flatten week_ranges into single vector
  weeks_to_process <- unlist(week_ranges, use.names = FALSE)
  cat(sprintf("Will process %d weeks: %s\n",
              length(weeks_to_process),
              paste(weeks_to_process, collapse = ", ")))

} else {
  stop(sprintf("Invalid time_format '%s'. Must be 'seasonal' or 'weekly'.", time_format))
}

# === Get UK boundary and reproject to the raster's CRS ===
uk <- ne_countries(country = "United Kingdom", scale = "medium", returnclass = "sf")
uk_bng <- st_transform(uk, 27700)  # Pre-compute BNG transformation once

if (time_format == "seasonal") {
  # Original single-layer workflow
  uk_in_raster_crs <- st_transform(uk, crs = crs(time_layer))
  uk_vect <- vect(uk_in_raster_crs)

  # === Crop and mask ===
  cat("Cropping to UK extent...\n")
  abd_uk <- crop(time_layer, uk_vect)
  abd_uk <- mask(abd_uk, uk_vect)

  # === Save the cropped raster ===
  tif_path <- file.path(out_dir_tif, sprintf("%s_%s_uk_abundance.tif",
                                         focal_species_code, time_label))
  writeRaster(abd_uk, tif_path, overwrite = TRUE)
  cat("Saved cropped raster:", tif_path, "\n")

  # === Summary stats ===
  cat(sprintf("\n=== %s, %s, UK extent ===\n",
              focal_species_common, time_label))
  n_cells <- as.numeric(global(!is.na(abd_uk), "sum", na.rm = TRUE))
  cat(sprintf("  Non-NA cells: %.0f\n", n_cells))
  cat(sprintf("  Mean abundance: %.4f\n",
              as.numeric(global(abd_uk, "mean", na.rm = TRUE))))
  cat(sprintf("  Median abundance: %.4f\n",
              median(values(abd_uk), na.rm = TRUE)))
  cat(sprintf("  Max abundance: %.4f\n",
              as.numeric(global(abd_uk, "max", na.rm = TRUE))))
  cat(sprintf("  Stdev abundance: %.4f\n",
              as.numeric(global(abd_uk, "sd", na.rm = TRUE))))


} else if (time_format == "weekly") {
  # Multi-week workflow
  uk_in_raster_crs <- st_transform(uk, crs = crs(abd))
  uk_vect <- vect(uk_in_raster_crs)

  cat(sprintf("\n=== Processing %d weeks ===\n", length(weeks_to_process)))

  # Calculate global min/max across all weeks for consistent color scale
  cat("Calculating global abundance range across all weeks...\n")
  global_min <- Inf
  global_max <- -Inf

  for (week_num in weeks_to_process) {
    time_layer <- abd[[week_num]]
    abd_uk_temp <- crop(time_layer, uk_vect)
    abd_uk_temp <- mask(abd_uk_temp, uk_vect)

    week_min <- as.numeric(global(abd_uk_temp, "min", na.rm = TRUE))
    week_max <- as.numeric(global(abd_uk_temp, "max", na.rm = TRUE))

    global_min <- min(global_min, week_min, na.rm = TRUE)
    global_max <- max(global_max, week_max, na.rm = TRUE)
  }

  cat(sprintf("Global abundance range: %.4f to %.4f\n", global_min, global_max))

  for (i in seq_along(weeks_to_process)) {
    week_num <- weeks_to_process[i]
    time_label <- sprintf("week_%02d", week_num)

    cat(sprintf("\n[%d/%d] Processing week %d...\n", i, length(weeks_to_process), week_num))

    # Extract week layer
    time_layer <- abd[[week_num]]

    # Crop and mask
    abd_uk <- crop(time_layer, uk_vect)
    abd_uk <- mask(abd_uk, uk_vect)

    # Save TIF
    tif_path <- file.path(out_dir_tif, sprintf("%s_%s_uk_abundance.tif",
                                           focal_species_code, time_label))
    writeRaster(abd_uk, tif_path, overwrite = TRUE)
    cat("  Saved TIF:", basename(tif_path), "\n")

    # Summary stats
    n_cells <- as.numeric(global(!is.na(abd_uk), "sum", na.rm = TRUE))
    mean_abd <- as.numeric(global(abd_uk, "mean", na.rm = TRUE))
    cat(sprintf("  Stats: %.0f cells, mean=%.4f\n", n_cells, mean_abd))

  }
}

    process_status <- "success"

  }, error = function(e) {
    cat(sprintf("\n✗ ERROR processing %s: %s\n",
                focal_species_common, e$message))
    process_status <- "failed"
    error_message <- e$message
  })

  # Add to summary log
  summary_log <- rbind(summary_log, data.frame(
    species = focal_species_common,
    species_code = ifelse(exists("focal_species_code"), focal_species_code, NA),
    status = process_status,
    error = error_message,
    stringsAsFactors = FALSE
  ))

  # Clean up memory after each species
  if (exists("abd")) rm(abd)
  if (exists("abd_uk")) rm(abd_uk)
  if (exists("abd_uk_bng")) rm(abd_uk_bng)
  gc()

}  # end of species loop

# === Save summary log ===
log_file <- file.path(out_dir_base, sprintf("processing_summary_%s.csv",
                                           format(Sys.time(), "%Y%m%d_%H%M%S")))
write.csv(summary_log, log_file, row.names = FALSE)
cat(sprintf("\nProcessing summary saved to: %s\n", log_file))

# Show summary
cat("\n=== PROCESSING SUMMARY ===\n")
print(table(summary_log$status))
failed_species <- summary_log[summary_log$status == "failed", ]
if (nrow(failed_species) > 0) {
  cat("\nFailed downloads:\n")
  print(failed_species[, c("species", "error")])
}

cat("\nDone.\n")
