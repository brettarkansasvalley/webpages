# DSL Extension Specification for Toast Data Reports

## Executive Summary

Based on analysis of `/home/ubuntu/new_toasty/toasty/DSL/` and the CSV reports in `/home/ubuntu/new_toasty/toasty/data/reports/`, the current DSL needs four major extensions to handle complex Toast data reports:

1. **Complex Nested Aggregations** - For net_sales_by_employee_daily.csv
2. **Array Explosion with Context** - For item_mix_daily.csv  
3. **Date/Time Manipulations** - For hourly_sales_daily.csv
4. **Primitive Value Records** - For orders_v2_orders_20260130.json which stores just GUID strings

---

## 1. Complex Nested Aggregations

### Problem
The `net_sales_by_employee_daily.csv` requires:
- Traversing: orders → checks → payments
- Conditional aggregation (exclude voided/deleted)
- Multi-field attribution logic (payment server vs order server)
- Ratio-based distribution of sales across multiple payment servers

### Current Python Logic
```python
for order in orders:
    if is_voided_or_deleted(order): continue
    order_server = order.get("server", {}).get("guid")
    
    for check in order.get("checks", []):
        if is_voided_or_deleted(check): continue
        
        # Attribution strategy based on ATTRIBUTION_MODE
        payments = check.get("payments", [])
        
        # payment_prorated: distribute by payment amount ratio
        server_amounts = {}
        for p in payments:
            srv = p.get("server", {}).get("guid")
            server_amounts[srv] = server_amounts.get(srv, 0.0) + p.get("amount", 0)
        
        # Attribute sales proportionally
        total_pay = sum(server_amounts.values())
        for srv, pay_amt in server_amounts.items():
            ratio = pay_amt / total_pay
            result[srv] = (net_sales * ratio, total_sales * ratio, count)
```

### Proposed DSL Syntax

```json
{
  "_description": "Net sales by employee with nested aggregation",
  "from": {
    "source_file": "orders_v2_orders_20260130.json",
    "alias": "o",
    "explode_nested": {
      "path": "checks",
      "alias": "c",
      "where": [
        {"field": "c.voided", "op": "!=", "value": true},
        {"field": "c.deleted", "op": "!=", "value": true}
      ],
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
    {"field": "attributed_server", "expr": "coalesce(p.server.guid, o.server.guid)"}
  ],
  "select": [
    {"expr": "attributed_server", "alias": "employee_guid"},
    {"expr": "sum(c.amount * (p.amount / payment_total))", "alias": "net_sales"},
    {"expr": "sum(c.totalAmount * (p.amount / payment_total))", "alias": "total_sales"},
    {"expr": "count(distinct c.guid)", "alias": "checks_count"}
  ]
}
```

### Implementation Approach

Add new structures to `QueryDsl`:

```rust
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct NestedExplode {
    /// Path to array field (e.g., "checks")
    pub path: String,
    /// Alias for exploded items
    pub alias: String,
    /// Filter conditions on nested items
    #[serde(default)]
    pub r#where: Option<Vec<Condition>>,
    /// Deeper nesting (recursive)
    #[serde(default)]
    pub nested: Option<Box<NestedExplode>>,
    /// Aggregation at this nesting level
    #[serde(default)]
    pub aggregate: Option<NestedAggregate>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct NestedAggregate {
    pub group_by: Vec<String>,
    pub calculations: Vec<AggregateCalc>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct AggregateCalc {
    pub expr: String,
    pub alias: String,
}
```

---

## 2. Array Explosion with Context

### Problem
The `item_mix_daily.csv` requires:
- Exploding nested arrays: orders.checks[].selections[]
- Preserving parent context (order date, order GUID)
- Aggregating item quantities and sales

### Current Python Logic
```python
for order in orders:
    for check in order.get("checks", []):
        for sel in check.get("selections", []):
            if sel.get("voided") or sel.get("deleted"):
                continue
            item_mix_rows.append({
                "date": business_date_iso,
                "item_guid": sel.get("item", {}).get("guid"),
                "item_name": sel.get("displayName"),
                "quantity": sel.get("quantity", 1),
                "net_sales": sel.get("price"),
            })
```

### Proposed DSL Syntax

```json
{
  "_description": "Item mix with context preservation",
  "from": {
    "source_file": "orders_v2_orders_20260130.json",
    "alias": "o",
    "explode_with_context": {
      "path": "checks.selections",
      "aliases": ["c", "sel"],
      "preserve": ["o.guid", "o.businessDate", "o.server.guid"],
      "where": [
        {"field": "sel.voided", "op": "!=", "value": true},
        {"field": "sel.deleted", "op": "!=", "value": true}
      ]
    }
  },
  "joins": [
    {
      "source": {
        "source_file": "menus_v2_menus.json",
        "alias": "menu"
      },
      "on": {
        "left": "sel.item.guid",
        "right": "menu.items[].guid"
      },
      "join_type": "left"
    }
  ],
  "select": [
    {"expr": "o.businessDate", "alias": "date"},
    {"expr": "sel.item.guid", "alias": "item_guid"},
    {"expr": "sel.displayName", "alias": "item_name"},
    {"expr": "menu.salesCategory.guid", "alias": "sales_category_guid"},
    {"expr": "sel.quantity", "alias": "quantity"},
    {"expr": "sel.price", "alias": "net_sales"}
  ]
}
```

