# DSL Extension Review Summary

## Overview

This document summarizes the review of `/home/ubuntu/jaq/json-loader-server` and `/home/ubuntu/new_toasty/toasty/DSL` directories, with recommendations for extending the DSL to handle complex Toast data reports.

---

## Current State Analysis

### Existing DSL Capabilities (in `/home/ubuntu/jaq/json-loader-server/src/query_engine.rs`)

| Feature | Status | Notes |
|---------|--------|-------|
| Basic SELECT | ✅ | Field selection with aliases |
| JOINs | ✅ | Inner, Left, Right, Full, Cross |
| Array joins | ✅ | `field[]` notation |
| WHERE clauses | ✅ | Multiple operators (=, !=, <, >, etc.) |
| GROUP BY | ✅ | With aggregation (sum, count, avg, min, max) |
| ORDER BY | ✅ | Multi-column sorting |
| LIMIT/OFFSET | ✅ | Pagination |
| CTEs (WITH) | ✅ | Subquery support |
| explode | ✅ | Single-level array flattening |
| Wildcard select | ✅ | `alias.*` expansion |
| CASE expressions | ✅ | Conditional logic in SELECT |
| COALESCE | ✅ | Fallback values |
| skip_nulls | ✅ | Join option |

### Existing DSL Queries (in `/home/ubuntu/new_toasty/toasty/DSL/queries/`)

**10 Fully Working Queries:**
1. `01_employees.dsl.json` - Simple SELECT
2. `02_jobs.dsl.json` - Simple SELECT
3. `03_revenue_centers.dsl.json` - Simple SELECT
4. `04_labor_hours_daily.dsl.json` - GROUP BY with aggregation
5. `05_labor_shifts_detailed_daily.dsl.json` - JOINs
6. `06_cash_tips_per_shift.dsl.json` - JOINs with WHERE
7. `07_gratuity_per_shift.dsl.json` - JOINs
8. `08_cash_summary_daily.dsl.json` - GROUP BY with aggregation
9. `09_cash_entries_detailed.dsl.json` - JOINs
10. `10_payments_summary.dsl.json` - Simple query

### CSV Reports Status

| CSV Report | Status | Blocker |
|------------|--------|---------|
| employees.csv | ✅ Migrated | - |
| labor_hours_daily.csv | ✅ Migrated | - |
| labor_shifts_detailed_daily.csv | ✅ Migrated | - |
| cash_tips_per_shift.csv | ✅ Migrated | - |
| gratuity_per_shift.csv | ✅ Migrated | - |
| cash_summary_daily.csv | ✅ Migrated | - |
| **net_sales_by_employee_daily.csv** | ⚠️ **BLOCKED** | Nested aggregation + attribution logic |
| **item_mix_daily.csv** | ⚠️ **BLOCKED** | Multi-level array explosion |
| **category_sales_daily.csv** | ⚠️ **BLOCKED** | Depends on item_mix |
| **discounts_daily.csv** | ⚠️ **BLOCKED** | Nested array explosion |
| **hourly_sales_daily.csv** | ⚠️ **BLOCKED** | Date extraction functions |
| payments_tips_daily.csv | ⚠️ BLOCKED | Nested aggregation |
| voids_daily.csv | ⚠️ BLOCKED | Complex filtering |
| tips_by_server_daily.csv | ⚠️ BLOCKED | Payment aggregation |

---

## Required DSL Extensions

### 1. Primitive Value Records

**Problem:** `orders_v2_orders_20260130.json` contains only GUID strings, not objects.

```json
// Current data format
"c4932a6c-acb6-4869-ac9f-0de76b837778"
```

**Solution:** Add `as_primitive` option to wrap primitives in objects.

```json
{
  "from": {
    "source_file": "orders_v2_orders_20260130.json",
    "alias": "o",
    "as_primitive": "guid"
  },
  "select": [{"expr": "o.guid", "alias": "order_guid"}]
}
```

**Complexity:** Low
**Impact:** Enables querying GUID reference files

---

### 2. Date/Time Functions

**Problem:** `hourly_sales_daily.csv` needs hour extraction from datetime strings.

```python
# Python code being replaced
closed = _parse_iso(check.get("closedDate"))
hour = closed.hour
```

**Solution:** Add date function evaluation to expressions.

