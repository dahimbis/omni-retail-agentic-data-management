"""Write data-quality report, exceptions CSV, charts, and business answers."""

from __future__ import annotations

from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import pandas as pd

from src.ingest import OUTPUT_DIR

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
CHARTS_DIR = OUTPUT_DIR / "charts"


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
) -> Path:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    path = CHARTS_DIR / filename
    fig, ax = plt.subplots(figsize=(8, 4.5))
    if horizontal:
        ax.barh(categories, values, color="#2F6F8F")
        ax.set_xlabel(ylabel)
        ax.invert_yaxis()
    else:
        ax.bar(categories, values, color="#2F6F8F")
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
        )
        images["q2"] = "charts/q2_top_customers.png"

    if len(bq_frames) > 3 and not bq_frames[3].empty:
        q4 = bq_frames[3]
        _save_bar_chart(
            categories=q4["state"].astype(str).tolist(),
            values=q4["completed_revenue"].astype(float).tolist(),
            title="Q4: Completed revenue by state",
            ylabel="Revenue ($)",
            filename="q4_revenue_by_state.png",
        )
        images["q4"] = "charts/q4_revenue_by_state.png"

    return images


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

    # Optional small severity chart for DQ report
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    sev = (
        exceptions.groupby("severity").size().reindex(["High", "Medium", "Low"]).fillna(0)
        if not exceptions.empty
        else pd.Series({"High": 0, "Medium": 0, "Low": 0})
    )
    _save_bar_chart(
        categories=[str(x) for x in sev.index.tolist()],
        values=[float(x) for x in sev.values.tolist()],
        title="Exception count by severity",
        ylabel="Count",
        filename="dq_exceptions_by_severity.png",
    )

    dq_report = "\n".join(
        [
            "# Data Quality Report",
            "",
            "Generated from the curated DuckDB model and DQ001 to DQ013 checks.",
            "",
            "## Pipeline row counts",
            "",
            _md_table(counts),
            f"- Rules passed: **{passed}**",
            f"- Rules failed: **{failed}**",
            f"- Exception rows: **{len(exceptions)}**",
            "",
            "## Exception count by severity",
            "",
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
        "against the curated model. Values are not hard-coded. Charts are "
        "created automatically each time the pipeline runs.",
        "",
        "## Q1. What is completed revenue by month?",
        "",
        "Trusted completed orders only (valid customer and product IDs, quantity greater than zero).",
        "",
    ]
    if "q1" in images:
        sections.extend([f"![Q1 completed revenue by month]({images['q1']})", ""])
    sections.extend(
        [
            _md_table(bq_frames[0]) if len(bq_frames) > 0 else "_Query missing._\n",
            "",
            "## Q2. Who are the top 10 customers by completed order value?",
            "",
        ]
    )
    if "q2" in images:
        sections.extend([f"![Q2 top customers]({images['q2']})", ""])
    sections.extend(
        [
            _md_table(bq_frames[1]) if len(bq_frames) > 1 else "_Query missing._\n",
            "",
            "## Q3. Which orders have payment mismatches, missing payments, "
            "invalid customer references, invalid product references, or suspicious quantities?",
            "",
            _md_table(bq_frames[2]) if len(bq_frames) > 2 else "_Query missing._\n",
            "",
            "## Q4. Which states have the highest completed revenue?",
            "",
        ]
    )
    if "q4" in images:
        sections.extend([f"![Q4 completed revenue by state]({images['q4']})", ""])
    sections.extend(
        [
            _md_table(bq_frames[3]) if len(bq_frames) > 3 else "_Query missing._\n",
            "",
            "## Q5. Is there any visible relationship between negative support tickets "
            "and order or payment exceptions?",
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
