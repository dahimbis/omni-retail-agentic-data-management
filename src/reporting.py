"""Write data-quality report, exceptions CSV, and business answers."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from src.ingest import OUTPUT_DIR

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _md_table(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "_No rows._\n"
    cols = [str(c) for c in df.columns]
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    rows = []
    for _, row in df.iterrows():
        cells = []
        for col in df.columns:
            val = row[col]
            cells.append("" if pd.isna(val) else str(val).replace("|", "\\|"))
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, sep, *rows]) + "\n"


def _run_sql_file(con: duckdb.DuckDBPyConnection, path: Path) -> list[pd.DataFrame]:
    """Execute a multi-statement SQL file; return each SELECT result."""
    text = path.read_text(encoding="utf-8")
    # strip line comments
    cleaned_lines = []
    for line in text.splitlines():
        if line.strip().startswith("--"):
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)
    statements = [s.strip() for s in text.split(";") if s.strip()]
    results: list[pd.DataFrame] = []
    for stmt in statements:
        cur = con.execute(stmt)
        if cur.description is not None:
            results.append(cur.df())
    return results


def write_outputs(con: duckdb.DuckDBPyConnection) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    exceptions = con.execute(
        """
        SELECT rule_id, dataset, record_key, severity, issue_description, suggested_action
        FROM dq_exception_report
        ORDER BY
          CASE severity WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
          rule_id, dataset, record_key
        """
    ).df()
    exceptions.to_csv(OUTPUT_DIR / "exceptions.csv", index=False)

    dq = con.execute("SELECT * FROM dq_results ORDER BY rule_id").df()
    counts = con.execute(
        """
        SELECT 'stg_customers' AS table_name, count(*) AS row_count FROM stg_customers
        UNION ALL SELECT 'stg_products', count(*) FROM stg_products
        UNION ALL SELECT 'stg_orders', count(*) FROM stg_orders
        UNION ALL SELECT 'stg_payments', count(*) FROM stg_payments
        UNION ALL SELECT 'stg_support_tickets', count(*) FROM stg_support_tickets
        UNION ALL SELECT 'dim_customer', count(*) FROM dim_customer
        UNION ALL SELECT 'dim_product', count(*) FROM dim_product
        UNION ALL SELECT 'fact_order', count(*) FROM fact_order
        UNION ALL SELECT 'fact_payment', count(*) FROM fact_payment
        UNION ALL SELECT 'fact_customer_issue', count(*) FROM fact_customer_issue
        """
    ).df()

    passed = int((dq["status"] == "PASS").sum()) if not dq.empty else 0
    failed = int((dq["status"] == "FAIL").sum()) if not dq.empty else 0

    dq_report = "\n".join(
        [
            "# Data Quality Report",
            "",
            "Generated from curated DuckDB model and DQ001–DQ013 checks.",
            "",
            "## Pipeline row counts",
            "",
            _md_table(counts),
            f"- Rules passed: **{passed}**",
            f"- Rules failed: **{failed}**",
            f"- Exception rows: **{len(exceptions)}**",
            "",
            "## Rule results",
            "",
            _md_table(dq),
            "## Exception preview",
            "",
            f"Full detail: `exceptions.csv` (`dq_exception_report`).",
            "",
            _md_table(exceptions.head(40)),
            "",
        ]
    )
    (OUTPUT_DIR / "data_quality_report.md").write_text(dq_report, encoding="utf-8")

    # Business answers from sql/business_questions.sql
    bq_frames = _run_sql_file(con, SQL_DIR / "business_questions.sql")
    labels = [
        ("Q1 — Completed revenue by month", 0),
        ("Q2 — Top 10 customers by completed order value", 1),
        ("Q3 — Orders with payment / FK / quantity exceptions", 2),
        ("Q4 — Completed revenue by state", 3),
        ("Q5a — Negative tickets vs order/payment exceptions (summary)", 4),
        ("Q5b — Negative tickets vs exceptions (customer detail)", 5),
    ]
    sections = [
        "# Business Question Answers",
        "",
        "Answers are generated with SQL from `sql/business_questions.sql` "
        "against the curated/intermediate model (not hard-coded).",
        "",
    ]
    for title, idx in labels:
        sections.append(f"## {title}")
        sections.append("")
        if idx < len(bq_frames):
            sections.append(_md_table(bq_frames[idx]))
        else:
            sections.append("_Query missing._\n")
        sections.append("")

    (OUTPUT_DIR / "business_answers.md").write_text("\n".join(sections), encoding="utf-8")
