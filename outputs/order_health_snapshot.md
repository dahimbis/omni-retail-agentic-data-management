# Order health snapshot

`Completed` describes the source order status; it does not mean the order passed every quality check. Each completed order appears in one group. An order is placed in the identified-issues group when it has at least one related entry in `dq_exception_report`.

| category | order_count |
| --- | --- |
| Completed: no identified issues | 21 |
| Completed: identified issues | 7 |

![Order health snapshot](charts/readme_order_health.png)
