# Location Detection Feature

## Overview
The Toasty webapp now automatically detects which locations a worker worked at based on their shifts in the labor data.

## How It Works

### 1. Job Title to Location Mapping
Based on the old application's logic, job titles are mapped to locations:

| Job Title | Bucket ID | Display Name |
|-----------|-----------|--------------|
| AM Sunset Server | `am_bar` | AM Bar |
| PM Sunset Server | `sunset` | Sunset Bar |
| WW Server | `westwing` | West Wing |
| EW Server | `eastwing` | East Wing |
| AM Bar (bartender) | `am_bar` | AM Bar |
| PM Bar (bartender) | `sunset` | Sunset Bar |
| WW Bar (bartender) | `westwing` | West Wing |

### 2. Data Flow

1. User selects a **Worker** and **Date**
2. Click "Fetch from Toast"
3. API looks up the worker's employee GUID from `employees.json`
4. API scans `labor_shifts_detailed_daily.csv` for shifts on that date
5. API extracts job titles and maps them to bucket IDs
6. Frontend displays **Detected Locations** with clickable buttons

### 3. Example API Response

```json
{
  "suggested_buckets": [
    {
      "id": "am_bar",
      "name": "AM Bar",
      "job_title": "AM Sunset Server",
      "hours": 2.89
    },
    {
      "id": "sunset",
      "name": "Sunset Bar",
      "job_title": "PM Sunset Server",
      "hours": 4.52
    }
  ],
  "existing_record": {
    "server": "Sheryl Moore",
    "date": "2025-12-10",
    "bucket": "sunset",
    "cash_tips": 20.0,
    "non_cash_tips": 46.0,
    ...
  }
}
```

### 4. User Interface

When a worker has shifts on the selected date:
- **Detected Locations** section appears
- Shows buttons for each location with job title and hours worked
- User clicks a location button to auto-select it in the dropdown
- Then enters tip amounts for that specific location

Example:
```
Detected Locations from Shifts:
[AM Bar] (AM Sunset Server, 2.89h)  [Sunset Bar] (PM Sunset Server, 4.52h)

Click a location above to auto-select it, or choose manually from the dropdown.
```

### 5. Multiple Locations

If a worker worked at multiple locations (e.g., AM Bar and Sunset Bar), the user can:
1. Select the first location and enter tips
2. Save/Push to payouts
3. Select the second location and enter tips
4. Save/Push again

This matches the workflow from the old application.

## API Endpoints

### Get Suggested Buckets
```
GET /api/workers/{name}/suggested-buckets?date=YYYY-MM-DD
```

Returns list of locations where the worker worked on the given date.

### Get Server Tips (includes suggested buckets)
```
GET /api/server-tips?worker={name}&date=YYYY-MM-DD&bucket={bucket}
```

Returns both suggested buckets and any existing tip record.

## Testing

Test with Sheryl Moore on 2025-12-10:
```bash
curl "http://localhost:5000/api/workers/Sheryl%20Moore/suggested-buckets?date=2025-12-10"
```

Expected: Both AM Bar and Sunset Bar

Test with Jordan Bailey on 2025-12-12:
```bash
curl "http://localhost:5000/api/workers/Jordan%20Bailey/suggested-buckets?date=2025-12-12"
```

Expected: Empty (Jordan is a Cook, not a server)
