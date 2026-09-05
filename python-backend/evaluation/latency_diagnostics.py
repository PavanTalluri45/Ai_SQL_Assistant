"""
AI SQL Assistant — Latency Diagnostic Runner

Instruments every stage of process_question() with high-resolution timing.
Captures per-attempt Gemini retry data by monkey-patching generate_response.
Saves full diagnostic report to JSON.

Usage:
    python -m evaluation.latency_diagnostics

DO NOT modify this file to hide or suppress slow data.
"""

import contextlib
import datetime
import io
import json
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from evaluation.config import DEFAULT_SCHEMA_TEXT, PRIMARY_TABLE, RESULTS_DIR
from evaluation.test_cases import SQL_TEST_CASES
from database.sql_executor import execute_query
from database.schema_provider import get_retail_sales_schema
from app.ai.sql_validator import validate_sql
from app.ai.sql_generator import generate_sql
from app.ai.result_explainer import explain_results
from app.ai.visualization.visualization_selector import select_visualization
from app.ai.visualization.intent_mapper import map_intent_to_chart
from app.ai.visualization.visualization_response_builder import build_visualization_response, disabled_visualization_response
import app.ai.gemini_service as gemini_module


# ─────────────────────────────────────────────────────────────────────────────
# Thread-local retry tracker — captures retries from each call context
# ─────────────────────────────────────────────────────────────────────────────
_retry_log: threading.local = threading.local()


def _reset_retry_log():
    _retry_log.events = []


def _get_retry_events() -> List[Dict]:
    return getattr(_retry_log, 'events', [])


def _patched_generate_response(prompt: str, max_retries: int = 5, _call_label: str = "unknown") -> str:
    """
    Instrumented replacement for gemini_service.generate_response.
    Records every attempt, HTTP status, and retry wait without changing behavior.
    """
    if not hasattr(_retry_log, 'events'):
        _retry_log.events = []

    delay = 2.0
    call_start = time.perf_counter()
    total_wait_s = 0.0

    for attempt in range(max_retries):
        attempt_start = time.perf_counter()
        try:
            response = gemini_module.client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=prompt
            )
            duration_ms = (time.perf_counter() - attempt_start) * 1000
            _retry_log.events.append({
                "call_label": _call_label,
                "attempt": attempt + 1,
                "status": "200 OK",
                "duration_ms": round(duration_ms, 1),
                "wait_before_ms": 0,
                "error": None,
            })
            return response.text
        except Exception as e:
            err_str = str(e)
            duration_ms = (time.perf_counter() - attempt_start) * 1000
            is_rate_limit = ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower())

            if is_rate_limit and attempt < max_retries - 1:
                match = re.search(r"retry in (\d+(?:\.\d+)?)s", err_str, re.IGNORECASE)
                if not match:
                    match = re.search(r"retryDelay':\s*'(\d+)s'", err_str)
                sleep_time = float(match.group(1)) + 1.0 if match else delay

                _retry_log.events.append({
                    "call_label": _call_label,
                    "attempt": attempt + 1,
                    "status": "429 RESOURCE_EXHAUSTED",
                    "duration_ms": round(duration_ms, 1),
                    "wait_before_ms": 0,
                    "wait_after_ms": round(sleep_time * 1000, 1),
                    "error": err_str[:200],
                })
                total_wait_s += sleep_time
                time.sleep(sleep_time)
                delay *= 2
            else:
                _retry_log.events.append({
                    "call_label": _call_label,
                    "attempt": attempt + 1,
                    "status": "ERROR" if not is_rate_limit else "429 EXHAUSTED_MAX_RETRIES",
                    "duration_ms": round(duration_ms, 1),
                    "wait_before_ms": 0,
                    "error": err_str[:200],
                })
                raise e


def _make_labeled_generate(label: str):
    """Returns a generate_response variant that tags retry events with a label."""
    def _labeled(prompt: str, max_retries: int = 5) -> str:
        return _patched_generate_response(prompt, max_retries=max_retries, _call_label=label)
    return _labeled


# ─────────────────────────────────────────────────────────────────────────────
# Instrumented pipeline
# ─────────────────────────────────────────────────────────────────────────────

