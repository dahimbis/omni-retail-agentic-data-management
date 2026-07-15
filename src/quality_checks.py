"""Data-quality checks and dq_exception_report assembly."""

from __future__ import annotations

import duckdb
import pandas as pd

EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

SUGGESTED_ACTIONS = {
    "DQ001": "Enforce unique customer_key in curated load and fix source duplicates",
    "DQ002": "Request missing email or correct invalid syntax before marketing use",
    "DQ003": "Apply reference data standardization for country/state",
    "DQ004": "Deduplicate orders at ingest and block duplicate order_id writes",
    "DQ005": "Quarantine order; repair customer_key via MDM lookup",
    "DQ006": "Quarantine order; repair product_key in catalog",
    "DQ007": "Hold completed order with non-positive quantity for ops review",
    "DQ008": "Reconcile order_total vs qty*unit_price; correct pricing feed",
    "DQ009": "Reject orphan payment or create missing order if legitimate",
    "DQ010": "Investigate settled amount vs completed order total mismatch",
    "DQ011": "Fix malformed ticket timestamp in source system",
    "DQ012": "Link ticket to valid customer_key or quarantine",
    "DQ013": "Flag completed sales of inactive products for catalog review",
    "DQ014": "Create or locate the missing payment before closing the order",
    "DQ015": "Hold payment in the audit layer until the related order keys are repaired",
    "DQ016": "Deduplicate payment IDs and repair the payment source write path",
}


def _append(
    buckets: list[pd.DataFrame],
    rule_id: str,
    dataset: str,
    entities: pd.DataFrame,
    severity: str,
) -> int:
    if entities.empty:
        return 0
    frame = pd.DataFrame(
        {
            "rule_id": rule_id,
            "dataset": dataset,
            "record_key": entities["record_key"].astype(str),
            "severity": severity,
            "issue_description": entities["issue_description"].astype(str),
            "suggested_action": SUGGESTED_ACTIONS.get(
                rule_id, "Review record and document remediation"
            ),
        }
    )
    buckets.append(frame)
    return len(frame)


