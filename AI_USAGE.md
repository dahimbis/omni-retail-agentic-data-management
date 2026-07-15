# AI Usage

## Tools used

- **Cursor (Auto agent router)** - primary agentic coding assistant for planning, implementation, debugging, docs, and report polish.
- **Claude Code** - used for reviewing the solution (structure, logic, and submission completeness).
- **Codex** - used as an additional review / cross-check on implementation and documentation.

## How the tool was steered

1. **Problem decomposition** - Asked Cursor to inventory the candidate pack, read business context / STTM / DQ rules / expected questions, and produce an implementation plan before coding.
2. **Constraint prompts** - Required local-only Python + DuckDB, no paid cloud services, reproducible single-command run, and answers generated from the curated model (not hard-coded).
3. **Structure realignment** - After discovering `Take-home-exercise_v1.docx` lived outside the original Cursor workspace, asked Cursor to restructure to the recommended repository layout, enrich the suggested target model columns, split outputs, and add mandatory `AI_USAGE.md` / `APPROACH.md`.
4. **Verification loop** - Ran the pipeline and pytest locally; inspected exception keys (e.g. O1021/PMT021, O1024, T010) against known intentional defects in the input files.

## Important prompts / tasks given

- Inspect `input_data` and draft a stepwise data-management plan.
- Implement ingest -> transform -> DQ -> analytics with DuckDB.
- Catch duplicate customers/orders, mixed timestamps, invalid FKs, payment mismatches, suspicious quantities.
- Re-read `Take-home-exercise_v1` and match the recommended structure exactly.
- Add SQL artifacts, split report outputs, exception `suggested_action`, inactive-product check, and submission docs.
- Add generated stakeholder charts and full business question titles in the reports.

## Generated artifacts accepted

- Pipeline modules under `src/` (`pipeline`, `ingest`, `transform`, `quality_checks`, `reporting`).
- `sql/curated_model.sql` and `sql/business_questions.sql`.
- Pytest suite in `tests/test_quality_checks.py`.
- README / APPROACH drafts (edited for accuracy).
- Generated PNG charts under `outputs/charts/`.

## Rejected or corrected tool output

- Initial build used an invented folder layout (`omni_retail_dm/`) because the `.docx` brief was not in the workspace - **rejected** for submission packaging; replaced with `omni-retail-agentic-data-management/` per section 8 of the brief.
- Early curated schema was STTM-minimal (missing phone, variance, suggested_action) - **extended** to the suggested target model in the brief.
- Combined single Markdown report - **split** into `data_quality_report.md`, `exceptions.csv`, and `business_answers.md`.
- Pandas `to_markdown` dependency - **replaced** with a small local Markdown table formatter.
- Brief revenue queries originally included negative-quantity completed orders - **filtered** `quantity > 0` after manual check of O1030.

## Manual judgment / verification

- Confirmed row-count story: 20 raw customers -> 19 `dim_customer`; 31 raw orders -> 28 curated `fact_order` (after removing duplicate IDs and invalid keys from trusted facts).
- Spot-checked O1021: order_total 50 vs qty x price 44 and settled payment 44 (DQ008 + DQ010).
- Spot-checked O1024 missing payment and PMT029 orphan order O9999.
- Confirmed negative-ticket overlap is computed from joins, not narrative text.
- Reviewed exception severities and suggested actions for business readability.

## What we did in follow-up iterations (this submission polish)

After the core pipeline worked, we continued steering Cursor to harden the submission and validate answers:

1. **Mapped the solution to `Take-home-exercise_v1`** - Confirmed required deliverables (folder layout, curated columns, DQ + exceptions, five business questions, README / APPROACH / AI_USAGE).
2. **Improved README for reviewers** - Added a simple pipeline flowchart, clearer wording, and operational notes for new data.
3. **Independently re-checked business answers** - Recomputed Q1 to Q5 from `curated.duckdb` and raw tickets. Confirmed Q3 defect keys (O1019, O1020, O1021, O1024, O1030) and Q5 overlap rate 0.5.
4. **Resolved competing Q1 definitions** - Chose curated completed revenue with quantity > 0: Mar `440.70`, Apr `356.97`, May `446.20`. Defective rows stay in exceptions / Q3.
5. **Submission packaging** - Prepared GitHub-oriented contents; noted shared-PC credential issues for push.
6. **Stakeholder report polish** - Added generated matplotlib charts for Q1, Q2, Q4, and DQ severity, with full business question titles and no em dashes in docs/reports.
7. **Final review** - Ran separate read-only reviews of pipeline logic, tests, outputs, and documentation. The reviews confirmed the five business answers and identified follow-up work before final submission:
   - Preserve and flag payments linked to orders excluded from the trusted order table (PMT019 and PMT020).
   - Clarify that revenue-eligible orders and exception orders can overlap.
   - Avoid counting the same source defect twice under transform and DQ rule IDs.
   - Stop report generation from rewriting `README.md`.
   - Add deterministic sorting for tied customer totals.
   - Add automated regression tests for Q1 to Q5, report files, and implemented DQ rules.

Net result: a local, reproducible OmniRetail data-management solution with verified analytics and clear judgment on completed revenue.

## What I would improve next

- More explicit prompt checkpoints before each major module (ingest, transform, DQ) with reviewer-style acceptance criteria.
- Add a short manual reconciliation worksheet in outputs (source totals vs curated completed revenue).
- Expand fuzzy-match tests for C001/C019 phone sharing beyond informational flags.
