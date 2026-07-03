#!/usr/bin/env python3
"""
Simple Flask API for Toasty tips and payouts management.
Uses webapp.db - separate from the old tip_distribution.db.
"""

import sqlite3
import json
import csv
import uuid
import os
import time
import hashlib
import requests
import atexit
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Dict, Set, Any
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)  # Enable CORS for all routes

# Enable ProxyFix to handle X-Forwarded headers from Nginx reverse proxy
# This allows the app to work correctly when served under a subpath like /webapp/
app.wsgi_app = ProxyFix(app.wsgi_app, x_prefix=1)

def load_env_file(env_path: Path):
    """Load environment variables from a .env file."""
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    if key not in os.environ:
                        os.environ[key] = value

# Load environment variables from .env files if they exist
# Check both webapp directory and parent directory
load_env_file(Path(__file__).parent / ".env")
load_env_file(Path(__file__).parent.parent / ".env")

# Database path (new separate database for webapp)
DB_PATH = Path(__file__).parent / "webapp.db"

# Data paths
REPORTS_DIR = Path("/home/ubuntu/new_toasty/toasty/data/reports")
JSON_DIR = Path("/home/ubuntu/jaq/loadjson")
RAW_DIR = Path("/home/ubuntu/new_toasty/toasty/data/raw")
RAW_ORDERS_DIR = RAW_DIR / "orders"

# Bucket/Location mapping from job titles
def job_title_to_bucket_id(title: Optional[str]) -> Optional[str]:
    """Map job title to bucket ID (location).
    
    Based on the old application's _job_title_to_bucket_id function.
    """
    t = (title or "").strip().lower()
    if not t:
        return None
    if "am sunset server" in t:
        return "am_bar"
    if "pm sunset server" in t:
        return "sunset"
    if "ww server" in t:
        return "westwing"
    if "ew server" in t:
        return "eastwing"
    # Also handle bar jobs
    if "am bar" in t:
        return "am_bar"
    if "pm bar" in t or "sunset bar" in t or "low bar" in t:
        return "sunset"
    if "ww bar" in t:
        return "westwing"
    if "ew bar" in t or "eastwing bar" in t:
        return "eastwing"
    return None

def bucket_id_to_display(bucket_id: Optional[str]) -> str:
    """Convert bucket ID to human-readable name."""
    mapping = {
        "am_bar": "AM Bar",
        "sunset": "Sunset Bar", 
        "westwing": "West Wing",
        "eastwing": "East Wing"
    }
    return mapping.get(bucket_id, bucket_id or "Unknown")


def bucket_id_to_server_job_title(bucket_id: Optional[str]) -> str:
    """Map bucket ID to a canonical server job title."""
    mapping = {
        "am_bar": "AM Sunset Server",
        "sunset": "PM Sunset Server",
        "westwing": "WW Server",
        "eastwing": "EW Server",
    }
    return mapping.get(bucket_id or "", "Server")

def get_employee_guid_for_worker(worker_name: str) -> Optional[str]:
    """Get employee GUID from employees.json by matching first/last name."""
    emp_file = JSON_DIR / "labor_v1_employees.json"
    if not emp_file.exists():
        return None
    
    try:
        with open(emp_file, 'r') as f:
            employees = json.load(f)
        
        target = worker_name.strip().lower()
        target_parts = target.split()
        
        for emp in employees:
            first = (emp.get("firstName") or "").strip()
            last = (emp.get("lastName") or "").strip()
            chosen = (emp.get("chosenName") or "").strip()
            
            # Try full name match
            full = " ".join(f"{first} {last}".split())
            if full.lower() == target or chosen.lower() == target:
                return emp.get("guid") or emp.get("v2EmployeeGuid")
            
            # Try partial match (first name or last name)
            if len(target_parts) == 1:
                if first.lower() == target or last.lower() == target:
                    return emp.get("guid") or emp.get("v2EmployeeGuid")
        
        return None
    except Exception as e:
        print(f"Error getting employee GUID: {e}")
        return None

def get_employee_aliases_for_worker(worker_name: str) -> set[str]:
    """Return all known employee identifier aliases for a worker.

    Includes guid/id/v2EmployeeGuid when present.
    """
    aliases: set[str] = set()
    emp_file = JSON_DIR / "labor_v1_employees.json"
    if not emp_file.exists():
        return aliases

    try:
        with open(emp_file, 'r') as f:
            employees = json.load(f)

        target = worker_name.strip().lower()
        target_parts = target.split()

        for emp in employees:
            first = (emp.get("firstName") or "").strip()
            last = (emp.get("lastName") or "").strip()
            chosen = (emp.get("chosenName") or "").strip()
            full = " ".join(f"{first} {last}".split())

            matched = False
            if full.lower() == target or chosen.lower() == target:
                matched = True
            elif len(target_parts) == 1 and (first.lower() == target or last.lower() == target):
                matched = True

            if matched:
                for key in ("guid", "id", "v2EmployeeGuid"):
                    value = (emp.get(key) or "").strip()
                    if value:
                        aliases.add(value)
                break
    except Exception as e:
        print(f"Error getting employee aliases: {e}")

    return aliases

def get_employee_name_by_guid(emp_guid: str) -> Optional[str]:
    """Get employee name from JAQ by GUID."""
    try:
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        
        response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_employees.json',
            'limit': '5000'
        }, timeout=30)
        
        if response.status_code == 200:
            for item in response.json():
                try:
                    emp = json.loads(item.get('json_data', '{}'))
                    if emp.get('guid') == emp_guid or emp.get('v2EmployeeGuid') == emp_guid:
                        first = (emp.get('firstName') or '').strip()
                        last = (emp.get('lastName') or '').strip()
                        chosen = (emp.get('chosenName') or '').strip()
                        full = (first + (' ' + last if last else '')).strip()
                        return full or chosen
                except:
                    continue
        return None
    except Exception:
        return None


def build_worker_name_alias_map() -> Dict[str, str]:
    """Build alias->legal-name mapping from employees data.

    Preferred behavior:
    - Use legal name ("First Last") when available.
    - Fall back to chosen/preferred name only when legal name is missing.
    """
    alias_map: Dict[str, str] = {}
    emp_file = JSON_DIR / "labor_v1_employees.json"
    if not emp_file.exists():
        return alias_map

    try:
        with open(emp_file, "r") as f:
            employees = json.load(f)

        # Track abbreviation collisions for safe mapping (e.g., "Justin W").
        abbr_candidates: Dict[str, Set[str]] = {}

        for emp in employees:
            first = (emp.get("firstName") or "").strip()
            last = (emp.get("lastName") or "").strip()
            chosen = (emp.get("chosenName") or "").strip()

            legal_name = " ".join(f"{first} {last}".split())
            canonical = legal_name or chosen
            if not canonical:
                continue

            aliases = {canonical}
            if legal_name:
                aliases.add(legal_name)
            if chosen:
                aliases.add(chosen)

            for alias in aliases:
                key = alias.strip().lower()
                if not key:
                    continue
                alias_map.setdefault(key, canonical)

            # Add abbreviation candidate "First L" for later if unique.
            if first and last:
                abbr_key = f"{first} {last[0]}".strip().lower()
                if abbr_key:
                    abbr_candidates.setdefault(abbr_key, set()).add(canonical)

        # Promote only unique abbreviations to avoid bad merges.
        for abbr_key, canonicals in abbr_candidates.items():
            if len(canonicals) == 1:
                canonical = next(iter(canonicals))
                alias_map.setdefault(abbr_key, canonical)
                alias_map.setdefault(f"{abbr_key}.", canonical)
    except Exception as e:
        print(f"Error building worker alias map: {e}")

    return alias_map


def query_jaq2(dsl_query: Dict) -> Dict:
    """Query JAQ2 server using its QueryDSL format.
    
    JAQ2 uses a different API than the legacy JAQ server:
    - Endpoint: POST /query/dsl
    - Request body: JSON string containing the QueryDSL
    - Response: {success, columns, rows, total_count}
    
    Example dsl_query:
    {
        "from": {"source_file": "employees.json", "alias": "e"},
        "select": [{"expr": "e.firstName", "alias": "firstName"}],
        "limit": 10
    }
    """
    try:
        jaq2_url = os.environ.get('JAQ2_SERVER_URL', 'http://localhost:3001')
        
        response = requests.post(
            f"{jaq2_url}/query/dsl",
            json={"query": json.dumps(dsl_query)},
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"success": False, "error": f"HTTP {response.status_code}", "rows": [], "columns": []}
    except Exception as e:
        return {"success": False, "error": str(e), "rows": [], "columns": []}


def query_jaq2_employees(limit: int = 1000) -> List[Dict]:
    """Query employees from JAQ2 using QueryDSL format."""
    result = query_jaq2({
        "from": {"source_file": "labor_v1_employees.json", "alias": "e"},
        "select": [
            {"expr": "e.guid", "alias": "guid"},
            {"expr": "e.firstName", "alias": "firstName"},
            {"expr": "e.lastName", "alias": "lastName"},
            {"expr": "e.chosenName", "alias": "chosenName"}
        ],
        "limit": limit
    })
    
    employees = []
    if result.get("success"):
        columns = result.get("columns", [])
        for row in result.get("rows", []):
            emp = dict(zip(columns, row))
            employees.append(emp)
    return employees

def get_worker_shifts_for_date(worker_name: str, date_str: str) -> List[Dict]:
    """Get worker's shifts for a specific date from JAQ datalake."""
    shifts = []
    
    # Convert date format from YYYY-MM-DD to Toast format YYYYMMDD
    toast_date = date_str.replace('-', '')
    
    try:
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        
        # First, get employee GUID for the worker name
        emp_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_employees.json',
            'limit': '1000'
        })
        
        emp_guid = None
        if emp_response.status_code == 200:
            for item in emp_response.json():
                try:
                    emp = json.loads(item.get('json_data', '{}'))
                    first = emp.get('firstName', '')
                    last = emp.get('lastName', '')
                    name = " ".join(f"{first} {last}".split())
                    if name == worker_name:
                        emp_guid = emp.get('guid') or emp.get('v2EmployeeGuid')
                        break
                except:
                    continue
        
        if not emp_guid:
            print(f"Could not find employee GUID for {worker_name}")
            return shifts
        
        # Get jobs to map job GUIDs to titles
        job_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_jobs.json',
            'limit': '1000'
        })
        
        jobs = {}
        if job_response.status_code == 200:
            for item in job_response.json():
                try:
                    job = json.loads(item.get('json_data', '{}'))
                    guid = job.get('guid')
                    title = job.get('title', '')
                    if guid and title:
                        jobs[guid] = title
                except:
                    continue
        
        # Query time entries for the specific date
        time_file = f"labor_v1_timeEntries_{toast_date}.json"
        time_response = requests.get(f"{jaq_url}/query", params={
            'source_file': time_file,
            'limit': '10000'
        })
        
        time_data = time_response.json() if time_response.status_code == 200 else []
        
        if time_data:
            # Use time entries data
            for item in time_data:
                try:
                    entry = json.loads(item.get('json_data', '{}'))
                    
                    # Check if this entry belongs to our employee and date
                    emp_ref = entry.get('employeeReference', {})
                    entry_emp_guid = emp_ref.get('guid')
                    
                    if entry_emp_guid != emp_guid:
                        continue
                    
                    if entry.get('businessDate') != toast_date:
                        continue
                    
                    # Get job title
                    job_ref = entry.get('jobReference', {})
                    job_guid = job_ref.get('guid')
                    job_title = jobs.get(job_guid, 'Unknown')
                    
                    # Parse times
                    in_date = entry.get('inDate', '')
                    out_date = entry.get('outDate', '')
                    hours = float(entry.get('regularHours', 0) or 0)
                    
                    shifts.append({
                        "job_title": job_title,
                        "start_time": in_date,
                        "end_time": out_date,
                        "hours": hours
                    })
                    
                except Exception as e:
                    continue
        else:
            # Fallback: Use orders data to find shift info
            print(f"Time entries not found for {date_str}, using orders data as fallback")
            orders_file = f"orders_full_{toast_date}.json"
            orders_response = requests.get(f"{jaq_url}/query", params={
                'source_file': orders_file,
                'limit': '100000'
            })
            
            if orders_response.status_code == 200:
                first_order_time = None
                last_order_time = None
                total_tips = 0
                order_count = 0
                
                for item in orders_response.json():
                    try:
                        order = json.loads(item.get('json_data', '{}'))
                        
                        # Get order timestamp
                        opened_date = order.get('openedDate', '')
                        if opened_date:
                            if not first_order_time or opened_date < first_order_time:
                                first_order_time = opened_date
                            if not last_order_time or opened_date > last_order_time:
                                last_order_time = opened_date
                        
                        # Check each check for this employee
                        for check in order.get('checks', []):
                            for payment in check.get('payments', []):
                                server = payment.get('server', {})
                                if server.get('guid') == emp_guid:
                                    total_tips += float(payment.get('tipAmount') or 0)
                                    order_count += 1
                                    
                    except Exception as e:
                        continue
                
                # If employee had activity, create a synthetic shift
                if order_count > 0:
                    # Calculate estimated hours from first and last order
                    try:
                        first_dt = datetime.fromisoformat(first_order_time.replace('Z', '+00:00'))
                        last_dt = datetime.fromisoformat(last_order_time.replace('Z', '+00:00'))
                        hours_worked = (last_dt - first_dt).total_seconds() / 3600
                        hours_worked = max(round(hours_worked, 2), 0.5)
                    except:
                        hours_worked = 0
                    
                    # Try to infer location from worker name
                    bucket_id = job_title_to_bucket_id(worker_name)
                    location_display = bucket_id_to_display(bucket_id) if bucket_id else "Unknown"
                    
                    shifts.append({
                        "job_title": "Server (from orders)",
                        "start_time": first_order_time or "",
                        "end_time": last_order_time or "",
                        "hours": hours_worked,
                        "location": location_display,
                        "orders_count": order_count,
                        "total_tips": round(total_tips, 2)
                    })
                    
    except Exception as e:
        print(f"Error fetching shifts from JAQ: {e}")
        import traceback
        traceback.print_exc()
    
    # Auto-reconcile manual location correction:
    # if Toast data now includes the override bucket, clear stale override and use Toast.
    override = get_server_shift_override(worker_name, date_str)
    if override:
        raw_buckets = set()
        for shift in shifts:
            job_title = (shift.get("job_title") or "").strip()
            if "cleaning" in job_title.lower():
                continue
            bid = job_title_to_bucket_id(job_title)
            if bid:
                raw_buckets.add(bid)
        override_bucket = (override.get("bucket") or "").strip()
        if override_bucket and override_bucket in raw_buckets:
            delete_server_shift_override(worker_name, date_str)
            return shifts

    # Apply manual location correction (clocked-into-wrong-location cases).
    shifts = apply_server_shift_override(worker_name, date_str, shifts)
    return shifts


def get_server_bucket_shift_windows(worker_name: str, date_str: str, bucket: str) -> List[tuple[datetime, datetime]]:
    """Build bucket shift windows for a server, reassigning Cleaning shifts by proximity.

    This mirrors the legacy app behavior:
    - include the worker's actual server shifts for the selected bucket
    - reassign any "Cleaning - Server" shift to the nearest real server shift bucket
    - if there are only cleaning shifts and no server shifts, assign cleaning to AM
    """
    all_shifts = get_worker_shifts_for_date(worker_name, date_str)
    if not all_shifts or not bucket:
        return []

    windows: List[tuple[datetime, datetime]] = []
    server_shifts: List[tuple[str, datetime, datetime]] = []
    cleaning_shifts: List[tuple[datetime, datetime]] = []

    for shift in all_shifts:
        try:
            job_title = (shift.get('job_title') or '').strip()
            in_time_str = shift.get('in_time') or shift.get('start_time', '')
            out_time_str = shift.get('out_time') or shift.get('end_time', '')
            if not in_time_str:
                continue
            start = parse_toast_datetime(in_time_str)
            if not start:
                continue
            # Open shifts may not have outDate yet; use "now" so completed checks
            # during an active shift are included before clock-out.
            if out_time_str:
                end = parse_toast_datetime(out_time_str)
                if not end:
                    continue
            else:
                end = datetime.now(timezone.utc)
            if end <= start:
                continue

            bid = job_title_to_bucket_id(job_title)
            if bid:
                server_shifts.append((bid, start, end))
                # Use normalized bucket mapping directly; text-pattern matching can miss
                # valid titles and cause bucket views to show zero while unbucketed shows data.
                if bid == bucket:
                    windows.append((start, end))
            elif (job_title or '').strip().lower() == 'cleaning - server':
                cleaning_shifts.append((start, end))
        except Exception:
            continue

    def midpoint(st: datetime, en: datetime) -> float:
        return (st.timestamp() + en.timestamp()) / 2.0

    if cleaning_shifts:
        server_mids = [(bid, midpoint(st, en), st) for bid, st, en in server_shifts]
        for stc, enc in cleaning_shifts:
            assigned_bucket = None
            if server_mids:
                mid_c = midpoint(stc, enc)
                best = min(server_mids, key=lambda x: (abs(x[1] - mid_c), x[2]))
                assigned_bucket = best[0]
            else:
                assigned_bucket = 'am_bar'
            if assigned_bucket == bucket:
                windows.append((stc, enc))

    windows.sort(key=lambda w: w[0])
    return windows


def get_worker_shift_ranges_with_cleaning(worker_name: str, date_str: str) -> List[Dict[str, Any]]:
    """Return worker shift ranges with Cleaning - Server reassigned to nearest bucket."""
    shifts = get_worker_shifts_for_date(worker_name, date_str)
    if not shifts:
        return []

    ranges: List[Dict[str, Any]] = []
    server_ranges: List[Dict[str, Any]] = []
    cleaning_ranges: List[Dict[str, Any]] = []

    for shift in shifts:
        start = parse_toast_datetime(shift.get('start_time', ''))
        end = parse_toast_datetime(shift.get('end_time', ''))
        if not start:
            continue
        if not end:
            # Open shift: use now so in-progress shifts still contribute.
            end = datetime.now(timezone.utc)
        if end <= start:
            continue

        job_title = shift.get('job_title', '')
        bucket = job_title_to_bucket_id(job_title)
        row = {'start': start, 'end': end, 'bucket': bucket, 'job_title': job_title}

        if bucket:
            server_ranges.append(row)
        elif (job_title or '').strip().lower() == 'cleaning - server':
            cleaning_ranges.append(row)

    ranges.extend(server_ranges)

    def midpoint(st: datetime, en: datetime) -> float:
        return (st.timestamp() + en.timestamp()) / 2.0

    for row in cleaning_ranges:
        assigned_bucket = None
        if server_ranges:
            mid_c = midpoint(row['start'], row['end'])
            best = min(
                server_ranges,
                key=lambda x: (abs(midpoint(x['start'], x['end']) - mid_c), x['start'])
            )
            assigned_bucket = best['bucket']
        else:
            assigned_bucket = 'am_bar'
        ranges.append({
            'start': row['start'],
            'end': row['end'],
            'bucket': assigned_bucket,
            'job_title': row['job_title'],
        })

    ranges.sort(key=lambda r: r['start'])
    return ranges


def _assign_timestamp_to_bucket(ts: Optional[datetime], shift_ranges: List[Dict[str, Any]]) -> Optional[str]:
    """Assign a timestamp to a worker bucket using closest-shift fallback.

    Rules:
    - If timestamp falls inside a shift window, use that shift's bucket.
    - Otherwise, assign to the closest shift window by time distance.
    """
    if not ts or not shift_ranges:
        return None

    candidates = [r for r in shift_ranges if r.get('bucket')]
    if not candidates:
        return None

    # In-window match first.
    for r in candidates:
        if r['start'] <= ts <= r['end']:
            return r['bucket']

    # Outside all windows: assign to nearest shift boundary.
    def distance_seconds(r: Dict[str, Any]) -> tuple[float, datetime]:
        st = r['start']
        en = r['end']
        if ts < st:
            d = (st - ts).total_seconds()
        elif ts > en:
            d = (ts - en).total_seconds()
        else:
            d = 0.0
        return (d, st)

    best = min(candidates, key=distance_seconds)
    return best.get('bucket')


def get_order_assigned_bucket(order: Dict[str, Any], shift_ranges: List[Dict[str, Any]]) -> Optional[str]:
    """Assign an order to a bucket based on order opening time and closest shift."""
    order_time = parse_toast_datetime(
        order.get('openedDate') or order.get('createdDate') or order.get('paidDate') or order.get('closedDate')
    )
    assigned = _assign_timestamp_to_bucket(order_time, shift_ranges)
    if assigned:
        return assigned

    # Last-resort fallback to first available bucket for the worker/date.
    for r in shift_ranges:
        if r.get('bucket'):
            return r['bucket']
    return None


def get_check_assigned_bucket(check: Dict[str, Any], shift_ranges: List[Dict[str, Any]]) -> Optional[str]:
    """Assign a check to a bucket based on finalized check/payment time.

    For transferred checks, Toast attribution follows the check owner at transfer/finalization;
    using payment/check close timing best matches that behavior.
    """
    ts: Optional[datetime] = None

    # Prefer latest payment paidDate when present.
    payment_times: List[datetime] = []
    for payment in check.get('payments', []) or []:
        if not isinstance(payment, dict):
            continue
        pdt = parse_toast_datetime(payment.get('paidDate') or payment.get('paidTime') or '')
        if pdt:
            payment_times.append(pdt)
    if payment_times:
        ts = max(payment_times)

    # Fallback to check-level timestamps.
    if not ts:
        ts = parse_toast_datetime(
            check.get('paidDate') or check.get('closedDate') or check.get('openedDate')
        )

    assigned = _assign_timestamp_to_bucket(ts, shift_ranges)
    if assigned:
        return assigned

    # Last-resort fallback to first available bucket for the worker/date.
    for r in shift_ranges:
        if r.get('bucket'):
            return r['bucket']
    return None


def get_declared_cash_tips_from_time_entries(worker_name: str, date_str: str, bucket: str = None) -> float:
    """Get declared cash tips from Toast time entries for a specific worker/date.
    
    This looks at the 'declaredCashTips' field in time entries, which is where
    employees declare their cash tips in Toast.
    
    Args:
        worker_name: The worker's name
        date_str: Date in YYYY-MM-DD format
        bucket: Optional bucket to filter by (e.g., 'am_bar', 'westwing')
    """
    total_cash_tips = 0.0
    
    # Convert date format from YYYY-MM-DD to Toast format YYYYMMDD
    toast_date = date_str.replace('-', '')
    
    try:
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        
        # First, get employee GUID for the worker name
        emp_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_employees.json',
            'limit': '1000'
        })
        
        emp_guid = None
        if emp_response.status_code == 200:
            for item in emp_response.json():
                try:
                    emp = json.loads(item.get('json_data', '{}'))
                    first = emp.get('firstName', '')
                    last = emp.get('lastName', '')
                    name = " ".join(f"{first} {last}".split())
                    if name == worker_name:
                        emp_guid = emp.get('guid') or emp.get('v2EmployeeGuid')
                        break
                except:
                    continue
        
        if not emp_guid:
            print(f"Could not find employee GUID for {worker_name}")
            return total_cash_tips
        
        # Get jobs to map job GUIDs to titles (for bucket filtering)
        job_map = {}
        if bucket:
            job_response = requests.get(f"{jaq_url}/query", params={
                'source_file': 'labor_v1_jobs.json',
                'limit': '1000'
            })
            if job_response.status_code == 200:
                for item in job_response.json():
                    try:
                        job = json.loads(item.get('json_data', '{}'))
                        guid = job.get('guid')
                        title = job.get('title', '')
                        if guid and title:
                            job_map[guid] = title
                    except:
                        continue
        
        # Query time entries for the specific date
        time_file = f"labor_v1_timeEntries_{toast_date}.json"
        time_response = requests.get(f"{jaq_url}/query", params={
            'source_file': time_file,
            'limit': '10000'
        })
        
        time_data = time_response.json() if time_response.status_code == 200 else []
        
        if time_data:
            for item in time_data:
                try:
                    entry = json.loads(item.get('json_data', '{}'))
                    
                    # Check if this entry belongs to our employee and date
                    emp_ref = entry.get('employeeReference', {})
                    entry_emp_guid = emp_ref.get('guid')
                    
                    if entry_emp_guid != emp_guid:
                        continue
                    
                    if entry.get('businessDate') != toast_date:
                        continue
                    
                    # Filter by bucket if specified
                    if bucket:
                        job_ref = entry.get('jobReference', {})
                        job_guid = job_ref.get('guid')
                        job_title = job_map.get(job_guid, '')
                        entry_bucket = job_title_to_bucket_id(job_title)
                        if entry_bucket != bucket:
                            continue
                    
                    # Get declared cash tips
                    declared_cash = entry.get('declaredCashTips')
                    if declared_cash is not None:
                        try:
                            total_cash_tips += float(declared_cash)
                        except:
                            pass
                    
                except Exception as e:
                    continue
        
        print(f"Found {total_cash_tips} declared cash tips for {worker_name} on {date_str}")
        
    except Exception as e:
        print(f"Error fetching declared cash tips from JAQ: {e}")
    
    return total_cash_tips


def get_gratuity_from_time_entries(worker_name: str, date_str: str, bucket: str = None) -> float:
    """Get gratuity/service charges from Toast time entries for a worker/date.

    Toast exposes this on time entries as:
    - cashGratuityServiceCharges
    - nonCashGratuityServiceCharges
    """
    total_gratuity = 0.0
    toast_date = date_str.replace('-', '')

    try:
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')

        emp_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_employees.json',
            'limit': '1000'
        })

        emp_guid = None
        if emp_response.status_code == 200:
            for item in emp_response.json():
                try:
                    emp = json.loads(item.get('json_data', '{}'))
                    first = emp.get('firstName', '')
                    last = emp.get('lastName', '')
                    name = " ".join(f"{first} {last}".split())
                    if name == worker_name:
                        emp_guid = emp.get('guid') or emp.get('v2EmployeeGuid')
                        break
                except Exception:
                    continue

        if not emp_guid:
            return total_gratuity

        job_map = {}
        if bucket:
            job_response = requests.get(f"{jaq_url}/query", params={
                'source_file': 'labor_v1_jobs.json',
                'limit': '1000'
            })
            if job_response.status_code == 200:
                for item in job_response.json():
                    try:
                        job = json.loads(item.get('json_data', '{}'))
                        guid = job.get('guid')
                        title = job.get('title', '')
                        if guid and title:
                            job_map[guid] = title
                    except Exception:
                        continue

        time_response = requests.get(f"{jaq_url}/query", params={
            'source_file': f'labor_v1_timeEntries_{toast_date}.json',
            'limit': '10000'
        })
        time_data = time_response.json() if time_response.status_code == 200 else []

        for item in time_data:
            try:
                entry = json.loads(item.get('json_data', '{}'))
                if (entry.get('employeeReference') or {}).get('guid') != emp_guid:
                    continue
                if entry.get('businessDate') != toast_date:
                    continue

                if bucket:
                    job_guid = (entry.get('jobReference') or {}).get('guid')
                    job_title = job_map.get(job_guid, '')
                    if job_title_to_bucket_id(job_title) != bucket:
                        continue

                total_gratuity += float(entry.get('cashGratuityServiceCharges') or 0.0)
                total_gratuity += float(entry.get('nonCashGratuityServiceCharges') or 0.0)
            except Exception:
                continue

    except Exception as e:
        print(f"Error fetching gratuity from JAQ: {e}")

    return total_gratuity


def get_non_cash_tips_from_time_entries(worker_name: str, date_str: str, bucket: str = None) -> float:
    """Get non-cash tips from Toast time entries for a worker/date."""
    total_non_cash = 0.0
    toast_date = date_str.replace('-', '')

    try:
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')

        emp_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_employees.json',
            'limit': '1000'
        })

        emp_guid = None
        if emp_response.status_code == 200:
            for item in emp_response.json():
                try:
                    emp = json.loads(item.get('json_data', '{}'))
                    first = emp.get('firstName', '')
                    last = emp.get('lastName', '')
                    name = " ".join(f"{first} {last}".split())
                    if name == worker_name:
                        emp_guid = emp.get('guid') or emp.get('v2EmployeeGuid')
                        break
                except Exception:
                    continue

        if not emp_guid:
            return total_non_cash

        job_map = {}
        if bucket:
            job_response = requests.get(f"{jaq_url}/query", params={
                'source_file': 'labor_v1_jobs.json',
                'limit': '1000'
            })
            if job_response.status_code == 200:
                for item in job_response.json():
                    try:
                        job = json.loads(item.get('json_data', '{}'))
                        guid = job.get('guid')
                        title = job.get('title', '')
                        if guid and title:
                            job_map[guid] = title
                    except Exception:
                        continue

        time_response = requests.get(f"{jaq_url}/query", params={
            'source_file': f'labor_v1_timeEntries_{toast_date}.json',
            'limit': '10000'
        })
        time_data = time_response.json() if time_response.status_code == 200 else []

        for item in time_data:
            try:
                entry = json.loads(item.get('json_data', '{}'))
                if (entry.get('employeeReference') or {}).get('guid') != emp_guid:
                    continue
                if entry.get('businessDate') != toast_date:
                    continue

                if bucket:
                    job_guid = (entry.get('jobReference') or {}).get('guid')
                    job_title = job_map.get(job_guid, '')
                    if job_title_to_bucket_id(job_title) != bucket:
                        continue

                total_non_cash += float(entry.get('nonCashTips') or 0.0)
            except Exception:
                continue

    except Exception as e:
        print(f"Error fetching non-cash tips from JAQ: {e}")

    return total_non_cash


def get_suggested_buckets_for_worker(worker_name: str, date_str: str) -> List[Dict]:
    """Get suggested buckets (locations) where worker worked on a given date."""
    shifts = get_worker_shifts_for_date(worker_name, date_str)
    
    # Extract unique buckets from job titles
    buckets = []
    seen = set()
    
    for shift in shifts:
        job_title = shift.get("job_title", "")
        bucket_id = job_title_to_bucket_id(job_title)
        if bucket_id and bucket_id not in seen:
            seen.add(bucket_id)
            buckets.append({
                "id": bucket_id,
                "name": bucket_id_to_display(bucket_id),
                "job_title": job_title,
                "hours": shift.get("hours", 0)
            })
    
    return buckets

def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_labor_watch_tables():
    """Initialize tables for labor-watch scheduler state and change logs."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS labor_watch_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                summary TEXT,
                snapshot_hash TEXT,
                details_json TEXT
            )
        """)
        conn.commit()
        conn.close()
        print("Labor watch tables initialized")
    except Exception as e:
        print(f"Error initializing labor watch tables: {e}")


def get_app_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT value FROM app_settings WHERE key = ? LIMIT 1", (key,))
        row = cursor.fetchone()
        if not row:
            return default
        return row["value"]
    finally:
        conn.close()


def set_app_setting(key: str, value: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
        """, (key, value))
        conn.commit()
    finally:
        conn.close()


def get_labor_watch_interval_minutes(default_minutes: int = 1) -> int:
    raw = get_app_setting("labor_watch_interval_minutes", str(default_minutes))
    try:
        val = int(raw or default_minutes)
    except Exception:
        val = default_minutes
    return max(1, min(val, 60))


def init_server_shift_override_table():
    """Initialize per-worker/date bucket override table."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS server_shift_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_name TEXT NOT NULL,
                business_date TEXT NOT NULL,
                bucket TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(worker_name, business_date)
            )
        """)
        conn.commit()
        conn.close()
        print("Server shift override table initialized")
    except Exception as e:
        print(f"Error initializing server shift override table: {e}")


def delete_server_shift_override(worker_name: str, date_str: str) -> int:
    """Delete manual shift-bucket override for worker/date."""
    if not worker_name or not date_str:
        return 0
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            DELETE FROM server_shift_overrides
            WHERE worker_name = ? AND business_date = ?
        """, (worker_name, date_str))
        deleted = cursor.rowcount
        conn.commit()
        return deleted
    finally:
        conn.close()


def get_server_shift_override(worker_name: str, date_str: str) -> Optional[Dict[str, Any]]:
    """Fetch manual shift-bucket override for worker/date."""
    if not worker_name or not date_str:
        return None
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT worker_name, business_date, bucket, updated_at
            FROM server_shift_overrides
            WHERE worker_name = ? AND business_date = ?
            LIMIT 1
        """, (worker_name, date_str))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "worker": row["worker_name"],
            "date": row["business_date"],
            "bucket": row["bucket"],
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


def apply_server_shift_override(worker_name: str, date_str: str, shifts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply manual bucket override to shift records for server calculations."""
    override = get_server_shift_override(worker_name, date_str)
    if not override:
        return shifts

    override_bucket = (override.get("bucket") or "").strip()
    if not override_bucket:
        return shifts

    adjusted: List[Dict[str, Any]] = []
    for shift in shifts:
        s = dict(shift)
        job_title = (s.get("job_title") or "").strip()
        if "cleaning" not in job_title.lower():
            s["job_title"] = bucket_id_to_server_job_title(override_bucket)
        s["override_bucket"] = override_bucket
        adjusted.append(s)
    return adjusted


def init_role_corrections_table():
    """Initialize payout role correction override table."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payout_role_corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_name TEXT NOT NULL,
                business_date TEXT NOT NULL,
                bucket TEXT NOT NULL DEFAULT '',
                corrected_role TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(worker_name, business_date, bucket)
            )
        """)
        conn.commit()
        conn.close()
        print("Payout role corrections table initialized")
    except Exception as e:
        print(f"Error initializing payout role corrections table: {e}")