```json
{
  "group_by": [
    {"field": "hour(o.closedDate)", "is_expr": true}
  ],
  "select": [
    {"expr": "hour(o.closedDate)", "alias": "hour"},
    {"expr": "sum(c.amount)", "alias": "net_sales"}
  ]
}
```

**Required Functions:**
- `hour(field)` - Extract hour (0-23)
- `date(field)` - Extract date portion
- `date_diff(f1, f2, unit)` - Calculate difference
- `day_of_week(field)`, `month(field)`, `year(field)`

**Complexity:** Medium
**Impact:** Enables time-based reports

---

### 3. Array Explosion with Context

**Problem:** `item_mix_daily.csv` needs to traverse `orders.checks.selections` while preserving parent context.

```python
# Python code being replaced
for order in orders:
    for check in order.get("checks", []):
        for sel in check.get("selections", []):
            item_mix_rows.append({
                "date": order["businessDate"],  # Parent context
                "item_guid": sel["item"]["guid"],  # Leaf value
            })
```

**Solution:** Add `explode_with_context` for multi-level array traversal.

```json
{
  "from": {
    "source_file": "orders.json",
    "alias": "o",
    "explode_with_context": {
      "path": "checks.selections",
      "aliases": ["c", "sel"],
      "preserve": ["o.guid", "o.businessDate"],
      "where": [
        {"field": "sel.voided", "op": "!=", "value": true}
      ]
    }
  }
}
```

**Complexity:** High
**Impact:** Enables item_mix, discounts, and complex order reports

---

### 4. Nested Aggregations

**Problem:** `net_sales_by_employee_daily.csv` requires:
- Traversing orders → checks → payments
- Weighted attribution by payment amount
- COALESCE fallback logic

```python
# Python code being replaced
for order in orders:
    for check in order.get("checks", []):
        payments = check.get("payments", [])
        server_amounts = {}
        for p in payments:
            srv = p.get("server", {}).get("guid")
            server_amounts[srv] = server_amounts.get(srv, 0.0) + p.get("amount", 0)
        
        # Attribute proportionally
        total_pay = sum(server_amounts.values())
        for srv, pay_amt in server_amounts.items():
            ratio = pay_amt / total_pay
            result[srv] = net_sales * ratio
```

**Solution:** Add nested aggregation with weighted distribution.

```json
{
  "from": {
    "source_file": "orders.json",
    "alias": "o",
    "explode_nested": {
      "path": "checks",
      "alias": "c",
      "nested": {
        "path": "c.payments",
        "alias": "p",
        "aggregate": {
          "group_by": ["p.server.guid"],
          "calculations": [
            {"expr": "sum(p.amount)", "alias": "payment_total"}
          ]
        }
      }
    }
  },
  "group_by": [
    {"field": "coalesce(p.server.guid, o.server.guid)"}
  ],
  "select": [
    {"expr": "sum(c.amount * (p.amount / payment_total))", "alias": "net_sales"}
  ]
}
```

**Complexity:** Very High
**Impact:** Enables all complex sales attribution reports

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1)
**Goal:** Enable basic blocked reports

| Task | Complexity | Files Modified |
|------|------------|----------------|
| Primitive value wrapping | Low | `query_engine.rs` |
| Date functions (hour, date, date_diff) | Medium | `query_engine.rs` |
| GROUP BY expression support | Medium | `query_engine.rs` |

**Deliverables:**
- Query primitive GUID lists
- `hourly_sales_daily.csv` report
- `time_entries` with calculated hours

### Phase 2: Array Operations (Week 2)
**Goal:** Enable item-level reports

| Task | Complexity | Files Modified |
|------|------------|----------------|
| `explode_with_context` | High | `query_engine.rs` |
| Multi-level path parsing | Medium | `query_engine.rs` |
| Context preservation | High | `query_engine.rs` |

**Deliverables:**
- `item_mix_daily.csv` report
- `discounts_daily.csv` report
- `category_sales_daily.csv` report

### Phase 3: Complex Aggregation (Week 3-4)
**Goal:** Enable sales attribution reports

| Task | Complexity | Files Modified |
|------|------------|----------------|
| Nested explosion | Very High | `query_engine.rs` |
| Weighted aggregation | High | `query_engine.rs` |
| COALESCE in joins | Medium | `query_engine.rs` |

**Deliverables:**
- `net_sales_by_employee_daily.csv` report
- `tips_by_server_daily.csv` report
- `payments_tips_daily.csv` report

---

## Files Created

