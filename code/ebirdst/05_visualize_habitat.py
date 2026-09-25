"""
05_visualize_habitat.py
Generate static plots and interactive map for Canada Goose abundance vs habitat analysis

Outputs:
- Static plots (PNG): Abundance by habitat, seasonal comparisons, spatial distributions
- Interactive map (HTML): Combined land cover and abundance visualization with layers
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import folium
from folium import plugins
import geopandas as gpd
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# Configuration
DATA_FILE = Path("outputs/cangoo_abundance_with_landcover.csv")
OUTPUT_DIR = Path("outputs/visualizations")
OUTPUT_DIR.mkdir(exist_ok=True)

# Color palette for seasons
SEASON_COLORS = {
    'breeding': '#2ecc71',  # Green
    'nonbreeding': '#3498db',  # Blue
    'prebreeding_migration': '#f39c12',  # Orange
    'postbreeding_migration': '#e74c3c'  # Red
}

SEASON_ORDER = ['breeding', 'nonbreeding', 'prebreeding_migration', 'postbreeding_migration']
SEASON_LABELS = {
    'breeding': 'Breeding',
    'nonbreeding': 'Non-breeding',
    'prebreeding_migration': 'Pre-breeding Migration',
    'postbreeding_migration': 'Post-breeding Migration'
}

print("=" * 60)
print("Canada Goose Habitat Analysis - Visualization Suite")
print("=" * 60)

# === 1. Load Data ===
print("\n[1/6] Loading data...")
df = pd.read_csv(DATA_FILE)
print(f"  Loaded {len(df):,} records")
print(f"  Seasons: {df['season'].nunique()}")
print(f"  Unique cells: {df['cell_id'].nunique():,}")
print(f"  Land cover classes: {df['landcover_class'].nunique()}")

# Filter out zero abundance for some plots (to focus on presence)
df_present = df[df['abundance'] > 0].copy()
print(f"  Cells with presence (abundance > 0): {len(df_present):,} ({100*len(df_present)/len(df):.1f}%)")

# === 2. Static Plots ===
print("\n[2/6] Generating static plots...")

# Set style
sns.set_style("whitegrid")
plt.rcParams['figure.dpi'] = 150
plt.rcParams['savefig.dpi'] = 150

# --- Plot 1: Abundance by Habitat Type (Boxplot) ---
print("  Plot 1: Abundance by habitat type...")
fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle('Canada Goose Abundance by Land Cover Type (Per Season)', fontsize=16, fontweight='bold')

for idx, season in enumerate(SEASON_ORDER):
    ax = axes[idx // 2, idx % 2]
    season_data = df_present[df_present['season'] == season].copy()

    # Get top 10 habitats by mean abundance
    top_habitats = (season_data.groupby('landcover_name')['abundance']
                    .mean()
                    .sort_values(ascending=False)
                    .head(10)
                    .index)

    plot_data = season_data[season_data['landcover_name'].isin(top_habitats)]

    sns.boxplot(data=plot_data, y='landcover_name', x='abundance',
                order=top_habitats, color=SEASON_COLORS[season], ax=ax)
    ax.set_title(SEASON_LABELS[season], fontsize=12, fontweight='bold')
    ax.set_xlabel('Relative Abundance', fontsize=10)
    ax.set_ylabel('Land Cover Type', fontsize=10)
    ax.set_xlim(0, plot_data['abundance'].quantile(0.95))  # Trim outliers for visibility

plt.tight_layout()
plt.savefig(OUTPUT_DIR / "01_abundance_by_habitat_boxplot.png", bbox_inches='tight')
print(f"    Saved: 01_abundance_by_habitat_boxplot.png")
plt.close()

# --- Plot 2: Mean Abundance by Habitat (Bar Chart Comparison) ---
print("  Plot 2: Mean abundance comparison across seasons...")
fig, ax = plt.subplots(figsize=(14, 8))

# Calculate mean abundance by habitat and season
habitat_means = (df_present.groupby(['season', 'landcover_name'])['abundance']
                 .mean()
                 .reset_index())

# Get top 12 habitats overall
top_habitats = (df_present.groupby('landcover_name')['abundance']
                .mean()
                .sort_values(ascending=False)
                .head(12)
                .index)

plot_data = habitat_means[habitat_means['landcover_name'].isin(top_habitats)]
plot_data['season_label'] = plot_data['season'].map(SEASON_LABELS)

# Pivot for grouped bar chart
pivot_data = plot_data.pivot(index='landcover_name', columns='season', values='abundance')
pivot_data = pivot_data.reindex(top_habitats)

pivot_data.plot(kind='bar', ax=ax, color=[SEASON_COLORS[s] for s in SEASON_ORDER], width=0.8)
ax.set_title('Mean Abundance by Land Cover Type and Season\n(Top 12 Habitats)',
             fontsize=14, fontweight='bold')
ax.set_xlabel('Land Cover Type', fontsize=11)
ax.set_ylabel('Mean Relative Abundance', fontsize=11)
ax.legend(title='Season', labels=[SEASON_LABELS[s] for s in SEASON_ORDER],
          bbox_to_anchor=(1.05, 1), loc='upper left')
ax.grid(axis='y', alpha=0.3)
plt.xticks(rotation=45, ha='right')
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "02_mean_abundance_by_habitat_seasons.png", bbox_inches='tight')
print(f"    Saved: 02_mean_abundance_by_habitat_seasons.png")
plt.close()

# --- Plot 3: Habitat Composition (Proportion of Cells) ---
print("  Plot 3: Habitat composition pie charts...")
fig, axes = plt.subplots(2, 2, figsize=(14, 12))
fig.suptitle('Land Cover Composition by Season\n(Proportion of Grid Cells)',
             fontsize=16, fontweight='bold')

for idx, season in enumerate(SEASON_ORDER):
    ax = axes[idx // 2, idx % 2]
    season_data = df[df['season'] == season]

    # Get top 8 habitats, group rest as "Other"
    habitat_counts = season_data['landcover_name'].value_counts()
    top_8 = habitat_counts.head(8)
    other_count = habitat_counts[8:].sum()

    if other_count > 0:
        plot_counts = pd.concat([top_8, pd.Series({'Other': other_count})])
    else:
        plot_counts = top_8

    colors = sns.color_palette("husl", len(plot_counts))
    ax.pie(plot_counts.values, labels=plot_counts.index, autopct='%1.1f%%',
           startangle=90, colors=colors, textprops={'fontsize': 8})
    ax.set_title(SEASON_LABELS[season], fontsize=12, fontweight='bold')

plt.tight_layout()
plt.savefig(OUTPUT_DIR / "03_habitat_composition_pie.png", bbox_inches='tight')
print(f"    Saved: 03_habitat_composition_pie.png")
plt.close()

# --- Plot 4: Seasonal Abundance Distribution (Histogram) ---
print("  Plot 4: Abundance distribution histograms...")
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('Canada Goose Abundance Distribution by Season', fontsize=16, fontweight='bold')

for idx, season in enumerate(SEASON_ORDER):
    ax = axes[idx // 2, idx % 2]
    season_data = df[df['season'] == season]['abundance']

    # Plot on log scale for better visibility
    season_data_nonzero = season_data[season_data > 0]

    ax.hist(season_data_nonzero, bins=50, color=SEASON_COLORS[season], alpha=0.7, edgecolor='black')
    ax.set_title(f"{SEASON_LABELS[season]}\n(n={len(season_data_nonzero):,} cells with presence)",
                 fontsize=11, fontweight='bold')
    ax.set_xlabel('Relative Abundance', fontsize=10)
    ax.set_ylabel('Number of Grid Cells', fontsize=10)
    ax.set_yscale('log')

    # Add mean line
    mean_val = season_data_nonzero.mean()
    ax.axvline(mean_val, color='red', linestyle='--', linewidth=2, label=f'Mean: {mean_val:.2f}')
    ax.legend()

plt.tight_layout()
plt.savefig(OUTPUT_DIR / "04_abundance_distribution_histograms.png", bbox_inches='tight')
print(f"    Saved: 04_abundance_distribution_histograms.png")
plt.close()

# --- Plot 5: Top Habitat Preferences (Heatmap) ---
print("  Plot 5: Habitat preference heatmap...")
# Calculate mean abundance for top habitats across seasons
top_10_habitats = (df_present.groupby('landcover_name')['abundance']
                   .mean()
                   .sort_values(ascending=False)
                   .head(10)
                   .index)

heatmap_data = (df_present[df_present['landcover_name'].isin(top_10_habitats)]
                .groupby(['landcover_name', 'season'])['abundance']
                .mean()
                .reset_index()
                .pivot(index='landcover_name', columns='season', values='abundance'))

heatmap_data = heatmap_data[SEASON_ORDER]  # Reorder columns
heatmap_data = heatmap_data.reindex(top_10_habitats)  # Reorder rows

fig, ax = plt.subplots(figsize=(10, 8))
sns.heatmap(heatmap_data, annot=True, fmt='.2f', cmap='YlOrRd',
            cbar_kws={'label': 'Mean Abundance'}, ax=ax)
ax.set_title('Mean Abundance Heatmap: Top 10 Habitats vs. Season', fontsize=14, fontweight='bold')
ax.set_xlabel('Season', fontsize=11)
ax.set_ylabel('Land Cover Type', fontsize=11)
ax.set_xticklabels([SEASON_LABELS[s] for s in SEASON_ORDER], rotation=45, ha='right')
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "05_habitat_preference_heatmap.png", bbox_inches='tight')
print(f"    Saved: 05_habitat_preference_heatmap.png")
plt.close()

print(f"\n  All static plots saved to: {OUTPUT_DIR}/")

# === 3. Interactive Map ===
print("\n[3/6] Creating interactive map...")

# Convert British National Grid (EPSG:27700) to WGS84 (EPSG:4326) for web mapping
print("  Converting coordinates to WGS84...")
gdf = gpd.GeoDataFrame(
    df,
    geometry=gpd.points_from_xy(df['x'], df['y']),
    crs='EPSG:27700'
)
gdf_wgs84 = gdf.to_crs('EPSG:4326')

# Extract lat/lon
df['lon'] = gdf_wgs84.geometry.x
df['lat'] = gdf_wgs84.geometry.y

# Calculate map center (median of all coordinates)
center_lat = df['lat'].median()
center_lon = df['lon'].median()

print(f"  Map center: {center_lat:.4f}, {center_lon:.4f}")
print(f"  Creating map with all seasons...")

# === 4. Build Folium Map ===
print("\n[4/6] Building folium map layers...")

# Calculate grid cell size (in degrees) - UKCEH is 1km resolution
# For EPSG:27700, 1km = 1000m. Convert to approximate degrees at UK latitude
# At 55°N, 1km ≈ 0.0089° latitude, 0.0156° longitude (approximate)
CELL_SIZE_LAT = 0.0089
CELL_SIZE_LON = 0.0156

# Create base map
m = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=6,
    tiles='OpenStreetMap',
    control_scale=True
)

# Add alternative base maps
folium.TileLayer('CartoDB positron', name='CartoDB Light').add_to(m)
folium.TileLayer('CartoDB dark_matter', name='CartoDB Dark').add_to(m)

# Define color map for land cover classes
landcover_colors = {
    'Broadleaved woodland': '#2d5016',
    'Coniferous woodland': '#0b6623',
    'Arable': '#f4c430',
    'Improved grassland': '#7cfc00',
    'Neutral grassland': '#90ee90',
    'Calcareous grassland': '#98fb98',
    'Acid grassland': '#8fbc8f',
    'Fen, Marsh and Swamp': '#4a708b',
    'Heather and shrub': '#9370db',
    'Heather grassland': '#dda0dd',
    'Bog': '#704214',
    'Inland rock': '#808080',
    'Saltwater': '#0077be',
    'Freshwater': '#4682b4',
    'Supralittoral rock': '#a9a9a9',
    'Supralittoral sediment': '#d2b48c',
    'Littoral rock': '#696969',
    'Littoral sediment': '#deb887',
    'Saltmarsh': '#6b8e23',
    'Urban': '#ff0000',
    'Suburban': '#ff6347'
}

# Get unique land cover classes
unique_landcovers = sorted(df['landcover_name'].unique())

# Create layers for each season and land cover combination
print("  Creating season and land cover layers...")

# Sample data once for all seasons for performance
df_sample = df.iloc[::3].copy()

# Create separate land cover layers for EACH season
# Structure: {season: {landcover: FeatureGroup}}
season_landcover_layers = {}

for season in SEASON_ORDER:
    print(f"    Processing {season}...")
    season_landcover_layers[season] = {}

    df_season = df_sample[df_sample['season'] == season].copy()

    for landcover in unique_landcovers:
        df_lc = df_season[df_season['landcover_name'] == landcover].copy()

        if len(df_lc) == 0:
            continue

        color = landcover_colors.get(landcover, '#666666')

        # Create a layer for this land cover in this specific season
        # Layer name format: "LC_SeasonName_LandcoverName"
        layer_name = f'LC_{season}_{landcover}'
        lc_layer = folium.FeatureGroup(name=layer_name, show=True, overlay=True)

        # Add rectangles for each grid cell
        for _, row in df_lc.iterrows():
            # Calculate rectangle bounds (centered on cell)
            bounds = [
                [row['lat'] - CELL_SIZE_LAT/2, row['lon'] - CELL_SIZE_LON/2],  # SW corner
                [row['lat'] + CELL_SIZE_LAT/2, row['lon'] + CELL_SIZE_LON/2]   # NE corner
            ]

            folium.Rectangle(
                bounds=bounds,
                color=color,
                fill=True,
                fillColor=color,
                fillOpacity=0.5,  # 50% opacity as requested
                weight=1,
                opacity=0.8,
                popup=f"<b>{landcover}</b><br>"
                      f"Season: {SEASON_LABELS[season]}<br>"
                      f"Abundance: {row['abundance']:.3f}<br>"
                      f"Location: ({row['x']:.0f}, {row['y']:.0f})"
            ).add_to(lc_layer)

        season_landcover_layers[season][landcover] = lc_layer
        lc_layer.add_to(m)

# --- Add Abundance Heatmaps (one per season, mutually exclusive) ---
print("  Creating abundance heatmaps (one visible at a time)...")

heatmap_layers = {}
for idx, season in enumerate(SEASON_ORDER):
    df_season = df[df['season'] == season].copy()
    df_heatmap = df_season[df_season['abundance'] > 0].copy()

    if len(df_heatmap) == 0:
        continue

    heatmap_data = df_heatmap[['lat', 'lon', 'abundance']].values.tolist()

    # Only show breeding season by default
    show_default = (season == 'breeding')

    heatmap_layer = plugins.HeatMap(
        heatmap_data,
        name=f'HM_{season}',  # Internal name for JavaScript
        min_opacity=0.3,
        max_zoom=13,
        radius=15,
        blur=20,
        gradient={
            0.0: 'blue',
            0.5: 'lime',
            0.7: 'yellow',
            1.0: 'red'
        },
        show=show_default
    )
    heatmap_layer.add_to(m)
    heatmap_layers[season] = heatmap_layer

# === 5. Add Map Controls ===
print("\n[5/6] Adding map controls and legend...")

# Add custom JavaScript for season and land cover control
season_landcover_control_js = f"""
<script>
var currentSeason = 'breeding';  // Default season
var landcoverStates = {{}};  // Track which land covers are enabled

