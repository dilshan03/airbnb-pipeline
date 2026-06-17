# Airbnb Pipeline

A small data engineering pipeline for Inside Airbnb data: ingest, clean, profile, and enrich city listings, orchestrated end to end.

## Structure

```
config/
  cities.yaml       # cities to process, with source URLs
data/
  raw/               # untouched ingested data
  processed/         # cleaned/enriched outputs
logs/                # pipeline run logs
src/
  ingest.py           # fetch raw data per city
  clean.py            # normalize raw data into processed text
  profile.py          # basic data quality / profiling stats
  enrich.py            # derive additional fields from processed data
  pipeline.py         # orchestrates ingest -> clean -> profile -> enrich
```

## Setup

```bash
pip install -r requirements.txt
```

## Usage

Edit `config/cities.yaml` to set the cities and sources to process, then run:

```bash
python src/pipeline.py
```

Each stage can also be run independently via `python src/<stage>.py`.
