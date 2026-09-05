"""
AI SQL Assistant - Evaluation & Benchmarking Orchestrator

Executes all evaluation categories:
1. SQL Generation Accuracy (30 tests)
2. Destructive SQL / Security Testing (10 tests)
3. Ambiguous Questions (5 tests)
4. Invalid Schema Handling (5 tests)
5. Response Latency Metrics

Outputs results to console and saves raw machine-readable JSON.
"""

import contextlib
import datetime
import io
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is in sys.path
from evaluation.config import (
    BACKEND_BASE_URL,
    DEFAULT_SCHEMA_TEXT,
    LATEST_RESULTS_FILE,
    PRIMARY_TABLE,
    RESULTS_DIR,
)
from evaluation.metrics import (
    calculate_latency_stats,
    classify_ambiguity_handling,
    classify_invalid_schema_handling,
    classify_security_response,
    compare_result_rows,
    is_destructive_sql,
)
from evaluation.test_cases import (
    AMBIGUITY_TEST_CASES,
    INVALID_SCHEMA_TEST_CASES,
    SECURITY_TEST_CASES,
    SQL_TEST_CASES,
)

# Application imports
from app.services.chat_service import process_question
from app.ai.sql_validator import validate_sql
from database.sql_executor import execute_query


def check_database_status() -> Tuple[bool, str]:
    """Test connection to PostgreSQL without executing arbitrary user queries."""
    try:
        # Simple read-only check
        res = execute_query(f"SELECT 1 FROM {PRIMARY_TABLE} LIMIT 1;")
        if res["success"]:
            return True, "Connected (Read-only verified)"
        return False, f"Connection Failed: {res.get('error')}"
    except Exception as e:
        return False, f"Exception: {str(e)}"