// Initialize land cover states
{str(unique_landcovers).replace("'", '"')}.forEach(function(lc) {{
    landcoverStates[lc] = true;  // All enabled by default
}});

// Helper function to update map layers based on current season and land cover states
function updateMapLayers() {{
    var map = document.querySelector('.follet-container')?.leafletElement ||
              window.map;

    if (!map) return;

    // Update all land cover layers
    {str(SEASON_ORDER).replace("'", '"')}.forEach(function(season) {{
        {str(unique_landcovers).replace("'", '"')}.forEach(function(landcover) {{
            var layerName = 'LC_' + season + '_' + landcover;

            // Find the layer
            map.eachLayer(function(layer) {{
                if (layer.options && layer.options.name === layerName) {{
                    var shouldShow = (season === currentSeason) && landcoverStates[landcover];

                    if (shouldShow && !map.hasLayer(layer)) {{
                        map.addLayer(layer);
                    }} else if (!shouldShow && map.hasLayer(layer)) {{
                        map.removeLayer(layer);
                    }}
                }}
            }});
        }});
    }});

    // Update heatmap layers (only show heatmap for current season)
    {str(SEASON_ORDER).replace("'", '"')}.forEach(function(season) {{
        var hmLayerName = 'HM_' + season;
        map.eachLayer(function(layer) {{
            if (layer.options && layer.options.name === hmLayerName) {{
                var shouldShow = (season === currentSeason);
                if (shouldShow && !map.hasLayer(layer)) {{
                    map.addLayer(layer);
                }} else if (!shouldShow && map.hasLayer(layer)) {{
                    map.removeLayer(layer);
                }}
            }}
        }});
    }});
}}

