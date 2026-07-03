#!/usr/bin/env python3
"""
Process newly fetched Toast data:
1. Generate labor_shifts_detailed_daily.csv from time entries
2. Create summary reports
"""
import json
import csv
from pathlib import Path
from datetime import datetime
from collections import defaultdict

DATA_DIR = Path("/home/ubuntu/new_toasty/toasty/data/raw")
REPORTS_DIR = Path("/home/ubuntu/new_toasty/toasty/data/reports")

def load_employees():
    """Load employee data to map GUIDs to names."""
    emp_file = DATA_DIR / "employees.json"
    if not emp_file.exists():
        return {}
    
    with open(emp_file) as f:
        employees = json.load(f)
    
    emp_map = {}
    for emp in employees:
        guid = emp.get('guid') or emp.get('v2EmployeeGuid')
        if guid:
            first = emp.get('firstName', '')
            last = emp.get('lastName', '')
            name = f"{first} {last}".strip()
            emp_map[guid] = {
                'name': name,
                'firstName': first,
                'lastName': last
            }
    return emp_map

def load_jobs():
    """Create job GUID to name mapping from existing shifts."""
    job_map = {}
    
    # First, try to get jobs from existing CSV
    csv_file = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
    if csv_file.exists():
        with open(csv_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                job_guid = row.get('job_guid')
                job_title = row.get('job_title')
                if job_guid and job_title:
                    job_map[job_guid] = job_title
    
    # Add common job mappings
    job_map.update({
        '31de905c-e56d-4714-a17e-cfc977a595d8': 'Cleaning - Server',
        '29347321-8fa3-4eaf-a32c-9398bee4a20a': 'AM Sunset Server',
        'dc5e1a38-b6fd-4977-b88a-80f549aecfcb': 'PM Sunset Server',
        '265fabfa-f8ad-48e1-971d-0748dcada2a6': 'WW Server',
        '11bf4a1c-c723-45c5-9305-fd3a40d21c09': 'EW Server',
        '988657a1-20b5-450b-b645-4b0f6bee1e31': 'AM Bar Sunset',
        'badb9547-f9cb-46d6-9160-6e3b559b4607': 'PM Bar Sunset',
        '571df9d9-4906-4cff-be63-1998c696768d': 'Prep Cook',
        '1ce9c501-3832-4e70-a53c-f6fc19deb64f': 'Cook',
        'a2a6f80a-9ad1-448d-b378-9f0f066be1ef': 'Office Manager',
        '362a58ff-dc1b-4de8-b863-4e5b34c62f20': 'Hostess',
        '6bd66ea1-b944-4592-8bc4-0027cb863cb7': 'Bar Manager',
        '036fc23f-fcc1-40c9-af52-d5a88e3290da': 'Assistant Manager',
        '0361b72e-9722-4926-93fe-93324ca73bfc': 'Busser',
        '4e8ef5d5-8d69-449f-96e4-9c6dc0e7051d': 'Chef',
        'c707bc9a-31f6-415f-a0bb-7ac5adfdd9c7': 'Dishwasher',
        '635e5ed5-3211-44dd-a1ff-3e228294e1f8': 'Shift Manager',
    })
    
    return job_map

def process_time_entries():
    """Process all time entry files and generate labor_shifts_detailed_daily.csv."""
    emp_map = load_employees()
    job_map = load_jobs()
    
    # Read existing CSV to preserve old data
    existing_shifts = []
    csv_file = REPORTS_DIR / "labor_shifts_detailed_daily.csv"
    
    if csv_file.exists():
        with open(csv_file) as f:
            reader = csv.DictReader(f)
            existing_shifts = list(reader)
        print(f"Loaded {len(existing_shifts)} existing shifts")
    
    # Process new time entry files
    new_shifts = []
    time_entries_dir = DATA_DIR / "time_entries"
    
    # Track which dates we already have data for
    existing_dates = set(s['date'] for s in existing_shifts)
    print(f"Existing dates: {len(existing_dates)}")
    
    for entry_file in sorted(time_entries_dir.glob("*.json")):
        date_str = entry_file.stem  # YYYY-MM-DD
        
        # Skip if we already have data for this date
        if date_str in existing_dates:
            continue
        
        with open(entry_file) as f:
            entries = json.load(f)
        
        if len(entries) > 0:
            print(f"Processing {date_str}: {len(entries)} time entries")
        
        for entry in entries:
            # Get employee info - new format uses employeeReference
            emp_ref = entry.get('employeeReference', {})
            if isinstance(emp_ref, dict):
                emp_guid = emp_ref.get('guid')
            else:
                emp_guid = None
            
            if not emp_guid:
                continue
            
            emp_info = emp_map.get(emp_guid, {})
            emp_name = emp_info.get('name', 'Unknown')
            
            # Get job info - new format uses jobReference
            job_ref = entry.get('jobReference', {})
            if isinstance(job_ref, dict):
                job_guid = job_ref.get('guid')
            else:
                job_guid = None
            
            job_title = job_map.get(job_guid, 'Unknown')
            
            # Parse times
            in_date = entry.get('inDate', '')
            out_date = entry.get('outDate', '')
            
            # Calculate hours
            regular_hours = float(entry.get('regularHours', 0) or 0)
            
            # Skip if deleted
            if entry.get('deleted', False):
                continue
            
            shift = {
                'date': date_str,
                'employee_guid': emp_guid,
                'employee_name': emp_name,
                'job_guid': job_guid or '',
                'job_title': job_title,
                'start_time_utc': in_date,
                'end_time_utc': out_date,
                'hours': regular_hours
            }
            new_shifts.append(shift)
    
    print(f"Total new shifts: {len(new_shifts)}")
    
    # Combine existing and new
    all_shifts = existing_shifts + new_shifts
    
    print(f"Total combined shifts: {len(all_shifts)}")
    
    # Write updated CSV
    fieldnames = ['date', 'employee_guid', 'employee_name', 'job_guid', 'job_title', 
                  'start_time_utc', 'end_time_utc', 'hours']
    
    with open(csv_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_shifts)
    
    print(f"Saved to {csv_file}")
    return all_shifts

def generate_dates_csv():
    """Generate a CSV with all available dates."""
    orders_dir = DATA_DIR / "orders"
    dates = sorted([f.stem for f in orders_dir.glob("*.json")])
    
    csv_file = REPORTS_DIR / "available_dates.csv"
    with open(csv_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date'])
        for d in dates:
            writer.writerow([d])
    
    print(f"Saved {len(dates)} dates to {csv_file}")
    return dates

def main():
    print("=" * 60)
    print("Processing New Toast Data")
    print("=" * 60)
    
    # Process time entries into shifts CSV
    print("\n--- Processing Time Entries ---")
    process_time_entries()
    
    # Generate dates CSV
    print("\n--- Generating Dates List ---")
    dates = generate_dates_csv()
    
    print("\n" + "=" * 60)
    print("Processing Complete!")
    print(f"Total dates available: {len(dates)}")
    print("=" * 60)

if __name__ == "__main__":
    main()
