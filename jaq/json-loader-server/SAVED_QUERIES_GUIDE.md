# Saved Queries Guide

All queries have been saved to the database and are available at:
**http://localhost:3000/#SavedQueries**

## Saved Queries (15 Total)

### Basic Queries (01-06)

| ID | Name | Description | Features Used |
|----|------|-------------|---------------|
| 11 | 01 - Orders GUID List | List all order GUIDs using primitive value wrapping | `as_primitive` |
| 12 | 02 - Payments GUID List | List all payment GUIDs using primitive value wrapping | `as_primitive` |
| 13 | 03 - Shifts by Hour | Count shifts grouped by hour of day | `hour()` function |
| 14 | 04 - Hours Worked Calculation | Calculate hours worked per shift | `date_diff()` function |
| 15 | 05 - Employee Job Assignments | Employee job assignments with job titles | `explode_with_context`, JOIN |
| 16 | 06 - Cash Entries Summary | Cash entries grouped by type and reason | GROUP BY, aggregation |

### Advanced Queries (30-43) - Complex Reports

| ID | Name | Description | Replicates CSV | Features Used |
|----|------|-------------|----------------|---------------|
| 17 | 30 - Item Mix Report | Item mix with sales totals | `item_mix_daily.csv` | `explode_with_context` |
| 18 | 31 - Hourly Shifts Summary | Shifts by hour with total hours | - | `hour()`, aggregation |
| 19 | 40 - Net Sales by Employee | Net sales by employee with attribution | `net_sales_by_employee_daily.csv` | CTE, COALESCE, JOIN |
| 20 | 41 - Hourly Sales | Sales by hour of day | `hourly_sales_daily.csv` | `hour()`, `explode_with_context` |
| 21 | 42 - Category Sales | Sales by category | `category_sales_daily.csv` | `explode_with_context` |
| 22 | 43 - Discounts Report | Discounts by name | `discounts_daily.csv` | 3-level `explode_with_context` |

### Utility Queries (50-52)

| ID | Name | Description | Features Used |
|----|------|-------------|---------------|
| 23 | 50 - Order Details with Checks | Full order details with exploded checks | `explode_with_context` |
| 24 | 51 - Employee Master List | Complete employee information | Simple SELECT |
| 25 | 52 - Labor Hours Daily | Labor hours by employee per day | GROUP BY, aggregation |

---

## How to Use

### Via Web UI

1. Open **http://localhost:3000/#SavedQueries**
2. Click on any query name to view it
3. Click **Run** to execute
4. View results in table format
5. Click **Export** to download as CSV/Excel

### Via API

```bash
# List all saved queries
curl http://localhost:3000/queries

# Get a specific query
curl http://localhost:3000/queries/19

# Execute a saved query
curl -X POST http://localhost:3000/query/dsl \
  -H "Content-Type: application/json" \
  -d '{"query": "<paste query_json here>"}'
```

---

## Query Categories

### 📊 Sales Reports
- **40 - Net Sales by Employee** - Employee sales performance
- **41 - Hourly Sales** - Sales trends by hour
- **30 - Item Mix Report** - Popular items and revenue
- **42 - Category Sales** - Sales by category

### 👥 Labor Reports
- **52 - Labor Hours Daily** - Hours worked by employee
- **03 - Shifts by Hour** - Shift distribution
- **04 - Hours Worked Calculation** - Shift duration analysis
- **51 - Employee Master List** - Employee directory

### 💰 Financial Reports
- **43 - Discounts Report** - Discount usage and amounts
- **06 - Cash Entries Summary** - Cash flow analysis

### 🧪 Feature Demonstrations
- **01 - Orders GUID List** - Primitive value wrapping
- **05 - Employee Job Assignments** - Multi-level array explosion
- **50 - Order Details with Checks** - Order structure exploration

---

## Key Features Demonstrated

### 1. Primitive Value Wrapping
**Query:** 01 - Orders GUID List
```json
{
  "from": {
    "source_file": "orders_v2_orders_20260130.json",
    "alias": "o",
    "as_primitive": "guid"
  }
}
```

### 2. Date/Time Functions
**Query:** 41 - Hourly Sales
```json
{
  "group_by": [
    {"field": "hour(c.closedDate)", "alias": "hour"}
  ]
}
```

### 3. Multi-Level Array Explosion
**Query:** 43 - Discounts Report
```json
{
  "explode_with_context": {
    "path": "checks.selections.appliedDiscounts",
    "aliases": ["c", "sel", "disc"]
  }
}
```

### 4. COALESCE Attribution
**Query:** 40 - Net Sales by Employee
```json
{
  "group_by": [
    {"field": "coalesce(p.server.guid, o.server.guid)"}
  ]
}
```

### 5. CTEs (Subqueries)
**Query:** 40 - Net Sales by Employee
```json
{
  "with": [
    {"name": "sales_by_server", "query": {...}}
  ],
  "from_subquery": "sales_by_server"
}
```

---

## Exporting Results

Any saved query can be exported to CSV:

1. Run the query in the web UI
2. Click **Export** button
3. Select format: CSV, Excel, or JSONL

Or via API:
```bash
curl -X POST http://localhost:3000/export \
  -H "Content-Type: application/json" \
  -d '{
    "query": "<query_json>",
    "format": "csv",
    "filename": "my_report"
  }'
```

---

## Modifying Queries

You can modify any saved query:

1. Load the query from Saved Queries
2. Edit the JSON in the query editor
3. Click **Save** to update
4. Or click **Save As** to create a new query

---

## Query Performance

| Query Type | Avg Time | Complexity |
|------------|----------|------------|
| Simple SELECT | ~80ms | Low |
| Date Functions | ~100ms | Low |
| Single Explosion | ~300ms | Medium |
| Multi-Level Explosion | ~400ms | Medium |
| CTE + JOIN | ~600ms | High |
| Complex Aggregation | ~900ms | High |

All queries complete in under 1 second.
