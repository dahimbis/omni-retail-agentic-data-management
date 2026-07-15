"""Load raw OmniRetail files from input_data into DuckDB staging tables."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_ROOT / "input_data"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
DUCKDB_PATH = OUTPUT_DIR / "curated.duckdb"

REQUIRED_COLUMNS = {
    "customers.csv": {
        "customer_id",
        "first_name",
        "last_name",
        "email",
        "phone",
        "country",
        "state",
        "signup_date",
        "loyalty_tier",
    },
    "products.csv": {
        "product_id",
        "product_name",
        "category",
        "unit_price",
        "active_flag",
    },
    "orders.csv": {
        "order_id",
        "customer_id",
        "order_ts",
        "product_id",
        "quantity",
        "order_status",
        "shipping_state",
        "order_total",
    },
    "payments.csv": {
        "payment_id",
        "order_id",
        "payment_ts",
        "payment_method",
        "payment_status",
        "amount",
    },
    "support_tickets.jsonl": {
        "ticket_id",
        "customer_id",
        "created_ts",
        "channel",
        "category",
        "sentiment",
        "description",
    },
}

COUNTRY_MAP = {
    "usa": "USA",
    "us": "USA",
    "united states": "USA",
    "united states of america": "USA",
}

STATE_MAP = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "district of columbia": "DC",
}


def standardize_country(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    return COUNTRY_MAP.get(text.lower(), text.upper())


def standardize_state(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    key = text.lower()
    if key in STATE_MAP:
        return STATE_MAP[key]
    if len(text) == 2:
        return text.upper()
    return text


def connect(
    db_path: Path | None = None, *, reset: bool = False
) -> duckdb.DuckDBPyConnection:
    path = db_path or DUCKDB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if reset and path.exists():
        path.unlink()
    return duckdb.connect(str(path))


def _load_jsonl(path: Path) -> pd.DataFrame:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid JSON in {path.name} at line {line_number}: {exc.msg}"
                    ) from exc
    return pd.DataFrame(rows)


def _validate_source(path: Path, frame: pd.DataFrame) -> None:
    required = REQUIRED_COLUMNS[path.name]
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(
            f"{path.name} is missing required column(s): {', '.join(missing)}"
        )


def ingest_raw(con: duckdb.DuckDBPyConnection, input_dir: Path | None = None) -> None:
    raw_dir = input_dir or INPUT_DIR
    if not raw_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {raw_dir}")

    source_paths = {name: raw_dir / name for name in REQUIRED_COLUMNS}
    missing_files = [name for name, path in source_paths.items() if not path.exists()]
    if missing_files:
        raise FileNotFoundError(
            f"Missing required input file(s): {', '.join(sorted(missing_files))}"
        )

    customers = pd.read_csv(source_paths["customers.csv"], dtype=str)
    products = pd.read_csv(source_paths["products.csv"], dtype=str)
    orders = pd.read_csv(source_paths["orders.csv"], dtype=str)
    payments = pd.read_csv(source_paths["payments.csv"], dtype=str)
    tickets = _load_jsonl(source_paths["support_tickets.jsonl"])

    for filename, frame in [
        ("customers.csv", customers),
        ("products.csv", products),
        ("orders.csv", orders),
        ("payments.csv", payments),
        ("support_tickets.jsonl", tickets),
    ]:
        _validate_source(source_paths[filename], frame)

    for name, frame in [
        ("stg_customers", customers),
        ("stg_products", products),
        ("stg_orders", orders),
        ("stg_payments", payments),
        ("stg_support_tickets", tickets),
    ]:
        con.register(f"{name}_df", frame)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM {name}_df")
        con.unregister(f"{name}_df")
