"""Generate simple data quality metrics for processed Airbnb text."""

import logging
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT_DIR / "data" / "processed"


def profile() -> None:
    """Entry point for the profile stage: log basic stats for each processed file.

    This acts as a lightweight data quality check between cleaning and
    enrichment — catching empty files or unexpected content before they
    propagate further down the pipeline.
    """
    for processed_file in PROCESSED_DIR.glob("*.txt"):
        text = processed_file.read_text(encoding="utf-8")
        tokens = text.split()
        counts = Counter(tokens)
        logging.info(
            "Profile %s: words=%d, unique_words=%d, top_terms=%s",
            processed_file.name,
            len(tokens),
            len(counts),
            counts.most_common(5),
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    profile()
