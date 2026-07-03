#!/usr/bin/env python3
"""
Sync Toast data from raw directories to JAQ data lake.
"""
import json
import shutil
from pathlib import Path
import sys
import urllib.request

RAW_DATA_DIR = Path("/home/ubuntu/new_toasty/toasty/data/raw")
JAQ_DIR = Path("/home/ubuntu/jaq/loadjson")

def sync_all_dates(start_date=None, end_date=None):
    synced_count = 0
    
    mappings = [
        ("orders", "orders_full_{}.json"),
        ("time_entries", "labor_v1_timeEntries_{}.json"),
        ("shifts", "shifts_{}.json"),
    ]
    
    for subdir, template in mappings:
        src_dir = RAW_DATA_DIR / subdir
        if not src_dir.exists():
            continue
            
        for f in sorted(src_dir.glob("*.json")):
            date_str = f.stem
            date_clean = date_str.replace("-", "")
            
            if start_date and date_str < start_date:
                continue
            if end_date and date_str > end_date:
                continue
            
            try:
                with open(f) as fp:
                    data = json.load(fp)
                    if not data:
                        continue
            except:
                continue
            
            dest = JAQ_DIR / template.format(date_clean)
            shutil.copy2(f, dest)
            print(f"  {template.format(date_clean)}")
            synced_count += 1
    
    # Cash entries
    cash_dir = RAW_DATA_DIR / "cash"
    if cash_dir.exists():
        for f in sorted(cash_dir.glob("entries_*.json")):
            date_str = f.stem.replace("entries_", "")
            date_clean = date_str.replace("-", "")
            
            if start_date and date_str < start_date:
                continue
            if end_date and date_str > end_date:
                continue
            
            try:
                with open(f) as fp:
                    data = json.load(fp)
                    if not data:
                        continue
            except:
                continue
            
            dest = JAQ_DIR / f"cash_entries_{date_clean}.json"
            shutil.copy2(f, dest)
            print(f"  cash_entries_{date_clean}.json")
            synced_count += 1
    
    return synced_count

def reload_jaq():
    try:
        req = urllib.request.Request("http://localhost:3000/load", method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            return {"success": True, "message": f"JAQ: {data.get('total_objects', 0)} objects loaded"}
    except Exception as e:
        return {"success": False, "message": f"JAQ reload failed: {e}"}

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--date" and len(sys.argv) > 2:
        date_str = sys.argv[2]
        print(f"Syncing data for {date_str}...")
        count = sync_all_dates(start_date=date_str, end_date=date_str)
    else:
        print("Syncing all data to JAQ...")
        count = sync_all_dates()
    
    print(f"\nSynced {count} files")
    print("\nReloading JAQ...")
    result = reload_jaq()
    print(result["message"])
    return 0 if result["success"] else 1

if __name__ == "__main__":
    sys.exit(main())
