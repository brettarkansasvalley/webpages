import json
import sqlite3
import os

def sync_employees_and_roles():
    # Define paths
    db_path = '/home/ubuntu/jbhooks1/jbhooks/tip_distribution.db'
    # Corrected path to the webapp data directory
    json_data_path = '/home/ubuntu/toast/webapp/data'
    employees_file = os.path.join(json_data_path, 'employees.json')
    jobs_file = os.path.join(json_data_path, 'jobs.json')

    # Check if JSON files exist
    if not os.path.exists(employees_file) or not os.path.exists(jobs_file):
        print(f"Error: JSON files not found in {json_data_path}")
        return

    # Load JSON data
    with open(employees_file, 'r') as f:
        employees = json.load(f)
    with open(jobs_file, 'r') as f:
        jobs = json.load(f)

    # Create a job title lookup map
    job_map = {job['guid']: job['title'] for job in jobs}

    # Connect to the database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("Syncing employees and roles...")

    for employee in employees:
        if not employee.get('firstName') or not employee.get('lastName'):
            continue

        full_name = f"{employee['firstName']} {employee['lastName']}"

        # --- Sync workers table ---
        try:
            cursor.execute("INSERT OR IGNORE INTO workers (name) VALUES (?)", (full_name,))
            if cursor.rowcount > 0:
                print(f"Added new worker: {full_name}")
        except sqlite3.IntegrityError:
            # This handles cases where the name might already exist, though OR IGNORE should prevent this.
            print(f"Worker {full_name} already exists.")
            pass

        # --- Sync worker_roles table ---
        if 'wageOverrides' in employee and employee['wageOverrides']:
            for override in employee['wageOverrides']:
                job_guid = override.get('jobReference', {}).get('guid')
                if job_guid and job_guid in job_map:
                    role_title = job_map[job_guid]
                    worker_role_key = f"{full_name}_{role_title}"
                    try:
                        cursor.execute("INSERT OR IGNORE INTO worker_roles (worker_name, role, worker_role_key) VALUES (?, ?, ?)", 
                                       (full_name, role_title, worker_role_key))
                        if cursor.rowcount > 0:
                            print(f"Added role '{role_title}' for worker: {full_name}")
                    except sqlite3.IntegrityError:
                        # This handles cases where the worker_role_key might already exist.
                        pass

    # --- Add role aliases ---
    print("Adding role aliases...")
    aliases_to_add = []
    # Get all WW Server roles
    cursor.execute("SELECT worker_name FROM worker_roles WHERE role = 'WW Server'")
    ww_servers = cursor.fetchall()
    for row in ww_servers:
        aliases_to_add.append((row[0], 'Server', f"{row[0]}_Server"))

    # Get all EW/WW Expo roles
    cursor.execute("SELECT worker_name FROM worker_roles WHERE role = 'EW/WW Expo'")
    ew_expos = cursor.fetchall()
    for row in ew_expos:
        aliases_to_add.append((row[0], 'Expo', f"{row[0]}_Expo"))

    if aliases_to_add:
        cursor.executemany("INSERT OR IGNORE INTO worker_roles (worker_name, role, worker_role_key) VALUES (?, ?, ?)", aliases_to_add)
        print(f"Added {cursor.rowcount} new role aliases.")

    # Commit changes and close the connection
    conn.commit()
    conn.close()
    print("Sync and alias process complete.")

if __name__ == '__main__':
    sync_employees_and_roles()
