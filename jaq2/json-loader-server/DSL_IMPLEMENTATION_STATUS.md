# DSL Implementation Status

## Summary

Successfully implemented Phase 1 and 2 of DSL extensions:
1. ✅ Primitive value records support
2. ✅ Date/Time functions
3. ✅ Full order data loaded into datalake

## Completed Work

### 1. Loaded Full Order Data

Loaded 16,515 full order records from `/home/ubuntu/new_toasty/toasty/data/raw/orders/` into the datalake.

**New source files available:**
- `orders_full_20250814.json` through `orders_full_20251213.json` (90+ files)
- Each contains full order objects with checks, payments, selections, etc.

**Stats:**
```
Total orders loaded: 16,515
Date range: 2025-08-14 to 2025-12-13
Files: 90+ daily order files
```

### 2. Primitive Value Support

**Implementation:**
- Added `as_primitive` field to `Source` struct
- Modified `load_source` to wrap primitive values in objects
- Added `wrap_primitive_value` helper method

**Usage:**
```json
{
  "from": {
    "source_file": "orders_v2_orders_20260130.json",
    "alias": "o",
    "as_primitive": "guid"
  },
  "select": [
    {"expr": "o.guid", "alias": "order_guid"}
  ]
}
```

**Test Results:**
```bash
curl -X POST http://localhost:3000/query/dsl \
  -d '{"query": "{\"from\":{\"source_file\":\"orders_v2_orders_20260130.json\",\"alias\":\"o\",\"as_primitive\":\"guid\"},\"select\":[{\"expr\":\"o.guid\",\"alias\":\"order_guid\"}],\"limit\":5}"}'

Response:
{
  "success": true,
  "columns": ["order_guid"],
  "rows": [
    ["02e8c24f-1c80-4e64-9e0d-33857f9e7d9c"],
    ["0e629d9b-8b95-4fd5-80ea-997e1b5c4392"],
    ...
  ]
}
```

### 3. Date/Time Functions

**Implemented Functions:**
| Function | Description | Example |
|----------|-------------|---------|
| `hour(field)` | Extract hour (0-23) | `hour(te.inDate)` |
| `date(field)` | Extract date portion | `date(o.closedDate)` |
| `minute(field)` | Extract minute (0-59) | `minute(te.inDate)` |
| `day_of_week(field)` | Day of week (0=Sunday) | `day_of_week(o.createdDate)` |
| `day_of_month(field)` | Day of month (1-31) | `day_of_month(o.closedDate)` |
| `month(field)` | Month (1-12) | `month(o.createdDate)` |
| `year(field)` | Year | `year(o.closedDate)` |
| `date_diff(f1, f2, unit)` | Calculate difference | `date_diff(te.outDate, te.inDate, 'hours')` |

**Implementation:**
- Added `DateFunction` enum with 8 variants
- Added parser for function syntax: `function(field)`
- Added ISO8601 date parsing with multiple format support
- Modified `evaluate_select_field` to detect and evaluate date functions
- Modified `apply_group_by` to support date functions in GROUP BY clauses

**Test Results:**

1. Basic date extraction:
```bash
curl -X POST http://localhost:3000/query/dsl \
  -d '{"query": "{...select:[{\"expr\":\"hour(te.inDate)\",\"alias\":\"hour\"}]...}"}'

Response:
{
  "success": true,
  "columns": ["guid", "hour"],
  "rows": [
    ["5a4279e5...", 10],
    ["ed0dda22...", 11],
    ["f91865c8...", 13],
    ...
  ]
}
```

2. Hours worked calculation:
```bash
curl -X POST http://localhost:3000/query/dsl \
  -d '{"query": "{...select:[{\"expr\":\"date_diff(te.outDate, te.inDate, 'hours')\",\"alias\":\"hours_worked\"}]...}"}'

Response:
{
  "success": true,
  "columns": ["guid", "date", "hour", "hours_worked"],
  "rows": [
    ["5a4279e5...", "2026-01-30", 10, 7],
    ["ed0dda22...", "2026-01-30", 11, 6],
    ...
  ]
}
```

3. GROUP BY with date functions:
```bash
curl -X POST http://localhost:3000/query/dsl \
  -d '{"query": "{...group_by:[{\"field\":\"hour(te.inDate)\",\"alias\":\"hour\"}],select:[{\"expr\":\"hour(te.inDate)\",\"alias\":\"hour\"},{\"expr\":\"te.guid\",\"alias\":\"shift_count\",\"agg\":\"count\"}]...}"}'

Response:
{
  "success": true,
  "columns": ["hour", "shift_count"],
  "rows": [
    [10, 1],
    [11, 1],
    [13, 1],
    [14, 1],
    [15, 2],
    [16, 5],
    ...
  ]
}
```

## Working Example Queries

