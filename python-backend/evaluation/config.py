"""
Configuration settings for the AI SQL Assistant Evaluation Suite.
"""

import os
import sys
from pathlib import Path

# Ensure python-backend root is on sys.path
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Evaluation directories
EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

LATEST_RESULTS_FILE = RESULTS_DIR / "latest_results.json"

# API & Database metadata
BACKEND_BASE_URL = "http://localhost:8000"
PRIMARY_TABLE = "retail_sales"

# Schema text for the LLM prompt (matches production Database Profiling output)
DEFAULT_SCHEMA_TEXT = """
Table: retail_sales

Columns:
transaction_id
date
customer_id
gender
age
product_category
quantity
price_per_unit
total_amount
created_at
""".strip()

# Allowed columns for schema validation
KNOWN_COLUMNS = {
    "transaction_id",
    "date",
    "customer_id",
    "gender",
    "age",
    "product_category",
    "quantity",
    "price_per_unit",
    "total_amount",
    "created_at",
}

# Known categorical values
KNOWN_CATEGORIES = {"Beauty", "Clothing", "Electronics"}
KNOWN_GENDERS = {"Female", "Male"}

