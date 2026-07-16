-- Business questions for OmniRetail curated model.
-- Executed by src/reporting.py against outputs/curated.duckdb after transform/DQ.
-- Revenue eligibility is calculated once in src/transform.py:
-- completed status, valid customer/product keys, parsed date, and positive quantity.

-- Q1: Completed revenue by month
SELECT
  strftime(order_date, '%Y-%m') AS month,
  round(sum(gross_order_amount), 2) AS completed_revenue,
  count(*) AS completed_order_count
FROM fact_order
WHERE is_revenue_eligible
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
WHERE o.is_revenue_eligible
GROUP BY 1, 2, 3
ORDER BY completed_order_value DESC, c.customer_key
LIMIT 10;

-- Q3: Orders with payment mismatches, missing payments, invalid refs, suspicious qty
SELECT
  order_key,
  customer_key,
  product_key,
  order_status,
  quantity,
  gross_order_amount,
  issues
FROM vw_order_exceptions
ORDER BY order_key;

-- Q4: Completed revenue by shipping state
SELECT
  coalesce(shipping_state, 'UNKNOWN') AS state,
  round(sum(gross_order_amount), 2) AS completed_revenue,
  count(*) AS completed_order_count
FROM fact_order
WHERE is_revenue_eligible
GROUP BY 1
ORDER BY completed_revenue DESC, state;

-- Q5a: Compare exception rates for customers with and without negative tickets
WITH exception_customers AS (
  SELECT DISTINCT customer_key FROM vw_order_exceptions
  WHERE customer_key IS NOT NULL
),
negative_ticket_customers AS (
  SELECT DISTINCT customer_key
  FROM int_customer_issue
  WHERE lower(sentiment) = 'negative' AND valid_customer
),
customer_flags AS (
  SELECT
    c.customer_key,
    CASE
      WHEN n.customer_key IS NOT NULL THEN 'Negative support ticket'
      ELSE 'No negative support ticket'
    END AS customer_group,
    CASE WHEN e.customer_key IS NOT NULL THEN 1 ELSE 0 END AS has_exception
  FROM dim_customer c
  LEFT JOIN negative_ticket_customers n ON c.customer_key = n.customer_key
  LEFT JOIN exception_customers e ON c.customer_key = e.customer_key
)
SELECT
  customer_group,
  count(*) AS customers,
  sum(has_exception) AS customers_with_exceptions,
  round(sum(has_exception) * 1.0 / nullif(count(*), 0), 3) AS exception_rate
FROM customer_flags
GROUP BY 1
ORDER BY CASE WHEN customer_group = 'Negative support ticket' THEN 1 ELSE 2 END;

-- Q5b: Customer-level detail for negative tickets vs exceptions
WITH exception_customers AS (
  SELECT DISTINCT customer_key FROM vw_order_exceptions
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
ORDER BY has_order_payment_exception DESC, n.negative_ticket_count DESC, n.customer_key;
