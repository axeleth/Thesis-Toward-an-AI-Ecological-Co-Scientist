# demo_download_eursta_local.R
# Download European Starling (eursta) 2023 weekly abundance, crop/mask to the UK,
# and write 52 weekly TIFs to a LOCAL directory.
#
# Replicates the "single" / "weekly" download + crop logic of
# code/ebirdst/pull_and_map.R, but writes to a local output path instead of the
# (currently unmounted) external drive.
#
# Output: code/ebirdst/outputs/eursta/tif/eursta_week_NN_uk_abundance.tif

library(ebirdst)
library(terra)
library(sf)
library(rnaturalearth)
library(here)

# === Configuration ===
focal_species_common <- "European Starling"
out_dir_tif <- here("code", "ebirdst", "outputs", "eursta", "tif")
weeks_to_process <- 1:52

# === Verify API key ===
if (Sys.getenv("EBIRDST_KEY") == "") {
  stop("EBIRDST_KEY is not set. See code/API_KEY_SETUP.md to add it to ~/.Renviron, then restart R.")
}

# === Resolve species code ===
runs <- ebirdst_runs
match_row <- runs[runs$common_name == focal_species_common, ]
if (nrow(match_row) == 0) {
  stop(sprintf("Species '%s' not found in ebirdst_runs.", focal_species_common))
}
focal_species_code <- match_row$species_code[1]
cat(sprintf("Resolved %s -> code: %s\n", focal_species_common, focal_species_code))

dir.create(out_dir_tif, recursive = TRUE, showWarnings = FALSE)

# === Check if already complete ===
existing <- list.files(out_dir_tif,
                       pattern = sprintf("^%s_week_\\d{2}_uk_abundance\\.tif$", focal_species_code),
                       full.names = FALSE)
if (length(existing) >= 52) {
  cat(sprintf("Already have %d weekly TIFs in %s. Skipping download.\n",
              length(existing), out_dir_tif))
  quit(save = "no", status = 0)
}

# === Download weekly abundance (3km) ===
cat("Downloading 3km weekly abundance (this may take a while)...\n")
ebirdst_download_status(
  species   = focal_species_code,
  pattern   = "abundance_median.*_3km_",  # 3km resolution only
  download_pis = FALSE,
  download_ppms = FALSE
)

abd <- load_raster(focal_species_code,
                   product = "abundance",
                   period  = "weekly",
                   metric  = "median")
cat(sprintf("Loaded weekly raster with %d layers\n", nlyr(abd)))

# === UK boundary in raster CRS ===
uk <- ne_countries(country = "United Kingdom", scale = "medium", returnclass = "sf")
uk_in_raster_crs <- st_transform(uk, crs = crs(abd))
uk_vect <- vect(uk_in_raster_crs)

# === Crop, mask, write each week ===
for (i in seq_along(weeks_to_process)) {
  week_num <- weeks_to_process[i]
  time_label <- sprintf("week_%02d", week_num)

  time_layer <- abd[[week_num]]
  abd_uk <- crop(time_layer, uk_vect)
  abd_uk <- mask(abd_uk, uk_vect)

  tif_path <- file.path(out_dir_tif,
                        sprintf("%s_%s_uk_abundance.tif", focal_species_code, time_label))
  writeRaster(abd_uk, tif_path, overwrite = TRUE)

  n_cells <- as.numeric(global(!is.na(abd_uk), "sum", na.rm = TRUE))
  mean_abd <- as.numeric(global(abd_uk, "mean", na.rm = TRUE))
  cat(sprintf("[%d/%d] %s: %.0f cells, mean=%.4f\n",
              i, length(weeks_to_process), time_label, n_cells, mean_abd))
}

# === Verify ===
final <- list.files(out_dir_tif,
                    pattern = sprintf("^%s_week_\\d{2}_uk_abundance\\.tif$", focal_species_code))
cat(sprintf("\nDone. %d weekly TIFs in %s\n", length(final), out_dir_tif))
if (length(final) < 52) {
  stop(sprintf("Expected 52 TIFs but only %d present.", length(final)))
}
