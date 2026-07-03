# Toast Data Import Summary

## Data Fetched

Successfully pulled data from Toast API for **December 15-31, 2025** and **January 1-31, 2026**.

### Raw Data Files
- **48 days** of order data (JSON)
- **48 days** of time entries (JSON)
- **48 days** of payments (JSON)
- **156 employees** (updated)
- **7 menus** (updated)

### Processed Data
- **11,482 total shifts** in labor_shifts_detailed_daily.csv
- **171 unique dates** with data
- **189 days** in shifts database (includes existing data back to July)
- **134 workers** in the system

## Date Range Coverage

| Month | Dates Available |
|-------|----------------|
| August 2025 | 14-31 |
| September 2025 | 1-30 |
| October 2025 | 1-31 |
| November 2025 | 1-30 |
| December 2025 | 1-31 |
| January 2026 | 1-31 |

## Locations Detected

The system can detect these locations from job titles:
- **AM Bar** (AM Sunset Server, AM Bar Sunset)
- **Sunset Bar** (PM Sunset Server, PM Bar Sunset)
- **West Wing** (WW Server, WW Bar)
- **East Wing** (EW Server, EW Bar)

## How to View the Data

### 1. Calendar View
1. Open http://localhost:8080
2. Click **Calendar** in the sidebar
3. Navigate to December 2025 or January 2026
4. Click any date with blue "Orders" badge
5. See all workers who worked that day

### 2. Server Tips
1. Click **Server Tips** in the sidebar
2. Select a worker and date (Dec 15+ or Jan 1+)
3. System will auto-detect locations from shifts
4. Enter tip amounts and save

### 3. API Endpoints
All data is accessible via the API:
- `GET /api/dates` - All 171 available dates
- `GET /api/dates/2026-01-15/workers` - Workers for specific date
- `GET /api/workers/{name}/suggested-buckets?date=2026-01-15` - Locations for worker/date

## Notable Dates

| Date | Workers | Notes |
|------|---------|-------|
| Dec 25, 2025 | 0 | Christmas - Restaurant closed |
| Dec 31, 2025 | 85 | New Year's Eve |
| Jan 1, 2026 | 50 | New Year's Day |
| Jan 25, 2026 | 0 | No data (possibly closed) |

## Data Quality

- ✅ Orders: All 48 days fetched successfully
- ✅ Time Entries: All 48 days fetched successfully
- ✅ Payments: All 48 days fetched successfully
- ⚠️ Shifts API: Returns 404 (using time entries instead)
- ⚠️ Cash Management: Returns 404 (not critical)

## Next Steps

The data is now ready to use in the Toasty web app:
1. Navigate to the Calendar to browse dates
2. Click on any date to see workers
3. Click a worker to assign tips
4. Use the Payouts page to distribute tips

All data is stored locally in:
- `/home/ubuntu/new_toasty/toasty/data/raw/` - Raw JSON files
- `/home/ubuntu/new_toasty/toasty/data/reports/` - Processed CSV files
