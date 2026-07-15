# Approach

## Goal

Build a small local OmniRetail data-management solution that turns operational extracts containing known quality issues into curated, queryable tables, surfaces exceptions with remediation guidance, and answers the five business questions from the cleaned model.

## Architecture

1. **Ingest** (`src/ingest.py`) - load all `input_data` files into DuckDB staging tables with minimal casting.
2. **Transform** (`src/transform.py`) - apply STTM rules into `dim_*` / `fact_*` plus intermediate tables used by DQ.
3. **Quality** (`src/quality_checks.py`) - evaluate DQ001 to DQ016 into `dq_results` and `dq_exception_report`. DQ013 to DQ016 extend the provided reference rules for inactive products, missing payments, quarantined-order payments, and payment-key uniqueness.
4. **Reporting** (`src/reporting.py`) - write Markdown/CSV outputs and generated charts; business answers come from `sql/business_questions.sql`.

## Curated model decisions

| Object | Decision |
|--------|----------|
| `dim_customer` | Remove duplicate `customer_id` rows; keep earliest signup then highest completeness; set `duplicate_resolution_flag` when a sibling row was dropped. Shared phones are flagged only (not merged). |
| Customer email | Lowercase supplied values and flag missing or invalid email. The STTM explicitly requires missing-email exceptions, resolving the shorter DQ002 wording. |
| Country/state | Map USA/US/United States to `USA`; map full state names to 2-letter codes. |
| `fact_order` | Curated fact keeps valid customer+product IDs only. Audit table `int_order` keeps invalid-ID rows for exception inventory. Adds calculated amount, variance, and `is_revenue_eligible`. |
| `fact_payment` / tickets | Invalid references are excluded from curated facts and retained in audit tables. Payments linked to quarantined orders are explicitly flagged. Tickets with bad timestamps remain available with a null curated date and a DQ exception. |
| Revenue metrics | `is_revenue_eligible` requires completed status, valid keys, a parsed date, and positive quantity. Payment and inactive-product exceptions remain visible but do not silently change the requested order-revenue definition. |

## Assumptions

- Exact ID duplicates are resolved automatically; near-duplicates (shared phone, e.g. C001/C019) stay separate until MDM confirms a merge.
- C019 is not automatically merged into C001 because C016 shares the same phone number. Name and phone similarity are surfaced as evidence, not treated as authoritative identity resolution.
- "Completed revenue" means `is_revenue_eligible = true` on curated fact rows.
- Settled vs completed order total comparison uses gross order amount (source `order_total`), not recalculated amount, so DQ008 (price math) and DQ010 (payment match) stay distinct.
- Missing payments for completed orders are reported as DQ014, an explicit extension of DQ010 and business question 3.

## Tradeoffs

- Python drives transforms for mixed timestamps and readability; SQL files document the target model and business answers.
- `sttm_target_mapping.csv` and `data_quality_rules.csv` are reference specifications. The current implementation is intentionally explicit Python/SQL, not a metadata-driven rules engine.
- Invalid orders are excluded from curated facts (cleaner analytics) but remain in intermediate tables and the exception report (auditable).
- Kept dependencies minimal: DuckDB, pandas, matplotlib, pytest.
- `requirements.txt` communicates supported minimums; `requirements-lock.txt` records the exact versions used for final verification.
- Reporting writes Markdown tables plus generated bar charts for key business views.

## Known limitations / next improvements

- No streaming ingest and no auto-detect of new files. The pipeline only reads what is already in `input_data/` when `python -m src.pipeline` is run.
- No incremental (delta-only) loads. Each run does a full refresh and rebuilds `outputs/curated.duckdb` and the report files.
- No SCD Type 2 history for slowly changing customer attributes.
- State standardization covers US names/codes only.
- Fuzzy matching is phone-based only; email or name similarity could be added later.
- A small dashboard over `exceptions.csv` could help business review in a later version.

**How new data is expected to land today:** update the extract files in `input_data/`, rerun the pipeline, then review the new outputs. That keeps the take-home simple and fully reproducible.

## Final audit fixes

The final review led to concrete hardening work:

1. Payments PMT019 and PMT020 remain visible in `int_payment` and are flagged by DQ015.
2. Order-health categories are mutually exclusive: completed orders clear vs completed orders requiring review.
3. Transform events that already have a DQ equivalent are excluded from the final exception report, preventing duplicate counts.
4. Missing payments are registered as DQ014, and payment-key uniqueness is checked by DQ016.
5. Report generation writes only under `outputs/` and no longer modifies `README.md`.
6. Revenue eligibility and Q3/Q5 exception logic are each defined once and reused.
7. Business query tie-breaking is deterministic, and Q4 explicitly uses order shipping state.
8. Automated regression tests cover Q1 to Q5, Q5 customer details, email validation, expected defect keys, schemas, reconciliation, and generated reports.
9. A final cross-solution reconciliation restored the C004 missing-email exception required by the STTM and documented why April revenue, Q4 geography, and Q5 overlap can differ under other definitions.

## Verification performed

- Re-ran `python -m src.pipeline` end-to-end from a clean DuckDB file.
- Confirmed intentional defect catches: C006/O1018 duplicate IDs, O1019/O1020 bad IDs, PMT019/PMT020 quarantined-order payments, O1021 payment mismatch, O1024 missing payment, O1030 negative quantity, T010 bad timestamp, and P011 inactive product on O1015.
- Ran `pytest tests/ -q`: 10 tests passed, covering reconciliation, references, schemas, all five business answers, expected defect keys, email validation, and generated report files.
- Confirmed charts regenerate under `outputs/charts/` for Q1, Q2, Q4, and DQ severity.
