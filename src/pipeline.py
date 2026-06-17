"""Orchestrate the Airbnb ETL pipeline stages."""

import logging
from pathlib import Path

from ingest import ingest
from clean import clean
from profile import profile
from enrich import enrich

ROOT_DIR = Path(__file__).resolve().parents[1]


def run_pipeline() -> None:
    """Run the full pipeline end to end, in dependency order.

    Each stage reads the previous stage's output from disk (rather than
    passing data in memory), so any stage can also be re-run independently
    while debugging.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("Starting Airbnb pipeline")
    ingest()    # fetch raw city pages -> data/raw
    clean()     # strip HTML, normalize text -> data/processed
    profile()   # log data quality stats for processed files
    enrich()    # derive metadata fields -> data/processed/*.meta.json
    logging.info("Airbnb pipeline complete")


if __name__ == "__main__":
    run_pipeline()
