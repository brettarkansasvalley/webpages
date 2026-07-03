#!/usr/bin/env python3
"""
Advanced import script to upsert data from workers.csv and worker_roles.csv.
It will update assignments for workers in the list and add new workers/roles.
"""
import sqlite3
import csv
import os
from config import DATABASE_FILE

# --- NEW: Define CSV filenames ---
WORKERS_CSV_FILE = 'workers.csv'
ROLES_CSV_FILE = 'worker_roles.csv'

def parse_combined_role(combined_role):
    """
    Parses a combined role string (e.g., "AM Server") and returns a list of tuples,
    each containing the generic role and the corresponding bucket name.
    """
    role_map = {
        'Server': 'Server', 'Bar': 'Bartender', 'Busser': 'Busser',
        'Expo': 'Expo', 'Runner': 'Runner'
    }
    
    generic_role = "Unknown"
    for key, value in role_map.items():
        if key in combined_role:
            generic_role = value
            break
            
    assignments = []
    if "EW/WW" in combined_role:
        assignments.append({'role': generic_role, 'bucket': 'eastwing'})
        assignments.append({'role': generic_role, 'bucket': 'westwing'})
    elif "AM" in combined_role:
        assignments.append({'role': generic_role, 'bucket': 'am_bar'})
    elif "EW" in combined_role:
        assignments.append({'role': generic_role, 'bucket': 'eastwing'})
    elif "WW" in combined_role:
        assignments.append({'role': generic_role, 'bucket': 'westwing'})
    elif "Sunset" in combined_role:
        assignments.append({'role': generic_role, 'bucket': 'sunset'})
    elif "West Wing Bar" in combined_role:
         assignments.append({'role': 'Bartender', 'bucket': 'westwing'})

    return assignments


def upsert_data_from_csv():
    """
    Connects to the database and upserts data from CSV files.
    """
    # --- MODIFIED: Check for file existence ---
    if not os.path.exists(WORKERS_CSV_FILE) or not os.path.exists(ROLES_CSV_FILE):
        print(f"Error: Make sure '{WORKERS_CSV_FILE}' and '{ROLES_CSV_FILE}' exist in the same directory.")
        return

    all_workers = set()
    all_roles = set()

    # --- NEW: Read from workers.csv ---
    print(f"Reading data from {WORKERS_CSV_FILE}...")
    with open(WORKERS_CSV_FILE, mode='r', encoding='utf-8') as infile:
        reader = csv.reader(infile)
        next(reader, None) # Skip header
        for row in reader:
            if row:
                all_workers.add(row[0].strip())

    # --- NEW: Read from worker_roles.csv ---
    print(f"Reading data from {ROLES_CSV_FILE}...")
    with open(ROLES_CSV_FILE, mode='r', encoding='utf-8') as infile:
        reader = csv.reader(infile)
        next(reader, None) # Skip header
        for row in reader:
            if not row or len(row) < 2:
                continue
            worker_name, combined_role = row
            worker_name = worker_name.strip()
            
            all_workers.add(worker_name)
            parsed_assignments = parse_combined_role(combined_role.strip())
            for assignment in parsed_assignments:
                generic_role = assignment['role']
                all_roles.add((worker_name, generic_role))
    
    print(f"Found {len(all_workers)} total unique workers from files.")

    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        print("Adding/Updating workers...")
        worker_list = [(name,) for name in sorted(list(all_workers))]
        cursor.executemany("INSERT OR IGNORE INTO workers (name) VALUES (?)", worker_list)

        # --- MODIFIED: Full role synchronization logic ---
        workers_in_csv = {name for name, role in all_roles}
        
        if workers_in_csv:
            print(f"Synchronizing roles for {len(workers_in_csv)} workers found in the CSV...")
            
            # Step 1: Delete all existing roles for these specific workers
            placeholders = ', '.join('?' * len(workers_in_csv))
            cursor.execute(f"DELETE FROM worker_roles WHERE worker_name IN ({placeholders})", sorted(list(workers_in_csv)))
            print(f"  - Old roles removed for workers in CSV.")

            # Step 2: Insert the new roles as specified in the CSV
            role_list = [(name, role, f"{name}_{role}") for name, role in sorted(list(all_roles))]
            cursor.executemany("INSERT OR IGNORE INTO worker_roles (worker_name, role, worker_role_key) VALUES (?, ?, ?)", role_list)
            print(f"  - {len(role_list)} new roles from the CSV have been inserted.")
        else:
            print("No roles found in CSV to update.")
        
        conn.commit()
        print("\nRole synchronization complete!")
        print("Worker assignments must be managed from within the application.")

    except sqlite3.Error as e:
        print(f"\nAn error occurred: {e}")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    answer = input("This will add/update workers and SYNCHRONIZE roles from CSV files. Are you sure? (y/n): ")
    if answer.lower() == 'y':
        upsert_data_from_csv()
    else:
        print("Operation cancelled.")