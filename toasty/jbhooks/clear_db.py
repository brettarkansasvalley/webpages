#!/usr/bin/env python3
"""
This script clears the transactional tables from the database,
preserving the worker and assignment configurations.
"""
import sqlite3
from config import DATABASE_FILE

# List of tables to be cleared.
# These are the tables that store history and daily transactions.
TABLES_TO_CLEAR = [
    'servers',
    'bartenders',
    'payouts',
    'cashbox_ledger',
    'transactions',
    'worker_assignments'
]

def clear_transactional_data():
    """
    Connects to the database and executes the DELETE command 
    on each of the specified tables.
    """
    try:
        # Connect to the database file defined in config.py
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        print(f"Connected to the database: {DATABASE_FILE}")

        for table in TABLES_TO_CLEAR:
            print(f"Clearing data from table: {table}...", end="")
            # DELETE FROM is used to clear all records without dropping the table
            cursor.execute(f"DELETE FROM {table};")
            print(" Done!")

        # Commit the changes to the database
        conn.commit()
        print("\nCleanup complete. All transactional tables are now empty.")

    except sqlite3.Error as e:
        print(f"\nA database error occurred: {e}")

    finally:
        # Close the connection
        if conn:
            conn.close()
            print("Database connection closed.")

if __name__ == "__main__":
    # Ask the user for confirmation
    answer = input("Are you sure you want to delete all transactional data? (y/n): ")
    if answer.lower() == 'y':
        clear_transactional_data()
    else:
        print("Operation cancelled.")