def _run_instrumented(question: str, schema: str) -> Dict[str, Any]:
    """
    Run the full pipeline with per-stage timing and retry instrumentation.
    Returns a dict with all timing breakdowns.
    """
    _reset_retry_log()
    timings: Dict[str, float] = {}
    errors: Dict[str, Optional[str]] = {}

    # ── 1. Input check ────────────────────────────────────────────────────
    t0 = time.perf_counter()
    timings['input_ms'] = round((time.perf_counter() - t0) * 1000, 2)

    # ── 2. Schema retrieval ───────────────────────────────────────────────
    t0 = time.perf_counter()
    # Schema already pre-loaded; just measure the pass-through cost
    _ = schema
    timings['schema_ms'] = round((time.perf_counter() - t0) * 1000, 2)

    # ── 3. SQL Generation (LLM 1) ─────────────────────────────────────────
    import app.ai.sql_generator as sg_module
    original_gen = gemini_module.generate_response
    gemini_module.generate_response = _make_labeled_generate("SQL Generation")
    sg_module.generate_response = gemini_module.generate_response
    t0 = time.perf_counter()
    try:
        generated_sql = generate_sql(question=question, schema=schema)
        errors['sql_gen'] = None
    except Exception as e:
        generated_sql = None
        errors['sql_gen'] = str(e)
    timings['sql_gen_ms'] = round((time.perf_counter() - t0) * 1000, 2)
    sql_gen_retries = [ev for ev in _get_retry_events() if ev['call_label'] == 'SQL Generation']

    # ── 4. SQL Validation ─────────────────────────────────────────────────
    t0 = time.perf_counter()
    if generated_sql:
        validation = validate_sql(generated_sql)
    else:
        validation = {"valid": False, "sql": None, "error": "No SQL generated"}
    timings['validation_ms'] = round((time.perf_counter() - t0) * 1000, 2)
    validated_sql = validation.get("sql") if validation["valid"] else None
    errors['validation'] = validation.get("error") if not validation["valid"] else None

    # ── 5. PostgreSQL Execution ───────────────────────────────────────────
    t0 = time.perf_counter()
    rows = []
    if validated_sql:
        exec_result = execute_query(validated_sql)
        rows = exec_result.get("data") or []
        errors['db'] = exec_result.get("error")
    else:
        errors['db'] = "Skipped (validation failed)"
    timings['db_ms'] = round((time.perf_counter() - t0) * 1000, 2)

    # ── 6. Business Explanation (LLM 2) + Visualization (LLM 3) — Concurrent
    import app.ai.result_explainer as re_module
    import app.ai.visualization.visualization_selector as vs_module

    # Explanation timing
    explain_start = [0.0]
    explain_end = [0.0]
    vis_start = [0.0]
    vis_end = [0.0]
    answer_holder = [None]
    vis_holder = [None]
    explain_ex = [None]
    vis_ex = [None]

    def _explain():
        _reset_retry_log()
        gemini_module.generate_response = _make_labeled_generate("Business Explanation")
        re_module.generate_response = gemini_module.generate_response
        explain_start[0] = time.perf_counter()
        try:
            answer_holder[0] = explain_results(question=question, rows=rows)
        except Exception as e:
            explain_ex[0] = str(e)
            answer_holder[0] = ""
        explain_end[0] = time.perf_counter()
        # Save events for this thread
        explain_events = list(_get_retry_events())
        return explain_events

    def _visualize():
        _reset_retry_log()
        gemini_module.generate_response = _make_labeled_generate("Visualization Selection")
        vs_module.generate_response = gemini_module.generate_response
        vis_start[0] = time.perf_counter()
        try:
            goal_result = select_visualization(question=question, rows=rows)
            vis_holder[0] = build_visualization_response(question=question, goal_result=goal_result, rows=rows)
        except Exception as e:
            vis_ex[0] = str(e)
            vis_holder[0] = None
        vis_end[0] = time.perf_counter()
        vis_events = list(_get_retry_events())
        return vis_events

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_ex = executor.submit(_explain)
        future_vis = executor.submit(_visualize)
        explain_events = future_ex.result()
        vis_events = future_vis.result()

    timings['explanation_ms'] = round((explain_end[0] - explain_start[0]) * 1000, 2)
    timings['visualization_ms'] = round((vis_end[0] - vis_start[0]) * 1000, 2)

    # Wall time of concurrent block = max(explain, vis) because they overlap
    concurrent_wall_ms = max(timings['explanation_ms'], timings['visualization_ms'])
    timings['concurrent_postprocess_wall_ms'] = round(concurrent_wall_ms, 2)

    # Restore
    gemini_module.generate_response = original_gen
    re_module.generate_response = original_gen
    vs_module.generate_response = original_gen

    # ── Aggregate ─────────────────────────────────────────────────────────
    total_ms = (
        timings['input_ms']
        + timings['schema_ms']
        + timings['sql_gen_ms']
        + timings['validation_ms']
        + timings['db_ms']
        + timings['concurrent_postprocess_wall_ms']
    )
    timings['total_ms'] = round(total_ms, 2)

    # Retry analysis
    all_events = sql_gen_retries + explain_events + vis_events
    count_429 = sum(1 for e in all_events if '429' in str(e.get('status', '')))
    total_retry_wait_ms = sum(e.get('wait_after_ms', 0) for e in all_events if '429' in str(e.get('status', '')))
    retry_count = sum(1 for e in all_events if e.get('attempt', 1) > 1)

    # Identify bottleneck
    stage_latencies = {
        'SQL Generation (LLM)': timings['sql_gen_ms'],
        'PostgreSQL Execution': timings['db_ms'],
        'Business Explanation (LLM)': timings['explanation_ms'],
        'Visualization Selection (LLM)': timings['visualization_ms'],
    }
    bottleneck = max(stage_latencies, key=stage_latencies.get)

    # Root cause classification
    if count_429 > 0 and total_retry_wait_ms > 10000:
        primary_cause = "API_RATE_LIMIT_429_BACKOFF"
    elif timings['sql_gen_ms'] > 10000:
        primary_cause = "SLOW_LLM_SQL_GENERATION"
    elif timings['explanation_ms'] > 10000 or timings['visualization_ms'] > 10000:
        primary_cause = "SLOW_LLM_POST_PROCESSING"
    elif timings['db_ms'] > 5000:
        primary_cause = "SLOW_POSTGRESQL"
    else:
        primary_cause = "NORMAL_PROCESSING"

    return {
        "timings": timings,
        "errors": errors,
        "generated_sql": generated_sql,
        "validated": validation["valid"],
        "row_count": len(rows),
        "retry_events": all_events,
        "count_429": count_429,
        "total_retry_wait_ms": round(total_retry_wait_ms, 1),
        "retry_count": retry_count,
        "bottleneck": bottleneck,
        "primary_cause": primary_cause,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main diagnostic run
# ─────────────────────────────────────────────────────────────────────────────

def run_latency_diagnostics():
    start_time = datetime.datetime.now(datetime.timezone.utc)
    file_ts = start_time.strftime("%Y-%m-%d_%H-%M-%S")

    print("=" * 65)
    print("  AI SQL ASSISTANT — LATENCY DIAGNOSTIC RUNNER")
    print("=" * 65)
    print(f"Run start: {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Test cases: {len(SQL_TEST_CASES)}")
    print(f"DB Check: ", end="", flush=True)
    db_ok = execute_query(f"SELECT 1 FROM {PRIMARY_TABLE} LIMIT 1;")["success"]
    print("ONLINE" if db_ok else "OFFLINE")
    print("-" * 65)

    schema = DEFAULT_SCHEMA_TEXT
    results = []

    for tc in SQL_TEST_CASES:
        print(f"\n[{tc.id}] {tc.question[:65]}")
        with contextlib.redirect_stdout(io.StringIO()):
            diag = _run_instrumented(tc.question, schema)

        t = diag["timings"]
        print(f"  Total:          {t['total_ms']/1000:.2f}s")
        print(f"  SQL Generation: {t['sql_gen_ms']/1000:.2f}s")
        print(f"  Validation:     {t['validation_ms']/1000:.3f}s")
        print(f"  PostgreSQL:     {t['db_ms']/1000:.3f}s")
        print(f"  Explanation:    {t['explanation_ms']/1000:.2f}s")
        print(f"  Visualization:  {t['visualization_ms']/1000:.2f}s")
        print(f"  Concurrent Wall:{t['concurrent_postprocess_wall_ms']/1000:.2f}s")
        if diag["count_429"] > 0:
            print(f"  *** 429 Responses: {diag['count_429']} | Retry Wait: {diag['total_retry_wait_ms']/1000:.1f}s ***")
        print(f"  Bottleneck:     {diag['bottleneck']}")
        print(f"  Root Cause:     {diag['primary_cause']}")

        results.append({
            "id": tc.id,
            "question": tc.question,
            "category": tc.category,
            "total_latency_ms": t["total_ms"],
            "input_ms": t["input_ms"],
            "schema_ms": t["schema_ms"],
            "sql_gen_ms": t["sql_gen_ms"],
            "validation_ms": t["validation_ms"],
            "db_ms": t["db_ms"],
            "explanation_ms": t["explanation_ms"],
            "visualization_ms": t["visualization_ms"],
            "concurrent_wall_ms": t["concurrent_postprocess_wall_ms"],
            "count_429": diag["count_429"],
            "total_retry_wait_ms": diag["total_retry_wait_ms"],
            "retry_count": diag["retry_count"],
            "retry_events": diag["retry_events"],
            "bottleneck": diag["bottleneck"],
            "primary_cause": diag["primary_cause"],
        })

    # ── Summary ───────────────────────────────────────────────────────────
    total_latencies = [r["total_latency_ms"] for r in results]
    sorted_results = sorted(results, key=lambda x: x["total_latency_ms"], reverse=True)

    import numpy as np
    arr = np.array(total_latencies)
    avg_ms = float(np.mean(arr))
    median_ms = float(np.median(arr))
    p95_ms = float(np.percentile(arr, 95))
    min_ms = float(np.min(arr))
    max_ms = float(np.max(arr))

    print("\n" + "=" * 65)
    print("SLOWEST REQUESTS")
    print("=" * 65)
    print(f"{'Rank':<5} {'Test ID':<10} {'Total Time':<13} {'429s':<6} {'Cause':<30} Question")
    print("-" * 120)
    for rank, r in enumerate(sorted_results[:10], 1):
        print(f"{rank:<5} {r['id']:<10} {r['total_latency_ms']/1000:.2f}s{'':<6} {r['count_429']:<6} {r['primary_cause']:<30} {r['question'][:50]}")

    print("\n" + "=" * 65)
    print("LATENCY DISTRIBUTION")
    print("=" * 65)
    buckets = [("<5s", 0, 5000), ("5–10s", 5000, 10000), ("10–20s", 10000, 20000),
               ("20–30s", 20000, 30000), ("30–45s", 30000, 45000), ("45–60s", 45000, 60000), (">60s", 60000, 1e9)]
    for label, lo, hi in buckets:
        count = sum(1 for r in results if lo <= r["total_latency_ms"] < hi)
        bar = "#" * count
        print(f"  {label:<10}: {count:>3}  {bar}")

    slow_cases = [r for r in results if r["total_latency_ms"] > 20000]
    print(f"\n{'='*65}")
    print(f"SLOW REQUEST DETAIL (>{20}s)")
    print(f"{'='*65}")
    for r in sorted(slow_cases, key=lambda x: x["total_latency_ms"], reverse=True):
        print(f"\n{r['id']} — {r['question']}")
        print(f"  Total:              {r['total_latency_ms']/1000:.2f}s")
        print(f"  SQL Generation:     {r['sql_gen_ms']/1000:.2f}s")
        print(f"  Validation:         {r['validation_ms']/1000:.3f}s")
        print(f"  PostgreSQL:         {r['db_ms']/1000:.3f}s")
        print(f"  Explanation (LLM2): {r['explanation_ms']/1000:.2f}s")
        print(f"  Visualization(LLM3):{r['visualization_ms']/1000:.2f}s")
        print(f"  Concurrent Wall:    {r['concurrent_wall_ms']/1000:.2f}s")
        print(f"  429 Responses:      {r['count_429']}")
        print(f"  Total Retry Wait:   {r['total_retry_wait_ms']/1000:.2f}s")
        print(f"  Primary Cause:      {r['primary_cause']}")
        if r["retry_events"]:
            print(f"  Retry Events:")
            for ev in r["retry_events"]:
                wait = ev.get('wait_after_ms', 0)
                print(f"    [{ev['call_label']}] Attempt {ev['attempt']}: {ev['status']} | LLM dur={ev['duration_ms']:.0f}ms" +
                      (f" | Wait={wait/1000:.1f}s" if wait else ""))

    # ── LLM Performance Table ─────────────────────────────────────────────
    print(f"\n{'='*65}")
    print("LLM PERFORMANCE BREAKDOWN")
    print(f"{'='*65}")
    sql_ms = np.array([r["sql_gen_ms"] for r in results])
    exp_ms = np.array([r["explanation_ms"] for r in results])
    vis_ms = np.array([r["visualization_ms"] for r in results])
    total_429 = sum(r["count_429"] for r in results)
    total_retries = sum(r["retry_count"] for r in results)
    print(f"{'Operation':<28} {'Avg':>8} {'Median':>8} {'P95':>10} {'Max':>10}")
    print("-" * 70)
    print(f"{'SQL Generation':<28} {np.mean(sql_ms)/1000:>7.2f}s {np.median(sql_ms)/1000:>7.2f}s {np.percentile(sql_ms, 95)/1000:>9.2f}s {np.max(sql_ms)/1000:>9.2f}s")
    print(f"{'Business Explanation':<28} {np.mean(exp_ms)/1000:>7.2f}s {np.median(exp_ms)/1000:>7.2f}s {np.percentile(exp_ms, 95)/1000:>9.2f}s {np.max(exp_ms)/1000:>9.2f}s")
    print(f"{'Visualization Selection':<28} {np.mean(vis_ms)/1000:>7.2f}s {np.median(vis_ms)/1000:>7.2f}s {np.percentile(vis_ms, 95)/1000:>9.2f}s {np.max(vis_ms)/1000:>9.2f}s")
    print(f"\nTotal 429 Responses across all 30 tests: {total_429}")
    print(f"Total Retry Attempts across all 30 tests: {total_retries}")
    total_wait_all = sum(r["total_retry_wait_ms"] for r in results)
    print(f"Total Time Spent Waiting on Retries: {total_wait_all/1000:.1f}s")

    # ── Root Cause Summary ────────────────────────────────────────────────
    cause_counts = {}
    for r in results:
        cause_counts[r["primary_cause"]] = cause_counts.get(r["primary_cause"], 0) + 1
    print(f"\n{'='*65}")
    print("ROOT CAUSE SUMMARY")
    print(f"{'='*65}")
    for cause, cnt in sorted(cause_counts.items(), key=lambda x: -x[1]):
        print(f"  {cause:<40}: {cnt} request(s)")

    affected_by_429 = sum(1 for r in results if r["count_429"] > 0)
    print(f"\nRequests affected by at least one 429: {affected_by_429}/{len(results)}")
    max_single_wait = max((r["total_retry_wait_ms"] for r in results), default=0)
    print(f"Largest retry wait on a single request: {max_single_wait/1000:.1f}s")
    print(f"\nMedian latency (normal requests): {median_ms/1000:.2f}s")
    print(f"Average latency (all requests):   {avg_ms/1000:.2f}s")
    print(f"Max latency (worst request):      {max_ms/1000:.2f}s")
    print(f"P95 latency:                      {p95_ms/1000:.2f}s")

    # ── Save JSON ─────────────────────────────────────────────────────────
    output = {
        "metadata": {
            "run_date": start_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "test_count": len(results),
            "db_connected": db_ok,
        },
        "summary": {
            "average_ms": round(avg_ms, 1),
            "median_ms": round(median_ms, 1),
            "p95_ms": round(p95_ms, 1),
            "min_ms": round(min_ms, 1),
            "max_ms": round(max_ms, 1),
            "requests_above_20s": len(slow_cases),
            "total_429_count": total_429,
            "total_retry_wait_ms": round(total_wait_all, 1),
        },
        "cases": results,
    }
    out_path = RESULTS_DIR / f"latency_diagnostics_{file_ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"\n[OK] Diagnostic JSON saved to: {out_path}\n")


if __name__ == "__main__":
    run_latency_diagnostics()

