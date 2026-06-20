"""Build a DuckDB star schema from cleaned Inside Airbnb data and query it."""

from pathlib import Path

import duckdb
import pandas as pd
from loguru import logger

from clean import clean_price

ROOT_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT_DIR / "data" / "raw"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
DB_PATH = PROCESSED_DIR / "airbnb.duckdb"


def get_connection(db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open (and create if needed) the DuckDB database file.

    Args:
        db_path: Path to the .duckdb file on disk.

    Returns:
        An open DuckDB connection.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Connecting to DuckDB at {}", db_path)
    return duckdb.connect(str(db_path))


def _table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    """Check whether a table is already present in the database.

    Args:
        con: Open DuckDB connection.
        table_name: Name of the table to check for.

    Returns:
        True if the table exists, False otherwise.
    """
    result = con.execute(
        "select count(*) from information_schema.tables where table_name = ?",
        [table_name],
    ).fetchone()
    return result[0] > 0


def _write_table(
    con: duckdb.DuckDBPyConnection,
    table_name: str,
    df: pd.DataFrame,
    primary_key=None,
    mode: str = "replace",
) -> None:
    """Create or append a table from a DataFrame, handling the "already exists" case.

    mode="replace" drops and recreates the table — fine for a single
    standalone run. mode="append" inserts only rows not already present
    (matched on primary_key), which is what a multi-city pipeline needs so
    loading city 2 doesn't wipe out city 1's rows.

    Args:
        con: Open DuckDB connection.
        table_name: Name of the table to create/replace/append to.
        df: DataFrame holding the rows to write.
        primary_key: Column name, or list of column names, used to detect
            already-loaded rows when mode="append". Ignored in "replace" mode.
        mode: "replace" or "append".
    """
    keys = [primary_key] if isinstance(primary_key, str) else (primary_key or [])

    # DuckDB infers a column's type from its data when registering a
    # pandas DataFrame. An empty object-dtype column (e.g. a city whose
    # listings were all filtered out) carries no values to infer from, so
    # DuckDB defaults it to INTEGER instead of VARCHAR — corrupting the
    # table schema for every later append. Pinning object columns to
    # pandas' "string" dtype makes them map to VARCHAR even when empty.
    object_columns = df.select_dtypes(include="object").columns
    if len(object_columns):
        df = df.astype({col: "string" for col in object_columns})

    try:
        # DuckDB can query a pandas DataFrame directly if it's registered
        # as a temporary view first.
        con.register("tmp_df", df)

        table_already_exists = _table_exists(con, table_name)
        if mode == "replace" or not table_already_exists:
            if table_already_exists:
                logger.warning("Table {} already exists, replacing it", table_name)
            con.execute(f"create or replace table {table_name} as select * from tmp_df")
        elif keys:
            # Anti-join on the primary key(s) so re-running a city (or
            # rerunning the whole pipeline) doesn't duplicate rows already
            # loaded by a previous city.
            join_clause = " and ".join(f"existing.{k} = t.{k}" for k in keys)
            con.execute(
                f"""
                insert into {table_name}
                select t.* from tmp_df t
                where not exists (
                    select 1 from {table_name} existing where {join_clause}
                )
                """
            )
        else:
            con.execute(f"insert into {table_name} select * from tmp_df")

        logger.success("Wrote table {} ({} incoming rows, mode={})", table_name, len(df), mode)
    except duckdb.Error as exc:
        logger.error("Failed to write table {}: {}", table_name, exc)
        raise
    finally:
        con.unregister("tmp_df")


def _extract_bathrooms(df: pd.DataFrame) -> pd.Series:
    """Get a numeric bathrooms count, handling Inside Airbnb's schema drift.

    Newer Inside Airbnb snapshots dropped the numeric "bathrooms" column in
    favor of a free-text "bathrooms_text" (e.g. "1.5 baths"), so we fall
    back to parsing the number out of that text when needed.

    Args:
        df: Listings DataFrame that has either a "bathrooms" or
            "bathrooms_text" column.

    Returns:
        A numeric Series of bathroom counts.
    """
    if "bathrooms" in df.columns:
        return pd.to_numeric(df["bathrooms"], errors="coerce")
    if "bathrooms_text" in df.columns:
        return df["bathrooms_text"].astype(str).str.extract(r"([\d.]+)")[0].astype(float)
    return pd.Series([None] * len(df), index=df.index)


def _parse_superhost(series: pd.Series) -> pd.Series:
    """Convert Inside Airbnb's "t"/"f" superhost flag into a real boolean."""
    return series.astype(str).str.lower().map({"t": True, "f": False})


def _parse_percent(series: pd.Series) -> pd.Series:
    """Convert a percentage string like "100%" into a float (e.g. 100.0)."""
    return pd.to_numeric(series.astype(str).str.replace("%", "", regex=False), errors="coerce")


def create_dim_listing(con: duckdb.DuckDBPyConnection, listings: pd.DataFrame, mode: str = "replace") -> None:
    """Create the dim_listing table from a cleaned listings DataFrame.

    Args:
        con: Open DuckDB connection.
        listings: Cleaned listings DataFrame (output of clean.clean_listings).
        mode: "replace" to rebuild the table, "append" to add rows for
            another city without disturbing what's already loaded.
    """
    dim = pd.DataFrame(
        {
            "id": listings["id"],
            "name": listings["name"],
            "room_type": listings["room_type"],
            "property_type": listings.get("property_type"),
            "bedrooms": pd.to_numeric(listings.get("bedrooms"), errors="coerce"),
            "bathrooms": _extract_bathrooms(listings),
            "neighbourhood": listings.get("neighbourhood_cleansed", listings.get("neighbourhood")),
        }
    )
    _write_table(con, "dim_listing", dim, primary_key="id", mode=mode)


def create_dim_host(con: duckdb.DuckDBPyConnection, listings: pd.DataFrame, mode: str = "replace") -> None:
    """Create the dim_host table from a cleaned listings DataFrame.

    Listings, not hosts, are the row grain of the source data, so a host
    with multiple listings appears multiple times here. They're
    deduplicated by host_id since the dimension should describe one row
    per host, not one row per listing.

    Args:
        con: Open DuckDB connection.
        listings: Cleaned listings DataFrame (output of clean.clean_listings).
        mode: "replace" to rebuild the table, "append" to add rows for
            another city without disturbing what's already loaded.
    """
    dim = pd.DataFrame(
        {
            "host_id": listings["host_id"],
            "host_name": listings["host_name"],
            "host_since": pd.to_datetime(listings["host_since"], errors="coerce"),
            "is_superhost": _parse_superhost(listings["host_is_superhost"]),
            "host_response_rate": _parse_percent(listings["host_response_rate"]),
        }
    ).drop_duplicates(subset="host_id")
    _write_table(con, "dim_host", dim, primary_key="host_id", mode=mode)


def create_dim_neighbourhood(
    con: duckdb.DuckDBPyConnection, neighbourhoods: pd.DataFrame, mode: str = "replace"
) -> None:
    """Create the dim_neighbourhood table.

    Args:
        con: Open DuckDB connection.
        neighbourhoods: DataFrame with "neighbourhood" and "city" columns,
            typically built by concatenating each city's neighbourhoods.csv
            with a city column attached.
        mode: "replace" to rebuild the table, "append" to add rows for
            another city without disturbing what's already loaded.
    """
    dim = neighbourhoods[["neighbourhood", "city"]].drop_duplicates()
    _write_table(con, "dim_neighbourhood", dim, primary_key=["neighbourhood", "city"], mode=mode)


def create_fact_availability(con: duckdb.DuckDBPyConnection, calendar: pd.DataFrame, mode: str = "replace") -> None:
    """Create the fact_availability table from raw calendar data.

    Args:
        con: Open DuckDB connection.
        calendar: Raw calendar DataFrame (Inside Airbnb's calendar.csv.gz),
            with "listing_id", "date", "available", and "price" columns.
        mode: "replace" to rebuild the table, "append" to add rows for
            another city without disturbing what's already loaded.
    """
    fact = pd.DataFrame(
        {
            "listing_id": calendar["listing_id"],
            "date": pd.to_datetime(calendar["date"], errors="coerce"),
            # calendar's "available" column is "t"/"f", same encoding as
            # the superhost flag, so the same boolean mapping logic applies.
            "available": _parse_superhost(calendar["available"]),
        }
    )
    # Reuse the same $-and-comma price parsing used for listings, since
    # calendar.csv.gz formats price as a currency string too.
    fact["price"] = clean_price(calendar[["price"]].copy())["price"]
    _write_table(con, "fact_availability", fact, primary_key=["listing_id", "date"], mode=mode)


def avg_price_by_neighbourhood(con: duckdb.DuckDBPyConnection, limit: int = 10) -> pd.DataFrame:
    """Rank neighbourhoods by average listing price.

    Args:
        con: Open DuckDB connection.
        limit: Max number of neighbourhoods to return.

    Returns:
        DataFrame of neighbourhood, listing_count, avg_price.
    """
    return con.execute(
        """
        select
            l.neighbourhood,
            count(*) as listing_count,
            round(avg(l.bedrooms), 2) as avg_bedrooms,
            round(avg(f.price), 2) as avg_price
        from dim_listing l
        join fact_availability f on f.listing_id = l.id
        group by l.neighbourhood
        order by avg_price desc
        limit ?
        """,
        [limit],
    ).df()


def superhost_price_comparison(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Compare average nightly price between superhosts and non-superhosts.

    Args:
        con: Open DuckDB connection.

    Returns:
        DataFrame of is_superhost, listing_count, avg_price.
    """
    return con.execute(
        """
        select
            h.is_superhost,
            count(distinct l.id) as listing_count,
            round(avg(f.price), 2) as avg_price
        from dim_listing l
        join dim_host h on h.host_id = l.id
        join fact_availability f on f.listing_id = l.id
        group by h.is_superhost
        """
    ).df()


def occupancy_rate_by_room_type(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Compute the booked-night rate (1 - available rate) per room type.

    Args:
        con: Open DuckDB connection.

    Returns:
        DataFrame of room_type, total_nights, occupancy_rate_pct.
    """
    return con.execute(
        """
        select
            l.room_type,
            count(*) as total_nights,
            round(100.0 * sum(case when not f.available then 1 else 0 end) / count(*), 2)
                as occupancy_rate_pct
        from dim_listing l
        join fact_availability f on f.listing_id = l.id
        group by l.room_type
        order by occupancy_rate_pct desc
        """
    ).df()


def build_star_schema(
    con: duckdb.DuckDBPyConnection,
    listings: pd.DataFrame,
    neighbourhoods: pd.DataFrame,
    calendar: pd.DataFrame,
    mode: str = "replace",
) -> None:
    """Build all 4 star-schema tables in one call.

    Args:
        con: Open DuckDB connection.
        listings: Cleaned listings DataFrame.
        neighbourhoods: Neighbourhoods DataFrame with a "city" column.
        calendar: Raw calendar DataFrame.
        mode: "replace" for a single standalone load, "append" when
            loading one city at a time across a multi-city pipeline run.
    """
    create_dim_listing(con, listings, mode=mode)
    create_dim_host(con, listings, mode=mode)
    create_dim_neighbourhood(con, neighbourhoods, mode=mode)
    create_fact_availability(con, calendar, mode=mode)


if __name__ == "__main__":
    # Minimal manual smoke test: build the schema from the first city found
    # in data/processed, then run the 3 example queries.
    listings_files = list(PROCESSED_DIR.glob("*/listings_clean.csv"))
    if not listings_files:
        logger.error("No cleaned listings found under {} — run clean.py first", PROCESSED_DIR)
    else:
        city_name = listings_files[0].parent.name
        listings_df = pd.read_csv(listings_files[0])
        neighbourhoods_df = pd.read_csv(RAW_DIR / city_name / "neighbourhoods.csv")
        neighbourhoods_df["city"] = city_name
        calendar_df = pd.read_csv(RAW_DIR / city_name / "calendar.csv.gz", compression="infer")

        connection = get_connection()
        build_star_schema(connection, listings_df, neighbourhoods_df, calendar_df)

        logger.info("Top neighbourhoods by avg price:\n{}", avg_price_by_neighbourhood(connection))
        logger.info("Superhost price comparison:\n{}", superhost_price_comparison(connection))
        logger.info("Occupancy rate by room type:\n{}", occupancy_rate_by_room_type(connection))

        connection.close()
