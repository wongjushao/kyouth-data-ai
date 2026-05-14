"""CLI orchestrator for the Week 1 medallion pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

WEEK1_ROOT = Path(__file__).resolve().parent
if str(WEEK1_ROOT) not in sys.path:
    sys.path.insert(0, str(WEEK1_ROOT))

from src.ingestor import ingest_all_mhtml  # noqa: E402
from src.loader import load_all_jsons  # noqa: E402
from src.processor import process_all_html  # noqa: E402
from src.profiler import run_data_profile  # noqa: E402

DATA_DIR = WEEK1_ROOT / "data"
SOURCE_DIR = DATA_DIR / "0_source"
BRONZE_DIR = DATA_DIR / "1_bronze"
SILVER_DIR = DATA_DIR / "2_silver"
GOLD_DIR = DATA_DIR / "3_gold"


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        print("Usage: python main.py [ingest|process|load|profile|all]")
        sys.exit(1)

    match argv[0]:
        case "ingest":
            ingest_all_mhtml(SOURCE_DIR, BRONZE_DIR)
        case "process":
            process_all_html(BRONZE_DIR, SILVER_DIR)
        case "load":
            load_all_jsons(SILVER_DIR, GOLD_DIR)
        case "profile":
            run_data_profile(GOLD_DIR / "jobs.db")
        case "all":
            ingest_all_mhtml(SOURCE_DIR, BRONZE_DIR)
            process_all_html(BRONZE_DIR, SILVER_DIR)
            load_all_jsons(SILVER_DIR, GOLD_DIR)
            run_data_profile(GOLD_DIR / "jobs.db")
        case _:
            print(f"Unknown command: {argv[0]}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
