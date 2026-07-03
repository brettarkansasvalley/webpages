# Calendar Feature

## Overview
The Calendar page provides a visual monthly calendar showing all dates with order data, and allows you to view all workers who worked on any given date.

## Features

### 1. Monthly Calendar View
- Displays a full month grid with days of the week
- Dates with order data are highlighted in blue
- Navigate between months with arrow buttons
- "Today" button to jump to current month

### 2. Date Selection
- Click any date with data to view workers for that day
- Selected date is highlighted in purple
- Shows the full date name (e.g., "Friday, December 12, 2025")

### 3. Workers List
When a date is selected, displays:
- Total number of workers for that day
- Each worker's card showing:
  - Name
  - Locations worked (AM Bar, Sunset Bar, West Wing, East Wing)
  - Job title(s) and hours per shift
  - Total hours for the day

### 4. Quick Actions
- **Filter workers**: Search by name, location, or job title
- **Click worker**: Navigate to Server Tips page with worker/date pre-filled
- **Assign Tips button**: Quick navigation to Server Tips with date pre-filled

## Data Sources

### Available Dates
The calendar gets dates from:
- JAQ Server: `orders_full_YYYYMMDD.json` files
- Local files: `/data/raw/orders/YYYY-MM-DD.json` files

### Workers for Date
The workers list comes from:
- `labor_shifts_detailed_daily.csv`
- Filters out "Cleaning - Server" shifts (not real serving shifts)
- Maps job titles to locations using the same logic as the old app

## Job Title → Location Mapping

| Job Title | Location |
|-----------|----------|
| AM Sunset Server | AM Bar |
| PM Sunset Server | Sunset Bar |
| WW Server | West Wing |
| EW Server | East Wing |
| AM Bar Sunset | AM Bar |
| PM Bar Sunset | Sunset Bar |
| WW Bar | West Wing |

## API Endpoints

### Get Available Dates
```
GET /api/dates
```
Returns: `["2025-08-14", "2025-08-15", ...]`

### Get Workers for Date
```
GET /api/dates/{YYYY-MM-DD}/workers
```
Returns:
```json
[
  {
    "name": "Sheryl Moore",
    "locations": ["Sunset Bar"],
    "shifts": [
      {
        "job_title": "PM Sunset Server",
        "hours": 6.74,
        "location": "Sunset Bar",
        "start_time": "2025-12-12T20:45:33...",
        "end_time": "2025-12-12T03:30:00..."
      }
    ],
    "total_hours": 6.74
  }
]
```

## Example Usage

1. Navigate to **Calendar** page
2. Click on a date with blue highlighting (e.g., Dec 12, 2025)
3. See all 48 workers who worked that day
4. Filter by typing "server" to see only servers
5. Click on "Sheryl Moore" to go to Server Tips with her info pre-filled

## Integration with Server Tips

When you click a worker from the calendar:
1. Worker name is pre-selected
2. Date is pre-filled
3. Location suggestions are automatically detected from shifts
4. Existing tips data (if any) is loaded

This creates a seamless workflow:
```
Calendar → Select Date → View Workers → Click Worker → Enter Tips
```
