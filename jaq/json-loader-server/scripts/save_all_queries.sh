#!/bin/bash
# Save all DSL queries to the database

BASE_URL="http://localhost:3000"

echo "Saving queries to database..."

# 01. Orders GUID List (Primitive Values)
curl -s -X POST "${BASE_URL}/queries" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "01 - Orders GUID List",
    "description": "List all order GUIDs using primitive value wrapping",
    "query": "{\"from\":{\"source_file\":\"orders_v2_orders_20260130.json\",\"alias\":\"o\",\"as_primitive\":\"guid\"},\"select\":[{\"expr\":\"o.guid\",\"alias\":\"order_guid\"}]}"
  }'
echo " - Saved: 01 - Orders GUID List"

# 02. Payments GUID List (Primitive Values)
curl -s -X POST "${BASE_URL}/queries" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "02 - Payments GUID List",
    "description": "List all payment GUIDs using primitive value wrapping",
    "query": "{\"from\":{\"source_file\":\"orders_v2_payments_20260130.json\",\"alias\":\"p\",\"as_primitive\":\"guid\"},\"select\":[{\"expr\":\"p.guid\",\"alias\":\"payment_guid\"}]}"
  }'
echo " - Saved: 02 - Payments GUID List"

# 03. Time Entries by Hour (Date Functions)
curl -s -X POST "${BASE_URL}/queries" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "03 - Shifts by Hour",
    "description": "Count shifts grouped by hour of day using hour() function",
    "query": "{\"from\":{\"source_file\":\"labor_v1_timeEntries_20260130.json\",\"alias\":\"te\"},\"where\":[{\"field\":\"te.inDate\",\"op\":\"is_not_null\"}],\"group_by\":[{\"field\":\"hour(te.inDate)\",\"alias\":\"hour\"}],\"select\":[{\"expr\":\"hour(te.inDate)\",\"alias\":\"hour\"},{\"expr\":\"te.guid\",\"alias\":\"shift_count\",\"agg\":\"count\"}],\"order_by\":[{\"field\":\"hour\",\"direction\":\"asc\"}]}"
  }'
echo " - Saved: 03 - Shifts by Hour"

# 04. Time Entries with Hours Worked
curl -s -X POST "${BASE_URL}/queries" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "04 - Hours Worked Calculation",
    "description": "Calculate hours worked per shift using date_diff()",
    "query": "{\"from\":{\"source_file\":\"labor_v1_timeEntries_20260130.json\",\"alias\":\"te\"},\"where\":[{\"field\":\"te.inDate\",\"op\":\"is_not_null\"},{\"field\":\"te.outDate\",\"op\":\"is_not_null\"}],\"select\":[{\"expr\":\"te.guid\",\"alias\":\"shift_guid\"},{\"expr\":\"te.businessDate\",\"alias\":\"date\"},{\"expr\":\"te.inDate\",\"alias\":\"clock_in\"},{\"expr\":\"te.outDate\",\"alias\":\"clock_out\"},{\"expr\":\"date_diff(te.outDate, te.inDate, 'hours')\",\"alias\":\"hours_worked\"}],\"order_by\":[{\"field\":\"te.inDate\",\"direction\":\"desc\"}],\"limit\":100}"
  }'
echo " - Saved: 04 - Hours Worked Calculation"

# 05. Employee Jobs Exploded
curl -s -X POST "${BASE_URL}/queries" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "05 - Employee Job Assignments",
    "description": "Employee job assignments with job titles from explode_with_context",
    "query": "{\"from\":{\"source_file\":\"labor_v1_employees.json\",\"alias\":\"emp\",\"explode_with_context\":{\"path\":\"jobReferences\",\"alias\":\"job_ref\",\"preserve\":[\"emp.guid\",\"emp.firstName\",\"emp.lastName\"]}},\"joins\":[{\"source\":{\"source_file\":\"labor_v1_jobs.json\",\"alias\":\"job\"},\"on\":{\"left\":\"job_ref.guid\",\"right\":\"job.guid\"},\"join_type\":\"left\",\"skip_nulls\":true}],\"select\":[{\"expr\":\"emp.guid\",\"alias\":\"employee_guid\"},{\"expr\":\"emp.firstName\",\"alias\":\"first_name\"},{\"expr\":\"emp.lastName\",\"alias\":\"last_name\"},{\"expr\":\"job.title\",\"alias\":\"job_title\"}]}"
  }'
