# build_landcover_3km_type_counts.R
# For each 3 km cell, COUNT how many of its constituent 1 km squares are
# dominantly each of the 9 Strategy-2 classes.
#
# WHY: the 3 km composition file gives mean PERCENTAGE cover per class. This
# instead gives an integer COUNT — of the ~9 land 1 km squares that make up each
# 3 km cell, how many are dominantly woodland / arable / ... / builtup. The
# per-cell counts sum to that cell's number of 1 km land members (n_1km_members).
#
# INPUT: ukceh_landcover_composition_1km_strategy2_aggregate9.csv
#        (built by build_landcover_1km_members.R — each 1 km land square with its
#         dominant_class and parent_cell_id = its 3 km cell).
#
# OUTPUT: ukceh_landcover_composition_3km_strategy2_typecounts.csv
# Columns: cell_id, x, y,
#          n_woodland, n_arable, n_improved_grassland, n_seminat_grassland,
#          n_mountain_heath_bog, n_saltwater, n_freshwater, n_coastal, n_builtup,
#          n_1km_members
# One row per documented 3 km cell (the 28,107 with >=1 land member).

suppressWarnings(suppressMessages({
  library(dplyr)
  library(tidyr)
  library(readr)
}))

cat("=== 3 km per-type 1 km-square counts (Strategy 2, 9 classes) ===\n\n")

# --- Paths (resolve relative to this script's location) ---------------------
this_script <- tryCatch(
  normalizePath(sub("^--file=", "",
                    grep("^--file=", commandArgs(FALSE), value = TRUE)[1])),
  error = function(e) NA_character_
)
script_dir <- if (!is.na(this_script)) dirname(this_script) else getwd()

input_file  <- file.path(script_dir, "outputs",
                         "ukceh_landcover_composition_1km_strategy2_aggregate9.csv")
output_file <- file.path(script_dir, "outputs",
                         "ukceh_landcover_composition_3km_strategy2_typecounts.csv")

# The 9 Strategy-2 class labels, in canonical order (matches dominant_class
# values, which are the merged column names with the "pct_" prefix stripped).
class_labels <- c("woodland", "arable", "improved_grassland", "seminat_grassland",
                  "mountain_heath_bog", "saltwater", "freshwater", "coastal",
                  "builtup")

# --- Load the 1 km member list ----------------------------------------------
cat("Reading 1 km member list...\n")
km1 <- read_csv(input_file, show_col_types = FALSE)
stopifnot(all(c("parent_cell_id", "dominant_class") %in% names(km1)))
cat(sprintf("  %d 1 km land squares\n", nrow(km1)))

# Land-only file should carry no Undocumented rows, but guard anyway.
km1 <- km1 %>% filter(dominant_class != "Undocumented")

# --- Count 1 km squares per (3 km parent, dominant class) --------------------
cat("Counting 1 km squares by dominant class within each 3 km cell...\n")
counts <- km1 %>%
  mutate(dominant_class = factor(dominant_class, levels = class_labels)) %>%
  count(parent_cell_id, dominant_class, name = "n", .drop = FALSE) %>%
  pivot_wider(names_from = dominant_class, values_from = n,
              names_prefix = "n_", values_fill = 0)

# Ensure every class column exists and is ordered, then add the total.
n_cols <- paste0("n_", class_labels)
for (nc in n_cols) if (!nc %in% names(counts)) counts[[nc]] <- 0L
counts <- counts %>%
  mutate(n_1km_members = rowSums(across(all_of(n_cols)))) %>%
  rename(cell_id = parent_cell_id)

# --- Attach 3 km centroid coords from the 3 km reference (if available) ------
ref_3km <- file.path(script_dir, "outputs",
                     "ukceh_landcover_composition_3km_strategy2_aggregate9.csv")
if (file.exists(ref_3km)) {
  cat("Attaching 3 km centroid coords from the 3 km reference...\n")
  ref <- read_csv(ref_3km, show_col_types = FALSE) %>% select(cell_id, x, y)
  counts <- counts %>% left_join(ref, by = "cell_id")
} else {
  cat("  (3 km reference not found; writing without x/y)\n")
  counts$x <- NA_real_; counts$y <- NA_real_
}

out <- counts %>% select(cell_id, x, y, all_of(n_cols), n_1km_members)

# --- Validation --------------------------------------------------------------
cat("\n=== Validation ===\n")
cat(sprintf("3 km cells with counts: %d\n", nrow(out)))
cat(sprintf("total 1 km members counted: %d (should equal the 1 km land rows)\n",
            sum(out$n_1km_members)))
cat(sprintf("per-class n columns sum == n_1km_members for every row: %s\n",
            all(rowSums(out[n_cols]) == out$n_1km_members)))
cat(sprintf("members per 3 km cell: min %d / median %d / max %d\n",
            min(out$n_1km_members), as.integer(median(out$n_1km_members)),
            max(out$n_1km_members)))

# cross-check against the 3 km reference: same set of cell_ids?
if (file.exists(ref_3km)) {
  ref_doc <- read_csv(ref_3km, show_col_types = FALSE) %>%
    filter(dominant_class != "Undocumented") %>% pull(cell_id)
  cat(sprintf("cell_ids match the 3 km documented set: %s (%d vs %d)\n",
              setequal(out$cell_id, ref_doc), nrow(out), length(ref_doc)))
}

cat("\nExample rows:\n")
print(head(out, 3))

# --- Write -------------------------------------------------------------------
write_csv(out, output_file)
cat(sprintf("\nWrote %s\n  rows: %d   cols: %d\n",
            output_file, nrow(out), ncol(out)))
cat("\n=== Complete ===\n")
