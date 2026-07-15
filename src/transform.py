"""Build curated dimensions/facts aligned to Take-home suggested target model."""

from __future__ import annotations

from datetime import datetime

import duckdb
import pandas as pd

from src.ingest import standardize_country, standardize_state

TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%m/%d/%Y %H:%M",
    "%Y/%m/%d %H:%M",
    "%m-%d-%Y %H:%M",
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%m-%d-%Y",
)


def parse_timestamp(value: object) -> datetime | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "bad_timestamp"}:
        return None
    if text.endswith("Z") and "T" in text:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    for fmt in TS_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return pd.to_datetime(text, utc=False).to_pydatetime()
    except (ValueError, TypeError):
        return None


def _completeness_score(row: pd.Series) -> int:
    fields = ["email", "phone", "first_name", "last_name", "country", "state", "loyalty_tier"]
    return sum(1 for f in fields if pd.notna(row.get(f)) and str(row.get(f)).strip())


def _clean_phone(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def build_dim_customer(customers: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = customers.copy()
    df["source_row"] = range(len(df))
    df["signup_parsed"] = df["signup_date"].map(parse_timestamp)
    df["completeness"] = df.apply(_completeness_score, axis=1)
    df = df.sort_values(
        by=["customer_id", "signup_parsed", "completeness", "source_row"],
        ascending=[True, True, False, True],
        na_position="last",
        kind="stable",
    )
    kept = df.drop_duplicates(subset=["customer_id"], keep="first").copy()
    dropped_ids = set(df.loc[~df.index.isin(kept.index), "customer_id"].astype(str))

    kept["full_name"] = (
        kept["first_name"].fillna("").astype(str).str.strip()
        + " "
        + kept["last_name"].fillna("").astype(str).str.strip()
    ).str.strip()
    kept["email"] = kept["email"].apply(
        lambda x: str(x).strip().lower() if pd.notna(x) and str(x).strip() else None
    )
    kept["phone"] = kept["phone"].map(_clean_phone)
    kept["standard_country"] = kept["country"].map(standardize_country)
    kept["standard_state"] = kept["state"].map(standardize_state)
    kept["signup_date"] = kept["signup_parsed"].map(lambda x: x.date() if x else None)
    kept["loyalty_tier"] = kept["loyalty_tier"].apply(
        lambda x: str(x).strip() if pd.notna(x) and str(x).strip() else None
    )
    kept["duplicate_resolution_flag"] = kept["customer_id"].astype(str).isin(dropped_ids)

    dim = kept.rename(columns={"customer_id": "customer_key"})[
        [
            "customer_key",
            "full_name",
            "email",
            "phone",
            "standard_country",
            "standard_state",
            "signup_date",
            "loyalty_tier",
            "duplicate_resolution_flag",
        ]
    ].reset_index(drop=True)

    dropped = df.loc[~df.index.isin(kept.index)].copy()
    exceptions = pd.DataFrame(
        {
            "rule_id": "TRANSFORM_DEDUP_CUSTOMER",
            "dataset": "customers",
            "record_key": dropped["customer_id"].astype(str),
            "severity": "High",
            "issue_description": "Duplicate customer_id dropped; kept earliest/most-complete row",
            "suggested_action": "Merge profiles in source MDM and retain single survivor key",
        }
    )
    return dim, exceptions


def build_dim_product(products: pd.DataFrame) -> pd.DataFrame:
    df = products.copy()
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
    return (
        df.rename(columns={"product_id": "product_key"})[
            ["product_key", "product_name", "category", "unit_price", "active_flag"]
        ]
        .drop_duplicates(subset=["product_key"], keep="first")
        .reset_index(drop=True)
    )


def build_fact_order(
    orders: pd.DataFrame,
    dim_customer: pd.DataFrame,
    dim_product: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = orders.copy()
    df["order_parsed"] = df["order_ts"].map(parse_timestamp)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["order_total"] = pd.to_numeric(df["order_total"], errors="coerce")
    df["shipping_state"] = df["shipping_state"].map(standardize_state)
    df = df.sort_values(by=["order_id", "order_parsed"], ascending=[True, True])
    kept = df.drop_duplicates(subset=["order_id"], keep="first").copy()
    dropped = df.loc[~df.index.isin(kept.index)].copy()

    dedup_ex = pd.DataFrame(
        {
            "rule_id": "TRANSFORM_DEDUP_ORDER",
            "dataset": "orders",
            "record_key": dropped["order_id"].astype(str),
            "severity": "High",
            "issue_description": "Duplicate order_id dropped",
            "suggested_action": "Investigate source double-write; keep single canonical order row",
        }
    )

    price_map = dim_product.set_index("product_key")["unit_price"].to_dict()
    cust_keys = set(dim_customer["customer_key"])
    prod_keys = set(dim_product["product_key"])
    kept["valid_customer"] = kept["customer_id"].isin(cust_keys)
    kept["valid_product"] = kept["product_id"].isin(prod_keys)
    kept["unit_price"] = kept["product_id"].map(price_map)
    kept["calculated_order_amount"] = (kept["quantity"] * kept["unit_price"]).round(2)
    kept["order_amount_variance"] = (
        kept["order_total"] - kept["calculated_order_amount"]
    ).round(2)
    kept["is_revenue_eligible"] = (
        kept["order_status"].str.lower().eq("completed")
        & kept["quantity"].gt(0)
        & kept["order_parsed"].notna()
        & kept["valid_customer"]
        & kept["valid_product"]
    )

    fk_rows = []
    invalid_mask = ~(kept["valid_customer"] & kept["valid_product"])
    for _, row in kept.loc[invalid_mask].iterrows():
        reasons = []
        if not row["valid_customer"]:
            reasons.append(f"invalid customer_id={row['customer_id']}")
        if not row["valid_product"]:
            reasons.append(f"invalid product_id={row['product_id']}")
        fk_rows.append(
            {
                "rule_id": "TRANSFORM_ORDER_FK",
                "dataset": "orders",
                "record_key": row["order_id"],
                "severity": "High",
                "issue_description": "; ".join(reasons),
                "suggested_action": "Quarantine order until dimension keys are repaired",
            }
        )
    fk_ex = pd.DataFrame(fk_rows)

    int_order = kept.rename(
        columns={
            "order_id": "order_key",
            "customer_id": "customer_key",
            "product_id": "product_key",
            "order_total": "gross_order_amount",
        }
    ).copy()
    int_order["order_date"] = int_order["order_parsed"].map(lambda x: x.date() if x else None)
    int_order = int_order[
        [
            "order_key",
            "customer_key",
            "product_key",
            "order_date",
            "quantity",
            "order_status",
            "shipping_state",
            "gross_order_amount",
            "calculated_order_amount",
            "order_amount_variance",
            "is_revenue_eligible",
            "valid_customer",
            "valid_product",
        ]
    ].reset_index(drop=True)

    fact = int_order.loc[int_order["valid_customer"] & int_order["valid_product"]].drop(
        columns=["valid_customer", "valid_product"]
    ).reset_index(drop=True)

    return fact, int_order, pd.concat([dedup_ex, fk_ex], ignore_index=True)


def build_fact_payment(
    payments: pd.DataFrame,
    fact_order: pd.DataFrame,
    int_order: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = payments.copy()
    df["source_row"] = range(len(df))
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["payment_parsed"] = df["payment_ts"].map(parse_timestamp)
    df = df.sort_values(
        by=["payment_id", "payment_parsed", "source_row"],
        ascending=[True, True, True],
        na_position="last",
        kind="stable",
    )
    kept = df.drop_duplicates(subset=["payment_id"], keep="first").copy()
    dropped = df.loc[~df.index.isin(kept.index)]
    dedup_ex = pd.DataFrame(
        {
            "rule_id": "TRANSFORM_DEDUP_PAYMENT",
            "dataset": "payments",
            "record_key": dropped["payment_id"].astype(str),
            "severity": "High",
            "issue_description": "Duplicate payment_id dropped",
            "suggested_action": "Investigate payment source double-write and retain one canonical row",
        }
    )
    df = kept
    known_orders = set(int_order["order_key"]) | set(fact_order["order_key"])
    curated_keys = set(fact_order["order_key"])
    df["valid_order"] = df["order_id"].isin(known_orders)
    df["in_curated_order"] = df["order_id"].isin(curated_keys)

    orphan = df.loc[~df["valid_order"]].copy()
    orphan_ex = pd.DataFrame(
        {
            "rule_id": "TRANSFORM_PAYMENT_ORPHAN",
            "dataset": "payments",
            "record_key": orphan["payment_id"].astype(str),
            "severity": "High",
            "issue_description": orphan["order_id"].map(
                lambda x: f"orphan payment order_id={x}"
            ),
            "suggested_action": "Reject or hold payment until matching order is loaded",
        }
    )

    int_payment = df.rename(
        columns={
            "payment_id": "payment_key",
            "order_id": "order_key",
            "amount": "payment_amount",
        }
    ).copy()
    int_payment["payment_date"] = int_payment["payment_parsed"].map(
        lambda x: x.date() if x else None
    )
    int_payment = int_payment[
        [
            "payment_key",
            "order_key",
            "payment_date",
            "payment_method",
            "payment_status",
            "payment_amount",
            "valid_order",
            "in_curated_order",
        ]
    ].reset_index(drop=True)

    fact = int_payment.loc[int_payment["in_curated_order"]].drop(
        columns=["valid_order", "in_curated_order"]
    ).reset_index(drop=True)
    return fact, int_payment, pd.concat([dedup_ex, orphan_ex], ignore_index=True)


def build_fact_customer_issue(
    tickets: pd.DataFrame,
    dim_customer: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = tickets.copy()
    df["created_parsed"] = df["created_ts"].map(parse_timestamp)
    df["parse_ok"] = df["created_parsed"].notna()
    cust_keys = set(dim_customer["customer_key"])
    df["valid_customer"] = df["customer_id"].isin(cust_keys)

    exceptions = []
    for _, row in df.iterrows():
        if not row["parse_ok"]:
            exceptions.append(
                {
                    "rule_id": "TRANSFORM_TICKET_TS",
                    "dataset": "support_tickets",
                    "record_key": row["ticket_id"],
                    "severity": "Medium",
                    "issue_description": f"unparseable created_ts={row['created_ts']}",
                    "suggested_action": "Fix source timestamp encoding and re-ingest ticket",
                }
            )
        if not row["valid_customer"]:
            exceptions.append(
                {
                    "rule_id": "TRANSFORM_TICKET_FK",
                    "dataset": "support_tickets",
                    "record_key": row["ticket_id"],
                    "severity": "Medium",
                    "issue_description": f"invalid customer_id={row['customer_id']}",
                    "suggested_action": "Map ticket to surviving customer_key or quarantine",
                }
            )

    int_issue = df.rename(
        columns={"customer_id": "customer_key", "category": "issue_category"}
    ).copy()
    int_issue["created_date"] = int_issue["created_parsed"].map(
        lambda x: x.date() if x else None
    )
    int_issue = int_issue[
        [
            "ticket_id",
            "customer_key",
            "created_date",
            "channel",
            "issue_category",
            "sentiment",
            "description",
            "created_ts",
            "parse_ok",
            "valid_customer",
        ]
    ].reset_index(drop=True)

    fact = int_issue.loc[int_issue["valid_customer"]][
        [
            "ticket_id",
            "customer_key",
            "created_date",
            "channel",
            "issue_category",
            "sentiment",
            "description",
        ]
    ].reset_index(drop=True)
    return fact, int_issue, pd.DataFrame(exceptions)


def build_fuzzy_customer_flags(raw_customers: pd.DataFrame) -> pd.DataFrame:
    phones = raw_customers.copy()
    phones["phone"] = phones["phone"].map(_clean_phone)
    phone_counts = phones.dropna(subset=["phone"]).groupby("phone")["customer_id"].nunique()
    shared = phone_counts[phone_counts > 1].index
    flagged = phones.loc[phones["phone"].isin(shared), ["customer_id", "phone"]]
    if flagged.empty:
        return pd.DataFrame(
            columns=[
                "rule_id",
                "dataset",
                "record_key",
                "severity",
                "issue_description",
                "suggested_action",
            ]
        )
    return pd.DataFrame(
        {
            "rule_id": "INFO_FUZZY_CUSTOMER_PHONE",
            "dataset": "customers",
            "record_key": flagged["customer_id"].astype(str),
            "severity": "Medium",
            "issue_description": flagged["phone"].map(
                lambda p: f"shared phone {p} with other customer_id(s); not merged"
            ),
            "suggested_action": "Review for customer-360 merge; keep separate keys until confirmed",
        }
    )


def _register(con: duckdb.DuckDBPyConnection, name: str, frame: pd.DataFrame) -> None:
    con.register(f"{name}_df", frame)
    con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM {name}_df")
    con.unregister(f"{name}_df")


def transform_all(con: duckdb.DuckDBPyConnection) -> None:
    customers = con.execute("SELECT * FROM stg_customers").df()
    products = con.execute("SELECT * FROM stg_products").df()
    orders = con.execute("SELECT * FROM stg_orders").df()
    payments = con.execute("SELECT * FROM stg_payments").df()
    tickets = con.execute("SELECT * FROM stg_support_tickets").df()

    dim_customer, cust_ex = build_dim_customer(customers)
    dim_product = build_dim_product(products)
    fact_order, int_order, order_ex = build_fact_order(orders, dim_customer, dim_product)
    fact_payment, int_payment, pay_ex = build_fact_payment(payments, fact_order, int_order)
    fact_issue, int_issue, ticket_ex = build_fact_customer_issue(tickets, dim_customer)
    fuzzy_ex = build_fuzzy_customer_flags(customers)

    transform_exceptions = pd.concat(
        [cust_ex, order_ex, pay_ex, ticket_ex, fuzzy_ex], ignore_index=True
    )

    _register(con, "dim_customer", dim_customer)
    _register(con, "dim_product", dim_product)
    _register(con, "fact_order", fact_order)
    _register(con, "fact_payment", fact_payment)
    _register(con, "fact_customer_issue", fact_issue)
    _register(con, "int_order", int_order)
    _register(con, "int_payment", int_payment)
    _register(con, "int_customer_issue", int_issue)
    _register(con, "transform_exceptions", transform_exceptions)