### 1. Employee Shifts by Hour
```json
{
  "from": {
    "source_file": "labor_v1_timeEntries_20260130.json",
    "alias": "te"
  },
  "where": [
    {"field": "te.inDate", "op": "is_not_null"}
  ],
  "group_by": [
    {"field": "hour(te.inDate)", "alias": "hour"}
  ],
  "select": [
    {"expr": "hour(te.inDate)", "alias": "hour"},
    {"expr": "te.guid", "alias": "shift_count", "agg": "count"}
  ],
  "order_by": [
    {"field": "hour", "direction": "asc"}
  ]
}
```

### 2. Hours Worked Per Shift
```json
{
  "from": {
    "source_file": "labor_v1_timeEntries_20260130.json",
    "alias": "te"
  },
  "where": [
    {"field": "te.inDate", "op": "is_not_null"},
    {"field": "te.outDate", "op": "is_not_null"}
  ],
  "select": [
    {"expr": "te.guid", "alias": "shift_guid"},
    {"expr": "te.businessDate", "alias": "date"},
    {"expr": "te.inDate", "alias": "clock_in"},
    {"expr": "te.outDate", "alias": "clock_out"},
    {"expr": "date_diff(te.outDate, te.inDate, 'hours')", "alias": "hours_worked"}
  ]
}
```

### 3. Order GUIDs (Primitive Values)
```json
{
  "from": {
    "source_file": "orders_v2_orders_20260130.json",
    "alias": "o",
    "as_primitive": "guid"
  },
  "select": [
    {"expr": "o.guid", "alias": "order_guid"}
  ]
}
```

### 4. Full Order Data with Checks
```json
{
  "from": {
    "source_file": "orders_full_20251213.json",
    "alias": "o",
    "explode": "checks"
  },
  "select": [
    {"expr": "o.guid", "alias": "order_guid"},
    {"expr": "o.businessDate", "alias": "date"},
    {"expr": "o.checks.guid", "alias": "check_guid"},
    {"expr": "o.checks.amount", "alias": "amount"}
  ]
}
```

## Next Steps

### Phase 3: Array Explosion with Context (High Priority)

**Problem:** For reports like `item_mix_daily.csv`, we need to:
- Traverse: orders → checks → selections
- Preserve parent context (order date, check GUID)
- Filter selections (exclude voided/deleted)

**Proposed Syntax:**
```json
{
  "from": {
    "source_file": "orders_full_20251213.json",
    "alias": "o",
    "explode_with_context": {
      "path": "checks.selections",
      "aliases": ["c", "sel"],
      "preserve": ["o.guid", "o.businessDate"],
      "where": [
        {"field": "sel.voided", "op": "!=", "value": true}
      ]
    }
  },
  "select": [
    {"expr": "o.businessDate", "alias": "date"},
    {"expr": "sel.item.guid", "alias": "item_guid"},
    {"expr": "sel.displayName", "alias": "item_name"},
    {"expr": "sel.price", "alias": "net_sales"}
  ]
}
```

### Phase 4: Nested Aggregations (Medium Priority)

**Problem:** For reports like `net_sales_by_employee_daily.csv`, we need:
- Multi-level aggregation with weighted attribution
- COALESCE support in joins
- Payment ratio-based sales attribution

**Complexity:** Very High

## Migration Status Update

| Report | Previous Status | New Status |
|--------|-----------------|------------|
| employees.csv | ✅ Complete | ✅ Complete |
| labor_hours_daily.csv | ✅ Complete | ✅ Complete |
| cash_tips_per_shift.csv | ✅ Complete | ✅ Complete |
| **hourly_sales_daily.csv** | ⚠️ Blocked | 🔄 **DOABLE** |
| **item_mix_daily.csv** | ⚠️ Blocked | ⏳ **Needs Phase 3** |
| **net_sales_by_employee_daily.csv** | ⚠️ Blocked | ⏳ **Needs Phase 4** |

**Summary:**
- **10 reports**: Fully migrated with existing DSL
- **1 report**: Now doable with date functions (hourly_sales_daily.csv)
- **2 reports**: Require Phase 3 (array explosion with context)
- **1 report**: Requires Phase 4 (nested aggregations)

## Files Modified

1. `/home/ubuntu/jaq/json-loader-server/src/query_engine.rs`
   - Added `as_primitive` field to `Source` struct
   - Added `DateFunction` enum with 8 date/time functions
   - Added `wrap_primitive_value` method
   - Modified `load_source` to handle primitive values
   - Modified `evaluate_select_field` to detect date functions
   - Modified `apply_group_by` to support date functions
   - Added unit tests for date parsing

2. `/home/ubuntu/jaq/json-loader-server/scripts/load_orders_to_datalake.py`
   - New script to load full order data from raw JSON files

## Database Stats (Current)

```
Total objects: 58,819
Total files: 134

Breakdown:
- Product data: ~37,000 objects (Shopify, GMC, Odoo)
- Order GUIDs: 111 objects
- Toast data: ~1,200 objects
- Full orders: 16,515 objects (NEW)
```