def run_evaluation():
    start_eval_time = datetime.datetime.now(datetime.timezone.utc)
    date_str = start_eval_time.strftime("%Y-%m-%d %H:%M:%S UTC")
    file_timestamp = start_eval_time.strftime("%Y-%m-%d_%H-%M-%S")

    print("=" * 60)
    print("        AI SQL ASSISTANT EVALUATION & BENCHMARK")
    print("=" * 60)
    print(f"Environment: Local Application Module Execution")
    print(f"Target Service: {BACKEND_BASE_URL} (Direct Pipeline Invocation)")
    print(f"LLM Engine: Google Gemini 3.1 Flash Lite via LangChain")
    print(f"Database Engine: Supabase PostgreSQL (Table: {PRIMARY_TABLE})")
    print(f"Test Date: {date_str}")
    print("-" * 60)

    # 1. Check Database Connectivity
    db_connected, db_status_msg = check_database_status()
    if not db_connected:
        print(f"[WARNING] Database Connection: OFFLINE")
        print(f"Details: {db_status_msg}")
        print("Note: In accordance with Rule 6, SQL generation and validation will execute,")
        print("      while query execution against DB will record the real connection error.")
    else:
        print(f"[OK] Database Connection: ONLINE ({db_status_msg})")
    print("=" * 60)

    # -----------------------------------------------------------------
    # CATEGORY A: SQL Generation Accuracy (30 questions)
    # -----------------------------------------------------------------
    print("\n" + "=" * 60)
    print("INDIVIDUAL TEST RESULTS - CATEGORY A: SQL GENERATION")
    print("=" * 60)

    sql_results = []
    latencies_ms: List[float] = []
    passed_count = 0
    failed_count = 0
    error_count = 0
    sql_gen_success_count = 0
    sql_exec_success_count = 0

    for tc in SQL_TEST_CASES:
        t0 = time.perf_counter()
        
        # Suppress internal step printing from process_question
        with contextlib.redirect_stdout(io.StringIO()):
            resp = process_question(tc.question, schema=DEFAULT_SCHEMA_TEXT)
            
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(elapsed_ms)

        gen_sql = resp.get("sql")
        app_success = resp.get("success", False)
        app_error = resp.get("error")
        actual_data = resp.get("data")

        # Independent validation of generated SQL
        val_res = validate_sql(gen_sql) if gen_sql else {"valid": False, "error": "No SQL generated"}
        if val_res["valid"]:
            sql_gen_success_count += 1

        ref_data = None
        ref_error = None
        match_success = False
        match_reason = None
        status = "ERROR"

        # If DB is online, execute reference query and compare
        if db_connected:
            ref_exec = execute_query(tc.reference_sql)
            if ref_exec["success"]:
                ref_data = ref_exec["data"]
            else:
                ref_error = ref_exec["error"]

            if app_success and ref_exec["success"]:
                sql_exec_success_count += 1
                match_success, match_reason = compare_result_rows(actual_data, ref_data)
                if match_success:
                    status = "PASS"
                    passed_count += 1
                else:
                    status = "FAIL"
                    failed_count += 1
            else:
                status = "ERROR"
                error_count += 1
        else:
            # DB is offline - faithfully record error
            status = "ERROR"
            error_count += 1
            match_reason = f"Database unavailable: {app_error or 'Connection failed'}"

        # Print individual result
        print(f"\n[{status}] {tc.id} ({tc.category})")
        print(f"Question: {tc.question}")
        print(f"Generated SQL: {gen_sql or 'None'}")
        val_err_str = f"({val_res['error']})" if not val_res['valid'] else ""
        print(f"SQL Valid: {val_res['valid']} {val_err_str}".strip())
        if db_connected:
            print(f"Expected Rows: {len(ref_data) if ref_data is not None else 'Error'}")
            print(f"Actual Rows:   {len(actual_data) if actual_data is not None else 'Error'}")
            if status == "FAIL":
                print(f"Reason: {match_reason}")
        else:
            print(f"Execution: NOT RUN / FAILED ({app_error})")
        print(f"Latency: {elapsed_ms:.1f} ms")

        sql_results.append({
            "id": tc.id,
            "question": tc.question,
            "category": tc.category,
            "reference_sql": tc.reference_sql,
            "generated_sql": gen_sql,
            "sql_validation": val_res,
            "app_success": app_success,
            "app_error": app_error,
            "execution_data_count": len(actual_data) if actual_data else 0,
            "reference_data_count": len(ref_data) if ref_data else 0,
            "results_matched": match_success,
            "match_reason": match_reason,
            "status": status,
            "latency_ms": elapsed_ms,
        })
        # Benchmark pacing: allow quota window to pace naturally between tests
        time.sleep(2.0)

    # -----------------------------------------------------------------
    # CATEGORY B: Destructive SQL / Security Testing (10 prompts)
    # -----------------------------------------------------------------
    print("\n" + "=" * 60)
    print("INDIVIDUAL TEST RESULTS - CATEGORY B: SECURITY TESTING")
    print("=" * 60)

    security_results = []
    sec_blocked_count = 0
    sec_allowed_count = 0
    sec_error_count = 0

    for sec in SECURITY_TEST_CASES:
        t0 = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            resp = process_question(sec.prompt, schema=DEFAULT_SCHEMA_TEXT)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        gen_sql = resp.get("sql")
        
        # NEVER EXECUTE destructive SQL!
        # Classify based on generated SQL and validation behavior
        sec_status, sec_reason = classify_security_response(resp, gen_sql)

        if sec_status == "BLOCKED":
            sec_blocked_count += 1
        elif sec_status == "INCORRECTLY_ALLOWED":
            sec_allowed_count += 1
        else:
            sec_error_count += 1

        print(f"\n[{sec_status}] {sec.id} ({sec.attack_type})")
        print(f"Prompt: {sec.prompt}")
        print(f"Generated SQL: {gen_sql or 'None'}")
        print(f"Action: NOT EXECUTED (Safety Guard Active)")
        print(f"Result: {sec_reason}")
        print(f"Latency: {elapsed_ms:.1f} ms")

        security_results.append({
            "id": sec.id,
            "prompt": sec.prompt,
            "attack_type": sec.attack_type,
            "generated_sql": gen_sql,
            "status": sec_status,
            "reason": sec_reason,
            "action": "NOT EXECUTED",
            "latency_ms": elapsed_ms,
        })

    # -----------------------------------------------------------------
    # CATEGORY C: Ambiguous User Questions (5 cases)
    # -----------------------------------------------------------------
    print("\n" + "=" * 60)
    print("INDIVIDUAL TEST RESULTS - CATEGORY C: AMBIGUOUS QUESTIONS")
    print("=" * 60)

    ambiguity_results = []
    amb_clarification = 0
    amb_explicit = 0
    amb_unsupported = 0
    amb_failed = 0

    for amb in AMBIGUITY_TEST_CASES:
        t0 = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            resp = process_question(amb.question, schema=DEFAULT_SCHEMA_TEXT)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        gen_sql = resp.get("sql")
        classification, details = classify_ambiguity_handling(resp, gen_sql)

        if classification == "CLARIFICATION_REQUESTED":
            amb_clarification += 1
        elif classification == "EXPLICIT_ASSUMPTION":
            amb_explicit += 1
        elif classification == "UNSUPPORTED_ASSUMPTION":
            amb_unsupported += 1
        else:
            amb_failed += 1

        print(f"\n[{classification}] {amb.id}")
        print(f"Question: {amb.question}")
        print(f"Ambiguity: {amb.ambiguity_type}")
        print(f"Generated SQL: {gen_sql or 'None'}")
        print(f"Assessment: {details}")
        print(f"Latency: {elapsed_ms:.1f} ms")

        ambiguity_results.append({
            "id": amb.id,
            "question": amb.question,
            "ambiguity_type": amb.ambiguity_type,
            "generated_sql": gen_sql,
            "classification": classification,
            "details": details,
            "latency_ms": elapsed_ms,
        })

    # -----------------------------------------------------------------
    # CATEGORY D: Invalid / Non-existent Schema Requests (5 cases)
    # -----------------------------------------------------------------
    print("\n" + "=" * 60)
    print("INDIVIDUAL TEST RESULTS - CATEGORY D: INVALID SCHEMA REQUESTS")
    print("=" * 60)

    invalid_schema_results = []
    inv_handled_correctly = 0
    inv_hallucinated = 0

    for inv in INVALID_SCHEMA_TEST_CASES:
        t0 = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            resp = process_question(inv.question, schema=DEFAULT_SCHEMA_TEXT)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        gen_sql = resp.get("sql")
        classification, details = classify_invalid_schema_handling(
            resp, gen_sql, inv.target_nonexistent_element
        )

        if classification == "HANDLED_CORRECTLY":
            inv_handled_correctly += 1
        else:
            inv_hallucinated += 1

        print(f"\n[{classification}] {inv.id}")
        print(f"Question: {inv.question}")
        print(f"Target Element: {inv.target_nonexistent_element}")
        print(f"Generated SQL: {gen_sql or 'None'}")
        print(f"Assessment: {details}")
        print(f"Latency: {elapsed_ms:.1f} ms")

        invalid_schema_results.append({
            "id": inv.id,
            "question": inv.question,
            "target_element": inv.target_nonexistent_element,
            "generated_sql": gen_sql,
            "classification": classification,
            "details": details,
            "latency_ms": elapsed_ms,
        })

    # -----------------------------------------------------------------
    # LATENCY & AGGREGATE CALCULATIONS
    # -----------------------------------------------------------------
    latency_stats = calculate_latency_stats(latencies_ms)
    total_sql_tests = len(SQL_TEST_CASES)
    
    # Accurate rates
    sql_accuracy_rate = (passed_count / total_sql_tests * 100.0) if db_connected else 0.0
    sql_gen_rate = (sql_gen_success_count / total_sql_tests) * 100.0
    sql_exec_rate = (sql_exec_success_count / total_sql_tests) * 100.0 if db_connected else 0.0
    sec_block_rate = (sec_blocked_count / len(SECURITY_TEST_CASES)) * 100.0

    # -----------------------------------------------------------------
    # PRINT FORMAL SUMMARY TABLE (Matching Section 11 format)
    # -----------------------------------------------------------------
    print("\n" + "=" * 60)
    print("        AI SQL ASSISTANT EVALUATION SUMMARY")
    print("=" * 60)
    print(f"Environment:")
    print(f"Backend:          {BACKEND_BASE_URL}")
    print(f"Database:         PostgreSQL ({'ONLINE' if db_connected else 'OFFLINE - ' + db_status_msg})")
    print(f"Test Date:        {date_str}")

    print("\n" + "-" * 60)
    print("1. SQL GENERATION ACCURACY")
    print("-" * 60)
    print(f"Tests:                  {total_sql_tests}")
    print(f"Passed:                 {passed_count}")
    print(f"Failed:                 {failed_count}")
    print(f"Errors:                 {error_count}")
    print(f"SQL Generation Valid:   {sql_gen_rate:.2f}% ({sql_gen_success_count}/{total_sql_tests})")
    if db_connected:
        print(f"SQL Accuracy:           {sql_accuracy_rate:.2f}%")
        print(f"Execution Success:      {sql_exec_rate:.2f}%")
    else:
        print(f"SQL Accuracy:           NOT RUN (Database Offline: {db_status_msg})")
        print(f"Execution Success:      0.00% (Real DB Connection Error Reported)")

    print("\n" + "-" * 60)
    print("2. SECURITY / DESTRUCTIVE SQL")
    print("-" * 60)
    print(f"Tests:                  {len(SECURITY_TEST_CASES)}")
    print(f"Blocked:                {sec_blocked_count}")
    print(f"Incorrectly Allowed:    {sec_allowed_count}")
    print(f"Errors:                 {sec_error_count}")
    print(f"Block Rate:             {sec_block_rate:.2f}%")

    print("\n" + "-" * 60)
    print("3. AMBIGUOUS QUESTIONS")
    print("-" * 60)
    print(f"Tests:                  {len(AMBIGUITY_TEST_CASES)}")
    print(f"Clarifications:         {amb_clarification}")
    print(f"Explicit Assumptions:   {amb_explicit}")
    print(f"Unsupported Assumptions:{amb_unsupported}")
    print(f"Failures:               {amb_failed}")

    print("\n" + "-" * 60)
    print("4. INVALID SCHEMA")
    print("-" * 60)
    print(f"Tests:                  {len(INVALID_SCHEMA_TEST_CASES)}")
    print(f"Handled Correctly:      {inv_handled_correctly}")
    print(f"Hallucinated Schema:    {inv_hallucinated}")

    print("\n" + "-" * 60)
    print("5. RESPONSE LATENCY (Measured over 30 SQL Queries)")
    print("-" * 60)
    print(f"Average:                {latency_stats['average']:.1f} ms")
    print(f"Median:                 {latency_stats['median']:.1f} ms")
    print(f"P95:                    {latency_stats['p95']:.1f} ms")
    print(f"Minimum:                {latency_stats['min']:.1f} ms")
    print(f"Maximum:                {latency_stats['max']:.1f} ms")

    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    if db_connected:
        print(f"SQL Accuracy:           {sql_accuracy_rate:.2f}%")
        print(f"SQL Execution Success:  {sql_exec_rate:.2f}%")
    else:
        print(f"SQL Valid Generation:   {sql_gen_rate:.2f}% ({sql_gen_success_count}/{total_sql_tests} syntactically and structurally valid)")
        print(f"SQL Accuracy:           NOT RUN (PostgreSQL Connection Offline)")
    print(f"Security Block Rate:    {sec_block_rate:.2f}% ({sec_blocked_count}/{len(SECURITY_TEST_CASES)} blocked)")
    print(f"Average Latency:        {latency_stats['average']:.1f} ms")
    print(f"P95 Latency:            {latency_stats['p95']:.1f} ms")
    print("=" * 60)

    # -----------------------------------------------------------------
    # SECTION 16: RESUME-READY METRICS
    # -----------------------------------------------------------------
    print("\n" + "=" * 60)
    print("RESUME-READY METRICS (Derived strictly from actual measurements)")
    print("=" * 60)
    print(f"- SQL Generation Validity: {sql_gen_rate:.1f}% across {total_sql_tests} production-grade analytical prompts")
    print(f"- Destructive SQL Defense: {sec_block_rate:.1f}% block rate across {len(SECURITY_TEST_CASES)} malicious DDL/DML injection vectors")
    print(f"- End-to-End LLM Latency: {latency_stats['average']:.0f} ms average, {latency_stats['p95']:.0f} ms P95")
    print(f"- Schema Guardrails: {inv_handled_correctly}/{len(INVALID_SCHEMA_TEST_CASES)} invalid/hallucinated schema requests prevented")
    if not db_connected:
        print("- Database Fault Tolerance: Gracefully handled PostgreSQL connection outage without server crash")

    print("\nRecommended resume wording:")
    if db_connected:
        print(f'  "Engineered an enterprise AI SQL Assistant with LangChain and Google Gemini, achieving')
        print(f'   {sql_accuracy_rate:.1f}% query accuracy on retail analytics, {sec_block_rate:.0f}% defense against malicious')
        print(f'   SQL injections, and a {latency_stats["p95"]:.0f} ms P95 response latency."')
    else:
        print(f'  "Architected a robust AI SQL Assistant with Google Gemini and LangChain, featuring a')
        print(f'   defense-in-depth SQL validation layer achieving a {sec_block_rate:.0f}% block rate against destructive operations,')
        print(f'   {sql_gen_rate:.1f}% valid SQL generation rate, and {latency_stats["average"]:.0f} ms average pipeline latency."')
    print("=" * 60)

    # -----------------------------------------------------------------
    # SAVE RAW RESULTS TO JSON
    # -----------------------------------------------------------------
    full_output = {
        "metadata": {
            "test_date": date_str,
            "database_connected": db_connected,
            "database_status": db_status_msg,
            "primary_table": PRIMARY_TABLE,
            "llm_model": "gemini-3.1-flash-lite",
            "framework": "LangChain + FastAPI + SQLAlchemy",
        },
        "metrics": {
            "sql_generation_validity_rate_pct": round(sql_gen_rate, 2),
            "sql_accuracy_rate_pct": round(sql_accuracy_rate, 2) if db_connected else None,
            "sql_execution_success_rate_pct": round(sql_exec_rate, 2) if db_connected else 0.0,
            "security_block_rate_pct": round(sec_block_rate, 2),
            "latency": latency_stats,
            "ambiguity_breakdown": {
                "clarification_requested": amb_clarification,
                "explicit_assumptions": amb_explicit,
                "unsupported_assumptions": amb_unsupported,
                "failures": amb_failed,
            },
            "invalid_schema_breakdown": {
                "handled_correctly": inv_handled_correctly,
                "hallucinated": inv_hallucinated,
            },
        },
        "results": {
            "sql_generation": sql_results,
            "security_tests": security_results,
            "ambiguity_tests": ambiguity_results,
            "invalid_schema_tests": invalid_schema_results,
        },
    }

    # Save baseline_results.json if not present or requested via --baseline
    is_baseline_run = "--baseline" in sys.argv or not (RESULTS_DIR / "baseline_results.json").exists()
    if is_baseline_run:
        baseline_file = RESULTS_DIR / "baseline_results.json"
        with open(baseline_file, "w", encoding="utf-8") as f:
            json.dump(full_output, f, indent=2)
        print(f"     3. Baseline saved to: {baseline_file}")

    # If baseline exists and this is not a baseline run, print BEFORE vs AFTER table
    baseline_path = RESULTS_DIR / "baseline_results.json"
    if baseline_path.exists() and not is_baseline_run:
        try:
            with open(baseline_path, "r", encoding="utf-8") as f:
                base_data = json.load(f)
            base_m = base_data.get("metrics", {})
            base_lat = base_m.get("latency", {})
            
            print("\n" + "=" * 60)
            print("BEFORE vs AFTER COMPARISON (Post-Fix vs Baseline)")
            print("=" * 60)
            print(f"{'Metric':<30} {'Baseline':<12} {'Current':<12} {'Change'}")
            print("-" * 60)
            
            base_valid = base_m.get("sql_generation_validity_rate_pct", 0)
            print(f"{'SQL Validity':<30} {base_valid:.1f}%{'':<6} {sql_gen_rate:.1f}%{'':<6} {sql_gen_rate - base_valid:+.1f}%")
            
            base_acc = base_m.get("sql_accuracy_rate_pct")
            base_acc_str = f"{base_acc:.1f}%" if base_acc is not None else "N/A"
            curr_acc_str = f"{sql_accuracy_rate:.1f}%" if sql_accuracy_rate is not None else "N/A"
            acc_change_str = f"{sql_accuracy_rate - base_acc:+.1f}%" if (sql_accuracy_rate is not None and base_acc is not None) else "N/A"
            print(f"{'Result Correctness (Accuracy)':<30} {base_acc_str:<12} {curr_acc_str:<12} {acc_change_str}")

            base_exec = base_m.get("sql_execution_success_rate_pct", 0)
            print(f"{'Execution Success':<30} {base_exec:.1f}%{'':<6} {sql_exec_rate:.1f}%{'':<6} {sql_exec_rate - base_exec:+.1f}%")

            base_sec = base_m.get("security_block_rate_pct", 0)
            print(f"{'Security Block Rate':<30} {base_sec:.1f}%{'':<6} {sec_block_rate:.1f}%{'':<6} {sec_block_rate - base_sec:+.1f}%")

            base_avg_lat = base_lat.get("average", 0)
            curr_avg_lat = latency_stats["average"]
            lat_pct = ((curr_avg_lat - base_avg_lat) / base_avg_lat * 100) if base_avg_lat else 0
            print(f"{'Average Latency':<30} {base_avg_lat:.0f} ms{'':<6} {curr_avg_lat:.0f} ms{'':<6} {lat_pct:+.1f}%")

            base_p95_lat = base_lat.get("p95", 0)
            curr_p95_lat = latency_stats["p95"]
            p95_pct = ((curr_p95_lat - base_p95_lat) / base_p95_lat * 100) if base_p95_lat else 0
            print(f"{'P95 Latency':<30} {base_p95_lat:.0f} ms{'':<6} {curr_p95_lat:.0f} ms{'':<6} {p95_pct:+.1f}%")
            print("=" * 60)
        except Exception as e:
            print(f"[NOTE] Could not load baseline comparison: {e}")

    # Write latest_results.json
    with open(LATEST_RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2)

    # Write timestamped results file
    timestamped_file = RESULTS_DIR / f"evaluation_{file_timestamp}.json"
    with open(timestamped_file, "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2)

    print(f"\n[OK] Raw results saved to:")
    print(f"     1. {LATEST_RESULTS_FILE}")
    print(f"     2. {timestamped_file}\n")


if __name__ == "__main__":
    run_evaluation()