def upsert_server_tip_cache(cursor, worker: str, date: str, bucket: str, values: Dict[str, Any]) -> int:
    """Store one cached server-tip row per worker/date/bucket."""
    cursor.execute("""
        DELETE FROM servers
        WHERE worker_name = ? AND business_date = ? AND bucket = ?
    """, (worker, date, bucket))

    cursor.execute("""
        INSERT INTO servers
        (business_date, worker_name, bucket, cash_tips, credit_tips, gratuity, net_sales,
         bar_tips, busser_tips, expo_tips, runner_tips)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        date,
        worker,
        bucket,
        values.get('cash_tips', 0),
        values.get('credit_tips', 0),
        values.get('gratuity', 0),
        values.get('net_sales', 0),
        values.get('bar_tips', 0),
        values.get('busser_tips', 0),
        values.get('expo_tips', 0),
        values.get('runner_tips', 0)
    ))

    return cursor.lastrowid


def get_worker_check_assignment_map(worker_name: str, date_str: str) -> Dict[str, List[Dict[str, Any]]]:
    """Return split assignments for checks where this worker is involved."""
    assignments: Dict[str, List[Dict[str, Any]]] = {}
    best_rank: Dict[str, Tuple[int, int]] = {}
    worker_key = (worker_name or '').strip()
    if not worker_key or not date_str:
        return assignments

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, worker_name, check_guid, assigned_workers
            FROM check_assignments
            WHERE business_date = ?
            ORDER BY id ASC
        """, (date_str,))

        for row in cursor.fetchall():
            primary_worker = (row['worker_name'] or '').strip()
            raw_workers = json.loads(row['assigned_workers'] or '[]')
            normalized_workers = []
            for aw in raw_workers:
                normalized_workers.append({
                    'worker_name': (aw.get('worker_name') or '').strip(),
                    'split_percentage': aw.get('split_percentage')
                })

            includes_worker = any(aw['worker_name'] == worker_key for aw in normalized_workers)
            if primary_worker != worker_key and not includes_worker:
                continue

            if not normalized_workers:
                normalized_workers = [{'worker_name': primary_worker or worker_key, 'split_percentage': 100.0}]

            rank = 2 if primary_worker == worker_key else 1
            check_guid = row['check_guid']
            row_id = int(row['id'] or 0)
            current_rank = best_rank.get(check_guid)
            if current_rank and (rank, row_id) <= current_rank:
                continue

            best_rank[check_guid] = (rank, row_id)
            assignments[check_guid] = normalized_workers
    finally:
        conn.close()

    return assignments


def get_worker_split_percentage(
    check_guid: str,
    worker_name: str,
    assignment_map: Dict[str, List[Dict[str, Any]]]
) -> float:
    """Return the worker's split percentage for a check."""
    assigned_workers = assignment_map.get(check_guid)
    if not assigned_workers:
        return 100.0

    worker_key = (worker_name or '').strip()
    fallback = 100.0 / len(assigned_workers) if assigned_workers else 100.0
    for aw in assigned_workers:
        if (aw.get('worker_name') or '').strip() == worker_key:
            try:
                return float(aw.get('split_percentage', fallback))
            except Exception:
                return fallback
    return 0.0


def get_connected_split_workers(worker_name: str, date_str: str) -> List[str]:
    """Return all workers connected by split-check relationships for a date.

    Builds an undirected graph from check_assignments:
    - edge between check owner (worker_name column) and each assigned worker.
    Then returns the connected component containing worker_name.
    """
    root = (worker_name or '').strip()
    if not root or not date_str:
        return [root] if root else []

    conn = get_db()
    cursor = conn.cursor()
    adjacency: Dict[str, Set[str]] = {}
    try:
        cursor.execute("""
            SELECT worker_name, assigned_workers
            FROM check_assignments
            WHERE business_date = ?
        """, (date_str,))

        for row in cursor.fetchall():
            owner = (row['worker_name'] or '').strip()
            if not owner:
                continue
            adjacency.setdefault(owner, set())
            try:
                assigned_workers = json.loads(row['assigned_workers'] or '[]')
            except Exception:
                assigned_workers = []
            if not isinstance(assigned_workers, list):
                continue
            for aw in assigned_workers:
                if not isinstance(aw, dict):
                    continue
                aw_name = (aw.get('worker_name') or '').strip()
                if not aw_name:
                    continue
                adjacency.setdefault(aw_name, set())
                adjacency[owner].add(aw_name)
                adjacency[aw_name].add(owner)
    finally:
        conn.close()

    # BFS connected component
    visited: Set[str] = set()
    stack = [root]
    while stack:
        cur = stack.pop()
        if cur in visited or not cur:
            continue
        visited.add(cur)
        for nxt in adjacency.get(cur, set()):
            if nxt not in visited:
                stack.append(nxt)

    if root not in visited:
        visited.add(root)
    return sorted(visited)


def get_split_assigned_main_figures(worker_name: str, date_str: str) -> Dict[str, float]:
    """Calculate main-figure values for split-assigned checks that were actually pushed."""
    worker_key = (worker_name or '').strip()
    if not worker_key or not date_str:
        return {
            'cash_tips': 0.0,
            'credit_tips': 0.0,
            'gratuity': 0.0,
            'net_sales': 0.0,
        }

    conn = get_db()
    cursor = conn.cursor()
    secondary_check_guids = set()
    try:
        cursor.execute("""
            SELECT DISTINCT check_guid
            FROM split_payouts
            WHERE business_date = ?
              AND worker_name = ?
        """, (date_str, worker_key))
        secondary_check_guids = {row['check_guid'] for row in cursor.fetchall() if row['check_guid']}
    finally:
        conn.close()

    if not secondary_check_guids:
        return {
            'cash_tips': 0.0,
            'credit_tips': 0.0,
            'gratuity': 0.0,
            'net_sales': 0.0,
        }

    assignment_map = get_worker_check_assignment_map(worker_key, date_str)
    if not assignment_map:
        return {
            'cash_tips': 0.0,
            'credit_tips': 0.0,
            'gratuity': 0.0,
            'net_sales': 0.0,
        }

    orders = load_orders_for_date(date_str) or []
    figures = {
        'cash_tips': 0.0,
        'credit_tips': 0.0,
        'gratuity': 0.0,
        'net_sales': 0.0,
    }

    for order in orders:
        for check in order.get('checks', []) or []:
            if check.get('voided') or check.get('deleted'):
                continue
            check_guid = check.get('guid', '')
            if check_guid not in secondary_check_guids:
                continue

            split_pct = get_worker_split_percentage(check_guid, worker_key, assignment_map)
            share = split_pct / 100.0
            if share <= 0:
                continue

            check_cash_tips = 0.0
            check_credit_tips = 0.0
            for payment in check.get('payments', []) or []:
                tip = float(payment.get('tipAmount', 0) or 0)
                payment_type = (payment.get('type') or '').upper()
                if payment_type == 'CASH':
                    check_cash_tips += tip
                else:
                    check_credit_tips += tip

            gratuity_total = 0.0
            for svc_charge in check.get('appliedServiceCharges', []) or []:
                if svc_charge.get('voided') or svc_charge.get('deleted'):
                    continue
                if svc_charge.get('gratuity', False):
                    gratuity_total += float(svc_charge.get('chargeAmount') or 0)

            check_amount = float(check.get('amount') or check.get('total') or check.get('net') or check.get('subtotal') or 0.0)
            gift_card_total = 0.0
            for selection in check.get('selections', []) or []:
                item_name = (selection.get('displayName', '') or selection.get('itemName', '')).lower()
                if 'gift card' in item_name or 'giftcard' in item_name:
                    gift_card_total += float(selection.get('price', 0) or 0)

            figures['cash_tips'] += check_cash_tips * share
            figures['credit_tips'] += check_credit_tips * share
            figures['gratuity'] += gratuity_total * share
            figures['net_sales'] += max(0.0, check_amount - gift_card_total) * share

    return figures


def init_bartender_tip_override_table():
    """Initialize aggregate bartender override cache."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bartender_tip_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_date TEXT NOT NULL,
                bucket TEXT NOT NULL,
                cash_tips REAL DEFAULT 0,
                credit_tips REAL DEFAULT 0,
                net_sales REAL DEFAULT 0,
                busser_tips REAL DEFAULT 0,
                expo_tips REAL DEFAULT 0,
                runner_tips REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(business_date, bucket)
            )
        """)
        conn.commit()
        conn.close()
        print("Bartender tip override table initialized")
    except Exception as e:
        print(f"Error initializing bartender tip override table: {e}")


def upsert_bartender_tip_override(cursor, date_str: str, bucket: str, values: Dict[str, Any]) -> int:
    """Store one bartender override row per date/bucket."""
    cursor.execute("""
        DELETE FROM bartender_tip_overrides
        WHERE business_date = ? AND bucket = ?
    """, (date_str, bucket))

    cursor.execute("""
        INSERT INTO bartender_tip_overrides
        (business_date, bucket, cash_tips, credit_tips, net_sales, busser_tips, expo_tips, runner_tips, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (
        date_str,
        bucket,
        values.get('cash_tips', 0),
        values.get('credit_tips', 0),
        values.get('net_sales', 0),
        values.get('busser_tips', 0),
        values.get('expo_tips', 0),
        values.get('runner_tips', 0),
    ))

    return cursor.lastrowid


def init_check_assignments_table():
    """Initialize check_assignments table for tracking worker splits."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Table to store check assignments and splits
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS check_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_name TEXT NOT NULL,
                business_date TEXT NOT NULL,
                order_guid TEXT NOT NULL,
                check_guid TEXT NOT NULL,
                order_number TEXT,
                check_number TEXT,
                total_amount REAL DEFAULT 0,
                subtotal REAL DEFAULT 0,
                tax_amount REAL DEFAULT 0,
                assigned_workers TEXT DEFAULT '[]',
                split_type TEXT DEFAULT 'equal',
                split_count INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(check_guid, worker_name, business_date)
            )
        """)
        
        # Table to store per-check category sales per worker
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS check_category_sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_guid TEXT NOT NULL,
                worker_name TEXT NOT NULL,
                business_date TEXT NOT NULL,
                bucket TEXT,
                category_name TEXT NOT NULL,
                sales_amount REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(check_guid, worker_name, category_name, business_date)
            )
        """)
        
        # Table to track split payouts for rollback
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS split_payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payout_session_id TEXT,
                worker_name TEXT NOT NULL,
                check_guid TEXT NOT NULL,
                business_date TEXT NOT NULL,
                bucket TEXT NOT NULL,
                amount REAL NOT NULL,
                payout_destination TEXT NOT NULL,
                split_percentage REAL DEFAULT 100,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (payout_session_id) REFERENCES payout_sessions(id)
            )
        """)
        
        conn.commit()
        conn.close()
        print("Check assignments tables initialized")
    except Exception as e:
        print(f"Error initializing check assignments tables: {e}")


def init_order_check_tables():
    """Initialize tables for storing order and check data with per-item category details.
    
    These tables enable accurate per-check tip calculations when splitting checks.
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Table to store orders
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_guid TEXT NOT NULL UNIQUE,
                business_date TEXT NOT NULL,
                order_number TEXT,
                opened_date TEXT,
                paid_date TEXT,
                source TEXT,
                total_amount REAL DEFAULT 0,
                tax_amount REAL DEFAULT 0,
                dining_option TEXT,
                revenue_center TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(business_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_orders_guid ON orders(order_guid)
        """)
        
        # Table to store checks within orders
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_guid TEXT NOT NULL UNIQUE,
                order_guid TEXT NOT NULL,
                business_date TEXT NOT NULL,
                check_number TEXT,
                server_guid TEXT,
                server_name TEXT,
                total_amount REAL DEFAULT 0,
                tax_amount REAL DEFAULT 0,
                subtotal REAL DEFAULT 0,
                is_voided BOOLEAN DEFAULT 0,
                is_deleted BOOLEAN DEFAULT 0,
                opened_date TEXT,
                paid_date TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (order_guid) REFERENCES orders(order_guid)
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_checks_date ON checks(business_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_checks_server ON checks(server_guid)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_checks_order ON checks(order_guid)
        """)
        
        # Table to store individual items on checks with category info
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS check_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_guid TEXT NOT NULL,
                order_guid TEXT NOT NULL,
                business_date TEXT NOT NULL,
                item_guid TEXT,
                item_name TEXT,
                category_name TEXT,
                category_guid TEXT,
                quantity REAL DEFAULT 1,
                unit_price REAL DEFAULT 0,
                total_price REAL DEFAULT 0,
                is_voided BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (check_guid) REFERENCES checks(check_guid),
                FOREIGN KEY (order_guid) REFERENCES orders(order_guid)
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_check_items_check ON check_items(check_guid)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_check_items_date ON check_items(business_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_check_items_category ON check_items(category_name)
        """)
        
        # Table to store per-check category totals (computed from check_items)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS check_category_totals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_guid TEXT NOT NULL,
                business_date TEXT NOT NULL,
                category_name TEXT NOT NULL,
                total_sales REAL DEFAULT 0,
                item_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(check_guid, category_name)
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_check_cat_totals_date ON check_category_totals(business_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_check_cat_totals_check ON check_category_totals(check_guid)
        """)
        
        # Table to track which workers handled which checks (many-to-many)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS check_workers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_guid TEXT NOT NULL,
                worker_guid TEXT NOT NULL,
                worker_name TEXT NOT NULL,
                business_date TEXT NOT NULL,
                is_primary_server BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(check_guid, worker_guid)
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_check_workers_date ON check_workers(business_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_check_workers_worker ON check_workers(worker_guid)
        """)
        
        conn.commit()
        conn.close()
        print("Order/check tables initialized")
    except Exception as e:
        print(f"Error initializing order/check tables: {e}")


# Initialize tables on module load
init_check_assignments_table()
init_order_check_tables()
init_bartender_tip_override_table()
init_server_shift_override_table()
init_role_corrections_table()
init_labor_watch_tables()

# ====================
# STATIC FILES
# ====================

@app.route('/')
def index():
    """Serve the main index.html file."""
    return send_from_directory('.', 'index.html')

@app.route('/app.js')
def app_js():
    """Serve the app.js file."""
    return send_from_directory('.', 'app.js')

# ====================
# WORKERS API
# ====================

@app.route('/api/workers', methods=['GET'])
def get_workers():
    """Get all workers from JAQ datalake."""
    try:
        # Query JAQ server for employees
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_employees.json',
            'limit': '1000'
        })
        
        if response.status_code == 200:
            data = response.json()
            workers = []
            for item in data:
                try:
                    emp = json.loads(item.get('json_data', '{}'))
                    first = emp.get('firstName', '')
                    last = emp.get('lastName', '')
                    name = " ".join(f"{first} {last}".split())
                    if name:
                        workers.append(name)
                except:
                    continue
            return jsonify(sorted(workers))
        else:
            # Fallback to local DB
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM workers ORDER BY name")
            workers = [row['name'] for row in cursor.fetchall()]
            conn.close()
            return jsonify(workers)
    except Exception as e:
        print(f"Error fetching workers from JAQ: {e}")
        # Fallback to local DB
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM workers ORDER BY name")
        workers = [row['name'] for row in cursor.fetchall()]
        conn.close()
        return jsonify(workers)

@app.route('/api/workers/<name>/shifts', methods=['GET'])
def get_worker_shifts(name):
    """Get worker's shifts for a specific date."""
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({"error": "Date required"}), 400
    
    shifts = get_worker_shifts_for_date(name, date_str)
    return jsonify(shifts)

@app.route('/api/workers/<name>/suggested-buckets', methods=['GET'])
def get_worker_suggested_buckets(name):
    """Get suggested buckets (locations) where worker worked on a given date."""
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({"error": "Date required"}), 400
    
    buckets = get_suggested_buckets_for_worker(name, date_str)
    return jsonify(buckets)

@app.route('/api/dates', methods=['GET'])
def get_available_dates():
    """Get all dates that have order data."""
    try:
        # Get dates from orders files - check both locations
        dates = []
        
        # Check JAQ directory (orders_full_YYYYMMDD.json)
        for f in JSON_DIR.glob("orders_full_*.json"):
            date_str = f.stem.replace("orders_full_", "")
            if len(date_str) == 8 and date_str.isdigit():
                formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
                dates.append(formatted)
        
        # Check raw orders directory (YYYY-MM-DD.json)
        for f in RAW_ORDERS_DIR.glob("*.json"):
            date_str = f.stem  # Already in YYYY-MM-DD format
            if len(date_str) == 10 and date_str[4] == '-' and date_str[7] == '-':
                dates.append(date_str)
        
        # Remove duplicates and sort
        return jsonify(sorted(set(dates)))
    except Exception as e:
        print(f"Error getting dates: {e}")
        return jsonify([])

@app.route('/api/dates/<date_str>/workers', methods=['GET'])
def get_workers_for_date(date_str):
    """Get all workers who worked on a specific date with their shifts from JAQ."""
    try:
        # Convert date format from YYYY-MM-DD to Toast format YYYYMMDD
        toast_date = date_str.replace('-', '')
        
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        
        # First, get all employees to map GUIDs to names
        emp_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_employees.json',
            'limit': '1000'
        })
        
        employees = {}
        if emp_response.status_code == 200:
            for item in emp_response.json():
                try:
                    emp = json.loads(item.get('json_data', '{}'))
                    guid = emp.get('guid') or emp.get('v2EmployeeGuid')
                    first = emp.get('firstName', '')
                    last = emp.get('lastName', '')
                    name = " ".join(f"{first} {last}".split())
                    if guid and name:
                        employees[guid] = {
                            'name': name,
                            'guid': guid
                        }
                except:
                    continue
        
        # Get jobs to map job GUIDs to titles
        job_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_jobs.json',
            'limit': '1000'
        })
        
        jobs = {}
        if job_response.status_code == 200:
            for item in job_response.json():
                try:
                    job = json.loads(item.get('json_data', '{}'))
                    guid = job.get('guid')
                    title = job.get('title', '')
                    if guid and title:
                        jobs[guid] = title
                except:
                    continue
        
        # Now get time entries for the specific date
        time_file = f"labor_v1_timeEntries_{toast_date}.json"
        time_response = requests.get(f"{jaq_url}/query", params={
            'source_file': time_file,
            'limit': '10000'
        })
        
        workers = {}  # Group by worker name
        time_data = time_response.json() if time_response.status_code == 200 else []
        
        if time_data:
            # Use time entries data (detailed shift info available)
            for item in time_data:
                try:
                    entry = json.loads(item.get('json_data', '{}'))
                    
                    # Skip if not the right business date
                    if entry.get('businessDate') != toast_date:
                        continue
                    
                    emp_ref = entry.get('employeeReference', {})
                    emp_guid = emp_ref.get('guid')
                    
                    if not emp_guid or emp_guid not in employees:
                        continue
                    
                    name = employees[emp_guid]['name']
                    
                    job_ref = entry.get('jobReference', {})
                    job_guid = job_ref.get('guid')
                    job_title = jobs.get(job_guid, 'Unknown')
                    
                    # Skip cleaning jobs
                    if "cleaning" in job_title.lower():
                        continue
                    
                    bucket_id = job_title_to_bucket_id(job_title)
                    
                    if name not in workers:
                        workers[name] = {
                            "name": name,
                            "shifts": [],
                            "locations": set(),
                            "total_hours": 0
                        }
                    
                    hours = float(entry.get('regularHours', 0) or 0)
                    in_date = entry.get('inDate', '')
                    out_date = entry.get('outDate', '')
                    
                    workers[name]["shifts"].append({
                        "job_title": job_title,
                        "start_time": in_date,
                        "end_time": out_date,
                        "hours": hours,
                        "location": bucket_id_to_display(bucket_id) if bucket_id else "Other"
                    })
                    
                    workers[name]["total_hours"] += hours
                    if bucket_id:
                        workers[name]["locations"].add(bucket_id)
                        
                except Exception as e:
                    continue
        else:
            # Fallback: Use orders data to find employees who worked on this date
            orders_file = f"orders_full_{toast_date}.json"
            orders_response = requests.get(f"{jaq_url}/query", params={
                'source_file': orders_file,
                'limit': '100000'
            })
            
            if orders_response.status_code == 200:
                # Track unique employees and their activity
                emp_activity = {}  # {emp_guid: {'orders': 0, 'tips': 0, 'first_order': None, 'last_order': None}}
                
                for item in orders_response.json():
                    try:
                        order = json.loads(item.get('json_data', '{}'))
                        
                        # Get order timestamp
                        opened_date = order.get('openedDate', '')
                        if not opened_date:
                            continue
                            
                        # Check each check in the order
                        for check in order.get('checks', []):
                            # Check each payment for server info
                            for payment in check.get('payments', []):
                                server = payment.get('server', {})
                                emp_guid = server.get('guid')
                                
                                if not emp_guid or emp_guid not in employees:
                                    continue
                                
                                if emp_guid not in emp_activity:
                                    emp_activity[emp_guid] = {
                                        'orders': 0, 
                                        'tips': 0, 
                                        'first_order': opened_date,
                                        'last_order': opened_date
                                    }
                                
                                emp_activity[emp_guid]['orders'] += 1
                                emp_activity[emp_guid]['tips'] += float(payment.get('tipAmount') or 0)
                                
                                # Track first and last order times
                                if opened_date < emp_activity[emp_guid]['first_order']:
                                    emp_activity[emp_guid]['first_order'] = opened_date
                                if opened_date > emp_activity[emp_guid]['last_order']:
                                    emp_activity[emp_guid]['last_order'] = opened_date
                                
                    except Exception as e:
                        continue
                
                # Create worker entries from activity
                for emp_guid, activity in emp_activity.items():
                    name = employees[emp_guid]['name']
                    
                    # Only include employees who had tips (indicates they were serving)
                    if activity['tips'] > 0:
                        # Calculate estimated hours from first and last order
                        from datetime import datetime as dt
                        try:
                            first_dt = dt.fromisoformat(activity['first_order'].replace('Z', '+00:00'))
                            last_dt = dt.fromisoformat(activity['last_order'].replace('Z', '+00:00'))
                            # Calculate hours between first and last order
                            hours_worked = (last_dt - first_dt).total_seconds() / 3600
                            # Round to 2 decimal places, minimum 0.5 hours
                            hours_worked = max(round(hours_worked, 2), 0.5)
                        except:
                            hours_worked = 0
                        
                        # Try to infer location from worker name (for placeholder bars)
                        bucket_id = job_title_to_bucket_id(name)
                        location_display = bucket_id_to_display(bucket_id) if bucket_id else "Unknown"
                        
                        # Build locations set
                        locations = set()
                        if bucket_id:
                            locations.add(bucket_id)
                        
                        workers[name] = {
                            "name": name,
                            "shifts": [{
                                "job_title": "Server (from orders)",
                                "start_time": activity['first_order'],
                                "end_time": activity['last_order'],
                                "hours": hours_worked,
                                "location": location_display
                            }],
                            "locations": locations,
                            "total_hours": hours_worked,
                            "orders_count": activity['orders'],
                            "total_tips": round(activity['tips'], 2)
                        }
        
        # Convert sets to lists for JSON serialization
        result = []
        for w in workers.values():
            # Get primary job title from shifts (most common)
            job_titles = [s.get("job_title", "") for s in w["shifts"]]
            primary_job_title = job_titles[0] if job_titles else "Unknown"
            
            entry = {
                "name": w["name"],
                "shifts": w["shifts"],
                "locations": [bucket_id_to_display(loc) for loc in w["locations"]],
                "total_hours": round(w["total_hours"], 2),
                "job_title": primary_job_title
            }
            # Include total_tips if available (orders fallback)
            if "total_tips" in w:
                entry["total_tips"] = w["total_tips"]
            if "orders_count" in w:
                entry["orders_count"] = w["orders_count"]
            result.append(entry)
        
        # Sort by name
        result.sort(key=lambda x: x["name"])
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Error getting workers for date: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/workers/<name>/roles', methods=['GET'])
def get_worker_roles(name):
    """Get roles for a specific worker."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM worker_roles WHERE worker_name = ?", (name,))
    roles = [row['role'] for row in cursor.fetchall()]
    conn.close()
    return jsonify(roles)

# ====================
# BUCKETS API
# ====================

@app.route('/api/buckets', methods=['GET'])
def get_buckets():
    """Get all unique buckets from worker_assignments."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT bucket FROM worker_assignments ORDER BY bucket")
    db_buckets = [row['bucket'] for row in cursor.fetchall()]
    
    # Map bucket IDs to display names
    buckets = []
    for bucket_id in db_buckets:
        buckets.append({
            "id": bucket_id,
            "name": bucket_id_to_display(bucket_id)
        })
    
    # If no buckets in DB, return defaults (Toast location buckets)
    if not buckets:
        buckets = [
            {"id": "am_bar", "name": "AM Bar"},
            {"id": "sunset", "name": "Sunset Bar"},
            {"id": "westwing", "name": "West Wing"},
            {"id": "eastwing", "name": "East Wing"}
        ]
    
    conn.close()
    return jsonify(buckets)

def parse_toast_datetime(dt_str: str) -> Optional[datetime]:
    """Parse Toast datetime string to datetime object.
    Handles formats like: 2025-12-30T15:37:30.780+0000
    """
    if not dt_str:
        return None
    try:
        # Handle +0000 format (convert to +00:00 for fromisoformat)
        if dt_str.endswith('+0000'):
            dt_str = dt_str[:-5] + '+00:00'
        elif dt_str.endswith('-0000'):
            dt_str = dt_str[:-5] + '-00:00'
        elif '+00:00' not in dt_str and '-00:00' not in dt_str:
            # Handle Z suffix
            dt_str = dt_str.replace('Z', '+00:00')
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None


def load_orders_for_date(date_str: str) -> List[Dict]:
    """Load orders for a date from JAQ daily file only.

    Source:
    - /home/ubuntu/jaq/loadjson/orders_full_YYYYMMDD.json
    """
    date_clean = date_str.replace('-', '')
    jaq_file = JSON_DIR / f"orders_full_{date_clean}.json"
    if not jaq_file.exists():
        return []
    try:
        with open(jaq_file, 'r') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def calculate_tips_from_orders(worker_name: str, date_str: str) -> Dict:
    """Calculate tips from Toast orders for a specific worker on a date.
    
    Returns dict with:
    - cash_tips: Tips from cash payments
    - non_cash_tips: Tips from credit/card payments  
    - gratuity: Auto-gratuity (if available)
    - cash_collected: Cash sales collected (cash payment amount excluding cash tips)
    - net_sales: Total sales attributed to worker
    - tips_by_bucket: Breakdown by location bucket
    """
    result = {
        "cash_tips": 0.0,
        "non_cash_tips": 0.0,
        "gratuity": 0.0,
        "cash_collected": 0.0,
        "net_sales": 0.0,
        "tips_by_bucket": {},
        "split_check_count": 0,
        "has_split_checks": False
    }
    
    # Get employee GUID from JAQ
    emp_guid = get_employee_guid_for_worker(worker_name)
    if not emp_guid:
        print(f"No employee GUID found for {worker_name}")
        return result
    
    try:
        orders = load_orders_for_date(date_str)
        if not orders:
            print(f"No orders found for {date_str}")
            return result
        
        print(f"Processing {len(orders)} orders for {worker_name} on {date_str}")
        
        # Get worker's shifts to determine time ranges and buckets
        shift_ranges = get_worker_shift_ranges_with_cleaning(worker_name, date_str)
        if not shift_ranges:
            print(f"No shifts found for {worker_name} on {date_str}")
            return result
        
        print(f"Found {len(shift_ranges)} shifts")
        for shift_range in shift_ranges:
            print(f"  Shift: {shift_range['bucket']} - {shift_range['start']} to {shift_range['end']}")
        
        # Build employee alias set for robust matching (guid/id/v2EmployeeGuid)
        emp_aliases = get_employee_aliases_for_worker(worker_name) or {emp_guid}
        emp_aliases.add(emp_guid)
        check_assignments = get_worker_check_assignment_map(worker_name, date_str)
        split_check_guids = {guid for guid, assigned in check_assignments.items() if len(assigned) > 1}
        
        # Process each order
        for order in orders:
            order_srv = order.get('server', {}) or {}
            order_srv_ids = [
                (order_srv.get('guid') or '').strip(),
                (order_srv.get('id') or '').strip(),
                (order_srv.get('v2EmployeeGuid') or '').strip(),
            ]
            has_emp_order = any(sid and sid in emp_aliases for sid in order_srv_ids)
            checks = order.get('checks', [])
            for check in checks:
                if check.get('voided') or check.get('deleted'):
                    continue
                matched_bucket = get_check_assigned_bucket(check, shift_ranges)
                
                # Check ownership is based on order.server (not payment.server).
                check_cash_tips = 0.0
                check_credit_tips = 0.0
                check_cash_collected = 0.0
                check_gratuity = 0.0
                check_guid = check.get('guid', '')
                split_pct = get_worker_split_percentage(check_guid, worker_name, check_assignments)
                has_cash_payment = False
                has_non_cash_payment = False
                cash_payment_rows: List[tuple[float, float]] = []  # (amount, tip)
                
                for payment in check.get('payments', []):
                    tip = float(payment.get('tipAmount', 0) or 0)
                    payment_type_raw = (
                        payment.get('type')
                        or payment.get('paymentType')
                        or payment.get('tenderType')
                        or ''
                    )
                    if isinstance(payment_type_raw, dict):
                        payment_type = str(payment_type_raw.get('name') or payment_type_raw.get('value') or '').upper()
                    else:
                        payment_type = str(payment_type_raw).upper()
                    payment_amount = float(
                        payment.get('amount')
                        or payment.get('paymentAmount')
                        or payment.get('appliedAmount')
                        or 0
                    )

                    if payment_type == 'CASH':
                        has_cash_payment = True
                        check_cash_tips += tip
                        # Keep cash payment rows and apply Toast-like mixed-tender
                        # exclusion after we know full tender composition.
                        cash_payment_rows.append((payment_amount, tip))
                    else:
                        has_non_cash_payment = True
                        check_credit_tips += tip

                # Cash collected (sales): include cash tender on both cash-only and
                # mixed-tender checks. Cash tip is excluded from sales cash.
                if has_cash_payment:
                    for payment_amount, tip in cash_payment_rows:
                        check_cash_collected += max(0.0, payment_amount - tip)
                
                has_split_share = check_guid in check_assignments and split_pct > 0

                # Include checks directly owned by the worker or explicitly split to them.
                if has_emp_order or has_split_share:
                    # Use 'amount' (net after discounts) like the original app, not 'totalAmount' (gross)
                    # Also check for gift card purchases and exclude them
                    check_amount = check.get('amount') or check.get('total') or check.get('net') or check.get('subtotal') or 0.0
                    check_amount = float(check_amount)
                    
                    # Check if this check has gift card purchases - exclude them from net sales
                    gift_card_total = 0.0
                    for selection in check.get('selections', []):
                        item_name = (selection.get('displayName', '') or selection.get('itemName', '')).lower()
                        if 'gift card' in item_name or 'giftcard' in item_name:
                            gift_card_total += float(selection.get('price', 0) or 0)
                    
                    # Subtract gift card sales from net sales (like original app)
                    check_net_sales = check_amount - gift_card_total
                    share = split_pct / 100.0 if check_guid in check_assignments else 1.0

                    # Gratuity/service fees come from applied gratuity service charges.
                    for svc_charge in check.get('appliedServiceCharges', []):
                        if not isinstance(svc_charge, dict):
                            continue
                        if svc_charge.get('voided') or svc_charge.get('deleted'):
                            continue
                        if svc_charge.get('gratuity', False):
                            check_gratuity += float(svc_charge.get('chargeAmount') or 0)
                    
                    # Add to totals
                    result['cash_tips'] += check_cash_tips * share
                    result['non_cash_tips'] += check_credit_tips * share
                    result['gratuity'] += check_gratuity * share
                    result['cash_collected'] += check_cash_collected * share
                    result['net_sales'] += check_net_sales * share
                    
                    # Add to bucket breakdown
                    if matched_bucket:
                        if matched_bucket not in result['tips_by_bucket']:
                            result['tips_by_bucket'][matched_bucket] = {
                                'cash_tips': 0,
                                'non_cash_tips': 0,
                                'gratuity': 0,
                                'cash_collected': 0,
                                'net_sales': 0
                            }
                        result['tips_by_bucket'][matched_bucket]['cash_tips'] += check_cash_tips * share
                        result['tips_by_bucket'][matched_bucket]['non_cash_tips'] += check_credit_tips * share
                        result['tips_by_bucket'][matched_bucket]['gratuity'] += check_gratuity * share
                        result['tips_by_bucket'][matched_bucket]['cash_collected'] += check_cash_collected * share
                        result['tips_by_bucket'][matched_bucket]['net_sales'] += check_net_sales * share
        
        result['split_check_count'] = len(split_check_guids)
        result['has_split_checks'] = bool(split_check_guids)
        
        return result
        
    except Exception as e:
        print(f"Error calculating tips: {e}")
        return result


# ====================
# SERVER TIPS API
# ====================

@app.route('/api/server-shift-override', methods=['GET'])
def get_server_shift_override_api():
    """Get manual shift-bucket override for worker/date."""
    worker = (request.args.get('worker') or '').strip()
    date = (request.args.get('date') or '').strip()
    if not worker or not date:
        return jsonify({"error": "Worker and date required"}), 400
    return jsonify(get_server_shift_override(worker, date))


