#!/bin/bash
# Script to run all DSL queries

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUERIES_DIR="$(dirname "$SCRIPT_DIR")/queries"

echo "=========================================="
echo "Running All DSL Queries"
echo "=========================================="
echo ""

# Find all .dsl.json files and sort them
for query_file in $(ls -1 "$QUERIES_DIR"/*.dsl.json 2>/dev/null | sort); do
    basename=$(basename "$query_file")
    echo ""
    echo "------------------------------------------"
    echo "Processing: $basename"
    echo "------------------------------------------"
    
    # Run the query
    if ! "$SCRIPT_DIR/run_dsl_query.sh" "$query_file"; then
        echo "WARNING: Query $basename failed"
    fi
    
    echo ""
done

echo "=========================================="
echo "All queries completed"
echo "=========================================="
