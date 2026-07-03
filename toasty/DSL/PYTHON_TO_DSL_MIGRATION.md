# Python to DSL Migration Guide

## Report Mapping: Python Script → DSL Query

### 1. employees.csv

**Python Approach (toast_30d_report.py)**
```python
def fetch_employees(token: str) -> List[Dict[str, Any]]:
    employees = get_api_data(token, "/labor/v1/employees")
    # Persist raw
    employees_path = OUTPUT_DIR / "raw" / "employees.json"
    with employees_path.open("w", encoding="utf-8") as f:
        json.dump(employees, f, indent=2)
    return employees

def build_employee_map(employees: List[Dict[str, Any]]) -> Dict[str, str]:
    mp: Dict[str, str] = {}
    for emp in employees or []:
        guid = emp.get("guid")
        name = f"{emp.get('firstName', '')} {emp.get('lastName', '')}".strip()
        if guid:
            mp[guid] = name
    return mp
```

**DSL Approach (01_employees.dsl.json)**
```json
{
  "from": {
    "source_file": "labor_v1_employees.json",
    "alias": "emp"
  },
  "select": [
    {"expr": "emp.guid", "alias": "guid"},
    {"expr": "emp.v2EmployeeGuid", "alias": "v2EmployeeGuid"},
    {"expr": "emp.firstName", "alias": "firstName"},
    {"expr": "emp.lastName", "alias": "lastName"},
    {"expr": "emp.chosenName", "alias": "chosenName"},
    {"expr": "emp.email", "alias": "email"},
    {"expr": "emp.phoneNumber", "alias": "phoneNumber"},
    {"expr": "emp.deleted", "alias": "deleted"},
    {"expr": "emp.createdDate", "alias": "createdDate"},
    {"expr": "emp.modifiedDate", "alias": "modifiedDate"}
  ]
}
```

**Status**: ✅ Fully migrated

---

### 2. labor_hours_daily.csv

**Python Approach**
```python
def summarize_labor_hours_day(business_date_iso: str, time_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_emp: Dict[str, Tuple[float, int]] = {}
    for te in time_entries or []:
        emp_guid = ((te.get("employee") or {}).get("guid")) or ((te.get("employeeReference") or {}).get("guid"))
        start = _parse_iso(te.get("inDate") or te.get("startDate"))
        end = _parse_iso(te.get("outDate") or te.get("endDate"))
        if not emp_guid or not start or not end:
            continue
        hours = max((end - start).total_seconds() / 3600.0, 0.0)
        h, c = by_emp.get(emp_guid, (0.0, 0))
        by_emp[emp_guid] = (h + hours, c + 1)

    rows: List[Dict[str, Any]] = []
    for guid, (hours, cnt) in sorted(by_emp.items()):
        rows.append({
            "date": business_date_iso,
            "employee_guid": guid,
            "shifts_count": cnt,
            "hours_total": f"{hours:.2f}",
        })
    return rows
```

