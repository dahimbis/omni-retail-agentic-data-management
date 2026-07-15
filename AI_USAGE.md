# AI Usage

## Tools I used

- **Cursor (Auto agent router)** was my primary agentic coding assistant for planning, implementation, debugging, tests, documentation, and report presentation.
- **Claude Code** was used to review structure, transformation logic, and submission completeness.
- **Codex** was used as an additional cross-check of implementation and documentation.

## Representative prompts I gave

The following excerpts are lightly corrected for spelling but preserve the tasks and constraints I gave the tools:

1. **Starting and planning:** “I was given this assessment and am not sure where to start. Inspect the input files and create a plan.”
2. **Implementation:** “Implement the plan as specified. Do not stop until all tasks are completed.”
3. **Requirement alignment:** “Read `Take-home-exercise_v1` and follow the recommended repository structure.”
4. **Stakeholder reporting:** “Add generated charts where useful, use the full business-question titles, and keep the tables easy for stakeholders to follow.”
5. **Operational behavior:** “Document what happens when new data is added, including that there is no streaming, automatic detection, or incremental loading.”
6. **FDE-focused review:** “Fix the audit issues while following the project requirements and remember this is for an FDE role.”
7. **Independent reconciliation:** “Compare these independently generated results and determine which definitions are correct or wrong.”

These prompts show how I moved from problem decomposition to implementation, review, correction, and verification rather than accepting the first generated answer.

## How I steered the tools

1. I asked Cursor to inventory the candidate pack, read the business context, STTM, DQ rules, and expected questions, then propose an implementation plan before coding.
2. I constrained the implementation to local Python, SQL, and DuckDB with no cloud services or paid APIs.
3. I required a reproducible pipeline command and generated answers rather than hard-coded totals.
4. I asked the tools to re-read the full exercise when the first repository layout did not match the recommended structure.
5. I repeatedly asked for clearer wording when terms such as “after dedupe” or “fix rule if needed” were not understandable to a business reviewer.
6. I requested a final audit from the perspective of an FDE who must explain technical decisions to customers and stakeholders.

## Agent-generated work I accepted

- Modular pipeline code under `src/` for ingestion, transformation, quality checks, reporting, and orchestration.
- SQL artifacts under `sql/` for the curated model and five business questions.
- Pytest coverage for transformations, reconciliation, expected defects, business answers, schemas, and generated reports.
- Drafts of `README.md`, `APPROACH.md`, and this AI usage record, which I reviewed and corrected for accuracy.
- Generated Markdown reports, CSV exceptions, DuckDB output, and stakeholder charts.

## Outputs I rejected or corrected

- The first build used an invented `omni_retail_dm/` layout. I rejected it and required the structure from section 8 of the exercise.
- The first curated schema was too narrow and omitted fields such as phone, amount variance, and `suggested_action`. I required the fuller target model.
- A single combined report was replaced with separate quality, exceptions, analytics, and reconciliation outputs.
- A `pandas.to_markdown` dependency was replaced with a small local formatter to keep dependencies minimal.
- Revenue initially included completed orders with non-positive quantity. I excluded O1030 after checking the source record and documenting the revenue definition.
- Report code originally rewrote `README.md`. I removed that side effect so generated files remain under `outputs/`.
- Transform and DQ exceptions initially counted some source defects twice. I kept one final exception representation for each duplicated semantic issue.
- DQ002 temporarily treated a missing email as acceptable because the supplied rule said “when available.” I corrected it after re-checking the STTM instruction to flag missing email, so C004 is now reported.

## Failed attempts and debugging

- A shell command using Unix heredoc syntax failed in PowerShell. I changed the execution approach to Windows-compatible commands and temporary scripts.
- README character encoding was damaged during punctuation cleanup. I rewrote the affected content with UTF-8-safe text.
- GitHub push attempts exposed repository and shared-machine credential problems. I kept those environment issues separate from pipeline correctness and verified the project locally before submission.
- An expanded regression test initially expected the wrong invalid-ticket key. I checked the raw JSONL, corrected the expected key from T012 to T005, and reran the suite.

## Manual judgment and verification

- I reconciled 20 raw customers to 19 curated customers after resolving the repeated C006 ID.
- I reconciled 31 raw order rows to 30 distinct order IDs and 28 curated `fact_order` rows after removing O1018 and quarantining O1019/O1020.
- I spot-checked O1021: source total `$50.00`, calculated amount `$44.00`, and settled payment `$44.00`, producing separate order-arithmetic and payment-mismatch findings.
- I verified O1024 has no settled payment, PMT029 references nonexistent O9999, and T010 has an invalid timestamp.
- I confirmed April's `$37.98` alternate total comes from adding quarantined O1019 and O1020 to curated revenue.
- I confirmed Q4 uses order shipping state and Q5 consistently uses the same exception definition as Q3.
- I ran the pipeline and pytest after the final corrections and inspected the generated reports rather than trusting generated narrative text.

## Follow-up iterations

1. Realigned the repository to the required submission structure.
2. Added the complete curated columns and intermediate audit tables.
3. Added DQ013 to DQ016 for inactive products, missing payments, quarantined-order payments, and payment-key uniqueness.
4. Preserved PMT019/PMT020 in the audit layer instead of silently dropping them.
5. Centralized Q3 and Q5 exception logic in `vw_order_exceptions`.
6. Added deterministic tie-breaking and explicit revenue eligibility.
7. Added input schema validation, generated charts, and regression tests.
8. Reconciled independently produced results and documented why alternate totals differ.

## What I would improve next

- Add explicit acceptance criteria before each major agent-generated module.
- Introduce historical customer tracking if the exercise expanded beyond a full-refresh take-home.
- Expand entity-resolution evidence beyond phone and name before automatically merging different customer IDs.

The final result is AI-assisted but not a black box: generated work was reviewed against source records, reconciled, tested, corrected, and documented.
