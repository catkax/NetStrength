"""Shared helpers for map generation and HTML display rendering."""

from __future__ import annotations

from typing import Iterable

import pandas as pd


def normalize_position(value: float, global_min: float, global_max: float) -> float:
    """Clamp value to [0,1] within the provided range."""
    if global_max == global_min:
        return 0.5
    return max(0.0, min(1.0, (value - global_min) / (global_max - global_min)))


def format_num(value: float) -> str:
    """Format numeric labels compactly for legends."""
    return "%s" % float("%.4g" % value)


def metric_columns(df: pd.DataFrame, metric_prefix: str, dynamic_cap_95: bool = False) -> list[str]:
    """Return metric columns matching the configured prefix."""
    cols = [col for col in df.columns if f"{metric_prefix}_" in str(col)]
    if not dynamic_cap_95:
        return cols

    filtered: list[str] = []
    for col in cols:
        suffix = str(col).split("_")[-1]
        try:
            level = float(suffix)
        except ValueError:
            filtered.append(col)
            continue
        if level <= 95:
            filtered.append(col)
    return filtered


def metric_global_range(
    df: pd.DataFrame,
    metric_prefix: str,
    *,
    dynamic_cap_95: bool = False,
    exclude_999_for_max: bool = True,
) -> tuple[float, float] | None:
    """Compute a shared min/max range for map and legend consistency."""
    numeric_cols = metric_columns(df, metric_prefix, dynamic_cap_95=dynamic_cap_95)
    if not numeric_cols:
        return None

    values = df[numeric_cols]
    global_min = values.min().min()

    if exclude_999_for_max:
        global_max = values.where(values != 999).max().max()
        if pd.isna(global_max):
            global_max = values.max().max()
    else:
        global_max = values.max().max()

    return float(global_min), float(global_max)
