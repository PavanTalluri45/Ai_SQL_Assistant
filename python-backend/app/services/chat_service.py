import logging
import time
from typing import Any, Dict, List, Optional
from decimal import Decimal
import datetime
from app.ai.sql_generator import generate_sql
from app.ai.sql_validator import validate_sql
from app.ai.result_explainer import explain_results
from app.ai.visualization.visualization_selector import select_visualization
from app.ai.visualization.intent_mapper import map_intent_to_chart
from app.ai.visualization.visualization_response_builder import (
    build_visualization_response,
    disabled_visualization_response,
)
from app.response.response_builder import BackendResponse, build_error_response, build_response
from database.sql_executor import execute_query
from database.schema_provider import get_retail_sales_schema

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Internal helpers (single responsibility each)
# ----------------------------------------------------------------------

def _check_question(question: str) -> None:
    """Raise a ValueError if the question is empty or whitespace-only."""
    if not question or not question.strip():
        raise ValueError("Question cannot be empty.")


def _select_visualization_safe(
    question: str,
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Run the full Visualization Layer:
    1. Analytical Goal Classifier (Gemini)
    2. Visualization Planner (Deterministic Python Engine)
    """
    try:
        goal_result = select_visualization(question=question, rows=rows)
        return build_visualization_response(
            question=question,
            goal_result=goal_result,
            rows=rows,
        )
    except Exception as e:
        logger.error("Visualization selection failed: %s", e)
        return disabled_visualization_response("Visualization selection failed due to an error.")


# ----------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------

def process_question(
    question: str,
    schema: Optional[Dict[str, Any]] = None,
) -> BackendResponse:
    """
    Run the complete pipeline for a single natural-language question.

    This function never raises - every failure mode from any stage
    (SQL generation, validation, execution, explanation, or
    visualization selection) is caught and returned as a structured
    BackendResponse via app.response.response_builder.

    Args:
        question: The user's natural language question.
        schema: Optional pre-loaded schema. Pass this in when you've
            already built the metadata cache (e.g. the persistent
            terminal session does this once at startup) so the
            Metadata Layer isn't hit again for every question. When
            omitted, the schema is loaded fresh inside this call -
            this keeps process_question backward compatible for any
            other caller (API routes, tests, scripts) that doesn't
            maintain its own cache.

    Returns:
        BackendResponse: a dict of the form
            {"success": True, "question": ..., "sql": ..., "execution_time": 0.82,
             "row_count": N, "data": [...], "answer": "...",
             "visualization": {...}, "error": None}
        or
            {"success": False, "question": ..., "sql": None|"...",
             "execution_time": 0.12, "row_count": 0, "data": None,
             "answer": None, "visualization": None, "error": "..."}

        This is the exact same shape a future FastAPI endpoint would
        return as JSON - the terminal printer below only formats it
        for display, it doesn't reshape it.
    """
    start_time = time.perf_counter()

    try:
        _check_question(question)
    except ValueError as e:
        logger.warning("Rejected empty question.")
        return build_error_response(question, str(e), time.perf_counter() - start_time)

    # Step 1: Load schema from the Metadata Layer (skipped if pre-loaded)
    schema_was_cached = schema is not None
    _step(1, "Using cached Database Metadata..." if schema_was_cached else "Loading Database Metadata...")
    try:
        if schema is None:
            schema = get_retail_sales_schema()
        logger.info("Schema ready for question: %s", question)
        _step_done()
    except Exception as e:
        logger.error("Failed to load database schema: %s", e)
        return build_error_response(
            question, f"Failed to load database schema: {e}", time.perf_counter() - start_time
        )

    # Step 2: Generate SQL
    _step(2, "Generating SQL...")
    try:
        generated_sql = generate_sql(question=question, schema=schema)
        logger.info("SQL generated for question: %s", question)
        _step_done()
    except Exception as e:
        logger.error("SQL generation failed: %s", e)
        return build_error_response(
            question, f"Failed to generate SQL: {e}", time.perf_counter() - start_time
        )

    # Step 3: Validate SQL
    _step(3, "Validating SQL...")
    validation = validate_sql(generated_sql)
    if not validation["valid"]:
        logger.warning("SQL validation failed: %s", validation["error"])
        return build_error_response(
            question,
            validation["error"],
            time.perf_counter() - start_time,
            sql=generated_sql,
        )
    validated_sql = validation["sql"]
    _step_done()

    # Step 4: Execute SQL
    _step(4, "Executing SQL...")
    execution = execute_query(validated_sql)
    if not execution["success"]:
        logger.error("SQL execution failed: %s", execution["error"])
        return build_error_response(
            question,
            execution["error"],
            time.perf_counter() - start_time,
            sql=validated_sql,
        )
    rows = execution["data"]
    _step_done()

    # Step 5 & 6: Concurrently generate Business Explanation and Select Visualization
    _step(5, "Generating Business Explanation & Selecting Visualization (Concurrent)...")
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_explain = executor.submit(explain_results, question=question, rows=rows)
            future_vis = executor.submit(_select_visualization_safe, question=question, rows=rows)
            answer = future_explain.result()
            visualization = future_vis.result()
        _step_done()
    except Exception as e:
        logger.error("Post-execution processing failed: %s", e)
        # Graceful fallback: attempt explanation directly if thread pool raised
        try:
            answer = explain_results(question=question, rows=rows)
        except Exception:
            answer = "Could not generate business explanation."
        visualization = _select_visualization_safe(question=question, rows=rows)
        _step_done()

    execution_time = time.perf_counter() - start_time
    return build_response(
        question=question,
        execution_time=execution_time,
        sql=validated_sql,
        data=rows,
        answer=answer,
        visualization=visualization,
    )


# ----------------------------------------------------------------------
# Terminal progress helpers
# ----------------------------------------------------------------------

_TOTAL_STEPS = 5


def _step(step_number: int, label: str) -> None:
    print(f"[{step_number}/{_TOTAL_STEPS}] {label}")


def _step_done() -> None:
    print("[OK] Completed\n")


def _format_value_for_display(val: Any) -> Any:
    """
    Recursively formats query result values for terminal display.
    Converts Decimal to float and datetime/date objects to readable month strings.
    """
    if isinstance(val, Decimal):
        return float(val)
    elif isinstance(val, (datetime.datetime, datetime.date)):
        return val.strftime("%B %Y")
    elif isinstance(val, list):
        return [_format_value_for_display(item) for item in val]
    elif isinstance(val, dict):
        return {k: _format_value_for_display(v) for k, v in val.items()}
    return val


def _print_visualization(visualization: Optional[Dict[str, Any]]) -> None:
    """Pretty-print the visualization metadata block."""
    if not visualization:
        return

    print("\nVisualization:")
    print(f"  Presentation: {visualization.get('presentation')}")
    print(f"  Analytical Goal: {visualization.get('goal')}")
    print(f"  Chart Type: {visualization.get('chart_type')}")
    print(f"  Chart Title: {visualization.get('title')}")
    print(f"  X-Axis: {visualization.get('x_axis')}")
    print(f"  Y-Axis: {visualization.get('y_axis')}")
    print(f"  Series: {visualization.get('series')}")
    print(f"  Legend: {visualization.get('legend')}")
    print(f"  Stacked: {visualization.get('stacked')}")
    print(f"  Horizontal: {visualization.get('horizontal')}")
    print(f"  Sort: {visualization.get('sort')}")
    print(f"  Reason: {visualization.get('reason')}")


def _print_final_response(result: BackendResponse) -> None:
    """
    Pretty-print a BackendResponse exactly as returned by
    process_question() - no manual reassembly, just formatting for
    terminal display. This is the same object a FastAPI endpoint would
    serialize to JSON.
    """
    print("\n" + "=" * 50)
    print(f"Question:\n{result['question']}")
    print(f"\nExecution Time:\n{result['execution_time']:.2f} seconds")

    if result["success"]:
        print(f"\nGenerated SQL:\n{result['sql']}")
        print(f"\nRows Returned ({result['row_count']}):")
        formatted_rows = _format_value_for_display(result["data"])
        print(formatted_rows)
        print(f"\nBusiness Explanation:\n{result['answer']}")
        _print_visualization(result.get("visualization"))
    else:
        if result["sql"]:
            print(f"\nGenerated SQL:\n{result['sql']}")
        print(f"\nError:\n{result['error']}")

    print("=" * 50)


# ----------------------------------------------------------------------
# Persistent terminal interface
# ----------------------------------------------------------------------
# This is the ONLY input() call in the backend.

def _run_terminal_session() -> None:
    import os

    # Ensure logs directory exists
    os.makedirs("logs", exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Clear existing handlers to avoid duplicates
    root_logger.handlers = []

    # Formatter matching the original configuration
    formatter = logging.Formatter("[%(asctime)s] %(levelname)-8s [%(name)s] - %(message)s")

    # File Handler: level INFO, targeting logs/backend.log
    file_handler = logging.FileHandler("logs/backend.log", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Console Handler: level WARNING, keeping console output concise
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    print("=" * 50)
    print("AI SQL DATA ASSISTANT")
    print("=" * 50)

    # Build the metadata cache ONCE for the lifetime of the session.
    print("\nInitializing session (loading schema once)...")
    try:
        schema = get_retail_sales_schema()
        print("Schema cached for this session.\n")
    except Exception as e:
        logger.error("Failed to load database schema at startup: %s", e)
        print(f"\nCould not start session - failed to load schema: {e}")
        return

    first_prompt = True
    while True:
        if first_prompt:
            question = input("\nAsk your question:\n> ")
            first_prompt = False
        else:
            print("\n" + "-" * 50)
            question = input("Ask another question\n(Type 'exit' to quit)\n> ")

        if question.strip().lower() == "exit":
            print("\nGoodbye!")
            break

        result = process_question(question, schema=schema)
        print(result)
        _print_final_response(result)


if __name__ == "__main__":
    _run_terminal_session()