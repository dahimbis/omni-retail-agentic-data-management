# Input Data Pack

Files included:

- business_context.md: Scenario and goal.
- customers.csv: Raw customer master data with duplicates and inconsistent fields.
- products.csv: Product master data with active/inactive product indicators.
- orders.csv: Raw order transactions with mixed timestamp formats and intentional quality issues.
- payments.csv: Payment records with mismatches and orphan examples.
- support_tickets.jsonl: Semi-structured customer support tickets.
- sttm_target_mapping.csv: Source-to-target mapping guidance for curated tables.
- data_quality_rules.csv: Suggested validation rules.
- expected_business_questions.md: Questions the solution should answer.

Recommended local stack: Python 3.10+, DuckDB or SQLite, pandas or polars, pytest optional.
