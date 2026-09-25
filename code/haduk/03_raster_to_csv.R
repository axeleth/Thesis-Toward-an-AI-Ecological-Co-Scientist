# 03_raster_to_csv.R
# Convert HadUK weekly temperature rasters to CSV format for analysis

library(terra)
library(here)
library(tidyr)
library(dplyr)

# === Configuration ===
year <- 2023
variable <- "tasmax"
months_suffix <- ""  # Empty = full year (all 52 weeks)

# Input files
in_dir <- here("code", "haduk", "outputs")
mean_file <- file.path(in_dir, sprintf("no_edit_%s_weekly_%d%s_3km_mean.tif", variable, year, months_suffix))
sd_file <- file.path(in_dir, sprintf("no_edit_%s_weekly_%d%s_3km_sd.tif", variable, year, months_suffix))

# Output file
out_csv <- file.path(in_dir, sprintf("%s_weekly_%d%s_3km.csv", variable, year, months_suffix))

cat("\n")
cat("╔════════════════════════════════════════════════════════════════════════════╗\n")
cat("║                                                                            ║\n")
cat("║           STEP 3: Convert Weekly Temperature Rasters to CSV               ║\n")
cat("║                                                                            ║\n")
cat("╚════════════════════════════════════════════════════════════════════════════╝\n")
cat("\n")

cat("Configuration:\n")
cat(sprintf("  Year: %d\n", year))
cat(sprintf("  Variable: %s\n", variable))
cat(sprintf("  Coverage: %s\n", ifelse(months_suffix == "", "Full year (52 weeks)", months_suffix)))
cat("\n")

