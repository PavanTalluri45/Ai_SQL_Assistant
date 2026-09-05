import re
from typing import List, Optional, TypedDict
from app.core.config import DEFAULT_MAX_SQL_LENGTH, SUPPORTED_TABLES_SET

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

# Rule 5: the tables generated SQL is permitted to reference.
ALLOWED_TABLES = SUPPORTED_TABLES_SET

# Rule 2: statement types that are never allowed, even though some of
# these (e.g. CREATE, GRANT) don't start a statement with "SELECT" and
# would already be caught by _check_select_only. Kept explicit so each
# check is self-contained and the error messages stay specific.
FORBIDDEN_STATEMENT_KEYWORDS = [
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "GRANT",
    "REVOKE",
    "COPY",
    "CALL",
    "EXECUTE",
    "MERGE",
]

# Rule 7: system/introspection functions and privilege-escalation
# vectors that must never appear, even inside an otherwise-valid SELECT.
DANGEROUS_SYSTEM_KEYWORDS = [
    "PG_SLEEP",
    "PG_READ_FILE",
    "PG_WRITE_FILE",
    "PG_TERMINATE_BACKEND",
    "PG_CANCEL_BACKEND",
    "DBLINK",
    "LO_IMPORT",
    "LO_EXPORT",
    "XP_CMDSHELL",
    "INTO OUTFILE",
    "INTO DUMPFILE",
]

# Rule 5: schemas/tables that are explicitly blocked even though a
# plain SELECT against them would otherwise look syntactically valid.
BLOCKED_TABLES = [
    "USERS",
    "PG_DATABASE",
    "PG_CATALOG",
    "INFORMATION_SCHEMA",
]


class ValidationResult(TypedDict):
    """Structured return type for validate_sql()."""
    valid: bool
    sql: Optional[str]
    error: Optional[str]


class SQLValidationError(Exception):
    """
    Raised internally by individual _check_* helpers when a rule fails.

    Caught by validate_sql() and converted into a ValidationResult so
    callers never need to handle exceptions directly.
    """
    pass


# ----------------------------------------------------------------------
# Individual validation checks (single responsibility each)
# ----------------------------------------------------------------------

def _check_empty(sql: str) -> None:
    """Rule 1: SQL cannot be empty (after trimming)."""
    if not sql or not sql.strip():
        raise SQLValidationError("SQL query is empty.")


def _check_length(sql: str, max_length: int) -> None:
    """Rule 6: reject SQL longer than the configured limit."""
    if len(sql) > max_length:
        raise SQLValidationError(
            f"SQL exceeds maximum allowed length of {max_length} characters."
        )


def _check_comments(sql: str) -> None:
    """Rule 4: reject single-line (--) and block (/* */) comments."""
    if "--" in sql:
        raise SQLValidationError("SQL comments ('--') are not allowed.")
    if "/*" in sql or "*/" in sql:
        raise SQLValidationError("SQL block comments ('/* */') are not allowed.")


def _check_multiple_statements(sql: str) -> None:
    """
    Rule 3: reject multiple SQL statements.

    A single trailing semicolon is tolerated (e.g. "SELECT 1;"). Any
    semicolon that appears before the end, or more than one semicolon
    total, means more than one statement is present.
    """
    stripped = sql.strip()

    if stripped.endswith(";"):
        stripped = stripped[:-1]

    if ";" in stripped:
        raise SQLValidationError("Multiple SQL statements are not allowed.")


def _check_select_only(sql: str) -> None:
    """
    Rule 2 + Rule 9: only SELECT statements are allowed, checked
    case-insensitively. Also scans the full statement for forbidden
    mutating/DDL keywords so a SELECT that hides a mutation via a CTE
    or subquery is still rejected.
    """
    stripped = sql.strip()

    if not re.match(r"(?i)^select\b", stripped):
        raise SQLValidationError("Only SELECT statements are allowed.")

    for keyword in FORBIDDEN_STATEMENT_KEYWORDS:
        if re.search(rf"(?i)\b{keyword}\b", stripped):
            raise SQLValidationError(f"{keyword} statements are not allowed.")


