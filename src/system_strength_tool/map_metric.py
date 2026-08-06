"""
Generate multiple strength metric scatter-map HTML visualizations.

This script reads the common bus location file and a strength metric results file. For each
strength metric column it creates an HTML map showing strength metric values at bus locations with an even
colorbar scale.

Update Strength_Metric_Results excel file(s) to include the models you want to visualize.
"""

from pathlib import Path
import re
import argparse

import pandas as pd
import numpy as np
import plotly.express as px
import os, sys
from map_display_utils import metric_global_range, normalize_position

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
MODEL_DIR = SCRIPT_DIR / "model_data"
MAP_CONFIG = {
    'style': 'carto-positron',
    'lat': 41.2,
    'lon': -117.0,
    'zoom': 3,
}

COLORBAR_LEN = 0.6
COLORBAR_FONT_SIZE = 20


def resolve_bus_location_file(case: str | None) -> Path:
    """Resolve bus GIS workbook from the case filename keyword.

    If case filename contains WECC or Maui, use <keyword>_Bus_GIS.xlsx.
    Otherwise fallback to default BUS_LOCATION_FILE.
    """
    if not case:
        raise FileNotFoundError(case)

    case_stem = Path(case).stem
    # match = re.search(r"(WECC240|Maui24)", case_stem, flags=re.IGNORECASE)
    # if not match:
    #     return FileNotFoundError(f"No GIS file found for case: {case}")
    # keyword = match.group(1)
    prefix = case_stem.split("_")[0]
    return MODEL_DIR / f"{prefix}_Bus_GIS.xlsx"

def estimate_zoom(latitude: np.ndarray, longitude: np.ndarray) -> float:
    """Estimate zoom from point spread using a compact log-scale heuristic."""
    if latitude.size == 0 or longitude.size == 0:
        return MAP_CONFIG["zoom"]

    lat_span = float(np.max(latitude) - np.min(latitude))
    lon_span = float(np.max(longitude) - np.min(longitude))
    span = max(lat_span, lon_span, 1e-6)
    return float(np.clip(7.5 - np.log2(span), 3.0, 12.0))


def create_custom_color_scale(global_min, global_max, metric_mode):
    """
    Build color scales for either absolute strength metric, or the change in strength metric between GFM and GFL.
    """
    bright_green = "#00CC00"
    bright_red = "#FF0000"
    bright_yellow = "#FFEA00"
    dark_green = "#004D20"

    if metric_mode == "delta":
        # Anchor zero based on the true data range so sign coloring is accurate.
        pos_0 = normalize_position(0, global_min, global_max)
        eps = 1e-6

        if global_min >= 0 and global_max <= 0:
            return [
                [0.0, bright_yellow],
                [1.0, bright_yellow],
            ]
        if global_min >= 0:
            return [
                [0.0, bright_yellow],
                [min(1.0, pos_0 + eps), bright_yellow],
                [min(1.0, pos_0 + 2 * eps), bright_green],
                [1.0, bright_green],
            ]
        if global_max <= 0:
            return [
                [0.0, bright_red],
                [max(0.0, pos_0 - 2 * eps), bright_red],
                [max(0.0, pos_0 - eps), bright_yellow],
                [1.0, bright_yellow],
            ]

        color_scale = [
            [0.0, bright_red],
            [max(0.0, pos_0 - 2 * eps), bright_red],
            [max(0.0, pos_0 - eps), bright_yellow],
            [min(1.0, pos_0 + eps), bright_yellow],
            [min(1.0, pos_0 + 2 * eps), bright_green],
            [1.0, bright_green],
        ]
        return color_scale

    pos_3 = normalize_position(3, global_min, global_max)
    pos_5 = normalize_position(5, global_min, global_max)
    pos_999 = normalize_position(999, global_min, global_max)

    color_scale = [
        [0.0, bright_red],      # Red at minimum
        [pos_3, bright_yellow],    # Yellow at 3
        [pos_5, bright_green],    # Green at 5
        [max(0, pos_999 - 1e-6), bright_green],
        [pos_999, dark_green],  # at 999
        [1.0, dark_green]
    ]
    return color_scale


def compute_global_marker_sizeref(
    strength_df: pd.DataFrame,
    strength_cols: list[str],
    metric_mode: str,
    *,
    marker_max_px: float = 16.0,
) -> float:
    """Build one sizeref shared by every map so marker sizes are globally comparable."""
    if marker_max_px <= 0:
        raise ValueError("marker_max_px must be positive")

    values = strength_df[strength_cols].to_numpy(dtype=float)
    if metric_mode == "delta":
        magnitude = np.abs(values)
    else:
        magnitude = np.clip(values, a_min=0, a_max=None)

    transformed_sizes = np.cbrt(magnitude) * 2

    if transformed_sizes.size == 0:
        max_size_value = 1.0
    else:
        max_size_value = float(np.max(transformed_sizes))
        if max_size_value <= 0:
            max_size_value = 1.0

    # Plotly size mapping uses this reference to keep pixel sizes consistent across figures.
    return float((2.0 * max_size_value) / (marker_max_px ** 2))


