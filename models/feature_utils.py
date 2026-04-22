"""Shared feature helpers for weekly player models."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd


def safe_col(df: pd.DataFrame, col: str, fill: float = 0.0) -> pd.Series:
    if col in df.columns:
        return df[col].fillna(fill)
    return pd.Series(fill, index=df.index, dtype=float)


def safe_ratio(
    numerator: pd.Series | np.ndarray,
    denominator: pd.Series | np.ndarray,
    fill: float = 0.0,
) -> pd.Series:
    num = np.asarray(numerator, dtype=float)
    den = np.asarray(denominator, dtype=float)
    values = np.divide(
        num,
        den,
        out=np.full_like(num, fill, dtype=float),
        where=den != 0,
    )
    return pd.Series(values)


def rolling_mean(series: pd.Series, window: int = 4) -> pd.Series:
    return series.shift(1).rolling(window, min_periods=1).mean()


def add_group_rolling_mean(
    df: pd.DataFrame,
    group_cols: str | list[str],
    source_col: str,
    feature_name: str,
    window: int = 4,
) -> pd.DataFrame:
    group_keys = [group_cols] if isinstance(group_cols, str) else list(group_cols)
    sort_cols = group_keys + ["season", "week"]
    df = df.sort_values(sort_cols).copy()
    grouped = df.groupby(group_keys, group_keys=False)
    df[feature_name] = grouped[source_col].transform(
        lambda s: rolling_mean(s, window=window)
    )
    return df


def merge_group_context(
    df: pd.DataFrame,
    group_col: str,
    stat_cols: Iterable[str],
    prefix: str,
    window: int = 4,
) -> tuple[pd.DataFrame, list[str]]:
    """Merge lagged group-level rolling stat totals back into player rows."""
    stat_list = [col for col in stat_cols if col in df.columns]
    if group_col not in df.columns or not stat_list:
        return df, []

    context = (
        df[[group_col, "season", "week", *stat_list]]
        .copy()
        .fillna(0.0)
        .groupby([group_col, "season", "week"], as_index=False)[stat_list]
        .sum()
        .sort_values([group_col, "season", "week"])
    )

    feature_cols: list[str] = []
    grouped = context.groupby(group_col, group_keys=False)
    for stat in stat_list:
        feature_name = f"{prefix}_{stat}"
        context[feature_name] = grouped[stat].transform(
            lambda s: rolling_mean(s, window=window)
        )
        feature_cols.append(feature_name)

    merged = df.merge(
        context[[group_col, "season", "week", *feature_cols]],
        on=[group_col, "season", "week"],
        how="left",
    )
    return merged, feature_cols