| File | Description |
|------|-------------|
| `DSL_EXTENSION_SPEC.md` | Complete specification of all DSL extensions |
| `DSL_IMPLEMENTATION_GUIDE.md` | Step-by-step implementation instructions |
| `dsl_examples/01_orders_guid_list.dsl.json` | Primitive value example |
| `dsl_examples/02_payments_guid_list.dsl.json` | Primitive value example |
| `dsl_examples/03_time_entries_hourly.dsl.json` | Date function example |
| `dsl_examples/04_time_entries_with_hours_worked.dsl.json` | Date diff example |
| `dsl_examples/05_employee_jobs_exploded.dsl.json` | Array explosion example |
| `dsl_examples/06_cash_entries_by_type.dsl.json` | GROUP BY example |
| `dsl_examples/07_nested_aggregation_concept.dsl.json` | Conceptual nested aggregation |

---

## Key Data Insights

### Database Contents (`json_objects` table)

| Source File | Record Count | Type | Notes |
|-------------|--------------|------|-------|
| `labor_v1_employees.json` | ~45 | Object | Employee records |
| `labor_v1_jobs.json` | ~15 | Object | Job definitions |
| `labor_v1_timeEntries_20260130.json` | ~150 | Object | Time punches |
| `cashmgmt_v1_entries_20260130.json` | ~100 | Object | Cash transactions |
| `cashmgmt_v1_deposits_20260130.json` | ~10 | Object | Cash deposits |
| `orders_v2_orders_20260130.json` | ~500 | **Primitive** | Just GUIDs |
| `orders_v2_payments_20260130.json` | ~1000 | **Primitive** | Just GUIDs |
| `config_v2_revenueCenters.json` | ~5 | Object | Revenue centers |
| `configuration_v1_salesCategories.json` | ~10 | Object | Sales categories |
| `menus_v2_menus.json` | ~5 | Object | Menu data |

### Critical Observation

The `orders_v2_orders_20260130.json` and `orders_v2_payments_20260130.json` files contain **only primitive GUID values**, not full order/payment objects. This means:

1. ✅ Current DSL can query the GUIDs using `as_primitive` extension
2. ❌ Cannot perform complex sales analysis without full order data
3. ⚠️ Full order data must be loaded from `/home/ubuntu/new_toasty/toasty/data/raw/orders/`

---

## Recommendations

### Immediate Actions (This Week)

1. **Implement primitive value wrapping** - Low effort, high impact
2. **Implement date functions** - Enables hourly reports
3. **Load full order data** into datalake if complex reports are needed

### Short-term (Next 2 Weeks)

4. **Implement `explode_with_context`** - Enables item-level analysis
5. **Create DSL queries** for remaining simple reports

### Medium-term (Next Month)

6. **Implement nested aggregations** - Enables full sales attribution
7. **Build Shoelace UI components** that consume DSL queries
8. **Create saved queries** for commonly used reports

### Long-term

9. **Consider SQL-like query engine** if DSL complexity grows
10. **Implement query caching** for performance
11. **Add query result caching** with cache invalidation

---

## Appendix: Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    TOAST API                                     │
│  (labor, orders, cashmgmt, config, menus)                       │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              Python Fetch Scripts                                │
│  /home/ubuntu/new_toasty/toasty/toast_30d_report.py             │
│  /home/ubuntu/new_toasty/toasty/toast_client.py                 │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              Raw JSON Files                                      │
│  /home/ubuntu/new_toasty/toasty/data/raw/                       │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              JAQ JSON Loader Server                              │
│  http://localhost:3000                                          │
│  /home/ubuntu/jaq/json-loader-server/                           │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              DSL Queries                                         │
│  /home/ubuntu/new_toasty/toasty/DSL/queries/                    │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              CSV Reports                                         │
│  /home/ubuntu/new_toasty/toasty/data/reports/                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Questions for Stakeholders

1. **Full Order Data**: Should we load full order objects (with checks, payments, selections) into the datalake? Currently only GUIDs are stored.

2. **Attribution Mode**: The Python code supports 3 attribution modes (`payment_closer_closed_only`, `order_server`, `payment_prorated`). Which should the DSL implement?

3. **Performance**: For complex nested aggregations, should we:
   - A) Implement in DSL (complex but flexible)
   - B) Pre-process in Python (simpler but less flexible)
   - C) Hybrid approach

4. **Priority**: Which reports are most critical to migrate first?
