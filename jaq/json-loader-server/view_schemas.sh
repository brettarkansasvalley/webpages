#!/bin/bash
# Quick schema viewer using sqlite3 and jq
# Shows 1-2 sample records from each source file with their structure

echo "sqlite3 database.db 'select distinct(source_file) from json_objects' -json"

sqlite3 database.db 'select distinct(source_file) from json_objects' -json


echo ""


DB_PATH="./database.db"

echo "================================================================================"
echo "JSON SCHEMA EXPLORER (Shell version - requires jq)"
echo "================================================================================"

# Check for jq
if ! command -v jq &> /dev/null; then
    echo "Error: jq is required but not installed. Install with: sudo apt-get install jq"
    exit 1
fi

# Get distinct source files
source_files=$(sqlite3 "$DB_PATH" "SELECT DISTINCT source_file FROM json_objects ORDER BY source_file")

echo "Found $(echo "$source_files" | wc -l) distinct source file(s)"
echo ""

# For each source file
while IFS= read -r source_file; do
    echo "--------------------------------------------------------------------------------"
    echo "SOURCE: $source_file"
    echo "--------------------------------------------------------------------------------"
    
    # Get 2 sample records
    sqlite3 "$DB_PATH" "SELECT json_data FROM json_objects WHERE source_file = '$source_file' LIMIT 2" | while IFS= read -r json_data; do
        echo ""
        echo "--- Sample Record ---"
        # Pretty print the JSON
        echo "$json_data" | jq . 2>/dev/null || echo "$json_data"
        echo ""
        echo "--- Keys (Schema Overview) ---"
        echo "$json_data" | jq 'keys' 2>/dev/null || echo "(unable to parse)"
    done
    
    echo ""
done <<< "$source_files"

echo "================================================================================"
echo "Done!"
