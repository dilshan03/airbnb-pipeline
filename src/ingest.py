"""Download Inside Airbnb data files for each configured city."""

import time
from pathlib import Path

import requests
import yaml
from loguru import logger

# Resolve paths relative to the project root, not the current working
# directory, so the script works no matter where it's run from.
ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config" / "cities.yaml"
RAW_DIR = ROOT_DIR / "data" / "raw"

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


def load_city_config(path: Path = CONFIG_PATH) -> dict:
    """Load city definitions (name + base data URL) from YAML config.

    Args:
        path: Path to the YAML config file.

    Returns:
        Parsed config dict, expected to contain a "cities" list.
    """
    logger.debug("Loading city config from {}", path)
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def download_file(url: str, destination: Path, max_retries: int = MAX_RETRIES) -> bool:
    """Download a single file to disk, retrying on failure.

    Args:
        url: Full URL of the file to download.
        destination: Local path the file should be written to.
        max_retries: Number of attempts before giving up.

    Returns:
        True if the file was downloaded and saved successfully, False otherwise.
    """
    for attempt in range(1, max_retries + 1):
        try:
            logger.info("Downloading {} (attempt {}/{})", url, attempt, max_retries)
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            destination.write_bytes(response.content)
            logger.success("Saved {} -> {}", url, destination)
            return True
        except requests.RequestException as exc:
            logger.warning(
                "Attempt {}/{} failed for {}: {}", attempt, max_retries, url, exc
            )
            if attempt < max_retries:
                time.sleep(RETRY_DELAY_SECONDS)

    logger.error("Giving up on {} after {} attempts", url, max_retries)
    return False


def ingest_city(city_name: str, files: dict) -> None:
    """Download every configured data file for a single city.

    Args:
        city_name: Name used as the city's subfolder under data/raw.
        files: Mapping of logical file key (e.g. "listings") to its full
            download URL, as defined per-city in cities.yaml. The local
            filename is taken from the URL itself, so it naturally matches
            whatever extension the source uses (.csv.gz vs .csv).
    """
    city_dir = RAW_DIR / city_name
    city_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Ingesting city '{}' ({} files)", city_name, len(files))

    for file_key, url in files.items():
        filename = url.rsplit("/", maxsplit=1)[-1]
        destination = city_dir / filename
        logger.info("Fetching '{}' for {}", file_key, city_name)
        download_file(url, destination)


def ingest() -> None:
    """Entry point for the ingest stage: download data for every configured city."""
    config = load_city_config()
    cities = config.get("cities", [])
    logger.info("Starting ingest for {} cities", len(cities))

    for city in cities:
        ingest_city(city["name"], city["files"])

    logger.info("Ingest complete")


if __name__ == "__main__":
    ingest()