### Implementation Approach

Add to `Source` struct:

```rust
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ExplodeWithContext {
    /// Dot-separated path through nested arrays (e.g., "checks.selections")
    pub path: String,
    /// Aliases for each level (e.g., ["c", "sel"])
    pub aliases: Vec<String>,
    /// Parent fields to preserve in exploded rows
    pub preserve: Vec<String>,
    /// Filter conditions on leaf items
    #[serde(default)]
    pub r#where: Option<Vec<Condition>>,
}
```

---

## 3. Date/Time Manipulations

### Problem
The `hourly_sales_daily.csv` requires:
- Parsing ISO8601 dates
- Extracting hour component
- Timezone conversion
- Date arithmetic (hours worked calculation)

### Current Python Logic
```python
def aggregate_hourly_sales(orders):
    buckets = {}
    for order in orders:
        for check in order.get("checks", []):
            closed = _parse_iso(check.get("closedDate"))
            if not closed:
                continue
            hour = closed.hour  # Extract hour
            amt = float(check.get("amount", 0))
            buckets[hour] = buckets.get(hour, 0.0) + amt
    return buckets
```

### Proposed DSL Syntax

```json
{
  "_description": "Hourly sales with date extraction",
  "from": {
    "source_file": "orders_v2_orders_20260130.json",
    "alias": "o",
    "explode": "checks"
  },
  "where": [
    {"field": "o.closedDate", "op": "is_not_null"}
  ],
  "group_by": [
    {"field": "hour", "expr": "hour(o.closedDate)"}
  ],
  "select": [
    {"expr": "o.businessDate", "alias": "date"},
    {"expr": "hour(o.closedDate)", "alias": "hour"},
    {"expr": "sum(c.amount)", "alias": "net_sales"}
  ]
}
```

### Supported Date/Time Functions

| Function | Description | Example |
|----------|-------------|---------|
| `datetime(field)` | Parse ISO8601 to datetime | `datetime(te.inDate)` |
| `date(field)` | Extract date portion | `date(o.closedDate)` |
| `time(field)` | Extract time portion | `time(te.inDate)` |
| `hour(field)` | Extract hour (0-23) | `hour(o.closedDate)` |
| `minute(field)` | Extract minute (0-59) | `minute(te.inDate)` |
| `day_of_week(field)` | Day of week (0=Sunday) | `day_of_week(o.createdDate)` |
| `day_of_month(field)` | Day of month (1-31) | `day_of_month(o.closedDate)` |
| `month(field)` | Month (1-12) | `month(o.createdDate)` |
| `year(field)` | Year | `year(o.closedDate)` |
| `date_diff(field1, field2, unit)` | Difference in units | `date_diff(te.outDate, te.inDate, 'hours')` |
| `timezone_convert(field, from_tz, to_tz)` | Convert timezone | `timezone_convert(te.inDate, 'UTC', 'America/Chicago')` |
| `format_date(field, format)` | Format as string | `format_date(o.closedDate, '%Y-%m-%d')` |
| `now()` | Current datetime | `now()` |
| `date_trunc(field, unit)` | Truncate to unit | `date_trunc(o.closedDate, 'hour')` |

### Implementation Approach

Add date function parsing to expression evaluation:

```rust
#[derive(Debug, Deserialize, Serialize, Clone)]
pub enum DateFunction {
    DateTime { field: String },
    Date { field: String },
    Hour { field: String },
    DateDiff { field1: String, field2: String, unit: String },
    TimezoneConvert { field: String, from_tz: String, to_tz: String },
    // ... etc
}
```

---

## 4. Primitive Value Records

### Problem
The `orders_v2_orders_20260130.json` and `orders_v2_payments_20260130.json` contain only primitive string values (GUIDs), not objects:

```json
"c4932a6c-acb6-4869-ac9f-0de76b837778"
```

Current DSL expects objects with fields.

### Proposed DSL Syntax

```json
{
  "_description": "Query primitive value records",
  "from": {
    "source_file": "orders_v2_orders_20260130.json",
    "alias": "order_guid",
    "primitive_value": {
      "type": "string",
      "column_name": "guid"
    }
  },
  "select": [
    {"expr": "order_guid.value", "alias": "guid"}
  ]
}
```

Or simpler syntax:

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

### Implementation Approach

Modify `load_source` to handle primitives:

```rust
fn load_source(&self, source_file: &str, primitive_config: Option<PrimitiveConfig>) -> Result<Vec<Value>> {
    // ... existing loading code ...
    
    if let Some(config) = primitive_config {
        // Wrap primitive values in objects
        let wrapped: Vec<Value> = result.into_iter()
            .map(|v| {
                if v.is_string() || v.is_number() || v.is_boolean() {
                    let mut obj = serde_json::Map::new();
                    obj.insert(config.column_name.clone(), v);
                    Value::Object(obj)
                } else {
                    v
                }
            })
            .collect();
        Ok(wrapped)
    } else {
        Ok(result)
    }
}
```

