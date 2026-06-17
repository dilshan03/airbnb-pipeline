"""Standardize raw Airbnb HTML into cleaned text files."""

import logging
from pathlib import Path
import re

ROOT_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT_DIR / "data" / "raw"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"


def normalize_text(text: str) -> str:
    """Collapse repeated whitespace/newlines into single spaces and trim ends."""
    return re.sub(r"\s+", " ", text).strip()


def strip_html(raw_text: str) -> str:
    """Remove HTML tags, leaving plain text content behind."""
    cleaned = re.sub(r"<[^>]+>", " ", raw_text)
    return normalize_text(cleaned)


def clean() -> None:
    """Entry point for the clean stage: turn every raw .html file into a .txt file."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    for raw_file in RAW_DIR.glob("*.html"):
        logging.info("Cleaning %s", raw_file.name)
        raw_text = raw_file.read_text(encoding="utf-8")
        cleaned_text = strip_html(raw_text)
        # Same filename, .txt extension, so downstream stages can pair
        # processed files back to their raw source by stem.
        processed_file = PROCESSED_DIR / f"{raw_file.stem}.txt"
        processed_file.write_text(cleaned_text, encoding="utf-8")
        logging.info("Wrote cleaned data to %s", processed_file)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    clean()
