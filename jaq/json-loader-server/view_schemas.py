#!/usr/bin/env python3
"""
Extract sample records from each source file and display their JSON schema/structure.
"""

import sqlite3
import json
from collections import OrderedDict

DB_PATH = "./database.db"


def infer_schema(obj, path=""):
    """Recursively infer the schema of a JSON object."""
    if obj is None:
        return "null"
    elif isinstance(obj, bool):
        return "boolean"
    elif isinstance(obj, int):
        return "integer"
    elif isinstance(obj, float):
        return "number"
    elif isinstance(obj, str):
        return "string"
    elif isinstance(obj, list):
        if not obj:
            return ["empty array"]
        # Show schema of first item as representative
        return [infer_schema(obj[0], path + "[]")]
    elif isinstance(obj, dict):
        result = OrderedDict()
        for key, value in sorted(obj.items()):
            result[key] = infer_schema(value, path + "." + key)
        return result
    else:
        return "unknown"


def simplify_schema(schema, max_examples=3):
    """Simplify schema for display - truncate long arrays, etc."""
    if isinstance(schema, dict):
        result = OrderedDict()
        for key, value in schema.items():
            result[key] = simplify_schema(value, max_examples)
        return result
    elif isinstance(schema, list):
        if not schema:
            return []
        return [simplify_schema(schema[0], max_examples)]
    else:
        return schema


def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get distinct source files
    cursor.execute("SELECT DISTINCT source_file FROM json_objects ORDER BY source_file")
    source_files = [row[0] for row in cursor.fetchall()]
    
    print("=" * 80)
    print("JSON SCHEMA EXPLORER")
    print("=" * 80)
    print(f"Database: {DB_PATH}")
    print(f"Found {len(source_files)} distinct source file(s)")
    print()
    
    for source_file in source_files:
        print("-" * 80)
        print(f"SOURCE: {source_file}")
        print("-" * 80)
        
        # Get 2 sample records
        cursor.execute(
            "SELECT json_data FROM json_objects WHERE source_file = ? LIMIT 2",
            (source_file,)
        )
        samples = cursor.fetchall()
        
        for i, (json_data,) in enumerate(samples, 1):
            try:
                data = json.loads(json_data)
                print(f"\n--- Sample Record {i} ---")
                
                # Show raw JSON (pretty printed, truncated if too long)
                raw_json = json.dumps(data, indent=2, ensure_ascii=False)
                lines = raw_json.split('\n')
                if len(lines) > 50:
                    lines = lines[:50] + ['... (truncated)']
                print('\n'.join(lines))
                
                # Show inferred schema
                print(f"\n--- Schema for Record {i} ---")
                schema = infer_schema(data)
                simplified = simplify_schema(schema)
                print(json.dumps(simplified, indent=2, ensure_ascii=False))
                
            except json.JSONDecodeError as e:
                print(f"  ERROR: Invalid JSON - {e}")
            except Exception as e:
                print(f"  ERROR: {e}")
        
        print()
    
    conn.close()
    print("=" * 80)
    print("Done!")


if __name__ == "__main__":
    main()
