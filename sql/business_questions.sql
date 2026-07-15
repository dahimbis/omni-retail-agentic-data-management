-- Business questions for OmniRetail curated model.
-- Executed by src/reporting.py against outputs/curated.duckdb after transform/DQ.
-- Completed revenue excludes non-positive quantities (DQ007 failures).

-- Q1: Completed revenue by month
SELECT
  strftime(order_date, '%Y-%m') AS month,
  round(sum(gross_order_amount), 2) AS completed_revenue,
  count(*) AS completed_order_count
FROM fact_order
WHERE lower(order_status) = 'completed'
  AND quantity > 0
  AND order_date IS NOT NULL
GROUP BY 1
ORDER BY 1;

-- Q2: Top 10 customers by completed order value
SELECT
  c.customer_key,
  c.full_name,
  c.loyalty_tier,
  round(sum(o.gross_order_amount), 2) AS completed_order_value,
  count(*) AS completed_orders
FROM fact_order o
JOIN dim_customer c ON o.customer_key = c.customer_key
WHERE lower(o.order_status) = 'completed'
  AND o.quantity > 0
GROUP BY 1, 2, 3
ORDER BY completed_order_value DESC
LIMIT 10;

-- Q3: Orders with payment mismatches, missing payments, invalid refs, suspicious qty
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
  LEFT JOIN int_payment p
    ON o.order_key = p.order_key
   AND lower(p.payment_status) IN ('settled', 'refunded')
  WHERE lower(o.order_status) = 'completed'
    AND p.payment_key IS NULL
)
SELECT
  f.order_key,
  o.customer_key,
  o.product_key,
  o.order_status,
  o.quantity,
  o.gross_order_amount,
  string_agg(DISTINCT f.issue, ', ') AS issues
FROM flagged f
JOIN int_order o ON f.order_key = o.order_key
GROUP BY 1, 2, 3, 4, 5, 6
ORDER BY 1;

-- Q4: Completed revenue by state
SELECT
  coalesce(shipping_state, 'UNKNOWN') AS state,
  round(sum(gross_order_amount), 2) AS completed_revenue,
  count(*) AS completed_order_count
FROM fact_order
WHERE lower(order_status) = 'completed'
  AND quantity > 0
GROUP BY 1
ORDER BY completed_revenue DESC;

-- Q5a: Summary overlap between negative tickets and exception customers
WITH exception_customers AS (
  SELECT DISTINCT customer_key
  FROM (
    SELECT customer_key FROM int_order WHERE NOT valid_customer
    UNION
    SELECT customer_key FROM int_order WHERE NOT valid_product
    UNION
    SELECT customer_key FROM int_order
    WHERE lower(order_status) = 'completed'
      AND (quantity IS NULL OR quantity <= 0)
    UNION
    SELECT o.customer_key
    FROM int_order o
    JOIN int_payment p ON o.order_key = p.order_key
    WHERE lower(o.order_status) = 'completed'
      AND lower(p.payment_status) = 'settled'
      AND abs(p.payment_amount - o.gross_order_amount) > 0.01
    UNION
    SELECT o.customer_key
    FROM int_order o
    LEFT JOIN int_payment p
      ON o.order_key = p.order_key
     AND lower(p.payment_status) IN ('settled', 'refunded')
    WHERE lower(o.order_status) = 'completed'
      AND p.payment_key IS NULL
  )
  WHERE customer_key IS NOT NULL
),
neg_tickets AS (
  SELECT customer_key, count(*) AS negative_ticket_count
  FROM int_customer_issue
  WHERE lower(sentiment) = 'negative' AND valid_customer
  GROUP BY 1
)
SELECT
  count(*) AS negative_ticket_customers,
  sum(CASE WHEN e.customer_key IS NOT NULL THEN 1 ELSE 0 END) AS also_have_exceptions,
  round(
    sum(CASE WHEN e.customer_key IS NOT NULL THEN 1 ELSE 0 END) * 1.0 / nullif(count(*), 0),
    3
  ) AS overlap_rate
FROM neg_tickets n
LEFT JOIN exception_customers e ON n.customer_key = e.customer_key;

-- Q5b: Customer-level detail for negative tickets vs exceptions
WITH exception_customers AS (
  SELECT DISTINCT customer_key
  FROM (
    SELECT customer_key FROM int_order WHERE NOT valid_customer
    UNION
    SELECT customer_key FROM int_order WHERE NOT valid_product
    UNION
    SELECT customer_key FROM int_order
    WHERE lower(order_status) = 'completed'
      AND (quantity IS NULL OR quantity <= 0)
    UNION
    SELECT o.customer_key
    FROM int_order o
    JOIN int_payment p ON o.order_key = p.order_key
    WHERE lower(o.order_status) = 'completed'
      AND lower(p.payment_status) = 'settled'
      AND abs(p.payment_amount - o.gross_order_amount) > 0.01
    UNION
    SELECT o.customer_key
    FROM int_order o
    LEFT JOIN int_payment p
      ON o.order_key = p.order_key
     AND lower(p.payment_status) IN ('settled', 'refunded')
    WHERE lower(o.order_status) = 'completed'
      AND p.payment_key IS NULL
  )
  WHERE customer_key IS NOT NULL
),
neg_tickets AS (
  SELECT
    customer_key,
    count(*) AS negative_ticket_count,
    string_agg(DISTINCT issue_category, ', ') AS categories
  FROM int_customer_issue
  WHERE lower(sentiment) = 'negative' AND valid_customer
  GROUP BY 1
)
SELECT
  n.customer_key,
  c.full_name,
  n.negative_ticket_count,
  n.categories,
  CASE WHEN e.customer_key IS NOT NULL THEN TRUE ELSE FALSE END AS has_order_payment_exception
FROM neg_tickets n
LEFT JOIN dim_customer c ON n.customer_key = c.customer_key
LEFT JOIN exception_customers e ON n.customer_key = e.customer_key
ORDER BY has_order_payment_exception DESC, n.negative_ticket_count DESC;
