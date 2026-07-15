# AI Usage

## Tool used

**Cursor** (agentic coding assistant) with local project execution.

## How the tool was steered

1. **Problem decomposition** — Asked Cursor to inventory the candidate pack, read business context / STTM / DQ rules / expected questions, and produce an implementation plan before coding.
2. **Constraint prompts** — Required local-only Python + DuckDB, no paid cloud services, reproducible single-command run, and answers generated from the curated model (not hard-coded).
3. **Structure realignment** — After discovering `Take-home-exercise_v1.docx` lived outside the original Cursor workspace, asked Cursor to restructure to the **recommended repository layout**, enrich the suggested target model columns, split outputs, and add mandatory `AI_USAGE.md` / `APPROACH.md`.
4. **Verification loop** — Ran the pipeline and pytest locally; inspected exception keys (e.g. O1021/PMT021, O1024, T010) against known intentional defects in the input files.

## Important prompts / tasks given

- Inspect `input_data` and draft a stepwise data-management plan.
- Implement ingest → transform → DQ → analytics with DuckDB.
- Catch duplicate customers/orders, mixed timestamps, invalid FKs, payment mismatches, suspicious quantities.
- Re-read `Take-home-exercise_v1` and **match the recommended structure exactly**.
- Add SQL artifacts, split report outputs, exception `suggested_action`, inactive-product check, and submission docs.

## Generated artifacts accepted

- Pipeline modules under `src/` (`pipeline`, `ingest`, `transform`, `quality_checks`, `reporting`).
- `sql/curated_model.sql` and `sql/business_questions.sql`.
- Pytest suite in `tests/test_quality_checks.py`.
- README / APPROACH drafts (edited for accuracy).

## Rejected or corrected tool output

- Initial build used an invented folder layout (`omni_retail_dm/`) because the `.docx` brief was not in the workspace — **rejected** for submission packaging; replaced with `omni-retail-agentic-data-management/` per section 8 of the brief.
- Early curated schema was STTM-minimal (missing phone, variance, suggested_action) — **extended** to the suggested target model in the brief.
- Combined single Markdown report — **split** into `data_quality_report.md`, `exceptions.csv`, and `business_answers.md`.
- Pandas `to_markdown` dependency — **replaced** with a small local Markdown table formatter.
- Brief revenue queries originally included negative-quantity completed orders — **filtered** `quantity > 0` after manual check of O1030.

## Manual judgment / verification

- Confirmed row-count story: 20 raw customers → 19 `dim_customer`; 31 raw orders → 28 curated `fact_order` (after dedupe + FK quarantine).
- Spot-checked O1021: order_total 50 vs qty×price 44 and settled payment 44 (DQ008 + DQ010).
- Spot-checked O1024 missing payment and PMT029 orphan order O9999.
- Confirmed negative-ticket overlap is computed from joins, not narrative text.
- Reviewed exception severities and suggested actions for business readability.

## What we did in follow-up iterations (this submission polish)

After the core pipeline worked, we continued steering Cursor to harden the submission and validate answers:

1. **Mapped the solution to `Take-home-exercise_v1`** — Confirmed every required deliverable (recommended folder layout, suggested curated columns, DQ + exceptions with suggested actions, five business questions, README / APPROACH / AI_USAGE).
2. **Improved README for reviewers** — Added a Mermaid pipeline flowchart, a “how this follows the brief” table, and a short build-iteration history so the agentic process is visible without reading the chat.
3. **Independently re-checked business answers** — Recomputed Q1–Q5 from `curated.duckdb` and raw tickets (not trusting the report blindly). Confirmed Q3 defect keys (O1019, O1020, O1021, O1024, O1030) and Q5 overlap rate 0.5.
4. **Resolved competing Q1 definitions** — Compared alternate revenue rules (include bad FKs, include negative qty O1030, use qty×price). Chose and documented the curated definition: **completed + valid FKs + quantity > 0 + sum(order_total)** → Mar `440.70`, Apr `356.97`, May `446.20`. Defective rows stay in the exception report / Q3 instead of distorting revenue.
5. **Submission packaging** — Prepared the GitHub-oriented repo contents (required files only; excluded optional `verify_answers.py` and generated `curated.duckdb` from the intended push set). Auth/push on a shared machine used browser/ZIP fallback guidance when another user’s cached Git credentials blocked `git push`.

Net result: a local, reproducible OmniRetail data-management solution with verified analytics and explicit judgment on how completed revenue is defined.

## What I would improve next

- More explicit prompt checkpoints before each major module (ingest, transform, DQ) with reviewer-style acceptance criteria.
- Add a short manual reconciliation worksheet in outputs (source totals vs curated completed revenue).
- Expand fuzzy-match tests for C001/C019 phone sharing beyond informational flags.
