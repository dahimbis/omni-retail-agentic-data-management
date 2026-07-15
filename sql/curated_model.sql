-- Curated model documentation / reference DDL for OmniRetail.
-- Physical tables are built by src/transform.py into outputs/curated.duckdb.
-- Column set follows Take-home-exercise_v1 suggested target model.

-- dim_customer
-- customer_key, full_name, email, phone, standard_country, standard_state,
-- signup_date, loyalty_tier, duplicate_resolution_flag

CREATE TABLE IF NOT EXISTS dim_customer (
  customer_key VARCHAR PRIMARY KEY,
  full_name VARCHAR,
  email VARCHAR,
  phone VARCHAR,
  standard_country VARCHAR,
  standard_state VARCHAR,
  signup_date DATE,
  loyalty_tier VARCHAR,
  duplicate_resolution_flag BOOLEAN
);

-- dim_product
CREATE TABLE IF NOT EXISTS dim_product (
  product_key VARCHAR PRIMARY KEY,
  product_name VARCHAR,
  category VARCHAR,
  unit_price DECIMAL(18, 2),
  active_flag VARCHAR
);

-- fact_order (valid FK rows only in curated fact)
CREATE TABLE IF NOT EXISTS fact_order (
  order_key VARCHAR PRIMARY KEY,
  customer_key VARCHAR,
  product_key VARCHAR,
  order_date DATE,
  quantity INTEGER,
  order_status VARCHAR,
  shipping_state VARCHAR,
  gross_order_amount DECIMAL(18, 2),
  calculated_order_amount DECIMAL(18, 2),
  order_amount_variance DECIMAL(18, 2)
);

-- fact_payment
CREATE TABLE IF NOT EXISTS fact_payment (
  payment_key VARCHAR PRIMARY KEY,
  order_key VARCHAR,
  payment_date DATE,
  payment_method VARCHAR,
  payment_status VARCHAR,
  payment_amount DECIMAL(18, 2)
);

-- fact_customer_issue
CREATE TABLE IF NOT EXISTS fact_customer_issue (
  ticket_id VARCHAR PRIMARY KEY,
  customer_key VARCHAR,
  created_date DATE,
  channel VARCHAR,
  issue_category VARCHAR,
  sentiment VARCHAR,
  description VARCHAR
);

-- dq_exception_report
CREATE TABLE IF NOT EXISTS dq_exception_report (
  rule_id VARCHAR,
  dataset VARCHAR,
  record_key VARCHAR,
  severity VARCHAR,
  issue_description VARCHAR,
  suggested_action VARCHAR
);
