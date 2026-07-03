#!/usr/bin/env python3
from __future__ import annotations
import os
import csv
import json
from datetime import date, timedelta
from typing import Any, Dict, List
import requests
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports"

API_HOST = os.getenv("TOAST_API_HOST", "https://ws-api.toasttab.com")
CLIENT_ID = os.getenv("TOAST_CLIENT_ID")
CLIENT_SECRET = os.getenv("TOAST_CLIENT_SECRET")
RESTAURANT_GUID = os.getenv("TOAST_RESTAURANT_GUID")
# Default to a plausible payments endpoint; allow override
PAYMENTS_PATH_TEMPLATE = os.getenv(
    "TOAST_PAYMENTS_PATH_TEMPLATE",
    "/orders/v2/payments?businessDate={YYYYMMDD}",
)

class ToastAuthError(Exception):
    pass


def _auth_token() -> str:
    if not (CLIENT_ID and CLIENT_SECRET and RESTAURANT_GUID):
        raise ToastAuthError("Missing TOAST_* env vars (TOAST_CLIENT_ID, TOAST_CLIENT_SECRET, TOAST_RESTAURANT_GUID)")
    url = f"{API_HOST}/authentication/v1/authentication/login"
    payload = {
        "clientId": CLIENT_ID,
        "clientSecret": CLIENT_SECRET,
        "userAccessType": "TOAST_MACHINE_CLIENT",
    }
    resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
    resp.raise_for_status()
    data = resp.json() or {}
    token = data.get("accessToken") or (data.get("token") or {}).get("accessToken")
    if not token:
        raise ToastAuthError("Toast auth did not return accessToken")
    return token


def _get_json(token: str, path: str) -> Any:
    url = f"{API_HOST}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Toast-Restaurant-External-ID": RESTAURANT_GUID,
        "Accept": "application/json",
    }
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json()


def fetch_payments_for_date(yyyy_mm_dd: str) -> List[Dict[str, Any]]:
    yyyymmdd = yyyy_mm_dd.replace("-", "")
    token = _auth_token()
    path = PAYMENTS_PATH_TEMPLATE.format(YYYYMMDD=yyyymmdd)
    data = _get_json(token, path)
    # Expecting a list; if object with 'results', handle both
    if isinstance(data, dict) and "results" in data:
        items = data.get("results") or []
    else:
        items = data or []
    if not isinstance(items, list):
        # Try common container field names
        items = data.get("payments") if isinstance(data, dict) else []
        if not isinstance(items, list):
            items = []
    return items


def write_payments_csv(rows: List[Dict[str, Any]], out_path: Path) -> None:
    headers = [
        "business_date",
        "payment_guid",
        "order_guid",
        "check_guid",
        "payment_type",
        "card_brand",
        "funding_type",
        "entry_mode",
        "amount",
        "tip_amount",
        "server_guid",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def normalize_payment_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    def g(obj, *keys, default=""):
        cur = obj
        for k in keys:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(k)
        return cur if cur is not None else default

    return {
        "business_date": str(g(raw, "businessDate", default="")),
        "payment_guid": str(g(raw, "guid", default="")),
        "order_guid": str(g(raw, "orderGuid", default=g(raw, "order", "guid", default=""))),
        "check_guid": str(g(raw, "checkGuid", default=g(raw, "check", "guid", default=""))),
        "payment_type": str(g(raw, "type", default="")),
        "card_brand": str(g(raw, "cardType", default=g(raw, "card", "brand", default=""))),
        "funding_type": str(g(raw, "fundingType", default=g(raw, "card", "fundingType", default=""))),
        "entry_mode": str(g(raw, "entryMode", default="")),
        "amount": str(g(raw, "amount", default="")),
        "tip_amount": str(g(raw, "tipAmount", default="")),
        "server_guid": str(g(raw, "server", "guid", default="")),
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Fetch Toast Payments and write payments_report.csv")
    ap.add_argument("--start", dest="start", help="Start date YYYY-MM-DD", required=False)
    ap.add_argument("--end", dest="end", help="End date YYYY-MM-DD", required=False)
    args = ap.parse_args()

    # Default: today only
    if args.start:
        s = date.fromisoformat(args.start)
    else:
        s = date.today()
    if args.end:
        e = date.fromisoformat(args.end)
    else:
        e = s

    all_rows: List[Dict[str, Any]] = []
    d = s
    while d <= e:
        dstr = d.isoformat()
        try:
            payments = fetch_payments_for_date(dstr)
        except Exception as exc:
            print(f"ERROR fetching payments for {dstr}: {exc}")
            d += timedelta(days=1)
            continue
        for p in payments:
            norm = normalize_payment_row(p)
            if not norm.get("business_date"):
                norm["business_date"] = dstr.replace("-", "")
            all_rows.append(norm)
        d += timedelta(days=1)

    out_path = REPORTS_DIR / "payments_report.csv"
    write_payments_csv(all_rows, out_path)
    print(f"Wrote {len(all_rows)} rows to {out_path}")


if __name__ == "__main__":
    main()
