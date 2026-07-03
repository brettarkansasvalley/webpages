#!/usr/bin/env python3
import os
import csv
import sys
import json
import uuid
import re
import hashlib
import sqlite3
from datetime import date as dt_date, timedelta
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Any, Dict, Optional, Set, Tuple
import time
import threading
import signal
import subprocess
import tempfile

from fastapi import FastAPI, BackgroundTasks, Query, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse

# Initialize FastAPI app early so route decorators below can bind
app = FastAPI(title="Toast Data Webapp")

import toast_30d_report as t
from toast_client import ToastClient, ToastClientError
from toast_30d_report import OUTPUT_DIR as T_OUTPUT_DIR, process_raw_data_to_formbuilderdb, clear_toast_data  # existing import alias if any
# Optionally import credentials from get_toast.py (local constants)
try:
    from get_toast import (
        CLIENT_ID as GT_CLIENT_ID,
        CLIENT_SECRET as GT_CLIENT_SECRET,
        RESTAURANT_GUID as GT_RESTAURANT_GUID,
        API_HOST as GT_API_HOST,
    )
except Exception:
    GT_CLIENT_ID = None
    GT_CLIENT_SECRET = None
    GT_RESTAURANT_GUID = None
    GT_API_HOST = None



# Helper: map job title to bucket id (shared by multiple routes)
def _job_title_to_bucket_id(title: Optional[str]) -> Optional[str]:
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
    return None


def _resolve_job_title_for(worker_name: str, business_date: str, bucket_id: Optional[str]) -> Optional[str]:
    """Resolve a worker's job_title for a date, optionally filtered by selected bucket.

    Strategy:
      1) Read employees.json to find all GUID aliases for the worker.
      2) Scan labor_shifts_detailed_daily.csv for matching date and any alias.
      3) If bucket_id is provided, return the first job_title whose mapped bucket matches bucket_id.
         Else return the first job_title found for the date.
    """
    try:
        import json as _json
        emp_p = RAW_DIR / "employees.json"
        aliases: Set[str] = set()
        if emp_p.exists():
            with emp_p.open("r", encoding="utf-8") as f:
                emps = _json.load(f) or []
            target = (worker_name or "").strip()
            target_lc = target.lower()
            best = None
            for e in emps:
                first = (e.get("firstName") or "").strip()
                last = (e.get("lastName") or "").strip()
                chosen = (e.get("chosenName") or "").strip()
                full = (first + (" " + last if last else "")).strip()
                for cand in [chosen, full]:
                    if cand and (cand.lower() == target_lc or cand == target):
                        best = e
                        break
                if best:
                    break
            if best:
                for k in ("guid", "id", "v2EmployeeGuid"):
                    v = (best.get(k) or "").strip()
                    if v:
                        aliases.add(v)
        # Now scan detailed shifts
        path = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
        if not path.exists():
            return None
        import csv as _csv
        jt_any = None
        with path.open("r", encoding="utf-8") as fcsv:
            rdr = _csv.DictReader(fcsv)
            for r in rdr:
                if (r.get("date") or "").strip() != (business_date or "").strip():
                    continue
                eg = (r.get("employee_guid") or "").strip()
                if aliases and eg not in aliases:
                    continue
                jt = (r.get("job_title") or r.get("jobtitle") or "").strip()
                if not jt:
                    continue
                if jt_any is None:
                    jt_any = jt
                if bucket_id:
                    bid = _job_title_to_bucket_id(jt)
                    if bid == bucket_id:
                        return jt
        return jt_any
    except Exception:
        return None


# Per-shift worker report (CSV + DB payouts)
@app.get("/report-shifts", response_class=HTMLResponse)
def report_shifts(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    worker: str | None = None,
    job_title: str | None = None,
    limit: int = 2000,
):
    """Show per-shift tips received and tips paid out per worker, job_title, and date.

    Tips Received sources (per shift):
      - cash_tips_per_shift.csv: declared_cash_tips
      - tips_by_server_shift.csv: tips_total (non-cash)
      - gratuity_per_shift.csv: gratuity_total (servers only)
      - Net Sales: initially 0.0 (can be enhanced later)

    Tips Paid Out:
      - From committed transfers in DB, summed for submitter (worker) by bucket (derived from job_title) and date.
    """
    # Normalize dates
    try:
        e_dt = dt_date.fromisoformat(end_date) if end_date else dt_date.today()
    except Exception:
        e_dt = dt_date.today()
    try:
        s_dt = dt_date.fromisoformat(start_date) if start_date else (e_dt - timedelta(days=30))
    except Exception:
        s_dt = e_dt - timedelta(days=30)
    s_str, e_str = s_dt.isoformat(), e_dt.isoformat()

    # Helper: map job title to bucket id (reuse server-tips mapping)
    def job_title_to_bucket_id(title: str | None) -> str | None:
        t = (title or "").strip().lower()
        if not t:
            return None
        if "am sunset server" in t or "am bar" in t:
            return "am_bar"
        if "pm sunset server" in t or "sunset" in t or "low bar" in t:
            return "sunset"
        if "ww server" in t or "west wing" in t or "ww bar" in t:
            return "westwing"
        if "ew server" in t or "east wing" in t:
            return "eastwing"
        return None

    def in_range(d: str) -> bool:
        try:
            return s_str <= d <= e_str
        except Exception:
            return False

    # Aggregation keyed by (date, employee_guid, employee_name, job_title)
    from collections import defaultdict
    rows_map: dict[tuple[str, str, str, str], dict] = {}

    def ensure_row(date: str, eg: str, en: str, jt: str) -> dict:
        key = (date, eg, en, jt)
        if key not in rows_map:
            rows_map[key] = {
                "date": date,
                "employee_guid": eg,
                "employee_name": en,
                "job_title": jt,
                "cash_tips": 0.0,
                "noncash_tips": 0.0,
                "gratuity": 0.0,
                "net_sales": 0.0,
                "tips_paid_out": 0.0,
            }
        return rows_map[key]

    import csv as _csv
    # Load cash tips per shift
    try:
        p = REPORTS_DIR / "cash_tips_per_shift.csv"
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                rdr = _csv.DictReader(f)
                for r in (rdr or []):
                    d = (r.get("date") or "").strip()
                    if not d or not in_range(d):
                        continue
                    en = (r.get("employee_name") or "").strip()
                    if worker and en and worker.strip() and en != worker.strip():
                        continue
                    jt = (r.get("job_title") or r.get("jobtitle") or "").strip()
                    if job_title and jt and job_title.strip() and jt != job_title.strip():
                        continue
                    eg = (r.get("employee_guid") or "").strip()
                    row = ensure_row(d, eg, en, jt)
                    try:
                        row["cash_tips"] += float(r.get("declared_cash_tips") or 0.0)
                    except Exception:
                        pass

    except Exception:
        pass

    # Load Net Sales per shift from CSV export (authoritative), overriding computed zeros
    try:
        p = REPORTS_DIR / "net_sales_by_employee_shift_daily.csv"
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                rdr = _csv.DictReader(f)
                for r in (rdr or []):
                    d = (r.get("date") or "").strip()
                    if not d or not in_range(d):
                        continue
                    eg = (r.get("employee_guid") or "").strip()
                    en = (r.get("employee_name") or "").strip()
                    jt = (r.get("job_title") or r.get("jobtitle") or "").strip()
                    if not (eg and jt and en):
                        continue
                    row = ensure_row(d, eg, en, jt)
                    try:
                        ns = float(r.get("net_sales") or 0.0)
                    except Exception:
                        ns = 0.0
                    # Use CSV net sales if it's non-zero or if current value is zero
                    try:
                        cur_ns = float(row.get("net_sales") or 0.0)
                    except Exception:
                        cur_ns = 0.0
                    if ns != 0.0 or cur_ns == 0.0:
                        row["net_sales"] = round(ns, 2)
    except Exception:
        pass

    # Load non-cash tips per shift (tips_by_server_shift.csv)
    try:
        p = REPORTS_DIR / "tips_by_server_shift.csv"
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                rdr = _csv.DictReader(f)
                for r in (rdr or []):
                    d = (r.get("date") or "").strip()
                    if not d or not in_range(d):
                        continue
                    en = (r.get("employee_name") or "").strip()
                    if worker and en and worker.strip() and en != worker.strip():
                        continue
                    jt = (r.get("job_title") or r.get("jobtitle") or "").strip()
                    if job_title and jt and job_title.strip() and jt != job_title.strip():
                        continue
                    eg = (r.get("employee_guid") or "").strip()
                    row = ensure_row(d, eg, en, jt)
                    try:
                        row["noncash_tips"] += float(r.get("tips_total") or 0.0)
                    except Exception:
                        pass
    except Exception:
        pass

    # Load gratuity per shift (servers)
    try:
        p = REPORTS_DIR / "gratuity_per_shift.csv"
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                rdr = _csv.DictReader(f)
                for r in (rdr or []):
                    d = (r.get("date") or "").strip()
                    if not d or not in_range(d):
                        continue
                    en = (r.get("employee_name") or "").strip()
                    if worker and en and worker.strip() and en != worker.strip():
                        continue
                    jt = (r.get("job_title") or r.get("jobtitle") or "").strip()
                    if job_title and jt and job_title.strip() and jt != job_title.strip():
                        continue
                    eg = (r.get("employee_guid") or "").strip()
                    row = ensure_row(d, eg, en, jt)
                    try:
                        row["gratuity"] += float(r.get("gratuity_total") or 0.0)
                    except Exception:
                        pass
    except Exception:
        pass

    # Use Main Figures from DB for Servers and Bartenders to populate Net Sales (and tips fields)
    def bucket_id_to_display(bid: str | None) -> str | None:
        if not bid:
            return None
        m = {"am_bar": "AM", "westwing": "West Wing", "sunset": "Sunset", "eastwing": "East Wing"}
        return m.get(bid)

    try:
        db = DatabaseManager()
        try:
            cur = db.conn.cursor()
            for row in rows_map.values():
                jt = (row.get("job_title") or "").lower()
                en = row.get("employee_name") or ""
                d = row.get("date") or ""
                if not (en and d and jt):
                    continue
                bucket_id = job_title_to_bucket_id(row.get("job_title"))
                # If looks like server, use servers table main figures
                if "server" in jt:
                    if bucket_id:
                        cur.execute(
                            "SELECT cash_tips, non_cash_tips, gratuity, net_sales FROM servers WHERE date = ? AND server = ? AND bucket = ? ORDER BY id DESC LIMIT 1",
                            (d, en, bucket_id),
                        )
                        r = cur.fetchone()
                        if r:
                            ct, nct, grat, ns = (r[0] or 0.0), (r[1] or 0.0), (r[2] or 0.0), (r[3] or 0.0)
                            row["cash_tips"] = float(ct or 0.0)
                            row["noncash_tips"] = float(nct or 0.0)
                            row["gratuity"] = float(grat or 0.0)
                            row["net_sales"] = float(ns or 0.0)
                # If looks like bartender, use bartenders table main figures
                if ("bar" in jt or "bartender" in jt) and not ("server" in jt):
                    bar_name = bucket_id_to_display(bucket_id)
                    if bar_name:
                        cur.execute(
                            "SELECT cash_tips, credit_tips, net_sales FROM bartenders WHERE date = ? AND bartender = ? AND bar_name = ? ORDER BY id DESC LIMIT 1",
                            (d, en, bar_name),
                        )
                        r = cur.fetchone()
                        if r:
                            ct, cc, ns = (r[0] or 0.0), (r[1] or 0.0), (r[2] or 0.0)
                            row["cash_tips"] = float(ct or 0.0)
                            row["noncash_tips"] = float(cc or 0.0)
                            row["net_sales"] = float(ns or 0.0)
        finally:
            db.close()
    except Exception:
        pass

    # Derive Net Sales per shift from orders/time_entries (same approach as server-tips)
    def _parse_iso(s: str | None):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    def to_float(x):
        try:
            return float(x or 0.0)
        except Exception:
            return 0.0
    try:
        import json as _json
        for row in rows_map.values():
            d = row.get("date") or ""
            eg = row.get("employee_guid") or ""
            jt = row.get("job_title") or ""
            if not (d and eg and jt):
                continue
            bucket_id = job_title_to_bucket_id(jt)
            if not bucket_id:
                continue
            # Load time entries to build shift windows for this employee/date/bucket
            shift_windows: list[tuple[datetime, datetime]] = []
            try:
                te_path = RAW_DIR / "time_entries" / f"{d}.json"
                if te_path.exists():
                    te_list = _json.load(te_path.open("r", encoding="utf-8")) or []
                    biz = None
                    try:
                        biz = t.normalize_business_date(d)
                    except Exception:
                        biz = d.replace("-", "")
                    for te in (te_list or []):
                        if (te.get("businessDate") or "") != (biz or ""):
                            continue
                        guid2 = ((te.get("employeeReference") or {}).get("guid")) or ""
                        if not guid2 or guid2 != eg:
                            continue
                        # Map TE job title to bucket and require match
                        jt2 = te.get("jobTitle") or ((te.get("job") or {}).get("name")) or ""
                        if job_title_to_bucket_id(jt2) != bucket_id:
                            continue
                        st = _parse_iso(te.get("inDate") or te.get("startDate"))
                        en = _parse_iso(te.get("outDate") or te.get("endDate"))
                        if not (st and en and en > st):
                            continue
                        try:
                            st = st.astimezone(timezone.utc)
                            en = en.astimezone(timezone.utc)
                        except Exception:
                            pass
                        shift_windows.append((st, en))
            except Exception:
                shift_windows = []
            if not shift_windows:
                continue
            # Load orders for the date and sum checks for this employee within windows
            net_sales_sum = 0.0
            try:
                orders_path = RAW_DIR / "orders" / f"{d}.json"
                orders_data = []
                if orders_path.exists():
                    orders_data = _json.load(orders_path.open("r", encoding="utf-8")) or []
                for o in (orders_data or []):
                    for c in (o.get("checks") or []):
                        if c.get("voided") or c.get("deleted"):
                            continue
                        # Does this check contain any payment by the employee?
                        has_emp_payment = False
                        for p in (c.get("payments") or []):
                            srv_obj = (p.get("server") or {}) if isinstance(p, dict) else {}
                            psrv_ids = [
                                (srv_obj.get("guid") or ""),
                                (srv_obj.get("id") or ""),
                                (srv_obj.get("v2EmployeeGuid") or ""),
                            ]
                            if any((sid or "").strip() == eg for sid in psrv_ids):
                                has_emp_payment = True
                                break
                        if not has_emp_payment:
                            continue
                        # Within any shift window?
                        check_ts = _parse_iso(c.get("paidDate") or c.get("closedDate") or c.get("openedDate"))
                        if check_ts:
                            try:
                                check_ts = check_ts.astimezone(timezone.utc)
                            except Exception:
                                pass
                        in_window = False
                        if check_ts:
                            for st, en in shift_windows:
                                if st <= check_ts <= en:
                                    in_window = True
                                    break
                        if not in_window:
                            continue
                        # Net sales fallback across common fields
                        amt_field = c.get("amount") or c.get("total") or c.get("net") or c.get("subtotal") or 0.0
                        net_sales_sum += to_float(amt_field)
                row["net_sales"] = round(net_sales_sum, 2)
            except Exception:
                pass
    except Exception:
        pass

    # Join Tips Paid Out from DB committed payouts, grouped per (date, bucket, worker)
    tips_paid_cache: dict[tuple[str, str, str], float] = {}
    try:
        db = DatabaseManager()
        try:
            for key, row in rows_map.items():
                d = row.get("date")
                en = row.get("employee_name") or ""
                jt = row.get("job_title") or ""
                bucket_id = job_title_to_bucket_id(jt)
                if not (d and bucket_id and en):
                    continue
                cache_key = (d, bucket_id, en)
                if cache_key in tips_paid_cache:
                    row["tips_paid_out"] = tips_paid_cache[cache_key]
                    continue
                try:
                    sums = db.get_committed_sums_for_submitter(en, bucket_id, d)
                    total_paid = float(sum((sums or {}).values())) if sums else 0.0
                except Exception:
                    total_paid = 0.0
                tips_paid_cache[cache_key] = round(total_paid, 2)
                row["tips_paid_out"] = tips_paid_cache[cache_key]
        finally:
            db.close()
    except Exception:
        pass

    # Build rows and apply limit
    all_rows = list(rows_map.values())
    # Sort by date desc, then name, then job_title
    all_rows.sort(key=lambda r: (r.get("date") or "", r.get("employee_name") or "", r.get("job_title") or ""), reverse=True)
    if limit and len(all_rows) > int(limit):
        all_rows = all_rows[: int(limit)]

    return templates.TemplateResponse(
        "report_shifts.html",
        {
            "request": request,
            "title": "Shift Tips Report",
            "start_date": s_str,
            "end_date": e_str,
            "worker": worker or "",
            "job_title": job_title or "",
            "rows": all_rows,
        },
    )

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports"
ORDERS_CACHE_DIR = REPORTS_DIR / ".orders_cache"
FETCH_LOG_PATH = REPORTS_DIR / "fetch_log.txt"
FETCH_LOCK_PATH = REPORTS_DIR / "fetch.lock"
RAW_DIR = DATA_DIR / "raw"
FETCH_CANCEL = threading.Event()
# Scheduler controls
SCHEDULER_STOP = threading.Event()
SCHEDULER_THREAD: Optional[threading.Thread] = None

BUILD_STATE_PATH = REPORTS_DIR / ".build_state.json"
MENU_CATEGORY_TTL_SEC = 6 * 60 * 60  # 6 hours
ORDERS_REPORT_KEY = "orders_report"
MENU_CATEGORY_KEY = "menu_category"
SHIFT_ORDERS_REPORT_KEY = "shift_orders_report"
REBUILDABLE_REPORTS = {
    "orders_report.csv",
    "menu_category.csv",
    "shift_orders_report.csv",
}
_BUILD_STATE_LOCK = threading.Lock()
_PENDING_BUILDS: Set[str] = set()
_PENDING_BUILDS_LOCK = threading.Lock()


def _load_build_state() -> Dict[str, Any]:
    with _BUILD_STATE_LOCK:
        try:
            return json.loads(BUILD_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}


def _save_build_state(state: Dict[str, Any]) -> None:
    with _BUILD_STATE_LOCK:
        try:
            BUILD_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            BUILD_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass


def _get_build_state_entry(key: str) -> Dict[str, Any]:
    state = _load_build_state()
    entry = state.get(key)
    return entry if isinstance(entry, dict) else {}


def _update_build_state_entry(key: str, payload: Dict[str, Any]) -> None:
    state = _load_build_state()
    state[key] = payload
    _save_build_state(state)


def _format_ts(ts: Any) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return ""


def _schedule_background_build(task_key: str, background_tasks: Optional[BackgroundTasks], func, *args, **kwargs) -> None:
    """
    Schedule a background build while ensuring only one pending build per task_key.
    If background_tasks is None, run synchronously.
    """
    if background_tasks is None:
        func(*args, **kwargs)
        return

    with _PENDING_BUILDS_LOCK:
        if task_key in _PENDING_BUILDS:
            return
        _PENDING_BUILDS.add(task_key)

    def _runner():
        try:
            func(*args, **kwargs)
        finally:
            with _PENDING_BUILDS_LOCK:
                _PENDING_BUILDS.discard(task_key)

    background_tasks.add_task(_runner)


def _is_build_pending(task_key: str) -> bool:
    with _PENDING_BUILDS_LOCK:
        return task_key in _PENDING_BUILDS


def _orders_report_sources_snapshot() -> Dict[str, Any]:
    orders_dir = RAW_DIR / "orders"
    latest_mtime = 0.0
    file_count = 0
    file_mtimes: Dict[str, float] = {}
    if orders_dir.exists():
        for p in sorted(orders_dir.glob("*.json")):
            try:
                stat = p.stat()
            except OSError:
                continue
            latest_mtime = max(latest_mtime, stat.st_mtime)
            file_count += 1
            file_mtimes[p.name] = stat.st_mtime
    employees_path = RAW_DIR / "employees.json"
    menus_path = RAW_DIR / "menus" / "menus.json"
    employees_mtime = 0.0
    menus_mtime = 0.0
    try:
        if employees_path.exists():
            employees_mtime = employees_path.stat().st_mtime
            latest_mtime = max(latest_mtime, employees_mtime)
    except OSError:
        employees_mtime = 0.0
    try:
        if menus_path.exists():
            menus_mtime = menus_path.stat().st_mtime
            latest_mtime = max(latest_mtime, menus_mtime)
    except OSError:
        menus_mtime = 0.0
    return {
        "latest_source_mtime": latest_mtime,
        "orders_file_count": file_count,
        "file_mtimes": file_mtimes,
        "employees_mtime": employees_mtime,
        "menus_mtime": menus_mtime,
        "snapshot_ts": time.time(),
    }


def _shift_orders_report_snapshot() -> Dict[str, Any]:
    snapshot = _orders_report_sources_snapshot()
    labor_csv = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
    labor_mtime = 0.0
    if labor_csv.exists():
        try:
            labor_mtime = labor_csv.stat().st_mtime
        except OSError:
            labor_mtime = 0.0
    time_entries_dir = RAW_DIR / "time_entries"
    time_entries_mtime = 0.0
    if time_entries_dir.exists():
        try:
            time_entries_mtime = max((p.stat().st_mtime for p in time_entries_dir.glob("*.json")), default=0.0)
        except OSError:
            time_entries_mtime = 0.0
    snapshot.update(
        {
            "labor_mtime": labor_mtime,
            "time_entries_mtime": time_entries_mtime,
        }
    )
    return snapshot


def _write_menu_category_csv() -> None:
    csv_text = _build_menu_category_csv_text()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "menu_category.csv").write_text(csv_text, encoding="utf-8")
    _update_build_state_entry(
        MENU_CATEGORY_KEY,
        {
            "built_at": time.time(),
        },
    )


def _ensure_menu_category_csv(background_tasks: Optional[BackgroundTasks], force: bool = False) -> None:
    path = REPORTS_DIR / "menu_category.csv"
    state = _get_build_state_entry(MENU_CATEGORY_KEY)
    built_at = float(state.get("built_at") or 0.0)
    age = time.time() - built_at
    needs_build = force or (not path.exists()) or (age > MENU_CATEGORY_TTL_SEC)
    if not needs_build:
        return

    def _builder():
        try:
            _write_menu_category_csv()
        except Exception as exc:
            print(f"[reports] Failed to refresh menu_category.csv: {exc}")

    _schedule_background_build(MENU_CATEGORY_KEY, background_tasks, _builder)


def _ensure_orders_report_ready(background_tasks: Optional[BackgroundTasks], force: bool = False) -> None:
    snapshot = _orders_report_sources_snapshot()
    orders_csv = REPORTS_DIR / "orders_report.csv"
    state = _get_build_state_entry(ORDERS_REPORT_KEY)
    recorded_mtime = float(state.get("latest_source_mtime") or 0.0)
    prev_employees_mtime = float(state.get("employees_mtime") or 0.0)
    prev_menus_mtime = float(state.get("menus_mtime") or 0.0)
    needs_build = (
        force
        or (not orders_csv.exists())
        or (snapshot["latest_source_mtime"] > recorded_mtime)
        or (state.get("orders_file_count") != snapshot["orders_file_count"])
        or (snapshot["employees_mtime"] > prev_employees_mtime)
        or (snapshot["menus_mtime"] > prev_menus_mtime)
    )
    if not needs_build:
        return
    _schedule_background_build(ORDERS_REPORT_KEY, background_tasks, _build_orders_report_csv, snapshot, force)


def _build_shift_orders_report(snapshot: Optional[Dict[str, Any]] = None) -> None:
    shift_orders_report_csv(snapshot=snapshot)


def _ensure_shift_orders_report(background_tasks: Optional[BackgroundTasks], force: bool = False) -> None:
    snapshot = _shift_orders_report_snapshot()
    report_path = REPORTS_DIR / "shift_orders_report.csv"
    state = _get_build_state_entry(SHIFT_ORDERS_REPORT_KEY)
    needs_build = (
        force
        or (not report_path.exists())
        or (float(state.get("latest_source_mtime") or 0.0) < snapshot.get("latest_source_mtime", 0.0))
        or (float(state.get("labor_mtime") or 0.0) < snapshot.get("labor_mtime", 0.0))
        or (float(state.get("time_entries_mtime") or 0.0) < snapshot.get("time_entries_mtime", 0.0))
    )
    if not needs_build:
        return
    _schedule_background_build(
        SHIFT_ORDERS_REPORT_KEY,
        background_tasks,
        _build_shift_orders_report,
        snapshot,
    )


def _report_status_messages() -> List[str]:
    messages: List[str] = []
    report_meta = {
        "orders_report.csv": _get_build_state_entry(ORDERS_REPORT_KEY),
        "menu_category.csv": _get_build_state_entry(MENU_CATEGORY_KEY),
        "shift_orders_report.csv": _get_build_state_entry(SHIFT_ORDERS_REPORT_KEY),
    }

    for name, state in report_meta.items():
        key = {
            "orders_report.csv": ORDERS_REPORT_KEY,
            "menu_category.csv": MENU_CATEGORY_KEY,
            "shift_orders_report.csv": SHIFT_ORDERS_REPORT_KEY,
        }.get(name)
        if not key:
            continue
        if _is_build_pending(key):
            messages.append(f"{name} is refreshing in the background.")
            continue
        path = REPORTS_DIR / name
        if not path.exists():
            messages.append(f"{name} has not been generated yet; it will build automatically.")
            continue
        built_at = _format_ts(state.get("built_at"))
        rows = state.get("rows_written")
        extra = f" ({rows} rows)" if rows else ""
        if built_at:
            messages.append(f"{name} last built at {built_at}{extra}.")

    return messages

# Templates & Static
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Best-effort: build menu_category.csv on app startup so it's ready early
@app.on_event("startup")
def _build_menu_category_on_startup():
    try:
        _ensure_menu_category_csv(background_tasks=None, force=False)
        _ensure_orders_report_ready(background_tasks=None, force=False)
        _ensure_shift_orders_report(background_tasks=None, force=False)
    except Exception:
        pass

# Ensure jbhooks modules (config, database, tip_calculator) can be imported
if str(ROOT / "jbhooks") not in sys.path:
    sys.path.append(str(ROOT / "jbhooks"))
from jbhooks.database import DatabaseManager
from jbhooks.tip_calculator import TipCalculator
from jbhooks.config import ADMIN_PASSWORD, BUCKETS, BUCKET_DISPLAY_NAMES, CASH_DRAWERS

# Robust ISO8601 datetime parser for Toast data
def _parse_iso(dt: Any) -> Optional[datetime]:
    if not dt or not isinstance(dt, str):
        return None
    s = dt.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    m = re.match(r"^(.*[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)([+-]\d{2})(\d{2})$", s)
    if m:
        s = f"{m.group(1)}{m.group(2)}:{m.group(3)}"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                return datetime.strptime(dt, fmt)
            except Exception:
                try:
                    return datetime.strptime(s, fmt)
                except Exception:
                    continue
    return None


def _build_credit_tips_per_shift_csv(allowed_dates: Optional[Set[str]] = None) -> int:
    """Generate credit_tips_per_shift.csv under REPORTS_DIR.

    Columns: date,employee_guid,employee_name,job_title,start_time_utc,end_time_utc,credit_card_tips
    Attribution: for each time entry shift, sum non-CASH tipAmount on checks by that employee whose
    timestamp falls within the shift window.
    Returns the number of data rows written (excluding header).
    """
    import json as _json

    # Employee maps
    emp_map: Dict[str, str] = {}
    # For robust matching: alias map of any known identifier -> canonical guid
    alias_to_guid: Dict[str, str] = {}
    try:
        with (RAW_DIR / "employees.json").open("r", encoding="utf-8") as f:
            employees = _json.load(f) or []
        emp_map = t.build_employee_map(employees) if employees else {}
        # collect aliases: guid, id, v2EmployeeGuid
        for e in (employees or []):
            try:
                cg = (e.get("guid") or e.get("id") or e.get("v2EmployeeGuid") or "").strip()
                if cg:
                    alias_to_guid[cg] = e.get("guid") or cg
                for k in ("guid", "id", "v2EmployeeGuid"):
                    v = (e.get(k) or "").strip()
                    if v:
                        alias_to_guid[v] = e.get("guid") or v
            except Exception:
                continue
    except Exception:
        emp_map = {}
        alias_to_guid = {}

    def biz_to_iso(d: str | None) -> str:
        s = (d or "").strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
        try:
            dt_date.fromisoformat(s)
            return s
        except Exception:
            return s

    orders_by_date: Dict[str, list] = {}
    # Load labor shifts detailed to backfill job_title when missing in time entries
    labor_index: Dict[tuple[str, str], list[dict]] = {}
    try:
        path_ls = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
        if path_ls.exists():
            with path_ls.open("r", encoding="utf-8") as fls:
                rdr_ls = csv.DictReader(fls)
                for r in (rdr_ls or []):
                    try:
                        d = (r.get("date") or "").strip()
                        eg = (r.get("employee_guid") or "").strip()
                        if not d or not eg:
                            continue
                        key = (d, eg)
                        labor_index.setdefault(key, []).append({
                            "job_title": r.get("job_title") or r.get("jobtitle") or "",
                            "start": _parse_iso(r.get("start_time_utc")),
                            "end": _parse_iso(r.get("end_time_utc")),
                        })
                    except Exception:
                        continue
    except Exception:
        labor_index = {}
    def load_orders(biz_iso: str) -> list:
        if biz_iso in orders_by_date:
            return orders_by_date[biz_iso]
        p = RAW_DIR / "orders" / f"{biz_iso}.json"
        try:
            if p.exists():
                orders_by_date[biz_iso] = _json.load(p.open("r", encoding="utf-8")) or []
            else:
                orders_by_date[biz_iso] = []
        except Exception:
            orders_by_date[biz_iso] = []
        return orders_by_date[biz_iso]

    def credit_tips_for_window(orders: list, emp_guid: str, st: Optional[datetime], en: Optional[datetime]) -> float:
        if not emp_guid or not st:
            return 0.0
        try:
            st = st.astimezone(timezone.utc)
        except Exception:
            pass
        if en:
            try:
                en = en.astimezone(timezone.utc)
            except Exception:
                pass
        total = 0.0
        for o in (orders or []):
            for c in (o.get("checks") or []):
                if c.get("voided") or c.get("deleted"):
                    continue
                ts = _parse_iso(
                    c.get("paidDate") or c.get("closedDate") or c.get("openedDate")
                    or o.get("paidDate") or o.get("closedDate") or o.get("openedDate")
                )
                if ts:
                    try:
                        ts = ts.astimezone(timezone.utc)
                    except Exception:
                        pass
                in_window = False
                if ts and (en is not None):
                    in_window = (st <= ts <= en)
                elif ts and (en is None):
                    in_window = (st <= ts)
                else:
                    in_window = False
                if not in_window:
                    continue
                for p in (c.get("payments") or []):
                    try:
                        srv_obj = (p.get("server") or {})
                        srv_ids = [
                            (srv_obj.get("guid") or ""),
                            (srv_obj.get("id") or ""),
                            (srv_obj.get("v2EmployeeGuid") or ""),
                        ]
                        # Match if any id resolves to the same canonical guid
                        match = False
                        for sid in srv_ids:
                            sid = (sid or "").strip()
                            if not sid:
                                continue
                            if alias_to_guid.get(sid) == alias_to_guid.get(emp_guid, emp_guid):
                                match = True
                                break
                        if not match:
                            continue
                        ptype = (p.get("type") or "").upper()
                        if ptype == "CASH":
                            continue
                        tip_amt = float(p.get("tipAmount") or 0.0)
                        total += tip_amt
                    except Exception:
                        continue
        return round(total, 2)

    rows: list[list[str]] = [[
        "date","employee_guid","employee_name","job_title","start_time_utc","end_time_utc","credit_card_tips"
    ]]
    te_dir = RAW_DIR / "time_entries"
    try:
        files = sorted([p for p in te_dir.glob("*.json") if p.is_file()])
    except Exception:
        files = []
    for f in files:
        try:
            day_iso = f.stem
            te_list = _json.load(f.open("r", encoding="utf-8")) or []
        except Exception:
            continue
        for te in (te_list or []):
            try:
                b = te.get("businessDate") or ""
                biz_iso = biz_to_iso(b)
                # If a filter is provided, only include shifts whose business date is in the current window
                if allowed_dates is not None and biz_iso not in allowed_dates:
                    continue
                eg = ((te.get("employeeReference") or {}).get("guid")) or ""
                if not eg:
                    continue
                name = emp_map.get(eg, "")
                jt = te.get("jobTitle") or ((te.get("job") or {}).get("name")) or ""
                st = _parse_iso(te.get("inDate") or te.get("startDate"))
                en = _parse_iso(te.get("outDate") or te.get("endDate"))
                st_s = st.isoformat() if st else ""
                en_s = en.isoformat() if en else ""
                # If job title missing, try to infer from labor_shifts_detailed_daily.csv by overlap
                if (not jt) and st and en:
                    try:
                        rows_ls = labor_index.get((biz_iso, eg), [])
                        if rows_ls:
                            # choose the labor row with maximum overlap duration
                            best = None
                            best_ov = 0.0
                            for lr in rows_ls:
                                ls = lr.get("start")
                                le = lr.get("end")
                                if not (ls and le and le > ls):
                                    continue
                                # compute overlap seconds
                                ov = max(0.0, (min(en, le) - max(st, ls)).total_seconds() if (min(en, le) > max(st, ls)) else 0.0)
                                if ov > best_ov:
                                    best_ov = ov
                                    best = lr
                            if best and best.get("job_title"):
                                jt = best.get("job_title")
                    except Exception:
                        pass
                # Load orders for this shift's business date
                orders = load_orders(biz_iso)
                cc = credit_tips_for_window(orders, eg, st, en)
                rows.append([
                    biz_iso,
                    eg,
                    name,
                    str(jt),
                    st_s,
                    en_s,
                    f"{cc:.2f}",
                ])
            except Exception:
                continue

    # Write CSV
    count = max(0, len(rows) - 1)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    outp = REPORTS_DIR / "credit_tips_per_shift.csv"
    try:
        with outp.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            for r in rows:
                w.writerow(r)
    except Exception:
        pass
    return count

