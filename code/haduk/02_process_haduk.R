# 02_process_haduk.R
# Process HadUK-Grid daily 1 km mean temperature into weekly 3 km rasters.
# Run after the raw NetCDF is downloaded to code/haduk/data/raw/.

library(terra)
library(sf)
library(here)

# === Configuration ===
year <- 2023
variable <- "tasmax"
# Process all 12 months (full year = 52 weeks)
months_to_process <- NULL  # NULL = all months, or set to e.g. 6:7 for June-July only
raw_dir <- here("code", "haduk", "data", "raw")
out_dir <- here("code", "haduk", "outputs")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

cat("\n")
cat("╔════════════════════════════════════════════════════════════════════════════╗\n")
cat("║                                                                            ║\n")
cat("║         STEP 2: Process HadUK-Grid Temperature to Weekly 3km              ║\n")
cat("║                                                                            ║\n")
cat("╚════════════════════════════════════════════════════════════════════════════╝\n")
cat("\n")

cat("Configuration:\n")
cat(sprintf("  Year: %d\n", year))
cat(sprintf("  Variable: %s\n", variable))
cat(sprintf("  Months: %s\n", ifelse(is.null(months_to_process), "All (1-12)", paste(months_to_process, collapse = ", "))))
cat("\n")

# === Find input file(s) ===
cat("════════════════════════════════════════════════════════════════════════════\n")
cat("FINDING INPUT FILES\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

# HadUK may publish as one annual file or twelve monthly files. Handle both.
pattern <- sprintf("^%s_hadukgrid_uk_1km_day_%d.*\\.nc$", variable, year)
files <- list.files(raw_dir, pattern = pattern, full.names = TRUE)
if (length(files) == 0) {
  stop(sprintf("No HadUK files found in %s matching %s for year %d",
               raw_dir, variable, year))
}
cat(sprintf("Found %d HadUK NetCDF file(s):\n", length(files)))
for (f in files) cat("  ", basename(f), "\n")

# === Load and stack ===
cat("\n════════════════════════════════════════════════════════════════════════════\n")
cat("LOADING DATA\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

# Each NetCDF has one layer per day with a time dimension.
cat("Loading NetCDF raster(s)...\n")
r_list <- lapply(files, rast)
r <- do.call(c, r_list)
cat(sprintf("  ✓ Loaded %d daily layers\n", nlyr(r)))

# Filter to selected months if specified
if (!is.null(months_to_process)) {
  day_dates_raw <- time(r)
  if (is.null(day_dates_raw) || any(is.na(day_dates_raw))) {
    # Infer dates from filenames - HadUK format: YYYYMMDD-YYYYMMDD
    first_file <- basename(files[1])
    start_date_str <- sub(".*_(\\d{8})-\\d{8}\\.nc$", "\\1", first_file)
    start_date <- as.Date(start_date_str, format = "%Y%m%d")
    day_dates_raw <- seq.Date(start_date, by = "day", length.out = nlyr(r))
  }

  months <- as.integer(format(day_dates_raw, "%m"))
  keep_layers <- which(months %in% months_to_process)

  cat(sprintf("\nFiltering to months %s...\n", paste(months_to_process, collapse = ", ")))
  cat(sprintf("  Keeping %d of %d days\n", length(keep_layers), nlyr(r)))

  r <- r[[keep_layers]]
  cat("  ✓ Month filtering complete\n")
}

cat(sprintf("\nDataset info:\n"))
cat(sprintf("  Daily layers: %d\n", nlyr(r)))
cat(sprintf("  Native resolution: %s m\n", paste(round(res(r)), collapse = " × ")))
cat(sprintf("  CRS: %s\n", crs(r, describe = TRUE)$name))

# === OPTIMIZED: Spatial aggregation BEFORE temporal aggregation ===
# This reduces data size by 9× before the expensive temporal operation.
# Strategy: 1km→3km spatial (365 layers), then daily→weekly temporal (52 layers).

# Get time information for later temporal aggregation
day_dates <- time(r)
if (is.null(day_dates) || any(is.na(day_dates))) {
  # Fallback: assume layers are sequential days from Jan 1.
  day_dates <- seq.Date(as.Date(sprintf("%d-01-01", year)),
                        by = "day", length.out = nlyr(r))
}
iso_weeks <- as.integer(format(day_dates, "%V"))

# === PROCESSING ===
cat("\n════════════════════════════════════════════════════════════════════════════\n")
cat("SPATIAL AGGREGATION (1km → 3km)\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

cat(sprintf("Processing %d daily layers...\n", nlyr(r)))
cat("  This reduces data size by 9× before temporal aggregation\n\n")
cat("  Progress: ")

t1 <- system.time({
  # Process day by day with progress indicators
  n_layers <- nlyr(r)
  daily_3km_list <- list()

  for (i in 1:n_layers) {
    layer <- r[[i]]
    daily_3km_list[[i]] <- aggregate(layer, fact = 3, fun = "mean", na.rm = TRUE)

    # Print progress after each day
    cat(sprintf("%d/%d ", i, n_layers))
    if (i %% 10 == 0 || i == n_layers) cat("\n  ")
    flush.console()  # Force output to display immediately
  }

  daily_3km <- do.call(c, daily_3km_list)
})
cat(sprintf("\n  ✓ Complete: %.1f seconds (%.2f sec/day average)\n", t1["elapsed"], t1["elapsed"] / nlyr(r)))
cat(sprintf("  Result: %d layers at 3km resolution\n", nlyr(daily_3km)))

# === TEMPORAL AGGREGATION ===
cat("\n════════════════════════════════════════════════════════════════════════════\n")
cat("TEMPORAL AGGREGATION (Daily → Weekly Mean)\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

cat(sprintf("Aggregating %d days to %d ISO weeks...\n", nlyr(daily_3km), length(unique(iso_weeks))))
cat("  Computing weekly means at 3km resolution...\n")

t2 <- system.time({
  weekly_3km_mean <- tapp(daily_3km, iso_weeks, fun = "mean", na.rm = TRUE)
})
cat(sprintf("  ✓ Complete: %.1f seconds\n", t2["elapsed"]))

names(weekly_3km_mean) <- sprintf("week_%02d", as.integer(sub("X", "", names(weekly_3km_mean))))
cat(sprintf("  Result: %d weekly layers\n", nlyr(weekly_3km_mean)))

# === WITHIN-CELL HETEROGENEITY ===
cat("\n════════════════════════════════════════════════════════════════════════════\n")
cat("COMPUTING WITHIN-CELL TEMPERATURE HETEROGENEITY (SD)\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

cat("Step 1: Aggregate 1km daily to weekly means...\n")
cat(sprintf("  Processing %d days → %d weeks at 1km resolution\n", nlyr(r), length(unique(iso_weeks))))
cat("  (This is the slowest step - full 1km resolution)\n")

t3a <- system.time({
  weekly_1km <- tapp(r, iso_weeks, fun = "mean", na.rm = TRUE)
})
cat(sprintf("  ✓ Complete: %.1f seconds (%.2f sec/day)\n", t3a["elapsed"], t3a["elapsed"] / nlyr(r)))

names(weekly_1km) <- sprintf("week_%02d", as.integer(sub("X", "", names(weekly_1km))))

cat("\nStep 2: Aggregate weekly 1km to 3km (computing SD)...\n")
cat(sprintf("  Processing %d weekly layers...\n", nlyr(weekly_1km)))

t3b <- system.time({
  weekly_3km_sd <- aggregate(weekly_1km, fact = 3, fun = "sd", na.rm = TRUE)
})
cat(sprintf("  ✓ Complete: %.1f seconds\n", t3b["elapsed"]))
cat(sprintf("  Result: %d weekly SD layers at 3km\n", nlyr(weekly_3km_sd)))

# === Save outputs in native BNG ===
month_suffix <- if (!is.null(months_to_process)) {
  sprintf("_months_%s", paste(months_to_process, collapse = "_"))
} else {
  ""
}

out_mean_bng <- file.path(out_dir, sprintf("no_edit_%s_weekly_%d%s_3km_mean.tif", variable, year, month_suffix))
out_sd_bng   <- file.path(out_dir, sprintf("no_edit_%s_weekly_%d%s_3km_sd.tif",   variable, year, month_suffix))

cat("\n════════════════════════════════════════════════════════════════════════════\n")
cat("SAVING OUTPUT FILES\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

cat("Writing mean temperature raster...\n")
cat(sprintf("  File: %s\n", basename(out_mean_bng)))
writeRaster(weekly_3km_mean, out_mean_bng, overwrite = TRUE)
cat(sprintf("  ✓ Saved (%.1f MB)\n", file.size(out_mean_bng) / 1024^2))

cat("\nWriting SD temperature raster...\n")
cat(sprintf("  File: %s\n", basename(out_sd_bng)))
writeRaster(weekly_3km_sd,   out_sd_bng,   overwrite = TRUE)
cat(sprintf("  ✓ Saved (%.1f MB)\n", file.size(out_sd_bng) / 1024^2))

# === Optional: reproject to eBird sinusoidal CRS for joining ===
# Skip this step if you do the join in BNG (reprojecting eBird to BNG is also valid).
# To produce eBird-CRS versions, uncomment and set the eBird CRS from one of your
# loaded eBird Status rasters, e.g. via:
#   ebird_crs <- crs(rast("code/ebirdst/outputs/tif/eurrob1_breeding_uk_abundance.tif"))
# weekly_3km_mean_eb <- project(weekly_3km_mean, ebird_crs)
# writeRaster(weekly_3km_mean_eb,
#             file.path(out_dir, sprintf("%s_weekly_%d_3km_mean_ebirdcrs.tif", variable, year)),
#             overwrite = TRUE)

# === Summary ===
cat("\n════════════════════════════════════════════════════════════════════════════\n")
cat("SUMMARY\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

cat("Dataset:\n")
cat(sprintf("  Year: %d\n", year))
cat(sprintf("  Variable: %s\n", variable))
if (!is.null(months_to_process)) {
  cat(sprintf("  Months: %s\n", paste(months_to_process, collapse = ", ")))
} else {
  cat("  Months: All (1-12)\n")
}
cat(sprintf("  Weeks: %d\n", nlyr(weekly_3km_mean)))

cat("\nTemperature statistics:\n")
cat(sprintf("  Mean range: %.2f to %.2f °C\n",
            as.numeric(global(weekly_3km_mean, "min", na.rm = TRUE) |> min()),
            as.numeric(global(weekly_3km_mean, "max", na.rm = TRUE) |> max())))
cat(sprintf("  SD range: %.2f to %.2f °C\n",
            as.numeric(global(weekly_3km_sd, "min", na.rm = TRUE) |> min()),
            as.numeric(global(weekly_3km_sd, "max", na.rm = TRUE) |> max())))

total_time <- t1["elapsed"] + t2["elapsed"] + t3a["elapsed"] + t3b["elapsed"]

cat("\nProcessing times:\n")
cat(sprintf("  Spatial aggregation (1km→3km):  %.1f sec\n", t1["elapsed"]))
cat(sprintf("  Temporal mean (daily→weekly):   %.1f sec\n", t2["elapsed"]))
cat(sprintf("  Within-cell heterogeneity:      %.1f sec\n", t3a["elapsed"] + t3b["elapsed"]))
cat(sprintf("  Total:                          %.1f sec (%.1f min)\n",
            total_time, total_time / 60))

cat("\n════════════════════════════════════════════════════════════════════════════\n")
cat("✓ COMPLETE\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

cat("Next step: Run 03_raster_to_csv.R to convert to CSV format\n\n")