@app.route('/api/server-shift-override', methods=['POST'])
def save_server_shift_override_api():
    """Save or update manual shift-bucket override for worker/date."""
    data = request.json or {}
    worker = (data.get('worker') or '').strip()
    date = (data.get('date') or '').strip()
    bucket = (data.get('bucket') or '').strip()
    valid_buckets = {'am_bar', 'sunset', 'westwing', 'eastwing'}
    if not worker or not date or bucket not in valid_buckets:
        return jsonify({"error": "Worker, date, and valid bucket required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO server_shift_overrides (worker_name, business_date, bucket, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(worker_name, business_date) DO UPDATE SET
                bucket = excluded.bucket,
                updated_at = CURRENT_TIMESTAMP
        """, (worker, date, bucket))
        conn.commit()
    finally:
        conn.close()

    return jsonify({"success": True, "override": get_server_shift_override(worker, date)})


@app.route('/api/server-shift-override', methods=['DELETE'])
def delete_server_shift_override_api():
    """Delete manual shift-bucket override for worker/date."""
    worker = (request.args.get('worker') or '').strip()
    date = (request.args.get('date') or '').strip()
    if not worker or not date:
        return jsonify({"error": "Worker and date required"}), 400

    deleted = delete_server_shift_override(worker, date)

    return jsonify({"success": True, "deleted": deleted})

@app.route('/api/server-tips', methods=['GET'])
def get_server_tips():
    """Get server tips for a specific worker/date/bucket."""
    worker = request.args.get('worker')
    date = request.args.get('date')
    bucket = request.args.get('bucket', '')
    
    if not worker or not date:
        return jsonify({"error": "Worker and date required"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get existing tips record
    cursor.execute("""
        SELECT * FROM servers 
        WHERE worker_name = ? AND business_date = ? AND bucket = ?
        ORDER BY id DESC LIMIT 1
    """, (worker, date, bucket))
    
    row = cursor.fetchone()
    
    # Get suggested buckets from shifts
    suggested_buckets = get_suggested_buckets_for_worker(worker, date)
    
    # Calculate tips from Toast orders
    calculated_tips = calculate_tips_from_orders(worker, date)
    
    # Get declared cash tips from Toast time entries (employee-declared cash tips)
    # Filter by bucket if specified to get bucket-specific cash tips
    declared_cash_tips = get_declared_cash_tips_from_time_entries(worker, date, bucket if bucket else None)
    gratuity_from_time_entries = get_gratuity_from_time_entries(worker, date, bucket if bucket else None)
    non_cash_from_time_entries = get_non_cash_tips_from_time_entries(worker, date, bucket if bucket else None)
    
    # If a specific bucket is selected, return only that bucket's data.
    split_check_count = int(calculated_tips.get('split_check_count') or 0)
    if bucket:
        bucket_data = calculated_tips.get('tips_by_bucket', {}).get(bucket)
        if bucket_data:
            filtered_tips = {
                "cash_tips": bucket_data['cash_tips'],
                "non_cash_tips": bucket_data['non_cash_tips'],
                "gratuity": bucket_data.get('gratuity', 0.0),
                "cash_collected": bucket_data.get('cash_collected', 0.0),
                "net_sales": bucket_data['net_sales'],
                "tips_by_bucket": {bucket: bucket_data}
            }
        else:
            # Explicit bucket selected, but no matching shifts/checks for that bucket.
            filtered_tips = {
                "cash_tips": 0.0,
                "non_cash_tips": 0.0,
                "gratuity": 0.0,
                "cash_collected": 0.0,
                "net_sales": 0.0,
                "tips_by_bucket": {}
            }
        calculated_tips = filtered_tips
    else:
        # Keep split-adjusted gratuity from checks by default.
        pass

    # Fallback: when no split assignments exist and check-derived gratuity is missing,
    # use Toast time-entry gratuity totals.
    try:
        current_gratuity = float(calculated_tips.get('gratuity') or 0.0)
        if split_check_count == 0 and current_gratuity <= 0 and gratuity_from_time_entries > 0:
            calculated_tips['gratuity'] = gratuity_from_time_entries
    except Exception:
        pass

    # During active/open shifts, order tip amounts may lag. Use Toast time-entry
    # non-cash tips as fallback when calculated non-cash tips are zero.
    try:
        current_non_cash = float(calculated_tips.get('non_cash_tips') or 0.0)
        if current_non_cash <= 0 and non_cash_from_time_entries > 0:
            calculated_tips['non_cash_tips'] = non_cash_from_time_entries
    except Exception:
        pass
    
    # Add declared cash tips from time entries to the result
    # This is separate from calculated cash tips (which come from order payments)
    calculated_tips['declared_cash_tips'] = declared_cash_tips
    
    conn.close()
    
    shift_override = get_server_shift_override(worker, date)
    result = {
        "suggested_buckets": suggested_buckets,
        "calculated_tips": calculated_tips,
        "existing_record": None,
        "shift_bucket_override": shift_override
    }
    
    if row:
        result["existing_record"] = {
            "id": row['id'],
            "server": row['worker_name'],
            "date": row['business_date'],
            "bucket": row['bucket'],
            "cash_tips": row['cash_tips'],
            "non_cash_tips": row['credit_tips'],
            "gratuity": row['gratuity'],
            "net_sales": row['net_sales'],
            "bar_tips": row['bar_tips'],
            "busser_tips": row['busser_tips'],
            "expo_tips": row['expo_tips'],
            "runner_tips": row['runner_tips'],
            "sum_tips_for_payout": (
                float(row['bar_tips'] or 0) +
                float(row['busser_tips'] or 0) +
                float(row['expo_tips'] or 0) +
                float(row['runner_tips'] or 0)
            ),
            "is_override": True
        }
    
    return jsonify(result)

@app.route('/api/server-tips', methods=['POST'])
def save_server_tips():
    """Save server tips."""
    data = request.json
    
    conn = get_db()
    cursor = conn.cursor()
    
    row_id = upsert_server_tip_cache(cursor, data.get('worker'), data.get('date'), data.get('bucket', ''), {
        'cash_tips': data.get('cash_tips', 0),
        'credit_tips': data.get('credit_tips', 0),
        'gratuity': data.get('gratuity', 0),
        'net_sales': data.get('net_sales', 0),
        'bar_tips': data.get('bar_tips', 0),
        'busser_tips': data.get('busser_tips', 0),
        'expo_tips': data.get('expo_tips', 0),
        'runner_tips': data.get('runner_tips', 0),
    })
    
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "id": row_id})

# ====================
# BARTENDER TIPS API
# ====================

@app.route('/api/bartender-tips', methods=['GET'])
def get_bartender_tips():
    """Get bartender tips for a specific bartender/date/bar."""
    bartender = request.args.get('bartender')
    date = request.args.get('date')
    bar = request.args.get('bar', '')
    
    if not bartender or not date:
        return jsonify({"error": "Bartender and date required"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM bartenders 
        WHERE bartender = ? AND date = ? AND bar_name = ?
        ORDER BY id DESC LIMIT 1
    """, (bartender, date, bar))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return jsonify({
            "id": row['id'],
            "bartender": row['bartender'],
            "date": row['date'],
            "bar_name": row['bar_name'],
            "cash_tips": row['cash_tips'],
            "credit_tips": row['credit_tips'],
            "net_sales": row['net_sales'],
            "hours_worked": row['hours_worked']
        })
    
    return jsonify(None)

@app.route('/api/bartender-tips', methods=['POST'])
def save_bartender_tips():
    """Save bartender tips."""
    data = request.json
    
    conn = get_db()
    cursor = conn.cursor()
    
    sum_tips = float(data.get('cash_tips', 0)) + float(data.get('credit_tips', 0))
    
    cursor.execute("""
        INSERT INTO bartenders 
        (date, bartender, bar_name, cash_tips, credit_tips, net_sales, hours_worked, sum_tips_for_payout)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get('date'),
        data.get('worker'),
        data.get('bar', ''),
        data.get('cash_tips', 0),
        data.get('credit_tips', 0),
        data.get('net_sales', 0),
        data.get('hours', 0),
        sum_tips
    ))
    
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "id": cursor.lastrowid})


# ====================
# BARTENDER DEFAULTS API (for group bartender tips page)
# ====================

def parse_iso_datetime(dt_str):
    """Parse ISO datetime string to datetime object."""
    if not dt_str:
        return None
    try:
        # Handle various ISO formats
        dt_str = dt_str.replace('Z', '+00:00')
        if dt_str.endswith('+0000'):
            dt_str = dt_str[:-5] + '+00:00'
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None


def job_title_to_bar_bucket(title):
    """Map job title to bar bucket ID."""
    t = (title or '').strip().lower()
    if not t:
        return None
    if 'am sunset' in t and 'bar' in t:
        return 'am_bar'
    if ('pm sunset' in t and 'bar' in t) or ('sunset' in t and 'bar' in t):
        return 'sunset'
    if 'ww bar' in t or 'west wing bar' in t:
        return 'westwing'
    if 'ew bar' in t or 'east wing bar' in t:
        return 'eastwing'
    return None


def bucket_to_bar_display_name(bucket):
    """Convert bucket ID to bar display name used in orders."""
    mapping = {
        'sunset': 'Low Bar',
        'am_bar': 'AM Bar',
        'westwing': 'WW Bar',
        'eastwing': 'EW Bar'
    }
    return mapping.get(bucket, '')


def load_sales_category_name_map():
    """Load sales category GUID to name mapping from JAQ datalake."""
    mp = {}
    
    # Try JAQ datalake first
    try:
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        
        response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'config_v2_salesCategories.json',
            'limit': '1000'
        }, timeout=30)
        
        if response.status_code == 200:
            for item in response.json():
                try:
                    cat = json.loads(item.get('json_data', '{}'))
                    gid = cat.get('guid', '')
                    name = cat.get('name', '')
                    if gid and name:
                        mp[gid] = name
                except:
                    continue
    except Exception as e:
        print(f"Error loading sales categories from JAQ: {e}")
    
    # Fallback to CSV if JAQ failed
    if not mp:
        try:
            csv_path = REPORTS_DIR / "menu_category.csv"
            if csv_path.exists():
                with open(csv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        gid = (row.get('sales_category_guid') or '').strip()
                        name = (row.get('sales_category_name') or '').strip()
                        if gid and name:
                            mp[gid] = name
        except Exception:
            pass
    
    return mp


def bucket_for_cat_name(name):
    """Categorize sales category name into Food/Wine/Beer/Liquor/NA Beverage."""
    n = (name or '').strip().lower()
    if not n:
        return 'Food'
    
    if ('wine' in n) and ('bottle' in n or 'bottled' in n):
        return 'Bottled Wine'
    if ('beer' in n) and ('bottle' in n or 'bottled' in n):
        return 'Bottled Beer'
    if n == 'wine' or ('wine' in n):
        return 'Wine'
    if ('draft' in n and 'beer' in n) or n == 'draft beer':
        return 'Draft Beer'
    if any(k in n for k in ['liquor', 'spirit', 'cocktail', 'whiskey', 'vodka', 'gin', 'tequila', 'rum', 'bourbon', 'rye', 'mezcal']):
        return 'Liquor'
    if any(k in n for k in ['na beverage', 'non-alcoholic', 'n/a beverage', 'mocktail', 'soda', 'juice', 'coffee', 'tea']):
        return 'NA Beverage'
    if 'beer' in n:
        return 'Draft Beer'
    return 'Food'


def classify_selection_category(item_name: str, category_guid: str, sales_cat_guid_to_name: Dict[str, str]) -> str:
    """Classify a check selection into a server-tip category.

    Special rule: room charges are always reported as No-Category.
    """
    item_name_l = (item_name or '').strip().lower()
    cat_guid = (category_guid or '').strip()

    # Always force room/open-room charges into No-Category.
    if 'room charge' in item_name_l or 'open room' in item_name_l:
        return 'No-Category'

    # Primary categorization via sales category GUID mapping.
    if cat_guid and cat_guid in sales_cat_guid_to_name:
        return bucket_for_cat_name(sales_cat_guid_to_name[cat_guid])

    # Fallback categorization from item text.
    if 'wine' in item_name_l:
        if 'bottle' in item_name_l or 'bottled' in item_name_l:
            return 'Bottled Wine'
        return 'Wine'
    if 'beer' in item_name_l or 'draft' in item_name_l:
        if 'bottle' in item_name_l or 'bottled' in item_name_l:
            return 'Bottled Beer'
        return 'Draft Beer'
    if 'liquor' in item_name_l or any(x in item_name_l for x in ['vodka', 'gin', 'rum', 'whiskey', 'bourbon', 'scotch', 'tequila']):
        return 'Liquor'
    if 'na ' in item_name_l or 'soda' in item_name_l or 'coffee' in item_name_l or 'tea' in item_name_l or 'water' in item_name_l:
        return 'NA Beverage'

    return 'No-Category'


def import_orders_for_date(date_str: str) -> Dict:
    """Import order data from JSON files into the database."""
    stats = {
        'orders_imported': 0,
        'checks_imported': 0,
        'items_imported': 0,
        'category_totals_computed': 0,
        'errors': []
    }
    
    sales_cat_map = load_sales_category_name_map()
    
    # Load employees mapping for looking up server names by GUID
    employees_by_guid = {}
    try:
        employees_file = JSON_DIR / "employees.json"
        if employees_file.exists():
            with open(employees_file, 'r') as f:
                employees = json.load(f)
            for emp in employees:
                guid = emp.get('guid') or emp.get('v2EmployeeGuid')
                if guid:
                    first = emp.get('firstName', '')
                    last = emp.get('lastName', '')
                    name = " ".join(f"{first} {last}".split())
                    employees_by_guid[guid] = name
    except Exception as e:
        print(f"Warning: Could not load employees: {e}")
    
    orders = load_orders_for_date(date_str)
    if not orders:
        stats['errors'].append(f"No order data found for {date_str}")
        return stats
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        for order_idx, order in enumerate(orders):
            if not isinstance(order, dict):
                continue
            
            try:
                order_guid = order.get('guid', '')
                if not order_guid:
                    continue
                
                order_number = str(order.get('displayNumber', ''))
                opened_date = order.get('openedDate', '')
                paid_date = order.get('paidDate', '')
                source = order.get('source', '')
                dining_option = (order.get('diningOption') or {}).get('name', '')
                revenue_center = (order.get('revenueCenter') or {}).get('name', '')
                
                total_amount = 0
                tax_amount = 0
                for check in order.get('checks', []):
                    if isinstance(check, dict) and not check.get('voided') and not check.get('deleted'):
                        total_amount += check.get('totalAmount', 0) or 0
                        tax_amount += check.get('taxAmount', 0) or 0
                
                cursor.execute("""
                    INSERT INTO orders 
                    (order_guid, business_date, order_number, opened_date, paid_date, 
                     source, total_amount, tax_amount, dining_option, revenue_center, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(order_guid) DO UPDATE SET
                        order_number = excluded.order_number,
                        opened_date = excluded.opened_date,
                        paid_date = excluded.paid_date,
                        source = excluded.source,
                        total_amount = excluded.total_amount,
                        tax_amount = excluded.tax_amount,
                        dining_option = excluded.dining_option,
                        revenue_center = excluded.revenue_center,
                        updated_at = datetime('now')
                """, (order_guid, date_str, order_number, opened_date, paid_date,
                      source, total_amount, tax_amount, dining_option, revenue_center))
                
                stats['orders_imported'] += 1
                
                for check in order.get('checks', []):
                    if not isinstance(check, dict):
                        continue
                    
                    check_guid = check.get('guid', '')
                    if not check_guid:
                        continue
                    
                    if check.get('voided') or check.get('deleted'):
                        continue
                    
                    check_number = str(check.get('displayNumber', ''))
                    check_total = check.get('totalAmount', 0) or 0
                    check_tax = check.get('taxAmount', 0) or 0
                    # Use 'amount' field if available (it's the actual subtotal)
                    # Otherwise fall back to totalAmount - taxAmount
                    check_subtotal = check.get('amount') or (check_total - check_tax)
                    
                    server_guid = None
                    server_name = None
                    check_paid_date = None
                    
                    for payment in check.get('payments', []):
                        if isinstance(payment, dict):
                            srv = payment.get('server', {})
                            if isinstance(srv, dict) and srv.get('guid'):
                                server_guid = srv.get('guid')
                                # Look up name from employees mapping if not in payment data
                                srv_first = srv.get('firstName', '')
                                srv_last = srv.get('lastName', '')
                                if srv_first or srv_last:
                                    server_name = f"{srv_first} {srv_last}".strip()
                                elif server_guid in employees_by_guid:
                                    server_name = employees_by_guid[server_guid]
                                check_paid_date = payment.get('paidDate') or payment.get('paidTime')
                                break
                    
                    cursor.execute("""
                        INSERT INTO checks 
                        (check_guid, order_guid, business_date, check_number, server_guid,
                         server_name, total_amount, tax_amount, subtotal, is_voided, is_deleted,
                         opened_date, paid_date, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(check_guid) DO UPDATE SET
                            server_guid = excluded.server_guid,
                            server_name = excluded.server_name,
                            total_amount = excluded.total_amount,
                            tax_amount = excluded.tax_amount,
                            subtotal = excluded.subtotal,
                            paid_date = excluded.paid_date,
                            updated_at = datetime('now')
                    """, (check_guid, order_guid, date_str, check_number, server_guid,
                          server_name, check_total, check_tax, check_subtotal,
                          check.get('voided', False), check.get('deleted', False),
                          opened_date, check_paid_date))
                    
                    stats['checks_imported'] += 1
                    
                    if server_guid and server_name:
                        cursor.execute("""
                            INSERT OR IGNORE INTO check_workers 
                            (check_guid, worker_guid, worker_name, business_date, is_primary_server)
                            VALUES (?, ?, ?, ?, 1)
                        """, (check_guid, server_guid, server_name, date_str))
                    
                    check_category_sales = {}
                    
                    for selection in check.get('selections', []):
                        if selection is None or not isinstance(selection, dict):
                            continue
                        
                        item_guid = selection.get('itemGuid', '') or selection.get('guid', '')
                        item_name = selection.get('displayName', '') or selection.get('itemName', '')
                        quantity = selection.get('quantity', 1) or 1
                        price = selection.get('price', 0) or 0
                        total_price = price
                        is_voided = selection.get('voided', False)
                        
                        if 'gift card' in (item_name or '').lower() or 'giftcard' in (item_name or '').lower():
                            continue
                        
                        category_guid = ''
                        category_name = 'No-Category'
                        
                        sales_cat = selection.get('salesCategory', {})
                        if isinstance(sales_cat, dict):
                            category_guid = sales_cat.get('guid', '')
                        category_name = classify_selection_category(item_name, category_guid, sales_cat_map)
                        
                        cursor.execute("""
                            INSERT INTO check_items 
                            (check_guid, order_guid, business_date, item_guid, item_name,
                             category_name, category_guid, quantity, unit_price, total_price, is_voided)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT DO NOTHING
                        """, (check_guid, order_guid, date_str, item_guid, item_name,
                              category_name, category_guid, quantity, price, total_price, is_voided))
                        
                        if cursor.rowcount > 0:
                            stats['items_imported'] += 1
                        
                        if not is_voided:
                            if category_name not in check_category_sales:
                                check_category_sales[category_name] = 0
                            check_category_sales[category_name] += total_price
                    
                    for cat_name, sales_amount in check_category_sales.items():
                        cursor.execute("""
                            INSERT INTO check_category_totals 
                            (check_guid, business_date, category_name, total_sales, item_count, updated_at)
                            VALUES (?, ?, ?, ?, ?, datetime('now'))
                            ON CONFLICT(check_guid, category_name) DO UPDATE SET
                                total_sales = excluded.total_sales,
                                item_count = excluded.item_count,
                                updated_at = datetime('now')
                        """, (check_guid, date_str, cat_name, sales_amount, 
                              sum(1 for s in check.get('selections', []) if isinstance(s, dict) and not s.get('voided'))))
                        
                        stats['category_totals_computed'] += 1
                
            except Exception as order_error:
                import traceback
                stats['errors'].append(f"Error processing order {order_idx}: {order_error}\\n{traceback.format_exc()}")
                continue
        
        conn.commit()
        
    except Exception as e:
        import traceback
        stats['errors'].append(f"Import error: {e}")
        stats['errors'].append(traceback.format_exc())
        conn.rollback()
    finally:
        conn.close()
    
    return stats


def get_bar_shift_windows(date_str, bucket):
    """Get bar shift time windows for a date and bucket using JAQ time entries."""
    shift_windows = []
    
    try:
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        toast_date = date_str.replace('-', '')
        
        # Load job map for GUID to title lookup
        job_map = load_job_map()
        
        response = requests.get(f"{jaq_url}/query", params={
            'source_file': f'labor_v1_timeEntries_{toast_date}.json',
            'limit': '10000'
        }, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            for item in data:
                try:
                    entry = json.loads(item.get('json_data', '{}'))
                    job_ref = entry.get('jobReference', {})
                    # Get job title from job map using GUID
                    job_guid = job_ref.get('guid', '')
                    job_title = job_map.get(job_guid, '')
                    
                    if job_title_to_bar_bucket(job_title) != bucket:
                        continue
                    
                    start = parse_iso_datetime(entry.get('inDate'))
                    end = parse_iso_datetime(entry.get('outDate'))
                    
                    if start and end and end > start:
                        shift_windows.append((start, end))
                except (json.JSONDecodeError, Exception):
                    continue
    except Exception as e:
        print(f"Error getting shift windows from JAQ: {e}")
    
    return shift_windows


def get_bar_worker_guids(bucket):
    """Get GUIDs for bar worker placeholder (Low Bar, AM Bar, etc) using JAQ employees.
    
    These GUIDs come from the employees 'guid' field and match the server.guid 
    values found in order payment data.
    """
    # Known GUID mappings - fallback if JAQ query fails
    known_guid_by_bucket = {
        'am_bar': {'88f963d0-1cc5-4243-943f-9f451d8ec715'},  # AM Bar
        'sunset': {'a407d349-f3a3-4354-a6c8-704a40f13e90'},   # Low Bar
        'westwing': {'303eb8b0-2874-4096-9817-9212adb5ac9f'}, # WW Bar
    }
    
    aliases = set(known_guid_by_bucket.get(bucket, set()))
    
    # Query JAQ for employees
    try:
        bar_name = bucket_to_bar_display_name(bucket).lower()
        if not bar_name:
            return aliases
        
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_employees.json',
            'limit': '10000'
        }, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            for item in data:
                try:
                    e = json.loads(item.get('json_data', '{}'))
                    first = (e.get('firstName') or '').strip()
                    last = (e.get('lastName') or '').strip()
                    chosen = (e.get('chosenName') or '').strip()
                    full = (first + (' ' + last if last else '')).strip()
                    
                    names = [n for n in [chosen, full] if n]
                    if any((n or '').strip().lower() == bar_name for n in names):
                        for k in ('guid', 'id', 'v2EmployeeGuid'):
                            v = (e.get(k) or '').strip()
                            if v:
                                aliases.add(v)
                        break
                except (json.JSONDecodeError, Exception):
                    continue
    except Exception as e:
        print(f"Error getting bar worker GUIDs from JAQ: {e}")
    
    return aliases


def calculate_bartender_defaults(date_str, bucket):
    """Calculate defaults for bartender tips page.
    
    Returns dict with:
    - cash_tips: Cash tips from bar worker payments
    - credit_card_tips: Credit card tips from bar worker payments
    - net_sales: Total net sales for bar
    - servertips: Calculated busser tips (2% of total sales)
    - expotips: Calculated expo tips (1% of food sales)
    - runnertips: Calculated runner tips (0.5% of food sales)
    - category_totals: Sales by category
    - category_tip_breakdown: Tips calculated per category
    - bartenders: List of bartenders who worked
    """
    result = {
        'cash_tips': 0.0,
        'credit_card_tips': 0.0,
        'net_sales': 0.0,
        'servertips': 0.0,
        'expotips': 0.0,
        'runnertips': 0.0,
        'category_totals': {},
        'category_tip_breakdown': {
            'servertips': {},
            'expotips': {},
            'runnertips': {}
        },
        'bartenders': []
    }
    
    # Get bar shift windows
    shift_windows = get_bar_shift_windows(date_str, bucket)
    
    # Get bar worker GUIDs for matching payments
    bar_aliases = get_bar_worker_guids(bucket)
    target_bar_name = bucket_to_bar_display_name(bucket).lower()
    
    # Load sales category mapping
    sales_cat_map = load_sales_category_name_map()
    
    # Category buckets
    BUCKETS = ["Food", "Wine", "Draft Beer", "Liquor", "NA Beverage", "Bottled Beer", "Bottled Wine", "Non-Grat Svc Charges"]
    category_totals = {k: 0.0 for k in BUCKETS}
    
    # Process orders
    cash_tip_sum = 0.0
    credit_tip_sum = 0.0
    net_sales_sum = 0.0
    
    # Process orders from JAQ datalake
    try:
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        toast_date = date_str.replace('-', '')
        
        # Query JAQ for orders on this date
        response = requests.get(f"{jaq_url}/query", params={
            'source_file': f'orders_full_{toast_date}.json',
            'limit': '50000'
        }, timeout=60)
        
        if response.status_code == 200:
            data = response.json()
            for item in data:
                try:
                    order = json.loads(item.get('json_data', '{}'))
                    for check in order.get('checks', []):
                        if check.get('voided') or check.get('deleted'):
                            continue
                        
                        # Check ownership by order.server (not payment.server).
                        order_srv = order.get('server', {}) or {}
                        order_srv_ids = [
                            (order_srv.get('guid') or '').strip(),
                            (order_srv.get('id') or '').strip(),
                            (order_srv.get('v2EmployeeGuid') or '').strip(),
                        ]
                        has_bar_order = False
                        if bar_aliases and any(i and i in bar_aliases for i in order_srv_ids):
                            has_bar_order = True
                        elif target_bar_name:
                            nm = (
                                order_srv.get('name')
                                or order_srv.get('fullName')
                                or order_srv.get('displayName')
                                or ''
                            ).strip().lower()
                            has_bar_order = (nm == target_bar_name)

                        if not has_bar_order:
                            continue
                        
                        # Check if within shift window
                        if shift_windows:
                            check_ts = parse_iso_datetime(
                                check.get('paidDate') or check.get('closedDate') or check.get('openedDate')
                            )
                            if check_ts:
                                in_window = False
                                for st, en in shift_windows:
                                    if st <= check_ts <= en:
                                        in_window = True
                                        break
                                if not in_window:
                                    continue
                        
                        # Aggregate tips from all payments on checks owned by the bar order.
                        for payment in check.get('payments', []):
                            tip_amt = float(payment.get('tipAmount') or payment.get('tips') or payment.get('gratuityTipAmount') or 0.0)
                            pay_type_raw = payment.get('paymentType') or payment.get('type') or payment.get('tenderType') or ''
                            if isinstance(pay_type_raw, dict):
                                pay_type = str(pay_type_raw.get('name') or pay_type_raw.get('value') or '').strip().upper()
                            else:
                                pay_type = str(pay_type_raw).strip().upper()

                            if pay_type == 'CASH' or 'CASH' in pay_type:
                                cash_tip_sum += tip_amt
                            else:
                                credit_tip_sum += tip_amt
                        
                        # Aggregate selections by category
                        for sel in check.get('selections', []):
                            if sel.get('voided') or sel.get('deleted'):
                                continue
                            
                            price = float(sel.get('price') or 0)
                            sc_guid = ((sel.get('salesCategory') or {}).get('guid')) or ''
                            sc_name = sales_cat_map.get(str(sc_guid), '')
                            
                            if not sc_name:
                                continue
                            
                            cat_bucket = bucket_for_cat_name(sc_name)
                            category_totals[cat_bucket] = category_totals.get(cat_bucket, 0.0) + price
                        
                        # Aggregate service charges (Non-Gratuity Service Charges)
                        for svc_charge in check.get('appliedServiceCharges', []):
                            if svc_charge.get('voided') or svc_charge.get('deleted'):
                                continue
                            # Only include non-gratuity service charges
                            if not svc_charge.get('gratuity', False):
                                charge_amt = float(svc_charge.get('chargeAmount') or 0)
                                category_totals['Non-Grat Svc Charges'] = category_totals.get('Non-Grat Svc Charges', 0.0) + charge_amt
                except (json.JSONDecodeError, Exception):
                    continue
    except Exception as e:
        print(f"Error processing orders from JAQ: {e}")
    
    # Calculate tip suggestions from categories
    sv_break = {}
    ex_break = {}
    rn_break = {}
    
    for cat, amt in category_totals.items():
        a = float(amt or 0.0)
        # Non-gratuity service charges are sales-only (no tip-out).
        if cat == 'Non-Grat Svc Charges':
            sv_break[cat] = 0.0
            ex_break[cat] = 0.0
            rn_break[cat] = 0.0
        else:
            sv_break[cat] = round(0.02 * a, 2)  # 2% for busser
            # 1% for expo on food only
            ex_break[cat] = round(0.01 * a, 2) if cat == 'Food' else 0.0
            # 0.5% for runner on food only
            rn_break[cat] = round(0.005 * a, 2) if cat == 'Food' else 0.0
    
    # Get bartenders who worked this bar on this date from JAQ
    bartenders = []
    try:
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        toast_date = date_str.replace('-', '')
        
        title_patterns = {
            'am_bar': ['am bar sunset', 'am bar'],
            'sunset': ['pm bar sunset', 'pm bar - sunset', 'sunset bar', 'low bar'],
            'westwing': ['ww bar', 'west wing bar']
        }
        patterns = title_patterns.get(bucket, [])
        
        # Query JAQ for time entries to find bartenders
        response = requests.get(f"{jaq_url}/query", params={
            'source_file': f'labor_v1_timeEntries_{toast_date}.json',
            'limit': '10000'
        }, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            # Load job and employee data for lookups
            job_map = load_job_map()
            
            for item in data:
                try:
                    entry = json.loads(item.get('json_data', '{}'))
                    job_ref = entry.get('jobReference', {})
                    # Get job title from job map using GUID
                    job_guid = job_ref.get('guid', '')
                    job_title = job_map.get(job_guid, '')
                    
                    if any(p in job_title.lower() for p in patterns):
                        # Get employee name by GUID
                        emp_ref = entry.get('employeeReference', {})
                        emp_guid = emp_ref.get('guid', '')
                        name = get_employee_name_by_guid(emp_guid)
                        if name and name.lower() not in {
                            'am bar',
                            'sunset bar',
                            'low bar',
                            'low',
                            'ww bar',
                            'ew bar',
                        }:
                            bartenders.append(name)
                except (json.JSONDecodeError, Exception):
                    continue
    except Exception as e:
        print(f"Error getting bartenders from JAQ: {e}")
    
    # Calculate net_sales from category_totals (sum of selection prices)
    # This matches the original app which uses pre-tax selection prices
    net_sales_from_categories = sum(category_totals.values())
    
    result['cash_tips'] = round(cash_tip_sum, 2)
    result['credit_card_tips'] = round(credit_tip_sum, 2)
    result['net_sales'] = round(net_sales_from_categories, 2)
    result['servertips'] = round(sum(sv_break.values()), 2)
    result['expotips'] = round(sum(ex_break.values()), 2)
    result['runnertips'] = round(sum(rn_break.values()), 2)
    result['category_totals'] = {k: round(v, 2) for k, v in category_totals.items() if v > 0}
    result['category_tip_breakdown'] = {
        'servertips': {k: round(v, 2) for k, v in sv_break.items() if v > 0},
        'expotips': {k: round(v, 2) for k, v in ex_break.items() if v > 0},
        'runnertips': {k: round(v, 2) for k, v in rn_break.items() if v > 0}
    }
    result['bartenders'] = sorted(set(bartenders))
    
    return result


@app.route('/api/bartender-defaults', methods=['GET'])
def get_bartender_defaults():
    """Get suggested defaults for bartender-tips by date and bar bucket.
    
    Query params:
    - date: YYYY-MM-DD
    - bucket: am_bar, sunset, westwing, eastwing
    """
    date_str = request.args.get('date', '').strip()
    bucket = request.args.get('bucket', '').strip()
    
    if not date_str or not bucket:
        return jsonify({"error": "Date and bucket required"}), 400
    
    result = calculate_bartender_defaults(date_str, bucket)

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT *
            FROM bartender_tip_overrides
            WHERE business_date = ? AND bucket = ?
            ORDER BY id DESC
            LIMIT 1
        """, (date_str, bucket))
        row = cursor.fetchone()
        if row:
            result['cash_tips'] = float(row['cash_tips'] or 0)
            result['credit_card_tips'] = float(row['credit_tips'] or 0)
            result['net_sales'] = float(row['net_sales'] or 0)
            result['servertips'] = float(row['busser_tips'] or 0)
            result['expotips'] = float(row['expo_tips'] or 0)
            result['runnertips'] = float(row['runner_tips'] or 0)
            result['existing_override'] = {
                'id': row['id'],
                'cash_tips': float(row['cash_tips'] or 0),
                'credit_tips': float(row['credit_tips'] or 0),
                'net_sales': float(row['net_sales'] or 0),
                'busser_tips': float(row['busser_tips'] or 0),
                'expo_tips': float(row['expo_tips'] or 0),
                'runner_tips': float(row['runner_tips'] or 0),
                'is_override': True
            }
    finally:
        conn.close()

    return jsonify(result)


@app.route('/api/bartender-defaults', methods=['POST'])
def save_bartender_defaults_override():
    """Save aggregate bartender override values for a date/bucket."""
    data = request.json or {}
    date_str = (data.get('date') or '').strip()
    bucket = (data.get('bucket') or '').strip()

    if not date_str or not bucket:
        return jsonify({"error": "Date and bucket required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    row_id = upsert_bartender_tip_override(cursor, date_str, bucket, {
        'cash_tips': data.get('cash_tips', 0),
        'credit_tips': data.get('credit_tips', 0),
        'net_sales': data.get('net_sales', 0),
        'busser_tips': data.get('busser_tips', 0),
        'expo_tips': data.get('expo_tips', 0),
        'runner_tips': data.get('runner_tips', 0),
    })
    conn.commit()
    conn.close()

    return jsonify({"success": True, "id": row_id})


@app.route('/api/bartenders/for-bucket-date', methods=['GET'])
def get_bartenders_for_bucket_date():
    """Get bartenders who worked at a specific bar on a date.
    
    Query params:
    - date: YYYY-MM-DD
    - bucket: am_bar, sunset, westwing, eastwing
    """
    date_str = request.args.get('date', '').strip()
    bucket = request.args.get('bucket', '').strip()
    
    if not date_str or not bucket:
        return jsonify({"error": "Date and bucket required"}), 400
    
    defaults = calculate_bartender_defaults(date_str, bucket)
    return jsonify({
        "bartenders": defaults.get('bartenders', []),
        "date": date_str,
        "bucket": bucket
    })


@app.route('/api/bartender/pushed-list', methods=['GET'])
def get_bartender_pushed_list():
    """Get list of bartenders who have pushed tips for a date/bucket.
    
    Query params:
    - date: YYYY-MM-DD
    - bucket: am_bar, sunset, westwing, eastwing
    - include_committed: 1 to include committed payouts (default: 0)
    """
    date_str = request.args.get('date', '').strip()
    bucket = request.args.get('bucket', '').strip()
    include_committed = request.args.get('include_committed', '0') == '1'
    
    if not date_str or not bucket:
        return jsonify({"error": "Date and bucket required"}), 400
    
    names = set()
    valid_bartenders = set()
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Build whitelist of actual bartenders for this bucket/date.
        # 1) Workers detected from labor data for this bar/date.
        try:
            defaults = calculate_bartender_defaults(date_str, bucket)
            for b in (defaults.get('bartenders') or []):
                if b:
                    valid_bartenders.add(b.strip())
        except Exception:
            pass

        # 2) Persisted bartender entries in bartenders table for this bar/date.
        cursor.execute("""
            SELECT DISTINCT bartender
            FROM bartenders
            WHERE date = ? AND bar_name = ?
        """, (date_str, bucket))
        for (bname,) in cursor.fetchall():
            if bname:
                valid_bartenders.add(bname.strip())

        # Exclude placeholder/location pseudo-workers.
        placeholder_names = {'am bar', 'sunset bar', 'low bar', 'low', 'ww bar', 'ew bar'}

        # Get unpaid pushed rows from transactions
        cursor.execute("""
            SELECT DISTINCT worker_name FROM transactions 
            WHERE business_date = ? AND bucket = ? 
            AND (bartips > 0 OR servertips > 0 OR expotips > 0 OR runnertips > 0)
        """, (date_str, bucket))
        
        for (w,) in cursor.fetchall():
            ws = (w or '').strip()
            if ws and ws.lower() not in placeholder_names and ws in valid_bartenders:
                names.add(ws)
        
        # Also check payouts table for unpaid entries
        cursor.execute("""
            SELECT DISTINCT worker_name FROM payouts 
            WHERE business_date = ? AND bucket = ? AND payout_session_id IS NULL
        """, (date_str, bucket))
        
        for (w,) in cursor.fetchall():
            ws = (w or '').strip()
            if ws and ws.lower() not in placeholder_names and ws in valid_bartenders:
                names.add(ws)
        
        if include_committed:
            # Include committed payouts
            cursor.execute("""
                SELECT DISTINCT worker_name FROM payouts 
                WHERE business_date = ? AND bucket = ? AND payout_session_id IS NOT NULL
            """, (date_str, bucket))
            
            for (w,) in cursor.fetchall():
                ws = (w or '').strip()
                if ws and ws.lower() not in placeholder_names and ws in valid_bartenders:
                    names.add(ws)
    
    except Exception as e:
        print(f"Error getting pushed list: {e}")
    finally:
        conn.close()
    
    return jsonify({
        "workers": sorted(names),
        "date": date_str,
        "bucket": bucket
    })


@app.route('/api/bartender/status', methods=['GET'])
def get_bartender_status():
    """Get push/commit status for a bartender on a date/bucket.
    
    Query params:
    - bartender: bartender name
    - bucket: am_bar, sunset, westwing, eastwing
    - date: YYYY-MM-DD
    """
    bartender = request.args.get('bartender', '').strip()
    bucket = request.args.get('bucket', '').strip()
    date_str = request.args.get('date', '').strip()
    
    if not bartender or not bucket or not date_str:
        return jsonify({"error": "Bartender, bucket, and date required"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    result = {
        "bartender": bartender,
        "bucket": bucket,
        "date": date_str,
        "pushed": {"Busser": 0.0, "Expo": 0.0, "Runner": 0.0},
        "committed": {"Busser": 0.0, "Expo": 0.0, "Runner": 0.0},
        "pushed_count": 0
    }
    
    try:
        # Get unpaid pushed amounts from payouts (where payout_session_id IS NULL)
        cursor.execute("""
            SELECT 
                payout_destination,
                COALESCE(SUM(amount), 0) as total
            FROM payouts 
            WHERE worker_name = ? AND business_date = ? AND bucket = ? AND payout_session_id IS NULL
            GROUP BY payout_destination
        """, (bartender, date_str, bucket))
        
        for row in cursor.fetchall():
            dest = row['payout_destination']
            if dest in result['pushed']:
                result['pushed'][dest] = float(row['total'] or 0)
        
        # Count distinct push records (for info)
        cursor.execute("""
            SELECT COUNT(*) as cnt
            FROM payouts 
            WHERE worker_name = ? AND business_date = ? AND bucket = ? AND payout_session_id IS NULL
        """, (bartender, date_str, bucket))
        
        count_row = cursor.fetchone()
        result['pushed_count'] = count_row['cnt'] or 0 if count_row else 0
        
        # Get committed amounts from payouts
        cursor.execute("""
            SELECT payout_destination, COALESCE(SUM(amount), 0) as total
            FROM payouts 
            WHERE worker_name = ? AND business_date = ? AND bucket = ? AND payout_session_id IS NOT NULL
            GROUP BY payout_destination
        """, (bartender, date_str, bucket))
        
        for row in cursor.fetchall():
            dest = row['payout_destination']
            if dest in result['committed']:
                result['committed'][dest] = float(row['total'] or 0)
    
    except Exception as e:
        print(f"Error getting bartender status: {e}")
    finally:
        conn.close()
    
    return jsonify(result)


@app.route('/api/bartender/push', methods=['POST'])
def push_bartender_tips():
    """Push bartender tips to payouts (creates unpaid payout records).
    
    Request body:
    - bartender: bartender name
    - date: YYYY-MM-DD
    - bucket: am_bar, sunset, westwing, eastwing
    - bussertips: amount for busser payout
    - expotips: amount for expo payout
    - runnertips: amount for runner payout
    - per_cash: per-bartender cash tips (stored for reference)
    - per_credit: per-bartender credit tips (stored for reference)
    - per_net: per-bartender net sales (stored for reference)
    """
    data = request.json or {}
    
    bartender = data.get('bartender', '').strip()
    date_str = data.get('date', '').strip()
    bucket = data.get('bucket', '').strip()
    
    if not bartender or not date_str or not bucket:
        return jsonify({"error": "Bartender, date, and bucket required"}), 400
    
    bussertips = float(data.get('bussertips') or data.get('busser_tips') or 0)
    expotips = float(data.get('expotips') or data.get('expo_tips') or 0)
    runnertips = float(data.get('runnertips') or data.get('runner_tips') or 0)
    per_cash = float(data.get('per_cash') or 0)
    per_credit = float(data.get('per_credit') or 0)
    per_net = float(data.get('per_net') or 0)
    total_cash = float(data.get('total_cash') or per_cash)
    total_credit = float(data.get('total_credit') or per_credit)
    total_net = float(data.get('total_net') or per_net)
    total_busser = float(data.get('total_busser') or bussertips)
    total_expo = float(data.get('total_expo') or expotips)
    total_runner = float(data.get('total_runner') or runnertips)
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Ensure worker exists
        cursor.execute("INSERT OR IGNORE INTO workers (name) VALUES (?)", (bartender,))

        upsert_bartender_tip_override(cursor, date_str, bucket, {
            'cash_tips': total_cash,
            'credit_tips': total_credit,
            'net_sales': total_net,
            'busser_tips': total_busser,
            'expo_tips': total_expo,
            'runner_tips': total_runner,
        })

        # Replace any existing unpaid bartender push state for this bartender/date/bucket
        # so repeated pushes from cached clients do not stack duplicate rows.
        cursor.execute("""
            DELETE FROM payouts
            WHERE worker_name = ? AND business_date = ? AND bucket = ? AND payout_session_id IS NULL
        """, (bartender, date_str, bucket))
        cursor.execute("""
            DELETE FROM bartenders
            WHERE bartender = ? AND date = ? AND bar_name = ?
        """, (bartender, date_str, bucket))
        
        # Insert into payouts table with NULL payout_session_id (unpaid)
        # Insert all amounts (including 0) so the breakdown shows complete info
        for dest, amount in [
            ('Bartender', 0),  # Bartenders don't pay themselves
            ('Busser', bussertips),
            ('Expo', expotips),
            ('Runner', runnertips)
        ]:
            cursor.execute("""
                INSERT INTO payouts 
                (business_date, worker_name, bucket, payout_destination, amount, payout_session_id)
                VALUES (?, ?, ?, ?, ?, NULL)
            """, (date_str, bartender, bucket, dest, amount))
        
        # Also insert into bartenders table to record the main figures for reference
        # This allows tracking per-bartender cash/credit/net even though we only push busser/expo/runner
        try:
            if per_cash > 0 or per_credit > 0 or per_net > 0:
                tip_pct = f"Gross Tip %: {(((per_cash + per_credit) / per_net) * 100.0):.2f}%" if per_net > 0 else "Gross Tip %: 0.00%"
                cursor.execute("""
                    INSERT INTO bartenders 
                    (date, bartender, bar_name, cash_tips, credit_tips, net_sales, sum_tips_for_payout, tipped_perc_of_net_sales)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    date_str,
                    bartender,
                    bucket,
                    per_cash,
                    per_credit,
                    per_net,
                    round(bussertips + expotips + runnertips, 2),
                    tip_pct
                ))
        except Exception as e:
            # Don't fail the push if summary persistence fails
            print(f"Warning: Failed to save bartender summary: {e}")
        
        conn.commit()
        
        return jsonify({
            "success": True,
            "message": f"Pushed tips for {bartender}",
            "bussertips": bussertips,
            "expotips": expotips,
            "runnertips": runnertips
        })
    
    except Exception as e:
        conn.rollback()
        print(f"Error pushing bartender tips: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/bartender/undo', methods=['POST'])
def undo_bartender_tips():
    """Undo pushed bartender tips (removes unpaid transaction records).
    
    Request body:
    - bartender: bartender name
    - date: YYYY-MM-DD
    - bucket: am_bar, sunset, westwing, eastwing
    """
    data = request.json or {}
    
    bartender = data.get('bartender', '').strip()
    date_str = data.get('date', '').strip()
    bucket = data.get('bucket', '').strip()
    
    if not bartender or not date_str or not bucket:
        return jsonify({"error": "Bartender, date, and bucket required"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Remove from transactions (unpushed)
        cursor.execute("""
            DELETE FROM transactions 
            WHERE worker_name = ? AND business_date = ? AND bucket = ?
        """, (bartender, date_str, bucket))
        
        trans_deleted = cursor.rowcount
        
        # Remove from payouts (uncommitted)
        cursor.execute("""
            DELETE FROM payouts 
            WHERE worker_name = ? AND business_date = ? AND bucket = ? AND payout_session_id IS NULL
        """, (bartender, date_str, bucket))
        
        payouts_deleted = cursor.rowcount

        # Remove persisted bartender summary rows so worker-report no longer shows
        # unpushed bartender entries.
        cursor.execute("""
            DELETE FROM bartenders
            WHERE bartender = ? AND date = ? AND bar_name = ?
        """, (bartender, date_str, bucket))
        bartender_rows_deleted = cursor.rowcount

        cursor.execute("""
            DELETE FROM bartender_tip_overrides
            WHERE business_date = ? AND bucket = ?
        """, (date_str, bucket))
        override_rows_deleted = cursor.rowcount
        
        conn.commit()
        
        if trans_deleted > 0 or payouts_deleted > 0 or bartender_rows_deleted > 0 or override_rows_deleted > 0:
            return jsonify({
                "success": True,
                "message": f"Undo successful for {bartender}",
                "transactions_removed": trans_deleted,
                "payouts_removed": payouts_deleted,
                "bartender_rows_removed": bartender_rows_deleted,
                "override_rows_removed": override_rows_deleted
            })
        else:
            return jsonify({
                "success": False,
                "message": "No pushed tips found to undo"
            })
    
    except Exception as e:
        conn.rollback()
        print(f"Error undoing bartender tips: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ====================
# PAYOUTS API
# ====================

@app.route('/api/payouts/unpaid', methods=['GET'])
def get_unpaid_payouts():
    """Get unpaid totals by destination for a bucket/date.
    
    Combines data from:
    - payouts table (for bartender tips and committed payouts)
    - transactions table (for server tips that were pushed)
    """
    bucket = request.args.get('bucket')
    date = request.args.get('date')
    
    if not bucket or not date:
        return jsonify({"error": "Bucket and date required"}), 400
    
    conn = get_db()
    cursor = conn.cursor()

    # If payouts were already committed for this bucket/date, only treat rows
    # created after the latest commit as "unpaid" (new pushes after commit).
    cursor.execute("""
        SELECT MAX(created_at) AS latest_commit_ts
        FROM payout_sessions
        WHERE bucket = ? AND business_date = ?
    """, (bucket, date))
    latest_commit_row = cursor.fetchone()
    latest_commit_ts = latest_commit_row['latest_commit_ts'] if latest_commit_row else None
    
    # Get unpaid amounts from payouts (where payout_session_id IS NULL)
    cursor.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN payout_destination = 'Bartender' THEN amount ELSE 0 END), 0) as bartender,
            COALESCE(SUM(CASE WHEN payout_destination = 'Busser' THEN amount ELSE 0 END), 0) as busser,
            COALESCE(SUM(CASE WHEN payout_destination = 'Expo' THEN amount ELSE 0 END), 0) as expo,
            COALESCE(SUM(CASE WHEN payout_destination = 'Runner' THEN amount ELSE 0 END), 0) as runner
        FROM payouts 
        WHERE bucket = ? AND business_date = ? AND payout_session_id IS NULL
          AND (? IS NULL OR timestamp > ?)
    """, (bucket, date, latest_commit_ts, latest_commit_ts))
    
    row = cursor.fetchone()
    payout_bartender = float(row['bartender'] or 0)
    payout_busser = float(row['busser'] or 0)
    payout_expo = float(row['expo'] or 0)
    payout_runner = float(row['runner'] or 0)
    
    # Get unpaid amounts from transactions (server tips pushed but not yet in payouts)
    # First try to get breakdown tips (bartips, servertips, etc.)
    cursor.execute("""
        SELECT 
            COALESCE(SUM(bartips), 0) as bartender,
            COALESCE(SUM(servertips), 0) as busser,
            COALESCE(SUM(expotips), 0) as expo,
            COALESCE(SUM(runnertips), 0) as runner,
            COALESCE(SUM(creditcardtip), 0) as total_credit,
            COALESCE(SUM(cashtips), 0) as total_cash
        FROM transactions 
        WHERE bucket = ? AND business_date = ?
          AND (? IS NULL OR timestamp > ?)
    """, (bucket, date, latest_commit_ts, latest_commit_ts))
    
    trans_row = cursor.fetchone()
    trans_bartender = float(trans_row['bartender'] or 0)
    trans_busser = float(trans_row['busser'] or 0)
    trans_expo = float(trans_row['expo'] or 0)
    trans_runner = float(trans_row['runner'] or 0)
    total_credit = float(trans_row['total_credit'] or 0)
    total_cash = float(trans_row['total_cash'] or 0)
    
    # If no breakdown tips but there are credit/cash tips, put them in busser (server tips) category
    total_breakdown = trans_bartender + trans_busser + trans_expo + trans_runner
    if total_breakdown == 0 and (total_credit > 0 or total_cash > 0):
        # Default to busser (server tips) when no breakdown is provided
        trans_busser = total_credit + total_cash
    
    # Get committed payouts (where payout_session_id IS NOT NULL)
    cursor.execute("""
        SELECT payout_destination, COALESCE(SUM(amount), 0) as total
        FROM payouts 
        WHERE bucket = ? AND business_date = ? AND payout_session_id IS NOT NULL
        GROUP BY payout_destination
    """, (bucket, date))
    
    committed = {row['payout_destination']: row['total'] for row in cursor.fetchall()}
    conn.close()
    
    # Use payouts if they exist (calculated from check splits), otherwise use transactions
    # Payouts represent the actual distribution based on per-check category data
    total_payouts = payout_bartender + payout_busser + payout_expo + payout_runner
    if total_payouts > 0:
        unpaid = {
            "Bartender": payout_bartender,
            "Busser": payout_busser,
            "Expo": payout_expo,
            "Runner": payout_runner
        }
    else:
        # Fall back to transaction totals if no payouts calculated yet
        unpaid = {
            "Bartender": trans_bartender,
            "Busser": trans_busser,
            "Expo": trans_expo,
            "Runner": trans_runner
        }
    
    return jsonify({
        "unpaid": unpaid,
        "committed": {
            "Bartender": float(committed.get('Bartender', 0)),
            "Busser": float(committed.get('Busser', 0)),
            "Expo": float(committed.get('Expo', 0)),
            "Runner": float(committed.get('Runner', 0))
        }
    })

@app.route('/api/payouts/assignments', methods=['GET'])
def get_payout_assignments():
    """Get worker assignments for a bucket."""
    bucket = request.args.get('bucket')
    
    if not bucket:
        return jsonify({"error": "Bucket required"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT payout_destination, worker_name 
        FROM worker_assignments 
        WHERE bucket = ?
        ORDER BY payout_destination, worker_name
    """, (bucket,))
    
    assignments = {}
    for row in cursor.fetchall():
        dest = row['payout_destination']
        if dest not in assignments:
            assignments[dest] = []
        assignments[dest].append(row['worker_name'])
    
    conn.close()
    return jsonify(assignments)

@app.route('/api/payouts/assignments', methods=['POST'])
def save_payout_assignments():
    """Save worker assignments for payouts."""
    data = request.json
    bucket = data.get('bucket')
    assignments = data.get('assignments', {})
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Clear existing assignments for this bucket
    cursor.execute("DELETE FROM worker_assignments WHERE bucket = ?", (bucket,))
    
    # Insert new assignments
    for destination, workers in assignments.items():
        for worker in workers:
            cursor.execute("""
                INSERT INTO worker_assignments (bucket, payout_destination, worker_name)
                VALUES (?, ?, ?)
            """, (bucket, destination, worker))
    
    conn.commit()
    conn.close()
    
    return jsonify({"success": True})


def load_job_map():
    """Load job GUID to title mapping from JAQ datalake."""
    try:
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        
        response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_jobs.json',
            'limit': '1000'
        })
        
        job_map = {}
        if response.status_code == 200:
            for item in response.json():
                try:
                    job = json.loads(item.get('json_data', '{}'))
                    guid = job.get('guid')
                    title = job.get('title') or job.get('name')
                    if guid and title:
                        job_map[guid] = title
                except:
                    continue
        return job_map
    except Exception:
        return {}


def load_employees_with_job_titles():
    """Load employees and their job titles from JAQ datalake."""
    try:
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        
        # Get jobs to map GUIDs to titles
        job_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_jobs.json',
            'limit': '1000'
        })
        
        job_map = {}
        if job_response.status_code == 200:
            for item in job_response.json():
                try:
                    job = json.loads(item.get('json_data', '{}'))
                    guid = job.get('guid')
                    title = job.get('title', '')
                    if guid and title:
                        job_map[guid] = title
                except:
                    continue
        
        # Get employees from JAQ
        emp_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_employees.json',
            'limit': '1000'
        })
        
        employees = {}
        if emp_response.status_code == 200:
            for item in emp_response.json():
                try:
                    emp = json.loads(item.get('json_data', '{}'))
                    
                    if emp.get('deleted') is True:
                        continue
                    
                    first = (emp.get('firstName') or '').strip()
                    last = (emp.get('lastName') or '').strip()
                    full = (first + (' ' + last if last else '')).strip()
                    if not full:
                        continue
                    
                    # Check job references
                    has_busser = False
                    has_bar = False
                    has_expo = False
                    has_runner = False
                    
                    for ref in emp.get('jobReferences', []):
                        guid = ref.get('guid') if ref else None
                        title = job_map.get(guid, '') if guid else ''
                        if title:
                            ttl = title.lower()
                            if 'busser' in ttl:
                                has_busser = True
                            if 'bar' in ttl:
                                has_bar = True
                            if 'expo' in ttl:
                                has_expo = True
                                has_runner = True  # Expo also counts for Runner
                            if 'runner' in ttl:
                                has_runner = True
                    
                    employees[full] = {
                        'busser': has_busser,
                        'bar': has_bar,
                        'expo': has_expo,
                        'runner': has_runner
                    }
                except:
                    continue
        
        return employees
    except Exception as e:
        print(f"Error loading employees from JAQ: {e}")
        return {}


def get_workers_for_date(business_date, job_title_filter=None):
    """Get workers who worked on a specific date with optional job title filter."""
    workers = set()
    try:
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        
        # Get employees to map GUIDs to names
        emp_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_employees.json',
            'limit': '1000'
        })
        
        employees = {}
        if emp_response.status_code == 200:
            for item in emp_response.json():
                try:
                    emp = json.loads(item.get('json_data', '{}'))
                    guid = emp.get('guid') or emp.get('v2EmployeeGuid')
                    first = emp.get('firstName', '')
                    last = emp.get('lastName', '')
                    name = " ".join(f"{first} {last}".split())
                    if guid and name:
                        employees[guid] = name
                except:
                    continue
        
        # Get jobs to map job GUIDs to titles
        job_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_jobs.json',
            'limit': '1000'
        })
        
        jobs = {}
        if job_response.status_code == 200:
            for item in job_response.json():
                try:
                    job = json.loads(item.get('json_data', '{}'))
                    guid = job.get('guid')
                    title = job.get('title', '')
                    if guid and title:
                        jobs[guid] = title
                except:
                    continue
        
        # Get time entries for the date
        toast_date = business_date.replace('-', '')
        time_file = f"labor_v1_timeEntries_{toast_date}.json"
        time_response = requests.get(f"{jaq_url}/query", params={
            'source_file': time_file,
            'limit': '10000'
        })
        
        if time_response.status_code == 200:
            for item in time_response.json():
                try:
                    entry = json.loads(item.get('json_data', '{}'))
                    
                    if entry.get('businessDate') != toast_date:
                        continue
                    
                    emp_ref = entry.get('employeeReference', {})
                    emp_guid = emp_ref.get('guid')
                    
                    if not emp_guid or emp_guid not in employees:
                        continue
                    
                    name = employees[emp_guid]
                    
                    if job_title_filter:
                        job_ref = entry.get('jobReference', {})
                        job_guid = job_ref.get('guid')
                        job_title = jobs.get(job_guid, '').lower()
                        if job_title_filter in job_title:
                            workers.add(name)
                    else:
                        workers.add(name)
                        
                except:
                    continue
                    
    except Exception as e:
        print(f"Error reading shifts from JAQ: {e}")
    return workers


def _load_employee_guid_to_name_map() -> Dict[str, str]:
    """Load employee guid->legal name map from JAQ."""
    names: Dict[str, str] = {}
    try:
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        emp_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_employees.json',
            'limit': '5000'
        }, timeout=30)
        if emp_response.status_code == 200:
            for item in emp_response.json():
                try:
                    emp = json.loads(item.get('json_data', '{}'))
                    first = (emp.get('firstName') or '').strip()
                    last = (emp.get('lastName') or '').strip()
                    name = " ".join(f"{first} {last}".split())
                    if not name:
                        continue
                    for key in ('guid', 'id', 'v2EmployeeGuid'):
                        guid = (emp.get(key) or '').strip()
                        if guid:
                            names[guid] = name
                except Exception:
                    continue
    except Exception as e:
        print(f"Error loading employee guid map: {e}")
    return names


def _load_job_guid_to_title_map() -> Dict[str, str]:
    """Load job guid->title map from JAQ."""
    jobs: Dict[str, str] = {}
    try:
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        job_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_jobs.json',
            'limit': '5000'
        }, timeout=30)
        if job_response.status_code == 200:
            for item in job_response.json():
                try:
                    job = json.loads(item.get('json_data', '{}'))
                    guid = (job.get('guid') or '').strip()
                    title = (job.get('title') or '').strip()
                    if guid and title:
                        jobs[guid] = title
                except Exception:
                    continue
    except Exception as e:
        print(f"Error loading job guid map: {e}")
    return jobs


def _role_match_for_title(dest: str, job_title: str, bucket: str) -> bool:
    """Check if a job title contributes hours for a payout destination."""
    ttl = (job_title or '').strip().lower()
    if not ttl:
        return False

    if dest == 'Bartender':
        bar_bucket = job_title_to_bar_bucket(job_title)
        if bar_bucket:
            return (not bucket) or (bar_bucket == bucket)
        return False

    if dest == 'Busser':
        return 'busser' in ttl

    # Keep Expo/Runner aligned with existing assignment behavior where
    # expo/runner shifts are effectively interchangeable.
    if dest in ('Expo', 'Runner'):
        return ('expo' in ttl) or ('runner' in ttl)

    return False


def _load_role_correction_map(date_str: str, bucket: str) -> Dict[str, str]:
    """Load worker->corrected_role map for a date/bucket."""
    mp: Dict[str, str] = {}
    if not date_str:
        return mp
    conn = get_db()
    cursor = conn.cursor()
    try:
        # bucket-specific entries take precedence over global ('')
        cursor.execute("""
            SELECT worker_name, corrected_role, bucket
            FROM payout_role_corrections
            WHERE business_date = ? AND (bucket = ? OR bucket = '')
            ORDER BY CASE WHEN bucket = ? THEN 1 ELSE 0 END DESC, updated_at DESC
        """, (date_str, bucket or '', bucket or ''))
        for row in cursor.fetchall():
            worker = (row['worker_name'] or '').strip()
            role = (row['corrected_role'] or '').strip()
            if worker and role and worker not in mp:
                mp[worker] = role
    finally:
        conn.close()
    return mp


def _role_match_with_override(dest: str, job_title: str, bucket: str, corrected_role: str) -> bool:
    """Match destination with optional explicit corrected role."""
    role = (corrected_role or '').strip().lower()
    if not role:
        return _role_match_for_title(dest, job_title, bucket)
    if role == 'bartender':
        return dest == 'Bartender'
    if role == 'busser':
        return dest == 'Busser'
    if role in ('expo', 'runner'):
        # Keep Expo/Runner coupled to existing behavior.
        return dest in ('Expo', 'Runner')
    return _role_match_for_title(dest, job_title, bucket)


@app.route('/api/payouts/role-corrections', methods=['GET'])
def get_payout_role_corrections():
    """Get saved role corrections for a date/bucket."""
    date_str = (request.args.get('date') or '').strip()
    bucket = (request.args.get('bucket') or '').strip()
    if not date_str:
        return jsonify({"error": "Date required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT worker_name, business_date, bucket, corrected_role, updated_at
            FROM payout_role_corrections
            WHERE business_date = ? AND (bucket = ? OR bucket = '')
            ORDER BY worker_name
        """, (date_str, bucket))
        rows = [{
            "worker": r["worker_name"],
            "date": r["business_date"],
            "bucket": r["bucket"],
            "corrected_role": r["corrected_role"],
            "updated_at": r["updated_at"],
        } for r in cursor.fetchall()]
    finally:
        conn.close()
    return jsonify({"date": date_str, "bucket": bucket, "corrections": rows})


@app.route('/api/payouts/role-corrections', methods=['POST'])
def save_payout_role_correction():
    """Save role correction for worker/date/bucket."""
    data = request.json or {}
    worker = (data.get('worker') or '').strip()
    date_str = (data.get('date') or '').strip()
    bucket = (data.get('bucket') or '').strip()
    role = (data.get('corrected_role') or '').strip()
    valid_roles = {'Bartender', 'Busser', 'Expo', 'Runner'}
    if not worker or not date_str or role not in valid_roles:
        return jsonify({"error": "Worker, date, and valid corrected_role required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO payout_role_corrections (worker_name, business_date, bucket, corrected_role, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(worker_name, business_date, bucket) DO UPDATE SET
                corrected_role = excluded.corrected_role,
                updated_at = CURRENT_TIMESTAMP
        """, (worker, date_str, bucket, role))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"success": True})


@app.route('/api/payouts/role-corrections', methods=['DELETE'])
def delete_payout_role_correction():
    """Delete role correction for worker/date/bucket."""
    worker = (request.args.get('worker') or '').strip()
    date_str = (request.args.get('date') or '').strip()
    bucket = (request.args.get('bucket') or '').strip()
    if not worker or not date_str:
        return jsonify({"error": "Worker and date required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            DELETE FROM payout_role_corrections
            WHERE worker_name = ? AND business_date = ? AND bucket = ?
        """, (worker, date_str, bucket))
        deleted = cursor.rowcount
        conn.commit()
    finally:
        conn.close()
    return jsonify({"success": True, "deleted": deleted})


@app.route('/api/payouts/role-hours', methods=['POST'])
def get_payout_role_hours():
    """Get worked hours per destination for selected workers on a date.

    Request JSON:
    - date: YYYY-MM-DD
    - bucket: optional location bucket
    - assignments: {Bartender:[...], Busser:[...], Expo:[...], Runner:[...]}
    """
    data = request.json or {}
    date_str = (data.get('date') or '').strip()
    bucket = (data.get('bucket') or '').strip()
    assignments = data.get('assignments') or {}

    if not date_str:
        return jsonify({"error": "Date required"}), 400

    toast_date = date_str.replace('-', '')
    wanted_dests = ['Bartender', 'Busser', 'Expo', 'Runner']
    hours_by_dest: Dict[str, Dict[str, float]] = {d: {} for d in wanted_dests}

    # Build selected worker sets per destination (legal-name matching)
    selected_sets: Dict[str, Set[str]] = {}
    for dest in wanted_dests:
        selected_sets[dest] = set((assignments.get(dest) or []))

    try:
        name_by_guid = _load_employee_guid_to_name_map()
        job_by_guid = _load_job_guid_to_title_map()
        role_corrections = _load_role_correction_map(date_str, bucket)

        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        time_file = f"labor_v1_timeEntries_{toast_date}.json"
        time_response = requests.get(f"{jaq_url}/query", params={
            'source_file': time_file,
            'limit': '20000'
        }, timeout=30)

        if time_response.status_code != 200:
            return jsonify({"hours": hours_by_dest, "date": date_str, "bucket": bucket})

        for item in time_response.json():
            try:
                entry = json.loads(item.get('json_data', '{}'))
                if entry.get('businessDate') != toast_date:
                    continue

                emp_ref = entry.get('employeeReference', {}) or {}
                emp_guid = (emp_ref.get('guid') or '').strip()
                worker_name = name_by_guid.get(emp_guid)
                if not worker_name:
                    continue

                job_ref = entry.get('jobReference', {}) or {}
                job_guid = (job_ref.get('guid') or '').strip()
                job_title = job_by_guid.get(job_guid, '')

                # Prefer Toast-provided regularHours, fallback to clock diff for open/incomplete entries.
                regular_hours = float(entry.get('regularHours') or 0.0)
                hours = regular_hours
                if hours <= 0:
                    start = parse_toast_datetime(entry.get('inDate') or '')
                    end = parse_toast_datetime(entry.get('outDate') or '') or datetime.now(timezone.utc)
                    if start and end and end > start:
                        hours = (end - start).total_seconds() / 3600.0

                if hours <= 0:
                    continue

                for dest in wanted_dests:
                    if worker_name not in selected_sets[dest]:
                        continue
                    corrected_role = role_corrections.get(worker_name, '')
                    if _role_match_with_override(dest, job_title, bucket, corrected_role):
                        hours_by_dest[dest][worker_name] = hours_by_dest[dest].get(worker_name, 0.0) + hours
            except Exception:
                continue

        # Ensure selected workers are always present with at least 0 for deterministic UI handling
        for dest in wanted_dests:
            for worker in selected_sets[dest]:
                hours_by_dest[dest].setdefault(worker, 0.0)

        # Round for stable display/weighting
        for dest in wanted_dests:
            for worker in list(hours_by_dest[dest].keys()):
                hours_by_dest[dest][worker] = round(float(hours_by_dest[dest][worker] or 0.0), 4)

    except Exception as e:
        print(f"Error calculating payout role hours: {e}")

    return jsonify({
        "date": date_str,
        "bucket": bucket,
        "hours": hours_by_dest
    })


def get_bar_workers_for_date(business_date, bucket):
    """Get bartenders who worked at a specific bar on a date."""
    title_map = {
        # Bar-role detection for payouts should include only bar job titles.
        'westwing': ['WW Bar', 'West Wing Bar'],
        'am_bar': ['AM Bar', 'AM Bar Sunset'],
        'sunset': ['PM Bar', 'PM Bar Sunset', 'Sunset Bar', 'Low Bar'],
        'eastwing': ['EW Bar', 'Eastwing Bar'],
    }
    wanted_titles = title_map.get(bucket, [])
    if not wanted_titles:
        return set()
    
    workers = set()
    try:
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        
        # Get employees to map GUIDs to names
        emp_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_employees.json',
            'limit': '1000'
        })
        
        employees = {}
        if emp_response.status_code == 200:
            for item in emp_response.json():
                try:
                    emp = json.loads(item.get('json_data', '{}'))
                    guid = emp.get('guid') or emp.get('v2EmployeeGuid')
                    first = emp.get('firstName', '')
                    last = emp.get('lastName', '')
                    name = " ".join(f"{first} {last}".split())
                    if guid and name:
                        employees[guid] = name
                except:
                    continue
        
        # Get jobs to map job GUIDs to titles
        job_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_jobs.json',
            'limit': '1000'
        })
        
        jobs = {}
        if job_response.status_code == 200:
            for item in job_response.json():
                try:
                    job = json.loads(item.get('json_data', '{}'))
                    guid = job.get('guid')
                    title = job.get('title', '')
                    if guid and title:
                        jobs[guid] = title
                except:
                    continue
        
        # Get time entries for the date
        toast_date = business_date.replace('-', '')
        time_file = f"labor_v1_timeEntries_{toast_date}.json"
        time_response = requests.get(f"{jaq_url}/query", params={
            'source_file': time_file,
            'limit': '10000'
        })
        
        if time_response.status_code == 200:
            for item in time_response.json():
                try:
                    entry = json.loads(item.get('json_data', '{}'))
                    
                    if entry.get('businessDate') != toast_date:
                        continue
                    
                    emp_ref = entry.get('employeeReference', {})
                    emp_guid = emp_ref.get('guid')
                    
                    if not emp_guid or emp_guid not in employees:
                        continue
                    
                    job_ref = entry.get('jobReference', {})
                    job_guid = job_ref.get('guid')
                    job_title = jobs.get(job_guid, '')
                    
                    name = employees[emp_guid]
                    
                    # Check if job title matches any of the wanted titles
                    for wanted in wanted_titles:
                        if wanted.lower() in job_title.lower():
                            workers.add(name)
                            break
                        
                except:
                    continue
                    
    except Exception as e:
        print(f"Error reading bar shifts from JAQ: {e}")
    return workers


@app.route('/api/payouts/suggested-assignments', methods=['GET'])
def get_suggested_assignments():
    """Get suggested worker assignments based on job titles and date.
    
    Query params:
    - bucket: location bucket
    - date: business date (YYYY-MM-DD)
    - show_all: if 1, show all workers regardless of date (default: 0)
    """
    bucket = request.args.get('bucket', '').strip()
    date = request.args.get('date', '').strip()
    show_all = request.args.get('show_all', '0') == '1'
    
    if not bucket:
        return jsonify({"error": "Bucket required"}), 400
    
    # Load employees with their job titles
    employees = load_employees_with_job_titles()
    
    # Get all worker names
    all_workers = list(employees.keys())
    
    # If date is provided and not show_all, filter to workers who worked that date
    worked_set = set()
    if date and not show_all:
        worked_set = get_workers_for_date(date)
    
    # Get shift sets for date filtering
    busser_shift_set = get_workers_for_date(date, 'busser') if date and not show_all else set()
    expo_shift_set = get_workers_for_date(date, 'expo') if date and not show_all else set()
    runner_shift_set = get_workers_for_date(date, 'runner') if date and not show_all else set()
    
    # Union of Expo and Runner shifts should be included in BOTH assignments
    expo_runner_union = expo_shift_set | runner_shift_set
    
    # Build assignment lists
    bartender_workers = []
    busser_workers = []
    expo_workers = []
    runner_workers = []
    
    for name in all_workers:
        emp = employees.get(name, {})
        
        # Bartender: has bar job and worked that day (or show_all)
        if emp.get('bar'):
            if show_all or not worked_set or name in worked_set:
                bartender_workers.append(name)
        
        # Busser: has busser job and had a busser shift that day
        if emp.get('busser'):
            if show_all:
                busser_workers.append(name)
            elif date and name in busser_shift_set:
                busser_workers.append(name)
        
        # Expo: has expo job AND (show_all OR worked an expo/runner shift that day)
        if emp.get('expo'):
            if show_all:
                expo_workers.append(name)
            elif date and name in expo_runner_union:
                expo_workers.append(name)
        
        # Runner: has runner job AND (show_all OR worked an expo/runner shift that day)
        # Note: In the old app, the UNION of shifts is used for both
        if emp.get('runner') or emp.get('expo'):  # Expo workers also count for Runner
            if show_all:
                runner_workers.append(name)
            elif date and name in expo_runner_union:
                runner_workers.append(name)
    
    # Filter bartenders by specific bar for the bucket
    if date and bucket:
        bar_workers = get_bar_workers_for_date(date, bucket)
        if bar_workers:
            bartender_workers = [w for w in bartender_workers if w in bar_workers]
    
    # Exclude placeholder bar entries
    if not show_all:
        barred = {'am bar', 'ww bar', 'low bar'}
        bartender_workers = [w for w in bartender_workers if w and w.strip().lower() not in barred]
    
    assignments = {
        'Bartender': sorted(bartender_workers),
        'Busser': sorted(busser_workers),
        'Expo': sorted(expo_workers),
        'Runner': sorted(runner_workers)
    }
    
    return jsonify({
        'assignments': assignments,
        'show_all': show_all,
        'date': date,
        'bucket': bucket
    })

@app.route('/api/payouts/preview', methods=['POST'])
def preview_payouts():
    """Preview payout distribution."""
    data = request.json
    bucket = data.get('bucket')
    date = data.get('date')
    amounts = data.get('amounts', {})
    assignments = data.get('assignments', {})
    
    distributions = []
    
    for destination, workers in assignments.items():
        amount = float(amounts.get(destination, 0))
        if workers and amount > 0:
            per_worker = amount / len(workers)
            for worker in workers:
                distributions.append({
                    "worker": worker,
                    "destination": destination,
                    "amount": round(per_worker, 2)
                })
    
    return jsonify({
        "distributions": distributions,
        "total": round(sum(d['amount'] for d in distributions), 2)
    })

@app.route('/api/payouts/commit', methods=['POST'])
def commit_payouts():
    """Commit payouts to database.
    
    This updates the existing unpaid payout records (where payout_session_id IS NULL)
    to mark them as committed by assigning them to a payout session.
    """
    data = request.json
    bucket = data.get('bucket')
    date = data.get('date')
    distributions = data.get('distributions', [])
    
    if not bucket or not date:
        return jsonify({"error": "Bucket and date required"}), 400
    if not isinstance(distributions, list) or len(distributions) == 0:
        return jsonify({"error": "At least one assigned worker is required to commit payouts"}), 400

    valid_destinations = {"Bartender", "Busser", "Expo", "Runner"}
    for dist in distributions:
        worker = (dist.get('worker') or '').strip() if isinstance(dist, dict) else ''
        destination = (dist.get('destination') or '').strip() if isinstance(dist, dict) else ''
        if not worker:
            return jsonify({"error": "Each payout distribution must include a worker"}), 400
        if destination not in valid_destinations:
            return jsonify({"error": f"Invalid payout destination: {destination or 'unknown'}"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Create payout session
        session_id = f"{bucket}_{date}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        cursor.execute("""
            INSERT INTO payout_sessions (id, bucket, business_date)
            VALUES (?, ?, ?)
        """, (session_id, bucket, date))
        
        # For each distribution, update the existing unpaid payout record
        # OR insert a new committed record if no unpaid record exists
        for dist in distributions:
            worker = dist['worker']
            destination = dist['destination']
            amount = dist['amount']
            
            # First, try to find and update an existing unpaid record
            cursor.execute("""
                SELECT id FROM payouts 
                WHERE worker_name = ? AND bucket = ? AND business_date = ? 
                AND payout_destination = ? AND payout_session_id IS NULL
                LIMIT 1
            """, (worker, bucket, date, destination))
            
            existing = cursor.fetchone()
            
            if existing:
                # Update existing record with the session_id
                cursor.execute("""
                    UPDATE payouts 
                    SET payout_session_id = ?, amount = ?
                    WHERE id = ?
                """, (session_id, amount, existing['id']))
            else:
                # Insert new committed record (for cases where there's no unpaid record)
                cursor.execute("""
                    INSERT INTO payouts 
                    (worker_name, amount, bucket, payout_destination, business_date, payout_session_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (worker, amount, bucket, destination, date, session_id))
        
        conn.commit()
        
        return jsonify({"success": True, "session_id": session_id})
        
    except Exception as e:
        conn.rollback()
        print(f"Error committing payouts: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/payouts/committed', methods=['GET'])
def get_committed_payouts():
    """Get committed payouts for a bucket/date."""
    bucket = request.args.get('bucket')
    date = request.args.get('date')
    
    if not bucket or not date:
        return jsonify({"error": "Bucket and date required"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT p.*, ps.created_at
        FROM payouts p
        JOIN payout_sessions ps ON p.payout_session_id = ps.id
        WHERE p.bucket = ? AND p.business_date = ?
        ORDER BY p.timestamp DESC
    """, (bucket, date))
    
    payouts = []
    for row in cursor.fetchall():
        payouts.append({
            "id": row['id'],
            "worker_name": row['worker_name'],
            "amount": row['amount'],
            "destination": row['payout_destination'],
            "session_id": row['payout_session_id'],
            "timestamp": row['timestamp']
        })
    
    conn.close()
    return jsonify(payouts)


@app.route('/api/payouts/rollback', methods=['POST'])
def rollback_payouts():
    """Rollback (delete) committed payouts for a session.
    
    This restores the tips to the unpaid pool by:
    1. Deleting the payouts records with the session_id
    2. Deleting the session record
    
    Request body:
    - bucket: location bucket
    - date: business date
    - session_id: optional specific session to rollback (if not provided, rolls back latest)
    """
    data = request.json
    bucket = data.get('bucket')
    date = data.get('date')
    session_id = data.get('session_id')  # Optional specific session
    
    if not bucket or not date:
        return jsonify({"error": "Bucket and date required"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Get the session(s) to rollback
        if session_id:
            cursor.execute("""
                SELECT id FROM payout_sessions 
                WHERE id = ? AND bucket = ? AND business_date = ?
            """, (session_id, bucket, date))
        else:
            # Get the latest session for this bucket/date
            cursor.execute("""
                SELECT id FROM payout_sessions 
                WHERE bucket = ? AND business_date = ?
                ORDER BY created_at DESC LIMIT 1
            """, (bucket, date))
        
        session_row = cursor.fetchone()
        if not session_row:
            conn.close()
            return jsonify({"error": "No committed payouts found to rollback"}), 404
        
        target_session_id = session_row['id']
        
        # Count payouts to be deleted
        cursor.execute("""
            SELECT COUNT(*) as count FROM payouts 
            WHERE payout_session_id = ?
        """, (target_session_id,))
        count = cursor.fetchone()['count']
        
        # Delete payouts for this session
        cursor.execute("""
            DELETE FROM payouts 
            WHERE payout_session_id = ?
        """, (target_session_id,))
        
        # Delete the session
        cursor.execute("""
            DELETE FROM payout_sessions 
            WHERE id = ?
        """, (target_session_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": f"Rolled back {count} payouts for session {target_session_id}",
            "session_id": target_session_id,
            "payouts_deleted": count
        })
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"error": f"Failed to rollback: {str(e)}"}), 500


# ====================
# SERVER TIPS - ENHANCED FEATURES
# ====================

@app.route('/api/server/bucket-status', methods=['GET'])
def get_server_bucket_status():
    """Get pushed/committed status for buckets for a worker/date.
    
    Returns status for each bucket:
    - unpushed: No tips pushed yet
    - pushed: Tips pushed but not committed  
    - committed: Tips have been committed via payouts
    """
    worker = request.args.get('worker', '').strip()
    date = request.args.get('date', '').strip()
    buckets_csv = request.args.get('buckets', '').strip()
    
    if not worker or not date:
        return jsonify({"error": "Worker and date required"}), 400
    
    bucket_ids = [b.strip() for b in buckets_csv.split(',') if b.strip()]
    
    conn = get_db()
    cursor = conn.cursor()
    
    result = {}
    for bucket_id in bucket_ids:
        # Check if this worker has a pushed server transaction for THIS DATE/BUCKET.
        cursor.execute("""
            SELECT COUNT(*) as cnt
            FROM transactions
            WHERE worker_name = ? AND bucket = ? AND business_date = ?
        """, (worker, bucket_id, date))
        has_transaction = (cursor.fetchone()['cnt'] or 0) > 0

        # Unpaid payouts for this source worker still pending commit.
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) as total
            FROM payouts
            WHERE worker_name = ? AND bucket = ? AND business_date = ? AND payout_session_id IS NULL
        """, (worker, bucket_id, date))
        pushed_total = float(cursor.fetchone()['total'] or 0)

        # Any committed payout session for this bucket/date indicates committed state
        # once this worker's unpaid rows are gone.
        cursor.execute("""
            SELECT COUNT(*) as cnt
            FROM payout_sessions
            WHERE bucket = ? AND business_date = ?
        """, (bucket_id, date))
        has_committed_session = (cursor.fetchone()['cnt'] or 0) > 0

        if has_transaction and has_committed_session:
            status = "committed"
            committed_total = 1.0
        elif has_transaction and pushed_total > 0:
            status = "pushed"
            committed_total = 0.0
        else:
            status = "unpushed"
            committed_total = 0.0
            
        result[bucket_id] = {
            "status": status,
            "pushed_total": round(pushed_total, 2),
            "committed_total": round(committed_total, 2)
        }
    
    conn.close()
    return jsonify(result)


def calculate_category_breakdown(worker_name: str, date_str: str, bucket: str) -> Dict:
    """Calculate per-category sales and tip breakdown for a worker/date/bucket.
    
    Categories: Food, Wine, Draft Beer, Liquor, NA Beverage, Bottled Beer, Bottled Wine
    
    Returns category totals and calculated tips:
    - Bartips: 2% of sales (excl Bottled Wine)
    - Servertips: 2% of sales
    - Expotips: 1% of Food sales only
    - Runnertips: 0.5% of Food sales only
    """
    # Initialize categories
    categories = ['Food', 'Wine', 'Draft Beer', 'Liquor', 'NA Beverage', 'Bottled Beer', 'Bottled Wine', 'Non-Grat Svc Charges', 'No-Category']
    category_sales = {cat: 0.0 for cat in categories}
    
    # Track total tips from payments.
    total_payment_tips = 0.0
    # Track deferred sales lines (Toast selections with deferred=true).
    deferred_amount = 0.0
    
    # Load sales category GUID to name mapping from JAQ datalake
    sales_cat_guid_to_name = load_sales_category_name_map()
    
    # Fallback to hardcoded if file not available
    if not sales_cat_guid_to_name:
        sales_cat_guid_to_name = {
            '1c3cabd2-5a3e-425b-8906-2c6d27f0d16c': 'Food',
            '1089627c-9edf-4f0c-bec9-4e225fe1e4e0': 'Liquor',
            'e65e40f8-fb8d-4e54-bdd5-cf5ffdfffda1': 'Wine',
            '6985fcc4-faf2-443b-b71d-2b61d3c6456b': 'Draft Beer',
            'a6a0f64e-84a1-4be4-8b31-9fbc8feec6fc': 'Bottled Beer',
            'e27e4ee0-b6d5-4e85-94df-3384e911e447': 'Bottled Wine',
            '533d5e9f-f87c-47ca-a8c5-b948a1739795': 'NA Beverage',
        }
    
    # Get employee GUID
    emp_guid = get_employee_guid_for_worker(worker_name)
    if not emp_guid:
        return {
            "category_sales": category_sales,
            "category_tips": {
                "bartips": {cat: 0.0 for cat in categories},
                "servertips": {cat: 0.0 for cat in categories},
                "expotips": {cat: 0.0 for cat in categories},
                "runnertips": {cat: 0.0 for cat in categories}
            },
            "total_sales": 0.0,
            "total_bartips": 0.0,
            "total_servertips": 0.0,
            "total_expotips": 0.0,
            "total_runnertips": 0.0,
            "total_tips": 0.0
        }
    emp_aliases = get_employee_aliases_for_worker(worker_name) or {emp_guid}
    emp_aliases.add(emp_guid)
    
    # Get shifts for this worker/date to determine time windows
    all_shifts = get_worker_shifts_for_date(worker_name, date_str)
    if not all_shifts:
        return {
            "category_sales": category_sales,
            "category_tips": {
                "bartips": {cat: 0.0 for cat in categories},
                "servertips": {cat: 0.0 for cat in categories},
                "expotips": {cat: 0.0 for cat in categories},
                "runnertips": {cat: 0.0 for cat in categories}
            },
            "total_sales": 0.0,
            "total_bartips": 0.0,
            "total_servertips": 0.0,
            "total_expotips": 0.0,
            "total_runnertips": 0.0,
            "total_tips": 0.0
        }
    
    shift_ranges = get_worker_shift_ranges_with_cleaning(worker_name, date_str) if bucket else []
    if bucket and not shift_ranges:
        # No shifts for this bucket - return empty results
        return {
            "category_sales": category_sales,
            "category_tips": {
                "bartips": {cat: 0.0 for cat in categories},
                "servertips": {cat: 0.0 for cat in categories},
                "expotips": {cat: 0.0 for cat in categories},
                "runnertips": {cat: 0.0 for cat in categories}
            },
            "total_sales": 0.0,
            "total_bartips": 0.0,
            "total_servertips": 0.0,
            "total_expotips": 0.0,
            "total_runnertips": 0.0,
            "total_tips": 0.0
        }
    
    # Load orders from local snapshots (prefer richer file to avoid stale counts).
    orders = load_orders_for_date(date_str)
    if not orders:
        return {
            "category_sales": category_sales,
            "category_tips": {
                "bartips": {cat: 0.0 for cat in categories},
                "servertips": {cat: 0.0 for cat in categories},
                "expotips": {cat: 0.0 for cat in categories},
                "runnertips": {cat: 0.0 for cat in categories}
            },
            "total_sales": 0.0,
            "total_bartips": 0.0,
            "total_servertips": 0.0,
            "total_expotips": 0.0,
            "total_runnertips": 0.0,
            "total_tips": 0.0
        }
    
    # Load check assignments from database to apply splits.
    check_assignments = get_worker_check_assignment_map(worker_name, date_str)
    
    # Process checks
    # Note: We filter by worker GUID and shift time window, which should be sufficient.
    # Bucket filtering via revenue center is unreliable since revenue center names may be empty.
    for order in orders:
        order_srv = order.get('server', {}) or {}
        order_srv_ids = [
            (order_srv.get('guid') or '').strip(),
            (order_srv.get('id') or '').strip(),
            (order_srv.get('v2EmployeeGuid') or '').strip(),
        ]
        has_worker_order = any(sid and sid in emp_aliases for sid in order_srv_ids)
        for check in order.get('checks', []):
            if check.get('voided') or check.get('deleted'):
                continue
            
            # Check ownership by order.server (not payment.server), with split override.
            check_time = parse_toast_datetime(
                check.get('paidDate') or check.get('closedDate') or check.get('openedDate')
            )
            check_guid = check.get('guid', '')
            split_pct = get_worker_split_percentage(check_guid, worker_name, check_assignments)

            has_split_share = check_guid in check_assignments and split_pct > 0
            if not has_worker_order and not has_split_share:
                continue
            if check_guid in check_assignments and split_pct <= 0:
                continue

            if bucket:
                check_bucket = get_check_assigned_bucket(check, shift_ranges)
                if check_bucket != bucket:
                    continue

            share = split_pct / 100.0 if check_guid in check_assignments else 1.0

            # Tips follow order ownership; sum all check payment tips.
            for payment in check.get('payments', []):
                if not isinstance(payment, dict):
                    continue
                tip_amount = float(payment.get('tipAmount', 0) or 0)
                total_payment_tips += tip_amount * share
            
            # Deferred lines can appear on receipts even when timing falls
            # outside the shift window; keep this as a separate reported value.
            for selection in check.get('selections', []):
                if selection.get('voided') or selection.get('deleted'):
                    continue
                if selection.get('deferred', False):
                    item_price = float(selection.get('price', 0) or 0)
                    deferred_amount += item_price * share
            
            # Process selections to categorize sales
            # Categorize based on salesCategory in order data (primary method)
            for selection in check.get('selections', []):
                if selection.get('voided') or selection.get('deleted'):
                    continue
                item_name = (selection.get('displayName', '') or selection.get('itemName', '')).lower()
                item_guid = selection.get('itemGuid', '') or selection.get('guid', '')
                
                # Skip gift cards
                if 'gift card' in item_name or 'giftcard' in item_name:
                    continue
                
                # Use the price field directly (already includes quantity and discounts in Toast)
                item_price = float(selection.get('price', 0) or 0)
                
                # Categorize selection with shared room-charge override logic.
                sales_cat = selection.get('salesCategory', {})
                cat_guid = sales_cat.get('guid', '') if isinstance(sales_cat, dict) else ''
                category = classify_selection_category(item_name, cat_guid, sales_cat_guid_to_name)
                
                # Add to category sales (with split applied)
                category_sales[category] += item_price * share
            
            # Process service charges (Non-Gratuity Service Charges)
            for svc_charge in check.get('appliedServiceCharges', []):
                if svc_charge.get('voided') or svc_charge.get('deleted'):
                    continue
                # Only include non-gratuity service charges
                if not svc_charge.get('gratuity', False):
                    charge_amt = float(svc_charge.get('chargeAmount') or 0)
                    category_sales['Non-Grat Svc Charges'] += charge_amt * share
    
    # Calculate tips based on category sales
    category_tips = {
        "bartips": {},
        "servertips": {},
        "expotips": {},
        "runnertips": {}
    }
    
    total_bartips = 0.0
    total_servertips = 0.0
    total_expotips = 0.0
    total_runnertips = 0.0
    
    for cat, sales in category_sales.items():
        # Non-gratuity service charges are shown as sales only; no tip-out applies.
        if cat in ('Non-Grat Svc Charges', 'No-Category'):
            bartip = 0.0
            servertip = 0.0
            expotip = 0.0
            runnertip = 0.0
        else:
            # Bartips: 2% of all sales except Bottled Wine
            bartip = sales * 0.02 if cat != 'Bottled Wine' else 0.0
            # Servertips: 2% of all sales
            servertip = sales * 0.02
            # Expotips: 1% of Food only
            expotip = sales * 0.01 if cat == 'Food' else 0.0
            # Runnertips: 0.5% of Food only
            runnertip = sales * 0.005 if cat == 'Food' else 0.0
        
        category_tips['bartips'][cat] = round(bartip, 2)
        category_tips['servertips'][cat] = round(servertip, 2)
        category_tips['expotips'][cat] = round(expotip, 2)
        category_tips['runnertips'][cat] = round(runnertip, 2)
        
        total_bartips += bartip
        total_servertips += servertip
        total_expotips += expotip
        total_runnertips += runnertip
    
    total_sales = sum(category_sales.values())
    
    return {
        "category_sales": {k: round(v, 2) for k, v in category_sales.items()},
        "category_tips": category_tips,
        "deferred_amount": round(deferred_amount, 2),
        "total_sales": round(total_sales, 2),
        "total_bartips": round(total_bartips, 2),
        "total_servertips": round(total_servertips, 2),
        "total_expotips": round(total_expotips, 2),
        "total_runnertips": round(total_runnertips, 2),
        "total_tips": round(total_payment_tips, 2)
    }


def build_check_category_sales_map(date_str: str, check_guids: Set[str]) -> Dict[str, Dict[str, float]]:
    """Build category totals per check from raw order snapshots.

    This keeps split-push math aligned with server breakdown rules, including
    No-Category handling for room charges.
    """
    result: Dict[str, Dict[str, float]] = {}
    if not check_guids:
        return result

    orders = load_orders_for_date(date_str) or []
    if not orders:
        return result

    sales_cat_guid_to_name = load_sales_category_name_map()
    if not sales_cat_guid_to_name:
        sales_cat_guid_to_name = {
            '1c3cabd2-5a3e-425b-8906-2c6d27f0d16c': 'Food',
            '1089627c-9edf-4f0c-bec9-4e225fe1e4e0': 'Liquor',
            'e65e40f8-fb8d-4e54-bdd5-cf5ffdfffda1': 'Wine',
            '6985fcc4-faf2-443b-b71d-2b61d3c6456b': 'Draft Beer',
            'a6a0f64e-84a1-4be4-8b31-9fbc8feec6fc': 'Bottled Beer',
            'e27e4ee0-b6d5-4e85-94df-3384e911e447': 'Bottled Wine',
            '533d5e9f-f87c-47ca-a8c5-b948a1739795': 'NA Beverage',
        }

    for order in orders:
        for check in order.get('checks', []):
            if check.get('voided') or check.get('deleted'):
                continue
            check_guid = (check.get('guid') or '').strip()
            if not check_guid or check_guid not in check_guids:
                continue

            category_totals: Dict[str, float] = {}

            for selection in check.get('selections', []):
                if selection.get('voided') or selection.get('deleted'):
                    continue
                item_name = selection.get('displayName', '') or selection.get('itemName', '')
                if 'gift card' in (item_name or '').lower() or 'giftcard' in (item_name or '').lower():
                    continue
                item_price = float(selection.get('price', 0) or 0)
                sales_cat = selection.get('salesCategory', {})
                cat_guid = sales_cat.get('guid', '') if isinstance(sales_cat, dict) else ''
                cat = classify_selection_category(item_name, cat_guid, sales_cat_guid_to_name)
                category_totals[cat] = category_totals.get(cat, 0.0) + item_price

            for svc_charge in check.get('appliedServiceCharges', []):
                if svc_charge.get('voided') or svc_charge.get('deleted'):
                    continue
                if not svc_charge.get('gratuity', False):
                    charge_amt = float(svc_charge.get('chargeAmount') or 0)
                    category_totals['Non-Grat Svc Charges'] = category_totals.get('Non-Grat Svc Charges', 0.0) + charge_amt

            result[check_guid] = category_totals

    return result


@app.route('/api/server-tips/breakdown', methods=['GET'])
def get_server_tips_breakdown():
    """Get category breakdown for server tips."""
    worker = request.args.get('worker')
    date = request.args.get('date')
    bucket = request.args.get('bucket', '')
    
    if not worker or not date:
        return jsonify({"error": "Worker and date required"}), 400
    
    breakdown = calculate_category_breakdown(worker, date, bucket)
    return jsonify(breakdown)


@app.route('/api/server-tips/orders', methods=['GET'])
def get_server_orders():
    """Get all orders and checks for a specific worker on a date.
    
    Query params:
    - worker: worker name
    - date: YYYY-MM-DD
    - bucket: optional bucket/location filter
    
    Returns list of orders with checks handled by this worker.
    """
    worker = request.args.get('worker', '').strip()
    date_str = request.args.get('date', '').strip()
    bucket = request.args.get('bucket', '').strip()
    
    if not worker or not date_str:
        return jsonify({"error": "Worker and date required"}), 400
    
    # Get worker GUID from employees file
    emp_guid = None
    try:
        employees_file = JSON_DIR / "employees.json"
        if employees_file.exists():
            with open(employees_file, 'r') as f:
                employees = json.load(f)
            for emp in employees:
                full_name = " ".join(f"{emp.get('firstName', '')} {emp.get('lastName', '')}".split())
                if full_name == worker or emp.get('firstName') == worker:
                    emp_guid = emp.get('guid')
                    break
    except Exception as e:
        print(f"Error loading employees: {e}")
    
    if not emp_guid:
        # Try alternative lookup from time entries
        try:
            time_entries_file = JSON_DIR / f"time_entries_{date_str}_{date_str}.json"
            if time_entries_file.exists():
                with open(time_entries_file, 'r') as f:
                    entries = json.load(f)
                for entry in entries:
                    emp = entry.get('employee', {})
                    full_name = " ".join(f"{emp.get('firstName', '')} {emp.get('lastName', '')}".split())
                    if full_name == worker or emp.get('firstName') == worker:
                        emp_guid = emp.get('guid')
                        break
        except Exception as e:
            print(f"Error looking up employee GUID: {e}")
    
    emp_aliases = set()
    if worker:
        emp_aliases = get_employee_aliases_for_worker(worker)
    if emp_guid:
        emp_aliases.add(emp_guid)
    
    # Get shift ranges for bucket assignment, treating Cleaning - Server as
    # belonging to the nearest real server shift bucket.
    shift_ranges = get_worker_shift_ranges_with_cleaning(worker, date_str) if bucket else []

    # Bucket selected but worker has no assignable shift ranges: return empty.
    if bucket and not shift_ranges:
        return jsonify({
            "worker": worker,
            "date": date_str,
            "employee_guid": emp_guid,
            "order_count": 0,
            "total_amount": 0.0,
            "orders": []
        })
    
    # Load split assignments so displayed check totals can reflect the selected worker's share.
    check_assignments = get_worker_check_assignment_map(worker, date_str)

    # Load orders for this date
    orders = load_orders_for_date(date_str)
    if not orders:
        return jsonify({"orders": [], "message": "No order data found for this date"})
    
    # Filter orders to only those handled by this worker
    worker_orders = []
    
    for order in orders:
        if not isinstance(order, dict):
            continue

        order_srv = order.get('server', {}) or {}
        order_srv_ids = [
            (order_srv.get('guid') or '').strip(),
            (order_srv.get('id') or '').strip(),
            (order_srv.get('v2EmployeeGuid') or '').strip(),
        ]
        has_worker_order = any(sid and sid in emp_aliases for sid in order_srv_ids)
        order_info = {
            "order_guid": order.get('guid', ''),
            "order_number": order.get('displayNumber', ''),
            "opened_date": order.get('openedDate', ''),
            "paid_date": order.get('paidDate', ''),
            "source": order.get('source', ''),
            "checks": []
        }
        
        for check in order.get('checks', []):
            if not isinstance(check, dict):
                continue
                
            if check.get('voided') or check.get('deleted'):
                continue
            
            # Check ownership by order.server (not payment.server).
            check_guid = check.get('guid', '')
            split_pct = get_worker_split_percentage(check_guid, worker, check_assignments)
            has_split_share = check_guid in check_assignments and split_pct > 0
            if not has_worker_order and not has_split_share:
                continue
            if check_guid in check_assignments and split_pct <= 0:
                continue

            if bucket:
                check_bucket = get_check_assigned_bucket(check, shift_ranges)
                if check_bucket != bucket:
                    continue
            
            # Calculate check totals
            check_total = float(check.get('totalAmount', 0) or 0)
            tax_amount = float(check.get('taxAmount', 0) or 0)
            non_cash_tips = 0.0
            for payment in check.get('payments', []):
                if not isinstance(payment, dict):
                    continue
                payment_type = (payment.get('type') or '').upper()
                tip_amt = float(payment.get('tipAmount', 0) or 0)
                # Display non-cash/card tips per check separately so subtotal can
                # represent sales amount without tip.
                if payment_type != 'CASH':
                    non_cash_tips += tip_amt
            gratuity_fees = 0.0
            for svc_charge in check.get('appliedServiceCharges', []):
                if not isinstance(svc_charge, dict):
                    continue
                if svc_charge.get('voided') or svc_charge.get('deleted'):
                    continue
                # "Gratuity and Fees" should only include gratuity/service-fee charges.
                # Non-gratuity service charges are shown separately in category breakdown.
                if svc_charge.get('gratuity', False):
                    gratuity_fees += float(svc_charge.get('chargeAmount') or 0)
            
            # Get items for this check
            items = []
            for item in check.get('selections', []):
                if not isinstance(item, dict):
                    continue
                items.append({
                    "name": item.get('displayName', item.get('item', {}).get('name', 'Unknown')),
                    "quantity": item.get('quantity', 1),
                    "price": item.get('price', 0),
                    "total": (item.get('price', 0) or 0) * (item.get('quantity', 1) or 1)
                })
            
            share = split_pct / 100.0 if check_guid in check_assignments else 1.0
            scaled_total = check_total * share
            scaled_tax = tax_amount * share
            scaled_non_cash_tips = non_cash_tips * share
            scaled_gratuity_fees = gratuity_fees * share

            order_info["checks"].append({
                "check_guid": check.get('guid', ''),
                "check_number": check.get('displayNumber', ''),
                "total": scaled_total,
                "tax": scaled_tax,
                "non_cash_tips": scaled_non_cash_tips,
                "gratuity_fees": scaled_gratuity_fees,
                "subtotal": scaled_total - scaled_tax - scaled_non_cash_tips,
                "items": items,
                "item_count": len(items)
            })
        
        if order_info["checks"]:
            # Calculate order totals from checks
            order_info["total_amount"] = sum(c["total"] for c in order_info["checks"])
            order_info["total_tax"] = sum(c["tax"] for c in order_info["checks"])
            order_info["total_non_cash_tips"] = sum(c.get("non_cash_tips", 0) for c in order_info["checks"])
            order_info["total_gratuity_fees"] = sum(c.get("gratuity_fees", 0) for c in order_info["checks"])
            order_info["total_subtotal"] = sum(c["subtotal"] for c in order_info["checks"])
            order_info["check_count"] = len(order_info["checks"])
            order_info["item_count"] = sum(c["item_count"] for c in order_info["checks"])
            worker_orders.append(order_info)
    
    # Sort by paid date
    worker_orders.sort(key=lambda x: x.get('paid_date', '') or '')
    
    return jsonify({
        "worker": worker,
        "date": date_str,
        "employee_guid": emp_guid,
        "order_count": len(worker_orders),
        "total_amount": sum(o["total_amount"] for o in worker_orders),
        "orders": worker_orders
    })


# ====================
# ORDER DATA SYNC API
# ====================

@app.route('/api/orders/sync', methods=['POST'])
def sync_orders():
    """Import order data from JSON files into the database.
    
    Request body:
    - date: Date in YYYY-MM-DD format (required)
    
    Returns import statistics.
    """
    data = request.json or {}
    date_str = data.get('date', '').strip()
    
    if not date_str:
        return jsonify({"error": "Date required (YYYY-MM-DD format)"}), 400
    
    stats = import_orders_for_date(date_str)
    return jsonify({
        "success": len(stats['errors']) == 0,
        "date": date_str,
        "stats": stats
    })


@app.route('/api/orders/sync-range', methods=['POST'])
def sync_orders_range():
    """Import order data for a date range.
    
    Request body:
    - start_date: Start date in YYYY-MM-DD format (required)
    - end_date: End date in YYYY-MM-DD format (required)
    
    Returns import statistics for each date.
    """
    data = request.json or {}
    start_date = data.get('start_date', '').strip()
    end_date = data.get('end_date', '').strip()
    
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date required"}), 400
    
    from datetime import datetime, timedelta
    
    results = []
    current = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    
    while current <= end:
        date_str = current.strftime('%Y-%m-%d')
        stats = import_orders_for_date(date_str)
        results.append({
            "date": date_str,
            "stats": stats
        })
        current += timedelta(days=1)
    
    return jsonify({
        "success": True,
        "start_date": start_date,
        "end_date": end_date,
        "results": results
    })


@app.route('/api/checks/<check_guid>/categories', methods=['GET'])
def get_check_categories(check_guid):
    """Get category breakdown for a specific check.
    
    Returns category sales for the check.
    """
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT category_name, total_sales, item_count
        FROM check_category_totals
        WHERE check_guid = ?
        ORDER BY category_name
    """, (check_guid,))
    
    categories = []
    for row in cursor.fetchall():
        categories.append({
            "category": row['category_name'],
            "sales": row['total_sales'],
            "item_count": row['item_count']
        })
    
    # Also get check details
    cursor.execute("""
        SELECT c.check_guid, c.check_number, c.total_amount, c.server_name,
               o.order_number, c.business_date
        FROM checks c
        JOIN orders o ON c.order_guid = o.order_guid
        WHERE c.check_guid = ?
    """, (check_guid,))
    
    check_row = cursor.fetchone()
    check_info = None
    if check_row:
        check_info = {
            "check_guid": check_row['check_guid'],
            "check_number": check_row['check_number'],
            "order_number": check_row['order_number'],
            "total_amount": check_row['total_amount'],
            "server_name": check_row['server_name'],
            "business_date": check_row['business_date']
        }
    
    conn.close()
    
    return jsonify({
        "check": check_info,
        "categories": categories,
        "total_sales": sum(c['sales'] for c in categories)
    })


@app.route('/api/worker/<worker_name>/checks', methods=['GET'])
def get_worker_checks(worker_name):
    """Get all checks handled by a worker on a specific date.
    
    Query params:
    - date: YYYY-MM-DD (required)
    - bucket: optional location filter
    
    Returns checks with category breakdowns.
    """
    date_str = request.args.get('date', '').strip()
    bucket = request.args.get('bucket', '').strip()
    
    if not worker_name or not date_str:
        return jsonify({"error": "Worker name and date required"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get employee GUID
    emp_guid = get_employee_guid_for_worker(worker_name)
    
    # Find checks handled by this worker
    cursor.execute("""
        SELECT c.check_guid, c.check_number, c.total_amount, c.tax_amount, 
               c.subtotal, c.server_name, c.paid_date,
               o.order_number, o.order_guid
        FROM checks c
        JOIN orders o ON c.order_guid = o.order_guid
        WHERE c.business_date = ? AND c.server_guid = ?
        ORDER BY c.paid_date
    """, (date_str, emp_guid))
    
    checks = []
    for row in cursor.fetchall():
        check_guid = row['check_guid']
        
        # Get category breakdown for this check
        cursor.execute("""
            SELECT category_name, total_sales, item_count
            FROM check_category_totals
            WHERE check_guid = ?
            ORDER BY category_name
        """, (check_guid,))
        
        categories = []
        for cat_row in cursor.fetchall():
            categories.append({
                "category": cat_row['category_name'],
                "sales": cat_row['total_sales'],
                "item_count": cat_row['item_count']
            })
        
        checks.append({
            "check_guid": check_guid,
            "check_number": row['check_number'],
            "order_number": row['order_number'],
            "order_guid": row['order_guid'],
            "total_amount": row['total_amount'],
            "tax_amount": row['tax_amount'],
            "subtotal": row['subtotal'],
            "server_name": row['server_name'],
            "paid_date": row['paid_date'],
            "categories": categories
        })
    
    conn.close()
    
    return jsonify({
        "worker": worker_name,
        "date": date_str,
        "check_count": len(checks),
        "checks": checks
    })


# ====================
# CHECK ASSIGNMENTS API
# ====================

@app.route('/api/check-assignments', methods=['GET'])
def get_check_assignments():
    """Get all check assignments for a worker on a specific date.
    
    Query params:
    - worker: worker name
    - date: YYYY-MM-DD
    - bucket: optional location filter
    
    Returns list of check assignments with split info.
    """
    worker = request.args.get('worker', '').strip()
    date_str = request.args.get('date', '').strip()
    bucket = request.args.get('bucket', '').strip()
    
    if not worker or not date_str:
        return jsonify({"error": "Worker and date required"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    assignments = []
    cursor.execute("""
        SELECT * FROM check_assignments
        WHERE business_date = ?
        ORDER BY id ASC
    """, (date_str,))

    by_check: Dict[str, Dict[str, Any]] = {}
    for row in cursor.fetchall():
        assigned_workers = json.loads(row['assigned_workers'] or '[]')
        normalized_names = {(aw.get('worker_name') or '').strip() for aw in assigned_workers}
        primary_worker = (row['worker_name'] or '').strip()
        if worker != primary_worker and worker not in normalized_names:
            continue

        rank = 2 if worker == primary_worker else 1
        check_guid = row['check_guid']
        existing = by_check.get(check_guid)
        if existing:
            if (rank, int(row['id'] or 0)) <= (existing['_rank'], existing['id']):
                continue

        by_check[check_guid] = {
            "_rank": rank,
            "id": row['id'],
            "worker_name": row['worker_name'],
            "business_date": row['business_date'],
            "order_guid": row['order_guid'],
            "check_guid": row['check_guid'],
            "order_number": row['order_number'],
            "check_number": row['check_number'],
            "total_amount": row['total_amount'],
            "subtotal": row['subtotal'],
            "tax_amount": row['tax_amount'],
            "assigned_workers": assigned_workers,
            "split_type": row['split_type'],
            "split_count": row['split_count'],
            "updated_at": row['updated_at']
        }

    assignments = list(by_check.values())
    assignments.sort(key=lambda r: (str(r.get('order_number') or ''), str(r.get('check_number') or '')))
    for row in assignments:
        row.pop('_rank', None)
    
    conn.close()
    
    return jsonify({
        "worker": worker,
        "date": date_str,
        "assignments": assignments,
        "count": len(assignments)
    })


@app.route('/api/check-assignments', methods=['POST'])
def save_check_assignment():
    """Save or update a check assignment with split workers.
    
    Request body:
    - worker_name: primary worker name
    - business_date: YYYY-MM-DD
    - order_guid: order GUID
    - check_guid: check GUID (unique identifier)
    - order_number: display order number
    - check_number: display check number
    - total_amount: total check amount
    - subtotal: subtotal before tax
    - tax_amount: tax amount
    - assigned_workers: JSON array of {worker_name, split_percentage}
    - split_type: 'equal', 'percentage', or 'amount'
    - bucket: optional location
    
    Returns success/failure.
    """
    data = request.json
    
    worker_name = data.get('worker_name', '').strip()
    date_str = data.get('business_date', '').strip()
    check_guid = data.get('check_guid', '').strip()
    
    if not worker_name or not date_str or not check_guid:
        return jsonify({"error": "worker_name, business_date, and check_guid required"}), 400
    
    order_guid = data.get('order_guid', '').strip()
    order_number = data.get('order_number', '').strip()
    check_number = data.get('check_number', '').strip()
    total_amount = float(data.get('total_amount', 0))
    subtotal = float(data.get('subtotal', 0))
    tax_amount = float(data.get('tax_amount', 0))
    bucket = data.get('bucket', '').strip()
    
    # Parse assigned workers
    assigned_workers = data.get('assigned_workers', [])
    if isinstance(assigned_workers, list):
        assigned_workers_json = json.dumps(assigned_workers)
    else:
        assigned_workers_json = json.dumps([assigned_workers])
    
    split_type = data.get('split_type', 'equal')
    split_count = len(assigned_workers) if isinstance(assigned_workers, list) else 1
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Upsert the assignment
    cursor.execute("""
        INSERT INTO check_assignments 
            (worker_name, business_date, order_guid, check_guid, order_number, check_number,
             total_amount, subtotal, tax_amount, assigned_workers, split_type, split_count, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(check_guid, worker_name, business_date) DO UPDATE SET
            order_guid = excluded.order_guid,
            order_number = excluded.order_number,
            check_number = excluded.check_number,
            total_amount = excluded.total_amount,
            subtotal = excluded.subtotal,
            tax_amount = excluded.tax_amount,
            assigned_workers = excluded.assigned_workers,
            split_type = excluded.split_type,
            split_count = excluded.split_count,
            updated_at = datetime('now')
    """, (worker_name, date_str, order_guid, check_guid, order_number, check_number,
          total_amount, subtotal, tax_amount, assigned_workers_json, split_type, split_count))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        "success": True,
        "message": "Check assignment saved",
        "check_guid": check_guid,
        "split_count": split_count
    })


@app.route('/api/check-assignments', methods=['DELETE'])
def delete_check_assignment():
    """Delete a check assignment.
    
    Query params:
    - check_guid: check GUID
    - worker_name: worker name
    - business_date: date
    
    Returns success/failure.
    """
    check_guid = request.args.get('check_guid', '').strip()
    worker_name = request.args.get('worker_name', '').strip()
    date_str = request.args.get('business_date', '').strip()
    
    if not check_guid or not worker_name or not date_str:
        return jsonify({"error": "check_guid, worker_name, and business_date required"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        DELETE FROM check_assignments 
        WHERE check_guid = ? AND worker_name = ? AND business_date = ?
    """, (check_guid, worker_name, date_str))
    
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    return jsonify({
        "success": True,
        "deleted": deleted,
        "message": f"Deleted {deleted} assignment(s)"
    })


@app.route('/api/check-assignments/calculate', methods=['GET'])
def calculate_check_splits():
    """Calculate split amounts for a worker's checks on a date.
    
    Query params:
    - worker: worker name
    - date: YYYY-MM-DD
    - bucket: optional location filter
    
    Returns split calculations per worker.
    """
    worker = request.args.get('worker', '').strip()
    date_str = request.args.get('date', '').strip()
    bucket = request.args.get('bucket', '').strip()
    
    if not worker or not date_str:
        return jsonify({"error": "Worker and date required"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get all assignments for this worker/date
    cursor.execute("""
        SELECT * FROM check_assignments 
        WHERE worker_name = ? AND business_date = ?
    """, (worker, date_str))
    
    # Calculate splits per assigned worker
    worker_splits = {}  # {worker_name: {checks: [], total_amount: 0}}
    
    for row in cursor.fetchall():
        check_guid = row['check_guid']
        total_amount = row['total_amount']
        subtotal = row['subtotal']
        assigned_workers = json.loads(row['assigned_workers'] or '[]')
        split_type = row['split_type']
        
        if not assigned_workers:
            # No splits, primary worker gets 100%
            assigned_workers = [{"worker_name": worker, "split_percentage": 100}]
        
        # Calculate each worker's share
        for aw in assigned_workers:
            aw_name = aw.get('worker_name', worker)
            split_pct = float(aw.get('split_percentage', 100 / len(assigned_workers)))
            
            if aw_name not in worker_splits:
                worker_splits[aw_name] = {
                    "checks": [],
                    "total_amount": 0,
                    "total_subtotal": 0,
                    "split_percentage": 0
                }
            
            split_amount = total_amount * (split_pct / 100)
            split_subtotal = subtotal * (split_pct / 100)
            
            worker_splits[aw_name]["checks"].append({
                "check_guid": check_guid,
                "order_number": row['order_number'],
                "check_number": row['check_number'],
                "total_amount": total_amount,
                "split_amount": round(split_amount, 2),
                "split_percentage": split_pct
            })
            worker_splits[aw_name]["total_amount"] += split_amount
            worker_splits[aw_name]["total_subtotal"] += split_subtotal
    
    conn.close()
    
    return jsonify({
        "worker": worker,
        "date": date_str,
        "splits": worker_splits,
        "worker_count": len(worker_splits)
    })


@app.route('/api/payouts/workers', methods=['GET'])
def get_payouts_workers():
    """Get workers who worked on a specific date and bucket.
    
    Returns list of workers who have shifts on the given date,
    filtered by bucket if provided.
    """
    date = request.args.get('date', '').strip()
    bucket = request.args.get('bucket', '').strip()
    
    if not date:
        return jsonify({"error": "Date required"}), 400
    
    # Convert date format if needed (YYYY-MM-DD to various formats)
    # Look up shifts from labor data
    workers = set()
    
    # Load from labor_shifts_detailed_daily.csv
    labor_file = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
    if labor_file.exists():
        try:
            with open(labor_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row_date = row.get('date', '').strip()
                    if row_date == date:
                        # Check bucket mapping from job_title
                        job_title = row.get('job_title', '').strip()
                        bucket_id = job_title_to_bucket_id(job_title)
                        
                        # If bucket specified, only include matching workers
                        if not bucket or bucket_id == bucket:
                            worker_name = row.get('employee_name', '').strip()
                            if worker_name:
                                workers.add(worker_name)
        except Exception as e:
            print(f"Error reading labor shifts: {e}")
    
    # Also include workers who have pushed transactions for this date/bucket
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT DISTINCT worker_name FROM transactions 
            WHERE date = ? AND bucket = ?
        """, (date, bucket))
        for row in cursor.fetchall():
            if row['worker_name']:
                workers.add(row['worker_name'])
    except Exception as e:
        print(f"Error querying transactions: {e}")
    finally:
        conn.close()
    
    return jsonify(sorted(list(workers)))


@app.route('/api/payouts/unpaid-breakdown', methods=['GET'])
def get_unpaid_breakdown():
    """Get unpaid pushed breakdown by server for a bucket/date.
    
    Returns detailed breakdown of which servers pushed what amounts,
    and which are still unpaid. Combines data from payouts and transactions tables.
    """
    bucket = request.args.get('bucket', '').strip()
    date = request.args.get('date', '').strip()
    
    if not bucket or not date:
        return jsonify({"error": "Bucket and date required"}), 400
    
    conn = get_db()
    cursor = conn.cursor()

    # Ignore stale unpaid rows from before the latest commit for this bucket/date.
    # This keeps breakdown accurate after committing payouts while still allowing
    # new pushes after commit to show up as unpaid.
    cursor.execute("""
        SELECT MAX(created_at) AS latest_commit_ts
        FROM payout_sessions
        WHERE bucket = ? AND business_date = ?
    """, (bucket, date))
    latest_commit_row = cursor.fetchone()
    latest_commit_ts = latest_commit_row['latest_commit_ts'] if latest_commit_row else None
    
    # Get all unpaid pushed payouts for this bucket/date (payout_session_id IS NULL)
    cursor.execute("""
        SELECT 
            worker_name,
            payout_destination,
            COALESCE(SUM(amount), 0) as total
        FROM payouts 
        WHERE bucket = ? AND business_date = ? AND payout_session_id IS NULL
          AND (? IS NULL OR timestamp > ?)
        GROUP BY worker_name, payout_destination
    """, (bucket, date, latest_commit_ts, latest_commit_ts))
    
    unpaid_rows = cursor.fetchall()
    
    # DEBUG: Log what payouts were found
    print(f"[DEBUG get_unpaid_breakdown] Bucket: {bucket}, Date: {date}")
    print(f"[DEBUG get_unpaid_breakdown] Found {len(unpaid_rows)} unpaid payout rows:")
    for row in unpaid_rows:
        print(f"  - {row['worker_name']}: {row['payout_destination']} = ${row['total']}")
    
    # Build breakdown from payouts
    breakdown = []
    for row in unpaid_rows:
        amount = float(row['total'] or 0)
        if amount > 0:
            breakdown.append({
                "server": row['worker_name'],
                "destination": row['payout_destination'],
                "amount": round(amount, 2)
            })
    
    # Also get server tips from transactions table (server tips pushed)
    cursor.execute("""
        SELECT 
            worker_name,
            bartips,
            servertips,
            expotips,
            runnertips,
            creditcardtip,
            cashtips
        FROM transactions 
        WHERE bucket = ? AND business_date = ?
          AND (? IS NULL OR timestamp > ?)
    """, (bucket, date, latest_commit_ts, latest_commit_ts))
    
    for row in cursor.fetchall():
        worker = row['worker_name']
        
        # Get breakdown tips
        bartips = float(row['bartips'] or 0)
        servertips = float(row['servertips'] or 0)
        expotips = float(row['expotips'] or 0)
        runnertips = float(row['runnertips'] or 0)
        
        # If no breakdown, use credit/cash tips as server/busser tips
        total_breakdown = bartips + servertips + expotips + runnertips
        if total_breakdown == 0:
            credit_tip = float(row['creditcardtip'] or 0)
            cash_tip = float(row['cashtips'] or 0)
            total_tip = credit_tip + cash_tip
            if total_tip > 0:
                # Default to Busser (server tips) when no breakdown
                servertips = total_tip
        
        destinations = [
            ('Bartender', bartips),
            ('Busser', servertips),
            ('Expo', expotips),
            ('Runner', runnertips)
        ]
        
        # Only add transaction amounts if no payouts exist for this worker
        # (payouts represent the calculated split amounts from check data)
        worker_has_payouts = any(b['server'] == worker for b in breakdown)
        if not worker_has_payouts:
            for dest, amount in destinations:
                if amount > 0:
                    breakdown.append({
                        "server": worker,
                        "destination": dest,
                        "amount": round(amount, 2)
                    })
    
    return jsonify(breakdown)


@app.route('/api/server-tips/push', methods=['POST'])
def push_server_tips():
    """Push server tips to payouts (create transaction record).
    
    This creates a record in the transactions table that the payouts page
    can then display and distribute to workers.
    """
    data = request.json
    
    worker = data.get('worker', '').strip()
    date = data.get('date', '').strip()
    bucket = data.get('bucket', '').strip()
    
    if not worker or not date or not bucket:
        return jsonify({"error": "Worker, date, and bucket required"}), 400
    
    # Get tip amounts
    bar_tips = float(data.get('bar_tips', 0))
    busser_tips = float(data.get('busser_tips', 0))
    expo_tips = float(data.get('expo_tips', 0))
    runner_tips = float(data.get('runner_tips', 0))
    
    # Get main figures for context
    cash_tips = float(data.get('cash_tips', 0))
    credit_tips = float(data.get('credit_tips', 0))
    gratuity = float(data.get('gratuity', 0))
    net_sales = float(data.get('net_sales', 0))
    
    conn = get_db()
    cursor = conn.cursor()

    upsert_server_tip_cache(cursor, worker, date, bucket, {
        'cash_tips': cash_tips,
        'credit_tips': credit_tips,
        'gratuity': gratuity,
        'net_sales': net_sales,
        'bar_tips': bar_tips,
        'busser_tips': busser_tips,
        'expo_tips': expo_tips,
        'runner_tips': runner_tips,
    })
    
    # Check if there's already a pushed record for this worker/date/bucket
    # Use business_date to prevent duplicates across the same business day
    cursor.execute("""
        SELECT id FROM transactions 
        WHERE worker_name = ? AND bucket = ? AND business_date = ?
    """, (worker, bucket, date))
    
    existing = cursor.fetchone()
    
    if existing:
        # Update existing record instead of creating duplicate
        cursor.execute("""
            UPDATE transactions 
            SET bartips = ?, servertips = ?, expotips = ?, runnertips = ?,
                cashtips = ?, creditcardtip = ?, gratuity = ?, net_sales = ?,
                timestamp = datetime('now')
            WHERE id = ?
        """, (bar_tips, busser_tips, expo_tips, runner_tips,
              cash_tips, credit_tips, gratuity, net_sales, existing['id']))
        action = "Updated"
    else:
        # Insert new record
        cursor.execute("""
            INSERT INTO transactions 
            (worker_name, bucket, bartips, servertips, expotips, runnertips,
             cashtips, creditcardtip, gratuity, net_sales, business_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (worker, bucket, bar_tips, busser_tips, expo_tips, runner_tips,
              cash_tips, credit_tips, gratuity, net_sales, date))
        action = "Pushed"
    
    # Also insert/update payouts table for unpaid breakdown
    
    # Get check assignments to calculate splits
    cursor.execute("""
        SELECT * FROM check_assignments 
        WHERE worker_name = ? AND business_date = ?
    """, (worker, date))
    
    check_assignments = cursor.fetchall()
    
    # Build a map of check_guid -> assigned_workers from check_assignments
    check_splits = {}
    all_split_workers = set([worker.strip()])
    
    for assignment in check_assignments:
        assigned_workers = json.loads(assignment['assigned_workers'] or '[]')
        # Normalize worker names in assigned_workers
        normalized_assigned = []
        for aw in assigned_workers:
            normalized_aw = dict(aw)
            normalized_aw['worker_name'] = aw.get('worker_name', '').strip()
            normalized_assigned.append(normalized_aw)
        check_splits[assignment['check_guid']] = normalized_assigned
        for aw in normalized_assigned:
            all_split_workers.add(aw.get('worker_name'))
    
    # DEBUG: Log split information
    print(f"[DEBUG push_server_tips] Worker: {worker}, Date: {date}, Bucket: {bucket}")
    print(f"[DEBUG push_server_tips] Check assignments found: {len(check_assignments)}")
    print(f"[DEBUG push_server_tips] Check splits: {check_splits}")
    print(f"[DEBUG push_server_tips] All split workers: {all_split_workers}")
    
    # Delete existing unpaid payouts only for the active worker.
    # Split workers push from their own server-tips page.
    cursor.execute("""
        DELETE FROM payouts 
        WHERE worker_name = ? AND bucket = ? AND business_date = ? AND payout_session_id IS NULL
    """, (worker, bucket, date))
    
    # Track splits per assigned worker
    # {worker_name: {bar_tips, busser_tips, expo_tips, runner_tips}}
    worker_splits = {}
    
    # Get shift windows for bucket filtering (if bucket specified)
    shift_windows = []
    if bucket:
        try:
            shift_windows = get_server_bucket_shift_windows(worker, date, bucket)
        except Exception as e:
            print(f"[DEBUG push_server_tips] Error getting shift windows: {e}")
    
    # Get all checks handled by this worker from check_workers table
    # Filter by bucket shift windows if bucket is specified
    if shift_windows:
        # Get checks with paid_date filtering
        cursor.execute("""
            SELECT DISTINCT c.check_guid, c.total_amount, c.paid_date
            FROM checks c
            JOIN check_workers cw ON c.check_guid = cw.check_guid
            WHERE cw.worker_name = ? AND c.business_date = ?
        """, (worker, date))
        all_checks_raw = cursor.fetchall()
        all_worker_checks = {}
        for row in all_checks_raw:
            check_guid = row['check_guid']
            paid_date_str = row['paid_date']
            if paid_date_str:
                try:
                    check_time = parse_toast_datetime(paid_date_str)
                    if not check_time:
                        continue
                    in_window = any(start <= check_time <= end for start, end in shift_windows)
                    if in_window:
                        all_worker_checks[check_guid] = row['total_amount']
                except Exception:
                    continue
    else:
        # No bucket filter - get all checks
        cursor.execute("""
            SELECT DISTINCT c.check_guid, c.total_amount
            FROM checks c
            JOIN check_workers cw ON c.check_guid = cw.check_guid
            WHERE cw.worker_name = ? AND c.business_date = ?
        """, (worker, date))
        all_worker_checks = {row['check_guid']: row['total_amount'] for row in cursor.fetchall()}
    
    # Check if there are any actual splits (multiple workers on any check)
    has_actual_splits = any(len(aw) > 1 for aw in check_splits.values())
    check_category_sales_map = build_check_category_sales_map(date, set(all_worker_checks.keys()))
    
    # Initialize worker_splits for all workers involved
    for w in all_split_workers:
        worker_splits[w] = {
            'bar_tips': 0, 'busser_tips': 0, 
            'expo_tips': 0, 'runner_tips': 0,
            'check_guids': []
        }
    
    # Process ALL checks handled by the worker
    for check_guid, check_total in all_worker_checks.items():
        # Prefer category totals derived from raw snapshots so split calculations
        # match server page rules (including No-Category room charges).
        category_sales_from_raw = check_category_sales_map.get(check_guid) or {}
        if category_sales_from_raw:
            category_sales = [
                {'category_name': cat, 'total_sales': amt}
                for cat, amt in category_sales_from_raw.items()
            ]
        else:
            cursor.execute("""
                SELECT category_name, total_sales 
                FROM check_category_totals 
                WHERE check_guid = ?
            """, (check_guid,))
            category_sales = cursor.fetchall()
        
        # Determine how to split this check
        if check_guid in check_splits:
            # This check has a defined split
            assigned_workers = check_splits[check_guid]
            for aw in assigned_workers:
                aw_name = aw.get('worker_name', worker)
                split_pct = float(aw.get('split_percentage', 100 / len(assigned_workers)))
                
                if aw_name not in worker_splits:
                    print(f"[DEBUG push_server_tips] WARNING: Worker '{aw_name}' from split not in worker_splits (check: {check_guid}). Available: {list(worker_splits.keys())}")
                    continue
                
                if category_sales:
                    for cs in category_sales:
                        cat_name = cs['category_name']
                        cat_amount = (cs['total_sales'] or 0) * (split_pct / 100)
                        
                        # Map categories to tip destinations
                        # Bartips: 2% of all categories EXCEPT Bottled Wine
                        # Servertips (Busser): 2% of all categories
                        # Expotips: 1% of Food only
                        # Runnertips: 0.5% of Food only
                        if cat_name in ['Food']:
                            worker_splits[aw_name]['bar_tips'] += cat_amount * 0.02
                            worker_splits[aw_name]['busser_tips'] += cat_amount * 0.02
                            worker_splits[aw_name]['expo_tips'] += cat_amount * 0.01
                            worker_splits[aw_name]['runner_tips'] += cat_amount * 0.005
                        elif cat_name in ['Non-Grat Svc Charges', 'No-Category']:
                            # Non-gratuity service charges are sales-only (no tip-out).
                            pass
                        elif cat_name in ['Wine', 'Draft Beer', 'Liquor']:
                            worker_splits[aw_name]['bar_tips'] += cat_amount * 0.02
                            worker_splits[aw_name]['busser_tips'] += cat_amount * 0.02
                        elif cat_name in ['Bottled Beer']:
                            # Bottled Beer: Bartips 2%, Busser 2% (Expo/Runner get nothing)
                            worker_splits[aw_name]['bar_tips'] += cat_amount * 0.02
                            worker_splits[aw_name]['busser_tips'] += cat_amount * 0.02
                        elif cat_name in ['Bottled Wine']:
                            # Bottled Wine: NO Bartips, only Busser 2%
                            worker_splits[aw_name]['busser_tips'] += cat_amount * 0.02
                        else:
                            # Other categories: Bartips 2%, Busser 2%
                            worker_splits[aw_name]['bar_tips'] += cat_amount * 0.02
                            worker_splits[aw_name]['busser_tips'] += cat_amount * 0.02
                else:
                    # No category data - apply proportional split to total tips
                    share = split_pct / 100
                    worker_splits[aw_name]['bar_tips'] += bar_tips * share
                    worker_splits[aw_name]['busser_tips'] += busser_tips * share
                    worker_splits[aw_name]['expo_tips'] += expo_tips * share
                    worker_splits[aw_name]['runner_tips'] += runner_tips * share
                
                worker_splits[aw_name]['check_guids'].append(check_guid)
        else:
            # No split defined - primary worker gets 100%
            if category_sales:
                for cs in category_sales:
                    cat_name = cs['category_name']
                    cat_amount = cs['total_sales'] or 0
                    
                    # Map categories to tip destinations
                    if cat_name in ['Food']:
                        worker_splits[worker]['bar_tips'] += cat_amount * 0.02
                        worker_splits[worker]['busser_tips'] += cat_amount * 0.02
                        worker_splits[worker]['expo_tips'] += cat_amount * 0.01
                        worker_splits[worker]['runner_tips'] += cat_amount * 0.005
                    elif cat_name in ['Non-Grat Svc Charges', 'No-Category']:
                        # Non-gratuity service charges are sales-only (no tip-out).
                        pass
                    elif cat_name in ['Wine', 'Draft Beer', 'Liquor']:
                        worker_splits[worker]['bar_tips'] += cat_amount * 0.02
                        worker_splits[worker]['busser_tips'] += cat_amount * 0.02
                    elif cat_name in ['Bottled Beer']:
                        worker_splits[worker]['bar_tips'] += cat_amount * 0.02
                        worker_splits[worker]['busser_tips'] += cat_amount * 0.02
                    elif cat_name in ['Bottled Wine']:
                        worker_splits[worker]['busser_tips'] += cat_amount * 0.02
                    else:
                        worker_splits[worker]['bar_tips'] += cat_amount * 0.02
                        worker_splits[worker]['busser_tips'] += cat_amount * 0.02
            else:
                # No category data and no split - this shouldn't happen often
                # The fallback at the end will handle this
                pass
            
            worker_splits[worker]['check_guids'].append(check_guid)
    
    # If we didn't calculate any tips (no category data for any checks), use original amounts
    total_calculated = (worker_splits[worker]['bar_tips'] + 
                      worker_splits[worker]['busser_tips'] + 
                      worker_splits[worker]['expo_tips'] + 
                      worker_splits[worker]['runner_tips'])
    
    if total_calculated == 0 and worker_splits[worker]['check_guids']:
        if has_actual_splits and len(all_split_workers) > 1:
            # Distribute tips proportionally among all split workers
            # based on their split percentages from check assignments
            for split_worker in all_split_workers:
                # Calculate this worker's share across all their assigned checks
                total_share_pct = 0
                check_count = 0
                for check_guid, assigned in check_splits.items():
                    for aw in assigned:
                        if aw.get('worker_name') == split_worker:
                            total_share_pct += aw.get('split_percentage', 100 / len(assigned))
                            check_count += 1
                
                # Average the share percentage across all checks
                if check_count > 0:
                    avg_share_pct = total_share_pct / check_count / 100.0
                else:
                    avg_share_pct = 1.0 / len(all_split_workers)
                
                # Apply proportional share of tips
                worker_splits[split_worker]['bar_tips'] = bar_tips * avg_share_pct
                worker_splits[split_worker]['busser_tips'] = busser_tips * avg_share_pct
                worker_splits[split_worker]['expo_tips'] = expo_tips * avg_share_pct
                worker_splits[split_worker]['runner_tips'] = runner_tips * avg_share_pct
                print(f"[DEBUG push_server_tips] Fallback split for {split_worker}: {avg_share_pct*100:.1f}% share")
        else:
            # No splits - assign all to primary worker
            worker_splits[worker]['bar_tips'] = bar_tips
            worker_splits[worker]['busser_tips'] = busser_tips
            worker_splits[worker]['expo_tips'] = expo_tips
            worker_splits[worker]['runner_tips'] = runner_tips
    
    # If no check assignments, use the original amounts
    if worker not in worker_splits:
        worker_splits[worker] = {
            'bar_tips': bar_tips, 'busser_tips': busser_tips,
            'expo_tips': expo_tips, 'runner_tips': runner_tips,
            'check_guids': []
        }
    
    # DEBUG: Log worker_splits before adjusting for entered tips
    print(f"[DEBUG push_server_tips] Worker splits calculated: {worker_splits}")
    print(f"[DEBUG push_server_tips] Has actual splits: {has_actual_splits}")

    # No actual check splits: trust the UI-entered amounts (already bucket-filtered
    # and aligned with the Server Tips breakdown shown to the user).
    if not has_actual_splits and worker in worker_splits:
        worker_splits[worker]['bar_tips'] = bar_tips
        worker_splits[worker]['busser_tips'] = busser_tips
        worker_splits[worker]['expo_tips'] = expo_tips
        worker_splits[worker]['runner_tips'] = runner_tips
        print(f"[DEBUG push_server_tips] No actual splits; using entered values for {worker}")
    
    # The server-tips page shows the primary worker's own payout values after split
    # adjustments have already been applied to their checks. Keep those entered values
    # intact for the primary worker and add split-worker amounts on top.
    if worker in worker_splits:
        worker_splits[worker]['bar_tips'] = bar_tips
        worker_splits[worker]['busser_tips'] = busser_tips
        worker_splits[worker]['expo_tips'] = expo_tips
        worker_splits[worker]['runner_tips'] = runner_tips
        print(f"[DEBUG push_server_tips] Using entered values for primary worker {worker}")
    
    # Insert payout records for active worker only.
    split_details = []
    payouts_inserted = []
    for worker_name, splits in worker_splits.items():
        if worker_name != worker:
            continue
        worker_total = 0
        for dest, amount in [('Bartender', splits['bar_tips']), 
                             ('Busser', splits['busser_tips']), 
                             ('Expo', splits['expo_tips']), 
                             ('Runner', splits['runner_tips'])]:
            if amount > 0:
                worker_total += amount
                cursor.execute("""
                    INSERT INTO payouts (worker_name, amount, bucket, payout_destination, 
                                       business_date, payout_session_id)
                    VALUES (?, ?, ?, ?, ?, NULL)
                """, (worker_name, amount, bucket, dest, date))
                payouts_inserted.append(f"{worker_name}:{dest}:${amount:.2f}")
                
                # Store split payout records for rollback
                for check_guid in splits['check_guids']:
                    cursor.execute("""
                        INSERT INTO split_payouts 
                        (worker_name, check_guid, business_date, bucket, amount, 
                         payout_destination, split_percentage)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (worker_name, check_guid, date, bucket, amount, dest, 
                          100 / len(worker_splits) if worker_splits else 100))
        
        split_details.append({
            "worker": worker_name,
            "bar_tips": round(splits['bar_tips'], 2),
            "busser_tips": round(splits['busser_tips'], 2),
            "expo_tips": round(splits['expo_tips'], 2),
            "runner_tips": round(splits['runner_tips'], 2)
        })
        print(f"[DEBUG push_server_tips] {worker_name}: total=${worker_total:.2f}, checks={splits['check_guids']}")
    
    conn.commit()
    conn.close()
    
    primary = worker_splits.get(worker, {'bar_tips': 0, 'busser_tips': 0, 'expo_tips': 0, 'runner_tips': 0})
    total_pushed = sum(primary[d] for d in ['bar_tips', 'busser_tips', 'expo_tips', 'runner_tips'])
    
    return jsonify({
        "success": True,
        "message": f"{action} ${total_pushed:.2f} to payouts for 1 worker(s)",
        "action": action,
        "splits": split_details,
        "worker_count": 1
    })


@app.route('/api/server-tips/status', methods=['GET'])
def get_server_tips_status():
    """Get push/commit status for server tips.
    
    Query params:
    - worker: worker name
    - bucket: location bucket
    - date: business date
    
    Returns status: unpushed, pushed, or committed
    """
    worker = request.args.get('worker', '').strip()
    bucket = request.args.get('bucket', '').strip()
    date = request.args.get('date', '').strip()
    
    if not worker or not bucket or not date:
        return jsonify({"error": "Worker, bucket, and date required"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if there's a source transaction record for this worker/date/bucket.
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM transactions
        WHERE worker_name = ? AND bucket = ? AND business_date = ?
    """, (worker, bucket, date))
    has_transaction = (cursor.fetchone()['cnt'] or 0) > 0

    # Check if this worker still has unpaid rows (pushed but not committed).
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM payouts
        WHERE worker_name = ? AND bucket = ? AND business_date = ? AND payout_session_id IS NULL
    """, (worker, bucket, date))
    unpaid_count = int(cursor.fetchone()['cnt'] or 0)

    # Committed sessions are tracked at bucket/date level.
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM payout_sessions
        WHERE bucket = ? AND business_date = ?
    """, (bucket, date))
    has_committed_session = (cursor.fetchone()['cnt'] or 0) > 0
    
    conn.close()
    
    if has_transaction and has_committed_session:
        status = "committed"
    elif has_transaction and unpaid_count > 0:
        status = "pushed"
    else:
        status = "unpushed"
    
    return jsonify({
        "worker": worker,
        "bucket": bucket,
        "date": date,
        "status": status
    })


@app.route('/api/server-tips/undo', methods=['POST'])
def undo_server_tips():
    """Undo/unpush server tips for a worker/date/bucket.
    
    Removes the transaction record and all payouts (including split workers)
    if they haven't been committed yet.
    """
    data = request.json
    
    worker = data.get('worker', '').strip()
    date = data.get('date', '').strip()
    bucket = data.get('bucket', '').strip()
    
    if not worker or not date or not bucket:
        return jsonify({"error": "Worker, date, and bucket required"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Undo should cascade across all connected split-worker relationships.
    all_workers = get_connected_split_workers(worker, date)
    if not all_workers:
        all_workers = [worker]
    
    # Check if any payouts have been committed for any of these workers
    placeholders = ','.join(['?' for _ in all_workers])
    cursor.execute(f"""
        SELECT COUNT(*) as cnt, worker_name FROM payouts 
        WHERE worker_name IN ({placeholders}) 
        AND bucket = ? AND business_date = ? AND payout_session_id IS NOT NULL
        GROUP BY worker_name
    """, (*all_workers, bucket, date))
    
    committed = cursor.fetchall()
    if committed:
        committed_workers = [r['worker_name'] for r in committed]
        conn.close()
        return jsonify({
            "error": "Cannot undo - payouts have already been committed",
            "committed_workers": committed_workers
        }), 400
    
    deleted_transactions = 0
    deleted_overrides = 0
    for w in all_workers:
        cursor.execute("""
            DELETE FROM transactions 
            WHERE worker_name = ? AND bucket = ? AND business_date = ?
        """, (w, bucket, date))
        deleted_transactions += cursor.rowcount

        # Clear any saved manual override so the UI falls back to fresh calculations.
        cursor.execute("""
            DELETE FROM servers
            WHERE worker_name = ? AND bucket = ? AND business_date = ?
        """, (w, bucket, date))
        deleted_overrides += cursor.rowcount
    
    # Delete unpaid payouts for ALL workers involved in splits
    deleted_total = 0
    for w in all_workers:
        cursor.execute("""
            DELETE FROM payouts 
            WHERE worker_name = ? AND bucket = ? AND business_date = ? AND payout_session_id IS NULL
        """, (w, bucket, date))
        deleted_total += cursor.rowcount
    
    # Also delete split_payouts records
    split_placeholders = ','.join(['?' for _ in all_workers])
    cursor.execute(f"""
        DELETE FROM split_payouts 
        WHERE business_date = ? AND bucket = ? AND worker_name IN ({split_placeholders})
    """, (date, bucket, *all_workers))
    
    conn.commit()
    conn.close()
    
    if deleted_total > 0 or deleted_transactions > 0 or deleted_overrides > 0:
        return jsonify({
            "success": True,
            "message": f"Undo successful for {worker} and {len([w for w in all_workers if w != worker])} split worker(s) on {date}"
        })
    else:
        return jsonify({
            "success": False,
            "message": "No pushed tips found to undo"
        })


# ====================
# MAIN


# ====================
# WORKER REPORT API
# ====================

@app.route('/api/report', methods=['GET'])
def get_worker_report():
    """Get worker report for a date range.
    
    Query params:
    - start_date: YYYY-MM-DD (optional, defaults to today)
    - end_date: YYYY-MM-DD (optional, defaults to today)
    
    Returns a list of worker rows with:
    - date: business date
    - worker: worker name
    - job_title: job title (if available)
    - cash_tips: cash tips earned
    - credit_tips: credit tips earned
    - gratuity: gratuity earned
    - tips_paid_out: tips paid to others (busser/expo/runner)
    - net_sales: net sales
    - tips_received: tips received from others
    - tip_pct: tip percentage of sales
    """
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    
    # Default to today if no dates provided
    if not start_date:
        start_date = datetime.now().strftime('%Y-%m-%d')
    if not end_date:
        end_date = start_date
    
    conn = get_db()
    cursor = conn.cursor()
    
    report_rows = []
    row_map = {}
    alias_map = build_worker_name_alias_map()

    def canonical_worker_name(name: str) -> str:
        raw = (name or "").strip()
        if not raw:
            return raw
        return alias_map.get(raw.lower(), raw)
    
    try:
        # Get all workers who have data in the date range.
        # Server main figures should come from pushed transactions because that is
        # the source of truth written by the server-tips page.
        cursor.execute("""
            SELECT 
                business_date as date,
                worker_name as worker,
                SUM(COALESCE(cashtips, 0)) as cash_tips,
                SUM(COALESCE(creditcardtip, 0)) as credit_tips,
                SUM(COALESCE(gratuity, 0)) as gratuity,
                SUM(
                    COALESCE(bartips, 0) +
                    COALESCE(servertips, 0) +
                    COALESCE(expotips, 0) +
                    COALESCE(runnertips, 0)
                ) as tips_paid_out,
                SUM(COALESCE(net_sales, 0)) as net_sales,
                'Server' as role
            FROM transactions
            WHERE business_date BETWEEN ? AND ?
            GROUP BY business_date, worker_name
            ORDER BY business_date, worker_name
        """, (start_date, end_date))
        
        for row in cursor.fetchall():
            total_tips = (row['cash_tips'] or 0) + (row['credit_tips'] or 0) + (row['gratuity'] or 0)
            net_sales = row['net_sales'] or 0
            tip_pct = (total_tips / net_sales * 100) if net_sales > 0 else 0
            
            worker_name = canonical_worker_name(row['worker'])
            report_rows.append({
                'date': row['date'],
                'worker': worker_name,
                'job_title': 'Server',
                'cash_tips': round(row['cash_tips'] or 0, 2),
                'credit_tips': round(row['credit_tips'] or 0, 2),
                'gratuity': round(row['gratuity'] or 0, 2),
                'tips_paid_out': round(row['tips_paid_out'] or 0, 2),
                'net_sales': round(net_sales, 2),
                'tips_received': 0.0,  # Servers don't receive from others in this context
                'tip_pct': round(tip_pct, 2)
            })
            row_map[(row['date'], worker_name)] = report_rows[-1]
        
        # Bartender main figures should come from the latest pushed row per
        # bartender/date/bar_name, summed into one row per bartender/day.
        cursor.execute("""
            SELECT 
                latest_rows.date,
                latest_rows.bartender as worker,
                SUM(COALESCE(latest_rows.cash_tips, 0)) as cash_tips,
                SUM(COALESCE(latest_rows.credit_tips, 0)) as credit_tips,
                SUM(COALESCE(latest_rows.net_sales, 0)) as net_sales,
                SUM(COALESCE(latest_rows.sum_tips_for_payout, 0)) as tips_paid_out
            FROM bartenders latest_rows
            JOIN (
                SELECT date, bartender, bar_name, MAX(id) AS max_id
                FROM bartenders
                WHERE date BETWEEN ? AND ?
                GROUP BY date, bartender, bar_name
            ) latest
              ON latest_rows.id = latest.max_id
            GROUP BY latest_rows.date, latest_rows.bartender
            ORDER BY latest_rows.date, latest_rows.bartender
        """, (start_date, end_date))
        
        for row in cursor.fetchall():
            total_tips = (row['cash_tips'] or 0) + (row['credit_tips'] or 0)
            net_sales = row['net_sales'] or 0
            tip_pct = (total_tips / net_sales * 100) if net_sales > 0 else 0
            
            worker_name = canonical_worker_name(row['worker'])
            report_rows.append({
                'date': row['date'],
                'worker': worker_name,
                'job_title': 'Bartender',
                'cash_tips': round(row['cash_tips'] or 0, 2),
                'credit_tips': round(row['credit_tips'] or 0, 2),
                'gratuity': 0.0,
                'tips_paid_out': round(row['tips_paid_out'] or 0, 2),
                'net_sales': round(net_sales, 2),
                'tips_received': 0.0,
                'tip_pct': round(tip_pct, 2)
            })
            row_map[(row['date'], worker_name)] = report_rows[-1]
        
        # Get workers who PAID OUT tips (from payouts table with payout_session_id IS NULL)
        # These are servers/bartenders who pushed tips but haven't committed yet
        cursor.execute("""
            SELECT 
                business_date as date,
                worker_name as worker,
                bucket,
                payout_destination as destination,
                COALESCE(SUM(amount), 0) as total_paid
            FROM payouts
            WHERE business_date BETWEEN ? AND ? AND payout_session_id IS NULL
            GROUP BY business_date, worker_name, bucket, payout_destination
            ORDER BY business_date, worker_name
        """, (start_date, end_date))
        
        paid_out_map = {}
        for row in cursor.fetchall():
            worker_name = canonical_worker_name(row['worker'])
            key = (row['date'], worker_name)
            if key not in paid_out_map:
                paid_out_map[key] = {
                'bucket': row['bucket'],
                    'busser': 0,
                    'expo': 0,
                    'runner': 0,
                    'bartender': 0,
                    'total': 0
                }
            dest = (row['destination'] or '').lower()
            amount = float(row['total_paid'] or 0)
            if 'busser' in dest:
                paid_out_map[key]['busser'] += amount
            elif 'expo' in dest:
                paid_out_map[key]['expo'] += amount
            elif 'runner' in dest:
                paid_out_map[key]['runner'] += amount
            elif 'bartender' in dest:
                paid_out_map[key]['bartender'] += amount
            paid_out_map[key]['total'] += amount
        
        # Add rows for workers who paid out tips (servers/bartenders)
        for (date, worker), amounts in paid_out_map.items():
            # Check if this worker already has a row (from servers or bartenders table)
            existing = [r for r in report_rows if r['date'] == date and r['worker'] == worker]
            if existing:
                # Update existing row with tips paid out
                for row in existing:
                    row['tips_paid_out'] = round(amounts['total'], 2)
            else:
                split_figures = get_split_assigned_main_figures(worker, date)
                total_tips = (
                    float(split_figures.get('cash_tips') or 0) +
                    float(split_figures.get('credit_tips') or 0) +
                    float(split_figures.get('gratuity') or 0)
                )
                net_sales = float(split_figures.get('net_sales') or 0)
                tip_pct = (total_tips / net_sales * 100) if net_sales > 0 else 0
                # Add new row for this worker who paid out but has no other record.
                # Default these to Server. True bartender rows should come from the
                # bartenders table, not be inferred from bucket names like "am_bar".
                report_rows.append({
                    'date': date,
                    'worker': worker,
                    'job_title': 'Server',
                    'cash_tips': round(split_figures.get('cash_tips') or 0, 2),
                    'credit_tips': round(split_figures.get('credit_tips') or 0, 2),
                    'gratuity': round(split_figures.get('gratuity') or 0, 2),
                    'tips_paid_out': round(amounts['total'], 2),
                    'net_sales': round(net_sales, 2),
                    'tips_received': 0.0,
                    'tip_pct': round(tip_pct, 2)
                })
                row_map[(date, worker)] = report_rows[-1]
        
        # Get tips RECEIVED by workers (from payouts table)
        # This shows what bussers, expos, runners received
        cursor.execute("""
            SELECT 
                business_date as date,
                worker_name as worker,
                payout_destination as destination,
                COALESCE(SUM(amount), 0) as total_received
            FROM payouts
            WHERE business_date BETWEEN ? AND ? AND payout_session_id IS NOT NULL
            GROUP BY business_date, worker_name, payout_destination
            ORDER BY business_date, worker_name
        """, (start_date, end_date))
        
        received_map = {}
        for row in cursor.fetchall():
            worker_name = canonical_worker_name(row['worker'])
            key = (row['date'], worker_name)
            if key not in received_map:
                received_map[key] = {
                    'busser': 0,
                    'expo': 0,
                    'runner': 0,
                    'total': 0
                }
            dest = (row['destination'] or '').lower()
            amount = float(row['total_received'] or 0)
            if 'busser' in dest:
                received_map[key]['busser'] += amount
            elif 'expo' in dest:
                received_map[key]['expo'] += amount
            elif 'runner' in dest:
                received_map[key]['runner'] += amount
            received_map[key]['total'] += amount
        
        # Add rows for workers who only received tips (didn't earn their own)
        for (date, worker), amounts in received_map.items():
            # Check if this worker already has a row
            existing = [r for r in report_rows if r['date'] == date and r['worker'] == worker]
            if existing:
                # Update existing row with tips received
                for row in existing:
                    row['tips_received'] = round(amounts['total'], 2)
            else:
                # Add new row for this worker (they only received, didn't earn)
                # Determine job title from received destination
                job_title = 'Staff'
                if amounts['busser'] > 0 and amounts['expo'] == 0 and amounts['runner'] == 0:
                    job_title = 'Busser'
                elif amounts['expo'] > 0 and amounts['busser'] == 0 and amounts['runner'] == 0:
                    job_title = 'Expo'
                elif amounts['runner'] > 0 and amounts['busser'] == 0 and amounts['expo'] == 0:
                    job_title = 'Runner'
                elif amounts['busser'] > 0 or amounts['expo'] > 0 or amounts['runner'] > 0:
                    job_title = 'Support'
                
                report_rows.append({
                    'date': date,
                    'worker': worker,
                    'job_title': job_title,
                    'cash_tips': 0.0,
                    'credit_tips': 0.0,
                    'gratuity': 0.0,
                    'tips_paid_out': 0.0,
                    'net_sales': 0.0,
                    'tips_received': round(amounts['total'], 2),
                    'tip_pct': 0.0
                })
        
        # Sort by date, then worker
        report_rows.sort(key=lambda x: (x['date'], x['worker']))
        
    except Exception as e:
        print(f"Error generating worker report: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()
    
    return jsonify(report_rows)


# ====================
# SUGGEST API
# ====================

@app.route('/api/suggest', methods=['GET'])
def get_suggestions():
    """Get workers who have tips but haven't pushed or committed payouts.
    
    Query params:
    - date: YYYY-MM-DD (optional, defaults to today)
    
    Returns a list of workers with:
    - worker: worker name
    - bucket: location/bucket
    - reason: why they're in the suggestion list
    - cash_tips: cash tips earned
    - credit_tips: credit tips earned
    """
    import sys
    print("DEBUG: get_suggestions called", flush=True)
    sys.stdout.flush()
    
    date_str = request.args.get('date', '').strip()
    
    # Default to today if no date provided
    if not date_str:
        date_str = datetime.now().strftime('%Y-%m-%d')
    
    conn = get_db()
    cursor = conn.cursor()
    
    suggestions = []
    
    try:
        # Get worker/bucket combinations who have pushed or committed payouts for this date
        cursor.execute("""
            SELECT DISTINCT worker_name, bucket
            FROM payouts
            WHERE business_date = ?
        """, (date_str,))
        
        worker_buckets_with_payouts = {(row['worker_name'], row['bucket']) for row in cursor.fetchall()}
        
        # Get worker/bucket combinations who have transactions (server tips pushed)
        cursor.execute("""
            SELECT DISTINCT worker_name, bucket
            FROM transactions
            WHERE business_date = ?
        """, (date_str,))
        
        worker_buckets_with_transactions = {(row['worker_name'], row['bucket']) for row in cursor.fetchall()}
        
        # Combine - these worker/bucket combinations have done something
        worker_buckets_with_action = worker_buckets_with_payouts | worker_buckets_with_transactions
        
        # Get employee GUID to name mapping from JAQ
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        
        emp_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_employees.json',
            'limit': '1000'
        })
        
        employees = {}
        if emp_response.status_code == 200:
            for item in emp_response.json():
                try:
                    emp = json.loads(item.get('json_data', '{}'))
                    guid = emp.get('guid') or emp.get('v2EmployeeGuid')
                    first = emp.get('firstName', '')
                    last = emp.get('lastName', '')
                    name = " ".join(f"{first} {last}".split())
                    if guid and name:
                        employees[guid] = name
                except:
                    continue
        
        # Query time entries from JAQ to get declared cash tips per employee
        # This is more accurate than calculating from orders
        toast_date = date_str.replace('-', '')
        time_file = f"labor_v1_timeEntries_{toast_date}.json"
        
        # Track tips per employee per bucket
        employee_bucket_tips = {}  # {(employee_guid, bucket): {'cash': 0, 'credit': 0}}
        
        # Get job to bucket mapping
        job_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_jobs.json',
            'limit': '1000'
        })
        
        job_to_bucket = {}
        if job_response.status_code == 200:
            for item in job_response.json():
                try:
                    job = json.loads(item.get('json_data', '{}'))
                    job_guid = job.get('guid')
                    job_title = job.get('title', '')
                    if job_guid and job_title:
                        bucket = job_title_to_bucket_id(job_title)
                        if bucket:
                            job_to_bucket[job_guid] = bucket
                except:
                    continue
        
        time_response = requests.get(f"{jaq_url}/query", params={
            'source_file': time_file,
            'limit': '10000'
        })
        
        if time_response.status_code == 200:
            time_entries_count = 0
            cash_tips_found = 0
            for item in time_response.json():
                try:
                    entry = json.loads(item.get('json_data', '{}'))
                    time_entries_count += 1
                    
                    # Get employee GUID
                    emp_ref = entry.get('employeeReference', {})
                    emp_guid = emp_ref.get('guid')
                    
                    if not emp_guid:
                        continue
                    
                    # Get bucket from job
                    job_ref = entry.get('jobReference', {})
                    job_guid = job_ref.get('guid')
                    bucket = job_to_bucket.get(job_guid)
                    
                    if not bucket:
                        continue
                    
                    # Initialize employee/bucket tips entry
                    key = (emp_guid, bucket)
                    if key not in employee_bucket_tips:
                        employee_bucket_tips[key] = {'cash': 0, 'credit': 0}
                    
                    # Get declared cash tips from time entry
                    declared_cash = entry.get('declaredCashTips')
                    if declared_cash is not None:
                        declared_cash = float(declared_cash)
                        if declared_cash > 0:
                            employee_bucket_tips[key]['cash'] += declared_cash
                            cash_tips_found += 1
                    
                    # Also check nonCashTips for credit tips
                    non_cash_tips = entry.get('nonCashTips') or entry.get('declaredNonCashTips')
                    if non_cash_tips is not None:
                        non_cash_tips = float(non_cash_tips)
                        if non_cash_tips > 0:
                            employee_bucket_tips[key]['credit'] += non_cash_tips
                        
                except Exception as e:
                    continue
        
        # Also query orders to get credit tips (as fallback for any missing data)
        orders_file = f"orders_full_{toast_date}.json"
        orders_response = requests.get(f"{jaq_url}/query", params={
            'source_file': orders_file,
            'limit': '100000'
        })
        
        if orders_response.status_code == 200:
            for item in orders_response.json():
                try:
                    order = json.loads(item.get('json_data', '{}'))
                    
                    for check in order.get('checks', []):
                        for payment in check.get('payments', []):
                            tip_amount = float(payment.get('tipAmount') or 0)
                            if tip_amount <= 0:
                                continue
                            
                            server = payment.get('server', {})
                            server_guid = server.get('guid')
                            
                            if not server_guid:
                                continue
                            
                            # For order-based credit tips, we need to determine bucket
                            # This is approximate - we add to all buckets for this employee
                            # A more accurate approach would check the order time against shifts
                            for (guid, bucket), tips in list(employee_bucket_tips.items()):
                                if guid == server_guid:
                                    if payment_type != 'CASH':
                                        employee_bucket_tips[(guid, bucket)]['credit'] += tip_amount
                                
                except Exception as e:
                    continue
        
        # Convert employee GUIDs to names and check against worker_buckets_with_action
        for (emp_guid, bucket), tips in employee_bucket_tips.items():
            emp_name = employees.get(emp_guid)
            if not emp_name:
                continue
            
            # Skip worker/bucket combinations who already have payouts
            if (emp_name, bucket) in worker_buckets_with_action:
                continue
            
            # Skip placeholder bar names
            if emp_name.lower() in {'am bar', 'ww bar', 'low bar', 'ew bar'}:
                continue
            
            cash_tips = tips['cash']
            credit_tips = tips['credit']
            
            # Only include if they have tips
            if cash_tips > 0 or credit_tips > 0:
                suggestions.append({
                    'worker': emp_name,
                    'bucket': bucket,
                    'reason': 'Has tips but no pushed/committed payouts',
                    'cash_tips': round(cash_tips, 2),
                    'credit_tips': round(credit_tips, 2)
                })
        
        # Also check bartenders table for any bartenders not in orders
        cursor.execute("""
            SELECT bartender, bar_name, cash_tips, credit_tips
            FROM bartenders
            WHERE date = ?
        """, (date_str,))
        
        for row in cursor.fetchall():
            worker = row['bartender']
            bucket = row['bar_name']  # bar_name is the bucket for bartenders
            
            if (worker, bucket) in worker_buckets_with_action:
                continue
            
            cash_tips = float(row['cash_tips'] or 0)
            credit_tips = float(row['credit_tips'] or 0)
            
            if cash_tips > 0 or credit_tips > 0:
                # Check if already in suggestions
                if not any(s['worker'] == worker and s.get('bucket') == bucket for s in suggestions):
                    suggestions.append({
                        'worker': worker,
                        'bucket': bucket,
                        'reason': 'Has tips but no pushed/committed payouts',
                        'cash_tips': round(cash_tips, 2),
                        'credit_tips': round(credit_tips, 2)
                    })
        
        # Sort by worker name, then bucket
        suggestions.sort(key=lambda x: (x['worker'], x.get('bucket', '')))
        
    except Exception as e:
        print(f"Error generating suggestions: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()
    
    return jsonify({
        'date': date_str,
        'suggestions': suggestions,
        'count': len(suggestions)
    })


# ====================
# TOAST API CLIENT
# ====================

class ToastClient:
    """Simple Toast API client for fetching data."""
    
    def __init__(self):
        self.client_id = os.getenv('TOAST_CLIENT_ID')
        self.client_secret = os.getenv('TOAST_CLIENT_SECRET')
        self.restaurant_guid = os.getenv('TOAST_RESTAURANT_GUID')
        self.api_host = os.getenv('TOAST_API_HOST', 'https://ws-api.toasttab.com')
        self._token = None
        
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.restaurant_guid)
    
    def _get_access_token(self) -> str:
        """Authenticate and get access token."""
        if self._token:
            return self._token
            
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
            self._token = data.get("accessToken") or (data.get("token") or {}).get("accessToken")
            if not self._token:
                raise Exception("Toast auth did not return accessToken")
            return self._token
        except requests.RequestException as e:
            raise Exception(f"Toast auth error: {e}")
    
    def _get(self, path: str, params: Dict = None) -> Any:
        """Make a GET request to Toast API."""
        resp = self._get_response(path, params=params)
        return resp.json()

    def _get_response(self, path: str, params: Dict = None, url: str = None) -> requests.Response:
        """Make a GET request to Toast API and return the full response."""
        token = self._get_access_token()
        req_url = url or f"{self.api_host}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Toast-Restaurant-External-ID": self.restaurant_guid,
            "Accept": "application/json",
        }
        
        try:
            resp = requests.get(req_url, headers=headers, params=params, timeout=120)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            raise Exception(f"Toast GET {path} error: {e}")

    @staticmethod
    def _normalize_business_date(value: Any) -> Optional[str]:
        """Normalize business date values to YYYY-MM-DD."""
        if value is None:
            return None

        # Handle numeric values such as 20260219
        if isinstance(value, (int, float)):
            value = str(int(value))
        else:
            value = str(value).strip()

        if not value:
            return None

        if len(value) == 8 and value.isdigit():
            return f"{value[:4]}-{value[4:6]}-{value[6:]}"

        if len(value) >= 10 and value[4] == '-' and value[7] == '-':
            return value[:10]

        if 'T' in value and len(value) >= 10:
            return value[:10]

        return None

    @classmethod
    def _extract_order_business_date(cls, order: Dict[str, Any]) -> Optional[str]:
        """Extract a normalized business date from an order object."""
        if not isinstance(order, dict):
            return None

        for key in (
            'businessDate',
            'openedDate',
            'opened',
            'createdDate',
            'closedDate',
            'paidDate',
            'modifiedDate',
            'promisedDate',
            'estimatedFulfillmentDate',
        ):
            normalized = cls._normalize_business_date(order.get(key))
            if normalized:
                return normalized

        return None

    def _fetch_order_detail(self, order_guid: str) -> Optional[Dict]:
        """Fetch full order detail for a single order GUID."""
        try:
            data = self._get(f"/orders/v2/orders/{order_guid}")
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _expand_order_guids(self, order_guids: List[str], max_workers: int = 12) -> List[Dict]:
        """Expand a list of order GUIDs to full order objects."""
        if not order_guids:
            return []

        details: List[Dict] = []
        worker_count = max(1, min(max_workers, len(order_guids)))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {executor.submit(self._fetch_order_detail, guid): guid for guid in order_guids}
            for future in as_completed(futures):
                order = future.result()
                if order:
                    details.append(order)
        return details
    
    def fetch_time_entries(self, start_date: str, end_date: str) -> List[Dict]:
        """Fetch time entries for a date range."""
        results = []
        current = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        
        while current <= end:
            business_date = current.strftime('%Y%m%d')
            try:
                data = self._get("/labor/v1/timeEntries", {"businessDate": business_date})
                if isinstance(data, list):
                    results.extend(data)
                elif isinstance(data, dict) and 'elements' in data:
                    results.extend(data['elements'])
            except Exception as e:
                print(f"Error fetching time entries for {business_date}: {e}")
            current += timedelta(days=1)
        
        return results
    
    def fetch_employees(self) -> List[Dict]:
        """Fetch all employees."""
        try:
            data = self._get("/labor/v1/employees")
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'elements' in data:
                return data['elements']
            return []
        except Exception as e:
            print(f"Error fetching employees: {e}")
            return []
    
    def fetch_jobs(self) -> List[Dict]:
        """Fetch all jobs."""
        try:
            data = self._get("/labor/v1/jobs")
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'elements' in data:
                return data['elements']
            return []
        except Exception as e:
            print(f"Error fetching jobs: {e}")
            return []
    
    def fetch_shifts(self, start_date: str, end_date: str) -> List[Dict]:
        """Fetch shifts for a date range."""
        results = []
        current = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        
        while current <= end:
            business_date = current.strftime('%Y%m%d')
            try:
                data = self._get("/labor/v1/shifts", {"businessDate": business_date})
                if isinstance(data, list):
                    results.extend(data)
                elif isinstance(data, dict) and 'elements' in data:
                    results.extend(data['elements'])
            except Exception as e:
                print(f"Error fetching shifts for {business_date}: {e}")
            current += timedelta(days=1)
        
        return results
    
    def fetch_orders(self, start_date: str, end_date: str) -> List[Dict]:
        """Fetch full order objects for a date range.
        
        The Toast list endpoint may return order GUIDs only. In that case we
        expand GUIDs into full order records via per-order detail requests.
        """
        results = []
        current = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')

        def _extract_chunk(payload: Any) -> List[Any]:
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict):
                for key in ('elements', 'results', 'content', 'items'):
                    v = payload.get(key)
                    if isinstance(v, list):
                        return v
            return []

        def _to_full_orders(rows: List[Any]) -> List[Dict]:
            if not rows:
                return []

            # API may return:
            # - list[str guid]
            # - list[dict full order]
            # - list[dict guid stubs] (e.g., {"guid": "..."} with no checks)
            if isinstance(rows[0], str):
                return self._expand_order_guids([str(g) for g in rows if g])

            full_orders: List[Dict] = []
            stub_guids: List[str] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                guid = str(row.get('guid') or '').strip()
                has_checks = isinstance(row.get('checks'), list)
                if has_checks:
                    full_orders.append(row)
                elif guid:
                    stub_guids.append(guid)

            if stub_guids:
                full_orders.extend(self._expand_order_guids(stub_guids))

            # De-duplicate by guid; keep the richer record.
            dedup: Dict[str, Dict] = {}
            for order in full_orders:
                guid = str(order.get('guid') or '').strip()
                if not guid:
                    continue
                prev = dedup.get(guid)
                if not prev:
                    dedup[guid] = order
                    continue
                prev_checks = len(prev.get('checks') or []) if isinstance(prev, dict) else 0
                cur_checks = len(order.get('checks') or []) if isinstance(order, dict) else 0
                if cur_checks > prev_checks:
                    dedup[guid] = order
            return list(dedup.values())

        def _fetch_orders_for_business_date(business_date: str) -> List[Dict]:
            bdate = business_date.replace('-', '')
            page_size = int(os.getenv('TOAST_ORDERS_PAGE_SIZE', '1000'))
            max_pages = int(os.getenv('TOAST_ORDERS_MAX_PAGES', '50'))
            all_rows: List[Any] = []

            # Strategy 0: Follow Link rel=\"next\" using ordersBulk
            try:
                url = f"{self.api_host}/orders/v2/ordersBulk?businessDate={bdate}"
                for _ in range(max_pages):
                    resp = self._get_response('/orders/v2/ordersBulk', url=url)
                    payload = resp.json()
                    chunk = _extract_chunk(payload)
                    if not chunk:
                        break
                    all_rows.extend(chunk)

                    link_header = resp.headers.get('Link', '')
                    next_url = None
                    if link_header:
                        for part in link_header.split(','):
                            part = part.strip()
                            if part.endswith('rel=\"next\"'):
                                lt = part.split(';')[0].strip()
                                if lt.startswith('<') and lt.endswith('>'):
                                    next_url = lt[1:-1]
                                    break
                    if not next_url:
                        break
                    url = next_url
                if all_rows:
                    return _to_full_orders(all_rows)
            except Exception:
                pass

            # Strategy 1: page/pageSize on ordersBulk
            all_rows = []
            try:
                for page in range(0, max_pages):
                    payload = self._get('/orders/v2/ordersBulk', {'businessDate': bdate, 'page': page, 'pageSize': page_size})
                    chunk = _extract_chunk(payload)
                    if not chunk:
                        break
                    all_rows.extend(chunk)
                if all_rows:
                    return _to_full_orders(all_rows)
            except Exception:
                pass

            # Strategy 2: offset/pageSize on ordersBulk
            all_rows = []
            try:
                for page in range(0, max_pages):
                    offset = page * page_size
                    payload = self._get('/orders/v2/ordersBulk', {'businessDate': bdate, 'offset': offset, 'pageSize': page_size})
                    chunk = _extract_chunk(payload)
                    if not chunk:
                        break
                    all_rows.extend(chunk)
                    if len(chunk) < page_size:
                        break
                if all_rows:
                    return _to_full_orders(all_rows)
            except Exception:
                pass

            # Fallback: legacy orders endpoint
            try:
                payload = self._get('/orders/v2/orders', {'businessDate': bdate})
                chunk = _extract_chunk(payload)
                if not chunk:
                    return []
                return _to_full_orders(chunk)
            except Exception:
                return []

        while current <= end:
            business_date = current.strftime('%Y%m%d')
            try:
                daily = _fetch_orders_for_business_date(business_date)
                results.extend(daily)
            except Exception as e:
                print(f"Error fetching orders for {business_date}: {e}")
            current += timedelta(days=1)
        
        return results
    
    def fetch_cash_entries(self, start_date: str, end_date: str) -> List[Dict]:
        """Fetch cash entries for a date range."""
        results = []
        current = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        
        while current <= end:
            business_date = current.strftime('%Y%m%d')
            try:
                data = self._get("/cashmgmt/v1/entries", {"businessDate": business_date})
                if isinstance(data, list):
                    results.extend(data)
                elif isinstance(data, dict) and 'elements' in data:
                    results.extend(data['elements'])
            except Exception as e:
                print(f"Error fetching cash entries for {business_date}: {e}")
            current += timedelta(days=1)
        
        return results
    
    def fetch_deposits(self, start_date: str, end_date: str) -> List[Dict]:
        """Fetch deposits for a date range."""
        results = []
        current = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        
        while current <= end:
            business_date = current.strftime('%Y%m%d')
            try:
                data = self._get("/cashmgmt/v1/deposits", {"businessDate": business_date})
                if isinstance(data, list):
                    results.extend(data)
                elif isinstance(data, dict) and 'elements' in data:
                    results.extend(data['elements'])
            except Exception as e:
                print(f"Error fetching deposits for {business_date}: {e}")
            current += timedelta(days=1)
        
        return results
    
    def fetch_sales_categories(self) -> List[Dict]:
        """Fetch sales categories."""
        try:
            data = self._get("/configuration/v1/salesCategories")
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'elements' in data:
                return data['elements']
            elif isinstance(data, dict) and 'salesCategories' in data:
                return data['salesCategories']
            return []
        except Exception as e:
            print(f"Error fetching sales categories: {e}")
            return []
    
    def fetch_revenue_centers(self) -> List[Dict]:
        """Fetch revenue centers."""
        try:
            data = self._get("/config/v2/revenueCenters")
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'elements' in data:
                return data['elements']
            return []
        except Exception as e:
            print(f"Error fetching revenue centers: {e}")
            return []


def reload_and_verify_jaq_sources(source_counts: Dict[str, int], timeout_sec: int = 120) -> Dict:
    """Reload JAQ server and verify source_file row counts.

    Returns:
    {
      "in_sync": bool,
      "servers": {
        "JAQ": {"reload_ok": bool, "verify": [...], "error": str|None},
      }
    }
    """
    results: Dict[str, Any] = {"in_sync": True, "servers": {}}
    servers = [
        ("JAQ", os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')),
    ]

    for server_name, server_url in servers:
        server_result: Dict[str, Any] = {
            "url": server_url,
            "reload_ok": False,
            "cleanup_ok": True,
            "verify": [],
            "error": None,
        }

        try:
            # Force source-file refresh first. This avoids stale/duplicate snapshots
            # when loader mtime checks miss updates within the same timestamp bucket.
            for source_file in source_counts.keys():
                try:
                    cleanup_resp = requests.delete(
                        f"{server_url}/cleanup",
                        params={"source_file": source_file},
                        timeout=timeout_sec,
                    )
                    if cleanup_resp.status_code not in (200, 404):
                        server_result["cleanup_ok"] = False
                except Exception:
                    server_result["cleanup_ok"] = False

            reload_resp = requests.post(f"{server_url}/load", timeout=timeout_sec)
            server_result["reload_ok"] = reload_resp.status_code == 200
            if reload_resp.status_code != 200:
                server_result["error"] = f"/load returned {reload_resp.status_code}"
                results["in_sync"] = False
                results["servers"][server_name] = server_result
                continue

            for source_file, expected_count in source_counts.items():
                verify_entry = {
                    "source_file": source_file,
                    "expected_count": int(expected_count),
                    "actual_count": None,
                    "match": False,
                }
                try:
                    schema_resp = requests.get(
                        f"{server_url}/schema",
                        params={"source_file": source_file},
                        timeout=timeout_sec,
                    )
                    if schema_resp.status_code == 200:
                        schema_data = schema_resp.json()
                        actual = int(schema_data.get("total_objects", 0))
                        verify_entry["actual_count"] = actual
                        verify_entry["match"] = actual == int(expected_count)
                    else:
                        verify_entry["actual_count"] = -1
                        verify_entry["match"] = False
                except Exception:
                    verify_entry["actual_count"] = -1
                    verify_entry["match"] = False

                if not verify_entry["match"]:
                    results["in_sync"] = False
                server_result["verify"].append(verify_entry)

        except Exception as e:
            server_result["error"] = str(e)
            results["in_sync"] = False

        results["servers"][server_name] = server_result

    return results


@app.route('/api/fetch/toast', methods=['POST'])
def fetch_toast_data():
    """Fetch data from Toast API for a date range.
    
    Request body:
    - endpoint: str (time_entries, employees, jobs, shifts, orders, cash_entries, deposits, sales_categories, revenue_centers)
    - start_date: YYYY-MM-DD
    - end_date: YYYY-MM-DD
    
    Returns:
    - count: number of records fetched
    - records: list of records (optional, for small datasets)
    - message: status message
    - duration_ms: fetch duration
    """
    data = request.json
    endpoint = data.get('endpoint', '').strip()
    start_date = data.get('start_date', '').strip()
    end_date = data.get('end_date', '').strip()
    
    if not endpoint:
        return jsonify({"error": "Endpoint is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "Start date and end date are required"}), 400
    
    # Validate date format
    try:
        datetime.strptime(start_date, '%Y-%m-%d')
        datetime.strptime(end_date, '%Y-%m-%d')
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
    
    client = ToastClient()
    if not client.is_configured():
        return jsonify({
            "error": "Toast API not configured",
            "message": "Please set TOAST_CLIENT_ID, TOAST_CLIENT_SECRET, and TOAST_RESTAURANT_GUID environment variables"
        }), 503
    
    start_time = time.time()
    
    try:
        if endpoint == 'time_entries':
            records = client.fetch_time_entries(start_date, end_date)
        elif endpoint == 'employees':
            records = client.fetch_employees()
        elif endpoint == 'jobs':
            records = client.fetch_jobs()
        elif endpoint == 'shifts':
            records = client.fetch_shifts(start_date, end_date)
        elif endpoint == 'orders':
            records = client.fetch_orders(start_date, end_date)
        elif endpoint == 'cash_entries':
            records = client.fetch_cash_entries(start_date, end_date)
        elif endpoint == 'deposits':
            records = client.fetch_deposits(start_date, end_date)
        elif endpoint == 'sales_categories':
            records = client.fetch_sales_categories()
        elif endpoint == 'revenue_centers':
            records = client.fetch_revenue_centers()
        else:
            return jsonify({"error": f"Unknown endpoint: {endpoint}"}), 400
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Save to JSON file(s) for JAQ server
        output_files = []
        
        # Source files/counts to verify in JAQ after we save files
        source_counts_for_verify: Dict[str, int] = {}

        if endpoint == 'orders':
            # Split orders by business date and save as individual daily files
            orders_by_date = {}
            for order in records:
                business_date = ToastClient._extract_order_business_date(order)
                if not business_date:
                    continue
                
                if business_date not in orders_by_date:
                    orders_by_date[business_date] = []
                orders_by_date[business_date].append(order)
            
            # Save each date's orders to separate file
            for date_str, daily_orders in orders_by_date.items():
                # Convert YYYY-MM-DD to YYYYMMDD for filename
                date_clean = date_str.replace('-', '')
                daily_file = JSON_DIR / f"orders_full_{date_clean}.json"
                try:
                    with open(daily_file, 'w') as f:
                        json.dump(daily_orders, f, indent=2)
                    output_files.append(str(daily_file))
                    source_counts_for_verify[f"orders_full_{date_clean}.json"] = len(daily_orders)
                except Exception as e:
                    print(f"Error saving orders for {date_str}: {e}")

                # Keep raw snapshot aligned as well.
                raw_file = RAW_ORDERS_DIR / f"{date_str}.json"
                try:
                    with open(raw_file, 'w') as f:
                        json.dump(daily_orders, f, indent=2)
                except Exception as e:
                    print(f"Error saving raw orders for {date_str}: {e}")

            # Also save the combined file as backup
            combined_file = JSON_DIR / f"{endpoint}_{start_date}_{end_date}.json"
            try:
                with open(combined_file, 'w') as f:
                    json.dump(records, f, indent=2)
            except Exception as e:
                print(f"Error saving combined file: {e}")
                
        elif endpoint in ['employees', 'jobs', 'sales_categories', 'revenue_centers']:
            # These don't have date ranges
            try:
                output_file = JSON_DIR / f"{endpoint}.json"
                with open(output_file, 'w') as f:
                    json.dump(records, f, indent=2)
                output_files.append(str(output_file))
            except Exception as e:
                print(f"Error saving {endpoint} file: {e}")
        else:
            # Other endpoints - save with date range in filename
            try:
                output_file = JSON_DIR / f"{endpoint}_{start_date}_{end_date}.json"
                with open(output_file, 'w') as f:
                    json.dump(records, f, indent=2)
                output_files.append(str(output_file))
                print(f"Saved {len(records)} records to {output_file}")
            except Exception as e:
                print(f"Error saving file: {e}")

        # For order fetches, force JAQ reload and verify counts to prevent stale snapshots.
        jaq_sync_result = None
        if endpoint == 'orders' and source_counts_for_verify:
            jaq_sync_result = reload_and_verify_jaq_sources(source_counts_for_verify)
        
        return jsonify({
            "success": True,
            "endpoint": endpoint,
            "count": len(records),
            "duration_ms": duration_ms,
            "message": f"Fetched {len(records)} records" + (f" into {len(output_files)} daily files" if endpoint == 'orders' and output_files else ""),
            "files": output_files[:5] if len(output_files) > 5 else output_files,  # Limit to first 5 files
            "jaq_sync": jaq_sync_result
        })
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        return jsonify({
            "error": str(e),
            "duration_ms": duration_ms,
            "message": f"Failed to fetch {endpoint}: {str(e)}"
        }), 500


# ====================
# SYNC TO JAQ API
# ====================

@app.route('/api/sync/jaq', methods=['POST'])
def sync_to_jaq_api():
    """Sync raw data files to JAQ data lake and trigger reload.
    
    Optional request body:
    - date: YYYY-MM-DD (sync only this date, or omit for all dates)
    
    Returns:
    - success: bool
    - files_synced: number of files copied
    - jaq_status: JAQ server reload status
    """
    data = request.json or {}
    date_str = data.get('date', '').strip()
    
    import subprocess
    import os
    
    # Build command
    script_path = Path(__file__).parent / "sync_to_jaq.py"
    if date_str:
        cmd = ['python3', str(script_path), '--date', date_str]
    else:
        cmd = ['python3', str(script_path)]
    
    try:
        # Run sync script
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(Path(__file__).parent)
        )
        
        # Parse output for file count
        output = result.stdout + result.stderr
        files_synced = 0
        for line in output.split('\n'):
            if 'Synced' in line and 'files' in line:
                try:
                    files_synced = int(line.split('Synced')[1].split('files')[0].strip())
                except:
                    pass
        
        return jsonify({
            "success": result.returncode == 0,
            "files_synced": files_synced,
            "jaq_status": "reloaded" if result.returncode == 0 else "failed",
            "output": output
        })
    except subprocess.TimeoutExpired:
        return jsonify({
            "success": False,
            "error": "Sync timeout - operation took too long"
        }), 504
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ====================
# AUTO-FETCH SCHEDULER
# ====================

def auto_fetch_and_sync():
    """Background job to fetch all endpoints from Toast and sync orders to database.
    
    Runs every hour to keep data fresh.
    """
    import sys
    import logging
    
    # Set up logging for auto-fetch
    log_file = Path(__file__).parent / "auto_fetch.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logger = logging.getLogger('auto_fetch')
    
    try:
        logger.info("Starting auto-fetch job...")
        
        # Calculate date range: trailing N days to now (default 30)
        end_date = datetime.now()
        lookback_days = int(os.getenv('TOAST_AUTO_FETCH_DAYS', '30'))
        start_date = end_date - timedelta(days=lookback_days)
        
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')
        
        logger.info(f"Fetching data for {start_date_str} to {end_date_str}")
        
        # Initialize Toast client
        client = ToastClient()
        if not client.is_configured():
            logger.error("Toast API not configured, skipping auto-fetch")
            return
        
        # Fetch all endpoints
        endpoints = ['employees', 'jobs', 'sales_categories', 'revenue_centers', 
                     'time_entries', 'shifts', 'orders', 'cash_entries', 'deposits']
        
        fetch_results = {}
        
        for endpoint in endpoints:
            try:
                logger.info(f"Fetching {endpoint}...")
                
                if endpoint == 'time_entries':
                    records = client.fetch_time_entries(start_date_str, end_date_str)
                elif endpoint == 'employees':
                    records = client.fetch_employees()
                elif endpoint == 'jobs':
                    records = client.fetch_jobs()
                elif endpoint == 'shifts':
                    records = client.fetch_shifts(start_date_str, end_date_str)
                elif endpoint == 'orders':
                    records = client.fetch_orders(start_date_str, end_date_str)
                elif endpoint == 'cash_entries':
                    records = client.fetch_cash_entries(start_date_str, end_date_str)
                elif endpoint == 'deposits':
                    records = client.fetch_deposits(start_date_str, end_date_str)
                elif endpoint == 'sales_categories':
                    records = client.fetch_sales_categories()
                elif endpoint == 'revenue_centers':
                    records = client.fetch_revenue_centers()
                else:
                    continue
                
                # Save to JSON files with proper naming for JAQ server
                if endpoint == 'orders':
                    # Split orders by business date
                    orders_by_date = {}
                    for order in records:
                        business_date = ToastClient._extract_order_business_date(order)
                        if not business_date:
                            continue
                        if business_date not in orders_by_date:
                            orders_by_date[business_date] = []
                        orders_by_date[business_date].append(order)
                    
                    # Save daily files to both raw and JAQ directories
                    for date_str, daily_orders in orders_by_date.items():
                        date_clean = date_str.replace('-', '')
                        
                        # Save to raw directory (YYYY-MM-DD.json)
                        raw_file = RAW_ORDERS_DIR / f"{date_str}.json"
                        try:
                            with open(raw_file, 'w') as f:
                                json.dump(daily_orders, f, indent=2)
                            logger.info(f"Saved {len(daily_orders)} orders to raw/{date_str}.json")
                        except Exception as e:
                            logger.error(f"Error saving orders to raw/{date_str}.json: {e}")
                        
                        # Save to JAQ directory (orders_full_YYYYMMDD.json)
                        jaq_file = JSON_DIR / f"orders_full_{date_clean}.json"
                        try:
                            with open(jaq_file, 'w') as f:
                                json.dump(daily_orders, f, indent=2)
                            logger.info(f"Saved {len(daily_orders)} orders to JAQ/orders_full_{date_clean}.json")
                        except Exception as e:
                            logger.error(f"Error saving orders to JAQ/orders_full_{date_clean}.json: {e}")
                        
                elif endpoint == 'time_entries':
                    # Split time entries by business date and save as labor_v1_timeEntries_YYYYMMDD.json
                    entries_by_date = {}
                    for entry in records:
                        if isinstance(entry, dict):
                            # Try to get business date from various fields
                            business_date = entry.get('businessDate')
                            if not business_date:
                                # Try to extract from inDate or other timestamp fields
                                in_date = entry.get('inDate')
                                if in_date:
                                    try:
                                        if 'T' in in_date:
                                            business_date = in_date.split('T')[0]
                                        elif len(in_date) >= 10:
                                            business_date = in_date[:10]
                                    except:
                                        pass
                            if not business_date:
                                continue
                            
                            if business_date not in entries_by_date:
                                entries_by_date[business_date] = []
                            entries_by_date[business_date].append(entry)
                    
                    # Save daily files
                    for date_str, daily_entries in entries_by_date.items():
                        date_clean = date_str.replace('-', '')
                        jaq_file = JSON_DIR / f"labor_v1_timeEntries_{date_clean}.json"
                        try:
                            with open(jaq_file, 'w') as f:
                                json.dump(daily_entries, f, indent=2)
                            logger.info(f"Saved {len(daily_entries)} time entries to JAQ/labor_v1_timeEntries_{date_clean}.json")
                        except Exception as e:
                            logger.error(f"Error saving time entries: {e}")
                        
                elif endpoint == 'shifts':
                    # Split shifts by business date and save as labor_v1_shifts_YYYYMMDD.json
                    shifts_by_date = {}
                    for shift in records:
                        if isinstance(shift, dict):
                            business_date = shift.get('businessDate')
                            if business_date:
                                if business_date not in shifts_by_date:
                                    shifts_by_date[business_date] = []
                                shifts_by_date[business_date].append(shift)
                    
                    # Save daily files
                    for date_str, daily_shifts in shifts_by_date.items():
                        date_clean = date_str.replace('-', '')
                        jaq_file = JSON_DIR / f"labor_v1_shifts_{date_clean}.json"
                        try:
                            with open(jaq_file, 'w') as f:
                                json.dump(daily_shifts, f, indent=2)
                            logger.info(f"Saved {len(daily_shifts)} shifts to JAQ/labor_v1_shifts_{date_clean}.json")
                        except Exception as e:
                            logger.error(f"Error saving shifts: {e}")
                        
                elif endpoint == 'cash_entries':
                    # Split cash entries by business date and save as cashmgmt_v1_entries_YYYYMMDD.json
                    entries_by_date = {}
                    for entry in records:
                        if isinstance(entry, dict):
                            business_date = entry.get('businessDate')
                            if not business_date:
                                # Try to extract from transactionDate
                                trans_date = entry.get('transactionDate')
                                if trans_date:
                                    try:
                                        if 'T' in trans_date:
                                            business_date = trans_date.split('T')[0]
                                        elif len(trans_date) >= 10:
                                            business_date = trans_date[:10]
                                    except:
                                        pass
                            if not business_date:
                                continue
                            
                            if business_date not in entries_by_date:
                                entries_by_date[business_date] = []
                            entries_by_date[business_date].append(entry)
                    
                    # Save daily files
                    for date_str, daily_entries in entries_by_date.items():
                        date_clean = date_str.replace('-', '')
                        jaq_file = JSON_DIR / f"cashmgmt_v1_entries_{date_clean}.json"
                        try:
                            with open(jaq_file, 'w') as f:
                                json.dump(daily_entries, f, indent=2)
                            logger.info(f"Saved {len(daily_entries)} cash entries to JAQ/cashmgmt_v1_entries_{date_clean}.json")
                        except Exception as e:
                            logger.error(f"Error saving cash entries: {e}")
                        
                elif endpoint == 'deposits':
                    # Split deposits by business date and save as cashmgmt_v1_deposits_YYYYMMDD.json
                    deposits_by_date = {}
                    for deposit in records:
                        if isinstance(deposit, dict):
                            business_date = deposit.get('businessDate')
                            if not business_date:
                                # Try to extract from depositDate
                                dep_date = deposit.get('depositDate')
                                if dep_date:
                                    try:
                                        if 'T' in dep_date:
                                            business_date = dep_date.split('T')[0]
                                        elif len(dep_date) >= 10:
                                            business_date = dep_date[:10]
                                    except:
                                        pass
                            if not business_date:
                                continue
                            
                            if business_date not in deposits_by_date:
                                deposits_by_date[business_date] = []
                            deposits_by_date[business_date].append(deposit)
                    
                    # Save daily files
                    for date_str, daily_deposits in deposits_by_date.items():
                        date_clean = date_str.replace('-', '')
                        jaq_file = JSON_DIR / f"cashmgmt_v1_deposits_{date_clean}.json"
                        try:
                            with open(jaq_file, 'w') as f:
                                json.dump(daily_deposits, f, indent=2)
                            logger.info(f"Saved {len(daily_deposits)} deposits to JAQ/cashmgmt_v1_deposits_{date_clean}.json")
                        except Exception as e:
                            logger.error(f"Error saving deposits: {e}")
                        
                elif endpoint == 'employees':
                    # Save as both employees.json and labor_v1_employees.json
                    for filename in ['employees.json', 'labor_v1_employees.json']:
                        try:
                            output_file = JSON_DIR / filename
                            with open(output_file, 'w') as f:
                                json.dump(records, f, indent=2)
                            logger.info(f"Saved {len(records)} employees to JAQ/{filename}")
                        except Exception as e:
                            logger.error(f"Error saving employees to {filename}: {e}")
                elif endpoint == 'jobs':
                    # Save as both jobs.json and labor_v1_jobs.json
                    for filename in ['jobs.json', 'labor_v1_jobs.json']:
                        try:
                            output_file = JSON_DIR / filename
                            with open(output_file, 'w') as f:
                                json.dump(records, f, indent=2)
                            logger.info(f"Saved {len(records)} jobs to JAQ/{filename}")
                        except Exception as e:
                            logger.error(f"Error saving jobs to {filename}: {e}")
                elif endpoint == 'revenue_centers':
                    # Save as both revenue_centers.json and config_v2_revenueCenters.json
                    for filename in ['revenue_centers.json', 'config_v2_revenueCenters.json']:
                        try:
                            output_file = JSON_DIR / filename
                            with open(output_file, 'w') as f:
                                json.dump(records, f, indent=2)
                            logger.info(f"Saved {len(records)} revenue centers to JAQ/{filename}")
                        except Exception as e:
                            logger.error(f"Error saving revenue centers to {filename}: {e}")
                elif endpoint == 'sales_categories':
                    # Save as both sales_categories.json and config_v2_salesCategories.json
                    for filename in ['sales_categories.json', 'config_v2_salesCategories.json']:
                        try:
                            output_file = JSON_DIR / filename
                            with open(output_file, 'w') as f:
                                json.dump(records, f, indent=2)
                            logger.info(f"Saved {len(records)} sales categories to JAQ/{filename}")
                        except Exception as e:
                            logger.error(f"Error saving sales categories to {filename}: {e}")
                fetch_results[endpoint] = len(records)
                logger.info(f"Fetched {len(records)} {endpoint}")
                
            except Exception as e:
                logger.error(f"ERROR fetching {endpoint}: {e}")
                fetch_results[endpoint] = f"error: {e}"
        
        logger.info(f"Fetch complete. Results: {fetch_results}")
        
        # Now sync orders to database for the date range
        logger.info("Starting order sync to database...")
        
        current = start_date
        end = end_date
        sync_results = []
        
        while current <= end:
            date_str = current.strftime('%Y-%m-%d')
            try:
                stats = import_orders_for_date(date_str)
                sync_results.append({"date": date_str, "imported": stats['orders_imported']})
                if stats['orders_imported'] > 0:
                    logger.info(f"Synced {date_str}: {stats['orders_imported']} orders")
            except Exception as e:
                logger.error(f"ERROR syncing {date_str}: {e}")
                sync_results.append({"date": date_str, "error": str(e)})
            
            current += timedelta(days=1)
        
        logger.info("Auto-fetch and sync job complete!")
        
        # Clear old data from JAQ databases before reloading to prevent duplicates
        for jaq_name, jaq_db_path in [
            ("JAQ", Path("/home/ubuntu/jaq/json-loader-server/database.db")),
        ]:
            try:
                if jaq_db_path.exists():
                    import sqlite3
                    conn = sqlite3.connect(str(jaq_db_path))
                    cursor = conn.cursor()
                    # Delete records for files we just updated (orders and time entries for the date range)
                    for date_str in [d.strftime('%Y%m%d') for d in [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]]:
                        for pattern in [f'orders_full_{date_str}.json', f'labor_v1_timeEntries_{date_str}.json', 
                                       f'labor_v1_shifts_{date_str}.json', f'cashmgmt_v1_entries_{date_str}.json',
                                       f'cashmgmt_v1_deposits_{date_str}.json']:
                            cursor.execute("DELETE FROM json_objects WHERE source_file = ?", (pattern,))
                    conn.commit()
                    conn.close()
                    logger.info(f"Cleared old {jaq_name} data for updated files")
            except Exception as e:
                logger.warning(f"Could not clear old {jaq_name} data: {e}")
        
        # Trigger JAQ server reloads to pick up new files
        for jaq_name, jaq_url in [
            ("JAQ", os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')),
        ]:
            try:
                reload_response = requests.post(f"{jaq_url}/load", timeout=60)
                if reload_response.status_code == 200:
                    result = reload_response.json()
                    logger.info(f"{jaq_name} reload complete: {result.get('total_objects', 0)} objects in {len(result.get('loaded_files', []))} files")
                else:
                    logger.warning(f"{jaq_name} reload returned status {reload_response.status_code}")
            except Exception as e:
                logger.warning(f"Could not reload {jaq_name} server: {e}")
        
    except Exception as e:
        logger.exception("CRITICAL ERROR in auto-fetch job")


def _labor_watch_dates(num_days: int = 3) -> List[str]:
    """Business dates (YYYY-MM-DD) to include in labor-watch snapshots."""
    today = datetime.now().date()
    return [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(max(1, num_days))]


def _build_labor_snapshot(client: "ToastClient", dates: List[str]) -> Dict[str, Any]:
    """Build reduced labor snapshot for change detection."""
    jobs_raw = client.fetch_jobs() or []
    entries_raw: List[Dict[str, Any]] = []
    for d in dates:
        try:
            entries_raw.extend(client.fetch_time_entries(d, d) or [])
        except Exception:
            continue

    jobs = []
    for j in jobs_raw:
        jobs.append({
            "guid": j.get("guid"),
            "title": j.get("title"),
            "modifiedDate": j.get("modifiedDate"),
            "deleted": bool(j.get("deleted", False)),
        })

    entries = []
    date_keys = {d.replace("-", "") for d in dates}
    for t in entries_raw:
        bdate = (t.get("businessDate") or "")
        if bdate and bdate not in date_keys:
            continue
        emp_ref = t.get("employeeReference") or {}
        job_ref = t.get("jobReference") or {}
        entries.append({
            "guid": t.get("guid"),
            "businessDate": bdate,
            "employeeGuid": emp_ref.get("guid"),
            "jobGuid": job_ref.get("guid"),
            "inDate": t.get("inDate"),
            "outDate": t.get("outDate"),
            "regularHours": t.get("regularHours"),
            "modifiedDate": t.get("modifiedDate"),
            "declaredCashTips": t.get("declaredCashTips"),
            "nonCashTips": t.get("nonCashTips"),
            "gratuity": t.get("gratuity"),
        })

    jobs.sort(key=lambda x: (str(x.get("guid") or ""), str(x.get("title") or "")))
    entries.sort(key=lambda x: (
        str(x.get("businessDate") or ""),
        str(x.get("employeeGuid") or ""),
        str(x.get("inDate") or ""),
        str(x.get("jobGuid") or ""),
    ))

    canonical = json.dumps({"dates": dates, "jobs": jobs, "time_entries": entries}, sort_keys=True, separators=(',', ':'))
    snapshot_hash = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    return {
        "dates": dates,
        "jobs": jobs_raw,
        "jobs_reduced": jobs,
        "time_entries_raw": entries_raw,
        "time_entries_reduced": entries,
        "snapshot_hash": snapshot_hash,
    }


def _persist_labor_files_from_snapshot(snapshot: Dict[str, Any]):
    """Persist labor files used by the app and JAQ reload."""
    jobs_raw = snapshot.get("jobs") or []
    entries_raw = snapshot.get("time_entries_raw") or []

    # Save jobs files.
    for filename in ['jobs.json', 'labor_v1_jobs.json']:
        try:
            with open(JSON_DIR / filename, 'w') as f:
                json.dump(jobs_raw, f, indent=2)
        except Exception as e:
            print(f"Error saving {filename}: {e}")

    # Save time-entries by business date.
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for entry in entries_raw:
        bdate = entry.get("businessDate")
        if not bdate and entry.get("inDate"):
            try:
                dt = parse_toast_datetime(entry.get("inDate"))
                if dt:
                    bdate = dt.strftime('%Y%m%d')
            except Exception:
                bdate = None
        if not bdate:
            continue
        by_date.setdefault(bdate, []).append(entry)

    for date_clean, daily_entries in by_date.items():
        filename = f"labor_v1_timeEntries_{date_clean}.json"
        try:
            with open(JSON_DIR / filename, 'w') as f:
                json.dump(daily_entries, f, indent=2)
        except Exception as e:
            print(f"Error saving {filename}: {e}")


def _reload_jaq_servers():
    for _, jaq_url in [
        ("JAQ", os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')),
    ]:
        try:
            requests.post(f"{jaq_url}/load", timeout=60)
        except Exception:
            continue


def labor_watch_and_sync():
    """Lightweight 1-minute watcher for labor/time-entry and job changes."""
    import logging
    logger = logging.getLogger('labor_watch')
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(Path(__file__).parent / "auto_fetch.log")
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - [labor-watch] %(message)s'))
        logger.addHandler(handler)

    try:
        client = ToastClient()
        if not client.is_configured():
            logger.error("Toast API not configured, skipping labor-watch")
            return

        dates = _labor_watch_dates(3)
        snapshot = _build_labor_snapshot(client, dates)
        current_hash = snapshot["snapshot_hash"]
        previous_hash = get_app_setting("labor_watch_snapshot_hash", "")
        now_iso = datetime.now(timezone.utc).isoformat()
        set_app_setting("labor_watch_last_checked_at", now_iso)

        if current_hash == previous_hash:
            return

        _persist_labor_files_from_snapshot(snapshot)
        _reload_jaq_servers()

        set_app_setting("labor_watch_snapshot_hash", current_hash)
        set_app_setting("labor_watch_last_change_at", now_iso)
        summary = f"Labor/job change detected for dates {', '.join(dates)}"
        set_app_setting("labor_watch_last_change_summary", summary)

        conn = get_db()
        cursor = conn.cursor()
        try:
            details = {
                "dates": dates,
                "job_count": len(snapshot.get("jobs_reduced") or []),
                "time_entry_count": len(snapshot.get("time_entries_reduced") or []),
            }
            cursor.execute("""
                INSERT INTO labor_watch_changes (summary, snapshot_hash, details_json)
                VALUES (?, ?, ?)
            """, (summary, current_hash, json.dumps(details)))
            conn.commit()
        finally:
            conn.close()

        logger.info(summary)
    except Exception as e:
        logger.exception(f"Labor-watch error: {e}")

# Initialize scheduler
scheduler = BackgroundScheduler(daemon=True)

# Add job to run every 30 minutes
scheduler.add_job(
    func=auto_fetch_and_sync,
    trigger=IntervalTrigger(minutes=30),
    id='auto_fetch_job',
    name='Auto Fetch Toast Data',
    replace_existing=True
)

# Add labor-watch job (default every 1 minute, configurable).
labor_watch_interval_minutes = get_labor_watch_interval_minutes(1)
scheduler.add_job(
    func=labor_watch_and_sync,
    trigger=IntervalTrigger(minutes=labor_watch_interval_minutes),
    id='labor_watch_job',
    name='Labor Watch Job',
    replace_existing=True
)

# Start the scheduler
scheduler.start()
print(f"[{datetime.now()}] Auto-fetch scheduler started - runs every 30 minutes")
print(f"[{datetime.now()}] Labor-watch scheduler started - runs every {labor_watch_interval_minutes} minute(s)")

@app.route('/api/admin/auto-fetch/trigger', methods=['POST'])
def trigger_auto_fetch():
    """Manually trigger the auto-fetch job."""
    try:
        # Run in background thread so we don't block the response
        import threading
        thread = threading.Thread(target=auto_fetch_and_sync)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "success": True,
            "message": "Auto-fetch job started in background",
            "check_logs": "Check server logs for progress"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/auto-fetch/status', methods=['GET'])
def get_auto_fetch_status():
    """Get the auto-fetch scheduler status."""
    try:
        job = scheduler.get_job('auto_fetch_job')
        labor_job = scheduler.get_job('labor_watch_job')
        if not job:
            return jsonify({
                "enabled": False,
                "message": "Auto-fetch job not found"
            })

        next_run = job.next_run_time
        labor_next_run = labor_job.next_run_time if labor_job else None
        labor_interval = get_labor_watch_interval_minutes(1)
        return jsonify({
            "enabled": True,
            "interval_minutes": 30,
            "next_run": next_run.isoformat() if next_run else None,
            "job_id": job.id,
            "job_name": job.name,
            "labor_watch": {
                "enabled": labor_job is not None,
                "interval_minutes": labor_interval,
                "next_run": labor_next_run.isoformat() if labor_next_run else None,
                "last_checked_at": get_app_setting("labor_watch_last_checked_at", ""),
                "last_change_at": get_app_setting("labor_watch_last_change_at", ""),
                "last_change_summary": get_app_setting("labor_watch_last_change_summary", "")
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/admin/labor-watch/config', methods=['POST'])
def set_labor_watch_config():
    """Update labor-watch interval (minutes)."""
    data = request.json or {}
    raw = data.get('interval_minutes')
    try:
        minutes = int(raw)
    except Exception:
        return jsonify({"error": "interval_minutes must be an integer"}), 400

    minutes = max(1, min(minutes, 60))
    set_app_setting("labor_watch_interval_minutes", str(minutes))
    scheduler.reschedule_job('labor_watch_job', trigger=IntervalTrigger(minutes=minutes))
    job = scheduler.get_job('labor_watch_job')
    return jsonify({
        "success": True,
        "interval_minutes": minutes,
        "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None
    })


@app.route('/api/admin/labor-watch/changes', methods=['GET'])
def get_labor_watch_changes():
    """Recent labor-watch change log."""
    try:
        limit = int(request.args.get('limit', 20))
    except Exception:
        limit = 20
    limit = max(1, min(limit, 200))

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, detected_at, summary, snapshot_hash, details_json
            FROM labor_watch_changes
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        rows = []
        for r in cursor.fetchall():
            details = {}
            try:
                details = json.loads(r['details_json'] or '{}')
            except Exception:
                details = {}
            rows.append({
                "id": r["id"],
                "detected_at": r["detected_at"],
                "summary": r["summary"],
                "snapshot_hash": r["snapshot_hash"],
                "details": details,
            })
    finally:
        conn.close()

    return jsonify({
        "last_change_at": get_app_setting("labor_watch_last_change_at", ""),
        "last_change_summary": get_app_setting("labor_watch_last_change_summary", ""),
        "last_checked_at": get_app_setting("labor_watch_last_checked_at", ""),
        "changes": rows
    })

# Shutdown scheduler on exit
atexit.register(lambda: scheduler.shutdown())

# ====================
# MAIN
# ====================

if __name__ == '__main__':
    print(f"Database path: {DB_PATH}")
    print(f"Database exists: {DB_PATH.exists()}")
    # Disable debug mode to prevent auto-reloader issues with scheduler
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

@app.route('/api/jaq2/query', methods=['POST'])
def jaq2_query():
    """Execute a QueryDSL query against JAQ2 server.
    
    Accepts raw JSON (not stringified) for easier use:
    {
        "from": {"source_file": "employees.json", "alias": "e"},
        "select": [{"expr": "e.firstName", "alias": "name"}],
        "limit": 10
    }
    
    Or with advanced features:
    {
        "functions": {
            "double": {"params": ["x"], "body": {"multiply": [{"var": "x"}, {"literal": 2}]}}
        },
        "let": {
            "nums": {"field_access": {"object": {"var": "t"}, "field": "numbers"}},
            "doubled": {
                "map": {
                    "array": {"var": "nums"},
                    "function": {
                        "lambda": {
                            "params": ["n"],
                            "body": {"call": {"name": "double", "args": [{"var": "n"}]}}
                        }
                    }
                }
            }
        },
        "from": {"source_file": "test_numbers.json", "alias": "t"},
        "select": [{"expr": "t.id", "alias": "ID"}, {"expression": {"var": "doubled"}, "alias": "Doubled"}]
    }
    
    Returns:
    {
        "success": true,
        "columns": ["ID", "Doubled"],
        "rows": [[1, [2, 4, 6]], [2, [8, 10, 12]]],
        "total_count": 2
    }
    """
    try:
        dsl_query = request.get_json()
        if not dsl_query:
            return jsonify({"success": False, "error": "No query provided"}), 400
        
        result = query_jaq2(dsl_query)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/debug/workers/<date_str>', methods=['GET'])
def debug_workers_for_date(date_str):
    """Debug endpoint to check workers for a date."""
    try:
        toast_date = date_str.replace('-', '')
        jaq_url = os.environ.get('JAQ_SERVER_URL', 'http://localhost:3000')
        
        # Get employees
        emp_response = requests.get(f"{jaq_url}/query", params={
            'source_file': 'labor_v1_employees.json',
            'limit': '1000'
        })
        
        employees = {}
        if emp_response.status_code == 200:
            for item in emp_response.json():
                try:
                    emp = json.loads(item.get('json_data', '{}'))
                    guid = emp.get('guid') or emp.get('v2EmployeeGuid')
                    first = emp.get('firstName', '')
                    last = emp.get('lastName', '')
                    name = " ".join(f"{first} {last}".split())
                    if guid and name:
                        employees[guid] = name
                except:
                    continue
        
        # Check time entries
        time_file = f"labor_v1_timeEntries_{toast_date}.json"
        time_response = requests.get(f"{jaq_url}/query", params={
            'source_file': time_file,
            'limit': '10'
        })
        
        # Check orders
        orders_file = f"orders_full_{toast_date}.json"
        orders_response = requests.get(f"{jaq_url}/query", params={
            'source_file': orders_file,
            'limit': '10000'
        })
        
        # Count activity
        emp_activity = {}
        if orders_response.status_code == 200:
            for item in orders_response.json():
                try:
                    order = json.loads(item.get('json_data', '{}'))
                    for check in order.get('checks', []):
                        for payment in check.get('payments', []):
                            server = payment.get('server', {})
                            emp_guid = server.get('guid')
                            if emp_guid and emp_guid in employees:
                                if emp_guid not in emp_activity:
                                    emp_activity[emp_guid] = {'orders': 0, 'tips': 0}
                                emp_activity[emp_guid]['orders'] += 1
                                emp_activity[emp_guid]['tips'] += float(payment.get('tipAmount') or 0)
                except:
                    continue
        
        # Filter for those with tips
        with_tips = {guid: act for guid, act in emp_activity.items() if act['tips'] > 0}
        
        return jsonify({
            'date': date_str,
            'toast_date': toast_date,
            'employees_loaded': len(employees),
            'time_entries_status': time_response.status_code,
            'orders_status': orders_response.status_code,
            'activity_found': len(emp_activity),
            'with_tips': len(with_tips),
            'workers': [{'name': employees[guid], 'tips': act['tips']} for guid, act in with_tips.items()]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