// Function to switch season
function switchSeason(season) {{
    if (currentSeason !== season) {{
        currentSeason = season;
        updateMapLayers();

        // Update UI to reflect current season
        document.querySelectorAll('.season-button').forEach(function(btn) {{
            if (btn.dataset.season === season) {{
                btn.classList.add('active');
            }} else {{
                btn.classList.remove('active');
            }}
        }});
    }}
}}

// Function to toggle land cover
function toggleLandcover(landcover) {{
    landcoverStates[landcover] = !landcoverStates[landcover];
    updateMapLayers();
}}

// Initialize after DOM loads
document.addEventListener('DOMContentLoaded', function() {{
    updateMapLayers();
}});
</script>

<style>
.custom-control-panel {{
    position: fixed;
    top: 140px;
    right: 10px;
    background-color: white;
    border: 2px solid grey;
    border-radius: 5px;
    padding: 10px;
    z-index: 9999;
    box-shadow: 3px 3px 10px rgba(0,0,0,0.3);
    max-height: calc(100vh - 200px);
    overflow-y: auto;
    width: 280px;
}}

.custom-control-panel h4 {{
    margin: 0 0 10px 0;
    font-size: 14px;
    font-weight: bold;
}}

.season-selector {{
    margin-bottom: 15px;
}}