def create_scatter_map(
    metric_mode,
    value_label,
    latitude,
    longitude,
    values,
    html_filename,
    range_color=None,
    bus_numbers=None,
    SCMVAs=None,
    PMaxIBRs=None,
    marker_sizeref=None,
    marker_size_max=16,
):
    """Create a mapbox scatter plot and save it as HTML.

    If `range_color` is provided it will be used as the shared colorbar
    range for consistency across multiple maps.
    """

    latitude = np.asarray(latitude)
    longitude = np.asarray(longitude)
    values = np.asarray(values)
    bus_numbers = np.asarray(bus_numbers)
    SCMVAs = np.asarray(SCMVAs) if SCMVAs is not None else None
    PMaxIBRs = np.asarray(PMaxIBRs) if PMaxIBRs is not None else None

    # Build marker size from value magnitude.
    # Delta uses absolute value so negative and positive deltas are equally visible.
    if metric_mode == "delta":
        magnitude = np.abs(values)
    else:
        magnitude = values.clip(min=0)

    marker_sizes = np.cbrt(magnitude) * 2

    # Keep zero-value points visible by giving them the smallest non-zero size.
    zero_mask = magnitude <= 0.001
    marker_sizes[zero_mask] = 0.5

    # Generate custom color scale if range is available
    if range_color:
        color_scale = create_custom_color_scale(range_color[0], range_color[1], metric_mode=metric_mode)
    else:
        # Fallback to simple red-yellow-green
        sys.exit("colorscale failed")

    # In strength mode, reserve lavender for exact 999 values only.
    color_values = values.copy()
    range_for_plot = range_color
    if metric_mode == "strength" and range_color:
        is_999 = np.isclose(color_values, 999.0)
        color_values[~is_999] = np.minimum(color_values[~is_999], 999.0 - 1e-6)
        color_values[is_999] = 999.0
        range_for_plot = [float(range_color[0]), 999.0]

    if metric_mode == "delta":
        # Plot non-negative first and negative last so red points render on top.
        order = np.argsort(values < 0)
        latitude = latitude[order]
        longitude = longitude[order]
        values = values[order]
        color_values = color_values[order]
        marker_sizes = marker_sizes[order]
        bus_numbers = bus_numbers[order]
        if SCMVAs is not None:
            SCMVAs = SCMVAs[order]
        if PMaxIBRs is not None:
            PMaxIBRs = PMaxIBRs[order]

    hover_data = {"Bus Number": bus_numbers, value_label: values}
    if SCMVAs is not None:
        hover_data["SCMVA"] = SCMVAs
    if PMaxIBRs is not None:
        hover_data["IBR PMax Sum"] = PMaxIBRs

    center_lat = float((np.max(latitude) + np.min(latitude)) / 2.0)
    center_lon = float((np.max(longitude) + np.min(longitude)) / 2.0)
    zoom_level = estimate_zoom(latitude, longitude)

    fig = px.scatter_map(
        lat=latitude,
        lon=longitude,
        color=color_values,
        size=marker_sizes,
        size_max=marker_size_max,
        color_continuous_scale=color_scale,
        map_style=MAP_CONFIG['style'],
        range_color=range_for_plot,
        zoom=zoom_level,
        center=dict(lat=center_lat, lon=center_lon),
        hover_data=hover_data,
    )

    fig.update_layout(
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        font_family="Times New Roman",
    )
    fig.update_coloraxes(
        showscale=False,
    )
    if marker_sizeref is not None:
        fig.update_traces(
            marker_sizemode="area",
            marker_sizeref=float(marker_sizeref),
            marker_sizemin=0.5,
        )

    # Build hovertemplate from only the desired fields, bypassing Plotly's auto-added color/size
    hover_lines = [f"{k}: %{{customdata[{i}]}}" for i, k in enumerate(hover_data)]
    fig.update_traces(hovertemplate="<br>".join(hover_lines) + "<extra></extra>")
    # fig.update_coloraxes(
    #     colorbar=dict(
    #         len=COLORBAR_LEN,
    #         title=dict(text="SCR", font=dict(size=COLORBAR_FONT_SIZE)),
    #         tickfont=dict(size=COLORBAR_FONT_SIZE),
    #     )
    # )

    fig.write_html(html_filename, include_plotlyjs="cdn")
    print(f"Saved: {html_filename}")


