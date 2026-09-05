"""
Unit and Regression Test Suite for SQL Validator.

Tests:
1. Legitimate PostgreSQL date/time and advanced syntax:
   - EXTRACT(YEAR FROM date), EXTRACT(MONTH FROM date)
   - DATE_TRUNC, DATE_PART
   - CASE WHEN, COALESCE, CAST, ::date, ::numeric
   - Subqueries and nested expressions
2. Security & Guardrails enforcement:
   - Unauthorized table access (users, orders, system tables)
   - Mutating and destructive statements (DELETE, DROP, TRUNCATE, UPDATE, INSERT, ALTER, CREATE, GRANT, REVOKE)
   - Multi-statement execution and SQL comments
   - Dangerous system functions (pg_sleep, pg_read_file, dblink)
"""

import pytest
from app.ai.sql_validator import validate_sql


class TestSQLValidatorLegitimateSyntax:
    """Ensure legitimate PostgreSQL queries against retail_sales are valid."""

    def test_basic_select(self):
        sql = "SELECT * FROM retail_sales WHERE total_amount > 1000;"
        res = validate_sql(sql)
        assert res["valid"] is True, f"Expected valid, got error: {res['error']}"

    def test_extract_year_from_date(self):
        sql = """
        SELECT
            TO_CHAR(DATE_TRUNC('month', date), 'Mon YYYY') AS month,
            SUM(total_amount) AS total_sales
        FROM retail_sales
        WHERE EXTRACT(YEAR FROM date) = 2023
        GROUP BY DATE_TRUNC('month', date)
        ORDER BY total_sales DESC
        LIMIT 1;
        """
        res = validate_sql(sql)
        assert res["valid"] is True, f"Failed on EXTRACT(YEAR FROM date): {res['error']}"

    def test_extract_month_and_day_from_date(self):
        sql = "SELECT * FROM retail_sales WHERE EXTRACT(MONTH FROM date) = 12 AND EXTRACT(DAY FROM date) = 25;"
        res = validate_sql(sql)
        assert res["valid"] is True, f"Failed on multiple EXTRACT clauses: {res['error']}"

    def test_date_trunc_and_date_part(self):
        sql = """
        SELECT
            DATE_TRUNC('quarter', date) AS qtr,
            DATE_PART('year', date) AS yr,
            SUM(total_amount) AS rev
        FROM retail_sales
        GROUP BY DATE_TRUNC('quarter', date), DATE_PART('year', date);
        """
        res = validate_sql(sql)
        assert res["valid"] is True, f"Failed on DATE_TRUNC / DATE_PART: {res['error']}"

    def test_case_when_expression(self):
        sql = """
        SELECT
            CASE
                WHEN age < 30 THEN 'Under 30'
                WHEN age BETWEEN 30 AND 50 THEN '30-50'
                ELSE 'Over 50'
            END AS age_group,
            COUNT(*) AS customer_count
        FROM retail_sales
        GROUP BY 1;
        """
        res = validate_sql(sql)
        assert res["valid"] is True, f"Failed on CASE WHEN: {res['error']}"

    def test_coalesce_and_cast(self):
        sql = """
        SELECT
            COALESCE(product_category, 'Unknown') AS cat,
            CAST(total_amount AS NUMERIC(10, 2)) AS amount,
            date::DATE AS txn_date
        FROM retail_sales;
        """
        res = validate_sql(sql)
        assert res["valid"] is True, f"Failed on COALESCE/CAST: {res['error']}"

    def test_subquery_on_allowed_table(self):
        sql = """
        SELECT *
        FROM (
            SELECT customer_id, SUM(total_amount) AS total_spend
            FROM retail_sales
            GROUP BY customer_id
        ) sub
        WHERE total_spend > 5000;
        """
        res = validate_sql(sql)
        assert res["valid"] is True, f"Failed on subquery: {res['error']}"


class TestSQLValidatorSecurityAndGuardrails:
    """Ensure unauthorized access, destructive statements, and injection vectors are blocked."""

    def test_unauthorized_tables_rejected(self):
        unauthorized = [
            "SELECT * FROM users;",
            "SELECT * FROM orders;",
            "SELECT * FROM customers;",
            "SELECT * FROM retail_sales JOIN orders ON retail_sales.id = orders.id;",
            "SELECT * FROM pg_catalog.pg_tables;",
            "SELECT * FROM information_schema.tables;",
            "SELECT * FROM pg_database;",
        ]
        for sql in unauthorized:
            res = validate_sql(sql)
            assert res["valid"] is False, f"Expected rejection for '{sql}', but was accepted"
            assert res["error"] is not None

    def test_destructive_keywords_rejected(self):
        destructive = [
            "DELETE FROM retail_sales WHERE 1=1;",
            "DROP TABLE retail_sales;",
            "TRUNCATE TABLE retail_sales;",
            "UPDATE retail_sales SET total_amount = 0;",
            "INSERT INTO retail_sales (transaction_id) VALUES (1001);",
            "ALTER TABLE retail_sales DROP COLUMN age;",
            "CREATE TABLE admin_user (id INT, pw TEXT);",
            "GRANT ALL ON retail_sales TO public;",
            "REVOKE SELECT ON retail_sales FROM public;",
            "COPY retail_sales TO '/tmp/dump.csv';",
        ]
        for sql in destructive:
            res = validate_sql(sql)
            assert res["valid"] is False, f"Expected rejection for '{sql}', but was accepted"

    def test_multi_statement_and_comments_rejected(self):
        attacks = [
            "SELECT * FROM retail_sales; DROP TABLE retail_sales;",
            "SELECT * FROM retail_sales -- comment to bypass",
            "SELECT * FROM retail_sales /* block comment */",
            "SELECT 1; SELECT 2;",
        ]
        for sql in attacks:
            res = validate_sql(sql)
            assert res["valid"] is False, f"Expected rejection for '{sql}', but was accepted"

    def test_dangerous_system_functions_rejected(self):
        dangerous = [
            "SELECT PG_SLEEP(10) FROM retail_sales;",
            "SELECT PG_READ_FILE('/etc/passwd') FROM retail_sales;",
            "SELECT DBLINK('host=attacker.com', 'SELECT 1') FROM retail_sales;",
            "SELECT * FROM retail_sales INTO OUTFILE '/tmp/dump';",
        ]
        for sql in dangerous:
            res = validate_sql(sql)
            assert res["valid"] is False, f"Expected rejection for '{sql}', but was accepted"