echo " - Saved: 05 - Employee Job Assignments"

# 06. Cash Entries by Type
curl -s -X POST "${BASE_URL}/queries" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "06 - Cash Entries Summary",
    "description": "Cash entries grouped by type and reason with aggregations",
    "query": "{\"from\":{\"source_file\":\"cashmgmt_v1_entries_20260130.json\",\"alias\":\"ce\"},\"group_by\":[{\"field\":\"ce.type\"},{\"field\":\"ce.reason\"}],\"select\":[{\"expr\":\"ce.type\",\"alias\":\"entry_type\"},{\"expr\":\"ce.reason\",\"alias\":\"reason\"},{\"expr\":\"sum(ce.amount)\",\"alias\":\"total_amount\"},{\"expr\":\"count(ce.guid)\",\"alias\":\"entry_count\"}],\"order_by\":[{\"field\":\"entry_type\",\"direction\":\"asc\"},{\"field\":\"reason\",\"direction\":\"asc\"}]}"
  }'
echo " - Saved: 06 - Cash Entries Summary"

# 30. Item Mix Report
curl -s -X POST "${BASE_URL}/queries" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "30 - Item Mix Report",
    "description": "Item mix with sales totals - replicate item_mix_daily.csv",
    "query": "{\"from\":{\"source_file\":\"orders_full_20251213.json\",\"alias\":\"o\",\"explode_with_context\":{\"path\":\"checks.selections\",\"aliases\":[\"c\",\"sel\"],\"where\":[{\"field\":\"sel.voided\",\"op\":\"!=\",\"value\":true}]}},\"group_by\":[{\"field\":\"sel.displayName\",\"alias\":\"item_name\"}],\"select\":[{\"expr\":\"sel.displayName\",\"alias\":\"item_name\"},{\"expr\":\"sel.price\",\"alias\":\"total_sales\",\"agg\":\"sum\"},{\"expr\":\"sel.guid\",\"alias\":\"quantity\",\"agg\":\"count\"}],\"order_by\":[{\"field\":\"total_sales\",\"direction\":\"desc\"}]}"
  }'
echo " - Saved: 30 - Item Mix Report"

# 31. Hourly Shifts
curl -s -X POST "${BASE_URL}/queries" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "31 - Hourly Shifts Summary",
    "description": "Shifts by hour with total hours - demonstrates date functions",
    "query": "{\"from\":{\"source_file\":\"labor_v1_timeEntries_20260130.json\",\"alias\":\"te\"},\"where\":[{\"field\":\"te.inDate\",\"op\":\"is_not_null\"}],\"group_by\":[{\"field\":\"hour(te.inDate)\",\"alias\":\"hour\"}],\"select\":[{\"expr\":\"hour(te.inDate)\",\"alias\":\"hour\"},{\"expr\":\"te.guid\",\"alias\":\"shift_count\",\"agg\":\"count\"},{\"expr\":\"sum(te.regularHours)\",\"alias\":\"total_hours\"}],\"order_by\":[{\"field\":\"hour\",\"direction\":\"asc\"}]}"
  }'
echo " - Saved: 31 - Hourly Shifts Summary"

# 40. Net Sales by Employee
curl -s -X POST "${BASE_URL}/queries" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "40 - Net Sales by Employee",
    "description": "Net sales by employee with COALESCE attribution - replicate net_sales_by_employee_daily.csv",
    "query": "{\"with\":[{\"name\":\"sales_by_server\",\"query\":{\"from\":{\"source_file\":\"orders_full_20251213.json\",\"alias\":\"o\",\"explode_with_context\":{\"path\":\"checks.payments\",\"aliases\":[\"c\",\"p\"],\"where\":[{\"field\":\"c.voided\",\"op\":\"!=\",\"value\":true},{\"field\":\"c.deleted\",\"op\":\"!=\",\"value\":true}]}},\"group_by\":[{\"field\":\"coalesce(p.server.guid, o.server.guid)\",\"alias\":\"server_guid\"}],\"select\":[{\"expr\":\"coalesce(p.server.guid, o.server.guid)\",\"alias\":\"server_guid\"},{\"expr\":\"c.amount\",\"alias\":\"net_sales\",\"agg\":\"sum\"},{\"expr\":\"c.totalAmount\",\"alias\":\"total_sales\",\"agg\":\"sum\"},{\"expr\":\"c.guid\",\"alias\":\"checks_count\",\"agg\":\"count\"}]}}],\"from_subquery\":\"sales_by_server\",\"joins\":[{\"source\":{\"source_file\":\"labor_v1_employees.json\",\"alias\":\"emp\"},\"on\":{\"left\":\"sales_by_server.server_guid\",\"right\":\"emp.guid\"},\"join_type\":\"left\",\"skip_nulls\":true}],\"select\":[{\"expr\":\"sales_by_server.server_guid\",\"alias\":\"employee_guid\"},{\"expr\":\"emp.firstName\",\"alias\":\"first_name\"},{\"expr\":\"emp.lastName\",\"alias\":\"last_name\"},{\"expr\":\"sales_by_server.net_sales\",\"alias\":\"net_sales\"},{\"expr\":\"sales_by_server.total_sales\",\"alias\":\"total_sales\"},{\"expr\":\"sales_by_server.checks_count\",\"alias\":\"checks_count\"}],\"order_by\":[{\"field\":\"net_sales\",\"direction\":\"desc\"}]}"
  }'
