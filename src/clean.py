"""Clean raw Inside Airbnb listings.csv.gz files into validated DataFrames."""

from pathlib import Path

import pandas as pd
from loguru import logger

ROOT_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT_DIR / "data" / "raw"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"

# Inside Airbnb's raw room_type values aren't perfectly consistent across
# snapshots/cities (casing, "Entire home/apt" vs "Entire home", etc.), so we
# map everything down to exactly these 4 categories. Anything that doesn't
# match becomes NaN rather than being guessed at.
ROOM_TYPE_MAP = {
    "entire home/apt": "Entire home",
    "entire home": "Entire home",
    "entire apartment": "Entire home",
    "private room": "Private room",
    "shared room": "Shared room",
    "hotel room": "Hotel room",
}


def load_listings(path: Path) -> pd.DataFrame:
    """Load a city's raw listings.csv.gz into a DataFrame.

    Args:
        path: Path to the gzipped listings CSV.

    Returns:
        Raw, unmodified listings DataFrame.
    """
    logger.info("Loading listings from {}", path)
    # pandas infers the gzip compression from the .gz extension automatically.
    return pd.read_csv(path, compression="infer", low_memory=False)


def clean_price(df: pd.DataFrame) -> pd.DataFrame:
    """Convert the price column from a currency string (e.g. "$1,234.00") to float.

    Args:
        df: Listings DataFrame with a raw "price" column.

    Returns:
        DataFrame with "price" as a float column.
    """
    # price arrives as a string like "$1,234.00" — strip the symbol and
    # thousands separators before casting, otherwise pd.to_numeric fails.
    df["price"] = (
        df["price"]
        .astype(str)
        .str.replace("$", "", regex=False)
        .str.replace(",", "", regex=False)
    )
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    return df


def drop_invalid_price_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with a null, zero, or negative price, logging how many were removed.

    A listing with no usable price can't be analyzed for pricing trends and
    a price of 0 or below is not a real-world value, so these rows are
    removed entirely rather than just flagged.

    Args:
        df: Listings DataFrame with a numeric "price" column.

    Returns:
        DataFrame containing only rows with a strictly positive price.
    """
    before = len(df)
    valid_price = df["price"].notna() & (df["price"] > 0)
    dropped = before - int(valid_price.sum())
    logger.info("Dropping {} of {} rows with null/zero/negative price", dropped, before)
    return df[valid_price].copy()


def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Parse last_review and host_since columns into datetime values.

    Invalid or missing dates become NaT (errors="coerce") instead of
    raising, since a handful of malformed dates shouldn't crash the
    whole pipeline run.

    Args:
        df: Listings DataFrame with raw date string columns.

    Returns:
        DataFrame with "last_review" and "host_since" as datetime64 columns.
    """
    df["last_review"] = pd.to_datetime(df["last_review"], errors="coerce")
    df["host_since"] = pd.to_datetime(df["host_since"], errors="coerce")
    return df


def normalize_room_type(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize room_type into exactly 4 categories using ROOM_TYPE_MAP.

    Matching is done on a lowercased/stripped copy of the value so that
    casing or stray whitespace in the source data doesn't cause a value
    to be missed. Unrecognized values are set to NaN rather than dropped,
    since that decision belongs to is_valid / downstream filtering, not
    this normalization step.

    Args:
        df: Listings DataFrame with a raw "room_type" column.

    Returns:
        DataFrame with "room_type" replaced by its normalized category.
    """
    normalized_key = df["room_type"].astype(str).str.strip().str.lower()
    df["room_type"] = normalized_key.map(ROOM_TYPE_MAP)

    unmatched = df["room_type"].isna().sum()
    if unmatched:
        logger.warning("{} rows have an unrecognized room_type", unmatched)

    return df


def fill_reviews_per_month(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing reviews_per_month with 0.

    A null here means the listing has no reviews yet (not "unknown"), so 0
    is the correct value rather than a guess or imputed average.

    Args:
        df: Listings DataFrame with a "reviews_per_month" column.

    Returns:
        DataFrame with nulls in "reviews_per_month" replaced by 0.
    """
    missing = df["reviews_per_month"].isna().sum()
    logger.info("Filling {} missing reviews_per_month values with 0", missing)
    df["reviews_per_month"] = df["reviews_per_month"].fillna(0)
    return df


def add_validity_flag(df: pd.DataFrame) -> pd.DataFrame:
    """Add an is_valid column marking rows that pass all cleaning checks.

    By the time this runs, rows with bad prices have already been dropped,
    so the only remaining failure mode tracked here is an unrecognized
    room_type. is_valid is a flag rather than another drop so downstream
    consumers can decide for themselves whether to filter on it.

    Args:
        df: Listings DataFrame that has already had price/dates/room_type cleaned.

    Returns:
        DataFrame with a new boolean "is_valid" column.
    """
    df["is_valid"] = df["price"].notna() & (df["price"] > 0) & df["room_type"].notna()
    return df


def clean_listings(df: pd.DataFrame) -> pd.DataFrame:
    """Run the full cleaning pipeline on a single city's listings DataFrame.

    Args:
        df: Raw listings DataFrame as loaded from listings.csv.gz.

    Returns:
        Cleaned DataFrame with validated price/dates/room_type and an
        is_valid flag.
    """
    df = clean_price(df)
    df = drop_invalid_price_rows(df)
    df = parse_dates(df)
    df = normalize_room_type(df)
    df = fill_reviews_per_month(df)
    df = add_validity_flag(df)
    return df


def clean() -> None:
    """Entry point for the clean stage: clean every city's listings.csv.gz."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    for raw_file in RAW_DIR.glob("*/listings.csv.gz"):
        city_name = raw_file.parent.name
        logger.info("Cleaning listings for {}", city_name)

        df = load_listings(raw_file)
        df = clean_listings(df)

        city_processed_dir = PROCESSED_DIR / city_name
        city_processed_dir.mkdir(parents=True, exist_ok=True)
        processed_file = city_processed_dir / "listings_clean.csv"
        df.to_csv(processed_file, index=False)
        logger.success("Wrote cleaned listings to {}", processed_file)


if __name__ == "__main__":
    clean()
