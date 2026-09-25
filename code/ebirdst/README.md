# ebirdst harness

Working code for pulling, inspecting, and mapping eBird Status products in R. Three numbered scripts: setup, explore which species are available, pull a specific species and produce a UK map and stats.

## One-time setup

1. Install R (4.2 or newer) if you don't already have it.
2. From any R session, source `01_setup.R`. It will install the required packages.
3. Set your eBird Status access key. The cleanest way is to add a line to `~/.Renviron`:
   ```
   EBIRDST_KEY=your_key_here
   ```
   Restart R after editing. Alternative: call `ebirdst::set_ebirdst_access_key("your_key_here", overwrite = TRUE)` once interactively.
4. Verify by running `Sys.getenv("EBIRDST_KEY")` in R. You should see your key (not an empty string).

## Daily usage

Open R in this directory (so working directory resolves correctly), then:

```r
source("02_explore_runs.R")   # see which species have Status products
source("03_pull_and_map.R")    # pull one species, crop to UK, produce map and stats
```

### Configuration

Edit `03_pull_and_map.R` at the top to change:
- `focal_species_common`: Species common name (e.g., "Canada Goose", "European Robin")
- `season`: One of `"breeding"`, `"nonbreeding"`, `"prebreeding_migration"`, `"postbreeding_migration"`

### Outputs

Files are organized in `outputs/` subdirectories:
- **TIF files**: `outputs/tif/{species_code}_{season}_uk_abundance.tif` - Cropped UK abundance rasters
- **PNG files**: `outputs/png/{species_code}_{season}_uk_map.png` - Map visualizations
- **Summary stats**: Printed to console (non-NA cells, mean, median, max, stdev)

## Data storage and conventions

### Download cache
eBird Status data is downloaded to: `~/Library/Application Support/org.R-project.R/R/ebirdst/`

Structure:
```
ebirdst/
└── 2023/                          (data version year)
    └── {species_code}/            (e.g., cangoo, eurrob1)
        ├── config.json
        └── seasonal/
            ├── {species}_abundance_seasonal_mean_3km_2023.tif
            └── {species}_abundance_seasonal_max_3km_2023.tif
```

**Note**: The script downloads only 3km resolution data (pattern: `abundance_seasonal.*_3km_`). eBird also provides 9km and 27km resolutions, but these are skipped to save space and download time.

Cached files persist between runs. To re-download, delete the species folder or use `force = TRUE` in the download function.

### Coordinate reference systems
- **Native eBird CRS**: Sinusoidal equal-area projection (~3km resolution)
- **Analysis CRS**: Processing done in native CRS
- **Display CRS**: British National Grid (EPSG:27700) for UK maps only

## Function reference compatibility

The scripts use the `ebirdst` v3.x API (post-2024 redesign). If your installed version is older, function names may differ (`ebirdst_download()` instead of `ebirdst_download_status()`, etc.). Check `packageVersion("ebirdst")` and update with `install.packages("ebirdst")` if needed.

## What this codebase does NOT do yet

- No habitat-layer joins (UKCEH, NDVI, climate). That's the next step after the meeting once the resolution and aggregation strategy are locked.
- No multi-species batch processing. Easy to wrap once the single-species path is verified.
- No uncertainty layer handling. eBird Status publishes lower/upper bounds alongside the mean; current scripts ignore them.