def prepare_scatter_data(location_file: Path, strength_df: pd.DataFrame, col_name: str):
    """Load, aggregate, and sort data for plotting.

    Returns:
        tuple[pd.DataFrame, int, int]:
            - map dataframe (only rows that can be plotted)
            - number of buses with metric values
            - number of buses missing GIS coordinates
    """
    locations = pd.read_excel(location_file)
    merged = locations.merge(strength_df, on="Bus Number", how="left")

    metric_rows = merged[merged[col_name].notna()].copy()
    missing_geo_mask = metric_rows["latitude"].isna() | metric_rows["longitude"].isna()
    missing_geo_count = int(missing_geo_mask.sum())
    metric_bus_count = int(len(metric_rows))

    map_ready = metric_rows[~missing_geo_mask]
    map_ready = map_ready.sort_values(by=col_name, ascending=False).reset_index(drop=True)
    return map_ready, metric_bus_count, missing_geo_count


def get_strength_columns(strength_df: pd.DataFrame):
    strength_cols = [col for col in strength_df.columns if str(col).startswith(f"{METRIC}_")]

    def sort_key(col_name: str):
        level = extract_penetration_level(col_name)
        return level if level is not None else 10**9

    return sorted(strength_cols, key=sort_key)


def extract_penetration_level(col_name: str):
    """Extract penetration percentage from column names like SCR_RE63 or SCR_63."""
    text = str(col_name)
    re_match = re.search(r"RE(\d+)", text)
    if re_match:
        return int(re_match.group(1))

    suffix_match = re.search(r"_(\d+)$", text)
    if suffix_match:
        return int(suffix_match.group(1))

    return None

