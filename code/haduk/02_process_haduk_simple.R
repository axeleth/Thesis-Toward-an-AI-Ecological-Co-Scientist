# 02_process_haduk_simple.R
# Process HadUK-Grid daily 1 km mean temperature into daily 3 km rasters.
# Simplified version: Just spatial aggregation, no temporal aggregation.
# Run after the raw NetCDF is downloaded to code/haduk/data/raw/.

library(terra)
library(here)

# === Configuration ===
year <- 2023
variable <- "tasmax"
# Process only June (breeding season for willow warbler)
months_to_process <- 6  # Set to NULL to process all months
raw_dir <- here("code", "haduk", "data", "raw")
out_dir <- here("code", "haduk", "outputs")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

# === Find input file(s) ===
# HadUK may publish as one annual file or twelve monthly files. Handle both.
pattern <- sprintf("^%s_hadukgrid_uk_1km_day_%d.*\\.nc$", variable, year)
files <- list.files(raw_dir, pattern = pattern, full.names = TRUE)
if (length(files) == 0) {
  stop(sprintf("No HadUK files found in %s matching %s for year %d",
               raw_dir, variable, year))
}
cat(sprintf("Found %d HadUK file(s):\n", length(files)))
for (f in files) cat("  ", basename(f), "\n")

# === Load and stack ===
# Each NetCDF has one layer per day with a time dimension.
cat("Loading NetCDF files...\n")
r_list <- lapply(files, rast)
r <- do.call(c, r_list)

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

  cat(sprintf("Filtering to months %s: keeping %d of %d days\n",
              paste(months_to_process, collapse = ", "),
              length(keep_layers),
              nlyr(r)))

  r <- r[[keep_layers]]
}

cat(sprintf("Loaded %d daily layers, native resolution %s.\n",
            nlyr(r),
            paste(round(res(r)), collapse = " x ")))

# Check CRS. HadUK should be in EPSG:27700 (British National Grid).
cat("Native CRS: ", crs(r, describe = TRUE)$name, "\n")

# Get time information for layer naming
day_dates <- time(r)
if (is.null(day_dates) || any(is.na(day_dates))) {
  # Fallback: assume layers are sequential days from Jan 1.
  day_dates <- seq.Date(as.Date(sprintf("%d-01-01", year)),
                        by = "day", length.out = nlyr(r))
}

# === Aggregate spatially 1 km → 3 km ===
cat(sprintf("\nAggregating 1 km to 3 km spatially (%d daily layers)...\n", nlyr(r)))
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
cat(sprintf("\nDONE (%.1f seconds, %.1f sec/day avg)\n", t1["elapsed"], t1["elapsed"] / nlyr(r)))
cat(sprintf("  Spatial aggregation complete: %d layers at 3 km resolution.\n", nlyr(daily_3km)))

# === Add date labels ===
names(daily_3km) <- format(day_dates, "%Y-%m-%d")

# === Save output in native BNG ===
month_suffix <- if (!is.null(months_to_process)) {
  sprintf("_months_%s", paste(months_to_process, collapse = "_"))
} else {
  ""
}

out_daily_bng <- file.path(out_dir, sprintf("%s_daily_%d%s_3km.tif", variable, year, month_suffix))

cat("\nSaving output...\n")
cat("  Writing daily 3km raster... ")
writeRaster(daily_3km, out_daily_bng, overwrite = TRUE)
cat("DONE\n")

cat("\nSaved output:\n")
cat("  ", out_daily_bng, "\n")

# === Quick summary ===
cat("\n=== Summary ===\n")
cat(sprintf("Year: %d, variable: %s\n", year, variable))
if (!is.null(months_to_process)) {
  cat(sprintf("Months processed: %s\n", paste(months_to_process, collapse = ", ")))
}
cat(sprintf("Number of days: %d\n", nlyr(daily_3km)))
cat(sprintf("Date range: %s to %s\n",
            format(day_dates[1], "%Y-%m-%d"),
            format(day_dates[length(day_dates)], "%Y-%m-%d")))
cat(sprintf("Daily temperature range: %.2f to %.2f °C\n",
            as.numeric(global(daily_3km, "min", na.rm = TRUE) |> min()),
            as.numeric(global(daily_3km, "max", na.rm = TRUE) |> max())))

cat(sprintf("\n=== Processing Time ===\n"))
cat(sprintf("Spatial aggregation: %.1f seconds (%.1f sec/day avg)\n",
            t1["elapsed"], t1["elapsed"] / nlyr(r)))

cat("\nDone! You can now use this daily 3km data for your analysis.\n")
cat("Tip: Sample one day per week for weekly analysis, or use all days for daily correlations.\n")
