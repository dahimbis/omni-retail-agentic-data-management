"""Lightweight validation for OmniRetail quality and transforms."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.reporting as reporting
from src.ingest import (
    _validate_source,
    connect,
    ingest_raw,
    standardize_country,
    standardize_state,
)
from src.quality_checks import run_quality_checks
from src.reporting import _run_sql_file, write_outputs
from src.transform import build_dim_customer, build_fact_order, transform_all


@pytest.fixture(scope="module")
def pipeline_con(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("database") / "curated.duckdb"
    con = connect(db_path)
    ingest_raw(con)
    transform_all(con)
    run_quality_checks(con)
    yield con
    con.close()


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
    assert bool(fact.iloc[0]["is_revenue_eligible"]) is True
    assert "O999" in set(int_order["order_key"])
    assert any(ex["record_key"] == "O1018")


def test_input_schema_validation_has_clear_error():
    with pytest.raises(ValueError, match=r"orders.csv.*order_id"):
        _validate_source(Path("orders.csv"), pd.DataFrame({"customer_id": ["C001"]}))


def test_pipeline_reconciles_source_to_curated_counts(pipeline_con):
    con = pipeline_con
    comparisons = [
        (
            "SELECT count(DISTINCT customer_id) FROM stg_customers",
            "SELECT count(*) FROM dim_customer",
        ),
        (
            "SELECT count(DISTINCT order_id) FROM stg_orders",
            "SELECT count(*) FROM int_order",
        ),
        (
            "SELECT count(*) FROM int_order WHERE valid_customer AND valid_product",
            "SELECT count(*) FROM fact_order",
        ),
        (
            "SELECT count(*) FROM int_payment WHERE in_curated_order",
            "SELECT count(*) FROM fact_payment",
        ),
    ]
    for expected_sql, actual_sql in comparisons:
        expected = con.execute(expected_sql).fetchone()[0]
        actual = con.execute(actual_sql).fetchone()[0]
        assert actual == expected

    order_orphans = con.execute(
        """
        SELECT count(*) FROM fact_order o
        LEFT JOIN dim_customer c ON o.customer_key = c.customer_key
        LEFT JOIN dim_product p ON o.product_key = p.product_key
        WHERE c.customer_key IS NULL OR p.product_key IS NULL
        """
    ).fetchone()[0]
    payment_orphans = con.execute(
        """
        SELECT count(*) FROM fact_payment p
        LEFT JOIN fact_order o ON p.order_key = o.order_key
        WHERE o.order_key IS NULL
        """
    ).fetchone()[0]
    assert order_orphans == 0
    assert payment_orphans == 0
    assert con.execute("SELECT count(*) FROM ref_sttm_target_mapping").fetchone()[0] > 0
    assert con.execute("SELECT count(*) FROM ref_data_quality_rules").fetchone()[0] > 0


def test_all_expected_quality_rules_and_defects(pipeline_con):
    con = pipeline_con
    rules = set(con.execute("SELECT rule_id FROM dq_results").df()["rule_id"])
    assert rules == {f"DQ{i:03d}" for i in range(1, 17)}
    reference_rules = set(
        con.execute("SELECT rule_id FROM ref_data_quality_rules").df()["rule_id"]
    )
    assert reference_rules <= rules

    exceptions = con.execute(
        "SELECT rule_id, record_key FROM dq_exception_report"
    ).df()
    actual = set(exceptions.itertuples(index=False, name=None))
    expected = {
        ("TRANSFORM_DEDUP_CUSTOMER", "C006"),
        ("TRANSFORM_DEDUP_ORDER", "O1018"),
        ("DQ002", "C004"),
        ("DQ005", "O1019"),
        ("DQ006", "O1020"),
        ("DQ007", "O1030"),
        ("DQ008", "O1021"),
        ("DQ009", "PMT029"),
        ("DQ010", "PMT021"),
        ("DQ011", "T010"),
        ("DQ012", "T005"),
        ("DQ013", "O1015"),
        ("DQ014", "O1024"),
        ("DQ015", "PMT019"),
        ("DQ015", "PMT020"),
    }
    assert expected <= actual

    duplicated_semantics = con.execute(
        """
        SELECT count(*)
        FROM dq_exception_report
        WHERE rule_id IN (
          'TRANSFORM_ORDER_FK',
          'TRANSFORM_PAYMENT_ORPHAN',
          'TRANSFORM_TICKET_TS',
          'TRANSFORM_TICKET_FK'
        )
        """
    ).fetchone()[0]
    assert duplicated_semantics == 0


def test_quarantined_payments_and_bad_timestamp_remain_auditable(pipeline_con):
    quarantined = pipeline_con.execute(
        """
        SELECT payment_key, valid_order, in_curated_order
        FROM int_payment
        WHERE payment_key IN ('PMT019', 'PMT020')
        ORDER BY payment_key
        """
    ).fetchall()
    assert quarantined == [("PMT019", True, False), ("PMT020", True, False)]

    ticket = pipeline_con.execute(
        """
        SELECT created_date, parse_ok
        FROM int_customer_issue
        WHERE ticket_id = 'T010'
        """
    ).fetchone()
    assert ticket == (None, False)


def test_dq002_flags_missing_and_invalid_email(tmp_path):
    con = connect(tmp_path / "email_validation.duckdb")
    try:
        ingest_raw(con)
        transform_all(con)
        con.execute(
            "UPDATE dim_customer SET email = 'invalid-email' WHERE customer_key = 'C003'"
        )
        run_quality_checks(con)
        keys = set(
            con.execute(
                """
                SELECT record_key
                FROM dq_exception_report
                WHERE rule_id = 'DQ002'
                """
            ).df()["record_key"]
        )
        assert keys == {"C003", "C004"}
    finally:
        con.close()


def test_business_question_regressions(pipeline_con):
    frames = _run_sql_file(pipeline_con, ROOT / "sql" / "business_questions.sql")
    assert len(frames) == 6

    q1 = dict(zip(frames[0]["month"], frames[0]["completed_revenue"]))
    assert q1 == {"2025-03": 440.70, "2025-04": 356.97, "2025-05": 446.20}

    assert frames[1]["customer_key"].tolist() == [
        "C010",
        "C012",
        "C016",
        "C007",
        "C002",
        "C009",
        "C018",
        "C004",
        "C003",
        "C013",
    ]
    assert frames[2]["order_key"].tolist() == [
        "O1019",
        "O1020",
        "O1021",
        "O1024",
        "O1030",
    ]

    q4 = dict(zip(frames[3]["state"], frames[3]["completed_revenue"]))
    assert q4 == {
        "MA": 278.23,
        "IL": 277.97,
        "WA": 192.98,
        "CA": 169.72,
        "TX": 141.98,
        "NY": 117.0,
        "FL": 65.99,
    }
    assert frames[4].to_dict("records") == [
        {
            "customer_group": "Negative support ticket",
            "customers": 6,
            "customers_with_exceptions": 3.0,
            "exception_rate": 0.5,
        },
        {
            "customer_group": "No negative support ticket",
            "customers": 13,
            "customers_with_exceptions": 1.0,
            "exception_rate": 0.077,
        },
    ]
    q5_detail = frames[5].set_index("customer_key")
    assert set(q5_detail.index[q5_detail["has_order_payment_exception"]]) == {
        "C001",
        "C002",
        "C018",
    }
    assert set(q5_detail.index[~q5_detail["has_order_payment_exception"]]) == {
        "C006",
        "C014",
        "C017",
    }


def test_curated_schema_and_generated_reports(pipeline_con, tmp_path, monkeypatch):
    expected_order_columns = {
        "order_key",
        "customer_key",
        "product_key",
        "order_date",
        "quantity",
        "order_status",
        "shipping_state",
        "gross_order_amount",
        "calculated_order_amount",
        "order_amount_variance",
        "is_revenue_eligible",
    }
    columns = set(
        pipeline_con.execute("PRAGMA table_info('fact_order')").df()["name"]
    )
    assert columns == expected_order_columns
    order_types = dict(
        pipeline_con.execute("PRAGMA table_info('fact_order')").df()[
            ["name", "type"]
        ].itertuples(index=False, name=None)
    )
    for column in (
        "gross_order_amount",
        "calculated_order_amount",
        "order_amount_variance",
    ):
        assert order_types[column] == "DECIMAL(18,2)"

    product_types = dict(
        pipeline_con.execute("PRAGMA table_info('dim_product')").df()[
            ["name", "type"]
        ].itertuples(index=False, name=None)
    )
    payment_types = dict(
        pipeline_con.execute("PRAGMA table_info('fact_payment')").df()[
            ["name", "type"]
        ].itertuples(index=False, name=None)
    )
    assert product_types["unit_price"] == "DECIMAL(18,2)"
    assert payment_types["payment_amount"] == "DECIMAL(18,2)"

    generated_dir = tmp_path / "outputs"
    monkeypatch.setattr(reporting, "OUTPUT_DIR", generated_dir)
    monkeypatch.setattr(reporting, "CHARTS_DIR", generated_dir / "charts")
    readme_before = (ROOT / "README.md").read_bytes()
    write_outputs(pipeline_con)
    assert (ROOT / "README.md").read_bytes() == readme_before

    expected_files = {
        "business_answers.md",
        "data_quality_report.md",
        "exceptions.csv",
        "reconciliation_report.md",
        "order_health_snapshot.md",
        "charts/dq_exceptions_by_severity.png",
        "charts/q1_revenue_by_month.png",
        "charts/q2_top_customers.png",
        "charts/q4_revenue_by_state.png",
        "charts/readme_order_health.png",
    }
    actual_files = {
        path.relative_to(generated_dir).as_posix()
        for path in generated_dir.rglob("*")
        if path.is_file()
    }
    assert expected_files == actual_files

    answers = (generated_dir / "business_answers.md").read_text(encoding="utf-8")
    assert "Q1. What is completed revenue by month?" in answers
    assert "Q4. Which states have the highest completed revenue?" in answers
    assert "| Negative support ticket | 6 | 3 | 0.500 |" in answers
    assert "| No negative support ticket | 13 | 1 | 0.077 |" in answers
    assert (
        "Customers with negative support tickets had a 50.0% order or payment "
        "exception rate, compared with 7.7% among customers without negative "
        "tickets. This suggests a visible association in the supplied data. "
        "However, the sample is small and does not prove that the exceptions "
        "caused the negative tickets."
    ) in answers
    quality_report = (generated_dir / "data_quality_report.md").read_text(
        encoding="utf-8"
    )
    assert (
        "DQ001 and DQ004 validate uniqueness after duplicate resolution. "
        "Source duplicates remain visible as transformation exceptions."
    ) in quality_report
    reconciliation = (generated_dir / "reconciliation_report.md").read_text(
        encoding="utf-8"
    )
    assert "| Reconciliation difference | 0 | 0.00 |" in reconciliation
