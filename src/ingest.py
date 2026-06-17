"""Download and extract Airbnb city pages into raw storage."""

import logging
from pathlib import Path

import requests
import yaml

# Resolve paths relative to the project root, not the current working
# directory, so the script works no matter where it's run from.
ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config" / "cities.yaml"
RAW_DIR = ROOT_DIR / "data" / "raw"


def load_city_config(path: Path = CONFIG_PATH) -> dict:
    """Load the list of cities (and their source URLs) from YAML config."""
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def fetch_city_page(url: str) -> str:
    """Download a single city page and return its raw HTML text."""
    response = requests.get(url, timeout=30)
    response.raise_for_status()  # fail loudly on 4xx/5xx instead of silently continuing
    return response.text


def save_raw(city_name: str, content: str) -> Path:
    """Persist the untouched response body to data/raw for traceability."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{city_name}.html"
    raw_path.write_text(content, encoding="utf-8")
    logging.info("Saved raw data to %s", raw_path)
    return raw_path


def ingest() -> None:
    """Entry point for the ingest stage: fetch and save every configured city."""
    config = load_city_config()
    for city in config.get("cities", []):
        logging.info("Ingesting %s from %s", city["name"], city["url"])
        page = fetch_city_page(city["url"])
        save_raw(city["name"], page)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ingest()