.season-button {{
    display: block;
    width: 100%;
    padding: 8px;
    margin: 4px 0;
    background-color: #f0f0f0;
    border: 2px solid #ccc;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
    text-align: left;
}}

.season-button:hover {{
    background-color: #e0e0e0;
}}

.season-button.active {{
    background-color: #4CAF50;
    color: white;
    border-color: #45a049;
    font-weight: bold;
}}

.landcover-controls {{
    margin-top: 10px;
}}

.landcover-item {{
    margin: 4px 0;
    font-size: 11px;
}}

.landcover-item input[type="checkbox"] {{
    margin-right: 6px;
}}

.landcover-color {{
    display: inline-block;
    width: 12px;
    height: 12px;
    margin-right: 4px;
    border: 1px solid #333;
}}
</style>

<!-- Custom Control Panel -->
<div class="custom-control-panel">
    <h4>Season Selection</h4>
    <div class="season-selector">
"""

# Add season buttons
for season in SEASON_ORDER:
    active_class = ' active' if season == 'breeding' else ''
    season_landcover_control_js += f"""
        <button class="season-button{active_class}" data-season="{season}" onclick="switchSeason('{season}')">
            {SEASON_LABELS[season]}
        </button>
"""

season_landcover_control_js += """
    </div>

    <h4>Land Cover Categories</h4>
    <div class="landcover-controls">