def _employee_display_name(e: Dict[str, Any]) -> str:
    """Always use FirstName + LastName to match UI selections and workers table."""
    first = (e.get("firstName") or "").strip()
    last = (e.get("lastName") or "").strip()
    full = (first + (" " + last if last else "")).strip()
    return full


def sync_employees_to_workers() -> int:
    """Ensure all non-deleted Toast employees are present as workers.

    Returns number of workers added.
    """
    p = RAW_DIR / "employees.json"
    if not p.exists():
        return 0
    try:
        with p.open("r", encoding="utf-8") as f:
            employees = json.load(f) or []
    except Exception:
        return 0

    db = DatabaseManager()
    added = 0
    try:
        for e in employees:
            if e.get("deleted") is True:
                continue
            name = _employee_display_name(e)
            if not name:
                continue
            if db.add_worker(name):
                added += 1
    finally:
        db.close()
    return added


def _log(msg: str) -> None:
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        with FETCH_LOG_PATH.open("a", encoding="utf-8") as f:
            from datetime import datetime as _dt
            ts = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def _cancelled(ctx: str = "") -> bool:
    """Return True if cancellation requested; log context one time per check site."""
    if FETCH_CANCEL.is_set():
        if ctx:
            _log(f"Cancellation requested: {ctx}")
        return True
    return False