def get_re_bucket(col_name: str):
    """Return penetration bucket in percent tens (e.g., 63 -> 60, 100 -> 100)."""
    level = extract_penetration_level(col_name)
    if level is None:
        return None
    return (level // 10) * 10


def build_bucketed_metric_dataframe(weight_df: pd.DataFrame):
    """Aggregate strength metric columns into RE tens-place buckets."""
    bucket_to_cols = {}
    for col in get_strength_columns(weight_df):
        bucket = get_re_bucket(col)
        if bucket is None:
            continue
        bucket_to_cols.setdefault(bucket, []).append(col)

    if not bucket_to_cols:
        raise ValueError(f"No {METRIC} penetration columns with RE values were found.")

    bucket_df = pd.DataFrame({"Bus Number": weight_df["Bus Number"]})
    for bucket in sorted(bucket_to_cols):
        bucket_col = f"{METRIC}_{bucket}"
        bucket_df[bucket_col] = weight_df[bucket_to_cols[bucket]].mean(axis=1)

    return bucket_df

def build_compare_dataframe(gfl_file: Path, gfm_file: Path, compare_file: Path, analysis: str):
    if not gfl_file.exists():
        raise FileNotFoundError(f"{METRIC} results file not found: {gfl_file}")
    if not gfm_file.exists():
        raise FileNotFoundError(f"{METRIC} results file not found: {gfm_file}")

    gfl_df = pd.read_excel(gfl_file)
    gfm_df = pd.read_excel(gfm_file)

    if analysis == "dynamic":
        gfl_bucketed_df = build_bucketed_metric_dataframe(gfl_df)
        gfl_df = gfl_bucketed_df
        gfm_bucketed_df = build_bucketed_metric_dataframe(gfm_df)
        gfm_df = gfm_bucketed_df

    gfl_strength_cols = set(get_strength_columns(gfl_df))
    gfm_strength_cols = set(get_strength_columns(gfm_df))
    common_strength_cols = sorted(
        gfl_strength_cols.intersection(gfm_strength_cols),
        key=lambda c: extract_penetration_level(c) if extract_penetration_level(c) is not None else 10**9,
    )

    if len(common_strength_cols) == 0:
        raise ValueError(f"No common {METRIC} penetration columns were found between GFL and GFM result files.")

    merged = gfm_df[["Bus Number", *common_strength_cols]].merge(
        gfl_df[["Bus Number", *common_strength_cols]],
        on="Bus Number",
        how="inner",
        suffixes=("_gfm", "_gfl"),
    )

    compare_df = pd.DataFrame({
        "Bus Number": merged["Bus Number"],
        **{col: (merged[f"{col}_gfm"] - merged[f"{col}_gfl"]).round(3) for col in common_strength_cols}
    })

    compare_df = compare_df.sort_values(by="Bus Number").reset_index(drop=True)
    compare_df.to_excel(compare_file, index=False)
    return compare_df, common_strength_cols


def main(keyword: str, analysis: str, mode: str, metric: str, case: str | None = None) -> None:
    global METRIC
    global OUTPUT_DIR
    OUTPUT_DIR = PROJECT_ROOT / f"output_{'_'.join(Path(case).stem.split('_')[:2])}"
    METRIC = f"{analysis}_{metric}"
    bus_location_file = resolve_bus_location_file(case)

    base_output_dir = OUTPUT_DIR / f"{analysis}_analysis" / mode
    keyword_output_dir = base_output_dir / keyword

    if keyword == "COMPARE":
        output_dir = keyword_output_dir / f"{metric}_htmls"
        output_dir.mkdir(parents=True, exist_ok=True)
        compare_file = keyword_output_dir / f"Strength_Metric_Results_{metric}.xlsx"
        gfl_file = base_output_dir / "GFL" / f"Strength_Metric_Results_{metric}.xlsx"
        gfm_file = base_output_dir / "GFM" / f"Strength_Metric_Results_{metric}.xlsx"
        strength_df, strength_cols = build_compare_dataframe(gfl_file, gfm_file, compare_file, analysis)
        metric_mode = "delta"
        value_label = f"Δ {METRIC} (GFM-GFL)"
    else:
        strength_file = keyword_output_dir / f"Strength_Metric_Results_{metric}.xlsx"
        output_dir = keyword_output_dir / f"{metric}_htmls"

        if not strength_file.exists():
            raise FileNotFoundError(f"System strength results file not found: {strength_file}")

        strength_df = pd.read_excel(strength_file)
        strength_cols = get_strength_columns(strength_df)
        metric_mode = "strength"
        value_label = METRIC

    if not bus_location_file.exists():
        raise FileNotFoundError(f"Bus location file not found: {bus_location_file}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine a global range across all mapped columns so colors are comparable.
    exclude_999_for_max = metric_mode == "strength"
    global_range_tuple = metric_global_range(
        strength_df,
        METRIC,
        dynamic_cap_95=False,
        exclude_999_for_max=exclude_999_for_max,
    )
    if global_range_tuple is None:
        raise ValueError(f"No metric columns found for {METRIC}.")
    global_range = [global_range_tuple[0], global_range_tuple[1]]

    # One global marker-size reference keeps bubble sizes comparable across all generated maps.
    marker_sizeref = compute_global_marker_sizeref(strength_df, strength_cols, metric_mode)

    metric_details = METRIC.split("_")
    for col in strength_cols:
        scmva_col = col.replace(f"{metric_details[1]}_", "SCMVA_")
        pmax_col = col.replace(f"{metric_details[1]}_", "PMaxIBR_")

        selected_cols = ["Bus Number", col]
        if scmva_col in strength_df.columns:
            selected_cols.append(scmva_col)
        if pmax_col in strength_df.columns:
            selected_cols.append(pmax_col)

        output_html = output_dir / f"{col}.html"
        map_data, metric_bus_count, missing_geo_count = prepare_scatter_data(bus_location_file, strength_df[selected_cols], col)
        if missing_geo_count > 0:
            print(
                f"Warning: {missing_geo_count} of {metric_bus_count} buses in {col} are missing "
                f"latitude/longitude in {bus_location_file.name} and were not plotted in {output_html.name}."
            )

        if map_data.empty:
            print(f"Warning: no plottable buses found for {col}; skipping HTML generation.")
            continue

        create_scatter_map(
            metric_mode,
            value_label,
            latitude=map_data["latitude"].to_numpy(),
            longitude=map_data["longitude"].to_numpy(),
            values=map_data[col].to_numpy(),
            html_filename=str(output_html),
            range_color=global_range,
            bus_numbers=map_data["Bus Number"].to_numpy(),
            SCMVAs=map_data[scmva_col].to_numpy() if scmva_col in map_data.columns else None,
            PMaxIBRs=map_data[pmax_col].to_numpy() if pmax_col in map_data.columns else None,
            marker_sizeref=marker_sizeref,
            marker_size_max=16,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate HTML maps for system strength metrics.")
    parser.add_argument("--keyword", required=True, choices=["GFL", "GFM", "COMPARE", "CONTROL-NEUTRAL"])
    parser.add_argument("--analysis", default="static", choices=["static", "dynamic"])
    parser.add_argument("--mode", default="evolution", choices=["snapshot", "evolution"])
    parser.add_argument("--metric", default="SCR", help="Strength metric type to evaluate (e.g., SCR)")
    parser.add_argument("--case-file", help="Path to the case (.sav) used for extraction.")
    args = parser.parse_args()
    main(
        args.keyword,
        args.analysis,
        args.mode,
        args.metric,
        args.case_file,
    )