"""

# Add land cover checkboxes
for landcover in unique_landcovers:
    color = landcover_colors.get(landcover, '#666666')
    season_landcover_control_js += f"""
        <div class="landcover-item">
            <input type="checkbox" id="lc_{landcover.replace(' ', '_')}" checked
                   onchange="toggleLandcover('{landcover}')">
            <span class="landcover-color" style="background-color:{color}"></span>
            <label for="lc_{landcover.replace(' ', '_')}">{landcover}</label>
        </div>
"""

season_landcover_control_js += """
    </div>
</div>
"""

m.get_root().html.add_child(folium.Element(season_landcover_control_js))

# Add title
title_html = '''
<div style="position: fixed;
            top: 10px; left: 50px; width: 450px; height: 90px;
            background-color: white; border:2px solid grey; z-index:9999;
            font-size:14px; padding: 10px; box-shadow: 3px 3px 10px rgba(0,0,0,0.3);">
<h4 style="margin-top:0">Canada Goose Distribution - Interactive Map</h4>
<p style="margin:0; font-size:12px">
Use the control panel (right) to select season and toggle land cover types<br>
<b>Abundance heatmap</b> updates automatically with season selection
</p>
</div>
'''
m.get_root().html.add_child(folium.Element(title_html))

# === 6. Save Outputs ===
print("\n[6/6] Saving map...")
map_file = OUTPUT_DIR / "06_interactive_map_abundance_landcover.html"
m.save(str(map_file))
print(f"  Saved: {map_file}")
print(f"  File size: {map_file.stat().st_size / 1024 / 1024:.1f} MB")

# === Summary ===
print("\n" + "=" * 60)
print("VISUALIZATION COMPLETE")
print("=" * 60)
print(f"\nGenerated files in {OUTPUT_DIR}/:")
print("  1. 01_abundance_by_habitat_boxplot.png")
print("  2. 02_mean_abundance_by_habitat_seasons.png")
print("  3. 03_habitat_composition_pie.png")
print("  4. 04_abundance_distribution_histograms.png")
print("  5. 05_habitat_preference_heatmap.png")
print("  6. 06_interactive_map_abundance_landcover.html")
print(f"\nOpen the HTML file in your browser to explore the interactive map!")
print("=" * 60)
