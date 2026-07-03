#!/usr/bin/env python3
from __future__ import annotations

import json
import csv
from pathlib import Path
from typing import Any, Dict, List

# Project roots
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports"
RAW_DIR = DATA_DIR / "raw"

def _employee_display_name(e: Dict[str, Any]) -> str:
    """Preferred name for a Toast employee record."""
    chosen = (e.get("chosenName") or "").strip()
    first = (e.get("firstName") or "").strip()
    last = (e.get("lastName") or "").strip()
    if chosen:
        return chosen
    full = (first + (" " + last if last else "")).strip()
    return full


def build_employee_map(employees: List[Dict[str, Any]]) -> Dict[str, str]:
    """Return map of both guid and v2EmployeeGuid -> display name."""
    m: Dict[str, str] = {}
    for e in employees or []:
        name = _employee_display_name(e)
        if not name:
            continue
        g1 = e.get("guid")
        g2 = e.get("v2EmployeeGuid")
        if g1:
            m[str(g1)] = name
        if g2:
            m[str(g2)] = name
    return m


def _build_orders_report_csv():
    """Build orders_report.csv under REPORTS_DIR by scanning raw orders JSON files."""
    def to_float(x):
        try:
            return float(x)
        except Exception:
            return 0.0

    # Load sales category guid -> name map from menus.json (if available)
    def load_sales_category_name_map() -> Dict[str, str]:
        path = RAW_DIR / "menus" / "menus.json"
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}
        name_map: Dict[str, str] = {}

        def walk(obj: Any):
            if isinstance(obj, dict):
                # Some menu schemas include a salesCategories collection
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

    sales_cat_name_by_guid = load_sales_category_name_map()

    BUCKETS = [
        "Food",
        "Wine",
        "Draft Beer",
        "Liquor",
        "NA Beverage",
        "Bottled Beer",
        "Bottled Wine",
    ]

    def bucket_for_cat_name(name: str) -> str:
        n = (name or "").strip().lower()
        if not n:
            return "Food"
        # bottled wine/beer first
        if ("wine" in n) and ("bottle" in n or "bottled" in n):
            return "Bottled Wine"
        if ("beer" in n) and ("bottle" in n or "bottled" in n):
            return "Bottled Beer"
        # direct category names
        if n == "wine" or ("wine" in n):
            return "Wine"
        if ("draft" in n and "beer" in n) or (n == "draft beer"):
            return "Draft Beer"
        if any(k in n for k in ["liquor", "spirit", "cocktail", "whiskey", "vodka", "gin", "tequila", "rum"]):
            return "Liquor"
        if any(k in n for k in ["na beverage", "non-alcoholic", "n/a beverage", "mocktail", "soda", "juice", "coffee", "tea"]):
            return "NA Beverage"
        if "beer" in n:
            return "Draft Beer"
        return "Food"

    orders_dir = RAW_DIR / "orders"
    files = sorted(orders_dir.glob("*.json")) if orders_dir.exists() else []
    if not files:
        print("No orders files found at", orders_dir)
        return

    # Build employee GUID->name map for server lookups
    emp_map: Dict[str, str] = {}
    try:
        with (RAW_DIR / "employees.json").open("r", encoding="utf-8") as f:
            employees = json.load(f) or []
        emp_map = build_employee_map(employees) if employees else {}
    except Exception:
        emp_map = {}

    headers = [
        "business_date",
        "display_number",
        "order_guid",
        "server_guid",
        "server_name",
        "food_sales",
        "wine_sales",
        "draft_beer_sales",
        "liquor_sales",
        "na_beverage_sales",
        "bottled_beer_sales",
        "bottled_wine_sales",
        "check_index",
        "payment_index",
        "payment_guid",
        "check_tax_amount",
        "check_net_amount",
        "check_total_amount",
        "check_service_charges",
        "payment_type",
        "card_type",
        "payment_entry_mode",
        "payment_funding_type",
        "payment_amount",
        "payment_tip_amount",
        "payment_amount_tendered",
        "payment_processing_fee",
        "payment_mca_repayment",
        "payment_server_guid",
        "payment_server_name",
    ]

    # Optional: load payments_report.csv to backfill funding type by payment_guid
    payments_map: Dict[str, str] = {}
    payments_csv = REPORTS_DIR / "payments_report.csv"
    if payments_csv.exists():
        try:
            with payments_csv.open("r", encoding="utf-8") as f:
                rdr = csv.DictReader(f)
                for rec in rdr:
                    pg = (rec.get("payment_guid") or "").strip()
                    ft = (rec.get("funding_type") or "").strip()
                    if pg and ft and pg not in payments_map:
                        payments_map[pg] = ft
        except Exception:
            payments_map = {}

    rows: List[Dict[str, Any]] = []
    # Pre-compute per-order bucket totals so we can attach to each row for that order
    order_bucket_totals: Dict[str, Dict[str, float]] = {}
    for p in files:
        try:
            with p.open("r", encoding="utf-8") as f:
                orders = json.load(f) or []
        except Exception:
            continue
        for o in orders:
            biz_date = o.get("businessDate", "")
            order_guid = o.get("guid", "")
            display_number = o.get("displayNumber", "")
            # Order-level server
            order_server_guid = ((o.get("server") or {}).get("guid") or "")
            order_server_name = emp_map.get(order_server_guid, "") if order_server_guid else ""
            # Compute bucket totals once per order
            if order_guid and order_guid not in order_bucket_totals:
                buckets = {k: 0.0 for k in BUCKETS}
                for c in (o.get("checks", []) or []):
                    if c.get("voided") or c.get("deleted"):
                        continue
                    for sel in (c.get("selections", []) or []):
                        if sel.get("voided") or sel.get("deleted"):
                            continue
                        price = to_float(sel.get("price"))
                        # Determine category name
                        sc_guid = ((sel.get("salesCategory") or {}).get("guid")) or ""
                        sc_name = sales_cat_name_by_guid.get(str(sc_guid), "")
                        bucket = bucket_for_cat_name(sc_name)
                        # Fallback to infer from item display name when category name is missing
                        if (not sc_name) or (bucket == "Food"):
                            disp = (sel.get("displayName") or "").strip().lower()
                            if disp:
                                if any(k in disp for k in ["cabernet", "pinot", "merlot", "chardonnay", "sauvignon", "malbec", "grigio", "riesling", "rose", "rosé", "wine"]):
                                    bucket = "Wine"
                                elif any(k in disp for k in ["draft", "on tap", "pour", "pint"]) and "beer" in disp:
                                    bucket = "Draft Beer"
                                elif any(k in disp for k in ["beer", "lager", "ipa", "stout", "ale"]) and "draft" in disp:
                                    bucket = "Draft Beer"
                                elif any(k in disp for k in ["vodka", "whiskey", "whisky", "gin", "tequila", "rum", "bourbon", "rye", "mezcal", "cocktail"]):
                                    bucket = "Liquor"
                                elif any(k in disp for k in ["na", "non-alcoholic", "mocktail", "soda", "juice", "coffee", "tea"]):
                                    bucket = "NA Beverage"
                        buckets[bucket] = buckets.get(bucket, 0.0) + price
                order_bucket_totals[order_guid] = buckets
            checks = o.get("checks", []) or []
            for ci, c in enumerate(checks):
                if c.get("voided") or c.get("deleted"):
                    continue
                tax_amount = to_float(c.get("taxAmount"))
                net_amount = to_float(c.get("amount"))
                total_amount = to_float(c.get("totalAmount"))
                svc = 0.0
                try:
                    for sc in (c.get("appliedServiceCharges", []) or []):
                        svc += to_float((sc or {}).get("chargeAmount"))
                except Exception:
                    pass

                payments = c.get("payments", []) or []
                if not payments:
                    b = order_bucket_totals.get(order_guid, {})
                    rows.append({
                        "business_date": biz_date,
                        "order_guid": order_guid,
                        "display_number": display_number,
                        "server_guid": order_server_guid,
                        "server_name": order_server_name,
                        "food_sales": f"{b.get('Food', 0.0):.2f}",
                        "wine_sales": f"{b.get('Wine', 0.0):.2f}",
                        "draft_beer_sales": f"{b.get('Draft Beer', 0.0):.2f}",
                        "liquor_sales": f"{b.get('Liquor', 0.0):.2f}",
                        "na_beverage_sales": f"{b.get('NA Beverage', 0.0):.2f}",
                        "bottled_beer_sales": f"{b.get('Bottled Beer', 0.0):.2f}",
                        "bottled_wine_sales": f"{b.get('Bottled Wine', 0.0):.2f}",
                        "check_index": ci,
                        "payment_index": "",
                        "payment_guid": "",
                        "check_tax_amount": f"{tax_amount:.2f}",
                        "check_net_amount": f"{net_amount:.2f}",
                        "check_total_amount": f"{total_amount:.2f}",
                        "check_service_charges": f"{svc:.2f}",
                        "payment_type": "",
                        "card_type": "",
                        "payment_entry_mode": "",
                        "payment_funding_type": "",
                        "payment_amount": "",
                        "payment_tip_amount": "",
                        "payment_amount_tendered": "",
                        "payment_processing_fee": "",
                        "payment_mca_repayment": "",
                        "payment_server_guid": "",
                        "payment_server_name": "",
                    })
                    continue

                for pi, pay in enumerate(payments):
                    pay_server_guid = (((pay or {}).get("server") or {}).get("guid") or "")
                    pay_server_name = emp_map.get(pay_server_guid, "") if pay_server_guid else ""
                    pay_guid = str(pay.get("guid") or "")
                    pay_entry_mode = str(pay.get("entryMode") or "")
                    pay_funding_type = str(pay.get("fundingType") or "")  # may be empty in Orders payload
                    if (not pay_funding_type) and pay_guid and payments_map:
                        pay_funding_type = payments_map.get(pay_guid, "")
                    b = order_bucket_totals.get(order_guid, {})
                    rows.append({
                        "business_date": biz_date,
                        "order_guid": order_guid,
                        "display_number": display_number,
                        "server_guid": order_server_guid,
                        "server_name": order_server_name,
                        "food_sales": f"{b.get('Food', 0.0):.2f}",
                        "wine_sales": f"{b.get('Wine', 0.0):.2f}",
                        "draft_beer_sales": f"{b.get('Draft Beer', 0.0):.2f}",
                        "liquor_sales": f"{b.get('Liquor', 0.0):.2f}",
                        "na_beverage_sales": f"{b.get('NA Beverage', 0.0):.2f}",
                        "bottled_beer_sales": f"{b.get('Bottled Beer', 0.0):.2f}",
                        "bottled_wine_sales": f"{b.get('Bottled Wine', 0.0):.2f}",
                        "check_index": ci,
                        "payment_index": pi,
                        "payment_guid": pay_guid,
                        "check_tax_amount": f"{tax_amount:.2f}",
                        "check_net_amount": f"{net_amount:.2f}",
                        "check_total_amount": f"{total_amount:.2f}",
                        "check_service_charges": f"{svc:.2f}",
                        "payment_type": pay.get("type", ""),
                        "card_type": pay.get("cardType", ""),
                        "payment_entry_mode": pay_entry_mode,
                        "payment_funding_type": pay_funding_type,
                        "payment_amount": f"{to_float(pay.get('amount')):.2f}",
                        "payment_tip_amount": f"{to_float(pay.get('tipAmount')):.2f}",
                        "payment_amount_tendered": f"{to_float(pay.get('amountTendered')):.2f}",
                        "payment_processing_fee": f"{to_float(pay.get('originalProcessingFee')):.2f}",
                        "payment_mca_repayment": f"{to_float(pay.get('mcaRepaymentAmount')):.2f}",
                        "payment_server_guid": pay_server_guid,
                        "payment_server_name": pay_server_name,
                    })

    # Cap rows for CSV as well to avoid massive files
    MAX_ROWS = 50000
    if len(rows) > MAX_ROWS:
        rows = rows[:MAX_ROWS]

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / "orders_report.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"Wrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    _build_orders_report_csv()