def run_fetch(days: int = 30) -> None:
    # Reuse logic from toast_30d_report
    t.ensure_dirs()
    # Clear previous log
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        with FETCH_LOG_PATH.open("w", encoding="utf-8") as f:
            f.write("")
    except Exception:
        pass
    # Acquire simple lock to avoid concurrent runs
    try:
        if FETCH_LOCK_PATH.exists():
            _log("Another fetch appears to be running; exiting.")
            return
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        FETCH_LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass
    # Clear any previous cancel request
    try:
        FETCH_CANCEL.clear()
    except Exception:
        pass
    _log(f"Starting fetch for last {days} day(s)")
    token = t.get_access_token()

    # Static data once per run
    try:
        _log("Fetching employees...")
        t.fetch_employees(token)
        _log("Employees fetched.")
    except Exception as e:
        _log(f"WARN: employees fetch failed: {e}")
    try:
        _log("Fetching menus...")
        t.fetch_and_save_menus(token)
        _log("Menus saved.")
    except Exception as e:
        _log(f"WARN: menus fetch failed: {e}")
    try:
        _log("Fetching restaurant config...")
        t.fetch_and_save_restaurant_config(token)
        _log("Restaurant config saved.")
    except Exception as e:
        _log(f"WARN: restaurant config fetch failed: {e}")
    try:
        _log("Fetching revenue centers...")
        t.fetch_and_save_revenue_centers(token)
        _log("Revenue centers saved.")
    except Exception as e:
        _log(f"WARN: revenue centers fetch failed: {e}")
    try:
        _log("Fetching jobs...")
        t.fetch_and_save_jobs(token)
        _log("Jobs saved.")
    except Exception as e:
        _log(f"WARN: jobs fetch failed: {e}")

    # Iterate business dates: tomorrow (optional), today, and last N-1 completed days
    today = dt_date.today()
    rc_map = t.load_revenue_center_map()

    all_item_mix: List[dict] = []
    all_category_rows: List[dict] = []
    all_discount_rows: List[dict] = []
    all_payment_rows: List[dict] = []
    all_payments_by_employee_rows: List[dict] = []
    all_void_rows: List[dict] = []
    all_hourly_rows: List[dict] = []
    all_dim_rows: List[dict] = []
    all_tips_rows: List[dict] = []
    all_cash_rows: List[dict] = []
    all_labor_rows: List[dict] = []
    all_labor_shifts_detailed_rows: List[dict] = []
    all_cash_tips_shifts_rows: List[dict] = []
    all_gratuity_per_shift_rows: List[dict] = []
    all_tips_by_server_shift_rows: List[dict] = []
    all_payments_by_employee_shift_rows: List[dict] = []
    all_net_sales_by_employee_shift_rows: List[dict] = []  # NEW: per-shift net sales rows
    report_rows: List[Dict[str, Any]] = []  # net sales by employee daily

    employees = []
    try:
        with (RAW_DIR / "employees.json").open("r", encoding="utf-8") as f:
            import json
            employees = json.load(f)
    except Exception:
        pass
    emp_map = t.build_employee_map(employees) if employees else {}

    # Load job map once for resolving job titles in detailed labor shifts
    try:
        job_map = t.load_job_map()
    except Exception:
        job_map = {}

    # Write employees report CSV
    if employees:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        fields = [
            "guid",
            "v2EmployeeGuid",
            "firstName",
            "lastName",
            "chosenName",
            "email",
            "phoneNumber",
            "jobTitles",
            "deleted",
            "createdDate",
            "modifiedDate",
        ]
        with (REPORTS_DIR / "employees.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for e in employees:
                row = {k: (e.get(k) if e.get(k) is not None else "") for k in fields}
                # Resolve job titles from jobReferences using job_map, join with '; '
                titles: List[str] = []
                try:
                    for ref in (e.get("jobReferences") or []):
                        guid = (ref or {}).get("guid")
                        if guid and job_map:
                            title = job_map.get(guid)
                            if title:
                                titles.append(str(title))
                except Exception:
                    pass
                # de-duplicate while preserving order
                if titles:
                    seen = set()
                    dedup = []
                    for tstr in titles:
                        if tstr in seen:
                            continue
                        seen.add(tstr)
                        dedup.append(tstr)
                    row["jobTitles"] = "; ".join(dedup)
                else:
                    row["jobTitles"] = ""
                w.writerow(row)

        # After employees.json is updated, sync to workers table
        try:
            sync_employees_to_workers()
        except Exception:
            pass

    _log("Starting per-day pulls...")
    try:
        # Build list of dates to fetch: include tomorrow and today, then past days
        dates: List[dt_date] = []
        try:
            # Try to include tomorrow to catch UTC business date rollover
            dates.append(today + timedelta(days=1))
        except Exception:
            pass
        # Include today (current in-progress business day)
        dates.append(today)
        # Include the previous 'days' days (completed business days)
        for i in range(days):
            dates.append(today - timedelta(days=i + 1))

        total = len(dates)
        for idx, d in enumerate(dates):
            if _cancelled("before next day"):
                break
            biz = d.isoformat()
            _log(f"[Day {idx+1}/{total}] {biz}: starting")

            # Orders
            _log(f"[Day {idx+1}/{total}] {biz}: fetching orders...")
            _t0 = time.perf_counter()
            orders = t.get_orders_by_business_date(token, biz)
            t.save_orders_for_day(biz, orders)
            _t1 = time.perf_counter()
            try:
                checks_cnt = 0
                pays_cnt = 0
                for o in (orders or []):
                    for c in (o.get("checks") or []):
                        if c.get("voided") or c.get("deleted"):
                            continue
                        checks_cnt += 1
                        pays_cnt += len(c.get("payments") or [])
                _log(f"[Day {idx+1}/{total}] {biz}: orders saved: {len(orders)}; checks:{checks_cnt}; payments:{pays_cnt}; took {(_t1-_t0):.2f}s")
            except Exception:
                _log(f"[Day {idx+1}/{total}] {biz}: orders saved. took {(_t1-_t0):.2f}s")
            if _cancelled(f"after orders for {biz}"):
                break

            # Payments (raw API response)
            try:
                _log(f"[Day {idx+1}/{total}] {biz}: fetching payments...")
                _t0 = time.perf_counter()
                payments_json = t.get_payments_by_business_date(token, biz)
                t.save_payments_for_day(biz, payments_json)
                _t1 = time.perf_counter()
                _log(f"[Day {idx+1}/{total}] {biz}: payments saved; took {(_t1-_t0):.2f}s")
            except Exception as e:
                payments_json = []
                _log(f"[Day {idx+1}/{total}] {biz}: WARN failed to fetch payments: {e}")
            if _cancelled(f"after payments for {biz}"):
                break

            # Payment details by GUID
            try:
                _log(f"[Day {idx+1}/{total}] {biz}: extracting payment GUIDs...")
                payment_guids = t._extract_payment_guids(payments_json)
                _log(f"[Day {idx+1}/{total}] {biz}: found {len(payment_guids)} payment GUIDs")
                for gid in payment_guids:
                    if not gid:
                        continue
                    out_path = RAW_DIR / "paymentsid" / f"{gid}.json"
                    if out_path.exists():
                        continue  # skip already cached
                    try:
                        detail = t.get_payment_by_guid(token, gid)
                        t.save_payment_by_guid(gid, detail)
                    except Exception as e:
                        _log(f"[Day {idx+1}/{total}] {biz}: WARN failed to fetch payment detail {gid}: {e}")
                _log(f"[Day {idx+1}/{total}] {biz}: payment details processed")
            except Exception as e:
                _log(f"[Day {idx+1}/{total}] {biz}: WARN failed to process payment details: {e}")
            if _cancelled(f"after payment details for {biz}"):
                break

            # Time entries
            try:
                _log(f"[Day {idx+1}/{total}] {biz}: fetching time entries...")
                _t0 = time.perf_counter()
                time_entries = t.get_time_entries_by_business_date(token, biz)
                t.save_time_entries_for_day(biz, time_entries)
                _t1 = time.perf_counter()
                _log(f"[Day {idx+1}/{total}] {biz}: time entries saved: {len(time_entries)}; took {(_t1-_t0):.2f}s")
            except Exception:
                time_entries = []
                _log(f"[Day {idx+1}/{total}] {biz}: WARN failed to fetch time entries")
            if _cancelled(f"after time entries for {biz}"):
                break

            # Shifts
            try:
                # Shifts expect startDate inclusive and endDate exclusive
                # Shifts API requires ISO-8601 with milliseconds and numeric UTC offset (e.g. 2016-01-01T14:13:12.000-0000)
                start_dt = datetime(d.year, d.month, d.day, 0, 0, 0)
                next_dt = start_dt + timedelta(days=1)
                start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000-0000")
                end_iso = next_dt.strftime("%Y-%m-%dT%H:%M:%S.000-0000")
                _log(f"[Day {idx+1}/{total}] {biz}: fetching shifts...")
                _t0 = time.perf_counter()
                shifts = t.get_shifts_for_day(token, start_iso, end_iso)
                t.save_shifts_for_day(biz, shifts)
                _t1 = time.perf_counter()
                _log(f"[Day {idx+1}/{total}] {biz}: shifts saved: {len(shifts)}; took {(_t1-_t0):.2f}s")
            except Exception as e:
                shifts = []
                _log(f"[Day {idx+1}/{total}] {biz}: WARN failed to fetch shifts: {e}")
            if _cancelled(f"after shifts for {biz}"):
                break

            # Cash/deposits
            try:
                _log(f"[Day {idx+1}/{total}] {biz}: fetching cash entries...")
                _t0 = time.perf_counter()
                entries = t.get_cash_entries_by_business_date(token, biz)
                t.save_cash_entries_for_day(biz, entries)
                _t1 = time.perf_counter()
                _log(f"[Day {idx+1}/{total}] {biz}: cash entries saved: {len(entries)}; took {(_t1-_t0):.2f}s")
            except Exception:
                entries = []
                _log(f"[Day {idx+1}/{total}] {biz}: WARN failed to fetch cash entries")
            if _cancelled(f"after cash entries for {biz}"):
                break
            try:
                _log(f"[Day {idx+1}/{total}] {biz}: fetching deposits...")
                _t0 = time.perf_counter()
                deposits = t.get_deposits_by_business_date(token, biz)
                t.save_deposits_for_day(biz, deposits)
                _t1 = time.perf_counter()
                _log(f"[Day {idx+1}/{total}] {biz}: deposits saved: {len(deposits)}; took {(_t1-_t0):.2f}s")
            except Exception:
                pass
            if _cancelled(f"after deposits for {biz}"):
                break

            # Aggregations from orders
            _log(f"[Day {idx+1}/{total}] {biz}: aggregating daily reports from orders...")
            imx, cat, disc, pay, voids = t.aggregate_daily_reports(biz, orders)
            all_item_mix.extend(imx)
            all_category_rows.extend(cat)
            all_discount_rows.extend(disc)
            all_payment_rows.extend(pay)
            all_void_rows.extend(voids)
            try:
                _log(f"[Day {idx+1}/{total}] {biz}: aggregates — item_mix:{len(imx)}, categories:{len(cat)}, discounts:{len(disc)}, payments:{len(pay)}, voids:{len(voids)}")
            except Exception:
                pass
            if _cancelled(f"during aggregation for {biz}"):
                break
            all_hourly_rows.extend(t.aggregate_hourly_sales(biz, orders))
            ot, do, rc = t.aggregate_sales_by_dimensions(biz, orders, rc_map)
            all_dim_rows.extend(ot + do + rc)
            all_tips_rows.extend(t.aggregate_tips_by_server(biz, orders))
            # New: payments by employee (tender breakdown)
            try:
                all_payments_by_employee_rows.extend(
                    t.aggregate_payments_by_employee(biz, orders, emp_map)
                )
                _log(f"[Day {idx+1}/{total}] {biz}: payments by employee rows added.")
            except Exception:
                pass
            all_cash_rows.extend(t.summarize_cash_entries_day(biz, entries))
            all_labor_rows.extend(t.summarize_labor_hours_day(biz, time_entries))
            # Detailed labor shifts (with job info and UTC timestamps)
            try:
                all_labor_shifts_detailed_rows.extend(
                    t.summarize_labor_shifts_detailed_day(biz, time_entries, job_map)
                )
                _log(f"[Day {idx+1}/{total}] {biz}: labor shifts detailed rows added.")
            except Exception:
                pass
            if _cancelled(f"after labor summaries for {biz}"):
                break
            # Cash tips per shift from time entries (declaredCashTips)
            try:
                all_cash_tips_shifts_rows.extend(
                    t.summarize_cash_tips_shifts_day(biz, time_entries, job_map, emp_map)
                )
                _log(f"[Day {idx+1}/{total}] {biz}: cash tips per shift rows added.")
            except Exception:
                pass
            if _cancelled(f"after cash tips per shift for {biz}"):
                break
            # Gratuity per shift from time entries and orders
            try:
                all_gratuity_per_shift_rows.extend(
                    t.summarize_gratuity_per_shift_day(biz, time_entries, orders, job_map, emp_map)
                )
                _log(f"[Day {idx+1}/{total}] {biz}: gratuity per shift rows added.")
            except Exception:
                pass
            if _cancelled(f"after gratuity per shift for {biz}"):
                break

            # Tips by server per shift from time entries and orders (all tenders)
            try:
                all_tips_by_server_shift_rows.extend(
                    t.summarize_tips_by_server_shift_day(biz, time_entries, orders, job_map, emp_map)
                )
                _log(f"[Day {idx+1}/{total}] {biz}: tips by server per shift rows added.")
            except Exception:
                pass
            if _cancelled(f"after tips by server per shift for {biz}"):
                break

            # Payments by employee per shift (grouped by tender and subtype)
            try:
                all_payments_by_employee_shift_rows.extend(
                    t.summarize_payments_by_employee_shift_day(biz, time_entries, orders, job_map, emp_map)
                )
                _log(f"[Day {idx+1}/{total}] {biz}: payments by employee per shift rows added.")
            except Exception:
                pass
            if _cancelled(f"after payments by employee per shift for {biz}"):
                break

            # Per-shift net sales by employee (primary + fallback)
            try:
                ns_shift = t.aggregate_net_sales_by_employee_shift_day(biz, orders, time_entries, emp_map)
            except Exception:
                ns_shift = []
            # Fallback: derive from detailed labor shifts when helper produces no rows
            try:
                if not ns_shift:
                    def _piso(s: str | None):
                        if not s:
                            return None
                        try:
                            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
                        except Exception:
                            return None
                    labor_day_rows = t.summarize_labor_shifts_detailed_day(biz, time_entries, job_map) or []
                    rows_out = []
                    # Pre-normalize businessDate
                    try:
                        b_yyyymmdd = t.normalize_business_date(biz)
                    except Exception:
                        b_yyyymmdd = biz.replace("-", "")
                    for lr in labor_day_rows:
                        eg = (lr.get("employee_guid") or "").strip()
                        if not eg:
                            continue
                        name = (lr.get("employee_name") or "").strip()
                        jt = (lr.get("job_title") or lr.get("jobtitle") or "").strip()
                        st = _piso(lr.get("start_time_utc") or lr.get("start") or lr.get("inDate"))
                        en = _piso(lr.get("end_time_utc") or lr.get("end") or lr.get("outDate"))
                        if not (st and en and en > st):
                            continue
                        net_sales_sum = 0.0
                        checks_count = 0
                        cc_tips_sum = 0.0
                        tips_total_sum = 0.0
                        cash_tips = 0.0
                        # Sum declared cash tips for the employee on this date
                        try:
                            for te in (time_entries or []):
                                if (te.get("businessDate") or "") != b_yyyymmdd:
                                    continue
                                guid_te = ((te.get("employeeReference") or {}).get("guid")) or ""
                                if guid_te != eg:
                                    continue
                                dct = te.get("declaredCashTips")
                                cash_tips += float(dct) if dct is not None else 0.0
                        except Exception:
                            cash_tips = 0.0
                        # Scan orders and checks
                        for o in (orders or []):
                            order_srv = ((o.get("server") or {}).get("guid") or "").strip()
                            for c in (o.get("checks") or []):
                                if c.get("voided") or c.get("deleted"):
                                    continue
                                has_emp_payment = False
                                for p in (c.get("payments") or []):
                                    try:
                                        srv_obj = (p.get("server") or {}) if isinstance(p, dict) else {}
                                        psrv_ids = [
                                            (srv_obj.get("guid") or ""),
                                            (srv_obj.get("id") or ""),
                                            (srv_obj.get("v2EmployeeGuid") or ""),
                                        ]
                                        if any((sid or "").strip() == eg for sid in psrv_ids):
                                            has_emp_payment = True
                                            ptype = (p.get("type") or "").upper()
                                            if ptype != "CASH":
                                                try:
                                                    cc_tips_sum += float(p.get("tipAmount") or 0.0)
                                                except Exception:
                                                    pass
                                            try:
                                                tips_total_sum += float(p.get("tipAmount") or 0.0)
                                            except Exception:
                                                pass
                                    except Exception:
                                        continue
                                if not has_emp_payment and order_srv != eg:
                                    continue
                                ts = _piso(c.get("paidDate") or c.get("closedDate") or c.get("openedDate"))
                                if not (ts and st <= ts <= en):
                                    continue
                                amt = c.get("amount") or c.get("total") or c.get("net") or c.get("subtotal") or 0.0
                                try:
                                    net_sales_sum += float(amt or 0.0)
                                except Exception:
                                    pass
                                checks_count += 1
                        rows_out.append({
                            "date": biz,
                            "employee_guid": eg,
                            "employee_name": name,
                            "job_title": jt,
                            "start_time_utc": st.isoformat(),
                            "end_time_utc": en.isoformat(),
                            "net_sales": f"{net_sales_sum:.2f}",
                            "checks_count": checks_count,
                            "credit_card_tips": f"{cc_tips_sum:.2f}",
                            "cash_tips": f"{cash_tips:.2f}",
                            "tips_total": f"{tips_total_sum:.2f}",
                        })
                    ns_shift = rows_out
                _log(f"[Day {idx+1}/{total}] {biz}: shift net sales rows: {len(ns_shift)}")
            except Exception:
                ns_shift = []
            if ns_shift:
                all_net_sales_by_employee_shift_rows.extend(ns_shift)

            # Build per-employee net sales report row (with cash_tips and credit_card_tips)
            try:
                _log(f"[Day {idx+1}/{total}] {biz}: computing per-employee net sales and tips...")
                # Tips total by employee
                tips_list = t.aggregate_tips_by_server(biz, orders)
                tips_by_guid: Dict[str, float] = {}
                for r in tips_list:
                    guid_r = r.get("employee_guid")
                    if not guid_r:
                        continue
                    try:
                        tips_by_guid[guid_r] = float(r.get("tips_total", 0))
                    except Exception:
                        tips_by_guid[guid_r] = 0.0

                # Cash tips from time entries declaredCashTips
                cash_declared_by_guid: Dict[str, float] = {}
                try:
                    b_yyyymmdd = t.normalize_business_date(biz)
                except Exception:
                    b_yyyymmdd = biz.replace("-", "")
                for te in (time_entries or []):
                    try:
                        if (te.get("businessDate") or "") != b_yyyymmdd:
                            continue
                        guid_te = ((te.get("employeeReference") or {}).get("guid")) or ""
                        if not guid_te:
                            continue
                        dct = te.get("declaredCashTips")
                        cash = float(dct) if dct is not None else 0.0
                        cash_declared_by_guid[guid_te] = cash_declared_by_guid.get(guid_te, 0.0) + cash
                    except Exception:
                        continue

                # Credit card tips from non-CASH payments
                cc_tips_by_guid: Dict[str, float] = {}
                def _to_float(x):
                    try:
                        return float(x)
                    except Exception:
                        return 0.0
                for o in (orders or []):
                    for c in (o.get("checks") or []):
                        if c.get("voided") or c.get("deleted"):
                            continue
                        for p in (c.get("payments") or []):
                            try:
                                srv = (p.get("server") or {}).get("guid")
                                if not srv:
                                    continue
                                ptype = (p.get("type") or "").upper()
                                if ptype == "CASH":
                                    continue
                                tip_amt = _to_float(p.get("tipAmount"))
                                if tip_amt:
                                    cc_tips_by_guid[srv] = cc_tips_by_guid.get(srv, 0.0) + tip_amt
                            except Exception:
                                continue

                # Daily components and net sales per employee
                components_by_emp = t.compute_daily_components_by_employee(orders)
                daily = t.compute_daily_net_sales_by_employee(orders)
                # Gift card sales per employee (based on selections displayName and price)
                gift_by_emp = t.compute_daily_giftcard_sales_by_employee(orders)
                for guid, (net_sales, total_sales, cnt) in sorted(daily.items()):
                    it_total, disc_total, svc_total = components_by_emp.get(guid, (0.0, 0.0, 0.0))
                    gc_sales = float(gift_by_emp.get(guid, 0.0))
                    actual_net = float(net_sales) - gc_sales
                    report_rows.append(
                        {
                            "date": biz,
                            "employee_guid": guid,
                            "employee_name": emp_map.get(guid, ""),
                            "total_sales": f"{total_sales:.2f}",
                            "items_total": f"{it_total:.2f}",
                            "discounts_total": f"{disc_total:.2f}",
                            "service_charges_total": f"{svc_total:.2f}",
                            "net_sales": f"{net_sales:.2f}",
                            "giftcard_sales": f"{gc_sales:.2f}",
                            "actual_net_sales": f"{actual_net:.2f}",
                            "cash_tips": f"{cash_declared_by_guid.get(guid, 0.0):.2f}",
                            "credit_card_tips": f"{cc_tips_by_guid.get(guid, 0.0):.2f}",
                            "tips_total": f"{tips_by_guid.get(guid, 0.0):.2f}",
                            "checks_count": cnt,
                        }
                    )
                _log(f"[Day {idx+1}/{total}] {biz}: per-employee rows added: {len(daily)}")
            except Exception as e:
                _log(f"  WARN: failed building net sales report rows: {e}")

            _log(f"[Day {idx+1}/{total}] {biz}: finished")
        # Write net sales by employee daily report
        try:
            _log(f"Writing net_sales_by_employee_daily.csv ({len(report_rows)} rows)...")
            t.write_csv_report(report_rows)
            _log("net_sales_by_employee_daily.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write net_sales_by_employee_daily.csv: {e}")

        # Write remaining reports with row counts
        try:
            _log(f"Writing item_mix_daily.csv ({len(all_item_mix)} rows)...")
            t.write_item_mix_csv(all_item_mix)
            _log("item_mix_daily.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write item_mix_daily.csv: {e}")
        try:
            _log(f"Writing category_sales_daily.csv ({len(all_category_rows)} rows)...")
            with (REPORTS_DIR / "category_sales_daily.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["date", "sales_category_guid", "sales_category_name", "net_sales"])
                w.writeheader()
                for r in all_category_rows:
                    w.writerow(r)
            _log("category_sales_daily.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write category_sales_daily.csv: {e}")
        try:
            _log(f"Writing discounts_daily.csv ({len(all_discount_rows)} rows)...")
            with (REPORTS_DIR / "discounts_daily.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["date", "scope", "discount_name", "discount_guid", "count", "discount_amount_total"])
                w.writeheader()
                for r in all_discount_rows:
                    w.writerow(r)
            _log("discounts_daily.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write discounts_daily.csv: {e}")
        try:
            _log(f"Writing payments_tips_daily.csv ({len(all_payment_rows)} rows)...")
            with (REPORTS_DIR / "payments_tips_daily.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["date", "payment_type", "amount_total", "tip_amount_total", "count"])
                w.writeheader()
                for r in all_payment_rows:
                    w.writerow(r)
            _log("payments_tips_daily.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write payments_tips_daily.csv: {e}")
        try:
            _log(f"Writing voids_daily.csv ({len(all_void_rows)} rows)...")
            with (REPORTS_DIR / "voids_daily.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["date", "level", "count", "amount_total"])
                w.writeheader()
                for r in all_void_rows:
                    w.writerow(r)
            _log("voids_daily.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write voids_daily.csv: {e}")
        try:
            _log(f"Writing tips_by_server_daily.csv ({len(all_tips_rows)} rows)...")
            t.write_tips_by_server_csv(all_tips_rows, emp_map)
            _log("tips_by_server_daily.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write tips_by_server_daily.csv: {e}")
        try:
            _log(f"Writing payments_by_employee_daily.csv ({len(all_payments_by_employee_rows)} rows)...")
            t.write_payments_by_employee_csv(all_payments_by_employee_rows)
            _log("payments_by_employee_daily.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write payments_by_employee_daily.csv: {e}")
        try:
            _log(f"Writing cash_summary_daily.csv ({len(all_cash_rows)} rows)...")
            with (REPORTS_DIR / "cash_summary_daily.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["date", "type", "reason", "amount_total", "count"])
                w.writeheader()
                for r in all_cash_rows:
                    w.writerow(r)
            _log("cash_summary_daily.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write cash_summary_daily.csv: {e}")
        try:
            _log(f"Writing hourly_sales_daily.csv ({len(all_hourly_rows)} rows)...")
            t.write_hourly_sales_csv(all_hourly_rows)
            _log("hourly_sales_daily.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write hourly_sales_daily.csv: {e}")
        try:
            _log(f"Writing sales_by_dimension_daily.csv ({len(all_dim_rows)} rows)...")
            t.write_sales_dimensions_csv(all_dim_rows)
            _log("sales_by_dimension_daily.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write sales_by_dimension_daily.csv: {e}")
        try:
            _log(f"Writing labor_hours_daily.csv ({len(all_labor_rows)} rows)...")
            with (REPORTS_DIR / "labor_hours_daily.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["date", "employee_guid", "employee_name", "shifts_count", "hours_total"])
                w.writeheader()
                for r in all_labor_rows:
                    w.writerow(r)
            _log("labor_hours_daily.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write labor_hours_daily.csv: {e}")
        try:
            _log(f"Writing labor_shifts_detailed_daily.csv ({len(all_labor_shifts_detailed_rows)} rows)...")
            t.write_labor_shifts_detailed_csv(all_labor_shifts_detailed_rows, emp_map)
            _log("labor_shifts_detailed_daily.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write labor_shifts_detailed_daily.csv: {e}")
        try:
            _log(f"Writing cash_tips_per_shift.csv ({len(all_cash_tips_shifts_rows)} rows)...")
            t.write_cash_tips_shifts_csv(all_cash_tips_shifts_rows)
            _log("cash_tips_per_shift.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write cash_tips_per_shift.csv: {e}")
        try:
            _log(f"Writing gratuity_per_shift_daily.csv ({len(all_gratuity_per_shift_rows)} rows)...")
            t.write_gratuity_per_shift_csv(all_gratuity_per_shift_rows)
            _log("gratuity_per_shift_daily.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write gratuity_per_shift_daily.csv: {e}")
        try:
            _log(f"Writing tips_by_server_shift.csv ({len(all_tips_by_server_shift_rows)} rows)...")
            t.write_tips_by_server_shift_csv(all_tips_by_server_shift_rows)
            _log("tips_by_server_shift.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write tips_by_server_shift.csv: {e}")
        try:
            _log(f"Writing payments_by_employee_per_shift.csv ({len(all_payments_by_employee_shift_rows)} rows)...")
            t.write_payments_by_employee_shift_csv(all_payments_by_employee_shift_rows)
            _log("payments_by_employee_per_shift.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write payments_by_employee_per_shift.csv: {e}")

        # NEW: write per-shift net sales by employee
        try:
            # Backfill missing employee_name from emp_map (and employees.json if needed)
            fixed_rows = []
            # Ensure we have a guid->name map
            guid_to_name = dict(emp_map or {})
            if not guid_to_name:
                try:
                    import json as _json
                    empp = RAW_DIR / "employees.json"
                    if empp.exists():
                        with empp.open("r", encoding="utf-8") as ef:
                            emps = _json.load(ef) or []
                        for e in emps:
                            fn = (e.get("firstName") or "").strip()
                            ln = (e.get("lastName") or "").strip()
                            full = (fn + (" " + ln if ln else "")).strip()
                            if e.get("guid") and full:
                                guid_to_name[e.get("guid")] = full
                            if e.get("v2EmployeeGuid") and full:
                                guid_to_name[e.get("v2EmployeeGuid")] = full
                except Exception:
                    pass
            # Build quick index of labor shifts for job_title backfill: {(date, eg, start,end) -> job_title}
            labor_idx_exact = {}
            labor_idx_fuzzy = {}
            try:
                for lr in (all_labor_shifts_detailed_rows or []):
                    d = (lr.get("date") or "").strip()
                    egx = (lr.get("employee_guid") or "").strip()
                    jt = (lr.get("job_title") or lr.get("jobtitle") or "").strip()
                    stx = (lr.get("start_time_utc") or lr.get("start") or lr.get("inDate") or "").strip()
                    enx = (lr.get("end_time_utc") or lr.get("end") or lr.get("outDate") or "").strip()
                    if d and egx and jt:
                        labor_idx_fuzzy.setdefault((d, egx), jt)
                    if d and egx and jt and stx and enx:
                        labor_idx_exact[(d, egx, stx, enx)] = jt
            except Exception:
                pass

            for r in (all_net_sales_by_employee_shift_rows or []):
                try:
                    name = (r.get("employee_name") or "").strip()
                    if not name:
                        eg = (r.get("employee_guid") or "").strip()
                        if eg and eg in guid_to_name:
                            r = dict(r)
                            r["employee_name"] = guid_to_name.get(eg, "")
                    # Backfill job_title if missing, from detailed labor index
                    jt = (r.get("job_title") or "").strip()
                    if not jt:
                        d = (r.get("date") or "").strip()
                        eg = (r.get("employee_guid") or "").strip()
                        st = (r.get("start_time_utc") or "").strip()
                        en = (r.get("end_time_utc") or "").strip()
                        jt_m = None
                        if d and eg and st and en:
                            jt_m = labor_idx_exact.get((d, eg, st, en))
                        if (not jt_m) and d and eg:
                            jt_m = labor_idx_fuzzy.get((d, eg))
                        if jt_m:
                            r = dict(r)
                            r["job_title"] = jt_m
                    fixed_rows.append(r)
                except Exception:
                    fixed_rows.append(r)
            _log(f"Writing net_sales_by_employee_shift_daily.csv ({len(fixed_rows)} rows)...")
            t.write_net_sales_by_employee_shift_csv(fixed_rows)
            _log("net_sales_by_employee_shift_daily.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write net_sales_by_employee_shift_daily.csv: {e}")

        # Write credit tips per shift (limit to current fetch window)
        try:
            try:
                allowed_dates = {str(r.get("date")).strip() for r in (all_labor_shifts_detailed_rows or []) if r.get("date")}
            except Exception:
                allowed_dates = None
            cnt_credit = _build_credit_tips_per_shift_csv(allowed_dates=allowed_dates)
            _log(f"Writing credit_tips_per_shift.csv ({cnt_credit} rows)...")
            _log("credit_tips_per_shift.csv written.")
        except Exception as e:
            _log(f"WARN: failed to write credit_tips_per_shift.csv: {e}")

        # Final roll-up summary
        try:
            summary = [
                ("net_sales_by_employee_daily.csv", len(report_rows)),
                ("item_mix_daily.csv", len(all_item_mix)),
                ("category_sales_daily.csv", len(all_category_rows)),
                ("discounts_daily.csv", len(all_discount_rows)),
                ("payments_tips_daily.csv", len(all_payment_rows)),
                ("voids_daily.csv", len(all_void_rows)),
                ("tips_by_server_daily.csv", len(all_tips_rows)),
                ("cash_summary_daily.csv", len(all_cash_rows)),
                ("hourly_sales_daily.csv", len(all_hourly_rows)),
                ("sales_by_dimension_daily.csv", len(all_dim_rows)),
                ("labor_hours_daily.csv", len(all_labor_rows)),
                ("labor_shifts_detailed_daily.csv", len(all_labor_shifts_detailed_rows)),
                ("cash_tips_per_shift.csv", len(all_cash_tips_shifts_rows)),
                ("gratuity_per_shift_daily.csv", len(all_gratuity_per_shift_rows)),
                ("tips_by_server_shift.csv", len(all_tips_by_server_shift_rows)),
                ("payments_by_employee_per_shift.csv", len(all_payments_by_employee_shift_rows)),
                ("credit_tips_per_shift.csv", cnt_credit if 'cnt_credit' in locals() else 0),
                ("net_sales_by_employee_shift_daily.csv", len(all_net_sales_by_employee_shift_rows)),
            ]
            _log("Reports summary:")
            for name, cnt in summary:
                _log(f"  - {name}: {cnt} rows")
        except Exception:
            pass

    finally:
        # If cancelled or finished early, make sure to release the lock
        try:
            if FETCH_LOCK_PATH.exists():
                FETCH_LOCK_PATH.unlink()
        except Exception:
            pass
        if FETCH_CANCEL.is_set():
            _log("Cancelled.")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "title": "Toast Webapp", "header": "Toast Data Webapp"})


@app.get("/employees", response_class=HTMLResponse)
def view_employees(request: Request):
    p = RAW_DIR / "employees.json"
    if not p.exists():
        return HTMLResponse("<h3>No employees.json found. Run a fetch first.</h3>", status_code=404)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    # Auto-sync: ensure all current employees are present as workers
    try:
        sync_employees_to_workers()
    except Exception:
        pass
    # Load job map (guid -> title)
    try:
        job_map = t.load_job_map()
    except Exception:
        job_map = {}

    cols = [
        "guid",
        "v2EmployeeGuid",
        "firstName",
        "lastName",
        "chosenName",
        "email",
        "phoneNumber",
        "jobTitles",
        "deleted",
        "createdDate",
        "modifiedDate",
    ]
    rows = []
    for i, e in enumerate(data or []):
        if i > 1000:
            break
        row = {c: (e.get(c) if e.get(c) is not None else "") for c in cols}
        # Resolve job titles from jobReferences for hyperlinking
        job_list: List[Dict[str, str]] = []
        try:
            for ref in (e.get("jobReferences") or []):
                guid = (ref or {}).get("guid")
                if not guid:
                    continue
                title = job_map.get(guid)
                if title:
                    job_list.append({"guid": guid, "title": str(title)})
        except Exception:
            pass
        # de-duplicate by title while preserving order
        if job_list:
            seen_titles = set()
            dedup: List[Dict[str, str]] = []
            for jd in job_list:
                if jd["title"] in seen_titles:
                    continue
                seen_titles.add(jd["title"])
                dedup.append(jd)
            row["jobTitles"] = dedup
        else:
            row["jobTitles"] = []
        rows.append(row)
    return templates.TemplateResponse("employees.html", {"request": request, "title": "Employees", "cols": cols, "rows": rows})


# Debug: inspect committed transfers and journal state for troubleshooting UI zeros
@app.get("/api/debug/committed")
def api_debug_committed(bucket: str, business_date: str):
    db = DatabaseManager()
    try:
        committed = db.get_committed_transfers(bucket, business_date)
        return JSONResponse({
            "count": len(committed),
            "rows": committed[:50],
        })
    finally:
        db.close()


@app.get("/api/debug/journal")
def api_debug_journal(bucket: str, business_date: str):
    db = DatabaseManager()
    try:
        cur = db.conn.cursor()
        cur.execute("SELECT id FROM payout_sessions WHERE bucket = ? AND business_date = ? ORDER BY created_at DESC", (bucket, business_date))
        sessions = [r[0] for r in cur.fetchall() or []]
        transfers = []
        legs = []
        for sid in sessions:
            cur.execute("SELECT id, destination, amount, created_at FROM payout_transfers WHERE session_id = ? ORDER BY id", (sid,))
            transfers.extend([{"id": r[0], "session": sid, "destination": r[1], "amount": float(r[2] or 0.0), "created_at": r[3]} for r in cur.fetchall() or []])
            cur.execute("SELECT id, transfer_id, leg_kind, party_name, destination, amount FROM payout_legs WHERE transfer_id IN (SELECT id FROM payout_transfers WHERE session_id = ?) ORDER BY id", (sid,))
            legs.extend([{"id": r[0], "transfer_id": r[1], "leg_kind": r[2], "party_name": r[3], "destination": r[4], "amount": float(r[5] or 0.0)} for r in cur.fetchall() or []])
        return JSONResponse({
            "sessions": sessions,
            "transfers_count": len(transfers),
            "legs_count": len(legs),
            "sample_transfers": transfers[:50],
            "sample_legs": legs[:50],
        })
    finally:
        db.close()


@app.post("/run", response_class=PlainTextResponse)
def run(background: BackgroundTasks, days: int = Form(30, ge=1, le=60)):
    # If lock exists, don't start a second run
    if FETCH_LOCK_PATH.exists():
        return "A fetch is already running. Please wait for it to finish."
    background.add_task(run_fetch, days)
    return f"Started fetch for last {days} days in background. Open the home page to watch progress."


@app.post("/run/cancel", response_class=PlainTextResponse)
def run_cancel():
    try:
        if not FETCH_LOCK_PATH.exists():
            return "No fetch is currently running."
        FETCH_CANCEL.set()
        _log("Cancellation requested via /run/cancel")
        return "Cancel requested. The fetch will stop shortly."
    except Exception:
        return "Unable to request cancel."


@app.get("/run/status", response_class=PlainTextResponse)
def run_status():
    try:
        if not FETCH_LOG_PATH.exists():
            return "No fetch running. Submit a fetch to see progress."
        # Read and return entire log (small file). Could tail if needed.
        return FETCH_LOG_PATH.read_text(encoding="utf-8")
    except Exception:
        return "Unable to read status."


# --- Simple hourly scheduler to fetch last 7 days ---
def _scheduler_loop():
    """Background scheduler that fetches the past 7 days on startup and then hourly.

    Respects the existing FETCH_LOCK so it won't start overlapping runs.
    """
    # Kick off immediately once
    try:
        if not FETCH_LOCK_PATH.exists():
            _log("[Scheduler] Starting immediate fetch for last 7 days on startup")
            run_fetch(7)
        else:
            _log("[Scheduler] Fetch lock present at startup, skipping immediate run")
    except Exception as e:
        _log(f"[Scheduler] Immediate run failed: {e}")

    # Then run hourly until stopped
    while not SCHEDULER_STOP.is_set():
        # Sleep in small chunks to allow prompt shutdown
        for _ in range(30 * 60):
            if SCHEDULER_STOP.is_set():
                break
            time.sleep(1)
        if SCHEDULER_STOP.is_set():
            break
        try:
            if FETCH_LOCK_PATH.exists():
                _log("[Scheduler] Lock present, skipping hourly run")
                continue
            _log("[Scheduler] Starting hourly fetch for last 7 days")
            run_fetch(7)
        except Exception as e:
            _log(f"[Scheduler] Hourly run failed: {e}")


@app.on_event("startup")
def _start_scheduler():
    global SCHEDULER_THREAD
    try:
        if SCHEDULER_THREAD and SCHEDULER_THREAD.is_alive():
            return
        SCHEDULER_STOP.clear()
        SCHEDULER_THREAD = threading.Thread(target=_scheduler_loop, name="scheduler", daemon=True)
        SCHEDULER_THREAD.start()
        _log("[Scheduler] Background thread started")
    except Exception as e:
        _log(f"[Scheduler] Failed to start: {e}")


@app.on_event("shutdown")
def _stop_scheduler():
    try:
        SCHEDULER_STOP.set()
        if SCHEDULER_THREAD and SCHEDULER_THREAD.is_alive():
            SCHEDULER_THREAD.join(timeout=5)
        _log("[Scheduler] Background thread stopped")
    except Exception as e:
        _log(f"[Scheduler] Failed to stop: {e}")


@app.post("/run/force-clear", response_class=PlainTextResponse)
def run_force_clear():
    """Force clear a stuck fetch: remove lock file and clear cancel flag.
    Use only when cancellation did not complete and no fetch is actually running.
    """
    try:
        FETCH_CANCEL.clear()
    except Exception:
        pass
    try:
        if FETCH_LOCK_PATH.exists():
            FETCH_LOCK_PATH.unlink()
            _log("Force-cleared fetch lock via /run/force-clear")
            return "Force-cleared. You may start a new fetch."
        else:
            return "No lock file found. You may start a fetch."
    except Exception as e:
        return f"Failed to force-clear: {e}"

@app.post("/api/sync-raw-data", response_class=PlainTextResponse)
def sync_raw_data():
    """Sync raw JSON data from data/raw/ into formbuilderdb as Forms and Submissions."""
    try:
        process_raw_data_to_formbuilderdb()
        return "Raw data synced to formbuilderdb successfully."
    except Exception as e:
        return f"Error syncing data: {e}"

@app.post("/api/clear-toast-data", response_class=PlainTextResponse)
def clear_toast_data_endpoint():
    """Clear all Toast-related data from formbuilderdb."""
    try:
        clear_toast_data(confirm=True)  # Auto-confirm for API
        return "All Toast data cleared successfully."
    except Exception as e:
        return f"Error clearing data: {e}"


# Admin: Graceful shutdown endpoint
@app.post("/admin/shutdown")
def admin_shutdown(admin_password: str = Form("")):
    if not ADMIN_PASSWORD or admin_password != ADMIN_PASSWORD:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    # Respond immediately, then stop process shortly after so response flushes
    def _shutdown():
        try:
            time.sleep(0.5)
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            os._exit(0)
    try:
        threading.Thread(target=_shutdown, daemon=True).start()
    except Exception:
        # Fallback: hard-exit immediately if thread creation fails
        os._exit(0)
    return JSONResponse({"status": "shutting_down"})

# Admin: Restart server endpoint (spawns start.sh which will kill current UVicorn and launch a new one)
@app.post("/admin/restart")
def admin_restart(admin_password: str = Form("")):
    if not ADMIN_PASSWORD or admin_password != ADMIN_PASSWORD:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    def _restart():
        try:
            subprocess.Popen(["bash", "/home/ubuntu/toasty/start.sh"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        except Exception:
            pass
    try:
        threading.Thread(target=_restart, daemon=True).start()
    except Exception:
        try:
            subprocess.Popen(["bash", "/home/ubuntu/toasty/start.sh"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        except Exception:
            pass
    return JSONResponse({"status": "restarting"})

# Admin: Normalize workers to First+Last and cleanup rows with non-matching names
@app.post("/admin/normalize-workers")
def admin_normalize_workers(admin_password: str = Form(""), do_sync: bool = Form(True)):
    if not ADMIN_PASSWORD or admin_password != ADMIN_PASSWORD:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    # Optionally re-sync workers from employees.json using First+Last
    if do_sync:
        try:
            sync_employees_to_workers()
        except Exception:
            pass

    # Build valid set of First+Last from employees.json (non-deleted)
    valid_names: set[str] = set()
    try:
        with (RAW_DIR / "employees.json").open("r", encoding="utf-8") as f:
            emps = json.load(f) or []
        for e in emps:
            if e.get("deleted") is True:
                continue
            nm = _employee_display_name(e)
            if nm:
                valid_names.add(nm)
    except Exception:
        # If can't load, leave empty; nothing will be deleted in that case
        valid_names = set()

    db = DatabaseManager()
    deleted_counts: Dict[str, int] = {}
    try:
        cur = db.conn.cursor()
        # Tables with worker_name columns (payouts has FK; cashbox_ledger not FK)
        tables = [
            ("payouts", "worker_name"),
            ("transactions", "worker_name"),
            ("cashbox_ledger", "worker_name"),
            ("worker_roles", "worker_name"),
        ]
        for tbl, col in tables:
            try:
                # Delete rows where worker_name NOT IN valid_names
                if valid_names:
                    q_marks = ",".join(["?"] * len(valid_names))
                    sql = f"DELETE FROM {tbl} WHERE {col} NOT IN (" + q_marks + ")"
                    cur.execute(sql, tuple(sorted(valid_names)))
                else:
                    deleted_counts[tbl] = 0
                    continue
                deleted_counts[tbl] = cur.rowcount or 0
                db.conn.commit()
            except Exception:
                deleted_counts[tbl] = -1
        # Cleanup workers table itself: remove names not in valid set
        try:
            if valid_names:
                q_marks = ",".join(["?"] * len(valid_names))
                sql = "DELETE FROM workers WHERE name NOT IN (" + q_marks + ")"
                cur.execute(sql, tuple(sorted(valid_names)))
                deleted_counts["workers"] = cur.rowcount or 0
                db.conn.commit()
            else:
                deleted_counts["workers"] = 0
        except Exception:
            deleted_counts["workers"] = -1
    finally:
        db.close()

    return JSONResponse({"ok": True, "deleted": deleted_counts, "valid_names_count": len(valid_names)})


# API (legacy): bartender defaults from net_sales_by_employee_daily.csv based on date + bucket
@app.get("/api/bartender-defaults-legacy")
def api_bartender_defaults_legacy(date: str = Query(...), bucket: str = Query(...)):
    """
    Map a selected bucket to a bar employee_name and read net_sales_by_employee_daily.csv
    for that date and name, returning cash_tips, credit_card_tips, and net_sales.

    Mapping by display name:
      Sunset     -> Low Bar
      West Wing  -> WW Bar
      AM         -> AM Bar

    The `bucket` param can be either the bucket id or display; we normalize to display.
    """
    # Resolve bucket display name
    display_by_id = {bid: bname for bid, bname in (BUCKET_DISPLAY_NAMES or [])}
    # If matches id, use display; else assume provided is display
    bdisp = display_by_id.get(bucket, bucket)
    name_map = {
        "Sunset": "Low Bar",
        "West Wing": "WW Bar",
        "AM": "AM Bar",
    }
    employee_name = name_map.get(bdisp)
    if not employee_name:
        return JSONResponse({"error": f"Unsupported bucket '{bucket}'"}, status_code=400)

    # Read CSV
    csv_path = REPORTS_DIR / "net_sales_by_employee_daily.csv"
    if not csv_path.exists():
        return JSONResponse({"error": "net_sales_by_employee_daily.csv not found"}, status_code=404)
    result = {"cash_tips": 0.0, "credit_card_tips": 0.0, "net_sales": 0.0}
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                if (r.get("date") == date) and ((r.get("employee_name") or "").strip() == employee_name):
                    def _f(x):
                        try:
                            return float(x)
                        except Exception:
                            return 0.0
                    result = {
                        "cash_tips": _f(r.get("cash_tips")),
                        "credit_card_tips": _f(r.get("credit_card_tips")),
                        # Return actual_net_sales under the existing key so front-end continues to work
                        "net_sales": _f(r.get("actual_net_sales") or r.get("net_sales")),
                    }
                    break
    except Exception as e:
        return JSONResponse({"error": f"Failed reading CSV: {e}"}, status_code=500)
    return JSONResponse(result)


@app.post("/api/bartender/push")
async def api_bartender_push(request: Request):
    try:
        data = await request.json()
    except Exception:
        try:
            form = await request.form()
            data = dict(form)
        except Exception:
            return JSONResponse({"error": "Invalid payload"}, status_code=400)

    bartender = (data.get("bartender") or "").strip()
    bucket = (data.get("bucket") or "").strip()
    date = (data.get("date") or "").strip()
    if not (bartender and bucket and date):
        return JSONResponse({"error": "Missing bartender, bucket, or date"}, status_code=400)
    # Per-row amounts (already split) — bartips not needed here
    servertips = float(data.get("bussertips") or data.get("servertips") or 0)
    expotips = float(data.get("expotips") or 0)
    runnertips = float(data.get("runnertips") or 0)
    # Optional per-bartender main figures (already split equally in UI)
    per_cash = float(data.get("per_cash") or 0)
    per_credit = float(data.get("per_credit") or 0)
    per_net = float(data.get("per_net") or 0)
    try:
        db = DatabaseManager()
        try:
            # Ensure worker exists to satisfy FK on payouts
            try:
                db.add_worker(bartender)
            except Exception:
                pass
            # Resolve job_title for bartender by date/bucket (if available)
            jt_bt = _resolve_job_title_for(bartender, date, bucket)
            db.record_bartender_payouts(
                bartender_name=bartender,
                bucket=bucket,
                bartips=0.0,
                servertips=servertips,
                expotips=expotips,
                runnertips=runnertips,
                business_date=date,
                job_title=jt_bt,
            )
            # Also persist per-bartender main figures to bartenders table when provided
            try:
                if (per_cash or per_credit or per_net):
                    # Map bucket id to display bar name used in bartenders table
                    display_by_id = {bid: bname for bid, bname in (BUCKET_DISPLAY_NAMES or [])}
                    bdisp = display_by_id.get(bucket, bucket)
                    tip_pct = f"Gross Tip %: {(((per_cash + per_credit) / per_net) * 100.0):.2f}%" if per_net > 0 else "Gross Tip %: 0.00%"
                    db.save_bartender_entry(
                        date_str=date,
                        bartender=bartender,
                        bar_name=bdisp,
                        cash_tips=per_cash,
                        credit_tips=per_credit,
                        sum_tips_for_payout=round((servertips + expotips + runnertips), 2),
                        net_sales=per_net,
                        tipped_perc_of_net_sales=tip_pct,
                        job_title=jt_bt,
                    )
            except Exception:
                # Do not fail push if summary persistence fails
                pass
        finally:
            db.close()
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"error": f"Failed to push: {e}"}, status_code=500)


@app.post("/api/bartender/undo")
async def api_bartender_undo(request: Request):
    try:
        data = await request.json()
    except Exception:
        try:
            form = await request.form()
            data = dict(form)
        except Exception:
            return JSONResponse({"error": "Invalid payload"}, status_code=400)

    bartender = (data.get("bartender") or "").strip()
    bucket = (data.get("bucket") or "").strip()
    date = (data.get("date") or "").strip()
    if not (bartender and bucket and date):
        return JSONResponse({"error": "Missing bartender, bucket, or date"}, status_code=400)
    try:
        db = DatabaseManager()
        try:
            deleted = db.delete_unpaid_server_payouts(bartender, bucket, date)
            # If there are no remaining payout rows (unpaid or committed) for this bartender/date/bucket,
            # remove the bartender summary entry so it doesn't persist in the report.
            try:
                cur = db.conn.cursor()
                cur.execute(
                    'SELECT 1 FROM payouts WHERE worker_name = ? AND bucket = ? AND business_date = ? LIMIT 1',
                    (bartender, bucket, date),
                )
                still_exists = cur.fetchone() is not None
                if not still_exists:
                    # Map bucket id to display bar name used in bartenders table
                    display_by_id = {bid: bname for bid, bname in (BUCKET_DISPLAY_NAMES or [])}
                    bdisp = display_by_id.get(bucket, bucket)
                    try:
                        db.delete_bartender_entry(date, bartender, bdisp)
                    except Exception:
                        pass
            except Exception:
                pass
        finally:
            db.close()
        return JSONResponse({"ok": True, "deleted": deleted})
    except Exception as e:
        return JSONResponse({"error": f"Failed to undo: {e}"}, status_code=500)


@app.get("/api/bartender/status")
def api_bartender_status(bartender: str = Query(...), bucket: str = Query(...), date: str = Query(...)):
    bartender = (bartender or "").strip()
    bucket = (bucket or "").strip()
    date = (date or "").strip()
    if not (bartender and bucket and date):
        return JSONResponse({"error": "Missing bartender, bucket, or date"}, status_code=400)
    try:
        db = DatabaseManager()
        try:
            pushed = db.get_unpaid_pushed_sums_for_server(bartender, bucket, date)
            # Also return a count of unpaid pushed rows (including zero-amount rows)
            try:
                cur = db.conn.cursor()
                cur.execute(
                    'SELECT COUNT(*) FROM payouts WHERE worker_name = ? AND bucket = ? AND business_date = ? AND payout_destination IN ("Busser","Expo","Runner") AND payout_session_id IS NULL',
                    (bartender, bucket, date),
                )
                row = cur.fetchone()
                pushed_count = int(row[0] or 0) if row else 0
            except Exception:
                pushed_count = 0
            committed = db.get_committed_sums_for_server(bartender, bucket, date)
        finally:
            db.close()
        return JSONResponse({"pushed": pushed, "pushed_count": pushed_count, "committed": committed})
    except Exception as e:
        return JSONResponse({"error": f"Failed to get status: {e}"}, status_code=500)


# API: server bucket status for coloring suggested buckets on Server Tips page
@app.get("/api/server/bucket-status")
def api_server_bucket_status(worker: str = Query(...), date: str = Query(...), buckets: str = Query("")):
    """
    Given a worker name, business date (YYYY-MM-DD), and a comma-separated list of bucket ids,
    return a mapping of bucket id -> { pushed_total: float, committed_total: float }.

    This powers the color legend/states of suggested location buttons in templates/server_tips.html.
    """
    worker = (worker or "").strip()
    date = (date or "").strip()
    if not (worker and date):
        return JSONResponse({"error": "Missing worker or date"}, status_code=400)
    # Parse buckets CSV into list of ids
    try:
        ids = [b.strip() for b in (buckets or "").split(",") if b and b.strip()]
    except Exception:
        ids = []
    result = {}
    try:
        db = DatabaseManager()
        try:
            for bid in ids:
                try:
                    pm = db.get_unpaid_pushed_sums_for_server(worker, bid, date)
                except Exception:
                    pm = {}
                try:
                    cm = db.get_committed_sums_for_server(worker, bid, date)
                except Exception:
                    cm = {}
                pushed_total = float(sum((pm or {}).values()) if pm else 0.0)
                committed_total = float(sum((cm or {}).values()) if cm else 0.0)
                result[bid] = {
                    "pushed_total": round(pushed_total, 2),
                    "committed_total": round(committed_total, 2),
                }
        finally:
            db.close()
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": f"Failed bucket status lookup: {e}"}, status_code=500)


# UI: Bartender Tips page
@app.get("/bartender-tips", response_class=HTMLResponse)
def bartender_tips_get(request: Request):
    today = dt_date.today().isoformat()
    # Initial workers list from DB; front-end will refresh via APIs
    try:
        db = DatabaseManager()
        try:
            workers = db.load_workers() or []
        finally:
            db.close()
    except Exception:
        workers = []
    buckets = list(BUCKET_DISPLAY_NAMES or [])
    # Hide 'East Wing' from bartender-tips bucket selection
    try:
        buckets = [
            (bid, bname)
            for (bid, bname) in buckets
            if str(bid).lower() != "eastwing" and str(bname).strip().lower() != "east wing"
        ]
    except Exception:
        # If BUCKET_DISPLAY_NAMES is not iterable as expected, fall back silently
        pass
    return templates.TemplateResponse(
        "bartender_tips.html",
        {
            "request": request,
            "title": "Bartender Tips",
            "today": today,
            "workers": workers,
            "buckets": buckets,
        },
    )


@app.get("/reports/worker_report.csv", response_class=PlainTextResponse)
def worker_report_csv(
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 10000,
) -> PlainTextResponse:
    """CSV export for the consolidated worker report (/report) using the same filtering and enrichment."""
    # Normalize date range (default: last 30 days)
    try:
        e_dt = dt_date.fromisoformat(end_date) if end_date else dt_date.today()
    except Exception:
        e_dt = dt_date.today()
    try:
        s_dt = dt_date.fromisoformat(start_date) if start_date else (e_dt - timedelta(days=30))
    except Exception:
        s_dt = e_dt - timedelta(days=30)
    s_str, e_str = s_dt.isoformat(), e_dt.isoformat()

    sql_path = ROOT / "jbhooks" / "tip_report.sql"
    headers: List[str] = []
    rows: List[dict] = []
    if not sql_path.exists():
        # Return empty CSV with a message header
        import io, csv as _csv
        sio = io.StringIO()
        cw = _csv.writer(sio)
        cw.writerow(["message"])  # simple header
        cw.writerow(["tip_report.sql not found"])  # message row
        return PlainTextResponse(content=sio.getvalue(), media_type="text/csv")

    # Execute SQL and collect rows
    sql = sql_path.read_text(encoding="utf-8")
    db = DatabaseManager()
    try:
        cur = db.conn.cursor()
        base_sql = sql.strip().rstrip(";\n ")
        wrapped = (
            "WITH base AS (" + base_sql + ") "
            "SELECT * FROM base WHERE \"Date\" BETWEEN ? AND ? "
            "ORDER BY \"Date\" DESC LIMIT ?"
        )
        cur.execute(wrapped, [s_str, e_str, int(limit)])
        result_rows = cur.fetchall() or []
        headers = [d[0] for d in (cur.description or [])]
        for r in result_rows[: int(limit)]:
            row = {}
            for i, h in enumerate(headers):
                row[h] = r[i] if i < len(r) else None
            rows.append(row)
    finally:
        db.close()

    # Enrich rows with per-shift metrics from CSVs based on (Date, Worker, Job Title)
    try:
        import csv as _csv
        ns_path = REPORTS_DIR / "net_sales_by_employee_shift_daily.csv"
        gr_path = REPORTS_DIR / "gratuity_per_shift.csv"
        key = lambda d, w, jt: (str(d or "").strip(), str(w or "").strip(), str(jt or "").strip())
        def consolidate_server_rows(rows_iter):
            from collections import defaultdict
            grouped: Dict[tuple[str, str], Dict[str, Dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: {"cash_tips":0.0,"credit_card_tips":0.0,"net_sales":0.0,"gratuity":0.0}))
            for rr in rows_iter:
                d = (rr.get("date") or "").strip()
                w = (rr.get("employee_name") or "").strip()
                jt = (rr.get("job_title") or rr.get("jobtitle") or "").strip()
                if not d or not w or not jt:
                    continue
                try:
                    grouped[(d,w)][jt]["cash_tips"] += float(rr.get("cash_tips") or 0.0)
                except Exception:
                    pass
                try:
                    grouped[(d,w)][jt]["credit_card_tips"] += float(rr.get("credit_card_tips") or 0.0)
                except Exception:
                    pass
                try:
                    grouped[(d,w)][jt]["net_sales"] += float(rr.get("net_sales") or 0.0)
                except Exception:
                    pass
                try:
                    grouped[(d,w)][jt]["gratuity"] += float(rr.get("gratuity_total") or 0.0)
                except Exception:
                    pass
            out: Dict[tuple, Dict[str, float]] = {}
            for (d,w), by_jt in grouped.items():
                titles = list(by_jt.keys())
                non_clean = [t for t in titles if t.strip().lower() != "cleaning - server"]
                pref_order = ["PM Sunset Server","AM Sunset Server","WW Server","Server"]
                target = None
                for pref in pref_order:
                    for tname in non_clean:
                        if pref.lower() in tname.lower():
                            target = tname
                            break
                    if target:
                        break
                if not target:
                    target = non_clean[0] if non_clean else None
                cleaning_key = None
                for tname in titles:
                    if tname.strip().lower() == "cleaning - server":
                        cleaning_key = tname
                        break
                if cleaning_key and target:
                    for kf in ("cash_tips","credit_card_tips","net_sales","gratuity"):
                        by_jt[target][kf] = float(by_jt[target].get(kf,0.0)) + float(by_jt[cleaning_key].get(kf,0.0))
                    by_jt.pop(cleaning_key, None)
                for jt, vals in by_jt.items():
                    out[(d,w,jt)] = {
                        "cash_tips": float(vals.get("cash_tips",0.0)),
                        "credit_card_tips": float(vals.get("credit_card_tips",0.0)),
                        "net_sales": float(vals.get("net_sales",0.0)),
                        "gratuity": float(vals.get("gratuity",0.0)),
                    }
            return out
        ns_map: Dict[tuple, Dict[str, float]] = {}
        if ns_path.exists():
            with ns_path.open("r", encoding="utf-8") as f:
                rdr = _csv.DictReader(f)
                ns_map = consolidate_server_rows(rdr)
        gr_map: Dict[tuple, float] = {}
        if gr_path.exists():
            with gr_path.open("r", encoding="utf-8") as f:
                rdr = _csv.DictReader(f)
                gr_con = consolidate_server_rows(rdr)
                gr_map = { (d,w,jt): float(v.get("gratuity",0.0)) for (d,w,jt), v in gr_con.items() }
        for row in rows:
            k = key(row.get("Date"), row.get("Worker"), row.get("Job Title"))
            ns = ns_map.get(k)
            if ns:
                if row.get("Cash Tips") in (None, 0, 0.0):
                    row["Cash Tips"] = round(float(ns.get("cash_tips", 0.0)), 2)
                if row.get("Non-Cash Tips") in (None, 0, 0.0):
                    row["Non-Cash Tips"] = round(float(ns.get("credit_card_tips", 0.0)), 2)
                if row.get("Net Sales") in (None, 0, 0.0):
                    row["Net Sales"] = round(float(ns.get("net_sales", 0.0)), 2)
            gr = gr_map.get(k)
            if gr is not None and row.get("Gratuity") in (None, 0, 0.0):
                row["Gratuity"] = round(float(gr or 0.0), 2)
            try:
                cash = float(row.get("Cash Tips") or 0.0)
                noncash = float(row.get("Non-Cash Tips") or 0.0)
                grat = float(row.get("Gratuity") or 0.0)
                net = float(row.get("Net Sales") or 0.0)
                if net > 0:
                    row["Tip % of Sales"] = round(((cash + noncash + grat) / net) * 100.0, 2)
                else:
                    row["Tip % of Sales"] = float(row.get("Tip % of Sales") or 0.0)
            except Exception:
                pass
    except Exception:
        pass

    # Write CSV (hide certain columns from export)
    import io, csv as _csv
    sio = io.StringIO()
    cw = _csv.writer(sio)
    exclude_cols = {"Payout Bucket", "Payout Business Date"}
    export_headers = [h for h in headers if h not in exclude_cols]
    cw.writerow(export_headers)
    for r in rows:
        cw.writerow([r.get(h, "") for h in export_headers])
    return PlainTextResponse(content=sio.getvalue(), media_type="text/csv")
@app.post("/bartender-tips", response_class=HTMLResponse)
async def bartender_tips_post(request: Request):
    form = await request.form()
    biz_date = (form.get("biz_date") or "").strip()
    bucket = (form.get("bucket") or "").strip()
    bartender_names = form.getlist("bartender_names") if hasattr(form, "getlist") else [form.get("bartender_names")] if form.get("bartender_names") else []
    # Totals input (group totals)
    def _f(x):
        try:
            return float(x)
        except Exception:
            return 0.0
    cash_tips = _f(form.get("cashtips"))
    credit_tips = _f(form.get("creditcardtip"))
    net_sales = _f(form.get("netsales"))
    bussertips = _f(form.get("servertips"))
    expotips = _f(form.get("expotips"))
    runnertips = _f(form.get("runnertips"))

    errors: List[str] = []
    if not biz_date:
        errors.append("Missing date")
    if not bucket:
        errors.append("Missing bucket")
    bartender_names = [n for n in (bartender_names or []) if (n or "").strip()]
    if not bartender_names:
        errors.append("Select at least one bartender")

    # Map bucket id -> display name for bar_name
    display_by_id = {bid: bname for bid, bname in (BUCKET_DISPLAY_NAMES or [])}
    # If matches id, use display; else assume provided is display
    bdisp = display_by_id.get(bucket, bucket)
    name_map = {
        "Sunset": "Low Bar",
        "West Wing": "WW Bar",
        "AM": "AM Bar",
    }
    employee_name = name_map.get(bdisp)
    if not employee_name:
        return JSONResponse({"error": f"Unsupported bucket '{bucket}'"}, status_code=400)

    # Split per bartender
    n = max(1, len(bartender_names))
    per_cash = round(cash_tips / n, 2)
    per_credit = round(credit_tips / n, 2)
    per_net = round(net_sales / n, 2)
    per_busser = round(bussertips / n, 2)
    per_expo = round(expotips / n, 2)
    per_runner = round(runnertips / n, 2)

    # Save a summary row per bartender
    try:
        db = DatabaseManager()
        try:
            for name in bartender_names:
                try:
                    db.add_worker(name)
                except Exception:
                    pass
                tip_pct = f"Gross Tip %: {((per_cash + per_credit) / per_net * 100.0):.2f}%" if per_net > 0 else "Gross Tip %: 0.00%"
                db.save_bartender_entry(
                    date_str=biz_date,
                    bartender=name,
                    bar_name=bdisp,
                    cash_tips=per_cash,
                    credit_tips=per_credit,
                    sum_tips_for_payout=(per_busser + per_expo + per_runner),
                    net_sales=per_net,
                    tipped_perc_of_net_sales=tip_pct,
                )
        finally:
            db.close()
    except Exception as e:
        errors.append(f"Failed to save entries: {e}")

    result = {
        "saved": len(errors) == 0,
        "errors": errors,
        "biz_date": biz_date,
        "bartender_names": bartender_names,
        "bucket": bucket,
        "bar_name": bdisp,
        "payout_tips": round(bussertips + expotips + runnertips, 2),
        "gross_tip_pct": (f"{(((cash_tips + credit_tips) / net_sales) * 100.0):.2f}%" if net_sales > 0 else "0.00%"),
    }

    # Re-render page with result summary
    try:
        workers = DatabaseManager().load_workers()
    except Exception:
        workers = []
    return templates.TemplateResponse(
        "bartender_tips.html",
        {
            "request": request,
            "title": "Bartender Tips",
            "today": dt_date.today().isoformat(),
            "workers": workers,
            "buckets": list(BUCKET_DISPLAY_NAMES or []),
            "result": result,
        },
    )


def _load_job_map_safe() -> Dict[str, str]:
    try:
        return t.load_job_map()
    except Exception:
        return {}


def _load_employees_safe() -> list:
    try:
        with (RAW_DIR / "employees.json").open("r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def _employee_name_from_obj(e: Dict[str, Any]) -> str:
    return _employee_display_name(e)


@app.get("/api/employees/bar")
def api_employees_bar():
    emps = _load_employees_safe()
    job_map = _load_job_map_safe()
    names: List[str] = []
    for e in emps:
        full = _employee_name_from_obj(e)
        if not full:
            continue
        titles = []
        try:
            for ref in (e.get("jobReferences") or []):
                guid = (ref or {}).get("guid")
                if guid and job_map:
                    tname = job_map.get(guid)
                    if tname:
                        titles.append(str(tname))
        except Exception:
            pass
        has_bar = any("bar" in (tname or "").lower() for tname in titles)
        if has_bar:
            names.append(full)
    return JSONResponse({"workers": sorted(set(names))})


@app.get("/api/shifts/by-title")
def api_shifts_by_title(date: str = Query(...), titles: str = Query(""), exclude_placeholders: int = Query(0)):
    # titles: comma-separated substrings to match within job_title column of labor_shifts_detailed_daily.csv
    title_parts = [s.strip().lower() for s in (titles or "").split(",") if s.strip()]
    path_ls = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
    workers: Set[str] = set()
    job_title_col = "job_title"
    if not path_ls.exists():
        return JSONResponse({"workers": []})
    try:
        with path_ls.open("r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                if (r.get("date") or "").strip() != (date or "").strip():
                    continue
                jt = (r.get(job_title_col) or r.get("jobtitle") or "").strip()
                jt_l = jt.lower()
                if title_parts and not any(p in jt_l for p in title_parts):
                    continue
                name = (r.get("employee_name") or r.get("name") or "").strip()
                if not name:
                    continue
                workers.add(name)
    except Exception:
        workers = set()
    if exclude_placeholders:
        barred = {"am bar", "ww bar", "low bar"}
        workers = {w for w in workers if w.lower() not in barred}
    return JSONResponse({"workers": sorted(workers)})


@app.get("/api/bartender/pushed-list")
def api_bartender_pushed_list(date: str = Query(...), bucket: str = Query(...), include_committed: int = Query(0)):
    names: Set[str] = set()
    # Unpaid pushed rows in payouts
    try:
        db = DatabaseManager()
        try:
            cur = db.conn.cursor()
            cur.execute(
                "SELECT DISTINCT worker_name FROM payouts WHERE business_date = ? AND bucket = ? AND payout_session_id IS NULL",
                (date, bucket),
            )
            for (w,) in cur.fetchall() or []:
                if w:
                    names.add(w)
            if include_committed:
                cur.execute(
                    "SELECT DISTINCT l.party_name FROM payout_legs l JOIN payout_transfers t ON t.id = l.transfer_id JOIN payout_sessions s ON s.id = t.session_id WHERE s.business_date = ? AND s.bucket = ? AND l.leg_kind = 'received'",
                    (date, bucket),
                )
                for (w,) in cur.fetchall() or []:
                    if w:
                        names.add(w)
        finally:
            db.close()
    except Exception:
        pass
    return JSONResponse({"workers": sorted(names)})


@app.get("/suggest", response_class=HTMLResponse)
def suggest_view(request: Request, date: Optional[str] = Query(None)):
    """Suggest page: shows who pushed/committed/got tips and highlights workers with tips but no pushes/commits.

    - selected_date: defaults to today if not provided
    - rows: all workers with their job titles and amounts (pushed given unpaid, committed given, received committed)
    - suggestions: workers who reported tips (cash or credit) on selected_date but have no pushed or committed rows
    """
    # Resolve date
    selected_date = (date or dt_date.today().isoformat()).strip()

    # Load workers list
    try:
        all_workers = DatabaseManager().load_workers()
    except Exception:
        all_workers = []

    # Build titles by worker from employees.json and job_map
    emps = _load_employees_safe()
    job_map = _load_job_map_safe()
    titles_by_worker: Dict[str, List[str]] = {}
    try:
        for e in emps:
            name = _employee_name_from_obj(e)
            if not name:
                continue
            titles: List[str] = []
            for ref in (e.get("jobReferences") or []):
                guid = (ref or {}).get("guid")
                if guid and job_map.get(guid):
                    titles.append(str(job_map.get(guid)))
            # de-duplicate preserve order
            seen = set()
            dedup = []
            for tname in titles:
                if tname in seen:
                    continue
                seen.add(tname)
                dedup.append(tname)
            if dedup:
                titles_by_worker[name] = dedup
    except Exception:
        pass

    # Compute per-worker pushed (unpaid) given, committed given, and received using SQL
    pushed_given: Dict[str, float] = {}
    committed_given: Dict[str, float] = {}
    received_committed: Dict[str, float] = {}
    try:
        db = DatabaseManager()
        try:
            cur = db.conn.cursor()
            # Unpaid pushed: payouts rows with session NULL, sum by worker_name for this date (any bucket)
            cur.execute(
                "SELECT worker_name, COALESCE(SUM(amount),0.0) FROM payouts WHERE business_date = ? AND payout_session_id IS NULL GROUP BY worker_name",
                (selected_date,),
            )
            for w, amt in cur.fetchall() or []:
                if w:
                    pushed_given[w] = float(amt or 0.0)
            # Committed given: sum payout_legs where leg_kind = 'given' grouped by party_name for sessions on date
            cur.execute(
                "SELECT l.party_name, COALESCE(SUM(l.amount),0.0) "
                "FROM payout_legs l "
                "JOIN payout_transfers t ON t.id = l.transfer_id "
                "JOIN payout_sessions s ON s.id = t.session_id "
                "WHERE s.business_date = ? AND l.leg_kind = 'given' "
                "GROUP BY l.party_name",
                (selected_date,),
            )
            for w, amt in cur.fetchall() or []:
                if w:
                    committed_given[w] = float(amt or 0.0)
            # Received (committed): sum payout_legs where leg_kind = 'received' grouped by party_name
            cur.execute(
                "SELECT l.party_name, COALESCE(SUM(l.amount),0.0) "
                "FROM payout_legs l "
                "JOIN payout_transfers t ON t.id = l.transfer_id "
                "JOIN payout_sessions s ON s.id = t.session_id "
                "WHERE s.business_date = ? AND l.leg_kind = 'received' "
                "GROUP BY l.party_name",
                (selected_date,),
            )
            for w, amt in cur.fetchall() or []:
                if w:
                    received_committed[w] = float(amt or 0.0)
        finally:
            db.close()
    except Exception:
        pass

    # Helper: map job title to bucket id (mirror of server-tips mapping)
    def _job_title_to_bucket_id(title: Optional[str]) -> Optional[str]:
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
        return None

    # Build table rows, and for each worker compute buckets with/without activity for this date
    rows = []
    try:
        db2 = DatabaseManager()
        try:
            bucket_list = list(BUCKET_DISPLAY_NAMES or [])  # [(id, display)]
            for w in sorted(set(all_workers) | set(pushed_given) | set(committed_given) | set(received_committed)):
                inactive = []
                active = []
                # Derive candidate shift buckets from labor_shifts_detailed_daily.csv
                shift_buckets: Set[str] = set()
                try:
                    csv_path = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
                    if csv_path.exists() and w in name_to_guids:
                        guids = name_to_guids.get(w) or set()
                        import csv as _csv
                        with csv_path.open("r", encoding="utf-8") as fcsv:
                            rdr = _csv.DictReader(fcsv)
                            for r in rdr:
                                if (r.get("date") or "").strip() != selected_date:
                                    continue
                                eg = (r.get("employee_guid") or "").strip()
                                if eg and eg in guids:
                                    bid = _job_title_to_bucket_id(r.get("job_title") or r.get("jobtitle"))
                                    if bid:
                                        shift_buckets.add(bid)
                except Exception:
                    shift_buckets = set()
                for bid, bname in bucket_list:
                    try:
                        pm = db2.get_unpaid_pushed_sums_for_server(w, bid, selected_date)
                    except Exception:
                        pm = {}
                    try:
                        cm = db2.get_committed_sums_for_server(w, bid, selected_date)
                    except Exception:
                        cm = {}
                    pushed_total = float(sum((pm or {}).values()) if pm else 0.0)
                    committed_total = float(sum((cm or {}).values()) if cm else 0.0)
                    # Consider no activity when both pushed and committed are effectively zero
                    if (pushed_total <= 0.009) and (committed_total <= 0.009):
                        inactive.append({"id": bid, "name": bname})
                    else:
                        active.append({"id": bid, "name": bname, "pushed": round(pushed_total, 2), "committed": round(committed_total, 2)})
                # Partition shift buckets into unpushed vs active
                shift_unpushed = []
                shift_active = []
                try:
                    disp_by_id = {bid: bname for bid, bname in bucket_list}
                    for sb in sorted(shift_buckets):
                        # Look up totals in our just-computed lists
                        # Faster to recompute: sum maps again for clarity
                        try:
                            pm2 = db2.get_unpaid_pushed_sums_for_server(w, sb, selected_date)
                        except Exception:
                            pm2 = {}
                        try:
                            cm2 = db2.get_committed_sums_for_server(w, sb, selected_date)
                        except Exception:
                            cm2 = {}
                        pt = float(sum((pm2 or {}).values()) if pm2 else 0.0)
                        ct = float(sum((cm2 or {}).values()) if cm2 else 0.0)
                        if (pt <= 0.009) and (ct <= 0.009):
                            shift_unpushed.append({"id": sb, "name": disp_by_id.get(sb, sb)})
                        else:
                            shift_active.append({"id": sb, "name": disp_by_id.get(sb, sb), "pushed": round(pt, 2), "committed": round(ct, 2)})
                except Exception:
                    pass
                rows.append({
                    "worker": w,
                    "titles": titles_by_worker.get(w, []),
                    "pushed_given": round(pushed_given.get(w, 0.0), 2),
                    "committed_given": round(committed_given.get(w, 0.0), 2),
                    "received": round(received_committed.get(w, 0.0), 2),
                    "inactive_buckets": inactive,
                    "active_buckets": active,
                    "shift_unpushed_buckets": shift_unpushed,
                    "shift_active_buckets": shift_active,
                })
        finally:
            db2.close()
    except Exception:
        # Fallback without bucket details if DB error occurs
        for w in sorted(set(all_workers) | set(pushed_given) | set(committed_given) | set(received_committed)):
            rows.append({
                "worker": w,
                "titles": titles_by_worker.get(w, []),
                "pushed_given": round(pushed_given.get(w, 0.0), 2),
                "committed_given": round(committed_given.get(w, 0.0), 2),
                "received": round(received_committed.get(w, 0.0), 2),
                "inactive_buckets": [],
                "active_buckets": [],
                "shift_unpushed_buckets": [],
                "shift_active_buckets": [],
            })

    # Suggestions: from net_sales_by_employee_daily.csv find those with tips but 0 pushed and 0 committed
    suggestions: List[Dict[str, Any]] = []
    try:
        path = REPORTS_DIR / "net_sales_by_employee_daily.csv"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                rdr = csv.DictReader(f)
                for r in rdr:
                    if (r.get("date") or "").strip() != selected_date:
                        continue
                    worker = (r.get("employee_name") or "").strip()
                    if not worker:
                        continue
                    def _f(x):
                        try:
                            return float(x)
                        except Exception:
                            return 0.0
                    cash_tips = _f(r.get("cash_tips"))
                    cc_tips = _f(r.get("credit_card_tips"))
                    has_tips = (cash_tips > 0.009) or (cc_tips > 0.009)
                    if not has_tips:
                        continue
                    has_push_or_commit = (pushed_given.get(worker, 0.0) > 0.009) or (committed_given.get(worker, 0.0) > 0.009)
                    if not has_push_or_commit:
                        suggestions.append({
                            "worker": worker,
                            "reason": "Has tips but no pushed/committed payouts",
                            "cash_tips": round(cash_tips, 2),
                            "credit_card_tips": round(cc_tips, 2),
                        })
    except Exception:
        pass

    return templates.TemplateResponse(
        "suggest.html",
        {
            "request": request,
            "title": "Suggest",
            "selected_date": selected_date,
            "rows": rows,
            "suggestions": suggestions,
        },
    )

@app.get("/reports", response_class=HTMLResponse)
def list_reports(request: Request, background_tasks: BackgroundTasks):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_orders_report_ready(background_tasks)
    reports: List[Dict[str, Any]] = []
    for p in sorted(REPORTS_DIR.glob("*.csv")):
        try:
            ts = _format_ts(p.stat().st_mtime)
        except OSError:
            ts = ""
        reports.append({"name": p.name, "modified": ts, "can_rebuild": p.name in REBUILDABLE_REPORTS})

    # Prefer to surface shift report prominently if it exists
    shift_csv = "net_sales_by_employee_shift_daily.csv"
    if all(r["name"] != shift_csv for r in reports) and (REPORTS_DIR / shift_csv).exists():
        try:
            shift_ts = _format_ts((REPORTS_DIR / shift_csv).stat().st_mtime)
        except OSError:
            shift_ts = ""
        reports.insert(0, {"name": shift_csv, "modified": shift_ts, "can_rebuild": False})

    # Proactively (re)build menu_category.csv so it's always available after startup
    _ensure_menu_category_csv(background_tasks)
    _ensure_shift_orders_report(background_tasks)
    status_messages = _report_status_messages()
    return templates.TemplateResponse(
        "reports_list.html",
        {
            "request": request,
            "title": "Reports",
            "reports": reports,
            "status_messages": status_messages,
        },
    )


@app.get("/reports/{name}", response_class=HTMLResponse)
def view_report(request: Request, name: str, background_tasks: BackgroundTasks):
    if name == "orders_report.csv":
        _ensure_orders_report_ready(background_tasks)
    elif name == "shift_orders_report.csv":
        _ensure_shift_orders_report(background_tasks)
    elif name == "menu_category.csv":
        _ensure_menu_category_csv(background_tasks)
    p = REPORTS_DIR / name
    if not (p.exists() and p.is_file()):
        return HTMLResponse(f"Report not found: {name}", status_code=404)
    headers: List[str] = []
    rows: List[dict] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i == 0:
                headers = row
            else:
                rows.append(dict(zip(headers, row)))
    return templates.TemplateResponse(
        "report_view.html",
        {"request": request, "title": name, "name": name, "headers": headers, "rows": rows},
    )


@app.post("/reports/{name}/rebuild")
def rebuild_report(name: str, background_tasks: BackgroundTasks):
    if name not in REBUILDABLE_REPORTS:
        raise HTTPException(status_code=404, detail="Report cannot be rebuilt")
    if name == "orders_report.csv":
        _ensure_orders_report_ready(background_tasks, force=True)
    elif name == "menu_category.csv":
        _ensure_menu_category_csv(background_tasks, force=True)
    elif name == "shift_orders_report.csv":
        _ensure_shift_orders_report(background_tasks, force=True)
    return RedirectResponse(url="/reports", status_code=303)


@app.get("/reports/net_sales_by_employee_shift", response_class=HTMLResponse)
def view_net_sales_by_employee_shift(request: Request):
    """Friendly viewer for net_sales_by_employee_shift_daily.csv using the generic table template."""
    name = "net_sales_by_employee_shift_daily.csv"
    p = REPORTS_DIR / name
    if not p.exists():
        return HTMLResponse(
            "<h3>Shift Net Sales report not found. Generate it first (run toast_30d_report.py).</h3>",
            status_code=404,
        )
    headers: List[str] = []
    rows: List[dict] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i == 0:
                headers = row
                continue
            if i > 1000:
                break
            rows.append({headers[j]: (row[j] if j < len(row) else "") for j in range(len(headers))})
    return templates.TemplateResponse(
        "report_view.html",
        {
            "request": request,
            "title": name,
            "name": name,
            "headers": headers,
            "rows": rows,
        },
    )


@app.get("/orders/by-employee/{biz_date}/{employee_guid}", response_class=HTMLResponse)
def orders_by_employee(request: Request, biz_date: str, employee_guid: str):
    """
    Show all orders connected to an employee on a given business date.
    Connection means either:
      - order.server.guid == employee_guid, or
      - any payment on any check has server.guid == employee_guid
    """
    import json
    orders_path = RAW_DIR / "orders" / f"{biz_date}.json"
    if not orders_path.exists():
        return HTMLResponse(f"<h3>No orders found for {biz_date}. Generate data first.</h3>", status_code=404)

    with orders_path.open("r", encoding="utf-8") as f:
        orders_data = json.load(f) or []

    def matches(order: dict) -> bool:
        try:
            srv = (order.get("server") or {}).get("guid")
            if srv == employee_guid:
                return True
            for check in order.get("checks", []) or []:
                for p in (check.get("payments") or []):
                    psrv = (p.get("server") or {}).get("guid")
                    if psrv == employee_guid:
                        return True
        except Exception:
            pass
        return False

    filtered = [o for o in orders_data if matches(o)]

    # Optional: resolve employee name
    employee_name = ""
    try:
        import json as _json
        emp_p = RAW_DIR / "employees.json"
        if emp_p.exists():
            with emp_p.open("r", encoding="utf-8") as ef:
                emps = _json.load(ef) or []
            for e in emps:
                if e.get("guid") == employee_guid or e.get("v2EmployeeGuid") == employee_guid:
                    employee_name = (e.get("firstName") or "") + (" " + (e.get("lastName") or "") if e.get("lastName") else "")
                    employee_name = employee_name.strip()
                    break
    except Exception:
        pass

    def _to_float(x):
        try:
            return float(x)
        except Exception:
            return 0.0

    rows = []
    for o in filtered:
        checks = o.get("checks", []) or []
        net_sales = sum(_to_float(c.get("amount")) for c in checks if not (c.get("voided") or c.get("deleted")))
        total_sales = sum(_to_float(c.get("totalAmount")) for c in checks if not (c.get("voided") or c.get("deleted")))
        rows.append({
            "order_guid": o.get("guid", ""),
            "display_number": o.get("displayNumber", ""),
            "business_date": o.get("businessDate", ""),
            "opened": o.get("openedDate", ""),
            "paid": o.get("paidDate", ""),
            "server_guid": (o.get("server") or {}).get("guid", ""),
            "checks_count": len(checks),
            "total_sales": f"{total_sales:.2f}",
            "net_sales": f"{net_sales:.2f}",
        })

    headers = [
        "display_number",
        "order_guid",
        "business_date",
        "opened",
        "paid",
        "server_guid",
        "checks_count",
        "total_sales",
        "net_sales",
    ]

    title = f"Orders for {employee_name or employee_guid} on {biz_date}"
    return templates.TemplateResponse(
        "orders_by_employee.html",
        {
            "request": request,
            "title": title,
            "employee_guid": employee_guid,
            "employee_name": employee_name,
            "biz_date": biz_date,
            "headers": headers,
            "rows": rows,
        },
    )

@app.get("/labor/shifts/{biz_date}/{employee_guid}", response_class=HTMLResponse)
def labor_shifts_by_employee(request: Request, biz_date: str, employee_guid: str):
    """
    Show detailed labor shifts for an employee on a given business date using
    the CSV written by write_labor_shifts_detailed_csv().
    """
    # Path to detailed shifts CSV
    csv_path = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
    if not csv_path.exists():
        return HTMLResponse("<h3>No detailed labor shifts report found. Run a fetch first.</h3>", status_code=404)

    headers: List[str] = []
    rows: List[dict] = []
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            rdr = csv.reader(f)
            for i, row in enumerate(rdr):
                if i == 0:
                    headers = row
                    continue
                # Build row dict with safe indexing
                r = {headers[j]: (row[j] if j < len(row) else "") for j in range(len(headers))}
                if (r.get("date") == biz_date) and (r.get("employee_guid") == employee_guid):
                    rows.append(r)
    except Exception:
        pass

    # Optional: derive employee name
    employee_name = ""
    try:
        emp_p = RAW_DIR / "employees.json"
        if emp_p.exists():
            with emp_p.open("r", encoding="utf-8") as ef:
                emps = json.load(ef) or []
            for e in emps:
                if e.get("guid") == employee_guid or e.get("v2EmployeeGuid") == employee_guid:
                    first = (e.get("firstName") or "").strip()
                    last = (e.get("lastName") or "").strip()
                    employee_name = (first + (" " + last if last else "")).strip()
                    break
    except Exception:
        pass

    title = f"Shifts for {employee_name or employee_guid} on {biz_date}"
    # Reuse generic report view template
    return templates.TemplateResponse(
        "report_view.html",
        {
            "request": request,
            "title": title,
            "name": "labor_shifts_detailed_daily.csv",
            "headers": headers,
            "rows": rows,
        },
    )

def _walk_json(obj: Any, path: str = "$"):
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from _walk_json(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_json(v, f"{path}[{i}]")


def _object_contains_guid(obj: Any, guid: str) -> bool:
    if isinstance(obj, dict):
        for v in obj.values():
            if _object_contains_guid(v, guid):
                return True
        return False
    if isinstance(obj, list):
        return any(_object_contains_guid(v, guid) for v in obj)
    try:
        return str(obj) == guid
    except Exception:
        return False


@app.get("/inspect/{guid}", response_class=HTMLResponse)
def inspect_guid(request: Request, guid: str):
    import json
    matches: List[Dict[str, Any]] = []
    files_scanned = 0
    for p in sorted((RAW_DIR).rglob("*.json")):
        files_scanned += 1
        try:
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        for path_str, obj in _walk_json(data):
            if isinstance(obj, dict) and _object_contains_guid(obj, guid):
                try:
                    snippet = json.dumps(obj, indent=2)[:50000]
                except Exception:
                    snippet = str(obj)[:10000]
                matches.append({
                    "file": str(p.relative_to(ROOT)),
                    "path": path_str,
                    "json_str": snippet,
                })
                # no match limit

    return templates.TemplateResponse(
        "inspect.html",
        {
            "request": request,
            "title": f"Inspect {guid}",
            "guid": guid,
            "matches": matches,
            "files_scanned": files_scanned,
            "matches_count": len(matches),
        },
    )


@app.get("/reconcile/orders-by-server/{biz_date}", response_class=HTMLResponse)
def reconcile_orders_by_server(request: Request, biz_date: str, server: str):
    """
    Compare exported OrderDetails CSV for a date with raw orders JSON, filtered by server full name.
    Expects CSV path: OrderDetails_YYYY_MM_DD.csv at project root.
    """
    # Build CSV filename in project root
    try:
        d = dt_date.fromisoformat(biz_date)
    except Exception:
        return HTMLResponse("Invalid date. Use YYYY-MM-DD.", status_code=400)

    csv_name = f"OrderDetails_{d.year}_{d.month:02d}_{d.day:02d}.csv"
    csv_path = ROOT / csv_name
    if not csv_path.exists():
        return HTMLResponse(f"CSV not found: {csv_name}", status_code=404)

    # Normalize server for case-insensitive comparisons
    server_norm = (server or "").strip().lower()

    # Load CSV rows for the server
    csv_rows = []
    with csv_path.open("r", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            if (r.get("Server") or "").strip().lower() == server_norm:
                # Normalize order display number to string for consistent keys
                disp = (r.get("Order #") or "").strip()
                r["Order #"] = disp
                csv_rows.append(r)

    csv_disp_set = {r.get("Order #") for r in csv_rows if r.get("Order #")}

    # Load raw orders for that date
    import json
    orders_path = RAW_DIR / "orders" / f"{biz_date}.json"
    if not orders_path.exists():
        return HTMLResponse(f"No raw orders found for {biz_date}.", status_code=404)
    with orders_path.open("r", encoding="utf-8") as f:
        orders = json.load(f) or []

    # Build employee name map
    emp_name_by_guid: Dict[str, str] = {}
    emp_path = RAW_DIR / "employees.json"
    if emp_path.exists():
        try:
            with emp_path.open("r", encoding="utf-8") as ef:
                emps = json.load(ef) or []
            for e in emps:
                first = (e.get("firstName") or "").strip()
                last = (e.get("lastName") or "").strip()
                full = (first + " " + last).strip()
                if e.get("guid"):
                    emp_name_by_guid[e.get("guid")] = full
                if e.get("v2EmployeeGuid"):
                    emp_name_by_guid[e.get("v2EmployeeGuid")] = full
        except Exception:
            pass

    # Map orders by displayNumber (string)
    def disp_str(o) -> str:
        v = o.get("displayNumber")
        return str(v) if v is not None else ""

    orders_by_disp: Dict[str, Dict[str, Any]] = {disp_str(o): o for o in orders}

    # Filter orders for this server by matching employee full name (via guid -> name)
    def order_server_name(o: Dict[str, Any]) -> str:
        try:
            guid = (o.get("server") or {}).get("guid")
            return (emp_name_by_guid.get(guid, "") or "").strip().lower()
        except Exception:
            return ""

    json_orders_for_server = [o for o in orders if order_server_name(o) == server_norm]
    json_disp_set = {disp_str(o) for o in json_orders_for_server if disp_str(o)}

    # Reconciliation
    matches = sorted(csv_disp_set & json_disp_set, key=lambda x: (len(x), x))
    missing_in_json = sorted(csv_disp_set - json_disp_set, key=lambda x: (len(x), x))
    extra_in_json = sorted(json_disp_set - csv_disp_set, key=lambda x: (len(x), x))

    # Details for matched orders
    matched_details = []
    for disp in matches:
        o = orders_by_disp.get(disp)
        if not o:
            continue
        checks = o.get("checks", []) or []
        total_amount = 0.0
        net_amount = 0.0
        for c in checks:
            if c.get("voided") or c.get("deleted"):
                continue
            try:
                total_amount += float(c.get("totalAmount") or 0)
                net_amount += float(c.get("amount") or 0)
            except Exception:
                pass
        matched_details.append({
            "display": disp,
            "order_guid": o.get("guid", ""),
            "checks_count": len(checks),
            "total_sales": f"{total_amount:.2f}",
            "net_sales": f"{net_amount:.2f}",
        })

    return templates.TemplateResponse(
        "reconcile_orders_by_server.html",
        {
            "request": request,
            "title": f"Reconcile {server} on {biz_date}",
            "biz_date": biz_date,
            "server": server,
            "csv_count": len(csv_rows),
            "json_count": len(json_orders_for_server),
            "matches": matches,
            "missing_in_json": missing_in_json,
            "extra_in_json": extra_in_json,
            "matched_details": matched_details,
        },
    )


def _build_orders_report_csv(snapshot: Optional[Dict[str, Any]] = None, force: bool = False) -> int:
    """
    Build or incrementally extend orders_report.csv.

    When both an existing CSV and prior build metadata are available, this function appends rows only
    for newly-added order JSON files. Any file modification or removal triggers a full rebuild.
    Returns the number of new rows written.
    """
    snapshot = snapshot or _orders_report_sources_snapshot()
    def to_float(x):
        try:
            return float(x)
        except Exception:
            return 0.0

    orders_dir = RAW_DIR / "orders"
    if not orders_dir.exists():
        return 0

    orders_csv = REPORTS_DIR / "orders_report.csv"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    files_by_name: Dict[str, Path] = {p.name: p for p in sorted(orders_dir.glob("*.json"))}
    if not files_by_name:
        return 0

    prev_state = _get_build_state_entry(ORDERS_REPORT_KEY)
    prev_file_mtimes: Dict[str, float] = prev_state.get("file_mtimes") or {}
    prev_rows_total = int(prev_state.get("rows_written") or 0)

    append_mode = False
    files_to_process: List[str] = sorted(files_by_name.keys())

    if (
        not force
        and orders_csv.exists()
        and prev_file_mtimes
        and prev_rows_total > 0
    ):
        snapshot_files = snapshot.get("file_mtimes") or {}
        removed = any(name not in snapshot_files for name in prev_file_mtimes)
        modified = any(
            snapshot_files.get(name, 0.0) > (prev_file_mtimes.get(name, 0.0) + 1e-6)
            for name in snapshot_files
            if name in prev_file_mtimes
        )
        if removed or modified:
            # Fallback to full rebuild to avoid duplicate/dirty data.
            append_mode = False
            files_to_process = sorted(snapshot_files.keys())
        else:
            new_files = sorted(name for name in snapshot_files if name not in prev_file_mtimes)
            if not new_files:
                # No new files and nothing changed; nothing to do.
                return 0
            files_to_process = new_files
            append_mode = True
    elif not orders_csv.exists():
        append_mode = False

    # Build employee GUID->name map for server lookups
    emp_map: Dict[str, str] = {}
    try:
        with (RAW_DIR / "employees.json").open("r", encoding="utf-8") as f:
            employees = json.load(f) or []
        emp_map = t.build_employee_map(employees) if employees else {}
    except Exception:
        emp_map = {}

    # Load sales category guid->name from menus.json for classification
    def load_sales_category_name_map() -> Dict[str, str]:
        mp: Dict[str, str] = {}
        p = RAW_DIR / "menus" / "menus.json"
        if not p.exists():
            return mp
        try:
            data = json.loads(p.read_text())
        except Exception:
            return mp
        def walk(o):
            if isinstance(o, dict):
                try:
                    if o.get("entityType") == "SalesCategory" and o.get("guid"):
                        nm = (o.get("name") or o.get("label") or o.get("displayName") or "").strip()
                        if nm:
                            mp[str(o["guid"])]=nm
                except Exception:
                    pass
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(data)
        return mp

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
        if ("wine" in n) and ("bottle" in n or "bottled" in n):
            return "Bottled Wine"
        if ("beer" in n) and ("bottle" in n or "bottled" in n):
            return "Bottled Beer"
        if n == "wine" or ("wine" in n):
            return "Wine"
        if ("draft" in n and "beer" in n) or n == "draft beer":
            return "Draft Beer"
        if any(k in n for k in ["liquor", "spirit", "cocktail", "whiskey", "vodka", "gin", "tequila", "rum", "bourbon", "rye", "mezcal"]):
            return "Liquor"
        if any(k in n for k in ["na beverage", "non-alcoholic", "n/a beverage", "mocktail", "soda", "juice", "coffee", "tea"]):
            return "NA Beverage"
        if "beer" in n:
            return "Draft Beer"
        return "Food"

    headers = [
        "business_date",
        "display_number",
        "order_guid",
        "server_guid",
        "server_name",
        "check_index",
        "payment_index",
        "check_tax_amount",
        "check_net_amount",
        "check_total_amount",
        "check_service_charges",
        "payment_type",
        "card_type",
        "payment_amount",
        "payment_tip_amount",
        "payment_amount_tendered",
        "payment_processing_fee",
        "payment_mca_repayment",
        "payment_server_guid",
        "payment_server_name",
        # Per-order category sales breakdown
        "food_sales",
        "wine_sales",
        "draft_beer_sales",
        "liquor_sales",
        "na_beverage_sales",
        "bottled_beer_sales",
        "bottled_wine_sales",
    ]

    def iter_order_rows(order_file: Path):
        try:
            with order_file.open("r", encoding="utf-8") as f:
                orders = json.load(f) or []
        except Exception:
            return
        order_bucket_totals: Dict[str, Dict[str, float]] = {}
        for o in orders:
            biz_date = o.get("businessDate", "")
            order_guid = o.get("guid", "")
            display_number = o.get("displayNumber", "")
            order_server_guid = ((o.get("server") or {}).get("guid") or "")
            order_server_name = emp_map.get(order_server_guid, "") if order_server_guid else ""

            if order_guid and order_guid not in order_bucket_totals:
                buckets = {k: 0.0 for k in BUCKETS}
                for c in (o.get("checks") or []):
                    if c.get("voided") or c.get("deleted"):
                        continue
                    for sel in (c.get("selections") or []):
                        if sel.get("voided") or sel.get("deleted"):
                            continue
                        price = to_float(sel.get("price"))
                        sc_guid = ((sel.get("salesCategory") or {}).get("guid")) or ""
                        sc_name = sales_cat_name_by_guid.get(str(sc_guid), "")
                        cat_bucket = bucket_for_cat_name(sc_name)
                        if (not sc_name) or (cat_bucket == "Food"):
                            disp = (sel.get("displayName") or "").strip().lower()
                            if disp:
                                if any(k in disp for k in ["cabernet", "pinot", "merlot", "chardonnay", "sauvignon", "malbec", "grigio", "riesling", "rose", "rosé", "wine"]):
                                    cat_bucket = "Wine"
                                elif any(k in disp for k in ["draft", "on tap", "pour", "pint"]) and "beer" in disp:
                                    cat_bucket = "Draft Beer"
                                elif any(k in disp for k in ["beer", "lager", "ipa", "stout", "ale"]) and "draft" in disp:
                                    cat_bucket = "Draft Beer"
                                elif any(k in disp for k in ["vodka", "whiskey", "whisky", "gin", "tequila", "rum", "bourbon", "rye", "mezcal", "cocktail"]):
                                    cat_bucket = "Liquor"
                                elif any(k in disp for k in ["na", "non-alcoholic", "mocktail", "soda", "juice", "coffee", "tea"]):
                                    cat_bucket = "NA Beverage"
                        buckets[cat_bucket] = buckets.get(cat_bucket, 0.0) + price
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
                    yield {
                        "business_date": biz_date,
                        "order_guid": order_guid,
                        "display_number": display_number,
                        "server_guid": order_server_guid,
                        "server_name": order_server_name,
                        "check_index": ci,
                        "payment_index": "",
                        "check_tax_amount": f"{tax_amount:.2f}",
                        "check_net_amount": f"{net_amount:.2f}",
                        "check_total_amount": f"{total_amount:.2f}",
                        "check_service_charges": f"{svc:.2f}",
                        "payment_type": "",
                        "card_type": "",
                        "payment_amount": "",
                        "payment_tip_amount": "",
                        "payment_amount_tendered": "",
                        "payment_processing_fee": "",
                        "payment_mca_repayment": "",
                        "payment_server_guid": "",
                        "payment_server_name": "",
                        "food_sales": f"{b.get('Food', 0.0):.2f}",
                        "wine_sales": f"{b.get('Wine', 0.0):.2f}",
                        "draft_beer_sales": f"{b.get('Draft Beer', 0.0):.2f}",
                        "liquor_sales": f"{b.get('Liquor', 0.0):.2f}",
                        "na_beverage_sales": f"{b.get('NA Beverage', 0.0):.2f}",
                        "bottled_beer_sales": f"{b.get('Bottled Beer', 0.0):.2f}",
                        "bottled_wine_sales": f"{b.get('Bottled Wine', 0.0):.2f}",
                    }
                    continue

                for pi, pay in enumerate(payments):
                    pay_server_guid = (((pay or {}).get("server") or {}).get("guid") or "")
                    pay_server_name = emp_map.get(pay_server_guid, "") if pay_server_guid else ""
                    b = order_bucket_totals.get(order_guid, {})
                    yield {
                        "business_date": biz_date,
                        "order_guid": order_guid,
                        "display_number": display_number,
                        "server_guid": order_server_guid,
                        "server_name": order_server_name,
                        "check_index": ci,
                        "payment_index": pi,
                        "check_tax_amount": f"{tax_amount:.2f}",
                        "check_net_amount": f"{net_amount:.2f}",
                        "check_total_amount": f"{total_amount:.2f}",
                        "check_service_charges": f"{svc:.2f}",
                        "payment_type": pay.get("type", ""),
                        "card_type": pay.get("cardType", ""),
                        "payment_amount": f"{to_float(pay.get('amount')):.2f}",
                        "payment_tip_amount": f"{to_float(pay.get('tipAmount')):.2f}",
                        "payment_amount_tendered": f"{to_float(pay.get('amountTendered')):.2f}",
                        "payment_processing_fee": f"{to_float(pay.get('originalProcessingFee')):.2f}",
                        "payment_mca_repayment": f"{to_float(pay.get('mcaRepaymentAmount')):.2f}",
                        "payment_server_guid": pay_server_guid,
                        "payment_server_name": pay_server_name,
                        "food_sales": f"{b.get('Food', 0.0):.2f}",
                        "wine_sales": f"{b.get('Wine', 0.0):.2f}",
                        "draft_beer_sales": f"{b.get('Draft Beer', 0.0):.2f}",
                        "liquor_sales": f"{b.get('Liquor', 0.0):.2f}",
                        "na_beverage_sales": f"{b.get('NA Beverage', 0.0):.2f}",
                        "bottled_beer_sales": f"{b.get('Bottled Beer', 0.0):.2f}",
                        "bottled_wine_sales": f"{b.get('Bottled Wine', 0.0):.2f}",
                    }

    rows_written = 0

    if append_mode:
        with orders_csv.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            for fname in files_to_process:
                path = files_by_name.get(fname)
                if not path:
                    continue
                for row in iter_order_rows(path):
                    writer.writerow(row)
                    rows_written += 1
    else:
        tmp_fd, tmp_path = tempfile.mkstemp(prefix="orders_report_", suffix=".csv.tmp", dir=str(REPORTS_DIR))
        try:
            with os.fdopen(tmp_fd, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                for fname in files_to_process:
                    path = files_by_name.get(fname)
                    if not path:
                        continue
                    for row in iter_order_rows(path):
                        writer.writerow(row)
                        rows_written += 1
            Path(tmp_path).replace(orders_csv)
        except Exception:
            # Ensure temp file removed on failure
            Path(tmp_path).unlink(missing_ok=True)  # type: ignore[arg-type]
            raise

    total_rows = rows_written + (prev_rows_total if append_mode else 0)

    _update_build_state_entry(
        ORDERS_REPORT_KEY,
        {
            "built_at": time.time(),
            "latest_source_mtime": snapshot.get("latest_source_mtime", 0.0),
            "orders_file_count": snapshot.get("orders_file_count", 0),
            "file_mtimes": snapshot.get("file_mtimes", {}),
            "employees_mtime": snapshot.get("employees_mtime", 0.0),
            "menus_mtime": snapshot.get("menus_mtime", 0.0),
            "rows_written": total_rows,
        },
    )
    return rows_written

# Workers management
@app.get("/workers", response_class=HTMLResponse)
def list_workers(request: Request):
    # Ensure employees are synced as workers before listing
    try:
        sync_employees_to_workers()
    except Exception:
        pass
    db = DatabaseManager()
    try:
        workers = db.load_workers()
    finally:
        db.close()
    return templates.TemplateResponse(
        "workers.html",
        {
            "request": request,
            "title": "Workers",
            "workers": workers,
        },
    )


@app.post("/workers/add")
def add_worker(name: str = Form(...)):
    db = DatabaseManager()
    try:
        db.add_worker(name)
    finally:
        db.close()
    return RedirectResponse(url="/workers", status_code=303)


# Server Tips form
@app.get("/server-tips", response_class=HTMLResponse)
def get_server_tips(request: Request):
    # Ensure employees are synced as workers before listing
    try:
        sync_employees_to_workers()
    except Exception:
        pass
    # Build eligible workers from employees.json filtered by job titles containing 'server'
    workers: List[str] = []
    try:
        with (RAW_DIR / "employees.json").open("r", encoding="utf-8") as f:
            emps = json.load(f) or []
        try:
            job_map = t.load_job_map()
        except Exception:
            job_map = {}
        for e in emps:
            if e.get("deleted") is True:
                continue
            # resolve job titles and check for 'server'
            has_server = False
            for ref in (e.get("jobReferences") or []):
                guid = (ref or {}).get("guid")
                title = job_map.get(guid) if guid else None
                if title and ("server" in str(title).lower()):
                    has_server = True
                    break
            if not has_server:
                continue
            first = (e.get("firstName") or "").strip()
            last = (e.get("lastName") or "").strip()
            full = (first + (" " + last if last else "")).strip()
            if full:
                workers.append(full)
        # de-duplicate and sort
        workers = sorted(list(dict.fromkeys(workers)))
    except Exception:
        workers = []
    buckets = BUCKET_DISPLAY_NAMES
    defaults = {
        "cashtips": 0.0,
        "creditcardtip": 0.0,
        "gratuity": 0.0,
        "netsales": 0.0,
        "bartips": 0.0,
        "servertips": 0.0,
        "expotips": 0.0,
        "runnertips": 0.0,
    }
    today_str = dt_date.today().isoformat()
    return templates.TemplateResponse(
        "server_tips.html",
        {
            "request": request,
            "title": "Server Tips",
            "workers": workers,
            "buckets": buckets,
            "defaults": defaults,
            "date_str": today_str,
            "result": None,
        },
    )


@app.post("/server-tips", response_class=HTMLResponse)
def post_server_tips(
    request: Request,
    worker_name: str = Form(...),
    bucket: str | None = Form(None),
    date: str | None = Form(None),
    action: str = Form("save"),
    bartips: float = Form(0.0),
    servertips: float = Form(0.0),
    expotips: float = Form(0.0),
    runnertips: float = Form(0.0),
    cashtips: float = Form(0.0),
    creditcardtip: float = Form(0.0),
    gratuity: float = Form(0.0),
    netsales: float = Form(0.0),
):
    # Helper to build workers list (servers) and buckets
    def _load_server_workers() -> List[str]:
        ws: List[str] = []
        try:
            with (RAW_DIR / "employees.json").open("r", encoding="utf-8") as f:
                emps = json.load(f) or []
            try:
                job_map = t.load_job_map()
            except Exception:
                job_map = {}
            for e in emps:
                if e.get("deleted") is True:
                    continue
                # resolve job titles and check for 'server'
                has_server = False
                for ref in (e.get("jobReferences") or []):
                    guid = (ref or {}).get("guid")
                    title = job_map.get(guid) if guid else None
                    if title and ("server" in str(title).lower()):
                        has_server = True
                        break
                if not has_server:
                    continue
                first = (e.get("firstName") or "").strip()
                last = (e.get("lastName") or "").strip()
                full = (first + (" " + last if last else "")).strip()
                if full:
                    ws.append(full)
            # de-duplicate and sort
            ws = sorted(list(dict.fromkeys(ws)))
        except Exception:
            ws = []
        return ws

    # "Undo Payouts": remove unpaid payouts for this worker/date/bucket
    if action == "undo_payouts":
        biz_date = date or dt_date.today().isoformat()
        workers = _load_server_workers()
        buckets = BUCKET_DISPLAY_NAMES
        defaults = {
            "cashtips": cashtips,
            "creditcardtip": creditcardtip,
            "gratuity": gratuity,
            "netsales": netsales,
            "bartips": bartips,
            "servertips": servertips,
            "expotips": expotips,
            "runnertips": runnertips,
        }
        if not bucket:
            result = {
                "saved": False,
                "errors": ["Choose a location (bucket) first, then click Undo Payouts."],
                "worker_name": worker_name,
                "bucket": bucket,
            }
            return templates.TemplateResponse(
                "server_tips.html",
                {
                    "request": request,
                    "title": "Server Tips",
                    "workers": workers,
                    "buckets": buckets,
                    "defaults": defaults,
                    "date_str": biz_date,
                    "result": result,
                },
            )
        # Perform delete
        deleted = 0
        try:
            dbu = DatabaseManager()
            try:
                deleted = dbu.delete_unpaid_server_payouts(worker_name, bucket, biz_date)
            finally:
                dbu.close()
        except Exception as ex:
            result = {
                "saved": False,
                "errors": [f"Failed to undo payouts: {ex}"],
                "worker_name": worker_name,
                "bucket": bucket,
            }
            return templates.TemplateResponse(
                "server_tips.html",
                {
                    "request": request,
                    "title": "Server Tips",
                    "workers": workers,
                    "buckets": buckets,
                    "defaults": defaults,
                    "date_str": biz_date,
                    "result": result,
                },
            )
        # After deletion, refresh pushed totals
        try:
            db2 = DatabaseManager()
            try:
                pushed_map = db2.get_unpaid_pushed_sums_for_server(worker_name, bucket, biz_date)
                committed_map = db2.get_committed_sums_for_server(worker_name, bucket, biz_date)
            finally:
                db2.close()
            pushed = {
                "Bartender": float(pushed_map.get("Bartender", 0.0) or 0.0),
                "Busser": float(pushed_map.get("Busser", 0.0) or 0.0),
                "Expo": float(pushed_map.get("Expo", 0.0) or 0.0),
                "Runner": float(pushed_map.get("Runner", 0.0) or 0.0),
                "Total": float(sum((pushed_map or {}).values()) if pushed_map else 0.0),
            }
            committed = {
                "Bartender": float(committed_map.get("Bartender", 0.0) or 0.0),
                "Busser": float(committed_map.get("Busser", 0.0) or 0.0),
                "Expo": float(committed_map.get("Expo", 0.0) or 0.0),
                "Runner": float(committed_map.get("Runner", 0.0) or 0.0),
                "Total": float(sum((committed_map or {}).values()) if committed_map else 0.0),
            }
        except Exception:
            pushed = {"Bartender": 0.0, "Busser": 0.0, "Expo": 0.0, "Runner": 0.0, "Total": 0.0}
            committed = {"Bartender": 0.0, "Busser": 0.0, "Expo": 0.0, "Runner": 0.0, "Total": 0.0}
        result = {
            "saved": False,
            "errors": [],
            "worker_name": worker_name,
            "bucket": bucket,
            "undo_message": f"Undid {deleted} payout record(s) for {worker_name} on {biz_date} in {bucket}.",
            "pushed": pushed,
            "committed": committed,
            # Preserve basic computed values shown in table if any were present in the form
            "payout_tips": TipCalculator.calculate_total_tips(bartips, servertips, expotips, runnertips),
            "owed_to_server": TipCalculator.calculate_owed_amounts(cashtips, creditcardtip, gratuity, TipCalculator.calculate_total_tips(bartips, servertips, expotips, runnertips))[0],
            "owed_to_restaurant": TipCalculator.calculate_owed_amounts(cashtips, creditcardtip, gratuity, TipCalculator.calculate_total_tips(bartips, servertips, expotips, runnertips))[1],
            "gross_tip_pct": TipCalculator.calculate_gross_tip_percentage(cashtips, creditcardtip, gratuity, netsales),
        }
        return templates.TemplateResponse(
            "server_tips.html",
            {
                "request": request,
                "title": "Server Tips",
                "workers": workers,
                "buckets": buckets,
                "defaults": defaults,
                "date_str": biz_date,
                "result": result,
            },
        )

    # "Save": persist edited figures without pushing to payouts
    if action == "save":
        biz_date = date or dt_date.today().isoformat()
        workers = _load_server_workers()
        buckets = BUCKET_DISPLAY_NAMES
        defaults = {
            "cashtips": cashtips,
            "creditcardtip": creditcardtip,
            "gratuity": gratuity,
            "netsales": netsales,
            "bartips": bartips,
            "servertips": servertips,
            "expotips": expotips,
            "runnertips": runnertips,
        }
        db = DatabaseManager()
        try:
            tips_dict = {
                "bartips": bartips,
                "servertips": servertips,
                "expotips": expotips,
                "runnertips": runnertips,
                "cashtips": cashtips,
                "creditcardtip": creditcardtip,
                "gratuity": gratuity,
                "netsales": netsales,
            }
            try:
                db.save_transaction(worker_name, bucket, tips_dict, payouts=None)
            except Exception:
                pass
            try:
                total_payout_tips = TipCalculator.calculate_total_tips(bartips, servertips, expotips, runnertips)
                tipped_pct_text = TipCalculator.calculate_gross_tip_percentage(
                    float(cashtips or 0.0), float(creditcardtip or 0.0), float(gratuity or 0.0), float(netsales or 0.0)
                )
                jt_save = _resolve_job_title_for(worker_name, biz_date, bucket)
                db.save_server_entry(
                    date_str=biz_date,
                    server_name=worker_name,
                    bucket=bucket,
                    cash_tips=float(cashtips or 0.0),
                    non_cash_tips=float(creditcardtip or 0.0),
                    gratuity=float(gratuity or 0.0),
                    sum_tips_for_payout=float(total_payout_tips or 0.0),
                    net_sales=float(netsales or 0.0),
                    tipped_perc_of_net_sales=tipped_pct_text,
                    job_title=jt_save,
                    submit_id=None,
                )
            except Exception:
                pass
        finally:
            db.close()

        # Compute display fields for summary table
        payout_tips_val = TipCalculator.calculate_total_tips(bartips, servertips, expotips, runnertips)
        owed_s, owed_r = TipCalculator.calculate_owed_amounts(
            float(cashtips or 0.0), float(creditcardtip or 0.0), float(gratuity or 0.0), float(payout_tips_val or 0.0)
        )
        gross_pct = TipCalculator.calculate_gross_tip_percentage(
            float(cashtips or 0.0), float(creditcardtip or 0.0), float(gratuity or 0.0), float(netsales or 0.0)
        )

        result = {
            "saved": True,
            "errors": [],
            "worker_name": worker_name,
            "bucket": bucket,
            "payout_tips": payout_tips_val,
            "owed_to_server": owed_s,
            "owed_to_restaurant": owed_r,
            "gross_tip_pct": gross_pct,
        }
        return templates.TemplateResponse(
            "server_tips.html",
            {
                "request": request,
                "title": "Server Tips",
                "workers": workers,
                "buckets": buckets,
                "defaults": defaults,
                "date_str": biz_date,
                "result": result,
            },
        )

    # "Push to Payouts": record pools into payouts for the selected business date and bucket, then redirect to /payouts
    if action == "push_to_payouts":
        # Require a bucket selection for payouts
        if not bucket:
            workers = _load_server_workers()
            buckets = BUCKET_DISPLAY_NAMES
            defaults = {
                "cashtips": cashtips,
                "creditcardtip": creditcardtip,
                "gratuity": gratuity,
                "netsales": netsales,
                "bartips": bartips,
                "servertips": servertips,
                "expotips": expotips,
                "runnertips": runnertips,
            }
            result = {
                "saved": False,
                "errors": ["Please choose a location before pushing to payouts."]
            }
            return templates.TemplateResponse(
                "server_tips.html",
                {
                    "request": request,
                    "title": "Server Tips",
                    "workers": workers,
                    "buckets": buckets,
                    "defaults": defaults,
                    "date_str": date or dt_date.today().isoformat(),
                    "result": result,
                },
            )
        biz_date = date or dt_date.today().isoformat()
        db = DatabaseManager()
        try:
            # Persist the basic transaction as usual
            tips_dict = {
                "bartips": bartips,
                "servertips": servertips,
                "expotips": expotips,
                "runnertips": runnertips,
                "cashtips": cashtips,
                "creditcardtip": creditcardtip,
                "gratuity": gratuity,
                "netsales": netsales,
            }
            try:
                db.save_transaction(worker_name, bucket, tips_dict, payouts=None)
            except Exception:
                pass
            # Also persist the edited Main Figures into `servers` so /report reflects overrides
            try:
                total_payout_tips = TipCalculator.calculate_total_tips(bartips, servertips, expotips, runnertips)
                tipped_pct_text = TipCalculator.calculate_gross_tip_percentage(
                    float(cashtips or 0.0), float(creditcardtip or 0.0), float(gratuity or 0.0), float(netsales or 0.0)
                )
                # Resolve job title for context on the row
                jt_push = _resolve_job_title_for(worker_name, biz_date, bucket)
                db.save_server_entry(
                    date_str=biz_date,
                    server_name=worker_name,
                    bucket=bucket,
                    cash_tips=float(cashtips or 0.0),
                    non_cash_tips=float(creditcardtip or 0.0),
                    gratuity=float(gratuity or 0.0),
                    sum_tips_for_payout=float(total_payout_tips or 0.0),
                    net_sales=float(netsales or 0.0),
                    tipped_perc_of_net_sales=tipped_pct_text,
                    job_title=jt_push,
                    submit_id=None,
                )
            except Exception:
                # Non-fatal: continue with payouts even if the summary save fails
                pass
            # Record raw payout pools with business_date so they appear as unpaid for that day
            # Resolve job_title to attach to payouts
            jt_push = _resolve_job_title_for(worker_name, biz_date, bucket)
            db.record_server_payouts(
                server_name=worker_name,
                bucket=bucket,
                business_date=biz_date,
                bartips=bartips,
                servertips=servertips,
                expotips=expotips,
                runnertips=runnertips,
                submit_id=None,
                job_title=jt_push,
            )
        finally:
            db.close()
        # Redirect to payouts with filters applied
        redirect_url = f"/payouts?bucket={bucket}&business_date={biz_date}&message=" + (
            "Pushed+server+tips+to+payouts" 
        )
        return RedirectResponse(url=redirect_url, status_code=303)

    # Fallback: default flow continues below

    # If "Fetch from Toast" requested, resolve employee GUID and compute from local orders JSON only
    if action == "fetch_toast":
        message = None
        defaults = {
            "cashtips": cashtips,
            "creditcardtip": creditcardtip,
            "gratuity": gratuity,
            "netsales": netsales,
            "bartips": bartips,
            "servertips": servertips,
            "expotips": expotips,
            "runnertips": runnertips,
        }
        if not date:
            date = dt_date.today().isoformat()
        # Resolve GUID by matching worker_name in employees.json (chosenName-aware, case-insensitive)
        emp_guid = None
        try:
            with (RAW_DIR / "employees.json").open("r", encoding="utf-8") as f:
                emps = json.load(f) or []
            target = (worker_name or "").strip()
            target_lc = target.lower()
            best_match = None
            for e in emps:
                first = (e.get("firstName") or "").strip()
                last = (e.get("lastName") or "").strip()
                chosen = (e.get("chosenName") or "").strip()
                full = (first + " " + last).strip()
                candidates = [c for c in [chosen, full] if c]
                for cand in candidates:
                    if cand == target:
                        best_match = e
                        break
                if best_match:
                    break
                for cand in candidates:
                    if cand.lower() == target_lc:
                        best_match = e
                        break
                if best_match:
                    break
            if best_match:
                emp_guid = best_match.get("guid") or best_match.get("id") or best_match.get("v2EmployeeGuid") or None
        except Exception:
            emp_guid = None

        workers = _load_server_workers()
        buckets = BUCKET_DISPLAY_NAMES
        bucket_display_map = {bid: bname for bid, bname in buckets}

        if not emp_guid:
            result = {
                "saved": False,
                "errors": ["Selected worker is not linked to a Toast employee GUID. Please link or ensure names match."],
            }
            return templates.TemplateResponse(
                "server_tips.html",
                {
                    "request": request,
                    "title": "Server Tips",
                    "workers": workers,
                    "buckets": buckets,
                    "defaults": defaults,
                    "date_str": date,
                    "result": result,
                },
            )

        # Helper: map job title to bucket id
        def job_title_to_bucket_id(title: str | None) -> str | None:
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
            return None

        # Detect suggested buckets from labor_shifts_detailed_daily.csv for the given date/employee
        suggested_bucket_ids: list[str] = []
        detected_job_titles: list[str] = []
        try:
            import csv as _csv
            path = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
            if path.exists():
                with path.open("r", encoding="utf-8") as fcsv:
                    rdr = _csv.DictReader(fcsv)
                    for r in rdr:
                        emp_aliases = set([emp_guid])
                        try:
                            if best_match:
                                for k in ("guid", "id", "v2EmployeeGuid"):
                                    v = (best_match.get(k) or "").strip()
                                    if v:
                                        emp_aliases.add(v)
                        except Exception:
                            pass
                        if (r.get("date") == date) and (r.get("employee_guid") in emp_aliases):
                            jt = r.get("job_title") or ""
                            if jt:
                                detected_job_titles.append(jt)
                                bid = job_title_to_bucket_id(jt)
                                if bid and bid not in suggested_bucket_ids:
                                    suggested_bucket_ids.append(bid)
        except Exception:
            pass

        # If no suggestions found from labor_shifts_detailed_daily, derive fallback buckets from time_entries job titles
        fallback_bucket_ids: list[str] = []
        if not suggested_bucket_ids:
            try:
                te_path_fb = RAW_DIR / "time_entries" / f"{date}.json"
                if te_path_fb.exists() and emp_guid:
                    import json as _json
                    with te_path_fb.open("r", encoding="utf-8") as ftefb:
                        te_list_fb = _json.load(ftefb) or []
                    fb_set: set[str] = set()
                    for tefb in (te_list_fb or []):
                        ref = tefb.get("employeeReference") or {}
                        if ref.get("guid") != emp_guid:
                            continue
                        jt_fb = tefb.get("jobTitle") or ((tefb.get("job") or {}).get("name")) or ""
                        bid_fb = job_title_to_bucket_id(jt_fb)
                        if bid_fb:
                            fb_set.add(bid_fb)
                    fallback_bucket_ids = sorted(list(fb_set))
            except Exception:
                fallback_bucket_ids = []
        # Auto-select bucket if exactly one suggestion
        auto_bucket: str | None = suggested_bucket_ids[0] if len(suggested_bucket_ids) == 1 else None

        # Build shift windows for the selected bucket respecting user choice.
        # Normalize the incoming bucket to a canonical bucket ID. Accept either ID or display name.
        # '' or None means All Locations (no bucket filter).
        bucket_provided = (bucket is not None)
        canonical_bucket: str | None = None
        if bucket_provided:
            val = (bucket or "").strip()
            if val == "":
                canonical_bucket = None
            else:
                # Try exact ID first
                ids = [bid for bid, _nm in (buckets or [])]
                if val in ids:
                    canonical_bucket = val
                else:
                    # Try display name case-insensitive match
                    lc = val.lower()
                    for bid, bname in (buckets or []):
                        if (bname or "").strip().lower() == lc:
                            canonical_bucket = bid
                            break
                    # Fallback: keep original string (may still work if equals ID)
                    if canonical_bucket is None and val:
                        canonical_bucket = val
        else:
            canonical_bucket = auto_bucket or None
        selected_bucket = canonical_bucket
        shift_windows: list[tuple[datetime, datetime]] = []
        filter_windows_str: list[str] = []
        filter_windows_local: list[str] = []
        if selected_bucket:
            try:
                import csv as _csv
                # Local timezone for Missouri (handles DST)
                try:
                    from zoneinfo import ZoneInfo  # py3.9+
                    CT_TZ = ZoneInfo("America/Chicago")
                except Exception:
                    CT_TZ = None
                path = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
                # Collect all shifts for the employee on the date: server shifts (bucketed) and 'Cleaning - Server'
                server_shifts: list[tuple[str, datetime, datetime]] = []  # (bucket_id, start, end)
                cleaning_shifts: list[tuple[datetime, datetime]] = []
                if path.exists():
                    with path.open("r", encoding="utf-8") as fcsv:
                        rdr = _csv.DictReader(fcsv)
                        for r in rdr:
                            csv_date = (r.get("date") or "").strip()
                            ok_date = (csv_date == date)
                            if not ok_date:
                                try:
                                    from datetime import datetime as _dt
                                    # parse both formats
                                    def _parse_d(s: str):
                                        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
                                            try:
                                                return _dt.strptime(s, fmt).date()
                                            except Exception:
                                                continue
                                        return None
                                    d_csv = _parse_d(csv_date)
                                    d_sel = _parse_d(date or "")
                                    ok_date = bool(d_csv and d_sel and d_csv == d_sel)
                                except Exception:
                                    ok_date = False
                            emp_aliases2 = set([emp_guid])
                            try:
                                if best_match:
                                    for k in ("guid", "id", "v2EmployeeGuid"):
                                        v = (best_match.get(k) or "").strip()
                                        if v:
                                            emp_aliases2.add(v)
                            except Exception:
                                pass
                            if ok_date and (r.get("employee_guid") in emp_aliases2):
                                jt = (r.get("job_title") or "").strip()
                                st = _parse_iso(r.get("start_time_utc"))
                                en = _parse_iso(r.get("end_time_utc"))
                                if not (st and en and en > st):
                                    continue
                                try:
                                    st = st.astimezone(timezone.utc)
                                    en = en.astimezone(timezone.utc)
                                except Exception:
                                    pass
                                bid = job_title_to_bucket_id(jt)
                                if bid:
                                    server_shifts.append((bid, st, en))
                                else:
                                    # Track Cleaning - Server explicitly (case-insensitive match)
                                    if jt.lower() == "cleaning - server":
                                        cleaning_shifts.append((st, en))
                # Always include the selected bucket's actual server shifts as windows
                for bid, st, en in server_shifts:
                    if bid == selected_bucket:
                        shift_windows.append((st, en))
                        filter_windows_str.append(f"{st.isoformat()} — {en.isoformat()}")
                        if CT_TZ:
                            try:
                                st_local = st.astimezone(CT_TZ)
                                en_local = en.astimezone(CT_TZ)
                                filter_windows_local.append(f"{st_local.strftime('%Y-%m-%d %I:%M %p %Z')} — {en_local.strftime('%Y-%m-%d %I:%M %p %Z')}")
                            except Exception:
                                pass
                # Reassign Cleaning - Server windows to nearest server shift bucket
                if cleaning_shifts:
                    # Helper for midpoint
                    def _mid(a: datetime, b: datetime) -> float:
                        try:
                            return ((a.timestamp() + b.timestamp()) / 2.0)
                        except Exception:
                            return a.timestamp()
                    # Build midpoints for server shifts by bucket
                    server_mids: list[tuple[str, float, datetime, datetime]] = []
                    for bid, st, en in server_shifts:
                        server_mids.append((bid, _mid(st, en), st, en))
                    # Fallback when there are no server shifts that day: assign all cleaning to AM
                    for stc, enc in cleaning_shifts:
                        assigned_bid: str | None = None
                        if server_mids:
                            mid_c = _mid(stc, enc)
                            # find nearest by absolute distance; tie-break by earlier server shift start time
                            best = None  # (abs_dist, start_time, bid)
                            for bid, mid_s, st_s, _en_s in server_mids:
                                try:
                                    dist = abs(mid_s - mid_c)
                                except Exception:
                                    dist = 0.0
                                key = (dist, st_s)
                                if (best is None) or (key < (best[0], best[1])):
                                    best = (dist, st_s, bid)
                            if best:
                                assigned_bid = best[2]
                        else:
                            assigned_bid = "am_bar"
                        # If this cleaning window belongs to the selected bucket, include it
                        if assigned_bid == selected_bucket:
                            shift_windows.append((stc, enc))
                            filter_windows_str.append(f"{stc.isoformat()} — {enc.isoformat()} (Cleaning→{assigned_bid})")
                            if CT_TZ:
                                try:
                                    st_local = stc.astimezone(CT_TZ)
                                    en_local = enc.astimezone(CT_TZ)
                                    filter_windows_local.append(f"{st_local.strftime('%Y-%m-%d %I:%M %p %Z')} — {en_local.strftime('%Y-%m-%d %I:%M %p %Z')} (Cleaning→{assigned_bid})")
                                except Exception:
                                    pass
            except Exception:
                shift_windows = []

        # Compute directly from local orders JSON; do not call Toast API
        order_guids_used: list[str] = []
        # Map of order_guid -> list of {display_number, tip_amount}
        order_checks_by_order: dict[str, list[dict]] = {}
        # 1) Cash tips & Gratuity from local time entries (declaredCashTips and *_GratuityServiceCharges)
        try:
            declared_cash_sum = 0.0
            gratuity_te_sum = 0.0
            te_path = RAW_DIR / "time_entries" / f"{date}.json"
            if te_path.exists():
                import json as _json
                with te_path.open("r", encoding="utf-8") as fte:
                    te_data = _json.load(fte) or []
                # Normalize selected business date to YYYYMMDD for comparison
                try:
                    sel_biz = t.normalize_business_date(date)
                except Exception:
                    sel_biz = (date or "").replace("-", "")
                for te in te_data:
                    try:
                        emp_ref = (te.get("employeeReference") or {})
                        if emp_ref.get("guid") != emp_guid:
                            continue
                        if (te.get("businessDate") or "") != sel_biz:
                            continue
                        # If a specific bucket is selected, only include time entries that overlap finalized shift_windows
                        if selected_bucket and shift_windows:
                            st_te = _parse_iso(te.get("inDate") or te.get("startDate"))
                            en_te = _parse_iso(te.get("outDate") or te.get("endDate"))
                            if not (st_te and en_te and en_te > st_te):
                                continue
                            try:
                                st_te = st_te.astimezone(timezone.utc)
                                en_te = en_te.astimezone(timezone.utc)
                            except Exception:
                                pass
                            overlaps = False
                            for stw, enw in shift_windows:
                                if st_te <= enw and en_te >= stw:
                                    overlaps = True
                                    break
                            if not overlaps:
                                continue
                        dct = te.get("declaredCashTips")
                        if dct is not None:
                            try:
                                declared_cash_sum += float(dct)
                            except Exception:
                                pass
                        # Sum gratuity service charges from time entries (filtered by overlap if selected_bucket)
                        try:
                            gratuity_te_sum += float(te.get("cashGratuityServiceCharges") or 0.0)
                        except Exception:
                            pass
                        try:
                            gratuity_te_sum += float(te.get("nonCashGratuityServiceCharges") or 0.0)
                        except Exception:
                            pass
                    except Exception:
                        continue
            # Initialize defaults with declared cash tips; orders parsing may run next for other fields
            defaults["cashtips"] = round(declared_cash_sum, 2)
            # Stash time-entry gratuity for addition with orders gratuity later
            gratuity_from_time_entries = round(gratuity_te_sum, 2)
        except Exception:
            # Leave defaults["cashtips"] as provided if any error
            gratuity_from_time_entries = 0.0
        try:
            import json as _json
            orders_path = RAW_DIR / "orders" / f"{date}.json"
            if orders_path.exists():
                with orders_path.open("r", encoding="utf-8") as f:
                    orders_data = _json.load(f) or []
                def to_float(x):
                    try:
                        return float(x)
                    except Exception:
                        return 0.0
                cc_tips = 0.0
                # cash_tips will be derived from declaredCashTips above; still track any explicit CASH payments for reference if needed
                cash_tips = 0.0
                net_sales_sum = 0.0
                gratuity_sum_orders = 0.0
                # Category aggregation per selected server
                # Load sales category name map from menus.json
                def load_sales_category_name_map() -> Dict[str, str]:
                    """Prefer mapping from data/reports/menu_category.csv, fallback to Toast API and menus.json."""
                    import csv as _csv
                    mp: Dict[str, str] = {}
                    # 1) Try prebuilt CSV (fast, most accurate)
                    try:
                        csv_path = REPORTS_DIR / "menu_category.csv"
                        if csv_path.exists():
                            with csv_path.open("r", encoding="utf-8") as f:
                                rdr = _csv.DictReader(f)
                                for rr in rdr:
                                    gid = (rr.get("sales_category_guid") or "").strip()
                                    nm = (rr.get("sales_category_name") or "").strip()
                                    if gid and nm and gid not in mp:
                                        mp[gid] = nm
                    except Exception:
                        pass
                    # 2) If still empty, try Toast API
                    if not mp:
                        try:
                            from toast_client import ToastClient
                            tc = ToastClient()
                            mp = tc.get_sales_categories() or {}
                            # ensure keys are strings
                            mp = {str(k): v for k, v in (mp or {}).items()}
                        except Exception:
                            mp = {}
                    # 3) Supplement from menus.json
                    try:
                        p = RAW_DIR / "menus" / "menus.json"
                        if p.exists():
                            data = json.loads(p.read_text())
                            def walk(o):
                                if isinstance(o, dict):
                                    try:
                                        if (o.get("entityType") == "SalesCategory") and o.get("guid"):
                                            gid = str(o.get("guid"))
                                            nm = (o.get("name") or o.get("label") or o.get("displayName") or "").strip()
                                            if gid and nm and gid not in mp:
                                                mp[gid] = nm
                                    except Exception:
                                        pass
                                    for v in o.values():
                                        walk(v)
                                elif isinstance(o, list):
                                    for v in o:
                                        walk(v)
                            walk(data)
                    except Exception:
                        pass
                    return mp
                sales_cat_name_by_guid = load_sales_category_name_map()
                BUCKETS = ["Food","Wine","Draft Beer","Liquor","NA Beverage","Bottled Beer","Bottled Wine"]
                def bucket_for_cat_name(name: str) -> str:
                    n=(name or "").strip().lower()
                    if not n:
                        return "Food"
                    if ("wine" in n) and ("bottle" in n or "bottled" in n):
                        return "Bottled Wine"
                    if ("beer" in n) and ("bottle" in n or "bottled" in n):
                        return "Bottled Beer"
                    if n=="wine" or ("wine" in n):
                        return "Wine"
                    if ("draft" in n and "beer" in n) or n=="draft beer":
                        return "Draft Beer"
                    if any(k in n for k in ["liquor","spirit","cocktail","whiskey","vodka","gin","tequila","rum","bourbon","rye","mezcal"]):
                        return "Liquor"
                    if any(k in n for k in ["na beverage","non-alcoholic","n/a beverage","mocktail","soda","juice","coffee","tea"]):
                        return "NA Beverage"
                    if "beer" in n:
                        return "Draft Beer"
                    return "Food"
                bucket_totals = {k: 0.0 for k in BUCKETS}
                # Build employee alias set for robust payment server matching (guid/id/v2EmployeeGuid)
                emp_aliases_pay: set[str] = set()
                try:
                    if best_match:
                        for k in ("guid", "id", "v2EmployeeGuid"):
                            v = (best_match.get(k) or "").strip()
                            if v:
                                emp_aliases_pay.add(v)
                except Exception:
                    pass
                emp_aliases_pay.add(emp_guid)

                for o in orders_data:
                    order_had_emp_payment = False
                    checks_for_order: list[dict] = []
                    for c in (o.get("checks") or []):
                        if c.get("voided") or c.get("deleted"):
                            continue
                        # Does this check contain any payment by the employee?
                        has_emp_payment = False
                        check_tip_sum_emp = 0.0
                        for p in (c.get("payments") or []):
                            srv_obj = (p.get("server") or {}) if isinstance(p, dict) else {}
                            psrv_ids = [
                                (srv_obj.get("guid") or ""),
                                (srv_obj.get("id") or ""),
                                (srv_obj.get("v2EmployeeGuid") or ""),
                            ]
                            matched_emp = False
                            for sid in psrv_ids:
                                sid = (sid or "").strip()
                                if sid and sid in emp_aliases_pay:
                                    matched_emp = True
                                    break
                            if matched_emp:
                                has_emp_payment = True
                                # Tip grouping by payment type
                                ptype = (p.get("type") or "").upper()
                                tip_amt = to_float(p.get("tipAmount"))
                                if ptype == "CASH":
                                    # We rely on declaredCashTips from time entries for "Cash Tips"
                                    # Still tally separately but do not override defaults["cashtips"] with this value
                                    cash_tips += tip_amt
                                else:
                                    cc_tips += tip_amt
                                check_tip_sum_emp += tip_amt
                        # If a bucket (location) is selected, restrict to checks within shift windows
                        if has_emp_payment:
                            if selected_bucket and shift_windows:
                                # Determine a representative check timestamp: paidDate, else closedDate, else openedDate
                                check_ts = _parse_iso(c.get("paidDate") or c.get("closedDate") or c.get("openedDate"))
                                if check_ts:
                                    try:
                                        check_ts = check_ts.astimezone(timezone.utc)
                                    except Exception:
                                        pass
                                # Keep only if within any window
                                in_window = False
                                if check_ts:
                                    for st, en in shift_windows:
                                        if st <= check_ts <= en:
                                            in_window = True
                                            break
                                if not in_window:
                                    continue
                            order_had_emp_payment = True
                            # Net sales fallback across common fields
                            amt_field = c.get("amount") or c.get("total") or c.get("net") or c.get("subtotal") or 0.0
                            net_sales_sum += to_float(amt_field)
                            # Sum gratuity from applied service charges on checks (orders)
                            try:
                                def _is_gratuity_sc(sc: dict) -> bool:
                                    try:
                                        if sc.get("isGratuity") is True:
                                            return True
                                        svc = sc.get("serviceCharge") or {}
                                        if (svc.get("isGratuity") is True) or (svc.get("gratuity") is True):
                                            return True
                                        name = (sc.get("name") or svc.get("name") or "").strip().lower()
                                        return "gratuity" in name
                                    except Exception:
                                        return False
                                for sc in (c.get("appliedServiceCharges") or []):
                                    if _is_gratuity_sc(sc or {}):
                                        # Prefer chargeAmount, else appliedAmount, else amount
                                        amt = (sc or {}).get("chargeAmount")
                                        if amt is None:
                                            amt = (sc or {}).get("appliedAmount")
                                        if amt is None:
                                            amt = (sc or {}).get("amount")
                                        gratuity_sum_orders += to_float(amt)
                            except Exception:
                                pass
                            # Aggregate selections by category bucket for this check
                            for sel in (c.get("selections") or []):
                                if sel.get("voided") or sel.get("deleted"):
                                    continue
                                price = to_float(sel.get("price"))
                                sc_guid = ((sel.get("salesCategory") or {}).get("guid")) or ""
                                sc_name = sales_cat_name_by_guid.get(str(sc_guid), "")
                                # If no explicit mapped sales category, skip this selection entirely (no heuristics)
                                if not sc_name:
                                    continue
                                cat_bucket = bucket_for_cat_name(sc_name)
                                bucket_totals[cat_bucket] = bucket_totals.get(cat_bucket, 0.0) + price
                            # Record check-level details for UI
                            try:
                                disp_num = c.get("displayNumber") or c.get("checkNumber") or ""
                            except Exception:
                                disp_num = ""
                            checks_for_order.append({
                                "display_number": disp_num,
                                "tip_amount": round(check_tip_sum_emp, 2),
                            })
                    if order_had_emp_payment:
                        og = o.get("guid") or ""
                        if og and og not in order_guids_used:
                            order_guids_used.append(og)
                        if og and checks_for_order:
                            order_checks_by_order[og] = checks_for_order
                # Always update defaults from computed values
                defaults["creditcardtip"] = round(cc_tips, 2)
                # Combine gratuity from time entries and orders service charges
                try:
                    defaults["gratuity"] = round((gratuity_from_time_entries or 0.0) + (gratuity_sum_orders or 0.0), 2)
                except Exception:
                    defaults["gratuity"] = round(gratuity_sum_orders, 2)
                # Net sales attributable to the employee within filters
                defaults["netsales"] = round(net_sales_sum, 2)
                # Build category-based tip pool suggestions from bucket_totals
                try:
                    category_totals = {k: round(float(v or 0.0), 2) for k, v in (bucket_totals or {}).items()}
                except Exception:
                    category_totals = {}
                total_sales_all = float(sum((category_totals or {}).values()) if category_totals else 0.0)
                def _round2(x):
                    try:
                        return round(float(x or 0.0), 2)
                    except Exception:
                        return 0.0
                # Per-category breakdowns
                bt_break: dict[str, float] = {}
                sv_break: dict[str, float] = {}
                ex_break: dict[str, float] = {}
                rn_break: dict[str, float] = {}
                for cat, amt in (category_totals or {}).items():
                    a = float(amt or 0.0)
                    # Bartender tips: 2% of all except Bottled Wine
                    bt_break[cat] = _round2(0.02 * a if cat != "Bottled Wine" else 0.0)
                    # Servertips: 2% of all categories
                    sv_break[cat] = _round2(0.02 * a)
                    # Expo: 1% of Food only
                    ex_break[cat] = _round2(0.01 * a if cat == "Food" else 0.0)
                    # Runner: 0.5% of Food only
                    rn_break[cat] = _round2(0.005 * a if cat == "Food" else 0.0)
                bartips_suggest = _round2(sum(bt_break.values()))
                servertips_suggest = _round2(sum(sv_break.values()))
                expotips_suggest = _round2(sum(ex_break.values()))
                runnertips_suggest = _round2(sum(rn_break.values()))
                # Update defaults for Add Tips for Payout from suggestions
                defaults["bartips"] = bartips_suggest
                defaults["servertips"] = servertips_suggest
                defaults["expotips"] = expotips_suggest
                defaults["runnertips"] = runnertips_suggest
                category_tip_breakdown = {
                    "bartips": bt_break,
                    "servertips": sv_break,
                    "expotips": ex_break,
                    "runnertips": rn_break,
                }
                # Recompute declared cash tips per BUCKET when a specific location is selected,
                # by summing declaredCashTips only for time entries that map to this bucket and
                # overlap the computed shift windows for the bucket.
                def _recompute_cash_for_bucket():
                    cash_bucket_sum = 0.0
                    te_path2 = RAW_DIR / "time_entries" / f"{date}.json"
                    if not (te_path2.exists() and selected_bucket and shift_windows):
                        return None
                    import json as _json
                    with te_path2.open("r", encoding="utf-8") as fte2:
                        te_list2 = _json.load(fte2) or []
                    # Normalize date to Toast businessDate format once
                    try:
                        sel_biz2 = t.normalize_business_date(date)
                    except Exception:
                        sel_biz2 = (date or "").replace("-", "")
                    for te2 in (te_list2 or []):
                        # Same date, same employee
                        if (te2.get("businessDate") or "") != sel_biz2:
                            continue
                        guid2 = ((te2.get("employeeReference") or {}).get("guid")) or ""
                        if not guid2 or guid2 != emp_guid:
                            continue
                        # Use overlap with finalized shift windows (which already include any reassigned Cleaning windows)
                        st2 = _parse_iso(te2.get("inDate") or te2.get("startDate"))
                        en2 = _parse_iso(te2.get("outDate") or te2.get("endDate"))
                        if not (st2 and en2 and en2 > st2):
                            continue
                        try:
                            st2 = st2.astimezone(timezone.utc)
                            en2 = en2.astimezone(timezone.utc)
                        except Exception:
                            pass
                        # Overlap with any of the bucket windows
                        in_any = False
                        for stw, enw in shift_windows:
                            if st2 <= enw and en2 >= stw:
                                in_any = True
                                break
                        if not in_any:
                            continue
                        dct2 = te2.get("declaredCashTips")
                        if dct2 is not None:
                            try:
                                cash_bucket_sum += float(dct2)
                            except Exception:
                                pass
                    return round(cash_bucket_sum, 2)
        except Exception:
            # If orders parsing or computations fail, continue with whatever defaults we have
            pass

        # If a specific bucket was selected and we have shift windows, override cashtips with bucket-specific sum
        try:
            if selected_bucket and shift_windows:
                _cb = _recompute_cash_for_bucket()
                if _cb is not None:
                    defaults["cashtips"] = _cb
        except Exception:
            pass

        # If a specific bucket is selected, override Credit Card Tip from the prebuilt CSV.
        # Enhanced: if row job_title is 'Cleaning - Server', reassign it to the nearest server shift bucket by proximity
        # (using server_shifts computed above) and include it if it maps to the selected bucket.
        try:
            if selected_bucket and emp_guid and date:
                csv_path_cc = REPORTS_DIR / "credit_tips_per_shift.csv"
                if csv_path_cc.exists():
                    import csv as _csv
                    cc_sum_csv = 0.0
                    with csv_path_cc.open("r", encoding="utf-8") as fcc:
                        rdrcc = _csv.DictReader(fcc)
                        for rr in (rdrcc or []):
                            if (rr.get("date") or "").strip() != (date or ""):
                                continue
                            eg = (rr.get("employee_guid") or "").strip()
                            if not eg or eg != emp_guid:
                                continue
                            jt = (rr.get("job_title") or rr.get("jobtitle") or "").strip()
                            bid = job_title_to_bucket_id(jt)
                            if bid != selected_bucket:
                                # Try reassignment for Cleaning - Server
                                if jt.strip().lower() == "cleaning - server":
                                    # Use midpoint proximity to nearest server shift
                                    try:
                                        st_csv = _parse_iso(rr.get("start_time_utc"))
                                        en_csv = _parse_iso(rr.get("end_time_utc"))
                                        if st_csv and en_csv and en_csv > st_csv:
                                            try:
                                                st_csv = st_csv.astimezone(timezone.utc)
                                                en_csv = en_csv.astimezone(timezone.utc)
                                            except Exception:
                                                pass
                                            mid_c = (st_csv.timestamp() + en_csv.timestamp())/2.0
                                            best = None  # (abs_dist, start_time, bid)
                                            if 'server_shifts' in locals() and server_shifts:
                                                for _bid, _st, _en in server_shifts:
                                                    try:
                                                        mid_s = (_st.timestamp() + _en.timestamp())/2.0
                                                        dist = abs(mid_s - mid_c)
                                                    except Exception:
                                                        dist = 0.0
                                                    key = (dist, _st)
                                                    if (best is None) or (key < (best[0], best[1])):
                                                        best = (dist, _st, _bid)
                                            assigned = best[2] if best else "am_bar"
                                            if assigned != selected_bucket:
                                                continue
                                        else:
                                            # No valid times; default assign to AM
                                            if selected_bucket != "am_bar":
                                                continue
                                    except Exception:
                                        # On any error fallback to AM only
                                        if selected_bucket != "am_bar":
                                            continue
                                else:
                                    continue
                            try:
                                cc_sum_csv += float(rr.get("credit_card_tips") or 0.0)
                            except Exception:
                                pass
                    defaults["creditcardtip"] = round(cc_sum_csv, 2)
        except Exception:
            pass

        # If a specific bucket is selected, override Cash Tips from the prebuilt CSV similarly,
        # reassigning 'Cleaning - Server' rows by proximity to the nearest server shift bucket.
        try:
            if selected_bucket and emp_guid and date:
                import csv as _csv
                csv_path_cash = REPORTS_DIR / "cash_tips_per_shift.csv"
                if csv_path_cash.exists():
                    cash_sum_csv = 0.0
                    _match_count = 0
                    with csv_path_cash.open("r", encoding="utf-8") as fct:
                        rdrc = _csv.DictReader(fct)
                        for rr in (rdrc or []):
                            if (rr.get("date") or "").strip() != (date or ""):
                                continue
                            if (rr.get("employee_guid") or "").strip() != emp_guid:
                                continue
                            jt = (rr.get("job_title") or rr.get("jobtitle") or "").strip()
                            bid = job_title_to_bucket_id(jt)
                            if bid != selected_bucket:
                                # Try reassignment for Cleaning - Server rows
                                if jt.strip().lower() == "cleaning - server":
                                    try:
                                        st_csv = _parse_iso(rr.get("start_time_utc"))
                                        en_csv = _parse_iso(rr.get("end_time_utc"))
                                        if st_csv and en_csv and en_csv > st_csv:
                                            try:
                                                st_csv = st_csv.astimezone(timezone.utc)
                                                en_csv = en_csv.astimezone(timezone.utc)
                                            except Exception:
                                                pass
                                            mid_c = (st_csv.timestamp() + en_csv.timestamp())/2.0
                                            best = None
                                            if 'server_shifts' in locals() and server_shifts:
                                                for _bid, _st, _en in server_shifts:
                                                    try:
                                                        mid_s = (_st.timestamp() + _en.timestamp())/2.0
                                                        dist = abs(mid_s - mid_c)
                                                    except Exception:
                                                        dist = 0.0
                                                    key = (dist, _st)
                                                    if (best is None) or (key < (best[0], best[1])):
                                                        best = (dist, _st, _bid)
                                            assigned = best[2] if best else "am_bar"
                                            if assigned != selected_bucket:
                                                continue
                                        else:
                                            if selected_bucket != "am_bar":
                                                continue
                                    except Exception:
                                        if selected_bucket != "am_bar":
                                            continue
                                else:
                                    continue
                            try:
                                cash_sum_csv += float(rr.get("declared_cash_tips") or 0.0)
                                _match_count += 1
                            except Exception:
                                pass
                    defaults["cashtips"] = round(cash_sum_csv, 2)
                    try:
                        _log(f"[server-tips] Cash CSV match for emp={emp_guid} date={date} bucket={selected_bucket}: rows={_match_count} sum={cash_sum_csv:.2f}")
                    except Exception:
                        pass
        except Exception:
            pass

        # Build minimal result payload for template and return
        try:
            # Compute totals used in summary table
            payout_tips_val = TipCalculator.calculate_total_tips(bartips, servertips, expotips, runnertips)
            # New owed amounts calculation per spec:
            #   Owed to Server = (total gratuity + non-cash tips) - Cash Collected
            #   If negative, becomes Owed to Restaurant as absolute value and Owed to Server = 0
            gratuity_total_sum = 0.0
            noncash_tips_sum = 0.0
            cash_collected_sum = 0.0

            # Load gratuity_per_shift.csv: sum gratuity_total for this date/employee, filtered by job_title -> selected bucket (when selected)
            try:
                import csv as _csv
                path_g = REPORTS_DIR / "gratuity_per_shift.csv"
                if path_g.exists() and emp_guid and date:
                    with path_g.open("r", encoding="utf-8") as fg:
                        rdrg = _csv.DictReader(fg)
                        for rr in (rdrg or []):
                            if (rr.get("date") or "").strip() != (date or ""):
                                continue
                            if (rr.get("employee_guid") or "").strip() != emp_guid:
                                continue
                            jt = (rr.get("job_title") or rr.get("jobtitle") or "").strip()
                            if selected_bucket:
                                bid = job_title_to_bucket_id(jt)
                                if bid != selected_bucket:
                                    continue
                            try:
                                gratuity_total_sum += float(rr.get("gratuity_total") or 0.0)
                            except Exception:
                                pass
            except Exception:
                pass

            # Load tips_by_server_shift.csv: sum tips_total for this date/employee; filter by job_title -> selected bucket when provided
            try:
                import csv as _csv
                path_t = REPORTS_DIR / "tips_by_server_shift.csv"
                if path_t.exists() and emp_guid and date:
                    with path_t.open("r", encoding="utf-8") as ft:
                        rdrt = _csv.DictReader(ft)
                        for rr in (rdrt or []):
                            if (rr.get("date") or "").strip() != (date or ""):
                                continue
                            if (rr.get("employee_guid") or "").strip() != emp_guid:
                                continue
                            if selected_bucket:
                                jt = (rr.get("job_title") or rr.get("jobtitle") or "").strip()
                                bid = job_title_to_bucket_id(jt)
                                if bid != selected_bucket:
                                    continue
                            try:
                                noncash_tips_sum += float(rr.get("tips_total") or 0.0)
                            except Exception:
                                pass
            except Exception:
                pass

            # Load payments_by_employee_per_shift.csv: sum total_amount where payment_group=CASH; filter by job_title -> selected bucket when provided
            try:
                import csv as _csv
                path_p = REPORTS_DIR / "payments_by_employee_per_shift.csv"
                if path_p.exists() and emp_guid and date:
                    with path_p.open("r", encoding="utf-8") as fp:
                        rdrp = _csv.DictReader(fp)
                        for rr in (rdrp or []):
                            if (rr.get("date") or "").strip() != (date or ""):
                                continue
                            if (rr.get("employee_guid") or "").strip() != emp_guid:
                                continue
                            if (rr.get("payment_group") or "").strip().upper() != "CASH":
                                continue
                            if selected_bucket:
                                jt = (rr.get("job_title") or rr.get("jobtitle") or "").strip()
                                bid = job_title_to_bucket_id(jt)
                                if bid != selected_bucket:
                                    continue
                            try:
                                cash_collected_sum += float(rr.get("total_amount") or 0.0)
                            except Exception:
                                pass
            except Exception:
                pass

            try:
                owed_calc = round((gratuity_total_sum + noncash_tips_sum) - cash_collected_sum, 2)
            except Exception:
                owed_calc = 0.0
            if owed_calc >= 0:
                owed_server, owed_rest = owed_calc, 0.0
            else:
                owed_server, owed_rest = 0.0, abs(owed_calc)
            gross_pct = TipCalculator.calculate_gross_tip_percentage(
                float(defaults.get("cashtips", 0.0) or 0.0),
                float(defaults.get("creditcardtip", 0.0) or 0.0),
                float(defaults.get("gratuity", 0.0) or 0.0),
                float(defaults.get("netsales", 0.0) or 0.0),
            )

            # Compute display name for current selection
            _sel_for_display = bucket if (bucket is not None) else auto_bucket
            if _sel_for_display == "":
                _display_name = "All Locations"
            else:
                _display_name = bucket_display_map.get(_sel_for_display or "", "")

            # Build fallback buckets tuples for template
            buckets_map = {bid: bname for bid, bname in (buckets or [])}
            fallback_buckets = [(bid, buckets_map.get(bid, bid)) for bid in (fallback_bucket_ids or [])]

            result = {
                "saved": False,
                "errors": [],
                "order_guids": order_guids_used,
                "order_checks": order_checks_by_order,
                "worker_name": worker_name,
                # Preserve explicit empty string (All Locations) to keep dropdown state consistent
                "bucket": bucket if bucket is not None else auto_bucket,
                "filter_bucket_display": _display_name,
                "filter_windows_utc": [*filter_windows_str],
                "filter_windows_local": [*filter_windows_local],
                "suggested_buckets": [(bid, buckets_map.get(bid, bid)) for bid in (suggested_bucket_ids or [])],
                "fallback_buckets": fallback_buckets,
                # Category totals and breakdown for the selected filter
                "category_totals": category_totals if 'category_totals' in locals() else {},
                "category_tip_breakdown": category_tip_breakdown if 'category_tip_breakdown' in locals() else {},
                "category_total_all": _round2(total_sales_all) if 'total_sales_all' in locals() else 0.0,
                "payout_tips": payout_tips_val,
                "owed_to_server": owed_server,
                "owed_to_restaurant": owed_rest,
                "gross_tip_pct": gross_pct,
                # Intermediate values for debugging/verification
                "gratuity_total_sum": round(gratuity_total_sum, 2),
                "noncash_tips_sum": round(noncash_tips_sum, 2),
                "cash_collected_sum": round(cash_collected_sum, 2),
                "compare_rows": [],
            }

            return templates.TemplateResponse(
                "server_tips.html",
                {
                    "request": request,
                    "title": "Server Tips",
                    "workers": workers,
                    "buckets": buckets,
                    "defaults": defaults,
                    "date_str": date,
                    "result": result,
                },
            )
        except Exception:
            # Fallback: at least return page with defaults
            return templates.TemplateResponse(
                "server_tips.html",
                {
                    "request": request,
                    "title": "Server Tips",
                    "workers": workers,
                    "buckets": buckets,
                    "defaults": defaults,
                    "date_str": date,
                    "result": {"saved": False, "errors": ["Failed to build result"]},
                },
            )


# Payouts view
@app.get("/payouts", response_class=HTMLResponse)
def get_payouts(request: Request, bucket: str | None = None, business_date: str | None = None, message: str | None = None, show_all: int = 0):
    db = DatabaseManager()
    try:
        workers = db.load_workers()
        buckets = BUCKET_DISPLAY_NAMES
        # Do not auto-select a bucket; wait for explicit selection
        selected_bucket = bucket or ""
        # Only load assignments/unpaid once both bucket and date are present
        have_filters = bool(selected_bucket) and bool(business_date)
        assignments = db.fetch_assignments_for_bucket(selected_bucket) if selected_bucket else {}
        unpaid = db.get_unpaid_payout_sums(selected_bucket, business_date) if have_filters else {"Bartender": 0.0, "Busser": 0.0, "Expo": 0.0, "Runner": 0.0}
        server_breakdown = db.get_unpaid_pushed_breakdown(selected_bucket, business_date) if have_filters else []
        # Double-entry committed transfers
        committed_log = db.get_committed_transfers(selected_bucket, business_date) if have_filters else []
    finally:
        db.close()

    # Normalize unpaid keys for all destinations
    for dest in ["Bartender", "Busser", "Expo", "Runner"]:
        unpaid.setdefault(dest, 0.0)

    # Build filtered assignment lists based on employees.json job titles
    # Additionally, if a business_date is selected and show_all is false, restrict to workers who clocked in that day
    worked_set: set[str] = set()
    try:
        if business_date and not show_all:
            csv_path_w = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
            if csv_path_w.exists():
                with csv_path_w.open("r", encoding="utf-8") as fcsvw:
                    reader_w = csv.DictReader(fcsvw)
                    for row in reader_w:
                        if (row.get("date") or "").strip() == business_date:
                            nm = (row.get("employee_name") or "").strip()
                            if nm:
                                worked_set.add(nm)
    except Exception:
        worked_set = set()
    busser_workers: List[str] = []
    bartender_workers: List[str] = []
    expo_workers: List[str] = []
    runner_workers: List[str] = []
    try:
        with (RAW_DIR / "employees.json").open("r", encoding="utf-8") as f:
            emps = json.load(f) or []
        try:
            job_map = t.load_job_map()
        except Exception:
            job_map = {}
        busser_names: List[str] = []
        bartender_names: List[str] = []
        expo_names: List[str] = []
        runner_names: List[str] = []
        for e in emps:
            if e.get("deleted") is True:
                continue
            has_busser = False
            has_bar = False
            has_expo = False
            has_runner = False
            for ref in (e.get("jobReferences") or []):
                guid = (ref or {}).get("guid")
                title = job_map.get(guid) if guid else None
                if title:
                    ttl = str(title).lower()
                    if "busser" in ttl:
                        has_busser = True
                    if "bar" in ttl:
                        has_bar = True
                    if "expo" in ttl:
                        has_expo = True
                        # Expo also counts for Runner assignments per request
                        has_runner = True
                    if "runner" in ttl:
                        has_runner = True
            first = (e.get("firstName") or "").strip()
            last = (e.get("lastName") or "").strip()
            full = (first + (" " + last if last else "")).strip()
            if not full:
                continue
            if has_busser:
                busser_names.append(full)
            if has_bar:
                bartender_names.append(full)
            if has_expo:
                expo_names.append(full)
            if has_runner:
                runner_names.append(full)
        # Preserve original workers ordering
        busser_set, bartender_set, expo_set, runner_set = set(busser_names), set(bartender_names), set(expo_names), set(runner_names)
        # Restrict bussers to those who have a Busser shift on the selected date per labor_shifts_detailed_daily.csv
        busser_shift_set: set[str] = set()
        try:
            if business_date:
                path = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
                if path.exists():
                    with path.open("r", encoding="utf-8") as fcsv:
                        rdr = csv.DictReader(fcsv)
                        for r in rdr:
                            if (r.get("date") or "").strip() != (business_date or ""):
                                continue
                            jt = (r.get("job_title") or r.get("jobtitle") or "").strip().lower()
                            if "busser" in jt:
                                nm = (r.get("employee_name") or "").strip()
                                if nm:
                                    busser_shift_set.add(nm)
        except Exception:
            busser_shift_set = set()
        busser_workers = [w for w in workers if (w in busser_set) and (w in busser_shift_set)]
        bartender_workers = [w for w in workers if (w in bartender_set) and ((not worked_set) or (w in worked_set))]
        # Exclude placeholder bar entries unless show_all is selected
        try:
            if not show_all:
                # Exclude placeholder bar entries from the bartender list
                barred = {"am bar", "ww bar", "low bar"}
                bartender_workers = [w for w in bartender_workers if w and w.strip().lower() not in barred]
        except Exception:
            pass
        # If a bucket and business_date are selected, restrict bartenders to those with matching bar job_title in labor_shifts_detailed_daily.csv
        try:
            if business_date and selected_bucket:
                title_map = {
                    "westwing": "WW Bar",
                    "am_bar": "AM Bar Sunset",
                    "sunset": "PM Bar Sunset",
                    # Per request: for East Wing bucket, only show bartenders who worked as 'PM Bar Sunset' on that date
                    "eastwing": "PM Bar Sunset",
                }
                wanted_title = title_map.get(selected_bucket)
                if wanted_title:
                    bar_shift_set: set[str] = set()
                    path = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
                    if path.exists():
                        with path.open("r", encoding="utf-8") as fcsv:
                            rdr = csv.DictReader(fcsv)
                            for r in rdr:
                                if (r.get("date") or "").strip() != (business_date or ""):
                                    continue
                                jt = (r.get("job_title") or r.get("jobtitle") or "").strip()
                                nm = (r.get("employee_name") or "").strip()
                                if not nm:
                                    continue
                                if jt == wanted_title:
                                    bar_shift_set.add(nm)
                    bartender_workers = [w for w in workers if w in bar_shift_set]
        except Exception:
            pass
        # Further restrict bartender list to only bartenders who contributed tipouts
        # via bartender-tips for this bucket/date, unless show_all is selected.
        try:
            if not show_all and business_date and selected_bucket:
                cur = DatabaseManager().conn.cursor()
                cur.execute(
                    "SELECT DISTINCT worker_name FROM payouts WHERE bucket = ? AND business_date = ?",
                    (selected_bucket, business_date),
                )
                contributed = {row[0] for row in (cur.fetchall() or [])}
                if contributed:
                    bartender_workers = [w for w in bartender_workers if w in contributed]
        except Exception:
            pass
        # Restrict Expo/Runner strictly to those who had a corresponding shift entry on the selected date
        expo_shift_set: set[str] = set()
        runner_shift_set: set[str] = set()
        try:
            if business_date:
                path = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
                if path.exists():
                    with path.open("r", encoding="utf-8") as fcsv:
                        rdr = csv.DictReader(fcsv)
                        for r in rdr:
                            if (r.get("date") or "").strip() != (business_date or ""):
                                continue
                            jt = (r.get("job_title") or r.get("jobtitle") or "").strip().lower()
                            nm = (r.get("employee_name") or "").strip()
                            if not nm:
                                continue
                            if "expo" in jt:
                                expo_shift_set.add(nm)
                            if "runner" in jt:
                                runner_shift_set.add(nm)
        except Exception:
            expo_shift_set, runner_shift_set = set(), set()
        # Union of Expo and Runner shifts should be included in both assignments
        expo_runner_union = set(expo_shift_set) | set(runner_shift_set)
        expo_workers = [w for w in workers if w in expo_runner_union]
        runner_workers = [w for w in workers if w in expo_runner_union]
    except Exception:
        busser_workers = []
        bartender_workers = []
        expo_workers = []
        runner_workers = []

    # As a final safeguard, never show placeholder bar entries in Bartender assignments
    try:
        barred_final = {"am bar", "ww bar", "low bar"}
        bartender_workers = [w for w in (bartender_workers or []) if w and w.strip().lower() not in barred_final]
    except Exception:
        pass

    # Auto-select visible bartenders by default if no bartender assignments exist
    try:
        derived_assignments = dict(assignments or {})
        if not derived_assignments.get("Bartender"):
            derived_assignments["Bartender"] = list(bartender_workers or [])
    except Exception:
        derived_assignments = assignments

    return templates.TemplateResponse(
        "payouts.html",
        {
            "request": request,
            "title": "Payouts",
            "workers": workers,
            "busser_workers": busser_workers,
            "bartender_workers": bartender_workers,
            "expo_workers": expo_workers,
            "runner_workers": runner_workers,
            "buckets": buckets,
            "selected_bucket": selected_bucket,
            "selected_date": business_date or "",
            "selected_show_all": bool(show_all),
            "assignments": derived_assignments,
            "unpaid": unpaid,
            # Default the amount-to-distribute inputs to unpaid only when filters applied; else zeros
            "tip_amounts": unpaid if (selected_bucket and business_date) else {"Bartender": 0.0, "Busser": 0.0, "Expo": 0.0, "Runner": 0.0},
            "result": None,
            "server_breakdown": server_breakdown,
            "committed_log": (
                [
                    {
                        **row,
                        "amount_received": (row.get("amount", 0.0) if (
                            (row.get("destination") == "Bartender" and row.get("worker_name") in (bartender_workers or [])) or
                            (row.get("destination") == "Busser" and row.get("worker_name") in (busser_workers or [])) or
                            (row.get("destination") == "Expo" and row.get("worker_name") in (expo_workers or [])) or
                            (row.get("destination") == "Runner" and row.get("worker_name") in (runner_workers or []))
                        ) else 0.0),
                        "amount_given": (row.get("amount", 0.0) if not (
                            (row.get("destination") == "Bartender" and row.get("worker_name") in (bartender_workers or [])) or
                            (row.get("destination") == "Busser" and row.get("worker_name") in (busser_workers or [])) or
                            (row.get("destination") == "Expo" and row.get("worker_name") in (expo_workers or [])) or
                            (row.get("destination") == "Runner" and row.get("worker_name") in (runner_workers or []))
                        ) else 0.0),
                    }
                    for row in (committed_log or [])
                ] if committed_log else []
            ),
            "message": message,
            "selected_show_all": bool(show_all),
        },
    )


@app.post("/payouts", response_class=HTMLResponse)
def post_payouts(
    request: Request,
    action: str = Form(...),
    bucket: str = Form(...),
    business_date: str = Form("") ,
    show_all: int = Form(0),
    bartender_amount: float = Form(0.0),
    busser_amount: float = Form(0.0),
    expo_amount: float = Form(0.0),
    runner_amount: float = Form(0.0),
    assign_Bartender: List[str] = Form([]),
    assign_Busser: List[str] = Form([]),
    assign_Expo: List[str] = Form([]),
    assign_Runner: List[str] = Form([]),
    payout_id: int = Form(0),
    payout_ids: List[int] = Form([]),
):
    db = DatabaseManager()
    try:
        workers = db.load_workers()
        buckets = BUCKET_DISPLAY_NAMES
        # Build assignment map from form
        form_assignments = {
            "Bartender": assign_Bartender or [],
            "Busser": assign_Busser or [],
            "Expo": assign_Expo or [],
            "Runner": assign_Runner or [],
        }

        # Always fetch current assignments for display baseline
        current_assignments = db.fetch_assignments_for_bucket(bucket) or {}

        # Tip amounts map for calculation
        tip_amounts = {
            "Bartender": float(bartender_amount or 0.0),
            "Busser": float(busser_amount or 0.0),
            "Expo": float(expo_amount or 0.0),
            "Runner": float(runner_amount or 0.0),
        }

        message = None
        result = None

        if action == "save_assignments":
            for dest, workers_list in form_assignments.items():
                db.set_worker_assignments(bucket, dest, workers_list)
            message = "Assignments saved."
            # Refresh assignments
            current_assignments = db.fetch_assignments_for_bucket(bucket) or {}

        # Prefer form assignments (what user just selected) for preview/commit
        active_assignments = form_assignments if any(form_assignments.values()) else current_assignments

        # Build list of conflicts: selected workers with no labor shift on business_date
        assignment_conflicts: list[dict] = []
        try:
            worked_set: set[str] = set()
            if business_date:
                csv_path = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
                if csv_path.exists():
                    with csv_path.open("r", encoding="utf-8") as fcsv:
                        reader = csv.DictReader(fcsv)
                        for row in reader:
                            if (row.get("date") or "").strip() == business_date:
                                name = (row.get("employee_name") or "").strip()
                                if name:
                                    worked_set.add(name)
            # Collate selected workers by destination
            selected_by_dest = {d: list(v or []) for d, v in (form_assignments or {}).items()}
            # If no form selections, show conflicts for existing assignments preview/commit baseline
            if not any(selected_by_dest.values()):
                selected_by_dest = {d: list(v or []) for d, v in (current_assignments or {}).items()}
            missing_map: dict[str, list[str]] = {}
            for dest, names in (selected_by_dest or {}).items():
                for n in (names or []):
                    if n and (worked_set and n not in worked_set):
                        missing_map.setdefault(n, []).append(dest)
            # Convert to list for template
            assignment_conflicts = [
                {"worker": w, "destinations": sorted(ds)} for w, ds in sorted(missing_map.items())
            ]
        except Exception:
            assignment_conflicts = []

        if action in ("preview", "commit"):
            worker_assignments_all = {bucket: active_assignments}
            # Build hours_by_worker for selected date to weight distributions by hours
            hours_by_worker: dict[str, float] = {}
            try:
                if business_date:
                    selected_workers: set[str] = set()
                    for _dest, _names in (active_assignments or {}).items():
                        for _n in (_names or []):
                            if _n:
                                selected_workers.add(_n)
                    csv_path = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
                    if csv_path.exists() and selected_workers:
                        with csv_path.open("r", encoding="utf-8") as fcsv:
                            reader = csv.DictReader(fcsv)
                            for row in reader:
                                if (row.get("date") or "").strip() != business_date:
                                    continue
                                name = (row.get("employee_name") or "").strip()
                                if not name or name not in selected_workers:
                                    continue
                                try:
                                    hrs = float(row.get("hours") or 0.0)
                                except Exception:
                                    hrs = 0.0
                                hours_by_worker[name] = hours_by_worker.get(name, 0.0) + hrs
            except Exception:
                hours_by_worker = {}

            distributions = TipCalculator.calculate_payout_distribution(
                bucket,
                worker_assignments_all,
                tip_amounts,
                hours_by_worker=hours_by_worker,
            )
            # Compute destination-level total hours and hourly rates for preview context
            destination_hours: dict[str, float] = {}
            hourly_rate: dict[str, float] = {}
            try:
                for dest, names in (active_assignments or {}).items():
                    th = 0.0
                    for n in (names or []):
                        th += float(hours_by_worker.get(n, 0.0) or 0.0)
                    destination_hours[dest] = th
                    amt = float(tip_amounts.get(dest, 0.0) or 0.0)
                    hourly_rate[dest] = (amt / th) if th > 0 else 0.0
            except Exception:
                destination_hours, hourly_rate = {}, {}

            result = {
                "distributions": distributions,
                "tip_amounts": tip_amounts,
                "hours_by_worker": hours_by_worker,
                "destination_hours": destination_hours,
                "hourly_rate": hourly_rate,
            }
            if action == "commit":
                payout_session_id = f"{bucket}-{dt_date.today().isoformat()}-{uuid.uuid4().hex[:8]}"
                # Create session and allocate balanced transfers from unpaid pools
                db.create_payout_session(payout_session_id, bucket, business_date or "")
                session_total = db.allocate_and_commit_transfers(bucket, business_date or "", distributions, payout_session_id)
                message = f"Payouts committed. Session {payout_session_id}. Total ${session_total:.2f}."

        if action == "delete_committed":
            try:
                res = db.delete_committed_transfer(int(payout_id)) if payout_id else {"transfers_deleted": 0, "legs_deleted": 0, "ledger_deleted": 0}
                td = res.get("transfers_deleted", 0)
                lgd = res.get("legs_deleted", 0)
                ld = res.get("ledger_deleted", 0)
                message = f"Deleted {td} transfer, {lgd} legs, and {ld} cashbox ledger row(s)."
            except Exception as ex:
                message = f"Failed to delete committed payout: {ex}"

        if action == "delete_committed_bulk":
            total_td = 0
            total_lgd = 0
            total_ld = 0
            pids = request.form().get("payout_ids") if False else payout_ids  # keep mypy happy
            for pid in (payout_ids or []):
                try:
                    res = db.delete_committed_transfer(int(pid))
                    total_td += int(res.get("transfers_deleted", 0) or 0)
                    total_lgd += int(res.get("legs_deleted", 0) or 0)
                    total_ld += int(res.get("ledger_deleted", 0) or 0)
                except Exception:
                    pass
            message = f"Bulk deleted {total_td} transfers, {total_lgd} legs, and {total_ld} cashbox ledger row(s)."

        unpaid = db.get_unpaid_payout_sums(bucket, business_date or None)
        server_breakdown = db.get_unpaid_pushed_breakdown(bucket, business_date) if business_date else []
        committed_log = db.get_committed_transfers(bucket, business_date) if business_date else []
    finally:
        db.close()

    # Normalize unpaid keys for all destinations
    for dest in ["Bartender", "Busser", "Expo", "Runner"]:
        unpaid.setdefault(dest, 0.0)

    # Build filtered assignment lists based on employees.json job titles
    # Additionally, if a business_date is selected, restrict to workers who clocked in that day
    worked_set: set[str] = set()
    try:
        if business_date:
            csv_path_w = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
            if csv_path_w.exists():
                with csv_path_w.open("r", encoding="utf-8") as fcsvw:
                    reader_w = csv.DictReader(fcsvw)
                    for row in reader_w:
                        if (row.get("date") or "").strip() == business_date:
                            nm = (row.get("employee_name") or "").strip()
                            if nm:
                                worked_set.add(nm)
    except Exception:
        worked_set = set()
    busser_workers: List[str] = []
    bartender_workers: List[str] = []
    expo_workers: List[str] = []
    runner_workers: List[str] = []
    try:
        with (RAW_DIR / "employees.json").open("r", encoding="utf-8") as f:
            emps = json.load(f) or []
        try:
            job_map = t.load_job_map()
        except Exception:
            job_map = {}
        busser_names: List[str] = []
        bartender_names: List[str] = []
        expo_names: List[str] = []
        runner_names: List[str] = []
        for e in emps:
            if e.get("deleted") is True:
                continue
            has_busser = False
            has_bar = False
            has_expo = False
            has_runner = False
            for ref in (e.get("jobReferences") or []):
                guid = (ref or {}).get("guid")
                title = job_map.get(guid) if guid else None
                if title:
                    ttl = str(title).lower()
                    if "busser" in ttl:
                        has_busser = True
                    if "bar" in ttl:
                        has_bar = True
                    if "expo" in ttl:
                        has_expo = True
                        # Expo also counts for Runner assignments per request
                        has_runner = True
                    if "runner" in ttl:
                        has_runner = True
            first = (e.get("firstName") or "").strip()
            last = (e.get("lastName") or "").strip()
            full = (first + (" " + last if last else "")).strip()
            if not full:
                continue
            if has_busser:
                busser_names.append(full)
            if has_bar:
                bartender_names.append(full)
            if has_expo:
                expo_names.append(full)
            if has_runner:
                runner_names.append(full)
        busser_set, bartender_set, expo_set, runner_set = set(busser_names), set(bartender_names), set(expo_names), set(runner_names)
        # Restrict bussers to those who have a Busser shift on the selected date per labor_shifts_detailed_daily.csv
        busser_shift_set: set[str] = set()
        try:
            if business_date:
                path = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
                if path.exists():
                    with path.open("r", encoding="utf-8") as fcsv:
                        rdr = csv.DictReader(fcsv)
                        for r in rdr:
                            if (r.get("date") or "").strip() != (business_date or ""):
                                continue
                            jt = (r.get("job_title") or r.get("jobtitle") or "").strip().lower()
                            if "busser" in jt:
                                nm = (r.get("employee_name") or "").strip()
                                if nm:
                                    busser_shift_set.add(nm)
        except Exception:
            busser_shift_set = set()
        busser_workers = [w for w in workers if (w in busser_set) and (w in busser_shift_set)]
        bartender_workers = [w for w in workers if (w in bartender_set) and ((not worked_set) or (w in worked_set))]
        # Exclude placeholder bar entries unless show_all is selected
        try:
            if not show_all:
                barred = {"am bar", "ww bar"}
                bartender_workers = [w for w in bartender_workers if w and w.strip().lower() not in barred]
        except Exception:
            pass
        # Restrict Expo/Runner strictly to those who had a corresponding shift entry on the selected date
        expo_shift_set: set[str] = set()
        runner_shift_set: set[str] = set()
        try:
            if business_date:
                path = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
                if path.exists():
                    with path.open("r", encoding="utf-8") as fcsv:
                        rdr = csv.DictReader(fcsv)
                        for r in rdr:
                            if (r.get("date") or "").strip() != (business_date or ""):
                                continue
                            jt = (r.get("job_title") or r.get("jobtitle") or "").strip().lower()
                            nm = (r.get("employee_name") or "").strip()
                            if not nm:
                                continue
                            if "expo" in jt:
                                expo_shift_set.add(nm)
                            if "runner" in jt:
                                runner_shift_set.add(nm)
        except Exception:
            expo_shift_set, runner_shift_set = set(), set()
        expo_workers = [w for w in workers if w in expo_shift_set]
        runner_workers = [w for w in workers if w in runner_shift_set]
    except Exception:
        busser_workers = []
        bartender_workers = []
        expo_workers = []
        runner_workers = []

    # Auto-select visible bartenders by default if no bartender assignments present in active selections
    try:
        if not (active_assignments or {}).get("Bartender"):
            active_assignments = dict(active_assignments or {})
            active_assignments["Bartender"] = list(bartender_workers or [])
    except Exception:
        pass

    return templates.TemplateResponse(
        "payouts.html",
        {
            "request": request,
            "title": "Payouts",
            "workers": workers,
            "busser_workers": busser_workers,
            "bartender_workers": bartender_workers,
            "expo_workers": expo_workers,
            "runner_workers": runner_workers,
            "buckets": buckets,
            "selected_bucket": bucket,
            "selected_date": business_date or "",
            # Preserve the user's current selections in the UI (with bartender auto-select default)
            "assignments": active_assignments,
            "assignment_conflicts": assignment_conflicts,
            "unpaid": unpaid,
            "tip_amounts": tip_amounts,
            "result": result,
            "server_breakdown": server_breakdown,
            "message": message,
        },
    )


# Cashbox ledger view
@app.get("/cashbox", response_class=HTMLResponse)
def view_cashbox(
    request: Request,
    drawer: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 200,
):
    """Display cashbox balances by drawer and recent ledger entries.

    Query params:
      - drawer: optional filter by cash drawer; when omitted shows all
      - limit: max number of ledger rows to display
    """
    # Normalize date range (default: last 30 days)
    try:
        e_dt = dt_date.fromisoformat(end_date) if end_date else dt_date.today()
    except Exception:
        e_dt = dt_date.today()
    try:
        s_dt = dt_date.fromisoformat(start_date) if start_date else (e_dt - timedelta(days=30))
    except Exception:
        s_dt = e_dt - timedelta(days=30)
    s_str, e_str = s_dt.isoformat(), e_dt.isoformat()

    db = DatabaseManager()
    try:
        cursor = db.conn.cursor()

        # Balances by drawer within date range
        cursor.execute(
            """
            SELECT COALESCE(cash_drawer, 'Unspecified') AS drawer, ROUND(SUM(amount), 2) AS total
            FROM cashbox_ledger
            WHERE date(timestamp) BETWEEN ? AND ?
            GROUP BY COALESCE(cash_drawer, 'Unspecified')
            ORDER BY drawer
            """,
            [s_str, e_str],
        )
        balances_rows = cursor.fetchall() or []
        balances = {row[0]: float(row[1] or 0.0) for row in balances_rows}

        # Ledger entries
        params = [s_str, e_str]
        conditions = ["date(timestamp) BETWEEN ? AND ?"]
        if drawer:
            conditions.append("cash_drawer = ?")
            params.append(drawer)
        base_sql = (
            "SELECT c.timestamp, COALESCE(c.cash_drawer, 'Unspecified') AS drawer, "
            "COALESCE(c.worker_name, '') AS worker, COALESCE(c.reason, '') AS reason, "
            "c.amount, c.submit_id, c.payout_session_id, "
            "COALESCE(s.bucket, p.bucket) AS bucket, COALESCE(s.business_date, p.business_date) AS business_date "
            "FROM cashbox_ledger c "
            "LEFT JOIN payout_sessions s ON s.id = c.payout_session_id "
            "LEFT JOIN payouts p ON p.payout_session_id = c.payout_session_id "
            " AND p.worker_name = c.worker_name "
            " AND p.payout_destination = REPLACE(c.reason, 'Payout - ', '') "
            f"WHERE {' AND '.join(['date(c.timestamp) BETWEEN ? AND ?'] + (['c.cash_drawer = ?'] if drawer else []))} "
            "ORDER BY datetime(c.timestamp) DESC LIMIT ?"
        )
        params.append(int(limit))

        cursor.execute(base_sql, params)
        entry_rows = cursor.fetchall() or []
        entries = [
            {
                "timestamp": r[0],
                "drawer": r[1],
                "worker": r[2],
                "reason": r[3],
                "amount": float(r[4] or 0.0),
                "submit_id": r[5],
                "payout_session_id": r[6],
                "bucket": r[7],
                "business_date": r[8],
            }
            for r in entry_rows
        ]
    finally:
        db.close()

    # Drawer options (prepend All)
    drawer_options = ["All"] + CASH_DRAWERS
    selected_drawer = drawer if drawer else "All"
    total_all = sum(balances.values()) if balances else 0.0
    selected_total = (
        (balances.get(selected_drawer, 0.0) if selected_drawer != "All" else total_all)
    )

    return templates.TemplateResponse(
        "cashbox.html",
        {
            "request": request,
            "title": "Cashbox",
            "drawer_options": drawer_options,
            "selected_drawer": selected_drawer,
            "start_date": s_str,
            "end_date": e_str,
            "balances": balances,
            "total_all": total_all,
            "selected_total": selected_total,
            "entries": entries,
            "limit": limit,
        },
    )


# Consolidated worker report (SQL-based)
@app.get("/report", response_class=HTMLResponse)
def consolidated_report(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 1000,
):
    """Run the consolidated worker report SQL and display as a table."""
    sql_path = ROOT / "jbhooks" / "tip_report.sql"
    headers: List[str] = []
    rows: List[dict] = []

    if not sql_path.exists():
        return templates.TemplateResponse(
            "worker_report.html",
            {
                "request": request,
                "title": "Worker Report",
                "headers": headers,
                "rows": rows,
                "message": "tip_report.sql not found",
            },
        )

    # Normalize date range (default: last 30 days)
    try:
        e_dt = dt_date.fromisoformat(end_date) if end_date else dt_date.today()
    except Exception:
        e_dt = dt_date.today()
    try:
        s_dt = dt_date.fromisoformat(start_date) if start_date else (e_dt - timedelta(days=30))
    except Exception:
        s_dt = e_dt - timedelta(days=30)
    s_str, e_str = s_dt.isoformat(), e_dt.isoformat()

    sql = sql_path.read_text(encoding="utf-8")
    db = DatabaseManager()
    try:
        cur = db.conn.cursor()
        base_sql = sql.strip().rstrip(";\n ")
        wrapped = (
            "WITH base AS (" + base_sql + ") "
            "SELECT * FROM base WHERE \"Date\" BETWEEN ? AND ? "
            "ORDER BY \"Date\" DESC LIMIT ?"
        )
        cur.execute(wrapped, [s_str, e_str, int(limit)])
        result_rows = cur.fetchall() or []
        # Extract column names from cursor description
        headers = [d[0] for d in (cur.description or [])]
        for r in result_rows[: int(limit)]:
            row = {}
            for i, h in enumerate(headers):
                row[h] = r[i] if i < len(r) else None
            rows.append(row)
    finally:
        db.close()

    # Enrich rows with per-shift metrics from CSVs based on (Date, Worker, Job Title)
    try:
        import csv as _csv
        # Build lookups from CSVs, consolidating 'Cleaning - Server' into a primary server shift on the same day
        ns_path = REPORTS_DIR / "net_sales_by_employee_shift_daily.csv"
        gr_path = REPORTS_DIR / "gratuity_per_shift.csv"
        key = lambda d, w, jt: (str(d or "").strip(), str(w or "").strip(), str(jt or "").strip())
        # Helper to consolidate cleaning rows into a primary server job title per (date, worker)
        def consolidate_server_rows(rows_iter):
            from collections import defaultdict
            grouped: Dict[tuple[str, str], Dict[str, Dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: {"cash_tips":0.0,"credit_card_tips":0.0,"net_sales":0.0,"gratuity":0.0}))
            for rr in rows_iter:
                d = (rr.get("date") or "").strip()
                w = (rr.get("employee_name") or "").strip()
                jt = (rr.get("job_title") or rr.get("jobtitle") or "").strip()
                if not d or not w or not jt:
                    continue
                try:
                    grouped[(d,w)][jt]["cash_tips"] += float(rr.get("cash_tips") or 0.0)
                except Exception:
                    pass
                try:
                    grouped[(d,w)][jt]["credit_card_tips"] += float(rr.get("credit_card_tips") or 0.0)
                except Exception:
                    pass
                try:
                    grouped[(d,w)][jt]["net_sales"] += float(rr.get("net_sales") or 0.0)
                except Exception:
                    pass
                try:
                    grouped[(d,w)][jt]["gratuity"] += float(rr.get("gratuity_total") or 0.0)
                except Exception:
                    # some sources won't have gratuity_total
                    pass
            # Now consolidate cleaning into a primary server title for the same (date, worker)
            out: Dict[tuple, Dict[str, float]] = {}
            for (d,w), by_jt in grouped.items():
                # Determine primary server title preference order
                titles = list(by_jt.keys())
                non_clean = [t for t in titles if t.strip().lower() != "cleaning - server"]
                # Pick a preferred target among known server titles if present
                pref_order = [
                    "PM Sunset Server","AM Sunset Server","WW Server","Server"
                ]
                target = None
                for pref in pref_order:
                    for tname in non_clean:
                        if pref.lower() in tname.lower():
                            target = tname
                            break
                    if target:
                        break
                if not target:
                    # Fallback: first non-cleaning title if any
                    target = non_clean[0] if non_clean else None
                # Sum cleaning into target if target exists
                cleaning_key = None
                for tname in titles:
                    if tname.strip().lower() == "cleaning - server":
                        cleaning_key = tname
                        break
                if cleaning_key and target:
                    for kf in ("cash_tips","credit_card_tips","net_sales","gratuity"):
                        by_jt[target][kf] = float(by_jt[target].get(kf,0.0)) + float(by_jt[cleaning_key].get(kf,0.0))
                    # drop cleaning entry
                    by_jt.pop(cleaning_key, None)
                # Emit consolidated rows
                for jt, vals in by_jt.items():
                    out[(d,w,jt)] = {
                        "cash_tips": float(vals.get("cash_tips",0.0)),
                        "credit_card_tips": float(vals.get("credit_card_tips",0.0)),
                        "net_sales": float(vals.get("net_sales",0.0)),
                        "gratuity": float(vals.get("gratuity",0.0)),
                    }
            return out

        ns_map: Dict[tuple, Dict[str, float]] = {}
        if ns_path.exists():
            with ns_path.open("r", encoding="utf-8") as f:
                rdr = _csv.DictReader(f)
                ns_map = consolidate_server_rows(rdr)
        gr_map: Dict[tuple, float] = {}
        if gr_path.exists():
            with gr_path.open("r", encoding="utf-8") as f:
                rdr = _csv.DictReader(f)
                gr_con = consolidate_server_rows(rdr)
                # extract only gratuity
                gr_map = { (d,w,jt): float(v.get("gratuity",0.0)) for (d,w,jt), v in gr_con.items() }
        # Update rows in-place
        for row in rows:
            k = key(row.get("Date"), row.get("Worker"), row.get("Job Title"))
            ns = ns_map.get(k)
            if ns:
                # Fill from CSV if missing or zero in DB-derived SQL results
                if row.get("Cash Tips") in (None, 0, 0.0):
                    row["Cash Tips"] = round(float(ns.get("cash_tips", 0.0)), 2)
                if row.get("Non-Cash Tips") in (None, 0, 0.0):
                    row["Non-Cash Tips"] = round(float(ns.get("credit_card_tips", 0.0)), 2)
                if row.get("Net Sales") in (None, 0, 0.0):
                    row["Net Sales"] = round(float(ns.get("net_sales", 0.0)), 2)
            gr = gr_map.get(k)
            if gr is not None and row.get("Gratuity") in (None, 0, 0.0):
                row["Gratuity"] = round(float(gr or 0.0), 2)
            # Recompute Tip % of Sales when data is available
            try:
                cash = float(row.get("Cash Tips") or 0.0)
                noncash = float(row.get("Non-Cash Tips") or 0.0)
                grat = float(row.get("Gratuity") or 0.0)
                net = float(row.get("Net Sales") or 0.0)
                if net > 0:
                    row["Tip % of Sales"] = round(((cash + noncash + grat) / net) * 100.0, 2)
                else:
                    # keep existing value or set 0
                    row["Tip % of Sales"] = float(row.get("Tip % of Sales") or 0.0)
            except Exception:
                pass
    except Exception:
        # Non-fatal: leave rows as-is if enrichment fails
        pass

    return templates.TemplateResponse(
        "worker_report.html",
        {
            "request": request,
            "title": "Worker Report",
            "headers": headers,
            "rows": rows,
            "start_date": s_str,
            "end_date": e_str,
            "message": None,
        },
    )


@app.get("/report-payouts", response_class=HTMLResponse)
def report_payouts_detailed(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    worker: str | None = None,
    bucket: str | None = None,
    limit: int = 5000,
):
    """Detailed payouts report showing who gave and who received for each transfer, with session context.

    Columns:
      - Date (session business_date)
      - Bucket
      - Transfer ID
      - Destination
      - Amount
      - Submitter Name, Submitter Job Title
      - Receiver Name, Receiver Job Title
    """
    # Normalize date range
    try:
        e_dt = dt_date.fromisoformat(end_date) if end_date else dt_date.today()
    except Exception:
        e_dt = dt_date.today()
    try:
        s_dt = dt_date.fromisoformat(start_date) if start_date else (e_dt - timedelta(days=30))
    except Exception:
        s_dt = e_dt - timedelta(days=30)
    s_str, e_str = s_dt.isoformat(), e_dt.isoformat()

    rows: List[dict] = []
    try:
        db = DatabaseManager()
        try:
            cur = db.conn.cursor()
            sql = (
                "SELECT s.business_date, s.bucket, t.id AS transfer_id, t.destination, t.amount, "
                "ls.party_name AS submitter_name, ls.job_title AS submitter_job_title, "
                "lr.party_name AS receiver_name, lr.job_title AS receiver_job_title "
                "FROM payout_transfers t "
                "JOIN payout_sessions s ON s.id = t.session_id "
                "LEFT JOIN payout_legs ls ON ls.transfer_id = t.id AND ls.leg_kind = 'received' AND ls.party_role = 'Submitter' "
                "LEFT JOIN payout_legs lr ON lr.transfer_id = t.id AND lr.leg_kind = 'given' AND lr.party_role = 'Worker' "
                "WHERE s.business_date BETWEEN ? AND ? "
            )
            args: List[Any] = [s_str, e_str]
            if bucket and bucket.strip():
                sql += " AND s.bucket = ?"
                args.append(bucket.strip())
            if worker and worker.strip():
                # Match either submitter or receiver name
                sql += " AND (ls.party_name = ? OR lr.party_name = ?)"
                args.extend([worker.strip(), worker.strip()])
            sql += " ORDER BY s.business_date DESC, t.id DESC LIMIT ?"
            args.append(int(limit))
            cur.execute(sql, args)
            for (biz_date, buck, tid, dest, amt, sname, sjt, rname, rjt) in (cur.fetchall() or []):
                rows.append({
                    "Date": biz_date,
                    "Bucket": buck,
                    "Transfer ID": tid,
                    "Destination": dest,
                    "Amount": float(amt or 0.0),
                    "Submitter": sname,
                    "Submitter Job Title": sjt,
                    "Receiver": rname,
                    "Receiver Job Title": rjt,
                })
        finally:
            db.close()
    except Exception:
        rows = []

    return templates.TemplateResponse(
        "report_payouts_detailed.html",
        {
            "request": request,
            "title": "Payouts Detail Report",
            "rows": rows,
            "start_date": s_str,
            "end_date": e_str,
            "worker": worker or "",
            "bucket": bucket or "",
            "limit": limit,
        },
    )


@app.get("/reports/payouts_detailed.csv", response_class=PlainTextResponse)
def payouts_detailed_csv(
    start_date: str | None = None,
    end_date: str | None = None,
    worker: str | None = None,
    bucket: str | None = None,
    limit: int = 50000,
) -> PlainTextResponse:
    """CSV export for the detailed payouts report (/report-payouts)."""
    # Normalize date range
    try:
        e_dt = dt_date.fromisoformat(end_date) if end_date else dt_date.today()
    except Exception:
        e_dt = dt_date.today()
    try:
        s_dt = dt_date.fromisoformat(start_date) if start_date else (e_dt - timedelta(days=30))
    except Exception:
        s_dt = e_dt - timedelta(days=30)
    s_str, e_str = s_dt.isoformat(), e_dt.isoformat()

    headers = [
        "date","bucket","transfer_id","destination","amount",
        "submitter","submitter_job_title","receiver","receiver_job_title",
    ]
    out_rows: list[list[str]] = []
    try:
        db = DatabaseManager()
        try:
            cur = db.conn.cursor()
            sql = (
                "SELECT s.business_date, s.bucket, t.id AS transfer_id, t.destination, t.amount, "
                "ls.party_name AS submitter_name, ls.job_title AS submitter_job_title, "
                "lr.party_name AS receiver_name, lr.job_title AS receiver_job_title "
                "FROM payout_transfers t "
                "JOIN payout_sessions s ON s.id = t.session_id "
                "LEFT JOIN payout_legs ls ON ls.transfer_id = t.id AND ls.leg_kind = 'received' AND ls.party_role = 'Submitter' "
                "LEFT JOIN payout_legs lr ON lr.transfer_id = t.id AND lr.leg_kind = 'given' AND lr.party_role = 'Worker' "
                "WHERE s.business_date BETWEEN ? AND ? "
            )
            args: List[Any] = [s_str, e_str]
            if bucket and bucket.strip():
                sql += " AND s.bucket = ?"
                args.append(bucket.strip())
            if worker and worker.strip():
                sql += " AND (ls.party_name = ? OR lr.party_name = ?)"
                args.extend([worker.strip(), worker.strip()])
            sql += " ORDER BY s.business_date DESC, t.id DESC LIMIT ?"
            args.append(int(limit))
            cur.execute(sql, args)
            for (biz_date, buck, tid, dest, amt, sname, sjt, rname, rjt) in (cur.fetchall() or []):
                out_rows.append([
                    str(biz_date or ""), str(buck or ""), str(tid or ""), str(dest or ""),
                    f"{float(amt or 0.0):.2f}",
                    str(sname or ""), str(sjt or ""), str(rname or ""), str(rjt or ""),
                ])
        finally:
            db.close()
    except Exception:
        out_rows = []

    import io, csv
    sio = io.StringIO()
    cw = csv.writer(sio)
    cw.writerow(headers)
    cw.writerows(out_rows)
    return PlainTextResponse(content=sio.getvalue(), media_type="text/csv")


@app.get("/reports/credit_tips_per_shift.csv", response_class=PlainTextResponse)
def credit_tips_per_shift_csv() -> PlainTextResponse:
    """Generate a CSV like data/reports/cash_tips_per_shift.csv but for credit card tips per shift.

    Columns: date,employee_guid,employee_name,job_title,start_time_utc,end_time_utc,credit_card_tips
    Logic: For each time entry shift, sum non-CASH payment tipAmount for checks attributed to that employee
           whose representative timestamp falls within the shift window.
    """
    import io
    import json as _json

    # Build employee guid -> display name map
    emp_map: Dict[str, str] = {}
    try:
        with (RAW_DIR / "employees.json").open("r", encoding="utf-8") as f:
            employees = _json.load(f) or []
        emp_map = t.build_employee_map(employees) if employees else {}
    except Exception:
        emp_map = {}

    # Helper to format businessDate (YYYYMMDD) -> YYYY-MM-DD
    def biz_to_iso(d: str | None) -> str:
        s = (d or "").strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
        try:
            # already ISO
            dt_date.fromisoformat(s)
            return s
        except Exception:
            return s

    # Cache orders per date
    orders_by_date: Dict[str, list] = {}

    def load_orders(biz_iso: str) -> list:
        if biz_iso in orders_by_date:
            return orders_by_date[biz_iso]
        p = RAW_DIR / "orders" / f"{biz_iso}.json"
        try:
            if p.exists():
                orders_by_date[biz_iso] = _json.load(p.open("r", encoding="utf-8")) or []
            else:
                orders_by_date[biz_iso] = []
        except Exception:
            orders_by_date[biz_iso] = []
        return orders_by_date[biz_iso]

    # Compute tips within a window for a given employee guid
    def credit_tips_for_window(orders: list, emp_guid: str, st: Optional[datetime], en: Optional[datetime]) -> float:
        if not emp_guid or not st:
            return 0.0
        try:
            st = st.astimezone(timezone.utc)
        except Exception:
            pass
        if en:
            try:
                en = en.astimezone(timezone.utc)
            except Exception:
                pass
        total = 0.0
        for o in (orders or []):
            for c in (o.get("checks") or []):
                if c.get("voided") or c.get("deleted"):
                    continue
                ts = _parse_iso(
                    c.get("paidDate") or c.get("closedDate") or c.get("openedDate")
                    or o.get("paidDate") or o.get("closedDate") or o.get("openedDate")
                )
                if ts:
                    try:
                        ts = ts.astimezone(timezone.utc)
                    except Exception:
                        pass
                # must be within [st, en] if en is present; or ts >= st if en missing
                in_window = False
                if ts and (en is not None):
                    in_window = (st <= ts <= en)
                elif ts and (en is None):
                    in_window = (st <= ts)
                else:
                    in_window = False
                if not in_window:
                    continue
                for p in (c.get("payments") or []):
                    try:
                        srv = (p.get("server") or {}).get("guid")
                        if srv != emp_guid:
                            continue
                        ptype = (p.get("type") or "").upper()
                        if ptype == "CASH":
                            continue
                        tip_amt = float(p.get("tipAmount") or 0.0)
                        total += tip_amt
                    except Exception:
                        continue
        return round(total, 2)

    # Walk all time_entries day files and produce per-shift rows
    rows: list[str] = ["date,employee_guid,employee_name,job_title,start_time_utc,end_time_utc,credit_card_tips"]
    te_dir = RAW_DIR / "time_entries"
    try:
        files = sorted([p for p in te_dir.glob("*.json") if p.is_file()])
    except Exception:
        files = []
    for f in files:
        try:
            day_iso = f.stem  # YYYY-MM-DD
            te_list = _json.load(f.open("r", encoding="utf-8")) or []
        except Exception:
            continue
        # Preload orders for the day
        orders = load_orders(day_iso)
        for te in (te_list or []):
            try:
                b = te.get("businessDate") or ""
                biz_iso = biz_to_iso(b)
                eg = ((te.get("employeeReference") or {}).get("guid")) or ""
                if not eg:
                    continue
                name = emp_map.get(eg, "")
                jt = te.get("jobTitle") or ((te.get("job") or {}).get("name")) or ""
                st = _parse_iso(te.get("inDate") or te.get("startDate"))
                en = _parse_iso(te.get("outDate") or te.get("endDate"))
                st_s = st.isoformat() if st else ""
                en_s = en.isoformat() if en else ""
                cc = credit_tips_for_window(orders, eg, st, en)
                rows.append(
                    ",".join([
                        biz_iso,
                        eg,
                        '"' + name.replace('"', '""') + '"',
                        '"' + str(jt).replace('"', '""') + '"',
                        st_s,
                        en_s,
                        f"{cc:.2f}",
                    ])
                )
            except Exception:
                continue

    csv_text = "\n".join(rows) + "\n"
    return PlainTextResponse(content=csv_text, media_type="text/csv")


@app.get("/api/bartender-defaults")
async def api_bartender_defaults(date: str, bucket: str):
    """Return suggested defaults and category breakdown for bartender-tips by date and bar bucket.

    Computes:
      - cash_tips (from time_entries gratuity cash tips? For bar, we set 0.0 as not used here)
      - credit_card_tips (not used here; 0.0)
      - net_sales (sum of selections within bar shift windows)
      - category_totals {bucket_name: sales}
      - category_tip_breakdown {servertips, expotips, runnertips} per category and totals
    """
    import json as _json
    import csv as _csv
    # Helper: map job title to bucket id (reuse from server-tips)
    def job_title_to_bucket_id(title: str | None) -> str | None:
        t = (title or "").strip().lower()
        if not t:
            return None
        if "am sunset" in t and "bar" in t:
            return "am_bar"
        if ("pm sunset" in t and "bar" in t) or ("sunset" in t and "bar" in t):
            return "sunset"
        if "ww bar" in t or "west wing bar" in t:
            return "westwing"
        if "ew bar" in t or "east wing bar" in t:
            return "eastwing"
        return None

    # Build bar shift windows for the selected bucket/date from labor_shifts_detailed_daily.csv
    shift_windows: list[tuple[datetime, datetime]] = []
    try:
        path = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
        if path.exists():
            with path.open("r", encoding="utf-8") as fcsv:
                rdr = _csv.DictReader(fcsv)
                for r in rdr:
                    if (r.get("date") or "").strip() != (date or ""):
                        continue
                    jt = (r.get("job_title") or r.get("jobtitle") or "").strip()
                    bid = job_title_to_bucket_id(jt)
                    if bid != (bucket or ""):
                        continue
                    st = _parse_iso(r.get("start_time_utc"))
                    en = _parse_iso(r.get("end_time_utc"))
                    if st and en and en > st:
                        # Normalize to UTC
                        try:
                            st = st.astimezone(timezone.utc)
                            en = en.astimezone(timezone.utc)
                        except Exception:
                            pass
                        shift_windows.append((st, en))
    except Exception:
        shift_windows = []

    # Load category name map (prefer menu_category.csv)
    def load_sales_category_name_map() -> Dict[str, str]:
        mp: Dict[str, str] = {}
        try:
            csv_path = REPORTS_DIR / "menu_category.csv"
            if csv_path.exists():
                with csv_path.open("r", encoding="utf-8") as f:
                    rdr = _csv.DictReader(f)
                    for rr in rdr:
                        gid = (rr.get("sales_category_guid") or "").strip()
                        nm = (rr.get("sales_category_name") or "").strip()
                        if gid and nm and gid not in mp:
                            mp[gid] = nm
        except Exception:
            pass
        if not mp:
            try:
                from toast_client import ToastClient
                tc = ToastClient()
                mp = tc.get_sales_categories() or {}
                mp = {str(k): v for k, v in (mp or {}).items()}
            except Exception:
                mp = {}
        # supplement from menus.json
        try:
            p = RAW_DIR / "menus" / "menus.json"
            if p.exists():
                data = json.loads(p.read_text())
                def walk(o):
                    if isinstance(o, dict):
                        try:
                            if (o.get("entityType") == "SalesCategory") and o.get("guid"):
                                gid = str(o.get("guid"))
                                nm = (o.get("name") or o.get("label") or o.get("displayName") or "").strip()
                                if gid and nm and gid not in mp:
                                    mp[gid] = nm
                        except Exception:
                            pass
                        for v in o.values():
                            walk(v)
                    elif isinstance(o, list):
                        for v in o:
                            walk(v)
                walk(data)
        except Exception:
            pass
        return mp

    sales_cat_name_by_guid = load_sales_category_name_map()
    BUCKETS = ["Food","Wine","Draft Beer","Liquor","NA Beverage","Bottled Beer","Bottled Wine"]
    def bucket_for_cat_name(name: str) -> str:
        n=(name or "").strip().lower()
        if not n:
            return "Food"
        if ("wine" in n) and ("bottle" in n or "bottled" in n):
            return "Bottled Wine"
        if ("beer" in n) and ("bottle" in n or "bottled" in n):
            return "Bottled Beer"
        if n=="wine" or ("wine" in n):
            return "Wine"
        if ("draft" in n and "beer" in n) or n=="draft beer":
            return "Draft Beer"
        if any(k in n for k in ["liquor","spirit","cocktail","whiskey","vodka","gin","tequila","rum","bourbon","rye","mezcal"]):
            return "Liquor"
        if any(k in n for k in ["na beverage","non-alcoholic","n/a beverage","mocktail","soda","juice","coffee","tea"]):
            return "NA Beverage"
        if "beer" in n:
            return "Draft Beer"
        return "Food"

    # Map bucket to bar worker display name (as appears on payments.server)
    # Normalize bucket aliases
    _bucket = (bucket or "").strip()
    if _bucket == "am":
        _bucket = "am_bar"
    bar_name_by_bucket = {
        "sunset": "Low Bar",
        "am_bar": "AM Bar",
        "westwing": "WW Bar",
        "eastwing": "EW Bar",
    }
    target_bar_name = bar_name_by_bucket.get(_bucket or "", "").strip().lower()

    # Build alias set of GUIDs for the target bar worker from employees.json
    # Seed with known v2EmployeeGuid mappings (from user-provided mapping)
    known_guid_by_bucket = {
        "am_bar": {"383c5a3d-c6d0-40c7-bb5b-2f1475c0a9a1"},
        "sunset": {"84c80171-22fb-4d7e-b015-e391a5c846de"},
        "westwing": {"33fbe0d8-3eb8-4dc8-a0d1-f753b92c232b"},
    }
    bar_aliases: set[str] = set(known_guid_by_bucket.get(_bucket, set()))
    try:
        emps_path = RAW_DIR / "employees.json"
        if emps_path.exists() and target_bar_name:
            with emps_path.open("r", encoding="utf-8") as f:
                emps = json.load(f) or []
            for e in emps:
                first = (e.get("firstName") or "").strip()
                last = (e.get("lastName") or "").strip()
                chosen = (e.get("chosenName") or "").strip()
                full = (first + (" " + last if last else "")).strip()
                # match by chosenName or full name case-insensitive to our mapping names
                names = [n for n in [chosen, full] if n]
                if any((n or "").strip().lower() == target_bar_name for n in names):
                    for k in ("guid", "id", "v2EmployeeGuid"):
                        v = (e.get(k) or "").strip()
                        if v:
                            bar_aliases.add(v)
                    break
    except Exception:
        bar_aliases = set()

    # Iterate orders for date and aggregate category totals within bar shift windows
    category_totals: Dict[str, float] = {k: 0.0 for k in BUCKETS}
    net_sales_sum = 0.0
    cash_tip_sum = 0.0
    credit_tip_sum = 0.0
    try:
        orders_path = RAW_DIR / "orders" / f"{date}.json"
        if orders_path.exists():
            orders_data = _json.load(orders_path.open("r", encoding="utf-8")) or []
            def to_float(x):
                try:
                    return float(x)
                except Exception:
                    return 0.0
            for o in orders_data:
                for c in (o.get("checks") or []):
                    if c.get("voided") or c.get("deleted"):
                        continue
                    # Only include checks with at least one payment by the target bar worker.
                    if target_bar_name:
                        has_bar_payment = False
                        for p in (c.get("payments") or []):
                            srv = (p.get("server") or {}) if isinstance(p, dict) else {}
                            # Prefer GUID-based match when available
                            ids = [
                                (srv.get("guid") or "").strip(),
                                (srv.get("id") or "").strip(),
                                (srv.get("v2EmployeeGuid") or "").strip(),
                            ]
                            if bar_aliases and any(i and i in bar_aliases for i in ids):
                                has_bar_payment = True
                                break
                            # Fallback to name match if we don't have aliases
                            if not bar_aliases:
                                nm = (srv.get("name") or srv.get("fullName") or srv.get("displayName") or "").strip().lower()
                                if nm == target_bar_name:
                                    has_bar_payment = True
                                    break
                        if not has_bar_payment:
                            continue
                    # Filter checks to bar shift windows if available
                    if shift_windows:
                        check_ts = _parse_iso(c.get("paidDate") or c.get("closedDate") or c.get("openedDate"))
                        if check_ts:
                            try:
                                check_ts = check_ts.astimezone(timezone.utc)
                            except Exception:
                                pass
                        in_window = False
                        if check_ts:
                            for st, en in shift_windows:
                                if st <= check_ts <= en:
                                    in_window = True
                                    break
                        if not in_window:
                            continue
                    # Aggregate amounts
                    amt_field = c.get("amount") or c.get("total") or c.get("net") or c.get("subtotal") or 0.0
                    net_sales_sum += to_float(amt_field)
                    # Tips from payments for this check by the target bar worker
                    for p in (c.get("payments") or []):
                        srv = (p.get("server") or {}) if isinstance(p, dict) else {}
                        ids = [
                            (srv.get("guid") or "").strip(),
                            (srv.get("id") or "").strip(),
                            (srv.get("v2EmployeeGuid") or "").strip(),
                        ]
                        matched_srv = False
                        if bar_aliases and any(i and i in bar_aliases for i in ids):
                            matched_srv = True
                        elif not bar_aliases:
                            nm = (srv.get("name") or srv.get("fullName") or srv.get("displayName") or "").strip().lower()
                            matched_srv = (nm == target_bar_name)
                        if not matched_srv:
                            continue
                        tip_amt = to_float(p.get("tipAmount") or p.get("tips") or p.get("gratuityTipAmount") or 0.0)
                        pay_type = (p.get("paymentType") or p.get("type") or p.get("tenderType") or "").strip().upper()
                        is_cash = (pay_type == "CASH") or ("CASH" in pay_type)
                        if is_cash:
                            cash_tip_sum += tip_amt
                        else:
                            credit_tip_sum += tip_amt
                    for sel in (c.get("selections") or []):
                        if sel.get("voided") or sel.get("deleted"):
                            continue
                        price = to_float(sel.get("price"))
                        sc_guid = ((sel.get("salesCategory") or {}).get("guid")) or ""
                        sc_name = sales_cat_name_by_guid.get(str(sc_guid), "")
                        # If no explicit mapped sales category, skip this selection entirely (no heuristics)
                        if not sc_name:
                            continue
                        cat_bucket = bucket_for_cat_name(sc_name)
                        category_totals[cat_bucket] = category_totals.get(cat_bucket, 0.0) + price
    except Exception:
        pass

    # Build tip pool suggestions from categories (Busser/Expo/Runner)
    def _round2(x: float) -> float:
        try:
            return round(float(x or 0.0), 2)
        except Exception:
            return 0.0
    sv_break: Dict[str, float] = {}
    ex_break: Dict[str, float] = {}
    rn_break: Dict[str, float] = {}
    for cat, amt in (category_totals or {}).items():
        a = float(amt or 0.0)
        sv_break[cat] = _round2(0.02 * a)
        ex_break[cat] = _round2(0.01 * a if cat == "Food" else 0.0)
        rn_break[cat] = _round2(0.005 * a if cat == "Food" else 0.0)
    servertips_suggest = _round2(sum(sv_break.values()))
    expotips_suggest = _round2(sum(ex_break.values()))
    runnertips_suggest = _round2(sum(rn_break.values()))
    total_sales_all = _round2(sum((category_totals or {}).values()))

    # Prefer CSV source for cash/credit tips if available (by bar display name)
    cash_final = cash_tip_sum
    credit_final = credit_tip_sum
    try:
        csv_path = REPORTS_DIR / "net_sales_by_employee_daily.csv"
        bar_display = bar_name_by_bucket.get(_bucket, "")
        if csv_path.exists() and bar_display:
            with csv_path.open("r", encoding="utf-8") as f:
                rdr = _csv.DictReader(f)
                for r in rdr:
                    if (r.get("date") == date) and ((r.get("employee_name") or "").strip() == bar_display):
                        def _f(x):
                            try:
                                return float(x)
                            except Exception:
                                return 0.0
                        cash_final = _f(r.get("cash_tips"))
                        credit_final = _f(r.get("credit_card_tips"))
                        break
    except Exception:
        pass

    payload = {
        "cash_tips": round(cash_final, 2),
        "credit_card_tips": round(credit_final, 2),
        "net_sales": total_sales_all,
        "category_totals": {k: _round2(v) for k, v in (category_totals or {}).items()},
        "category_tip_breakdown": {
            "servertips": sv_break,
            "expotips": ex_break,
            "runnertips": rn_break,
        },
        "servertips": servertips_suggest,
        "expotips": expotips_suggest,
        "runnertips": runnertips_suggest,
    }
    return payload


def _build_menu_category_csv_text() -> str:
    """Return CSV text mapping menu items to sales categories using Toast Configuration API.

    Columns: item_guid,item_name,sales_category_guid,sales_category_name,menu_path
    """
    import io
    import json as _json
    import csv as _csv
    from typing import Any, Dict, List

    # 1) Fetch Sales Categories from Toast API
    cat_map: Dict[str, str] = {}
    try:
        from toast_client import ToastClient
        tc = ToastClient()
        cat_map = tc.get_sales_categories() or {}
    except Exception as ex:
        cat_map = {}

    # 2) Load menus.json
    menus_path = RAW_DIR / "menus" / "menus.json"
    try:
        data = _json.loads(menus_path.read_text(encoding="utf-8")) if menus_path.exists() else {}
    except Exception:
        data = {}

    # 3) Supplement category map from menus.json (discover SalesCategory entities)
    try:
        def _walk_collect_categories(o: Any):
            if isinstance(o, dict):
                try:
                    et = (o.get("entityType") or o.get("type") or "").strip()
                    if et == "SalesCategory":
                        gid = (o.get("guid") or o.get("id") or o.get("v2Guid") or "").strip()
                        nm = (o.get("name") or o.get("label") or o.get("displayName") or "").strip()
                        if gid and nm and gid not in cat_map:
                            cat_map[gid] = nm
                except Exception:
                    pass
                for v in o.values():
                    if isinstance(v, (dict, list)):
                        _walk_collect_categories(v)
            elif isinstance(o, list):
                for it in o:
                    _walk_collect_categories(it)
        if data:
            _walk_collect_categories(data)
    except Exception:
        pass

    # 4) Traverse to collect items and their sales categories
    rows: List[Dict[str, Any]] = []

    def sales_cat_guid_from(obj: Dict[str, Any]) -> str:
        try:
            sc = obj.get("salesCategory") or {}
            g = (sc.get("guid") or sc.get("id") or sc.get("v2Guid") or "").strip()
            if g:
                return g
        except Exception:
            pass
        try:
            g2 = (obj.get("salesCategoryGuid") or obj.get("salesCategoryId") or "").strip()
            if g2:
                return g2
        except Exception:
            pass
        return ""

    def name_of(obj: Dict[str, Any]) -> str:
        for k in ("name", "label", "displayName", "posName"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def guid_of(obj: Dict[str, Any]) -> str:
        for k in ("guid", "id", "v2Guid"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    # Identify likely item entity types
    ITEM_ENTITY_TYPES = {"MenuItem", "Item", "MenuItemOption", "MenuGroupItem"}

    def walk(o: Any, path_names: List[str]):
        if isinstance(o, dict):
            et = (o.get("entityType") or o.get("type") or "").strip()
            # If this is a menu or group, extend the path for children
            if et in {"Menu", "MenuGroup", "Group"}:
                nm = name_of(o)
                walk_children = []
                for v in o.values():
                    if isinstance(v, (dict, list)):
                        walk_children.append(v)
                for ch in walk_children:
                    walk(ch, path_names + ([nm] if nm else []))
            else:
                # Treat as item when we have a guid and a name and a salesCategory
                item_guid = guid_of(o)
                item_name = name_of(o)
                sc_guid = sales_cat_guid_from(o)
                if item_guid and item_name and sc_guid and (et in ITEM_ENTITY_TYPES or o.get("price") is not None or o.get("sku") is not None):
                    # Try resolve category name: API map > inline name on item > menus.json-supplement map
                    sc_name = cat_map.get(sc_guid, "")
                    if not sc_name:
                        try:
                            sc_inline = o.get("salesCategory") or {}
                            nm_inline = (sc_inline.get("name") or sc_inline.get("label") or sc_inline.get("displayName") or "").strip()
                            if nm_inline:
                                sc_name = nm_inline
                                # cache it for other items with same guid
                                cat_map[sc_guid] = sc_name
                        except Exception:
                            pass
                    rows.append({
                        "item_guid": item_guid,
                        "item_name": item_name,
                        "sales_category_guid": sc_guid,
                        "sales_category_name": sc_name,
                        "menu_path": " / ".join([p for p in path_names if p]),
                    })
                # Continue walking nested structures
                for v in o.values():
                    if isinstance(v, (dict, list)):
                        walk(v, path_names)
        elif isinstance(o, list):
            for it in o:
                walk(it, path_names)

    # Start traversal: handle either root dict with 'menus' or list
    root = data
    if isinstance(root, dict) and isinstance(root.get("menus"), list):
        walk(root.get("menus"), [])
    else:
        walk(root, [])

    # De-duplicate by item_guid (keep first occurrence)
    seen: set[str] = set()
    unique_rows: List[Dict[str, Any]] = []
    for r in rows:
        gid = r.get("item_guid")
        if gid and gid not in seen:
            seen.add(gid)
            unique_rows.append(r)

    # 5) Build CSV content
    output = io.StringIO()
    fieldnames = ["item_guid", "item_name", "sales_category_guid", "sales_category_name", "menu_path"]
    writer = _csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for r in unique_rows:
        writer.writerow({k: r.get(k, "") for k in fieldnames})
    return output.getvalue()


@app.get("/reports/menu_category.csv", response_class=PlainTextResponse)
def menu_category_csv() -> PlainTextResponse:
    """HTTP endpoint to generate and return menu_category.csv and write it to data/reports."""
    csv_text = _build_menu_category_csv_text()
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / "menu_category.csv").write_text(csv_text, encoding="utf-8")
    except Exception:
        pass
    return PlainTextResponse(content=csv_text, media_type="text/csv")


@app.get("/reports/shift_orders_report.csv", response_class=PlainTextResponse)
def shift_orders_report_csv(snapshot: Optional[Dict[str, Any]] = None) -> PlainTextResponse:
    """Build a per-shift, per-worker orders aggregation CSV at data/reports/shift_orders_report.csv.

    Aggregates bucketized sales, check amounts, service charges, and tips split by cash/non-cash
    for checks whose timestamps fall within each worker's shift window.
    """
    import json as _json
    import csv as _csv

    def _f(x: Any) -> float:
        try:
            return float(x)
        except Exception:
            return 0.0

    # Employee guid -> display name
    emp_map: Dict[str, str] = {}
    try:
        with (RAW_DIR / "employees.json").open("r", encoding="utf-8") as f:
            emps = _json.load(f) or []
        emp_map = t.build_employee_map(emps) if emps else {}
    except Exception:
        emp_map = {}

    # Load sales category name map from menus.json
    def load_sales_category_name_map() -> Dict[str, str]:
        path = RAW_DIR / "menus" / "menus.json"
        try:
            with path.open("r", encoding="utf-8") as f:
                data = _json.load(f)
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

    # Load orders by date with cache
    orders_cache: Dict[str, List[Dict[str, Any]]] = {}
    def load_orders_for(date_iso: str) -> List[Dict[str, Any]]:
        if date_iso in orders_cache:
            return orders_cache[date_iso]
        p = RAW_DIR / "orders" / f"{date_iso}.json"
        try:
            orders_cache[date_iso] = _json.load(p.open("r", encoding="utf-8")) if p.exists() else []
        except Exception:
            orders_cache[date_iso] = []
        return orders_cache[date_iso]

    # Build shifts from labor_shifts_detailed_daily.csv or fallback to time_entries
    shifts: List[Dict[str, Any]] = []
    try:
        path = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                rdr = _csv.DictReader(f)
                for r in rdr:
                    try:
                        d = (r.get("date") or "").strip()
                        eg = (r.get("employee_guid") or "").strip()
                        if not (d and eg):
                            continue
                        st = t._parse_iso_any(r.get("start_time_utc") or r.get("start") or "")
                        en = t._parse_iso_any(r.get("end_time_utc") or r.get("end") or "")
                        if not (st and en and en > st):
                            continue
                        name = (r.get("employee_name") or r.get("name") or emp_map.get(eg) or "").strip()
                        jt = (r.get("job_title") or r.get("jobtitle") or "").strip()
                        shifts.append({"date": d, "employee_guid": eg, "employee_name": name, "job_title": jt, "start": st, "end": en})
                    except Exception:
                        continue
        else:
            te_dir = RAW_DIR / "time_entries"
            for f in sorted(te_dir.glob("*.json")):
                day_iso = f.stem
                try:
                    te_list = _json.load(f.open("r", encoding="utf-8")) or []
                except Exception:
                    continue
                for te in (te_list or []):
                    try:
                        eg = ((te.get("employeeReference") or {}).get("guid")) or ""
                        if not eg:
                            continue
                        st = t._parse_iso_any(te.get("inDate") or te.get("startDate"))
                        en = t._parse_iso_any(te.get("outDate") or te.get("endDate"))
                        if not (st and en and en > st):
                            continue
                        name = emp_map.get(eg, "")
                        jt = te.get("jobTitle") or ((te.get("job") or {}).get("name")) or ""
                        shifts.append({"date": day_iso, "employee_guid": eg, "employee_name": name, "job_title": jt, "start": st, "end": en})
                    except Exception:
                        continue
    except Exception:
        shifts = []

    # Precompute bucket totals per order
    def build_order_bucket_totals(orders: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
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
                    sc_name = sales_cat_name_by_guid.get(str(sc_guid), "")
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

    out_rows: List[Dict[str, Any]] = []
    for sh in shifts:
        d = sh["date"]
        st = sh["start"]
        en = sh["end"]
        eg = sh["employee_guid"]
        name = sh.get("employee_name") or emp_map.get(eg, "")
        jt = sh.get("job_title") or ""
        orders = load_orders_for(d)
        buckets_tot = build_order_bucket_totals(orders)
        orders_seen: Set[str] = set()
        checks_count = 0
        agg = {k: 0.0 for k in BUCKETS}
        tax_sum = net_sum = total_sum = svc_sum = 0.0
        cash_tips_sum = noncash_tips_sum = 0.0

        for o in (orders or []):
            order_guid = str(o.get("guid") or "")
            order_server_ids: List[str] = []
            try:
                srv_o = (o.get("server") or {})
                order_server_ids = [
                    (srv_o.get("guid") or "").strip(),
                    (srv_o.get("id") or "").strip(),
                    (srv_o.get("v2EmployeeGuid") or "").strip(),
                ]
                order_server_ids = [s for s in order_server_ids if s]
            except Exception:
                order_server_ids = []
            for c in (o.get("checks") or []):
                if c.get("voided") or c.get("deleted"):
                    continue
                ts = c.get("paidDate") or c.get("closedDate") or c.get("openedDate")
                dt = t._parse_iso_any(ts)
                try:
                    if dt:
                        dt = dt.astimezone(timezone.utc)
                except Exception:
                    pass
                if not (dt and st <= dt <= en):
                    continue

                payments = (c.get("payments") or [])
                server_amounts: Dict[str, float] = {}
                for p in payments:
                    srv_p = (p.get("server") or {})
                    ids = [
                        (srv_p.get("guid") or "").strip(),
                        (srv_p.get("id") or "").strip(),
                        (srv_p.get("v2EmployeeGuid") or "").strip(),
                    ]
                    amt = _f(p.get("amount"))
                    if not any(ids) or amt <= 0:
                        continue
                    canonical = next((s for s in ids if s), None)
                    if canonical:
                        server_amounts[canonical] = server_amounts.get(canonical, 0.0) + amt
                total_pay_amt = sum(server_amounts.values())
                allocations: Dict[str, float] = {}
                if total_pay_amt > 0:
                    for sid, amt in server_amounts.items():
                        allocations[sid] = (amt / total_pay_amt)
                    for p in payments:
                        srv_p = (p.get("server") or {})
                        alt_ids = [
                            (srv_p.get("guid") or "").strip(),
                            (srv_p.get("id") or "").strip(),
                            (srv_p.get("v2EmployeeGuid") or "").strip(),
                        ]
                        canonical = next((s for s in alt_ids if s in server_amounts), None)
                        if canonical:
                            for sid in alt_ids:
                                allocations[sid] = allocations.get(canonical, 0.0)
                elif order_server_ids:
                    for sid in order_server_ids:
                        allocations[sid] = 1.0

                frac = allocations.get(eg, 0.0)
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
                try:
                    for sc in (c.get("appliedServiceCharges", []) or []):
                        svc += _f((sc or {}).get("chargeAmount"))
                except Exception:
                    pass
                svc_sum += svc * frac
                for p in payments:
                    srv_p = (p.get("server") or {})
                    sid = (srv_p.get("guid") or srv_p.get("id") or srv_p.get("v2EmployeeGuid") or "").strip()
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

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    if snapshot is None:
        snapshot = _shift_orders_report_snapshot()
    out_path = REPORTS_DIR / "shift_orders_report.csv"
    headers = [
        "date","employee_guid","employee_name","job_title","start_time_utc","end_time_utc",
        "orders_count","checks_count",
        "food_sales","wine_sales","draft_beer_sales","liquor_sales","na_beverage_sales","bottled_beer_sales","bottled_wine_sales",
        "check_tax_amount","check_net_amount","check_total_amount","check_service_charges",
        "cash_tips","non_cash_tips",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    _update_build_state_entry(
        SHIFT_ORDERS_REPORT_KEY,
        {
            "built_at": time.time(),
            "latest_source_mtime": snapshot.get("latest_source_mtime", 0.0),
            "labor_mtime": snapshot.get("labor_mtime", 0.0),
            "time_entries_mtime": snapshot.get("time_entries_mtime", 0.0),
            "rows_written": len(out_rows),
        },
    )
    return PlainTextResponse(out_path.read_text(encoding="utf-8"), media_type="text/csv")
