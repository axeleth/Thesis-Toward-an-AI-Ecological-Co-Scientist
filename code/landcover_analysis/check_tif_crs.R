library(terra)

# Check a sample TIF to understand the CRS
tif_file <- "/Volumes/Other/ebirdst_outputs/eurrol1/tif/eurrol1_week_01_uk_abundance.tif"

if (file.exists(tif_file)) {
  r <- rast(tif_file)
  cat("File:", basename(tif_file), "\n")
  cat("CRS:", crs(r, describe = TRUE)$name, "\n")
  cat("EPSG:", crs(r, describe = TRUE)$code, "\n")
  cat("Extent:\n")
  print(ext(r))
  cat("\nResolution:", res(r), "\n")
  cat("Dimensions:", dim(r)[1:2], "(rows, cols)\n")

  # Sample values to check if it has data
  vals <- values(r)
  non_na <- sum(!is.na(vals))
  cat("Non-NA cells:", non_na, "of", length(vals), "\n")
} else {
  cat("File not found:", tif_file, "\n")
}