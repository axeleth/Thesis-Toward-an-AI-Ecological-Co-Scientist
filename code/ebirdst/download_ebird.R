# download_ebird.R
#
# Main eBird Status download script. Reads a species list from species_list.json,
# resolves each species against ebirdst_runs, and downloads the requested
# product files into the local ebirdst cache. Uses a retry loop because
# Cornell's CDN intermittently returns HTTP 500 for specific files; the
# package caches successful downloads, so retrying resumes from where the
# previous attempt failed.
#
# Once this script finishes, pull_and_map.R can process whichever species
# made it into the cache.

library(ebirdst)
library(jsonlite)
library(here)

# === Configuration ===
species_json   <- here("code", "ebirdst", "species_list.json")
species_group  <- "gb_full_list"      # which group key from the JSON to process (test_passerines, accipitridae_gb, scolopacidae_gb, accipitridae_uk, or gb_full_list)
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
  sci <- if (!is.null(s$scientific_name)) s$scientific_name else ""
  com <- if (!is.null(s$common_name))     s$common_name     else ""

  # Prefer scientific_name when supplied; otherwise fall back to common_name.
  # This lets groups list species by common name only (e.g. gb_full_list).
  if (nzchar(sci)) {
    match_row <- runs[runs$scientific_name == sci, ]
  } else if (nzchar(com)) {
    match_row <- runs[runs$common_name == com, ]
  } else {
    match_row <- runs[FALSE, ]
  }

  data.frame(
    common_name     = if (nrow(match_row) > 0) match_row$common_name[1]     else com,
    scientific_name = if (nrow(match_row) > 0) match_row$scientific_name[1] else sci,
    species_code    = if (nrow(match_row) > 0) match_row$species_code[1]    else NA_character_,
    in_runs         = nrow(match_row) > 0,
    stringsAsFactors = FALSE
  )
}))

cat("Resolution summary:\n")
cat(sprintf("  Resolved: %d/%d species\n",
            sum(species_table$in_runs), nrow(species_table)))
missing <- species_table[!species_table$in_runs, ]
if (nrow(missing) > 0) {
  cat("  Not found in ebirdst_runs (will be skipped):\n")
  for (i in seq_len(nrow(missing))) {
    label <- if (nzchar(missing$scientific_name[i])) missing$scientific_name[i] else missing$common_name[i]
    cat("    ", label, "\n", sep = "")
  }
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
cat("DOWNLOADING SPECIES\n")
cat(strrep("=", 78), "\n", sep = "")

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
out_csv <- file.path(out_dir, "download_results.csv")
write.csv(results, out_csv, row.names = FALSE)
cat("\nResults saved to: ", out_csv, "\n", sep = "")

cat("\nDone. Successful species are now in the ebirdst cache and can be\n")
cat("processed by pull_and_map.R.\n")
