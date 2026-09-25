# HadUK-Grid harness

Working code for processing Met Office HadUK-Grid daily temperature into a weekly product on the 3 km eBird Status grid. Parallel to `code/ebirdst/` in structure.

## One-time setup

1. Register at CEDA: `https://services.ceda.ac.uk/cedasite/register/start/`. Free for academic use.
2. Accept the HadUK-Grid license via the catalogue page.
3. Download the relevant NetCDF files (see "Download targets" below) into `code/haduk/data/raw/`.

No new R packages required beyond what `code/ebirdst/01_setup.R` already installs (`terra`, `sf`, `ncdf4` if not already pulled in by `terra`).

## Download targets

For v0.1:

- Variable: `tasmean` (daily mean temperature, units °C).
- Resolution: 1 km.
- Temporal: day.
- Year: match the eBird Status year (currently 2023).
- Path on CEDA archive: navigate from the HadUK-Grid record to `1km/tasmean/day/<version>/`.
- Filename pattern: `tasmean_hadukgrid_uk_1km_day_YYYYMM01-YYYYMMDD.nc`.

Optional additions:
- `tasmin` and `tasmax` for daily range as an additional feature.
- Other years if you want multi-year analysis later.

## Daily usage

After the raw NetCDF is in `code/haduk/data/raw/`:

```r
source("02_process_haduk.R")   # aggregate daily to weekly, downsample 1km to 3km, save
```

## Outputs

Files written to `code/haduk/outputs/`:

- `tasmean_weekly_2023_3km_mean.tif`: 52-layer raster, mean weekly temperature per 3 km cell.
- `tasmean_weekly_2023_3km_sd.tif`: 52-layer raster, standard deviation of temperature across the 9 underlying 1 km cells within each 3 km cell. The temperature heterogeneity feature.

Both are written in British National Grid (EPSG:27700) for display. The processing script also produces a version reprojected to the eBird sinusoidal CRS for joining with eBird Status rasters.

## Notes

- HadUK 1 km native CRS is British National Grid (EPSG:27700).
- The 3 km eBird Status grid is in a sinusoidal equal-area projection. Joining requires reprojecting the 3 km HadUK output, not the other way round (reprojecting at the higher resolution introduces less error).
- Daily-to-weekly aggregation uses ISO week numbers (so week 1 starts on the first Monday of the year). Adjust if eBird Status uses a different week convention.
- Standard deviation across the 9 underlying 1 km cells is captured as a feature in its own right, in the same spirit as the land cover fragmentation metrics.