# === Load rasters ===
cat("════════════════════════════════════════════════════════════════════════════\n")
cat("LOADING INPUT RASTERS\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

cat(sprintf("Loading mean temperature raster...\n"))
cat(sprintf("  File: %s\n", basename(mean_file)))
mean_temp <- rast(mean_file)
cat(sprintf("  ✓ Loaded: %d layers (weeks)\n", nlyr(mean_temp)))
cat(sprintf("  Resolution: %.0f × %.0f m\n", res(mean_temp)[1], res(mean_temp)[2]))
cat(sprintf("  Dimensions: %d × %d cells\n", nrow(mean_temp), ncol(mean_temp)))

cat(sprintf("\nLoading SD temperature raster...\n"))
cat(sprintf("  File: %s\n", basename(sd_file)))
sd_temp <- rast(sd_file)
cat(sprintf("  ✓ Loaded: %d layers (weeks)\n", nlyr(sd_temp)))

# === Convert to data frames ===
cat("\n════════════════════════════════════════════════════════════════════════════\n")
cat("EXTRACTING DATA FROM RASTERS\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

cat("Step 1: Converting mean temperature raster to data frame...\n")
cat("  (This may take a few minutes for 52 weeks of data)\n")
start_time <- Sys.time()

# This creates columns: x, y, week_1, week_2, ..., week_52
df_mean <- as.data.frame(mean_temp, xy = TRUE, na.rm = TRUE)

elapsed <- as.numeric(difftime(Sys.time(), start_time, units = "secs"))
cat(sprintf("  ✓ Extracted %s cells with data (%.1f seconds)\n",
            format(nrow(df_mean), big.mark = ","), elapsed))
cat(sprintf("  Columns: x, y, + %d week layers\n", nlyr(mean_temp)))

cat("\nStep 2: Converting SD temperature raster to data frame...\n")
start_time <- Sys.time()
df_sd <- as.data.frame(sd_temp, xy = TRUE, na.rm = TRUE)
elapsed <- as.numeric(difftime(Sys.time(), start_time, units = "secs"))
cat(sprintf("  ✓ Extracted %s cells (%.1f seconds)\n",
            format(nrow(df_sd), big.mark = ","), elapsed))

# === Reshape to long format ===
cat("\n════════════════════════════════════════════════════════════════════════════\n")
cat("RESHAPING TO LONG FORMAT\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

cat("Step 3: Pivoting mean temperature data...\n")
cat(sprintf("  From: %s rows × %d columns (wide format)\n",
            format(nrow(df_mean), big.mark = ","), ncol(df_mean)))
start_time <- Sys.time()

# Pivot mean data to long format
df_mean_long <- df_mean %>%
  pivot_longer(cols = starts_with("week_"),
               names_to = "week",
               values_to = "temp_mean_C") %>%
  mutate(week = as.integer(sub("week_", "", week)))

elapsed <- as.numeric(difftime(Sys.time(), start_time, units = "secs"))
cat(sprintf("  To: %s rows × 4 columns (long format, %.1f seconds)\n",
            format(nrow(df_mean_long), big.mark = ","), elapsed))

cat("\nStep 4: Pivoting SD temperature data...\n")
start_time <- Sys.time()

# Pivot SD data to long format
df_sd_long <- df_sd %>%
  pivot_longer(cols = starts_with("week_"),
               names_to = "week",
               values_to = "temp_sd_C") %>%
  mutate(week = as.integer(sub("week_", "", week))) %>%
  select(x, y, week, temp_sd_C)

elapsed <- as.numeric(difftime(Sys.time(), start_time, units = "secs"))
cat(sprintf("  ✓ Complete (%.1f seconds)\n", elapsed))

cat("\nStep 5: Joining mean and SD data...\n")
start_time <- Sys.time()

# Join mean and SD data
df_final <- df_mean_long %>%
  left_join(df_sd_long, by = c("x", "y", "week")) %>%
  arrange(week, y, x)

elapsed <- as.numeric(difftime(Sys.time(), start_time, units = "secs"))
cat(sprintf("  ✓ Joined and sorted %s rows (%.1f seconds)\n",
            format(nrow(df_final), big.mark = ","), elapsed))

# === Add cell ID for joining with eBird data ===
cat("\nStep 6: Adding cell_id for spatial joins...\n")
start_time <- Sys.time()

df_final <- df_final %>%
  mutate(cell_id = sprintf("%d_%d", round(x), round(y))) %>%
  select(week, cell_id, x, y, temp_mean_C, temp_sd_C)

elapsed <- as.numeric(difftime(Sys.time(), start_time, units = "secs"))
cat(sprintf("  ✓ Added cell_id column (%.1f seconds)\n", elapsed))

# === Save to CSV ===
cat("\n════════════════════════════════════════════════════════════════════════════\n")
cat("SAVING OUTPUT\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

cat("Writing CSV file...\n")
cat(sprintf("  Output: %s\n", basename(out_csv)))
start_time <- Sys.time()

write.csv(df_final, out_csv, row.names = FALSE)

elapsed <- as.numeric(difftime(Sys.time(), start_time, units = "secs"))
file_size_mb <- file.size(out_csv) / 1024^2

cat(sprintf("  ✓ Saved successfully (%.1f seconds)\n", elapsed))
cat(sprintf("  File size: %.1f MB\n", file_size_mb))

# === Summary ===
cat("\n════════════════════════════════════════════════════════════════════════════\n")
cat("SUMMARY\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

cat(sprintf("Dataset statistics:\n"))
cat(sprintf("  Total rows: %s\n", format(nrow(df_final), big.mark = ",")))
cat(sprintf("  Unique cells: %s\n", format(length(unique(df_final$cell_id)), big.mark = ",")))
cat(sprintf("  Weeks covered: %d to %d (%d weeks)\n",
            min(df_final$week), max(df_final$week),
            length(unique(df_final$week))))
cat(sprintf("  Temperature range: %.2f to %.2f °C\n",
            min(df_final$temp_mean_C, na.rm = TRUE),
            max(df_final$temp_mean_C, na.rm = TRUE)))
cat(sprintf("  SD range: %.2f to %.2f °C\n",
            min(df_final$temp_sd_C, na.rm = TRUE),
            max(df_final$temp_sd_C, na.rm = TRUE)))

cat("\nFirst 10 rows:\n")
print(head(df_final, 10))

cat("\n════════════════════════════════════════════════════════════════════════════\n")
cat("HOW TO USE THIS DATA\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")

cat("In R:\n")
cat("  haduk <- read.csv('", basename(out_csv), "')\n", sep = "")
cat("  # Join with eBird data by cell_id and week\n")
cat("  merged <- left_join(ebird_data, haduk, by = c('cell_id', 'week'))\n\n")

cat("In Python:\n")
cat("  import pandas as pd\n")
cat("  haduk = pd.read_csv('", basename(out_csv), "')\n", sep = "")
cat("  # Join with eBird data\n")
cat("  merged = ebird_data.merge(haduk, on=['cell_id', 'week'], how='left')\n")

cat("\n════════════════════════════════════════════════════════════════════════════\n")
cat("✓ COMPLETE\n")
cat("════════════════════════════════════════════════════════════════════════════\n\n")
