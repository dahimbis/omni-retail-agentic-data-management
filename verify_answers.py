"""Independent verification of business answers against curated.duckdb and raw CSV."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent
con = duckdb.connect(str(ROOT / "outputs" / "curated.duckdb"), read_only=True)

# --- Q1/Q2/Q4 from curated completed positive-qty orders ---
fact = con.execute(
    """
    SELECT order_key, customer_key, product_key, order_date, quantity,
           shipping_state, gross_order_amount
    FROM fact_order
    WHERE lower(order_status) = 'completed' AND quantity > 0
    ORDER BY order_key
    """
).df()

print("CURATED completed qty>0 orders:", len(fact))
print("Grand revenue:", round(fact["gross_order_amount"].sum(), 2))

q1 = (
    fact.assign(month=fact["order_date"].map(lambda d: d.strftime("%Y-%m")))
    .groupby("month", as_index=False)
    .agg(completed_revenue=("gross_order_amount", "sum"), completed_order_count=("order_key", "count"))
)
q1["completed_revenue"] = q1["completed_revenue"].round(2)
print("\nQ1 Independent:\n", q1.to_string(index=False))

q2 = (
    fact.groupby("customer_key", as_index=False)
    .agg(completed_order_value=("gross_order_amount", "sum"), completed_orders=("order_key", "count"))
    .sort_values("completed_order_value", ascending=False)
    .head(10)
)
q2["completed_order_value"] = q2["completed_order_value"].round(2)
print("\nQ2 Independent:\n", q2.to_string(index=False))

q4 = (
    fact.groupby("shipping_state", as_index=False)
    .agg(completed_revenue=("gross_order_amount", "sum"), completed_order_count=("order_key", "count"))
    .sort_values("completed_revenue", ascending=False)
)
q4["completed_revenue"] = q4["completed_revenue"].round(2)
print("\nQ4 Independent:\n", q4.to_string(index=False))

# --- Q3 known intentional issues from raw + int tables ---
print("\nQ3 checks:")
checks = {
    "O1019 invalid customer": con.execute(
        "SELECT customer_key, valid_customer FROM int_order WHERE order_key='O1019'"
    ).fetchall(),
    "O1020 invalid product": con.execute(
        "SELECT product_key, valid_product FROM int_order WHERE order_key='O1020'"
    ).fetchall(),
    "O1021 totals": con.execute(
        """
        SELECT o.gross_order_amount, o.calculated_order_amount, p.payment_amount
        FROM int_order o
        LEFT JOIN int_payment p ON o.order_key = p.order_key AND lower(p.payment_status)='settled'
        WHERE o.order_key='O1021'
        """
    ).fetchall(),
    "O1024 payments": con.execute(
        "SELECT count(*) FROM int_payment WHERE order_key='O1024'"
    ).fetchone(),
    "O1030 qty": con.execute(
        "SELECT quantity, gross_order_amount FROM int_order WHERE order_key='O1030'"
    ).fetchall(),
}
for k, v in checks.items():
    print(f"  {k}: {v}")

q3 = con.execute(
    """
    WITH flagged AS (
      SELECT order_key, 'invalid_customer_reference' AS issue FROM int_order WHERE NOT valid_customer
      UNION ALL SELECT order_key, 'invalid_product_reference' FROM int_order WHERE NOT valid_product
      UNION ALL SELECT order_key, 'suspicious_quantity' FROM int_order
        WHERE lower(order_status)='completed' AND (quantity IS NULL OR quantity <= 0)
      UNION ALL SELECT o.order_key, 'payment_amount_mismatch' FROM int_order o
        JOIN int_payment p ON o.order_key=p.order_key
        WHERE lower(o.order_status)='completed' AND lower(p.payment_status)='settled'
          AND abs(p.payment_amount - o.gross_order_amount) > 0.01
      UNION ALL SELECT o.order_key, 'missing_payment' FROM int_order o
        LEFT JOIN int_payment p
          ON o.order_key=p.order_key AND lower(p.payment_status) IN ('settled','refunded')
        WHERE lower(o.order_status)='completed' AND p.payment_key IS NULL
    )
    SELECT order_key, string_agg(DISTINCT issue, ', ') AS issues
    FROM flagged GROUP BY 1 ORDER BY 1
    """
).df()
print("\nQ3 Independent:\n", q3.to_string(index=False))

# --- Q5 from raw tickets + exception customers ---
tickets = pd.read_json(ROOT / "input_data" / "support_tickets.jsonl", lines=True)
neg = tickets[tickets["sentiment"] == "negative"]
print("\nRaw negative tickets:", neg[["ticket_id", "customer_id", "category"]].to_string(index=False))

exc_cust = con.execute(
    """
    SELECT DISTINCT customer_key FROM (
      SELECT customer_key FROM int_order WHERE NOT valid_customer
      UNION SELECT customer_key FROM int_order WHERE NOT valid_product
      UNION SELECT customer_key FROM int_order
        WHERE lower(order_status)='completed' AND (quantity IS NULL OR quantity <= 0)
      UNION SELECT o.customer_key FROM int_order o
        JOIN int_payment p ON o.order_key=p.order_key
        WHERE lower(o.order_status)='completed' AND lower(p.payment_status)='settled'
          AND abs(p.payment_amount - o.gross_order_amount) > 0.01
      UNION SELECT o.customer_key FROM int_order o
        LEFT JOIN int_payment p
          ON o.order_key=p.order_key AND lower(p.payment_status) IN ('settled','refunded')
        WHERE lower(o.order_status)='completed' AND p.payment_key IS NULL
    ) WHERE customer_key IS NOT NULL
    """
).df()["customer_key"].tolist()
print("Exception customers:", sorted(exc_cust))

valid_neg = neg[neg["customer_id"].isin(set(con.execute("SELECT customer_key FROM dim_customer").df()["customer_key"]))]
neg_customers = sorted(valid_neg["customer_id"].unique())
overlap = [c for c in neg_customers if c in exc_cust]
print("Negative ticket customers (valid):", neg_customers)
print("Overlap:", overlap, "rate", round(len(overlap) / len(neg_customers), 3) if neg_customers else None)

# C001 True because O1020 invalid product
print("\nWhy C001 flagged True:", con.execute(
    "SELECT order_key, product_key, valid_product FROM int_order WHERE customer_key='C001' AND NOT valid_product"
).fetchall())

# Compare reported file
print("\n=== MATCH vs report ===")
report_q1 = {"2025-03": 440.7, "2025-04": 356.97, "2025-05": 446.2}
ind_q1 = dict(zip(q1["month"], q1["completed_revenue"]))
print("Q1 match:", ind_q1 == report_q1, ind_q1)

report_top = ["C010", "C016", "C012", "C007", "C002", "C009", "C018", "C004", "C003", "C013"]
print("Q2 top keys match:", q2["customer_key"].tolist() == report_top, q2["customer_key"].tolist())

print("Q3 keys match:", q3["order_key"].tolist() == ["O1019", "O1020", "O1021", "O1024", "O1030"])

report_states = {"MA": 278.23, "IL": 277.97, "WA": 192.98, "CA": 169.72, "TX": 141.98, "NY": 117.0, "FL": 65.99}
ind_states = dict(zip(q4["shipping_state"], q4["completed_revenue"]))
print("Q4 match:", ind_states == report_states, ind_states)

print("Q5 overlap 3/6=0.5:", len(overlap) == 3 and len(neg_customers) == 6)

con.close()
print("\nDONE")
