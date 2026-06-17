"""Orchestrate the full Airbnb pipeline: ingest, profile, clean, enrich, load per city."""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from loguru import logger

from ingest import ingest_city, load_city_config
from clean import load_listings, clean_listings
from profile import profile_dataframe
from enrich import enrich_listings
from model import get_connection, build_star_schema

ROOT_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT_DIR / "data" / "raw"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
LOGS_DIR = ROOT_DIR / "logs"


def run_city(con, city: dict, is_first_city: bool) -> dict:
    """Run ingest -> profile -> clean -> enrich -> load for a single city.

    Any exception here is caught and recorded rather than re-raised, so a
    failure in one city (a bad download, a malformed file, etc.) doesn't
    stop the rest of the cities in the run.

    Args:
        con: Open DuckDB connection shared across all cities in this run.
        city: City config dict with "name" and "base_url" (from cities.yaml).
        is_first_city: Whether this is the first city processed in this run.
            The first city replaces any stale DuckDB tables from a previous
            run; every city after that appends, so the warehouse ends up
            holding all cities instead of only the last one loaded.

    Returns:
        Status dict: city name, start/end time, duration, status, and
        error message if it failed.
    """
    city_name = city["name"]
    start = datetime.now()
    logger.info("=== Starting pipeline for {} at {} ===", city_name, start.isoformat())

    status = {"city": city_name, "start_time": start.isoformat()}

    try:
        ingest_city(city_name, city["base_url"])

        raw_listings_path = RAW_DIR / city_name / "listings.csv.gz"
        raw_df = load_listings(raw_listings_path)
        # Profile the raw data before cleaning, to catch source data quality
        # issues (nulls, bad formatting) separately from cleaning bugs.
        profile_dataframe(raw_df, f"{city_name}_raw")

        cleaned_df = clean_listings(raw_df)
        enriched_df = enrich_listings(cleaned_df)

        city_processed_dir = PROCESSED_DIR / city_name
        city_processed_dir.mkdir(parents=True, exist_ok=True)
        enriched_df.to_csv(city_processed_dir / "listings_enriched.csv", index=False)

        neighbourhoods_df = pd.read_csv(RAW_DIR / city_name / "neighbourhoods.csv")
        neighbourhoods_df["city"] = city_name
        calendar_df = pd.read_csv(RAW_DIR / city_name / "calendar.csv.gz", compression="infer")

        mode = "replace" if is_first_city else "append"
        build_star_schema(con, enriched_df, neighbourhoods_df, calendar_df, mode=mode)

        status["status"] = "success"
    except Exception as exc:  # noqa: BLE001 - intentionally broad: one bad city must not kill the run
        logger.exception("Pipeline failed for {}", city_name)
        status["status"] = "failed"
        status["error"] = str(exc)

    end = datetime.now()
    status["end_time"] = end.isoformat()
    status["duration_seconds"] = round((end - start).total_seconds(), 2)
    logger.info(
        "=== Finished pipeline for {} in {:.2f}s, status={} ===",
        city_name,
        status["duration_seconds"],
        status["status"],
    )
    return status


def save_run_metadata(run_metadata: dict) -> Path:
    """Write the pipeline run's metadata (per-city statuses + totals) to logs/.

    Args:
        run_metadata: Metadata dict produced by run_pipeline.

    Returns:
        Path the metadata JSON was written to.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.fromisoformat(run_metadata["run_start"]).strftime("%Y%m%dT%H%M%S")
    metadata_path = LOGS_DIR / f"pipeline_run_{timestamp}.json"
    with metadata_path.open("w", encoding="utf-8") as handle:
        json.dump(run_metadata, handle, indent=2)
    logger.success("Wrote pipeline run metadata to {}", metadata_path)
    return metadata_path


def run_pipeline() -> dict:
    """Run the full pipeline for every city listed in config/cities.yaml.

    Returns:
        Run metadata dict containing overall timing and a per-city status list.
    """
    run_start = datetime.now()
    logger.info("Starting Airbnb pipeline run at {}", run_start.isoformat())

    config = load_city_config()
    cities = config.get("cities", [])

    con = get_connection()
    city_statuses = []
    try:
        for index, city in enumerate(cities):
            status = run_city(con, city, is_first_city=(index == 0))
            city_statuses.append(status)
    finally:
        con.close()

    run_end = datetime.now()
    run_metadata = {
        "run_start": run_start.isoformat(),
        "run_end": run_end.isoformat(),
        "duration_seconds": round((run_end - run_start).total_seconds(), 2),
        "success_count": sum(1 for s in city_statuses if s["status"] == "success"),
        "failure_count": sum(1 for s in city_statuses if s["status"] == "failed"),
        "cities": city_statuses,
    }
    save_run_metadata(run_metadata)

    logger.info(
        "Airbnb pipeline complete: {} succeeded, {} failed",
        run_metadata["success_count"],
        run_metadata["failure_count"],
    )
    return run_metadata


if __name__ == "__main__":
    run_pipeline()