def run_quality_checks(con: duckdb.DuckDBPyConnection) -> None:
    exceptions: list[pd.DataFrame] = []
    results: list[dict] = []

    # Keep source-resolution events that are not repeated by a DQ rule.
    # FK, orphan-payment, and ticket transform issues are represented by
    # DQ005/006/009/011/012 below to avoid double-counting the same defect.
    transform_ex = con.execute(
        """
        SELECT *
        FROM transform_exceptions
        WHERE rule_id IN (
          'TRANSFORM_DEDUP_CUSTOMER',
          'TRANSFORM_DEDUP_ORDER',
          'TRANSFORM_DEDUP_PAYMENT',
          'INFO_FUZZY_CUSTOMER_PHONE'
        )
        """
    ).df()
    if not transform_ex.empty:
        exceptions.append(transform_ex)

    def record(rule_id: str, description: str, severity: str, fail_n: int) -> None:
        results.append(
            {
                "rule_id": rule_id,
                "description": description,
                "severity": severity,
                "status": "PASS" if fail_n == 0 else "FAIL",
                "fail_count": fail_n,
            }
        )

    violators = con.execute(
        """
        SELECT customer_key AS record_key, 'duplicate customer_key in dim_customer' AS issue_description
        FROM dim_customer GROUP BY 1 HAVING COUNT(*) > 1
        """
    ).df()
    record("DQ001", "customer_id must be unique after duplicate resolution", "High",
           _append(exceptions, "DQ001", "customers", violators, "High"))

    email_issues = con.execute(
        f"""
        SELECT customer_key AS record_key,
               CASE
                 WHEN email IS NULL OR trim(email) = '' THEN 'missing email'
                 ELSE 'invalid email syntax: ' || email
               END AS issue_description
        FROM dim_customer
        WHERE email IS NULL
           OR trim(email) = ''
           OR NOT regexp_matches(email, '{EMAIL_RE}')
        """
    ).df()
    record("DQ002", "email must be present and syntactically valid", "Medium",
           _append(exceptions, "DQ002", "customers", email_issues, "Medium"))

    geo_issues = con.execute(
        """
        SELECT customer_key AS record_key,
               'non-standard geo country=' || coalesce(standard_country, 'NULL')
               || ' state=' || coalesce(standard_state, 'NULL') AS issue_description
        FROM dim_customer
        WHERE standard_country IS NULL OR length(standard_country) = 0
           OR standard_state IS NULL OR length(standard_state) <> 2
        """
    ).df()
    record("DQ003", "country and state must be standardized", "Medium",
           _append(exceptions, "DQ003", "customers", geo_issues, "Medium"))

    order_dups = con.execute(
        """
        SELECT order_key AS record_key, 'duplicate order_key' AS issue_description
        FROM int_order GROUP BY 1 HAVING COUNT(*) > 1
        """
    ).df()
    record("DQ004", "order_id must be unique", "High",
           _append(exceptions, "DQ004", "orders", order_dups, "High"))

    bad_cust = con.execute(
        """
        SELECT order_key AS record_key,
               'invalid customer_key=' || customer_key AS issue_description
        FROM int_order WHERE NOT valid_customer
        """
    ).df()
    record("DQ005", "customer_id must exist in customers", "High",
           _append(exceptions, "DQ005", "orders", bad_cust, "High"))

    bad_prod = con.execute(
        """
        SELECT order_key AS record_key,
               'invalid product_key=' || product_key AS issue_description
        FROM int_order WHERE NOT valid_product
        """
    ).df()
    record("DQ006", "product_id must exist in products", "High",
           _append(exceptions, "DQ006", "orders", bad_prod, "High"))

    bad_qty = con.execute(
        """
        SELECT order_key AS record_key,
               'completed order quantity=' || cast(quantity AS VARCHAR) AS issue_description
        FROM int_order
        WHERE lower(order_status) = 'completed' AND (quantity IS NULL OR quantity <= 0)
        """
    ).df()
    record("DQ007", "completed orders must have positive quantity", "High",
           _append(exceptions, "DQ007", "orders", bad_qty, "High"))

    amount_mismatch = con.execute(
        """
        SELECT order_key AS record_key,
               'order_total=' || cast(gross_order_amount AS VARCHAR)
               || ' calculated=' || cast(calculated_order_amount AS VARCHAR)
               || ' variance=' || cast(order_amount_variance AS VARCHAR) AS issue_description
        FROM int_order
        WHERE valid_product
          AND calculated_order_amount IS NOT NULL
          AND gross_order_amount IS NOT NULL
          AND abs(coalesce(order_amount_variance, 0)) > 0.01
        """
    ).df()
    record("DQ008", "order_total should equal quantity times product unit_price", "High",
           _append(exceptions, "DQ008", "orders", amount_mismatch, "High"))

    orphan_pay = con.execute(
        """
        SELECT payment_key AS record_key,
               'orphan order_key=' || order_key AS issue_description
        FROM int_payment WHERE NOT valid_order
        """
    ).df()
    record("DQ009", "payment order_id must exist in orders", "High",
           _append(exceptions, "DQ009", "payments", orphan_pay, "High"))

    pay_mismatch = con.execute(
        """
        SELECT p.payment_key AS record_key,
               'settled amount=' || cast(p.payment_amount AS VARCHAR)
               || ' order_total=' || cast(o.gross_order_amount AS VARCHAR)
               || ' order=' || o.order_key AS issue_description
        FROM int_payment p
        JOIN int_order o ON p.order_key = o.order_key
        WHERE lower(p.payment_status) = 'settled'
          AND lower(o.order_status) = 'completed'
          AND abs(p.payment_amount - o.gross_order_amount) > 0.01
        """
    ).df()
    record("DQ010", "settled payment amount should equal completed order total", "High",
           _append(exceptions, "DQ010", "payments", pay_mismatch, "High"))

    missing_pay = con.execute(
        """
        SELECT o.order_key AS record_key,
               'completed order missing settled payment' AS issue_description
        FROM int_order o
        WHERE lower(o.order_status) = 'completed'
          AND NOT EXISTS (
            SELECT 1
            FROM int_payment p
            WHERE p.order_key = o.order_key
              AND lower(p.payment_status) = 'settled'
          )
        """
    ).df()
    record(
        "DQ014",
        "completed orders should have a settled payment",
        "High",
        _append(exceptions, "DQ014", "orders", missing_pay, "High"),
    )

    quarantined_payments = con.execute(
        """
        SELECT payment_key AS record_key,
               'payment references order excluded from fact_order: ' || order_key
                 AS issue_description
        FROM int_payment
        WHERE valid_order AND NOT in_curated_order
        """
    ).df()
    record(
        "DQ015",
        "payments tied to quarantined orders must remain visible",
        "High",
        _append(exceptions, "DQ015", "payments", quarantined_payments, "High"),
    )

    duplicate_payments = con.execute(
        """
        SELECT payment_key AS record_key,
               'duplicate payment_key in fact_payment' AS issue_description
        FROM fact_payment
        GROUP BY 1
        HAVING count(*) > 1
        """
    ).df()
    record(
        "DQ016",
        "payment_id must be unique after duplicate resolution",
        "High",
        _append(exceptions, "DQ016", "payments", duplicate_payments, "High"),
    )

    bad_ts = con.execute(
        """
        SELECT ticket_id AS record_key,
               'unparseable created_ts=' || cast(created_ts AS VARCHAR) AS issue_description
        FROM int_customer_issue WHERE NOT parse_ok
        """
    ).df()
    record("DQ011", "created_ts must parse to a valid timestamp", "Medium",
           _append(exceptions, "DQ011", "support_tickets", bad_ts, "Medium"))

    bad_ticket_cust = con.execute(
        """
        SELECT ticket_id AS record_key,
               'invalid customer_key=' || customer_key AS issue_description
        FROM int_customer_issue WHERE NOT valid_customer
        """
    ).df()
    record("DQ012", "customer_id should exist in customers", "Medium",
           _append(exceptions, "DQ012", "support_tickets", bad_ticket_cust, "Medium"))

    # Extended check required by brief: inactive products
    inactive = con.execute(
        """
        SELECT o.order_key AS record_key,
               'completed order uses inactive product ' || o.product_key AS issue_description
        FROM int_order o
        JOIN dim_product p ON o.product_key = p.product_key
        WHERE lower(o.order_status) = 'completed'
          AND upper(coalesce(p.active_flag, 'Y')) = 'N'
        """
    ).df()
    record("DQ013", "completed orders should not reference inactive products", "Medium",
           _append(exceptions, "DQ013", "orders", inactive, "Medium"))

    dq_results = pd.DataFrame(results)
    if exceptions:
        dq_exception_report = pd.concat(exceptions, ignore_index=True)
        dq_exception_report = dq_exception_report.drop_duplicates(
            subset=["rule_id", "dataset", "record_key", "issue_description"], keep="first"
        )
    else:
        dq_exception_report = pd.DataFrame(
            columns=[
                "rule_id",
                "dataset",
                "record_key",
                "severity",
                "issue_description",
                "suggested_action",
            ]
        )

    con.register("dq_results_df", dq_results)
    con.execute("CREATE OR REPLACE TABLE dq_results AS SELECT * FROM dq_results_df")
    con.unregister("dq_results_df")

    con.register("dq_exception_report_df", dq_exception_report)
    con.execute(
        "CREATE OR REPLACE TABLE dq_exception_report AS SELECT * FROM dq_exception_report_df"
    )
    con.unregister("dq_exception_report_df")

    # One reusable source for business question 3, Q5 overlap, and reporting.
    con.execute(
        """
        CREATE OR REPLACE VIEW vw_order_exceptions AS
        WITH flagged AS (
          SELECT order_key, 'invalid_customer_reference' AS issue
          FROM int_order WHERE NOT valid_customer
          UNION ALL
          SELECT order_key, 'invalid_product_reference' AS issue
          FROM int_order WHERE NOT valid_product
          UNION ALL
          SELECT order_key, 'suspicious_quantity' AS issue
          FROM int_order
          WHERE lower(order_status) = 'completed'
            AND (quantity IS NULL OR quantity <= 0)
          UNION ALL
          SELECT o.order_key, 'payment_amount_mismatch' AS issue
          FROM int_order o
          JOIN int_payment p ON o.order_key = p.order_key
          WHERE lower(o.order_status) = 'completed'
            AND lower(p.payment_status) = 'settled'
            AND abs(p.payment_amount - o.gross_order_amount) > 0.01
          UNION ALL
          SELECT o.order_key, 'missing_payment' AS issue
          FROM int_order o
          WHERE lower(o.order_status) = 'completed'
            AND NOT EXISTS (
              SELECT 1
              FROM int_payment p
              WHERE p.order_key = o.order_key
                AND lower(p.payment_status) = 'settled'
            )
        )
        SELECT
          o.order_key,
          o.customer_key,
          o.product_key,
          o.order_status,
          o.quantity,
          o.gross_order_amount,
          string_agg(DISTINCT f.issue, ', ' ORDER BY f.issue) AS issues
        FROM flagged f
        JOIN int_order o ON f.order_key = o.order_key
        GROUP BY 1, 2, 3, 4, 5, 6
        """
    )
