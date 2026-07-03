#!/usr/bin/env python3
"""
Web-ready Toast API client for fetching employee financials by date.
Reads credentials from environment variables:
- TOAST_CLIENT_ID
- TOAST_CLIENT_SECRET
- TOAST_RESTAURANT_GUID
Optional:
- TOAST_API_HOST (default: https://ws-api.toasttab.com)

Provides ToastClient.get_financials_for_employee_by_guid(employee_guid, 'YYYY-MM-DD')
which returns a dict like: {'cashTips': float, 'nonCashTips': float, 'gratuity': float}

This mirrors the aggregation used in the tkinter app's ToastAPI:
- declaredCashTips -> cashTips
- nonCashTips -> nonCashTips
- cashGratuityServiceCharges + nonCashGratuityServiceCharges -> gratuity
"""
from __future__ import annotations
import os
import requests
from typing import Dict, List, Any

class ToastClientError(Exception):
    pass

class ToastClient:
    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        restaurant_guid: str | None = None,
        api_host: str | None = None,
    ):
        self.client_id = client_id or os.getenv("TOAST_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("TOAST_CLIENT_SECRET")
        self.restaurant_guid = restaurant_guid or os.getenv("TOAST_RESTAURANT_GUID")
        self.api_host = api_host or os.getenv("TOAST_API_HOST", "https://ws-api.toasttab.com")
        if not (self.client_id and self.client_secret and self.restaurant_guid):
            raise ToastClientError("Missing TOAST_* environment variables (TOAST_CLIENT_ID, TOAST_CLIENT_SECRET, TOAST_RESTAURANT_GUID)")

    def _get_access_token(self) -> str:
        url = f"{self.api_host}/authentication/v1/authentication/login"
        payload = {
            "clientId": self.client_id,
            "clientSecret": self.client_secret,
            "userAccessType": "TOAST_MACHINE_CLIENT",
        }
        headers = {"Content-Type": "application/json"}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            token = data.get("accessToken") or (data.get("token") or {}).get("accessToken")
            if not token:
                raise ToastClientError("Toast auth did not return accessToken")
            return token
        except requests.RequestException as e:
            raise ToastClientError(f"Toast auth error: {e}")

    def _get(self, token: str, path: str) -> Dict:
        url = f"{self.api_host}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Toast-Restaurant-External-ID": self.restaurant_guid,
            "Accept": "application/json",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            raise ToastClientError(f"Toast GET {path} error: {e}")

    @staticmethod
    def _yyyymmdd(date_yyyy_mm_dd: str) -> str:
        # naive simple transform, assume validated input
        return date_yyyy_mm_dd.replace("-", "")

    def get_financials_for_employee_by_guid(self, employee_guid: str, date_str: str) -> Dict[str, float]:
        if not employee_guid:
            raise ToastClientError("employee_guid is required")
        if not date_str or len(date_str) != 10:
            raise ToastClientError("date must be YYYY-MM-DD")
        token = self._get_access_token()
        business_date = self._yyyymmdd(date_str)
        # Toast endpoint used by tkinter logic: timeEntries by business date
        path = f"/labor/v1/timeEntries?businessDate={business_date}"
        data = self._get(token, path)
        # Aggregate entries for employee_guid
        cash_tips = 0.0
        non_cash_tips = 0.0
        gratuity = 0.0
        matched = False
        for entry in data or []:
            try:
                emp = entry.get("employee", {}) or {}
                if emp.get("guid") != employee_guid:
                    continue
                matched = True
                cash_tips += float(entry.get("declaredCashTips") or 0.0)
                non_cash_tips += float(entry.get("nonCashTips") or 0.0)
                gratuity += float(entry.get("cashGratuityServiceCharges") or 0.0)
                gratuity += float(entry.get("nonCashGratuityServiceCharges") or 0.0)
            except Exception:
                # skip malformed rows
                continue
        result = {"cashTips": round(cash_tips, 2), "nonCashTips": round(non_cash_tips, 2), "gratuity": round(gratuity, 2)}
        if not matched:
            result["warning"] = "No time entries matched this employee/date"
        return result

    def get_sales_categories(self) -> Dict[str, str]:
        """Fetch Sales Categories and return a {guid: name} mapping.

        Uses the Toast Configuration API operation salesCategoriesGet:
        GET /configuration/v1/salesCategories
        """
        token = self._get_access_token()
        # Path derived from Toast OpenAPI docs
        path = "/configuration/v1/salesCategories"
        data: Any = self._get(token, path)
        mapping: Dict[str, str] = {}
        try:
            # API may return a list or an object with 'elements'
            rows: List[dict] = []
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                # common shapes: {"elements": [...]} or {"salesCategories": [...]}
                if isinstance(data.get("elements"), list):
                    rows = data.get("elements") or []
                elif isinstance(data.get("salesCategories"), list):
                    rows = data.get("salesCategories") or []
                else:
                    # try flatten any lists inside
                    for v in data.values():
                        if isinstance(v, list):
                            rows = v
                            break
            for r in rows:
                try:
                    g = (r.get("guid") or r.get("id") or r.get("v2Guid") or "").strip()
                    n = (r.get("name") or r.get("label") or r.get("displayName") or "").strip()
                    if g and n:
                        mapping[g] = n
                except Exception:
                    continue
        except Exception:
            mapping = {}
        return mapping
