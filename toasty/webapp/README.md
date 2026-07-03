# Toasty Web App

A modern web-based replacement for the Python CSV-based Toast Data Analytics application, built with Shoelace Web Components.

## Architecture

```
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│   Web Browser   │◄────►│  Static HTML/JS  │◄────►│   JAQ Server    │
│                 │      │  (Port 8080)     │      │  (Port 3000)    │
└─────────────────┘      └──────────────────┘      └─────────────────┘
                                │
                                ▼
                         ┌──────────────────┐
                         │  Python API      │
                         │  (Port 5000)     │
                         └──────────────────┘
                                │
                                ▼
                         ┌──────────────────┐
                         │ tip_distribution │
                         │      .db         │
                         └──────────────────┘
```

## Features

### 1. Dashboard
- Real-time metrics (Orders, Employees, Time Entries, Cash Entries)
- Visual charts for Orders by Status
- Auto-refresh capability

### 2. Reports
- Orders Overview
- Employees Directory
- Time Entries
- Data fetched via DSL queries from JAQ Server

### 3. Query Builder
- Custom DSL query editor with syntax highlighting
- Execute queries against JAQ Server
- Export results to CSV
- Example query loader

### 4. Server Tips
- Select worker, date, and location
- Fetch existing tips from database
- Input: Cash Tips, Credit Tips, Gratuity, Net Sales
- Assign tips to payout pools:
  - Bartender Tips
  - Busser Tips
  - Expo Tips
  - Runner Tips
- Save and Push to Payouts

### 5. Bartender Tips
- Select bartender, date, and bar location
- Input: Cash Tips, Credit Tips, Net Sales, Hours Worked
- Save and Push to Payouts

### 6. Payouts Management
- Select location (bucket) and business date
- View unpaid tip totals by destination
- Assign workers to payout destinations:
  - Bartender Assignments
  - Busser Assignments
  - Expo Assignments
  - Runner Assignments
- Preview distribution calculation
- Commit payouts to database

## Running the Application

### 1. Start JAQ Server (if not running)
```bash
cd /home/ubuntu/jaq/json-loader-server
./start.sh start
```

### 2. Start Python API Server
```bash
cd /home/ubuntu/new_toasty/toasty/webapp
source ../.venv/bin/activate
python3 api.py
```

API will be available at: http://localhost:5000

### 3. Start Web Server
```bash
cd /home/ubuntu/new_toasty/toasty/webapp
python3 -m http.server 8080
```

Web app will be available at: http://localhost:8080

## API Endpoints

### Workers
- `GET /api/workers` - List all workers
- `GET /api/workers/<name>/roles` - Get worker roles

### Buckets
- `GET /api/buckets` - List all locations

### Server Tips
- `GET /api/server-tips?worker=X&date=Y&bucket=Z` - Get server tips
- `POST /api/server-tips` - Save server tips

### Bartender Tips
- `GET /api/bartender-tips?bartender=X&date=Y&bar=Z` - Get bartender tips
- `POST /api/bartender-tips` - Save bartender tips

### Payouts
- `GET /api/payouts/unpaid?bucket=X&date=Y` - Get unpaid amounts
- `GET /api/payouts/assignments?bucket=X` - Get worker assignments
- `POST /api/payouts/assignments` - Save assignments
- `POST /api/payouts/preview` - Preview distribution
- `POST /api/payouts/commit` - Commit payouts
- `GET /api/payouts/committed?bucket=X&date=Y` - Get committed payouts

## Database Schema

The app uses the existing `tip_distribution.db` with tables:
- `workers` - Worker names
- `servers` - Server tip records
- `bartenders` - Bartender tip records
- `payouts` - Committed payouts
- `payout_sessions` - Payout session tracking
- `worker_assignments` - Worker-to-destination assignments
- `transactions` - Historical tip transactions

## Technology Stack

- **Frontend**: HTML5, Vanilla JavaScript, Shoelace 2.17.1 Web Components
- **Charts**: Chart.js 4.4.1
- **Backend API**: Flask (Python)
- **Data Source**: JAQ JSON Loader Server (Rust)
- **Database**: SQLite (existing tip_distribution.db)

## Migration from Old App

| Old Feature | New Implementation |
|-------------|-------------------|
| Python CSV Generation | DSL queries to JAQ Server |
| Jinja2 Templates | Shoelace Web Components |
| Server Tips Form | Server Tips page with API backend |
| Bartender Tips Form | Bartender Tips page with API backend |
| Payouts Page | Payouts page with live distribution preview |
| Worker Assignments | Checkboxes with auto-save |
| CSV Downloads | In-browser CSV generation |
