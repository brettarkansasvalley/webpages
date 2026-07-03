# Toast Tip Distribution System - AI Agent Guide

## Project Overview

This is a **restaurant tip distribution and reporting system** integrated with the Toast POS (Point of Sale) API. The system automates the collection of sales, labor, and payment data from Toast, calculates tip distributions for servers and bartenders, and provides both a web interface and a desktop application for managing payouts.

The project serves a multi-location restaurant with four service areas (buckets):
- **AM Bar** (`am_bar`)
- **West Wing** (`westwing`)  
- **East Wing** (`eastwing`)
- **Sunset Bar** (`sunset`)

### Key Capabilities

1. **Data Synchronization**: Fetches employees, orders, time entries, shifts, cash entries, and payments from Toast API
2. **Tip Entry**: Servers and bartenders enter daily tips by bucket/location
3. **Payout Calculation**: Distributes tips to workers (Bartenders, Bussers, Expo, Runners) based on assignments and hours worked
4. **Cashbox Tracking**: Tracks cash movements across physical drawers (AM Bar, West Wing Bar, Sunset Bar, Office)
5. **Reporting**: Generates CSV reports and HTML views for analysis

## Technology Stack

| Component | Technology |
|-----------|------------|
| Web Framework | FastAPI (Python) |
| Desktop App | Tkinter (Python) |
| Database | SQLite (`tip_distribution.db`) |
| Frontend | Jinja2 templates + vanilla JavaScript |
| External API | Toast POS API |
| DSL Queries | JAQ JSON Loader (SQL-like interface for JSON) |
| Utilities | Go (for formbuilderdb operations) |

### Python Dependencies

```
requests>=2.31.0
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
python-multipart>=0.0.9
Jinja2>=3.1.4
```

## Project Structure

```
/home/ubuntu/new_toasty/toasty/
├── app.py                      # Main FastAPI web application (~7400 lines)
├── toast_30d_report.py         # Toast API data fetcher and report generator
├── toast_client.py             # Reusable Toast API client
├── get_toast.py                # CLI tool for fetching Toast data
├── requirements.txt            # Python dependencies
├── start.sh                    # Production startup script
├── tip_distribution.db         # SQLite database
│
├── jbhooks/                    # Desktop Tkinter application
│   ├── main_app.py             # Main tkinter application
│   ├── config.py               # Configuration constants
│   ├── database.py             # Database operations
│   ├── tip_calculator.py       # Tip calculation logic
│   ├── ui_popups.py            # Touch-friendly UI popups
│   └── ...
│
├── scripts/                    # Data processing scripts
│   ├── build_orders_report.py
│   ├── build_shift_orders_report.py
│   ├── fetch_payments_report.py
│   └── fetch_raw_payments.py
│
├── templates/                  # Jinja2 HTML templates
│   ├── base.html               # Base layout with navigation
│   ├── index.html              # Home with data fetch controls
│   ├── server_tips.html        # Server tip entry form
│   ├── bartender_tips.html     # Bartender tip entry form
│   ├── payouts.html            # Payout management
│   ├── cashbox.html            # Cashbox ledger
│   └── ... (18 templates total)
│
├── static/                     # Static web assets
│   ├── styles.css              # Application styles (touch-friendly)
│   ├── app.js                  # Client-side JavaScript
│   ├── sort_filter.js          # Table sorting/filtering
│   └── osk.js                  # On-screen keyboard for touch
│
├── data/                       # Data storage
│   ├── raw/                    # Raw JSON from Toast API
│   │   ├── employees.json
│   │   ├── orders/             # Daily order JSON files
│   │   ├── time_entries/       # Daily time entry JSON files
│   │   ├── shifts/             # Daily shift JSON files
│   │   ├── cash/               # Cash entries and deposits
│   │   ├── menus/              # Menu data
│   │   └── ...
│   └── reports/                # Generated CSV reports
│       ├── net_sales_by_employee_daily.csv
│       ├── labor_shifts_detailed_daily.csv
│       ├── cash_tips_per_shift.csv
│       └── ... (25+ report files)
│
├── DSL/                        # Domain Specific Language queries
│   ├── queries/                # DSL query files (.dsl.json)
│   ├── scripts/                # Helper scripts
│   └── outputs/                # Generated CSV outputs
│
└── *.go                        # Go utilities for formbuilderdb
    ├── fix_toast_indices.go
    ├── fix_toast_labor_indices.go
    ├── debug_submissions.go
    └── test_query.go
```