echo " - Saved: 40 - Net Sales by Employee"

# 41. Hourly Sales
curl -s -X POST "${BASE_URL}/queries" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "41 - Hourly Sales",
    "description": "Sales by hour of day - replicate hourly_sales_daily.csv",
    "query": "{\"from\":{\"source_file\":\"orders_full_20251213.json\",\"alias\":\"o\",\"explode_with_context\":{\"path\":\"checks\",\"aliases\":[\"c\"],\"where\":[{\"field\":\"c.voided\",\"op\":\"!=\",\"value\":true},{\"field\":\"c.deleted\",\"op\":\"!=\",\"value\":true}]}},\"where\":[{\"field\":\"c.closedDate\",\"op\":\"is_not_null\"}],\"group_by\":[{\"field\":\"hour(c.closedDate)\",\"alias\":\"hour\"}],\"select\":[{\"expr\":\"o.businessDate\",\"alias\":\"date\"},{\"expr\":\"hour(c.closedDate)\",\"alias\":\"hour\"},{\"expr\":\"c.amount\",\"alias\":\"net_sales\",\"agg\":\"sum\"},{\"expr\":\"c.guid\",\"alias\":\"check_count\",\"agg\":\"count\"}],\"order_by\":[{\"field\":\"hour\",\"direction\":\"asc\"}]}"
  }'
echo " - Saved: 41 - Hourly Sales"

# 42. Category Sales
curl -s -X POST "${BASE_URL}/queries" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "42 - Category Sales",
    "description": "Sales by category - replicate category_sales_daily.csv",
    "query": "{\"from\":{\"source_file\":\"orders_full_20251213.json\",\"alias\":\"o\",\"explode_with_context\":{\"path\":\"checks.selections\",\"aliases\":[\"c\",\"sel\"],\"where\":[{\"field\":\"sel.voided\",\"op\":\"!=\",\"value\":true},{\"field\":\"sel.deleted\",\"op\":\"!=\",\"value\":true}]}},\"group_by\":[{\"field\":\"sel.salesCategory.guid\",\"alias\":\"category_guid\"}],\"select\":[{\"expr\":\"o.businessDate\",\"alias\":\"date\"},{\"expr\":\"sel.salesCategory.guid\",\"alias\":\"category_guid\"},{\"expr\":\"sel.price\",\"alias\":\"net_sales\",\"agg\":\"sum\"},{\"expr\":\"sel.guid\",\"alias\":\"item_count\",\"agg\":\"count\"}],\"order_by\":[{\"field\":\"net_sales\",\"direction\":\"desc\"}]}"
  }'
echo " - Saved: 42 - Category Sales"

# 43. Discounts Daily
curl -s -X POST "${BASE_URL}/queries" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "43 - Discounts Report",
    "description": "Discounts by name - replicate discounts_daily.csv",
    "query": "{\"from\":{\"source_file\":\"orders_full_20251213.json\",\"alias\":\"o\",\"explode_with_context\":{\"path\":\"checks.selections.appliedDiscounts\",\"aliases\":[\"c\",\"sel\",\"disc\"],\"where\":[{\"field\":\"sel.voided\",\"op\":\"!=\",\"value\":true}]}},\"group_by\":[{\"field\":\"disc.name\",\"alias\":\"discount_name\"}],\"select\":[{\"expr\":\"o.businessDate\",\"alias\":\"date\"},{\"expr\":\"disc.name\",\"alias\":\"discount_name\"},{\"expr\":\"disc.discountAmount\",\"alias\":\"total_discount\",\"agg\":\"sum\"},{\"expr\":\"disc.guid\",\"alias\":\"discount_count\",\"agg\":\"count\"}],\"order_by\":[{\"field\":\"total_discount\",\"direction\":\"desc\"}]}"
  }'
