"""Lightweight validation for OmniRetail quality and transforms."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ingest import connect, ingest_raw, standardize_country, standardize_state
from src.quality_checks import run_quality_checks
from src.transform import build_dim_customer, build_fact_order, transform_all


def test_standardize_country_and_state():
    assert standardize_country("US") == "USA"
    assert standardize_country("United States") == "USA"
    assert standardize_state("Illinois") == "IL"
    assert standardize_state("ny") == "NY"


def test_customer_dedupe_and_resolution_flag():
    raw = pd.DataFrame(
        [
            {
                "customer_id": "C006",
                "first_name": "Mason",
                "last_name": "Davis",
                "email": "mason.davis@example.com",
                "phone": "646-555-0170",
                "country": "US",
                "state": "New York",
                "signup_date": "2025-02-18",
                "loyalty_tier": "Bronze",
            },
            {
                "customer_id": "C006",
                "first_name": "Mason",
                "last_name": "Davis",
                "email": "mason.d@example.com",
                "phone": "646-555-0171",
                "country": "USA",
                "state": "NY",
                "signup_date": "2025-02-18",
                "loyalty_tier": "Bronze",
            },
        ]
    )
    dim, ex = build_dim_customer(raw)
    assert len(dim) == 1
    assert bool(dim.iloc[0]["duplicate_resolution_flag"]) is True
    assert dim.iloc[0]["standard_state"] == "NY"
    assert len(ex) == 1


def test_order_dedupe_fk_and_variance():
    customers = pd.DataFrame(
        {
            "customer_key": ["C001"],
            "full_name": ["Ava Patel"],
            "email": ["ava@example.com"],
            "phone": ["312-555-0101"],
            "standard_country": ["USA"],
            "standard_state": ["IL"],
            "signup_date": [None],
            "loyalty_tier": ["Gold"],
            "duplicate_resolution_flag": [False],
        }
    )
    products = pd.DataFrame(
        {
            "product_key": ["P001"],
            "product_name": ["Bottle"],
            "category": ["Home"],
            "unit_price": [18.0],
            "active_flag": ["Y"],
        }
    )
    orders = pd.DataFrame(
        [
            {
                "order_id": "O1018",
                "customer_id": "C001",
                "order_ts": "2025-04-19 18:20",
                "product_id": "P001",
                "quantity": "1",
                "order_status": "completed",
                "shipping_state": "NY",
                "order_total": "18.00",
            },
            {
                "order_id": "O1018",
                "customer_id": "C001",
                "order_ts": "2025-04-19 18:20",
                "product_id": "P001",
                "quantity": "1",
                "order_status": "completed",
                "shipping_state": "NY",
                "order_total": "18.00",
            },
            {
                "order_id": "O999",
                "customer_id": "C999",
                "order_ts": "2025-04-22 09:30",
                "product_id": "P001",
                "quantity": "1",
                "order_status": "completed",
                "shipping_state": "IL",
                "order_total": "18.00",
            },
        ]
    )
    fact, int_order, ex = build_fact_order(orders, customers, products)
    assert len(fact) == 1
    assert fact.iloc[0]["order_amount_variance"] == 0.0
    assert "O999" in set(int_order["order_key"])
    assert any(ex["record_key"] == "O1018")


def test_pipeline_row_counts_and_dq010():
    con = connect()
    try:
        ingest_raw(con)
        transform_all(con)
        run_quality_checks(con)

        assert con.execute("SELECT count(*) FROM dim_customer").fetchone()[0] == 19
        assert con.execute("SELECT count(*) FROM fact_order").fetchone()[0] == 28

        dq010 = con.execute(
            "SELECT status, fail_count FROM dq_results WHERE rule_id = 'DQ010'"
        ).fetchone()
        assert dq010[0] == "FAIL"
        assert dq010[1] >= 1

        detail = con.execute(
            """
            SELECT record_key FROM dq_exception_report
            WHERE rule_id = 'DQ010'
            """
        ).df()
        assert "PMT021" in set(detail["record_key"])

        # referential: curated fact_order keys exist in dims
        orphans = con.execute(
            """
            SELECT count(*) FROM fact_order o
            LEFT JOIN dim_customer c ON o.customer_key = c.customer_key
            WHERE c.customer_key IS NULL
            """
        ).fetchone()[0]
        assert orphans == 0
    finally:
        con.close()


def test_timestamp_parsing_failure_flagged():
    con = connect()
    try:
        ingest_raw(con)
        transform_all(con)
        run_quality_checks(con)
        row = con.execute(
            "SELECT status FROM dq_results WHERE rule_id = 'DQ011'"
        ).fetchone()
        assert row[0] == "FAIL"
        keys = con.execute(
            "SELECT record_key FROM dq_exception_report WHERE rule_id = 'DQ011'"
        ).df()
        assert "T010" in set(keys["record_key"])
    finally:
        con.close()