**DSL Approach (04_labor_hours_daily.dsl.json)**
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
  "group_by": [
    {"field": "te.businessDate"},
    {"field": "te.employeeReference.guid"}
  ],
  "select": [
    {"expr": "te.businessDate", "alias": "date"},
    {"expr": "te.employeeReference.guid", "alias": "employee_guid"},
    {"expr": "count(te.guid)", "alias": "shifts_count"},
    {"expr": "sum(te.regularHours)", "alias": "regular_hours_total"},
    {"expr": "sum(te.overtimeHours)", "alias": "overtime_hours_total"}
  ]
}
```

**Status**: ✅ Migrated (using API's pre-calculated hours)

---

### 3. labor_shifts_detailed_daily.csv

**Python Approach**
```python
def summarize_labor_shifts_detailed_day(
    business_date_iso: str,
    time_entries: List[Dict[str, Any]],
    job_map: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    job_map = job_map or {}
    rows: List[Dict[str, Any]] = []
    for te in time_entries or []:
        emp_guid = ((te.get("employee") or {}).get("guid")) or ((te.get("employeeReference") or {}).get("guid"))
        job_guid = ((te.get("job") or {}).get("guid")) or ((te.get("jobReference") or {}).get("guid")) or ""
        start = _parse_iso(te.get("inDate") or te.get("startDate"))
        end = _parse_iso(te.get("outDate") or te.get("endDate"))
        if not emp_guid or not start or not end:
            continue
        try:
            start_utc = start.astimezone(timezone.utc)
        except Exception:
            start_utc = start
        try:
            end_utc = end.astimezone(timezone.utc)
        except Exception:
            end_utc = end
        hours = max((end_utc - start_utc).total_seconds() / 3600.0, 0.0)
        job_title = job_map.get(job_guid, "")
        rows.append({
            "date": business_date_iso,
            "employee_guid": emp_guid,
            "job_guid": job_guid,
            "job_title": job_title,
            "start_time_utc": start_utc.isoformat(),
            "end_time_utc": end_utc.isoformat(),
            "hours": f"{hours:.2f}",
        })
    return rows
```

**DSL Approach (05_labor_shifts_detailed_daily.dsl.json)**
```json
{
  "from": {
    "source_file": "labor_v1_timeEntries_20260130.json",
    "alias": "te"
  },
  "joins": [
    {
      "source": {
        "source_file": "labor_v1_employees.json",
        "alias": "emp"
      },
      "on": {
        "left": "te.employeeReference.guid",
        "right": "emp.guid"
      },
      "join_type": "left",
      "skip_nulls": true
    },
    {
      "source": {
        "source_file": "labor_v1_jobs.json",
        "alias": "job"
      },
      "on": {
        "left": "te.jobReference.guid",
        "right": "job.guid"
      },
      "join_type": "left",
      "skip_nulls": true
    }
  ],
  "where": [
    {"field": "te.inDate", "op": "is_not_null"},
    {"field": "te.outDate", "op": "is_not_null"}
  ],
  "select": [
    {"expr": "te.businessDate", "alias": "date"},
    {"expr": "te.employeeReference.guid", "alias": "employee_guid"},
    {"expr": "emp.firstName", "alias": "employee_first_name"},
    {"expr": "emp.lastName", "alias": "employee_last_name"},
    {"expr": "te.jobReference.guid", "alias": "job_guid"},
    {"expr": "job.title", "alias": "job_title"},
    {"expr": "te.inDate", "alias": "start_time_utc"},
    {"expr": "te.outDate", "alias": "end_time_utc"},
    {"expr": "te.regularHours", "alias": "regular_hours"},
    {"expr": "te.overtimeHours", "alias": "overtime_hours"}
  ]
}
```

**Status**: ✅ Migrated (JOINs handle employee/job lookup)

---

### 4. cash_tips_per_shift.csv

**Python Approach**
```python
def summarize_cash_tips_shifts_day(
    business_date_iso: str,
    time_entries: List[Dict[str, Any]],
    job_map: Dict[str, str],
    emp_map: Dict[str, str],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    b_yyyymmdd = normalize_business_date(business_date_iso)
    
    for te in time_entries:
        if (te.get("businessDate") or "") != b_yyyymmdd:
            continue
        emp_ref = te.get("employeeReference") or {}
        emp_guid = emp_ref.get("guid") or ""
        if not emp_guid:
            continue
        emp_name = emp_map.get(emp_guid, "")
        job_guid = (te.get("jobReference") or {}).get("guid")
        job_title = job_map.get(job_guid or "", "")
        start_iso = _to_iso_utc(te.get("inDate") or te.get("startDate"))
        end_iso = _to_iso_utc(te.get("outDate") or te.get("endDate"))
        dct = te.get("declaredCashTips")
        try:
            cash = float(dct) if dct is not None else 0.0
        except Exception:
            cash = 0.0
        rows.append({
            "date": business_date_iso,
            "employee_guid": emp_guid,
            "employee_name": emp_name,
            "job_title": job_title,
            "start_time_utc": start_iso,
            "end_time_utc": end_iso,
            "declared_cash_tips": round(cash, 2),
        })
    return rows
```

**DSL Approach (06_cash_tips_per_shift.dsl.json)**
```json
{
  "from": {
    "source_file": "labor_v1_timeEntries_20260130.json",
    "alias": "te"
  },
  "joins": [
    {
      "source": {
        "source_file": "labor_v1_employees.json",
        "alias": "emp"
      },
      "on": {
        "left": "te.employeeReference.guid",
        "right": "emp.guid"
      },
      "join_type": "left"
    },
    {
      "source": {
        "source_file": "labor_v1_jobs.json",
        "alias": "job"
      },
      "on": {
        "left": "te.jobReference.guid",
        "right": "job.guid"
      },
      "join_type": "left"
    }
  ],
  "where": [
    {"field": "te.declaredCashTips", "op": "is_not_null"}
  ],
  "select": [
    {"expr": "te.businessDate", "alias": "date"},
    {"expr": "te.employeeReference.guid", "alias": "employee_guid"},
    {"expr": "emp.firstName", "alias": "employee_first_name"},
    {"expr": "emp.lastName", "alias": "employee_last_name"},
    {"expr": "job.title", "alias": "job_title"},
    {"expr": "te.inDate", "alias": "start_time_utc"},
    {"expr": "te.outDate", "alias": "end_time_utc"},
    {"expr": "te.declaredCashTips", "alias": "declared_cash_tips"}
  ]
}
```

**Status**: ✅ Migrated

---

### 5. cash_summary_daily.csv

**Python Approach**
```python
def summarize_cash_entries_day(business_date_iso: str, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keyed: Dict[Tuple[str, str], Tuple[float, int]] = {}
    for e in entries or []:
        etype = e.get("type") or "UNKNOWN"
        reason = e.get("reason") or ""
        key = (etype, reason)
        amt, cnt = keyed.get(key, (0.0, 0))
        keyed[key] = (amt + _to_float(e.get("amount")), cnt + 1)
    rows: List[Dict[str, Any]] = []
    for (etype, reason), (amt, cnt) in sorted(keyed.items()):
        rows.append({
            "date": business_date_iso,
            "type": etype,
            "reason": reason,
            "amount_total": f"{amt:.2f}",
            "count": cnt,
        })
    return rows
```

**DSL Approach (08_cash_summary_daily.dsl.json)**
```json
{
  "from": {
    "source_file": "cashmgmt_v1_entries_20260130.json",
    "alias": "ce"
  },
  "group_by": [
    {"field": "ce.type"},
    {"field": "ce.reason"}
  ],
  "select": [
    {"expr": "ce.type", "alias": "type"},
    {"expr": "ce.reason", "alias": "reason"},
    {"expr": "sum(ce.amount)", "alias": "amount_total"},
    {"expr": "count(ce.guid)", "alias": "count"}
  ]
}
```

**Status**: ✅ Migrated

---

## Reports with Partial/Limited Migration

### 6. net_sales_by_employee_daily.csv

**Complexity**: Very High

**Challenge**: Requires nested traversal through orders → checks → payments with attribution logic.

**Python Approach**: ~200 lines with complex attribution logic

**DSL Limitation**: Current DSL doesn't support:
- Nested array explosion with aggregation
- Complex conditional attribution (payment server vs order server)
- Multi-level grouping

**Workaround**: Pre-process orders data into flat structure, then query with DSL.

**Status**: ⚠️ Requires DSL extension or pre-processing

---

### 7. item_mix_daily.csv

**Complexity**: High

**Challenge**: Requires exploding selections array from checks and joining with menu data.

**Python Approach**:
```python
for sel in check.get("selections", []) or []:
    if sel.get("voided") or sel.get("deleted"):
        continue
    item_mix_rows.append({
        "date": business_date_iso,
        "item_guid": item_guid or "",
        "item_name": item_name,
        "sales_category_guid": sales_cat_guid,
        "quantity": qty,
        "net_sales": f"{price:.2f}",
    })
```

**DSL Limitation**: No support for nested array explosion with parent context preservation.

**Workaround**: Flatten orders data before loading to datalake.

**Status**: ⚠️ Requires DSL extension or pre-processing

---

### 8. hourly_sales_daily.csv

**Complexity**: Medium

**Challenge**: Requires date parsing and hour extraction.

**Python Approach**:
```python
def aggregate_hourly_sales(business_date_iso: str, orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[int, float] = {}
    for order in orders or []:
        if is_voided_or_deleted(order):
            continue
        for check in order.get("checks", []) or []:
            if is_voided_or_deleted(check):
                continue
            closed = _parse_iso(check.get("closedDate") or check.get("businessDate"))
            if not closed:
                continue
            hour = closed.hour
            amt = _to_float(check.get("amount"))
            buckets[hour] = buckets.get(hour, 0.0) + amt
    rows: List[Dict[str, Any]] = []
    for hour, total in sorted(buckets.items()):
        rows.append({"date": business_date_iso, "hour": hour, "net_sales": f"{total:.2f}"})
    return rows
```

**DSL Limitation**: No date/time extraction functions.

**Status**: ⚠️ Requires DSL extension

---

## Summary

| Report | Status | Notes |
|--------|--------|-------|
| employees.csv | ✅ Complete | Simple SELECT |
| jobs.csv | ✅ Complete | Simple SELECT |
| revenue_centers.csv | ✅ Complete | Simple SELECT |
| labor_hours_daily.csv | ✅ Complete | GROUP BY with aggregation |
| labor_shifts_detailed_daily.csv | ✅ Complete | JOINs with reference data |
| cash_tips_per_shift.csv | ✅ Complete | JOINs with WHERE filter |
| gratuity_per_shift.csv | ✅ Complete | Simple JOINs |
| cash_summary_daily.csv | ✅ Complete | GROUP BY with aggregation |
| cash_entries_detailed.csv | ✅ Complete | JOINs |
| deposits_summary.csv | ✅ Complete | Simple SELECT |
| net_sales_by_employee_daily.csv | ⚠️ Limited | Needs nested aggregation |
| item_mix_daily.csv | ⚠️ Limited | Needs array explosion |
| category_sales_daily.csv | ⚠️ Limited | Depends on item_mix |
| discounts_daily.csv | ⚠️ Limited | Needs array explosion |
| payments_tips_daily.csv | ⚠️ Limited | Needs nested aggregation |
| hourly_sales_daily.csv | ⚠️ Limited | Needs date functions |
| voids_daily.csv | ⚠️ Limited | Needs complex filtering |
| sales_by_dimension_daily.csv | ⚠️ Limited | Needs order data |
| tips_by_server_daily.csv | ⚠️ Limited | Needs payment aggregation |

**Migrated**: 10/24 reports (42%)
**Partial/Limited**: 14/24 reports (58%)
