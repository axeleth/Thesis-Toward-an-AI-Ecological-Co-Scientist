# download_accipitridae.R
#
# Download script for UK Accipitridae species (hawks, eagles, and kites)
# This script downloads 2023 eBird Status data for:
#   - Hen Harrier
#   - Golden Eagle
#   - Eurasian Sparrowhawk
#   - Red Kite
#   - Common Buzzard
#
# For historical data (2020-2022), you'll need to contact Cornell Lab
# as API access has expired for those years.

library(ebirdst)
library(jsonlite)
library(here)

# === Configuration ===
species_json   <- here("code", "ebirdst", "species_list.json")
species_group  <- "accipitridae_uk"   # Process our new Accipitridae group
target_pattern <- "abundance_median.*_3km_"   # weekly 3km median
max_retries    <- 10
sleep_seconds  <- 5

# === Load species list from JSON ===
cat("Reading species list from ", species_json, "\n", sep = "")
all_groups <- fromJSON(species_json, simplifyVector = FALSE)

if (!species_group %in% names(all_groups)) {
  stop(sprintf("Species group '%s' not found in JSON. Available: %s",
               species_group, paste(names(all_groups), collapse = ", ")))
}

group <- all_groups[[species_group]]
cat("\nGroup: ", species_group, "\n", sep = "")
cat("Description: ", group$description, "\n", sep = "")
cat("Species count: ", length(group$species), "\n\n", sep = "")

# === Resolve species against ebirdst_runs ===
runs <- ebirdst_runs

species_table <- do.call(rbind, lapply(group$species, function(s) {
  match_row <- runs[runs$scientific_name == s$scientific_name, ]
  data.frame(
    common_name     = s$common_name,
    scientific_name = s$scientific_name,
    species_code    = if (nrow(match_row) > 0) match_row$species_code[1] else NA_character_,
    in_runs         = nrow(match_row) > 0,
    stringsAsFactors = FALSE
  )
}))

cat("Resolution summary:\n")
cat(sprintf("  Resolved: %d/%d species\n",
            sum(species_table$in_runs), nrow(species_table)))
missing <- species_table[!species_table$in_runs, "scientific_name"]
if (length(missing) > 0) {
  cat("  Not found in ebirdst_runs (will be skipped):\n")
  for (m in missing) cat("    ", m, "\n", sep = "")
}

# Display the species codes we found
cat("\nSpecies codes resolved:\n")
for (i in seq_len(nrow(species_table))) {
  sp <- species_table[i, ]
  cat(sprintf("  %s (%s): %s\n",
              sp$common_name,
              sp$scientific_name,
              ifelse(is.na(sp$species_code), "NOT FOUND", sp$species_code)))
}

# === Retry-on-500 download helper ===
try_download <- function(common_name, species_code, pattern,
                        max_retries = 10, sleep_seconds = 5) {
  cat(sprintf("Calling ebirdst_download_status(\"%s\", pattern = \"%s\") with up to %d retries...\n",
              species_code, pattern, max_retries))

  for (attempt in seq_len(max_retries)) {
    cat(sprintf("  Attempt %d/%d... ", attempt, max_retries))
    flush.console()

    attempt_result <- tryCatch({
      ebirdst_download_status(species_code, pattern = pattern)
      list(ok = TRUE, msg = "SUCCESS")
    }, error = function(e) {
      list(ok = FALSE, msg = conditionMessage(e))
    })

    if (isTRUE(attempt_result$ok)) {
      cat("SUCCESS\n")
      return(list(status = "SUCCESS",
                  attempts = attempt,
                  message = sprintf("Succeeded on attempt %d/%d", attempt, max_retries)))
    } else {
      cat("FAILED\n")
      cat(sprintf("    Error: %s\n", attempt_result$msg))
      if (attempt < max_retries) {
        cat(sprintf("    Sleeping %d seconds before retry...\n", sleep_seconds))
        Sys.sleep(sleep_seconds)
      }
    }
  }

  return(list(status = "FAILED",
              attempts = max_retries,
              message = sprintf("Failed after %d attempts; moving on.", max_retries)))
}

# === Main loop ===
cat("\n", strrep("=", 78), "\n", sep = "")
cat("DOWNLOADING ACCIPITRIDAE SPECIES (2023 DATA)\n")
cat(strrep("=", 78), "\n", sep = "")
cat("\nNOTE: This script downloads 2023 data only. For historical data (2020-2022),\n")
cat("      see the email template in HISTORICAL_DATA_SOLUTION.md\n\n")

results <- data.frame(
  common_name     = character(),
  scientific_name = character(),
  species_code    = character(),
  status          = character(),
  attempts        = integer(),
  message         = character(),
  stringsAsFactors = FALSE
)

species_to_download <- species_table[species_table$in_runs, ]

for (i in seq_len(nrow(species_to_download))) {
  sp <- species_to_download[i, ]
  cat(sprintf("\n[%d/%d] %s (%s, code: %s)\n",
              i, nrow(species_to_download),
              sp$common_name, sp$scientific_name, sp$species_code))
  cat(strrep("-", 78), "\n", sep = "")

  result <- try_download(
    common_name   = sp$common_name,
    species_code  = sp$species_code,
    pattern       = target_pattern,
    max_retries   = max_retries,
    sleep_seconds = sleep_seconds
  )

  results <- rbind(results, data.frame(
    common_name     = sp$common_name,
    scientific_name = sp$scientific_name,
    species_code    = sp$species_code,
    status          = result$status,
    attempts        = result$attempts,
    message         = result$message,
    stringsAsFactors = FALSE
  ))
}

# === Final summary ===
cat("\n", strrep("=", 78), "\n", sep = "")
cat("DOWNLOAD SUMMARY\n")
cat(strrep("=", 78), "\n", sep = "")

n_total   <- nrow(results)
n_success <- sum(results$status == "SUCCESS")
n_failed  <- sum(results$status == "FAILED")

cat(sprintf("Total species processed: %d\n", n_total))
cat(sprintf("  SUCCESS: %d\n", n_success))
cat(sprintf("  FAILED:  %d\n", n_failed))

if (n_failed > 0) {
  cat("\nFailed species (consider rerunning later):\n")
  failed <- results[results$status == "FAILED", c("common_name", "species_code", "message")]
  print(failed, row.names = FALSE)
}

cat("\nFull results table:\n")
print(results, row.names = FALSE)

# Save results table
out_dir <- here("code", "ebirdst", "outputs")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
out_csv <- file.path(out_dir, "download_accipitridae_results.csv")
write.csv(results, out_csv, row.names = FALSE)
cat("\nResults saved to: ", out_csv, "\n", sep = "")

cat("\nDone. Successful species are now in the ebirdst cache and can be\n")
cat("processed by pull_and_map.R.\n")

cat("\n", strrep("=", 78), "\n", sep = "")
cat("NEXT STEPS:\n")
cat(strrep("=", 78), "\n", sep = "")
cat("\n1. To process the downloaded 2023 data:\n")
cat("   - Run: source('pull_and_map.R') with species_mode = 'cache'\n")
cat("   - This will process all successfully downloaded species\n")
cat("\n2. For historical data (2020-2022):\n")
cat("   - Contact Cornell Lab using the email template in HISTORICAL_DATA_SOLUTION.md\n")
cat("   - Request archived data for these 5 Accipitridae species\n")
cat("\n")