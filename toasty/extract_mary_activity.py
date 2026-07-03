#!/usr/bin/env python3
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

MARY_GUID = "6616e563-7186-4501-93e5-6e2f3e976022"

INPUT_FILES = [
    "data/raw/orders/2025-08-07.json",
    "data/raw/orders/2025-08-08.json",
]

REPORTS_DIR = "data/reports/"


def ensure_reports_dir():
    os.makedirs(REPORTS_DIR, exist_ok=True)


def safe_get(d: Dict[str, Any], *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def load_orders(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_from_order(order: Dict[str, Any], file_date: str) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    order_guid = order.get("guid")
    order_display = order.get("displayNumber")
    order_business_date = order.get("businessDate")
    order_paid_date = order.get("paidDate")
    order_server_guid = safe_get(order, "server", "guid")
    served_by_mary = order_server_guid == MARY_GUID

    for check in order.get("checks", []) or []:
        check_guid = check.get("guid")
        check_display = check.get("displayNumber")

        # Payments where Mary is the payment server
        payments = check.get("payments", []) or []
        mary_payment_entries: List[Dict[str, Any]] = []
        for p in payments:
            p_server_guid = safe_get(p, "server", "guid")
            if p_server_guid == MARY_GUID:
                mary_payment_entries.append({
                    "payment_guid": p.get("guid"),
                    "type": p.get("type"),
                    "amount": p.get("amount"),
                    "tipAmount": p.get("tipAmount"),
                    "amountTendered": p.get("amountTendered"),
                    "paymentStatus": p.get("paymentStatus"),
                    "paidDate": p.get("paidDate"),
                    "paidBusinessDate": p.get("paidBusinessDate"),
                    "cardType": p.get("cardType"),
                    "last4Digits": p.get("last4Digits"),
                    "cardEntryMode": p.get("cardEntryMode"),
                    "checkGuid": p.get("checkGuid"),
                    "orderGuid": p.get("orderGuid"),
                })

        # Discounts approved by Mary on the check
        discounts = check.get("appliedDiscounts", []) or []
        mary_discounts: List[Dict[str, Any]] = []
        for d in discounts:
            approver_guid = safe_get(d, "approver", "guid")
            if approver_guid == MARY_GUID:
                mary_discounts.append({
                    "discount_guid": d.get("guid"),
                    "name": d.get("name"),
                    "discountType": d.get("discountType"),
                    "discountPercent": d.get("discountPercent"),
                    "discountAmount": d.get("discountAmount"),
                    "appliedDiscountReason": safe_get(d, "appliedDiscountReason", "name"),
                    "comment": safe_get(d, "appliedDiscountReason", "comment"),
                })

        # Row per Mary payment, if any
        if mary_payment_entries:
            for mpe in mary_payment_entries:
                results.append({
                    "file_date": file_date,
                    "orderGuid": order_guid,
                    "orderDisplayNumber": order_display,
                    "orderBusinessDate": order_business_date,
                    "orderPaidDate": order_paid_date,
                    "checkGuid": check_guid,
                    "checkDisplayNumber": check_display,
                    "servedByMary": served_by_mary,
                    "hasMaryPayment": True,
                    "payment": mpe,
                    "discountsApprovedByMary": mary_discounts,
                })
        else:
            # If no Mary payment, but Mary served the order or approved a discount, include a summary row
            if served_by_mary or mary_discounts:
                results.append({
                    "file_date": file_date,
                    "orderGuid": order_guid,
                    "orderDisplayNumber": order_display,
                    "orderBusinessDate": order_business_date,
                    "orderPaidDate": order_paid_date,
                    "checkGuid": check_guid,
                    "checkDisplayNumber": check_display,
                    "servedByMary": served_by_mary,
                    "hasMaryPayment": False,
                    "payment": None,
                    "discountsApprovedByMary": mary_discounts,
                })

    return results


def build_outputs(all_entries: List[Dict[str, Any]]):
    # JSON output
    json_out = os.path.join(REPORTS_DIR, "mary_widaman_checks_2025-08-07_08.json")
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(all_entries, f, indent=2, ensure_ascii=False)

    # CSV output (one row per result; if payment is None, leave payment fields blank)
    csv_out = os.path.join(REPORTS_DIR, "mary_widaman_checks_2025-08-07_08.csv")
    headers = [
        "file_date",
        "orderGuid",
        "orderDisplayNumber",
        "orderBusinessDate",
        "orderPaidDate",
        "checkGuid",
        "checkDisplayNumber",
        "servedByMary",
        "hasMaryPayment",
        "payment_guid",
        "payment_type",
        "payment_amount",
        "payment_tipAmount",
        "payment_amountTendered",
        "payment_status",
        "payment_paidDate",
        "payment_paidBusinessDate",
        "payment_cardType",
        "payment_last4",
        "payment_cardEntryMode",
        "discountsApprovedByMary_count",
    ]
    with open(csv_out, "w", encoding="utf-8") as f:
        f.write(",".join(headers) + "\n")
        for e in all_entries:
            p = e.get("payment") or {}
            row = [
                str(e.get("file_date", "")),
                str(e.get("orderGuid", "")),
                str(e.get("orderDisplayNumber", "")),
                str(e.get("orderBusinessDate", "")),
                str(e.get("orderPaidDate", "")),
                str(e.get("checkGuid", "")),
                str(e.get("checkDisplayNumber", "")),
                str(e.get("servedByMary", False)),
                str(e.get("hasMaryPayment", False)),
                str(p.get("payment_guid", "")),
                str(p.get("type", "")),
                str(p.get("amount", "")),
                str(p.get("tipAmount", "")),
                str(p.get("amountTendered", "")),
                str(p.get("paymentStatus", "")),
                str(p.get("paidDate", "")),
                str(p.get("paidBusinessDate", "")),
                str(p.get("cardType", "")),
                str(p.get("last4Digits", "")),
                str(p.get("cardEntryMode", "")),
                str(len(e.get("discountsApprovedByMary", []) or [])),
            ]
            # naive CSV escaping: wrap fields with commas in quotes
            def esc(v: str) -> str:
                s = v
                if "," in s or "\n" in s or '"' in s:
                    s = '"' + s.replace('"', '""') + '"'
                return s
            f.write(",".join(esc(x) for x in row) + "\n")



def main():
    ensure_reports_dir()
    all_entries: List[Dict[str, Any]] = []
    for path in INPUT_FILES:
        file_date = os.path.basename(path).split(".")[0]  # e.g., 2025-08-07
        full_path = os.path.join(os.path.dirname(__file__), path)
        if not os.path.exists(full_path):
            print(f"WARN: file not found: {full_path}")
            continue
        orders = load_orders(full_path)
        if not isinstance(orders, list):
            print(f"WARN: unexpected JSON root (not a list) in {full_path}")
            continue
        for order in orders:
            all_entries.extend(extract_from_order(order, file_date))

    # Sort by file_date then orderDisplayNumber then checkDisplayNumber then payment_paidDate
    def sort_key(e: Dict[str, Any]):
        p = e.get("payment") or {}
        return (
            e.get("file_date", ""),
            str(e.get("orderDisplayNumber", "")),
            str(e.get("checkDisplayNumber", "")),
            p.get("paidDate", ""),
        )

    all_entries.sort(key=sort_key)

    build_outputs(all_entries)
    print(f"Wrote {len(all_entries)} entries to {REPORTS_DIR}")


if __name__ == "__main__":
    main()
