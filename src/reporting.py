"""Write data-quality report, exceptions CSV, charts, and business answers."""

from __future__ import annotations

from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import pandas as pd

from src.ingest import OUTPUT_DIR

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
CHARTS_DIR = OUTPUT_DIR / "charts"

# Simple professional palette (no purple glow stack)
COLOR_PRIMARY = "#2F6F8F"  # revenue / single-series charts
COLOR_TRUSTED = "#2E7D4F"  # healthy / trusted
COLOR_EXCEPTION = "#C45C26"  # problems needing review
COLOR_HIGH = "#B33A3A"
COLOR_MEDIUM = "#C45C26"
COLOR_LOW = "#6B7280"


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
    # DuckDB handles SQL comments. Preserve them so comment markers inside quoted
    # text are not accidentally treated as comments by a home-grown parser.
    statements = [s.strip() for s in text.split(";") if s.strip()]
    results: list[pd.DataFrame] = []
    for stmt in statements:
        cur = con.execute(stmt)
        if cur.description is not None:
            results.append(cur.df())
    return results


def _style_axes(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.3)


def _save_bar_chart(
    categories: list[str],
    values: list[float],
    title: str,
    ylabel: str,
    filename: str,
    horizontal: bool = False,
    colors: str | list[str] | None = None,
) -> Path:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    path = CHARTS_DIR / filename
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bar_colors = colors if colors is not None else COLOR_PRIMARY
    if horizontal:
        ax.barh(categories, values, color=bar_colors)
        ax.set_xlabel(ylabel)
        ax.invert_yaxis()
    else:
        ax.bar(categories, values, color=bar_colors)
        ax.set_ylabel(ylabel)
        ax.tick_params(axis="x", rotation=0)
    ax.set_title(title)
    _style_axes(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _write_charts(bq_frames: list[pd.DataFrame]) -> dict[str, str]:
    """Create stakeholder charts. Returns markdown-relative image paths."""
    images: dict[str, str] = {}
    if len(bq_frames) > 0 and not bq_frames[0].empty:
        q1 = bq_frames[0]
        _save_bar_chart(
            categories=q1["month"].astype(str).tolist(),
            values=q1["completed_revenue"].astype(float).tolist(),
            title="Q1: Completed revenue by month",
            ylabel="Revenue ($)",
            filename="q1_revenue_by_month.png",
            colors=COLOR_PRIMARY,
        )
        images["q1"] = "charts/q1_revenue_by_month.png"

    if len(bq_frames) > 1 and not bq_frames[1].empty:
        q2 = bq_frames[1].copy()
        labels = [
            f"{row.customer_key} ({row.full_name})" for row in q2.itertuples(index=False)
        ]
        _save_bar_chart(
            categories=labels,
            values=q2["completed_order_value"].astype(float).tolist(),
            title="Q2: Top 10 customers by completed order value",
            ylabel="Completed order value ($)",
            filename="q2_top_customers.png",
            horizontal=True,
            colors=COLOR_PRIMARY,
        )
        images["q2"] = "charts/q2_top_customers.png"

    if len(bq_frames) > 3 and not bq_frames[3].empty:
        q4 = bq_frames[3]
        _save_bar_chart(
            categories=q4["state"].astype(str).tolist(),
            values=q4["completed_revenue"].astype(float).tolist(),
            title="Q4: Completed revenue by shipping state",
            ylabel="Revenue ($)",
            filename="q4_revenue_by_state.png",
            colors=COLOR_PRIMARY,
        )
        images["q4"] = "charts/q4_revenue_by_state.png"

    return images


def _order_health_counts(con: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    completed = con.execute(
        """
        SELECT count(*)
        FROM int_order
        WHERE lower(order_status) = 'completed'
        """
    ).fetchone()[0]
    requiring_review = con.execute(
        """
        WITH exception_orders AS (
          SELECT e.record_key AS order_key
          FROM dq_exception_report e
          JOIN int_order o ON e.record_key = o.order_key
          WHERE e.dataset = 'orders'
            AND lower(o.order_status) = 'completed'
          UNION
          SELECT p.order_key
          FROM dq_exception_report e
          JOIN int_payment p ON e.record_key = p.payment_key
          JOIN int_order o ON p.order_key = o.order_key
          WHERE e.dataset = 'payments'
            AND lower(o.order_status) = 'completed'
        )
        SELECT count(DISTINCT order_key) FROM exception_orders
        """
    ).fetchone()[0]
    clear = int(completed) - int(requiring_review)
    return clear, int(requiring_review)


def _write_order_health_chart(clear: int, requiring_review: int) -> Path:
    """Mutually exclusive completed-order health counts."""
    return _save_bar_chart(
        categories=["Completed orders clear", "Completed orders requiring review"],
        values=[float(clear), float(requiring_review)],
        title="Order health snapshot",
        ylabel="Order count",
        filename="readme_order_health.png",
        colors=[COLOR_TRUSTED, COLOR_EXCEPTION],
    )


def _section_with_table_then_chart(
    title: str,
    intro: str | None,
    table_df: pd.DataFrame | None,
    chart_path: str | None,
    chart_alt: str,
) -> list[str]:
    parts = [f"## {title}", ""]
    if intro:
        parts.extend([intro, ""])
    if table_df is not None:
        parts.extend([_md_table(table_df), ""])
    else:
        parts.extend(["_Query missing._\n", ""])
    if chart_path:
        parts.extend([f"![{chart_alt}]({chart_path})", ""])
    return parts


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

    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    clear_n, review_n = _order_health_counts(con)
    _write_order_health_chart(clear_n, review_n)

    sev = (
        exceptions.groupby("severity").size().reindex(["High", "Medium", "Low"]).fillna(0)
        if not exceptions.empty
        else pd.Series({"High": 0, "Medium": 0, "Low": 0})
    )
    sev_df = pd.DataFrame(
        {"severity": sev.index.astype(str), "exception_count": sev.values.astype(int)}
    )
    _save_bar_chart(
        categories=sev_df["severity"].tolist(),
        values=sev_df["exception_count"].astype(float).tolist(),
        title="Exception count by severity",
        ylabel="Count",
        filename="dq_exceptions_by_severity.png",
        colors=[COLOR_HIGH, COLOR_MEDIUM, COLOR_LOW],
    )

    # Keep a small snapshot table next to the README chart path for regenerable docs
    snapshot_df = pd.DataFrame(
        {
            "category": [
                "Completed orders clear",
                "Completed orders requiring review",
            ],
            "order_count": [clear_n, review_n],
        }
    )
    (OUTPUT_DIR / "order_health_snapshot.md").write_text(
        "\n".join(
            [
                "# Order health snapshot",
                "",
                "The categories are mutually exclusive. Requiring review means a completed "
                "order has at least one order or payment record in `dq_exception_report`.",
                "",
                _md_table(snapshot_df),
                "![Order health snapshot](charts/readme_order_health.png)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    unique_affected_records = len(
        exceptions[["dataset", "record_key"]].drop_duplicates()
    )
    dq_report = "\n".join(
        [
            "# Data Quality Report",
            "",
            f"Generated from the curated DuckDB model and {len(dq)} data quality checks.",
            "",
            "## Pipeline row counts",
            "",
            _md_table(counts),
            f"- Rules passed: **{passed}**",
            f"- Rules failed: **{failed}**",
            f"- Exception rows: **{len(exceptions)}**",
            f"- Distinct affected records: **{unique_affected_records}**",
            "",
            "The exception report also retains non-duplicated transform resolution events "
            "and informational fuzzy-match flags. These are not additional DQ rules.",
            "",
            "## Exception count by severity",
            "",
            _md_table(sev_df),
            "![Exception count by severity](charts/dq_exceptions_by_severity.png)",
            "",
            "## Rule results",
            "",
            _md_table(dq),
            "## Exception preview",
            "",
            "Full detail: `exceptions.csv` (`dq_exception_report`).",
            "",
            _md_table(exceptions.head(40)),
            "",
        ]
    )
    (OUTPUT_DIR / "data_quality_report.md").write_text(dq_report, encoding="utf-8")

    bq_frames = _run_sql_file(con, SQL_DIR / "business_questions.sql")
    images = _write_charts(bq_frames)

    sections = [
        "# Business Question Answers",
        "",
        "Answers are generated with SQL from `sql/business_questions.sql` "
        "against the curated model. Values are not hard-coded. Each section shows "
        "the table first, then the chart. Charts refresh when the pipeline runs.",
        "",
    ]
    sections.extend(
        _section_with_table_then_chart(
            "Q1. What is completed revenue by month?",
            "Revenue-eligible completed orders: valid customer and product IDs, "
            "a parsed order date, and quantity greater than zero. Payment and catalog "
            "exceptions remain visible in the quality report.",
            bq_frames[0] if len(bq_frames) > 0 else None,
            images.get("q1"),
            "Q1 completed revenue by month",
        )
    )
    sections.extend(
        _section_with_table_then_chart(
            "Q2. Who are the top 10 customers by completed order value?",
            None,
            bq_frames[1] if len(bq_frames) > 1 else None,
            images.get("q2"),
            "Q2 top customers",
        )
    )
    sections.extend(
        [
            "## Q3. Which orders have payment mismatches, missing payments, "
            "invalid customer references, invalid product references, or suspicious quantities?",
            "",
            "This answer is intentionally limited to the five exception categories named "
            "in the question. The data quality report also covers issues such as inactive "
            "products and order arithmetic variance.",
            "",
            _md_table(bq_frames[2]) if len(bq_frames) > 2 else "_Query missing._\n",
            "",
        ]
    )
    sections.extend(
        _section_with_table_then_chart(
            "Q4. Which shipping states have the highest completed revenue?",
            "Revenue is attributed to the order shipping state, not the customer's home state.",
            bq_frames[3] if len(bq_frames) > 3 else None,
            images.get("q4"),
            "Q4 completed revenue by state",
        )
    )
    sections.extend(
        [
            "## Q5. Is there any visible relationship between negative support tickets "
            "and order or payment exceptions?",
            "",
            "The exception-customer group uses the same five categories as Q3 so the "
            "comparison is consistent and reproducible.",
            "",
            "### Summary",
            "",
            _md_table(bq_frames[4]) if len(bq_frames) > 4 else "_Query missing._\n",
            "",
            "### Customer detail",
            "",
            _md_table(bq_frames[5]) if len(bq_frames) > 5 else "_Query missing._\n",
            "",
        ]
    )

    (OUTPUT_DIR / "business_answers.md").write_text("\n".join(sections), encoding="utf-8")
