#!/usr/bin/env python3
"""
Load full order data from raw JSON files into the datalake.

This script reads order JSON files from /home/ubuntu/new_toasty/toasty/data/raw/orders/
and inserts them into the json-loader-server database.
"""

import json
import sqlite3
import os
from pathlib import Path
from datetime import datetime

# Configuration
RAW_ORDERS_DIR = "/home/ubuntu/new_toasty/toasty/data/raw/orders"
DB_PATH = "/home/ubuntu/jaq/json-loader-server/database.db"

def load_orders_file(filepath: str, db_conn: sqlite3.Connection) -> int:
    """Load a single orders JSON file into the database.
    
    Args:
        filepath: Path to the JSON file
        db_conn: SQLite connection
        
    Returns:
        Number of records inserted
    """
    filename = Path(filepath).name
    modified_at = int(os.path.getmtime(filepath))
    
    # Read the JSON file
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Handle both array and single object formats
    if isinstance(data, list):
        orders = data
    elif isinstance(data, dict):
        orders = [data]
    else:
        print(f"Warning: {filename} contains neither array nor object")
        return 0
    
    cursor = db_conn.cursor()
    inserted = 0
    
    for order in orders:
        if not isinstance(order, dict):
            continue
            
        # Extract business date from the order or filename
        business_date = order.get('businessDate')
        if not business_date:
            # Try to extract from filename (e.g., "2025-12-12.json")
            try:
                date_str = filename.replace('.json', '').replace('-', '')
                business_date = date_str
            except:
                business_date = 'unknown'
        
        # Create a unique source file name based on business date
        source_file = f"orders_full_{business_date}.json"
        
        # Convert order to JSON string
        json_data = json.dumps(order, separators=(',', ':'))
        
        try:
            cursor.execute(
                """INSERT OR IGNORE INTO json_objects (json_data, source_file, modified_at)
                   VALUES (?, ?, ?)""",
                (json_data, source_file, modified_at)
            )
            if cursor.rowcount > 0:
                inserted += 1
        except sqlite3.Error as e:
            print(f"Error inserting order: {e}")
    
    db_conn.commit()
    return inserted

def main():
    """Main entry point."""
    print(f"Loading orders from {RAW_ORDERS_DIR}")
    print(f"Database: {DB_PATH}")
    
    # Check if raw orders directory exists
    if not os.path.exists(RAW_ORDERS_DIR):
        print(f"Error: Directory not found: {RAW_ORDERS_DIR}")
        return 1
    
    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    
    try:
        # Get list of JSON files
        json_files = sorted([f for f in os.listdir(RAW_ORDERS_DIR) if f.endswith('.json')])
        
        print(f"Found {len(json_files)} JSON files")
        
        total_inserted = 0
        
        for filename in json_files:
            filepath = os.path.join(RAW_ORDERS_DIR, filename)
            print(f"Processing {filename}...", end=' ')
            
            try:
                inserted = load_orders_file(filepath, conn)
                total_inserted += inserted
                print(f"Inserted {inserted} orders")
            except Exception as e:
                print(f"Error: {e}")
        
        print(f"\nTotal orders inserted: {total_inserted}")
        
        # Show summary
        cursor = conn.cursor()
        cursor.execute("""
            SELECT source_file, COUNT(*) as count 
            FROM json_objects 
            WHERE source_file LIKE 'orders_full_%'
            GROUP BY source_file
            ORDER BY source_file
        """)
        
        print("\nOrders loaded by business date:")
        for row in cursor.fetchall():
            print(f"  {row[0]}: {row[1]} orders")
            
    finally:
        conn.close()
    
    return 0

if __name__ == "__main__":
    exit(main())
