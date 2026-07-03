#!/usr/bin/env python3
"""
Get Net Sales per server for a selected business date from Toast API.
Correctly identifies eligible checks by payment's server GUID.
Uses official Toast logic: sum check['amount'] (Net Sales) for each check with a payment by the selected employee.
"""

import os
import requests
from datetime import datetime
import json

# --- Credentials from environment / .env (no hardcoded secrets) ---
def _load_env(path):
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

_load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

CLIENT_ID = os.environ["TOAST_CLIENT_ID"]
CLIENT_SECRET = os.environ["TOAST_CLIENT_SECRET"]
RESTAURANT_GUID = os.environ["TOAST_RESTAURANT_GUID"]
API_HOST = os.getenv("TOAST_API_HOST", "https://ws-api.toasttab.com")

def get_access_token():
    print("--> Getting access token...")
    auth_url = f"{API_HOST}/authentication/v1/authentication/login"
    payload = {
        "clientId": CLIENT_ID,
        "clientSecret": CLIENT_SECRET,
        "userAccessType": "TOAST_MACHINE_CLIENT"
    }
    headers = {"Content-Type": "application/json"}
    response = requests.post(auth_url, json=payload, headers=headers)
    response.raise_for_status()
    data = response.json()
    token = data.get("accessToken") or data.get("token", {}).get("accessToken")
    if token:
        print("--> Success: Access token obtained.\n")
        return token
    else:
        print("--> ERROR: Authentication did not return a valid token.")
        return None

def get_api_data(token, endpoint):
    url = f"{API_HOST}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Toast-Restaurant-External-ID": RESTAURANT_GUID,
        "Accept": "application/json"
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def get_orders_by_business_date(token, business_date):
    print(f"---> Fetching orders for business date {business_date}...")
    endpoint = f"/orders/v2/ordersBulk?businessDate={business_date}"
    url = f"{API_HOST}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Toast-Restaurant-External-ID": RESTAURANT_GUID,
        "Accept": "application/json"
    }
    response = requests.get(url, headers=headers, timeout=120)
    response.raise_for_status()
    orders = response.json()
    print(f"---> Retrieved {len(orders)} orders.")
    # Print a sample order for debugging field names/structure
    if orders:
        print("---> Sample order structure:\n", json.dumps(orders[0], indent=2)[:2000], "\n---(truncated)---")
    return orders

def is_voided_or_deleted(obj):
    return (
        obj.get("voided")
        or obj.get("isVoided")
        or obj.get("voidedAt")
        or obj.get("deleted")
        or obj.get("isDeleted")
        or obj.get("deletedAt")
    )

def main():
    token = get_access_token()
    if not token:
        return

    # Get employees metadata
    employees = get_api_data(token, "/labor/v1/employees")
    if not employees:
        print("ERROR: No employees found.")
        return

    employee_map = {emp['guid']: f"{emp.get('firstName','')} {emp.get('lastName','')}".strip() for emp in employees}
    print("Select an employee:")
    indexed_employees = list(employee_map.items())
    for i, (guid, name) in enumerate(indexed_employees):
        print(f"  {i + 1}: {name}")
    try:
        choice = int(input("\nEnter the employee's number: ")) - 1
        selected_guid, selected_name = indexed_employees[choice]
    except (ValueError, IndexError):
        print("Invalid input.")
        return
    print(f"Selected employee: {selected_name}")

    date_input = input("Enter the business date to query (YYYY-MM-DD): ")
    try:
        business_date_formatted = datetime.strptime(date_input, '%Y-%m-%d').strftime('%Y%m%d')
    except ValueError:
        print("Invalid date format.")
        return

    all_orders = get_orders_by_business_date(token, business_date_formatted)
    if all_orders is None:
        print("Could not fetch orders.")
        return

    # ---- Net Sales Calculation (by payment's server) ----
    total_net_sales = 0.0
    num_checks = 0

    for order in all_orders:
        if is_voided_or_deleted(order):
            continue
        for check in order.get("checks", []):
            if is_voided_or_deleted(check):
                continue
            # NEW LOGIC: Search every payment for this check for a match to the employee's GUID
            found_employee = False
            for payment in check.get("payments", []):
                payment_server = payment.get("server", {})
                payment_server_guid = payment_server.get("guid")
                if payment_server_guid == selected_guid:
                    found_employee = True
                    break  # Only count once per check per employee!
            if found_employee:
                net_sales = check.get("amount", 0.0) or 0.0
                print(f"DEBUG: Check {check.get('guid')} amount={net_sales} (found payment by {selected_name})")
                total_net_sales += net_sales
                num_checks += 1

    print("\n===================================================")
    print(f"Net Sales Results for {selected_name} on {date_input}")
    print("===================================================")
    print(f"  Total Net Sales: ${total_net_sales:.2f}")
    print(f"  Total number of paid checks: {num_checks}")

    if num_checks == 0:
        print("NOTE: No non-voided checks found for this employee and day.")
    print("\n===================================================")

if __name__ == "__main__":
    main()