---

## 5. Complete Complex Report Example

### net_sales_by_employee_daily.csv - Full DSL

```json
{
  "_description": "Net sales by employee with attribution logic",
  "_csv_source": "net_sales_by_employee_daily.csv",
  
  "with": [
    {
      "name": "employee_base",
      "query": {
        "from": {
          "source_file": "labor_v1_employees.json",
          "alias": "emp"
        },
        "select": [
          {"expr": "emp.guid", "alias": "employee_guid"},
          {"expr": "concat(emp.firstName, ' ', emp.lastName)", "alias": "employee_name"}
        ]
      }
    }
  ],
  
  "from_subquery": "employee_base",
  
  "left_nested_join": {
    "source": {
      "source_file": "orders_v2_orders_20260130.json",
      "alias": "o"
    },
    "nested_path": "checks.payments",
    "aliases": ["c", "p"],
    "where": [
      {"field": "c.voided", "op": "!=", "value": true},
      {"field": "c.deleted", "op": "!=", "value": true}
    ],
    "on": {
      "type": "coalesce",
      "fields": ["p.server.guid", "o.server.guid"],
      "target": "employee_base.employee_guid"
    },
    "aggregate": {
      "net_sales": {
        "expr": "c.amount",
        "weight_by": "p.amount / sum(p.amount)"
      },
      "total_sales": {
        "expr": "c.totalAmount", 
        "weight_by": "p.amount / sum(p.amount)"
      },
      "checks_count": {
        "expr": "count(distinct c.guid)"
      }
    }
  },
  
  "select": [
    {"expr": "employee_base.employee_guid", "alias": "employee_guid"},
    {"expr": "employee_base.employee_name", "alias": "employee_name"},
    {"expr": "aggregation.net_sales", "alias": "net_sales"},
    {"expr": "aggregation.total_sales", "alias": "total_sales"},
    {"expr": "aggregation.checks_count", "alias": "checks_count"}
  ]
}
```

---

## 6. Implementation Priority

### Phase 1: Essential for Basic Reports (Week 1)
1. **Primitive Value Records** - Simple fix, enables GUID list queries
2. **Date Functions** - hour(), date(), datetime() - enables hourly_sales

### Phase 2: Intermediate Complexity (Week 2)
3. **Array Explosion with Context** - Enables item_mix, discounts reports
4. **Enhanced GROUP BY expressions** - Allow expressions in group_by fields

### Phase 3: Complex Aggregation (Week 3-4)
5. **Nested Aggregations** - Full nested explosion with aggregation
6. **Weighted Aggregations** - For payment ratio attribution
7. **COALESCE in joins** - For fallback attribution logic

---

## 7. Files to Modify

### `/home/ubuntu/jaq/json-loader-server/src/query_engine.rs`

Add to existing structs:
- `QueryDsl`: Add `explode_nested`, `left_nested_join` fields
- `Source`: Add `primitive_value`, `explode_with_context` fields
- `GroupBy`: Support `expr` field for expressions

Add new structs:
- `NestedExplode`
- `ExplodeWithContext`  
- `PrimitiveConfig`
- `DateFunction`

Add new methods:
- `explode_nested_source()`
- `evaluate_date_function()`
- `wrap_primitive_values()`

### `/home/ubuntu/jaq/json-loader-server/src/main.rs`

Update export handlers if needed for new result formats.

---

## 8. Migration Status Summary

| Report | Current Status | Blocker | DSL Extension Needed |
|--------|---------------|---------|---------------------|
| employees.csv | ✅ Complete | None | - |
| labor_hours_daily.csv | ✅ Complete | None | - |
| labor_shifts_detailed_daily.csv | ✅ Complete | None | - |
| cash_tips_per_shift.csv | ✅ Complete | None | - |
| gratuity_per_shift.csv | ✅ Complete | None | - |
| cash_summary_daily.csv | ✅ Complete | None | - |
| net_sales_by_employee_daily.csv | ⚠️ Blocked | Nested aggregation + attribution | Nested explosion, weighted agg |
| item_mix_daily.csv | ⚠️ Blocked | Multi-level array explosion | explode_with_context |
| category_sales_daily.csv | ⚠️ Blocked | Depends on item_mix | explode_with_context |
| discounts_daily.csv | ⚠️ Blocked | Nested array explosion | explode_with_context |
| hourly_sales_daily.csv | ⚠️ Blocked | Date extraction | hour(), date() functions |
| payments_tips_daily.csv | ⚠️ Blocked | Nested aggregation | Nested explosion |
| voids_daily.csv | ⚠️ Blocked | Complex filtering | Conditional aggregation |
| sales_by_dimension_daily.csv | ⚠️ Blocked | Order data not loaded | Primitive value handling |
| tips_by_server_daily.csv | ⚠️ Blocked | Payment aggregation | Nested explosion |

**Migrated**: 6/14 reports (43%)
**Pending DSL Extensions**: 8/14 reports (57%)
