# DSL Quick Reference

## Query Results Summary

| Query | Status | Rows | Output File |
|-------|--------|------|-------------|
| 01_employees | ✅ Success | 156 | `01_employees.csv` |
| 02_jobs | ✅ Success | 25 | `02_jobs.csv` |
| 03_revenue_centers | ✅ Success | 3 | `03_revenue_centers.csv` |
| 04_labor_hours_daily | ⚠️ Partial | 16 | `04_labor_hours_daily.csv` |
| 05_labor_shifts_detailed_daily | ✅ Success | 19 | `05_labor_shifts_detailed_daily.csv` |
| 06_cash_tips_per_shift | ✅ Success | 4 | `06_cash_tips_per_shift.csv` |
| 07_gratuity_per_shift | ✅ Success | 56 | `07_gratuity_per_shift.csv` |
| 08_cash_summary_daily | ⚠️ Partial | 1 | `08_cash_summary_daily.csv` |
| 09_cash_entries_detailed | ✅ Success | 3 | `09_cash_entries_detailed.csv` |
| 10_payments_summary | ❌ Failed | - | - |
| 11_deposits_summary | ⚠️ Empty | 0 | `11_deposits_summary.csv` |
| 12_time_entry_gratuity | ⚠️ Partial | 1 | `12_time_entry_gratuity.csv` |
| 13_employee_jobs | ⚠️ Partial | 428 | `13_employee_jobs.csv` |
| 14_active_employees | ❌ Failed | 0 | `14_active_employees.csv` |
| 20_orders_guid_list | ❌ Failed | - | - |
| 21_payments_guid_list | ❌ Failed | - | - |

## Working Queries (Can Use Immediately)

### Employees
```bash
./scripts/run_dsl_query.sh 01_employees.dsl.json
```

### Jobs
```bash
./scripts/run_dsl_query.sh 02_jobs.dsl.json
```

### Revenue Centers
```bash
./scripts/run_dsl_query.sh 03_revenue_centers.dsl.json
```

### Labor Shifts Detailed
```bash
./scripts/run_dsl_query.sh 05_labor_shifts_detailed_daily.dsl.json
```

### Cash Tips
```bash
./scripts/run_dsl_query.sh 06_cash_tips_per_shift.dsl.json
```

### Gratuity Per Shift
```bash
./scripts/run_dsl_query.sh 07_gratuity_per_shift.dsl.json
```

### Cash Entries Detailed
```bash
./scripts/run_dsl_query.sh 09_cash_entries_detailed.dsl.json
```

## DSL Limitations Found

### 1. Primitive Values as Rows
**Problem**: When JSON contains just a string value (like order GUIDs), the DSL can't reference it.
```json
// This JSON fails:
"02e8c24f-1c80-4e64-9e0d-33857f9e7d9c"

// The DSL can't do: { "expr": "order_guid", ... }
```

**Workaround**: Wrap primitives in objects before loading to datalake.

### 2. Boolean Filtering
**Problem**: Boolean comparisons don't work correctly.
```json
// This fails:
{ "field": "emp.deleted", "op": "=", "value": false }
```

**Workaround**: Use `is_not_null`/`is_null` or filter in post-processing.

### 3. Array Explosion with JOINs
**Problem**: Combining `explode` with JOINs doesn't properly preserve exploded context.

**Workaround**: Do array explosion in separate step, save result, then JOIN.

### 4. Aggregation Aliases in Output
**Problem**: Sometimes aggregated columns don't appear in output with correct alias.

**Workaround**: Use simpler queries or post-process results.

### 5. GROUP BY with Expressions
**Problem**: GROUP BY with calculated expressions may not work.

**Workaround**: Pre-calculate in data or use simpler grouping.

## Recommended DSL Patterns

### Simple SELECT
```json
{
  "from": { "source_file": "file.json", "alias": "a" },
  "select": [
    { "expr": "a.field1", "alias": "col1" },
    { "expr": "a.field2", "alias": "col2" }
  ]
}
```

### JOIN Pattern
```json
{
  "from": { "source_file": "main.json", "alias": "m" },
  "joins": [{
    "source": { "source_file": "lookup.json", "alias": "l" },
    "on": { "left": "m.foreign_key", "right": "l.primary_key" },
    "join_type": "left",
    "skip_nulls": true
  }],
  "select": [
    { "expr": "m.field", "alias": "main_field" },
    { "expr": "l.name", "alias": "lookup_name" }
  ]
}
```

### Aggregation Pattern
```json
{
  "from": { "source_file": "data.json", "alias": "d" },
  "group_by": [
    { "field": "d.category" }
  ],
  "select": [
    { "expr": "d.category", "alias": "category" },
    { "expr": "sum(d.amount)", "alias": "total" },
    { "expr": "count(d.id)", "alias": "count" }
  ]
}
```

### Filter Pattern
```json
{
  "from": { "source_file": "data.json", "alias": "d" },
  "where": [
    { "field": "d.status", "op": "=", "value": "active" },
    { "field": "d.amount", "op": ">", "value": 100 }
  ],
  "where_op": "and",
  "select": [ ... ]
}
```

## curl Commands for Direct API Access

### List Available Sources
```bash
curl -s http://localhost:3000/files | jq .
```

### Get Schema for Source
```bash
curl -s "http://localhost:3000/schema?source_file=labor_v1_employees.json" | jq .
```

### Execute Simple Query
```bash
curl -s -X POST http://localhost:3000/query/dsl \
  -H "Content-Type: application/json" \
  -d '{
    "query": "{ \"from\": { \"source_file\": \"labor_v1_employees.json\", \"alias\": \"emp\" }, \"select\": [{\"expr\": \"emp.firstName\", \"alias\": \"name\"}], \"limit\": 5 }"
  }' | jq .
```

### Export to CSV
```bash
curl -s -X POST http://localhost:3000/export \
  -H "Content-Type: application/json" \
  -d '{
    "query": "{ \"from\": { \"source_file\": \"labor_v1_employees.json\", \"alias\": \"emp\" }, \"select\": [{\"expr\": \"emp.firstName\", \"alias\": \"name\"}], \"limit\": 5 }",
    "format": "csv",
    "filename": "test"
  }' \
  -o test.csv
```
