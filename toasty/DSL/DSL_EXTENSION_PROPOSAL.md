# DSL Extension Proposal for Toast Data Reports

## Current Limitations

The existing DSL handles basic queries well, but struggles with the complex aggregations needed for Toast reports like:

1. **net_sales_by_employee_daily.csv** - Requires:
   - Nested traversal: orders → checks → payments
   - Conditional aggregation (exclude voided/deleted)
   - Multi-field attribution (payment server, order server)
   - Currency calculations across multiple fields

2. **item_mix_daily.csv** - Requires:
   - Exploding nested arrays (selections)
   - Joining with menus data for category names
   - Summing quantities and prices

3. **hourly_sales_daily.csv** - Requires:
   - Date parsing and hour extraction
   - Timezone conversion
   - Time-based bucketing

## Proposed DSL Extensions

### 1. Array Explosion with Context

```json
{
  "from": {
    "source_file": "orders.json",
    "alias": "o",
    "explode": "checks",
    "explode_context": {
      "preserve": ["o.guid", "o.server", "o.businessDate"],
      "explode_alias": "check"
    }
  }
}
```

### 2. Nested Aggregation

```json
{
  "from": {
    "source_file": "orders.json",
    "alias": "o"
  },
  "nested_aggregations": [
    {
      "path": "checks.payments",
      "alias": "payment",
      "where": [
        {"field": "payment.voided", "op": "!=", "value": true}
      ],
      "aggregate": {
        "amount": "sum(payment.amount)",
        "tips": "sum(payment.tipAmount)",
        "count": "count(payment.guid)"
      },
      "group_by": ["payment.server.guid"]
    }
  ]
}
```

### 3. Date/Time Functions

```json
{
  "select": [
    {
      "expr": "datetime(te.inDate)",
      "alias": "parsed_date"
    },
    {
      "expr": "hour(te.inDate)",
      "alias": "hour_of_day"
    },
    {
      "expr": "date_diff(te.outDate, te.inDate, 'hours')",
      "alias": "hours_worked"
    },
    {
      "expr": "timezone_convert(te.inDate, 'UTC', 'America/Chicago')",
      "alias": "local_time"
    }
  ]
}
```

### 4. Conditional Expressions

```json
{
  "select": [
    {
      "expr": "case when check.voided = true then 0 else check.amount end",
      "alias": "net_amount"
    },
    {
      "expr": "coalesce(payment.server.guid, order.server.guid, 'UNKNOWN')",
      "alias": "attributed_server"
    }
  ]
}
```

### 5. Subqueries and CTEs

```json
{
  "with": [
    {
      "name": "employee_shifts",
      "query": {
        "from": {
          "source_file": "timeEntries.json",
          "alias": "te"
        },
        "select": [
          {"expr": "te.employeeReference.guid", "alias": "emp_guid"},
          {"expr": "te.inDate", "alias": "shift_start"},
          {"expr": "te.outDate", "alias": "shift_end"}
        ]
      }
    }
  ],
  "from_subquery": "employee_shifts",
  "joins": [
    {
      "source": {
        "source_file": "orders.json",
        "alias": "o"
      },
      "on": {
        "left": "employee_shifts.emp_guid",
        "right": "o.server.guid"
      },
      "join_type": "left"
    }
  ]
}
```

### 6. JSON Path Expressions

```json
{
  "select": [
    {
      "expr": "json_path(o, '$.checks[0].payments[0].amount')",
      "alias": "first_payment_amount"
    },
    {
      "expr": "json_path_sum(o, '$.checks[*].amount')",
      "alias": "total_check_amounts"
    }
  ]
}
```

## Complex Report Example

### net_sales_by_employee_daily.csv DSL

```json
{
  "_description": "Net sales by employee with component breakdown",
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
  "nested_aggregations": [
    {
      "source": {
        "source_file": "orders.json",
        "alias": "o"
      },
      "path": "checks",
      "alias": "c",
      "where": [
        {"field": "c.voided", "op": "!=", "value": true},
        {"field": "c.deleted", "op": "!=", "value": true}
      ],
      "join_conditions": [
        {
          "type": "left",
          "match": "coalesce(c.payments[0].server.guid, o.server.guid) = employee_base.employee_guid"
        }
      ],
      "aggregate": {
        "net_sales": "sum(c.amount)",
        "total_sales": "sum(c.totalAmount)",
        "checks_count": "count(c.guid)",
        "items_total": "sum(json_path_sum(c, '$.selections[*].price'))",
        "discounts_total": "sum(json_path_sum(c, '$.appliedDiscounts[*].discountAmount'))"
      }
    }
  ],
  "select": [
    {"expr": "employee_base.employee_guid", "alias": "employee_guid"},
    {"expr": "employee_base.employee_name", "alias": "employee_name"},
    {"expr": "aggregation.net_sales", "alias": "net_sales"},
    {"expr": "aggregation.total_sales", "alias": "total_sales"},
    {"expr": "aggregation.checks_count", "alias": "checks_count"},
    {"expr": "aggregation.items_total", "alias": "items_total"},
    {"expr": "aggregation.discounts_total", "alias": "discounts_total"}
  ]
}
```

## Implementation Recommendations

### Option 1: Extend Current DSL (Incremental)
- Add date/time functions first (most commonly needed)
- Add conditional expressions (case/when, coalesce)
- Add simple array explosion

### Option 2: Hybrid Approach (Recommended)
- Keep simple reports in DSL
- Use Python/JS pre-processing for complex nested structures
- Store intermediate results in datalake
- DSL queries the pre-processed data

### Option 3: Full Query Engine
- Implement SQL-like query engine
- Support JOINs across nested structures
- Add window functions for time-based analysis

## Migration Path

1. **Phase 1**: Implement simple reports (employees, jobs, labor hours)
2. **Phase 2**: Add date/time functions, implement time-based reports
3. **Phase 3**: Implement array operations, item_mix reports
4. **Phase 4**: Full nested aggregation, net_sales reports

## Current Workaround

Until DSL extensions are implemented, complex reports can use:

1. **Pre-processing script** to flatten nested JSON:
```python
# flatten_orders.py
for order in orders:
    for check in order.get('checks', []):
        for payment in check.get('payments', []):
            flattened.append({
                'order_guid': order['guid'],
                'check_guid': check['guid'],
                'payment_guid': payment['guid'],
                'amount': payment['amount'],
                'server_guid': payment.get('server', {}).get('guid'),
                # ... flatten all fields
            })
```

2. **Load flattened data** into datalake

3. **Query with DSL** on flattened structure
