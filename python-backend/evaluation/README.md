# AI SQL Assistant — Dedicated Evaluation & Benchmarking Suite

This directory contains the automated evaluation and benchmarking framework for the **AI SQL Assistant** project (InsightFlow).

It evaluates the real performance, reliability, security, and edge-case handling of the application pipeline without fabricating metrics or hard-coding fake results.

---

## 1. Overview of Test Categories

The suite runs **50 comprehensive test cases** across five critical dimensions:

| Category | Count | Focus |
|---|---|---|
| **A. SQL Generation Accuracy** | 30 | Evaluates natural language understanding, aggregation, grouping, date manipulation, complex filters, and business analysis against the `retail_sales` schema. |
| **B. Destructive SQL / Security** | 10 | Validates defense-in-depth against DDL/DML attacks (`DELETE`, `DROP`, `TRUNCATE`, `UPDATE`, `INSERT`, `ALTER`, `CREATE`, `GRANT`, `REVOKE`, and prompt injection bypasses). Destructive SQL is **never executed**. |
| **C. Ambiguous Questions** | 5 | Measures how the assistant navigates subjective or underspecified queries (e.g., "What are the best products?"). Tracks explicit assumptions, clarification requests, and unsupported assumptions. |
| **D. Invalid Schema Requests** | 5 | Tests hallucination resistance when users ask for nonexistent tables, columns, or metrics. |
| **E. Response Latency** | 30 | Measures real end-to-end wall-clock latency (ms) across all 30 SQL test cases, reporting Average, Median, P95, Min, and Max. |

---

## 2. Directory Structure

```text
python-backend/evaluation/
├── __init__.py
├── config.py              # Central evaluation configuration, paths, schema definitions
├── test_cases.py          # Definitions for all 50 evaluation test cases
├── metrics.py             # Accuracy comparison, security classifier, latency stats
├── run_evaluation.py      # Main CLI orchestrator and report generator
├── results/
│   ├── latest_results.json        # Machine-readable output of most recent run
│   └── evaluation_<timestamp>.json # Timestamped historical runs
└── README.md              # Documentation and methodology
```

---

## 3. Configuration & Prerequisites

1. Ensure the Python virtual environment has the required dependencies:
   ```bash
   cd python-backend
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Verify that `GEMINI_API_KEY` is set in `python-backend/.env`.
3. Database credentials (`host`, `port`, `user`, `password`, `dbname`) in `.env`:
   - If PostgreSQL is online, the suite executes queries and verifies result set matches.
   - If PostgreSQL is offline (e.g. paused free-tier instance), the suite detects the connection outage, validates generated SQL structure and safety, measures real LLM response latency, reports the failure faithfully, and marks DB execution comparisons as `NOT RUN` in accordance with Rule 6.

---

## 4. How to Run the Evaluation

From the `python-backend` directory:

```bash
python -m evaluation.run_evaluation
```

Or from the project root:

```bash
cd python-backend && python evaluation/run_evaluation.py
```

---

## 5. Evaluation Methodology

### SQL Generation Accuracy
- For each test case, the user prompt is sent through `process_question(question, schema=schema)`.
- The returned SQL is independently validated for PostgreSQL syntax compliance and single-table constraints.
- When PostgreSQL is active, the reference SQL query is executed directly to provide ground-truth rows.
- Actual vs. reference rows are compared using `compare_result_rows()` with:
  - Numeric floating-point tolerance ($\pm 0.01$).
  - Row order insensitivity (unless ordering was explicitly part of the prompt).
  - Column alias tolerance for single-value aggregates.

### Destructive SQL / Security Defense
- Tests send prompts attempting mutating operations (`DROP`, `DELETE`, etc.).
- The system checks both the application's response and generated SQL.
- **Strict safety rule**: Destructive statements are **never executed** against PostgreSQL.
- Queries are classified as `BLOCKED` if rejected by validation or if the model adhered to read-only constraints.

### Response Latency
- Measured using high-resolution timers (`time.perf_counter()`) starting immediately before `process_question()` and ending when the final response dictionary is produced.
- Includes LLM generation time, prompt serialization, SQL validation, and database round-trip.

---

## 6. Output & Results

Every evaluation run produces:
1. **Terminal Report**: Clean, section-by-section breakdown with individual test results, aggregate statistics, and resume-ready summaries.
2. **Machine-Readable JSON**: Saved automatically to:
   - `evaluation/results/latest_results.json`
   - `evaluation/results/evaluation_<YYYY-MM-DD_HH-MM-SS>.json`

No secrets, passwords, or API keys are stored in the results.

---

## 7. Limitations & Scope

- **Implementation Specific**: This benchmark evaluates this specific application's architecture (prompt design, Gemini 3.1 Flash Lite, LangChain integration, and custom SQL validator), not the raw capability of the underlying LLM.
- **Single-Table Scope**: The benchmark is designed around the project's analytical dataset (`retail_sales`). Tests reflect realistic retail analytics workflows.

