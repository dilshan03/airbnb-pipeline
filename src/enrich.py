"""Join and enrich processed Airbnb datasets with derived fields."""

import logging
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
# Enriched metadata is written alongside the processed text files rather
# than to a separate directory, keeping each city's outputs together.
ENRICHED_DIR = ROOT_DIR / "data" / "processed"


def enrich() -> None:
    """Entry point for the enrich stage: derive metadata for each processed file.

    Computes simple derived fields (word/character counts) per file and
    writes them out as a sidecar .meta.json file next to the source text.
    """
    ENRICHED_DIR.mkdir(parents=True, exist_ok=True)
    for processed_file in PROCESSED_DIR.glob("*.txt"):
        logging.info("Enriching %s", processed_file.name)
        text = processed_file.read_text(encoding="utf-8")
        derived = {
            "source_file": processed_file.name,
            "word_count": len(text.split()),
            "character_count": len(text),
        }
        enriched_path = ENRICHED_DIR / f"{processed_file.stem}.meta.json"
        enriched_path.write_text(str(derived), encoding="utf-8")
        logging.info("Wrote enrichment metadata to %s", enriched_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    enrich()
