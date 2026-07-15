# Source-to-Curated Reconciliation

This report shows how source records move into audit and curated tables. Counts and amounts are generated from DuckDB on every pipeline run.

## Row-count bridge

| dataset | raw_rows | canonical_audit_rows | curated_rows | explanation |
| --- | --- | --- | --- | --- |
| Customers | 20 | 19 | 19 | Repeated customer IDs resolved before loading dim_customer |
| Orders | 31 | 30 | 28 | Duplicate order IDs resolved; invalid customer/product keys remain in int_order |
| Payments | 30 | 30 | 27 | Orphan and quarantined-order payments remain in int_payment |
| Support tickets | 10 | 10 | 9 | Invalid customer keys excluded; malformed timestamps retained with null date |

## Completed-revenue bridge

| line_item | order_count | gross_amount |
| --- | --- | --- |
| Completed positive-quantity candidates | 27 | 1281.85 |
| Less: invalid-FK orders quarantined | -2 | -37.98 |
| Equals: revenue-eligible fact orders | 25 | 1243.87 |
| Reconciliation difference | 0 | 0.00 |

The zero reconciliation difference confirms that completed positive-quantity candidate revenue equals revenue-eligible fact revenue after removing invalid customer/product references.

## Interpretation

- O1019 and O1020 remain auditable but are excluded from `fact_order` because their customer or product references are invalid.
- O1030 remains in `fact_order` for audit context but is not revenue-eligible because its quantity is negative.
- Payment and catalog quality exceptions do not silently change the documented order-revenue definition.