echo " - Saved: 43 - Discounts Report"

# 50. Full Order Details with Checks
curl -s -X POST "${BASE_URL}/queries" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "50 - Order Details with Checks",
    "description": "Full order details with exploded checks",
    "query": "{\"from\":{\"source_file\":\"orders_full_20251213.json\",\"alias\":\"o\",\"explode_with_context\":{\"path\":\"checks\",\"aliases\":[\"c\"],\"where\":[{\"field\":\"c.voided\",\"op\":\"!=\",\"value\":true}]}},\"select\":[{\"expr\":\"o.guid\",\"alias\":\"order_guid\"},{\"expr\":\"o.businessDate\",\"alias\":\"date\"},{\"expr\":\"o.server.guid\",\"alias\":\"server_guid\"},{\"expr\":\"c.guid\",\"alias\":\"check_guid\"},{\"expr\":\"c.amount\",\"alias\":\"amount\"},{\"expr\":\"c.totalAmount\",\"alias\":\"total_amount\"}],\"limit\":100}"
  }'
echo " - Saved: 50 - Order Details with Checks"

# 51. Employee Master List
curl -s -X POST "${BASE_URL}/queries" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "51 - Employee Master List",
    "description": "Complete employee information - replicate employees.csv",
    "query": "{\"from\":{\"source_file\":\"labor_v1_employees.json\",\"alias\":\"emp\"},\"select\":[{\"expr\":\"emp.guid\",\"alias\":\"guid\"},{\"expr\":\"emp.v2EmployeeGuid\",\"alias\":\"v2EmployeeGuid\"},{\"expr\":\"emp.firstName\",\"alias\":\"firstName\"},{\"expr\":\"emp.lastName\",\"alias\":\"lastName\"},{\"expr\":\"emp.chosenName\",\"alias\":\"chosenName\"},{\"expr\":\"emp.email\",\"alias\":\"email\"},{\"expr\":\"emp.phoneNumber\",\"alias\":\"phoneNumber\"},{\"expr\":\"emp.deleted\",\"alias\":\"deleted\"},{\"expr\":\"emp.createdDate\",\"alias\":\"createdDate\"},{\"expr\":\"emp.modifiedDate\",\"alias\":\"modifiedDate\"}]}"
  }'
echo " - Saved: 51 - Employee Master List"

# 52. Labor Hours Daily
curl -s -X POST "${BASE_URL}/queries" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "52 - Labor Hours Daily",
    "description": "Labor hours by employee per day - replicate labor_hours_daily.csv",
    "query": "{\"from\":{\"source_file\":\"labor_v1_timeEntries_20260130.json\",\"alias\":\"te\"},\"where\":[{\"field\":\"te.inDate\",\"op\":\"is_not_null\"},{\"field\":\"te.outDate\",\"op\":\"is_not_null\"}],\"group_by\":[{\"field\":\"te.businessDate\"},{\"field\":\"te.employeeReference.guid\"}],\"select\":[{\"expr\":\"te.businessDate\",\"alias\":\"date\"},{\"expr\":\"te.employeeReference.guid\",\"alias\":\"employee_guid\"},{\"expr\":\"count(te.guid)\",\"alias\":\"shifts_count\"},{\"expr\":\"sum(te.regularHours)\",\"alias\":\"regular_hours_total\"},{\"expr\":\"sum(te.overtimeHours)\",\"alias\":\"overtime_hours_total\"}],\"order_by\":[{\"field\":\"te.businessDate\",\"direction\":\"desc\"},{\"field\":\"te.employeeReference.guid\",\"direction\":\"asc\"}]}"
  }'
echo " - Saved: 52 - Labor Hours Daily"

echo ""
echo "All queries saved successfully!"
echo "Visit http://localhost:3000/#SavedQueries to view and run them."
