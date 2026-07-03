#!/usr/bin/env python3
"""
Build data/reports/shift_orders_report.csv from raw orders and shift windows.
This mirrors the /reports/shift_orders_report.csv endpoint logic so you can
run it offline from the CLI.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

# Project paths
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports"
RAW_DIR = DATA_DIR / "raw"

# Reuse helpers similar to app.py

def _f(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def _parse_iso_any(s: str | None):
    from datetime import datetime
    if not s:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            # Handle Z suffix
            ss = s.replace("Z", "+00:00")
            return datetime.fromisoformat(ss)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def load_sales_category_name_map() -> Dict[str, str]:
    path = RAW_DIR / "menus" / "menus.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    name_map: Dict[str, str] = {}

    def walk(obj: Any):
        if isinstance(obj, dict):
            if (obj.get("entityType") == "SalesCategory") and obj.get("guid"):
                nm = (obj.get("name") or obj.get("label") or obj.get("displayName") or "").strip()
                if nm:
                    name_map[str(obj["guid"])] = str(nm)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data)
    return name_map


def bucket_for_cat_name(name: str) -> str:
    n = (name or "").strip().lower()
    if not n:
        return "Food"
    if ("wine" in n) and ("bottle" in n or "bottled" in n):
        return "Bottled Wine"
    if ("beer" in n) and ("bottle" in n or "bottled" in n):
        return "Bottled Beer"
    if n == "wine" or ("wine" in n):
        return "Wine"
    if ("draft" in n and "beer" in n) or (n == "draft beer"):
        return "Draft Beer"
    if any(k in n for k in ["liquor","spirit","cocktail","whiskey","vodka","gin","tequila","rum"]):
        return "Liquor"
    if any(k in n for k in ["na beverage","non-alcoholic","n/a beverage","mocktail","soda","juice","coffee","tea"]):
        return "NA Beverage"
    if "beer" in n:
        return "Draft Beer"
    return "Food"


def load_employee_map() -> Dict[str, str]:
    m: Dict[str, str] = {}
    p = RAW_DIR / "employees.json"
    try:
        emps = json.loads(p.read_text(encoding="utf-8")) or []
    except Exception:
        return m
    def display_name(e: Dict[str, Any]) -> str:
        chosen = (e.get("chosenName") or "").strip()
        first = (e.get("firstName") or "").strip()
        last = (e.get("lastName") or "").strip()
        return chosen or (first + (" " + last if last else "")).strip()
    for e in emps:
        name = display_name(e)
        if not name:
            continue
        for k in ("guid", "v2EmployeeGuid"):
            v = (e.get(k) or "").strip()
            if v:
                m[v] = name
    return m


def build_shifts() -> List[Dict[str, Any]]:
    shifts: List[Dict[str, Any]] = []
    emp_map = load_employee_map()
    path = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
    if path.exists():
        rdr = csv.DictReader(path.open("r", encoding="utf-8"))
        for r in rdr:
            try:
                d = (r.get("date") or "").strip()
                eg = (r.get("employee_guid") or "").strip()
                if not (d and eg):
                    continue
                st = _parse_iso_any(r.get("start_time_utc") or r.get("start") or "")
                en = _parse_iso_any(r.get("end_time_utc") or r.get("end") or "")
                if not (st and en and en > st):
                    continue
                name = (r.get("employee_name") or r.get("name") or emp_map.get(eg) or "").strip()
                jt = (r.get("job_title") or r.get("jobtitle") or "").strip()
                shifts.append({"date": d, "employee_guid": eg, "employee_name": name, "job_title": jt, "start": st, "end": en})
            except Exception:
                continue
        return shifts
    # Fallback from time_entries
    te_dir = RAW_DIR / "time_entries"
    for f in sorted(te_dir.glob("*.json")):
        try:
            day_iso = f.stem
            te_list = json.loads(f.read_text(encoding="utf-8")) or []
        except Exception:
            continue
        for te in (te_list or []):
            try:
                eg = ((te.get("employeeReference") or {}).get("guid")) or ""
                if not eg:
                    continue
                st = _parse_iso_any(te.get("inDate") or te.get("startDate"))
                en = _parse_iso_any(te.get("outDate") or te.get("endDate"))
                if not (st and en and en > st):
                    continue
                name = emp_map.get(eg, "")
                jt = te.get("jobTitle") or ((te.get("job") or {}).get("name")) or ""
                shifts.append({"date": day_iso, "employee_guid": eg, "employee_name": name, "job_title": jt, "start": st, "end": en})
            except Exception:
                continue
    return shifts


def load_orders_for(date_iso: str) -> List[Dict[str, Any]]:
    p = RAW_DIR / "orders" / f"{date_iso}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    except Exception:
        return []


def build_order_bucket_totals(orders: List[Dict[str, Any]], sales_cat_map: Dict[str, str]) -> Dict[str, Dict[str, float]]:
    BUCKETS = ["Food","Wine","Draft Beer","Liquor","NA Beverage","Bottled Beer","Bottled Wine"]
    totals: Dict[str, Dict[str, float]] = {}
    for o in (orders or []):
        og = str(o.get("guid") or "")
        if not og or og in totals:
            continue
        bmap = {k: 0.0 for k in BUCKETS}
        for c in (o.get("checks") or []):
            if c.get("voided") or c.get("deleted"):
                continue
            for sel in (c.get("selections") or []):
                if sel.get("voided") or sel.get("deleted"):
                    continue
                price = _f(sel.get("price"))
                sc_guid = ((sel.get("salesCategory") or {}).get("guid")) or ""
                sc_name = sales_cat_map.get(str(sc_guid), "")
                bucket = bucket_for_cat_name(sc_name)
                if (not sc_name) or (bucket == "Food"):
                    disp = (sel.get("displayName") or "").strip().lower()
                    if disp:
                        if any(k in disp for k in ["cabernet","pinot","merlot","chardonnay","sauvignon","malbec","grigio","riesling","rose","rosé","wine"]):
                            bucket = "Wine"
                        elif any(k in disp for k in ["draft","on tap","pour","pint"]) and "beer" in disp:
                            bucket = "Draft Beer"
                        elif any(k in disp for k in ["beer","lager","ipa","stout","ale"]) and "draft" in disp:
                            bucket = "Draft Beer"
                        elif any(k in disp for k in ["vodka","whiskey","whisky","gin","tequila","rum","bourbon","rye","mezcal","cocktail"]):
                            bucket = "Liquor"
                        elif any(k in disp for k in ["na","non-alcoholic","mocktail","soda","juice","coffee","tea"]):
                            bucket = "NA Beverage"
                bmap[bucket] = bmap.get(bucket, 0.0) + price
        totals[og] = bmap
    return totals


def main() -> int:
    from datetime import timezone
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    emp_map = load_employee_map()
    sales_cat_map = load_sales_category_name_map()
    shifts = build_shifts()

    BUCKETS = ["Food","Wine","Draft Beer","Liquor","NA Beverage","Bottled Beer","Bottled Wine"]
    out_rows: List[Dict[str, Any]] = []

    for sh in shifts:
        d = sh["date"]
        st = sh["start"]
        en = sh["end"]
        eg = sh["employee_guid"]
        name = sh.get("employee_name") or emp_map.get(eg, "")
        jt = sh.get("job_title") or ""

        orders = load_orders_for(d)
        buckets_tot = build_order_bucket_totals(orders, sales_cat_map)

        orders_seen: set[str] = set()
        checks_count = 0
        agg = {k: 0.0 for k in BUCKETS}
        tax_sum = net_sum = total_sum = svc_sum = 0.0
        cash_tips_sum = noncash_tips_sum = 0.0

        for o in (orders or []):
            order_guid = str(o.get("guid") or "")
            # Iterate checks
            for c in (o.get("checks") or []):
                if c.get("voided") or c.get("deleted"):
                    continue
                ts = c.get("paidDate") or c.get("closedDate") or c.get("openedDate")
                dt = _parse_iso_any(ts)
                try:
                    if dt:
                        dt = dt.astimezone(timezone.utc)
                except Exception:
                    pass
                if not (dt and st <= dt <= en):
                    continue

                # Attribution by payment server proportion
                payments = (c.get("payments") or [])
                server_amounts: Dict[str, float] = {}
                for p in payments:
                    srv = (p.get("server") or {})
                    sid = (srv.get("guid") or srv.get("id") or srv.get("v2EmployeeGuid") or "").strip()
                    amt = _f(p.get("amount"))
                    if sid and amt > 0:
                        server_amounts[sid] = server_amounts.get(sid, 0.0) + amt
                total_amt = sum(server_amounts.values())
                frac = server_amounts.get(eg, 0.0) / total_amt if total_amt > 0 else 0.0
                if frac <= 0:
                    continue

                checks_count += 1
                if order_guid:
                    orders_seen.add(order_guid)
                bmap = buckets_tot.get(order_guid, {})
                for bk in BUCKETS:
                    agg[bk] += (bmap.get(bk, 0.0) * frac)
                tax_sum += _f(c.get("taxAmount")) * frac
                net_sum += _f(c.get("amount")) * frac
                total_sum += _f(c.get("totalAmount")) * frac
                svc = 0.0
                for sc in (c.get("appliedServiceCharges", []) or []):
                    svc += _f((sc or {}).get("chargeAmount"))
                svc_sum += svc * frac
                for p in payments:
                    srv = (p.get("server") or {})
                    sid = (srv.get("guid") or srv.get("id") or srv.get("v2EmployeeGuid") or "").strip()
                    if sid != eg:
                        continue
                    tip_amt = _f(p.get("tipAmount"))
                    ptype = (p.get("type") or "").upper()
                    if ptype == "CASH":
                        cash_tips_sum += tip_amt
                    else:
                        noncash_tips_sum += tip_amt

        out_rows.append({
            "date": d,
            "employee_guid": eg,
            "employee_name": name,
            "job_title": jt,
            "start_time_utc": sh["start"].isoformat(),
            "end_time_utc": sh["end"].isoformat(),
            "orders_count": len(orders_seen),
            "checks_count": checks_count,
            "food_sales": f"{agg['Food']:.2f}",
            "wine_sales": f"{agg['Wine']:.2f}",
            "draft_beer_sales": f"{agg['Draft Beer']:.2f}",
            "liquor_sales": f"{agg['Liquor']:.2f}",
            "na_beverage_sales": f"{agg['NA Beverage']:.2f}",
            "bottled_beer_sales": f"{agg['Bottled Beer']:.2f}",
            "bottled_wine_sales": f"{agg['Bottled Wine']:.2f}",
            "check_tax_amount": f"{tax_sum:.2f}",
            "check_net_amount": f"{net_sum:.2f}",
            "check_total_amount": f"{total_sum:.2f}",
            "check_service_charges": f"{svc_sum:.2f}",
            "cash_tips": f"{cash_tips_sum:.2f}",
            "non_cash_tips": f"{noncash_tips_sum:.2f}",
        })

    # Write CSV
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / "shift_orders_report.csv"
    headers = [
        "date","employee_guid","employee_name","job_title","start_time_utc","end_time_utc",
        "orders_count","checks_count",
        "food_sales","wine_sales","draft_beer_sales","liquor_sales","na_beverage_sales","bottled_beer_sales","bottled_wine_sales",
        "check_tax_amount","check_net_amount","check_total_amount","check_service_charges",
        "cash_tips","non_cash_tips",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    print(f"Wrote {len(out_rows)} rows to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