## Key Modules

### 1. Web Application (`app.py`)

Main FastAPI application providing:

- **Data Management**: Fetch and sync data from Toast API
- **Tip Entry**: Forms for servers and bartenders to enter tips
- **Payouts**: Calculate and record tip payouts to workers
- **Cashbox**: Track cash movements across drawers
- **Reports**: Various CSV and HTML reports for analysis
- **API Endpoints**: RESTful API for programmatic access

Key routes:
| Route | Method | Description |
|-------|--------|-------------|
| `GET /` | HTML | Home page with fetch controls |
| `GET /server-tips` | HTML | Server tip entry form |
| `GET /bartender-tips` | HTML | Bartender tip entry form |
| `GET /payouts` | HTML | Payout management interface |
| `GET /cashbox` | HTML | Cashbox ledger |
| `GET /reports` | HTML | Data and reports listing |
| `GET /report-shifts` | HTML | Per-shift tips report |
| `GET /report-payouts` | HTML | Detailed payouts report |
| `POST /run` | PlainText | Trigger data fetch from Toast |
| `POST /admin/shutdown` | JSON | Shutdown server (password required) |
| `POST /admin/restart` | JSON | Restart server (password required) |

### 2. Desktop Application (`jbhooks/`)

Tkinter-based touch-friendly application for in-restaurant use:

- **Server tab**: Enter tips by bucket (AM, West Wing, Sunset, East Wing)
- **Bartender tab**: Bartender-specific tip calculations
- **Payouts tab**: Distribute tips to workers
- **Admin tab**: Worker management and cashbox operations

Run with: `cd jbhooks && python main_app.py`

### 3. Toast Integration (`toast_30d_report.py`, `toast_client.py`)

Handles authentication and data retrieval from Toast API:

- Employees, orders, time entries, shifts, cash entries, payments
- Generates CSV reports from raw JSON data
- Environment variables for credentials:
  - `TOAST_CLIENT_ID`
  - `TOAST_CLIENT_SECRET`
  - `TOAST_RESTAURANT_GUID`
  - `TOAST_API_HOST` (default: https://ws-api.toasttab.com)

### 4. Database (`jbhooks/database.py`)

SQLite database with tables:

| Table | Purpose |
|-------|---------|
| `workers` | Employee records |
| `transactions` | Tip transactions |
| `servers` | Server shift data |
| `bartenders` | Bartender shift data |
| `payouts` | Recorded payouts (unpaid and claimed) |
| `cashbox_ledger` | Cash drawer movements |
| `worker_assignments` | Worker-to-bucket assignments |
| `payout_sessions` | Double-entry payout session tracking |
| `payout_transfers` | Transfer records for payouts |
| `payout_legs` | Double-entry legs for each transfer |
| `worker_roles` | Worker role assignments |

### 5. DSL Query System (`DSL/`)

SQL-like queries for reporting against JSON data via JAQ server:

| Query | Output |
|-------|--------|
| `01_employees.dsl.json` | Employee master data |
| `04_labor_hours_daily.dsl.json` | Aggregated labor hours |
| `05_labor_shifts_detailed_daily.dsl.json` | Detailed shift information |
| `06_cash_tips_per_shift.dsl.json` | Cash tips declared per shift |
| `07_gratuity_per_shift.dsl.json` | Gratuity/service charges |
| `10_payments_summary.dsl.json` | Payments and tips summary |

## Build and Run Commands

### Development

```bash
# Activate virtual environment
source .venv/bin/activate

# Run FastAPI development server
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8001

# Or use the production startup script
./start.sh
```

### Production

```bash
# The start script handles:
# - Killing existing processes on port 8001
# - Starting uvicorn in background
# - Waiting for readiness
# - Optionally launching browser in kiosk mode
./start.sh
```

Logs are written to `/tmp/uvicorn.log`.

### Desktop Application

```bash
cd jbhooks
python main_app.py
```

### Data Fetch (Manual)

```bash
# Fetch Toast data for past 30 days
python toast_30d_report.py

# Or trigger via web API
curl -X POST http://localhost:8001/run
```

## Code Style Guidelines

### Python

1. **Type Hints**: Use type hints where practical (`from __future__ import annotations`)
2. **Indentation**: 4 spaces (PEP 8)
3. **Import Ordering**: stdlib, third-party, local
4. **File Operations**: Use `Path` from `pathlib`
5. **Error Handling**: Use try/except with specific exceptions; log errors appropriately

Example:
```python
from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, List, Any

# Local imports
from config import DATABASE_FILE
```

### Naming Conventions

- Functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_CASE`
- Private methods: `_leading_underscore`
- Database tables: `snake_case`

### Database Operations

- Use parameterized queries (never string concatenation)
- Always close connections in `finally` blocks
- Migrations handled via `ALTER TABLE` checks in `init_database()`

Example:
```python
cursor.execute(
    'SELECT * FROM payouts WHERE bucket = ? AND business_date = ?',
    (bucket, business_date)
)
```

## Testing

No formal test suite is present. Testing is done via:

1. **Manual UI testing** through web interface
2. **API endpoint testing** with `test_api.py`
3. **Database inspection** with Go utilities (`debug_submissions.go`, `test_query.go`)

When modifying core calculation logic:
1. Test with sample data from `data/raw/`
2. Verify CSV outputs in `data/reports/`
3. Check database consistency via SQLite browser or CLI

## Security Considerations

1. **Credentials**: Stored in `start.sh` (environment variables) and referenced throughout
2. **Admin Password**: Hardcoded in `jbhooks/config.py` as `ADMIN_PASSWORD = "071925"`
3. **API Authentication**: Uses Toast OAuth2 machine client flow
4. **Input Validation**: Always validate and sanitize user inputs, especially for database queries
5. **No HTTPS in dev**: Production deployment should use reverse proxy (nginx) with SSL

## Data Flow

### 1. Fetch Cycle (`/run` endpoint or manual)

```
Authenticate with Toast API
    ↓
Download employees, orders, time entries, shifts, cash data
    ↓
Store as JSON in data/raw/
    ↓
Generate CSV reports in data/reports/
```

### 2. Tip Entry

```
Server/bartender enters tips via web or desktop app
    ↓
Data stored in SQLite (servers, bartenders tables)
    ↓
Payout records created in payouts table (unpaid)
```

### 3. Payouts

```
System calculates distributions based on assignments and hours
    ↓
Creates payout_transfers and payout_legs (double-entry)
    ↓
Updates cashbox_ledger for physical drawer tracking
    ↓
Marks payouts as claimed (payout_session_id set)
```

## Important Notes

- The system is designed for **touchscreen use** in a restaurant environment
- Time zone handling assumes US/Pacific (Toast business dates)
- Net Sales calculation follows Toast's guidance: uses `check['amount']` excluding voids
- The `formbuilderdb` integration (Go files) is for a separate form system at `/home/ubuntu/toasty/formbuilderdb/`
- Employee matching uses GUIDs and names from `employees.json`
- Payout destinations: `Bartender`, `Busser`, `Expo`, `Runner`
- Cash drawers: `AM Bar`, `West Wing Bar`, `Sunset Bar`, `Office`

## Common Tasks

### Add a New Worker

Via web: `GET /workers` → Enter name → Submit
Via desktop: Admin tab → Worker Management

### Change Worker Assignments

Via web: `GET /payouts` → Select bucket → Check workers for each destination
Via desktop: Admin tab → Assignment Management

### View Reports

Via web: `GET /reports` → Click report name
Files: Check `data/reports/` directory

### Backup Database

```bash
cp tip_distribution.db tip_distribution.db.bak.$(date +%Y%m%d%H%M%S)
```

### Clear Toast Data (Start Fresh)

```bash
curl -X POST http://localhost:8001/api/clear-toast-data
```

## Troubleshooting

1. **Port 8001 in use**: `start.sh` automatically kills existing processes
2. **Database locked**: Check for concurrent access; SQLite allows one writer
3. **Toast API errors**: Check credentials in environment variables
4. **Missing reports**: Run `/run` endpoint to fetch fresh data
5. **Formbuilderdb errors**: Ensure Go files are compiled and `formbuilderdb` server is running

## File References

| File | Purpose |
|------|---------|
| `app.py:2035` | `/run` endpoint - triggers data fetch |
| `app.py:3986` | `GET /server-tips` - server form |
| `app.py:5371` | `GET /payouts` - payout interface |
| `jbhooks/config.py:18` | Admin password |
| `jbhooks/config.py:26` | Bucket configuration |
| `toast_30d_report.py:52` | Toast API credentials (fallback) |
