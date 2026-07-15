#!/usr/bin/env python3
"""Single entrypoint for the OmniRetail local data-management pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ingest import DUCKDB_PATH, INPUT_DIR, OUTPUT_DIR, connect, ingest_raw
from src.quality_checks import run_quality_checks
from src.reporting import write_outputs
from src.transform import transform_all


def main() -> int:
    print(f"Input dir : {INPUT_DIR}")
    print(f"DuckDB    : {DUCKDB_PATH}")
    print(f"Outputs   : {OUTPUT_DIR}")

    con = connect(reset=True)
    try:
        print("1/4 Ingesting raw sources...")
        ingest_raw(con)
        print("2/4 Transforming curated model...")
        transform_all(con)
        # Optional: also document SQL model definitions live in sql/curated_model.sql
        print("3/4 Running data-quality checks...")
        run_quality_checks(con)
        print("4/4 Writing reports...")
        write_outputs(con)
    finally:
        con.close()

    print("Wrote:")
    print(f"  - {OUTPUT_DIR / 'curated.duckdb'}")
    print(f"  - {OUTPUT_DIR / 'data_quality_report.md'}")
    print(f"  - {OUTPUT_DIR / 'exceptions.csv'}")
    print(f"  - {OUTPUT_DIR / 'business_answers.md'}")
    print(f"  - {OUTPUT_DIR / 'reconciliation_report.md'}")
    print(f"  - {OUTPUT_DIR / 'order_health_snapshot.md'}")
    print(f"  - {OUTPUT_DIR / 'charts' / 'readme_order_health.png'}")
    print(f"  - {OUTPUT_DIR / 'charts' / 'dq_exceptions_by_severity.png'}")
    print(f"  - {OUTPUT_DIR / 'charts' / 'q1_revenue_by_month.png'}")
    print(f"  - {OUTPUT_DIR / 'charts' / 'q2_top_customers.png'}")
    print(f"  - {OUTPUT_DIR / 'charts' / 'q4_revenue_by_state.png'}")
    print("Pipeline complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