def _check_dangerous_keywords(sql: str) -> None:
    """Rule 7: reject SQL containing dangerous system keywords/functions."""
    for keyword in DANGEROUS_SYSTEM_KEYWORDS:
        pattern = rf"(?i)\b{re.escape(keyword)}\b"
        if re.search(pattern, sql):
            raise SQLValidationError(
                f"Use of dangerous keyword '{keyword}' is not allowed."
            )


def _mask_function_from_clauses(sql: str) -> str:
    """
    Remove SQL function-internal 'FROM' keywords such as:
    - EXTRACT(field FROM expr)
    - TRIM(...)
    - SUBSTRING(... FROM ...)
    so they are not misinterpreted as table source clauses.
    """
    # Mask EXTRACT( ... FROM ... )
    sql = re.sub(r"(?i)\bEXTRACT\s*\([^)]*?\bFROM\b[^)]*?\)", "EXTRACT()", sql)
    # Mask TRIM( ... FROM ... )
    sql = re.sub(r"(?i)\bTRIM\s*\([^)]*?\bFROM\b[^)]*?\)", "TRIM()", sql)
    # Mask SUBSTRING( ... FROM ... )
    sql = re.sub(r"(?i)\bSUBSTRING\s*\([^)]*?\bFROM\b[^)]*?\)", "SUBSTRING()", sql)
    return sql


def _extract_referenced_tables(sql: str) -> List[str]:
    """
    Extract table-like identifiers referenced via FROM or JOIN clauses.
    Properly handles SQL functions that contain 'FROM' internally (e.g. EXTRACT).
    """
    cleaned_sql = _mask_function_from_clauses(sql)
    pattern = r"(?i)\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_\.]*)"
    matches = re.findall(pattern, cleaned_sql)
    return [m.upper() for m in matches]


def _check_allowed_tables(sql: str) -> None:
    """
    Rule 5: allow queries ONLY against the retail_sales table.

    Any schema-qualified reference (e.g. information_schema.tables,
    pg_catalog.pg_tables) is rejected outright, since only a bare
    "retail_sales" reference is permitted. Known-sensitive
    schemas/tables are rejected with a specific error message.
    """
    referenced = _extract_referenced_tables(sql)

    if not referenced:
        raise SQLValidationError("No table reference found in SQL.")

    for table in referenced:
        parts = table.split(".")

        if any(part in BLOCKED_TABLES for part in parts):
            raise SQLValidationError(f"Access to '{table}' is not allowed.")

        if len(parts) > 1:
            raise SQLValidationError(
                f"Schema-qualified table references are not allowed: '{table}'."
            )

        if parts[0].lower() not in ALLOWED_TABLES:
            raise SQLValidationError(
                f"Only the 'retail_sales' table may be queried. "
                f"Found reference to '{table}'."
            )


# ----------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------

def validate_sql(
    sql: str,
    max_length: int = DEFAULT_MAX_SQL_LENGTH,
) -> ValidationResult:
    """
    Validate AI-generated SQL before it reaches the database.

    This function never modifies the SQL it receives. It runs a fixed
    sequence of independent checks and stops at the first failure.

    Args:
        sql: Raw SQL string produced by the SQL Generator.
        max_length: Maximum allowed SQL length, in characters.

    Returns:
        ValidationResult: a dict of the form
            {"valid": True,  "sql": "<sql>", "error": None}
        or
            {"valid": False, "sql": None,    "error": "<reason>"}
    """
    try:
        # Rule 8: trim whitespace before validation.
        trimmed = sql.strip() if sql else sql

        _check_empty(trimmed)
        _check_length(trimmed, max_length)
        _check_comments(trimmed)
        _check_multiple_statements(trimmed)
        _check_select_only(trimmed)
        _check_dangerous_keywords(trimmed)
        _check_allowed_tables(trimmed)

        return {"valid": True, "sql": trimmed, "error": None}

    except SQLValidationError as e:
        return {"valid": False, "sql": None, "error": str(e)}