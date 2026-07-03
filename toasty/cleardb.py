import sqlite3

def clear_tables_except_workers(db_name):
    """
    Deletes all records from all tables in the specified SQLite database,
    except for the 'workers' table.

    Args:
        db_name (str): The name of the SQLite database file.
    """
    try:
        # Connect to the SQLite database
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()

        # Get a list of all tables in the database
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()

        # Iterate over the tables and delete records from each, except 'workers'
        for table_name in tables:
            table_name = table_name[0]
            if table_name != 'workers' and table_name != 'sqlite_sequence': # Also exclude sqlite_sequence which is used for autoincrementing keys
                print(f"Deleting records from {table_name}...")
                cursor.execute(f"DELETE FROM {table_name};")

        # Commit the changes and close the connection
        conn.commit()
        print("All specified tables have been cleared.")

    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    # Replace 'tip_distribution.db' with the actual path to your database if it's in a different directory
    clear_tables_except_workers('tip_distribution.db')
