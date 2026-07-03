#!/usr/bin/env python3
from __future__ import annotations
import os
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PAYMENTS_DIR = RAW_DIR / "payments"

API_HOST = os.getenv("TOAST_API_HOST", "https://ws-api.toasttab.com")
CLIENT_ID = os.getenv("TOAST_CLIENT_ID")
CLIENT_SECRET = os.getenv("TOAST_CLIENT_SECRET")
RESTAURANT_GUID = os.getenv("TOAST_RESTAURANT_GUID")
PAYMENTS_PATH_TEMPLATE = os.getenv(
    "TOAST_PAYMENTS_PATH_TEMPLATE",
    "/orders/v2/payments?businessDate={YYYYMMDD}",
)

class ToastAuthError(Exception):
    pass


def _auth_token() -> str:
    if not (CLIENT_ID and CLIENT_SECRET and RESTAURANT_GUID):
        raise ToastAuthError(
            "Missing TOAST_* env vars (TOAST_CLIENT_ID, TOAST_CLIENT_SECRET, TOAST_RESTAURANT_GUID)"
        )
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


def fetch_and_save(days: int = 30, end: date | None = None) -> int:
    if end is None:
        end = date.today()
    # We'll fetch the last `days` complete days, excluding today by default
    # i = 1 => yesterday, ..., i = days => days ago
    token = _auth_token()
    PAYMENTS_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0
    for i in range(1, days + 1):
        d = end - timedelta(days=i)
        yyyy_mm_dd = d.isoformat()
        yyyymmdd = yyyy_mm_dd.replace("-", "")
        path = PAYMENTS_PATH_TEMPLATE.format(YYYYMMDD=yyyymmdd)
        try:
            data = _get_json(token, path)
        except Exception as exc:
            print(f"ERROR fetching {yyyy_mm_dd}: {exc}")
            continue
        out_path = PAYMENTS_DIR / f"{yyyy_mm_dd}.json"
        try:
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            saved += 1
            print(f"Saved {out_path}")
        except Exception as exc:
            print(f"ERROR saving {out_path}: {exc}")
    return saved


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Fetch last N days of Payments JSON into data/raw/payments/")
    ap.add_argument("--days", type=int, default=30, help="Number of past complete days to fetch (default 30)")
    ap.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD (default: today)")
    args = ap.parse_args()
    end = date.fromisoformat(args.end) if args.end else None
    n = fetch_and_save(days=args.days, end=end)
    print(f"Done. Saved {n} files in {PAYMENTS_DIR}")


if __name__ == "__main__":
    main()
