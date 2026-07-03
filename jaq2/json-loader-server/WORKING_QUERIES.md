# Working DSL Queries

## 1. Primitive Value Query (orders_v2_orders_20260130.json)

Query GUID-only files by wrapping primitives:

```bash
curl -s -X POST http://localhost:3000/query/dsl \
  -H "Content-Type: application/json" \
  -d '{"query": "{\"from\":{\"source_file\":\"orders_v2_orders_20260130.json\",\"alias\":\"o\",\"as_primitive\":\"guid\"},\"select\":[{\"expr\":\"o.guid\",\"alias\":\"order_guid\"}],\"limit\":10}"}'
```

## 2. Full Order Data

Query the full order data we loaded:

```bash
curl -s -X POST http://localhost:3000/query/dsl \
  -H "Content-Type: application/json" \
  -d '{"query": "{\"from\":{\"source_file\":\"orders_full_20251213.json\",\"alias\":\"o\"},\"select\":[{\"expr\":\"o.guid\",\"alias\":\"guid\"},{\"expr\":\"o.businessDate\",\"alias\":\"date\"},{\"expr\":\"o.server.guid\",\"alias\":\"server_guid\"}],\"limit\":10}"}'
```

## 3. Explode Checks Array

Flatten order checks into individual rows:

```bash
curl -s -X POST http://localhost:3000/query/dsl \
  -H "Content-Type: application/json" \
  -d '{"query": "{\"from\":{\"source_file\":\"orders_full_20251213.json\",\"alias\":\"o\",\"explode\":\"checks\"},\"select\":[{\"expr\":\"o.guid\",\"alias\":\"order_guid\"},{\"expr\":\"o.checks.guid\",\"alias\":\"check_guid\"},{\"expr\":\"o.checks.amount\",\"alias\":\"amount\"}],\"limit\":10}"}'
```

## 4. Hour Extraction (for hourly_sales report)

Extract hour from datetime:

```bash
curl -s -X POST http://localhost:3000/query/dsl \
  -H "Content-Type: application/json" \
  -d '{"query": "{\"from\":{\"source_file\":\"labor_v1_timeEntries_20260130.json\",\"alias\":\"te\"},\"where\":[{\"field\":\"te.inDate\",\"op\":\"is_not_null\"}],\"select\":[{\"expr\":\"te.guid\",\"alias\":\"guid\"},{\"expr\":\"hour(te.inDate)\",\"alias\":\"hour\"}],\"limit\":10}"}'
```

## 5. Date Extraction

Extract date portion:

```bash
curl -s -X POST http://localhost:3000/query/dsl \
  -H "Content-Type: application/json" \
  -d '{"query": "{\"from\":{\"source_file\":\"labor_v1_timeEntries_20260130.json\",\"alias\":\"te\"},\"select\":[{\"expr\":\"te.guid\",\"alias\":\"guid\"},{\"expr\":\"date(te.inDate)\",\"alias\":\"date\"}],\"limit\":10}"}'
```

## 6. Hours Worked Calculation

Calculate shift duration:

```bash
curl -s -X POST http://localhost:3000/query/dsl \
  -H "Content-Type: application/json" \
  -d '{"query": "{\"from\":{\"source_file\":\"labor_v1_timeEntries_20260130.json\",\"alias\":\"te\"},\"where\":[{\"field\":\"te.inDate\",\"op\":\"is_not_null\"},{\"field\":\"te.outDate\",\"op\":\"is_not_null\"}],\"select\":[{\"expr\":\"te.guid\",\"alias\":\"guid\"},{\"expr\":\"date(te.inDate)\",\"alias\":\"date\"},{\"expr\":\"hour(te.inDate)\",\"alias\":\"hour\"},{\"expr\":\"date_diff(te.outDate, te.inDate, 'hours')\",\"alias\":\"hours_worked\"}],\"limit\":10}"}'
```

## 7. Hourly Aggregation

Group by hour with count:

```bash
curl -s -X POST http://localhost:3000/query/dsl \
  -H "Content-Type: application/json" \
  -d '{"query": "{\"from\":{\"source_file\":\"labor_v1_timeEntries_20260130.json\",\"alias\":\"te\"},\"where\":[{\"field\":\"te.inDate\",\"op\":\"is_not_null\"}],\"group_by\":[{\"field\":\"hour(te.inDate)\",\"alias\":\"hour\"}],\"select\":[{\"expr\":\"hour(te.inDate)\",\"alias\":\"hour\"},{\"expr\":\"te.guid\",\"alias\":\"shift_count\",\"agg\":\"count\"}],\"order_by\":[{\"field\":\"hour\",\"direction\":\"asc\"}]}"}'
```

## 8. Order Summary by Server

Aggregate orders by server:

```bash
curl -s -X POST http://localhost:3000/query/dsl \
  -H "Content-Type: application/json" \
  -d '{"query": "{\"from\":{\"source_file\":\"orders_full_20251213.json\",\"alias\":\"o\",\"explode\":\"checks\"},\"group_by\":[{\"field\":\"o.server.guid\"}],\"select\":[{\"expr\":\"o.server.guid\",\"alias\":\"server_guid\"},{\"expr\":\"o.checks.amount\",\"alias\":\"total_sales\",\"agg\":\"sum\"},{\"expr\":\"o.checks.guid\",\"alias\":\"check_count\",\"agg\":\"count\"}]}"}'
```

## Export to CSV

Any query can be exported to CSV:

```bash
curl -s -X POST http://localhost:3000/export \
  -H "Content-Type: application/json" \
  -d '{"query": "{\"from\":{\"source_file\":\"labor_v1_timeEntries_20260130.json\",\"alias\":\"te\"},\"where\":[{\"field\":\"te.inDate\",\"op\":\"is_not_null\"}],\"group_by\":[{\"field\":\"hour(te.inDate)\",\"alias\":\"hour\"}],\"select\":[{\"expr\":\"hour(te.inDate)\",\"alias\":\"hour\"},{\"expr\":\"te.guid\",\"alias\":\"shift_count\",\"agg\":\"count\"}]}"", "format": "csv", "filename": "hourly_shifts"}'
```
