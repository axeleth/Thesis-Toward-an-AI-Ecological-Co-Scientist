#!/usr/bin/env python3
"""
Adjust UKCEH Land Cover Composition CSV

This script processes the UKCEH land cover composition data to:
1. Create an 'adjusted_dominant' column that combines woodland types
2. Create a 'pct_woodland' column that sums broadleaved and coniferous percentages

Author: Generated for thesis EAICS project
Date: 2026-06-02
"""

import pandas as pd
import os

def adjust_landcover_csv(input_path, output_path):
    """
    Adjust land cover CSV by combining woodland categories.

    Parameters:
    -----------
    input_path : str
        Path to input CSV file
    output_path : str
        Path to output CSV file
    """

    print(f"Reading input file: {input_path}")
    df = pd.read_csv(input_path)

    print(f"Original shape: {df.shape}")
    print(f"Columns: {list(df.columns)}")

    # Identify ocean cells (no land cover data)
    ocean_cells = df['total_pct'] == 0.0

    # Fix ocean cells: assign special class and name
    # Convert dominant_class to string to allow '$' marker
    df['dominant_class'] = df['dominant_class'].astype(str)
    df.loc[ocean_cells, 'dominant_class'] = '$'  # Special marker for undocumented class
    df.loc[ocean_cells, 'dominant_name'] = 'Undocumented'

    # Create adjusted_dominant column
    # Replace both woodland types with "Woodland"
    df['adjusted_dominant'] = df['dominant_name'].replace({
        'Broadleaved woodland': 'Woodland',
        'Coniferous woodland': 'Woodland'
    })

    # Ocean cells keep their Undocumented designation
    df.loc[ocean_cells, 'adjusted_dominant'] = 'Undocumented'

    # Create pct_woodland column
    # Sum of broadleaved and coniferous woodland percentages
    df['pct_woodland'] = df['pct_broadleaf'] + df['pct_conifer']

    # Display summary statistics
    print("\n=== Summary Statistics ===")
    print(f"Total cells: {len(df)}")
    print(f"Ocean cells (N/A): {ocean_cells.sum()} ({ocean_cells.sum()/len(df)*100:.2f}%)")
    print(f"Land cells: {(~ocean_cells).sum()} ({(~ocean_cells).sum()/len(df)*100:.2f}%)")

    print(f"\nOriginal dominant_name counts:")
    print(df['dominant_name'].value_counts().head(10))
    print(f"\nAdjusted dominant_name counts:")
    print(df['adjusted_dominant'].value_counts().head(10))
    print(f"\nWoodland percentage statistics:")
    print(df['pct_woodland'].describe())

    # Count cells where woodland is dominant
    woodland_dominant = df[df['adjusted_dominant'] == 'Woodland']
    print(f"\nCells with Woodland as dominant: {len(woodland_dominant)} ({len(woodland_dominant)/len(df)*100:.2f}%)")

    # Save to new CSV
    print(f"\nSaving adjusted data to: {output_path}")
    df.to_csv(output_path, index=False)
    print(f"Output shape: {df.shape}")
    print("\nDone! Adjustments made:")
    print("  1. Ocean cells (total_pct=0) now have:")
    print("     - dominant_class = '$' (undocumented class marker)")
    print("     - dominant_name = 'Undocumented'")
    print("     - adjusted_dominant = 'Undocumented'")
    print("  2. Woodland types combined:")
    print("     - 'Broadleaved woodland' + 'Coniferous woodland' → 'Woodland' in adjusted_dominant")
    print("  3. New column pct_woodland = pct_broadleaf + pct_conifer")

    return df

if __name__ == "__main__":
    # Define paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_file = os.path.join(script_dir, "..", "UKCEH_data", "outputs", "ukceh_landcover_composition_3km_wide.csv")
    output_file = os.path.join(script_dir, "..", "UKCEH_data", "outputs", "ukceh_landcover_composition_3km_wide_adjusted.csv")

    # Check if input file exists
    if not os.path.exists(input_file):
        print(f"Error: Input file not found at {input_file}")
        exit(1)

    # Run the adjustment
    df_adjusted = adjust_landcover_csv(input_file, output_file)

    print(f"\n✓ Successfully created {output_file}")
