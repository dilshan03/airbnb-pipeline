"""Enrich cleaned Inside Airbnb listings with derived fields."""

from pathlib import Path

import pandas as pd
from loguru import logger

ROOT_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT_DIR / "data" / "processed"


def add_price_per_bedroom(df: pd.DataFrame) -> pd.DataFrame:
    """Add a price_per_bedroom column.

    Studios (0 bedrooms) are treated as 1 bedroom for this calculation,
    otherwise they'd divide by zero and turn into inf/NaN.

    Args:
        df: Cleaned listings DataFrame with "price" and "bedrooms" columns.

    Returns:
        DataFrame with a new "price_per_bedroom" column.
    """
    bedrooms = pd.to_numeric(df["bedrooms"], errors="coerce").replace(0, 1)
    df["price_per_bedroom"] = (df["price"] / bedrooms).round(2)
    return df


def add_days_since_last_review(df: pd.DataFrame) -> pd.DataFrame:
    """Add a days_since_last_review column.

    Listings with no reviews get NaT in last_review (from clean.parse_dates),
    which naturally propagates to NaN here rather than a misleading 0.

    Args:
        df: Cleaned listings DataFrame with a "last_review" datetime column.

    Returns:
        DataFrame with a new "days_since_last_review" column.
    """
    last_review = pd.to_datetime(df["last_review"], errors="coerce")
    df["days_since_last_review"] = (pd.Timestamp.now() - last_review).dt.days
    return df


def enrich_listings(df: pd.DataFrame) -> pd.DataFrame:
    """Run all enrichment steps on a single city's cleaned listings DataFrame.

    Args:
        df: Cleaned listings DataFrame (output of clean.clean_listings).

    Returns:
        DataFrame with all derived columns added.
    """
    df = add_price_per_bedroom(df)
    df = add_days_since_last_review(df)
    return df


def enrich() -> None:
    """Entry point for the enrich stage: enrich every city's cleaned listings."""
    for processed_file in PROCESSED_DIR.glob("*/listings_clean.csv"):
        city_name = processed_file.parent.name
        logger.info("Enriching listings for {}", city_name)

        df = pd.read_csv(processed_file)
        df = enrich_listings(df)

        enriched_path = processed_file.parent / "listings_enriched.csv"
        df.to_csv(enriched_path, index=False)
        logger.success("Wrote enriched listings to {}", enriched_path)


if __name__ == "__main__":
    enrich()
