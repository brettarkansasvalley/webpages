#!/usr/bin/env python3
import csv
from pathlib import Path

# Simulate the API logic
date = "2025-11-04"
titles = "ww bar,west wing bar"
exclude_placeholders = 1

title_parts = [s.strip().lower() for s in titles.split(",") if s.strip()]
print(f"Looking for titles: {title_parts}")

path_ls = Path("/home/ubuntu/toasty/data/reports/labor_shifts_detailed_daily.csv")
workers = set()

with path_ls.open("r", encoding="utf-8") as f:
    rdr = csv.DictReader(f)
    for r in rdr:
        if (r.get("date") or "").strip() != date.strip():
            continue
        jt = (r.get("job_title") or r.get("jobtitle") or "").strip()
        jt_l = jt.lower()
        if title_parts and not any(p in jt_l for p in title_parts):
            continue
        name = (r.get("employee_name") or r.get("name") or "").strip()
        if not name:
            continue
        print(f"Found: {name} - {jt}")
        workers.add(name)

if exclude_placeholders:
    barred = {"am bar", "ww bar", "low bar"}
    workers = {w for w in workers if w.lower() not in barred}
    print(f"\nAfter excluding placeholders: {sorted(workers)}")
else:
    print(f"\nAll workers: {sorted(workers)}")
