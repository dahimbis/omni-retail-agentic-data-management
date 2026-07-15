# Approach

## Goal

Build a small local OmniRetail data-management solution that turns messy operational extracts into curated, queryable tables, surfaces exceptions with remediation guidance, and answers the five business questions from the cleaned model.

## Architecture

1. **Ingest** (`src/ingest.py`) — load all `input_data` files into DuckDB staging tables with minimal casting.
2. **Transform** (`src/transform.py`) — apply STTM rules into `dim_*` / `fact_*` plus intermediate tables used by DQ.
3. **Quality** (`src/quality_checks.py`) — evaluate DQ001–DQ012 (+ DQ013 inactive products) into `dq_results` and `dq_exception_report`.
4. **Reporting** (`src/reporting.py`) — write the three required output artifacts; business answers come from `sql/business_questions.sql`.

## Curated model decisions

| Object | Decision |
|--------|----------|
| `dim_customer` | Dedupe on `customer_id`; keep earliest signup then highest completeness; set `duplicate_resolution_flag` when a sibling row was dropped. Fuzzy phone overlaps are informational only (not merged). |
| Country/state | Map USA/US/United States → `USA`; map full state names → 2-letter codes. |
| `fact_order` | Curated fact keeps valid customer+product FKs only. Intermediate `int_order` keeps invalid-FK rows for exception inventory. Adds `calculated_order_amount` and `order_amount_variance`. |
| `fact_payment` / tickets | Orphans / invalid customers excluded from curated facts and recorded in exceptions. |
| Revenue metrics | Completed revenue excludes `quantity <= 0` so DQ007 failures do not distort totals. |

## Assumptions

- Exact ID duplicates are resolved automatically; near-duplicates (shared phone, e.g. C001/C019) stay separate until MDM confirms a merge.
- “Completed revenue” means `order_status = completed` and positive quantity, on curated fact rows.
- Settled vs completed order total comparison uses gross order amount (source `order_total`), not recalculated amount, so DQ008 (price math) and DQ010 (payment match) stay distinct.
- Missing payments for completed orders are reported even though that rule is an extension of DQ010 / business Q3.

## Tradeoffs

- Python drives transforms for mixed timestamps and readability; SQL files document the target model and business answers.
- Invalid orders are excluded from curated facts (cleaner analytics) but remain in intermediate tables and the exception report (auditable).
- Kept dependencies minimal: DuckDB, pandas, pytest.

## Known limitations / next improvements

- No streaming ingest and no auto-detect of new files. The pipeline only reads what is already in `input_data/` when `python -m src.pipeline` is run.
- No incremental (delta-only) loads. Each run does a full refresh and rebuilds `outputs/curated.duckdb` and the report files.
- No SCD Type 2 history for slowly changing customer attributes.
- State standardization covers US names/codes only.
- Fuzzy matching is phone-based only; email or name similarity could be added later.
- A small dashboard over `exceptions.csv` could help business review in a later version.

**How new data is expected to land today:** update the extract files in `input_data/`, rerun the pipeline, then review the new outputs. That keeps the take-home simple and fully reproducible.

## Verification performed

- Re-ran `python -m src.pipeline` end-to-end from a clean DuckDB file.
- Confirmed intentional defect catches: C006/O1018 dedupe, O1019/O1020 bad FKs, O1021 payment mismatch, O1024 missing payment, O1030 negative qty, T010 bad timestamp, P011 inactive product on O1015.
- Ran `pytest tests/ -q` for row counts, referential integrity, parsing, and DQ010.
