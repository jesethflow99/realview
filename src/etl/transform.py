import pandas as pd
import logging
from typing import Callable

logger = logging.getLogger(__name__)


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = (
        df.columns.str.strip()
        .str.lower()
        .str.replace(r"[^a-z0-9_]+", "_", regex=True)
        .str.strip("_")
    )
    return df


def drop_duplicates(df: pd.DataFrame, subset: list[str] | None = None) -> pd.DataFrame:
    before = len(df)
    df = df.drop_duplicates(subset=subset)
    after = len(df)
    if before != after:
        logger.info(f"Removed {before - after} duplicate rows")
    return df


def clean_nulls(df: pd.DataFrame, threshold: float = 0.95) -> pd.DataFrame:
    before = len(df.columns)
    df = df.dropna(axis=1, thresh=int(len(df) * threshold))
    after = len(df.columns)
    if before != after:
        logger.info(f"Dropped {before - after} columns with >{(1-threshold)*100:.0f}% nulls")
    return df


def infer_types(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if df[col].dtype == "object":
            try:
                parsed = pd.to_datetime(df[col], infer_datetime_format=True)
                if parsed.notna().sum() > len(df) * 0.5:
                    df[col] = parsed
                    continue
            except (ValueError, TypeError):
                pass
            try:
                numeric = pd.to_numeric(df[col], errors="coerce")
                if numeric.notna().sum() > len(df) * 0.5:
                    df[col] = numeric
            except (ValueError, TypeError):
                pass
    return df


def transform(
    df: pd.DataFrame,
    column_mapping: dict[str, str] | None = None,
    custom_fn: Callable | None = None,
) -> pd.DataFrame:
    df = standardize_columns(df)
    df = infer_types(df)
    df = clean_nulls(df)

    if column_mapping:
        df = df.rename(columns=column_mapping)

    if custom_fn:
        df = custom_fn(df)

    logger.info(f"Transform complete — {len(df)} rows, {len(df.columns)} columns")
    return df
