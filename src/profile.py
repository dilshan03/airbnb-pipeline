"""Generate data quality profile reports for processed Airbnb DataFrames."""

import json
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

ROOT_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
LOGS_DIR = ROOT_DIR / "logs"

# How many distinct sample values to pull out for each string column —
# enough to eyeball the data shape without dumping the whole column.
SAMPLE_VALUE_COUNT = 5


def _to_jsonable(value: Any) -> Any:
    """Convert numpy/pandas scalar types into plain Python types for json.dump.

    pandas/numpy aggregates (e.g. df["x"].mean()) return numpy scalar types
    that json.dump can't serialize directly, so everything gets funneled
    through here before being written out.

    Args:
        value: Any scalar value pulled from a DataFrame.

    Returns:
        An equivalent value safe to pass to json.dump.
    """
    if pd.isna(value):
        return None
    if hasattr(value, "item"):  # numpy scalar (int64, float64, bool_, etc.)
        return value.item()
    return value


def build_null_rates(df: pd.DataFrame) -> dict:
    """Compute the percentage of null values per column.

    Args:
        df: DataFrame to inspect.

    Returns:
        Mapping of column name to null rate, rounded to 2 decimal places.
    """
    null_rates = (df.isna().mean() * 100).round(2)
    return {col: _to_jsonable(rate) for col, rate in null_rates.items()}


def build_numeric_stats(df: pd.DataFrame) -> dict:
    """Compute min/max/mean for every numeric column.

    Args:
        df: DataFrame to inspect.

    Returns:
        Mapping of numeric column name to a dict with "min", "max", "mean".
    """
    numeric_df = df.select_dtypes(include="number")
    stats = {}
    for col in numeric_df.columns:
        stats[col] = {
            "min": _to_jsonable(numeric_df[col].min()),
            "max": _to_jsonable(numeric_df[col].max()),
            "mean": _to_jsonable(numeric_df[col].mean()),
        }
    return stats


def build_string_samples(df: pd.DataFrame, sample_size: int = SAMPLE_VALUE_COUNT) -> dict:
    """Pull a handful of sample values from every string/object column.

    Samples are drawn from unique non-null values so the report shows
    variety rather than the same repeated value.

    Args:
        df: DataFrame to inspect.
        sample_size: Max number of sample values to include per column.

    Returns:
        Mapping of string column name to a list of sample values.
    """
    string_df = df.select_dtypes(include="object")
    samples = {}
    for col in string_df.columns:
        unique_values = string_df[col].dropna().unique()[:sample_size]
        samples[col] = [_to_jsonable(value) for value in unique_values]
    return samples


def generate_profile_report(df: pd.DataFrame, filename: str) -> dict:
    """Build a full data quality report for a DataFrame.

    Args:
        df: DataFrame to profile.
        filename: Logical name of the dataset (used for logging/labeling only).

    Returns:
        Dict containing row/column/duplicate counts, null rates, numeric
        stats, and string sample values.
    """
    return {
        "filename": filename,
        "row_count": len(df),
        "column_count": len(df.columns),
        "duplicate_count": int(df.duplicated().sum()),
        "null_rate_pct": build_null_rates(df),
        "numeric_stats": build_numeric_stats(df),
        "string_samples": build_string_samples(df),
    }


def save_report(report: dict, filename: str) -> Path:
    """Write a profile report to logs/{filename}_profile.json.

    Args:
        report: Report dict as produced by generate_profile_report.
        filename: Logical dataset name used to build the output filename.

    Returns:
        Path the report was written to.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = LOGS_DIR / f"{filename}_profile.json"
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    logger.success("Wrote profile report to {}", report_path)
    return report_path


def print_summary(report: dict) -> None:
    """Print a human-readable summary of a profile report to the console.

    Args:
        report: Report dict as produced by generate_profile_report.
    """
    print(f"\n=== Data Quality Report: {report['filename']} ===")
    print(f"Rows: {report['row_count']}  Columns: {report['column_count']}  Duplicates: {report['duplicate_count']}")

    print("\nNull rate % per column:")
    for col, rate in report["null_rate_pct"].items():
        print(f"  {col}: {rate}%")

    print("\nNumeric column stats:")
    for col, stats in report["numeric_stats"].items():
        print(f"  {col}: min={stats['min']} max={stats['max']} mean={stats['mean']}")

    print("\nString column samples:")
    for col, values in report["string_samples"].items():
        print(f"  {col}: {values}")
    print()


def profile_dataframe(df: pd.DataFrame, filename: str) -> dict:
    """Profile a DataFrame, save the report as JSON, and print a summary.

    Args:
        df: DataFrame to profile.
        filename: Logical dataset name, used for both the report's
            "filename" field and the output JSON filename.

    Returns:
        The generated report dict.
    """
    logger.info("Profiling {} ({} rows)", filename, len(df))
    report = generate_profile_report(df, filename)
    save_report(report, filename)
    print_summary(report)
    return report


def profile() -> None:
    """Entry point for the profile stage: profile every cleaned listings file."""
    for processed_file in PROCESSED_DIR.glob("*/listings_clean.csv"):
        city_name = processed_file.parent.name
        df = pd.read_csv(processed_file)
        profile_dataframe(df, city_name)


if __name__ == "__main__":
    profile()
