#!/bin/bash
# Script to run DSL queries against the JAQ JSON Loader server
# Usage: ./run_dsl_query.sh <query_file.dsl.json>

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DSL_DIR="$(dirname "$SCRIPT_DIR")"
QUERIES_DIR="$DSL_DIR/queries"
OUTPUTS_DIR="$DSL_DIR/outputs"

# Create outputs directory if it doesn't exist
mkdir -p "$OUTPUTS_DIR"

# Check if query file is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <query_file.dsl.json>"
    echo ""
    echo "Available queries:"
    ls -1 "$QUERIES_DIR"/*.dsl.json 2>/dev/null | while read f; do
        basename "$f"
    done
    exit 1
fi

QUERY_FILE="$1"

# If just a filename is provided, look in queries directory
if [ ! -f "$QUERY_FILE" ]; then
    QUERY_FILE="$QUERIES_DIR/$1"
fi

if [ ! -f "$QUERY_FILE" ]; then
    echo "Error: Query file not found: $1"
    exit 1
fi

# Extract the query name for output file
QUERY_BASENAME=$(basename "$QUERY_FILE" .dsl.json)
OUTPUT_FILE="$OUTPUTS_DIR/${QUERY_BASENAME}.csv"

echo "=========================================="
echo "Running DSL Query: $QUERY_BASENAME"
echo "=========================================="

# Read the query file and extract just the query part
QUERY_JSON=$(cat "$QUERY_FILE")

# Check if the query has a "query" wrapper or is the query itself
if echo "$QUERY_JSON" | jq -e '.query' > /dev/null 2>&1; then
    # Extract the query part
    DSL_QUERY=$(echo "$QUERY_JSON" | jq -c '.query')
    DESCRIPTION=$(echo "$QUERY_JSON" | jq -r '._description // "No description"')
    CSV_SOURCE=$(echo "$QUERY_JSON" | jq -r '._csv_source // "N/A"')
else
    DSL_QUERY="$QUERY_JSON"
    DESCRIPTION="Direct query"
    CSV_SOURCE="N/A"
fi

echo "Description: $DESCRIPTION"
echo "CSV Source: $CSV_SOURCE"
echo ""

# Execute the query via curl
echo "Executing query..."
RESPONSE=$(curl -s -X POST http://localhost:3000/query/dsl \
    -H "Content-Type: application/json" \
    -d "{\"query\": $(echo "$DSL_QUERY" | jq -c . | jq -R .)}" 2>&1)

# Check for errors
if echo "$RESPONSE" | jq -e '.error' > /dev/null 2>&1; then
    echo "ERROR: Query failed"
    echo "$RESPONSE" | jq .
    exit 1
fi

# Check if successful
if echo "$RESPONSE" | jq -e '.success' > /dev/null 2>&1; then
    ROW_COUNT=$(echo "$RESPONSE" | jq '.rows | length')
    echo "Query successful! Retrieved $ROW_COUNT rows"
    
    # Save to CSV using the export endpoint
    echo "Exporting to CSV: $OUTPUT_FILE"
    
    curl -s -X POST http://localhost:3000/export \
        -H "Content-Type: application/json" \
        -d "{\"query\": $(echo "$DSL_QUERY" | jq -c . | jq -R .), \"format\": \"csv\", \"filename\": \"${QUERY_BASENAME}\"}" \
        -o "$OUTPUT_FILE"
    
    if [ -f "$OUTPUT_FILE" ]; then
        echo "CSV saved successfully"
        echo "Preview (first 10 lines):"
        head -10 "$OUTPUT_FILE"
        echo ""
        echo "Full output: $OUTPUT_FILE"
    else
        echo "Warning: CSV file was not created"
    fi
else
    echo "Unexpected response:"
    echo "$RESPONSE" | jq .
fi

echo "=========================================="
