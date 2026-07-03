#!/bin/bash

# JAQ JSON Loader - Query Raw JSON Objects
# Returns full JSON objects from both joined sources
# Usage: ./query_raw.sh [limit] [mpn_filter]

API_BASE="${API_BASE:-http://localhost:3000}"
LIMIT="${1:-5}"
MPN_FILTER="${2:-}"

echo "Running query returning raw JSON objects"
echo "Limit: $LIMIT"
if [ -n "$MPN_FILTER" ]; then
    echo "MPN Filter: $MPN_FILTER"
fi
echo ""

# Build WHERE clause
if [ -n "$MPN_FILTER" ]; then
    WHERE_CLAUSE="[{\"field\": \"primary.mpn\", \"op\": \"=\", \"value\": \"$MPN_FILTER\"}]"
else
    WHERE_CLAUSE="[{\"field\": \"primary.mpn\", \"op\": \"!=\", \"value\": \"\"}]"
fi

# Select the entire JSON objects from both sources
SELECT_FIELDS='[
    {"expr": "primary", "alias": "gmc_data"},
    {"expr": "join1", "alias": "shopify_data"}
]'

# Build the full query
JSON_QUERY=$(cat <<EOF
{
  "from": {
    "source_file": "gmc_zucker_products.json",
    "alias": "primary"
  },
  "joins": [
    {
      "source": {
        "source_file": "shopify_zucker_products.json",
        "alias": "join1"
      },
      "on": {
        "left": "primary.mpn",
        "right": "join1.variants[].sku"
      },
      "join_type": "inner"
    }
  ],
  "where": $WHERE_CLAUSE,
  "select": $SELECT_FIELDS,
  "flatten": false,
  "limit": $LIMIT
}
EOF
)

# Escape for JSON string
ESCAPED_QUERY=$(echo "$JSON_QUERY" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()), end="")')

# Build request body
REQUEST_BODY="{\"query\": $ESCAPED_QUERY}"

echo "Executing query..."
echo ""

# Get response and output it
curl -s -X POST "$API_BASE/query/dsl" \
  -H "Content-Type: application/json" \
  -d "$REQUEST_BODY" | python3 -c '
import json
import sys

data = json.load(sys.stdin)
if not data.get("success"):
    print("Error:", data.get("error"))
    sys.exit(1)

print("Total matches:", data["total_count"])
print("Showing:", len(data["rows"]))
print()

for i, row in enumerate(data["rows"], 1):
    gmc = row[0] if len(row) > 0 else {}
    shopify = row[1] if len(row) > 1 else {}
    
    print("=== Record", i, "===")
    print("\nGMC Data (source_file: gmc_zucker_products.json):")
    print(json.dumps(gmc, indent=2))
    
    print("\nShopify Data (source_file: shopify_zucker_products.json):")
    print(json.dumps(shopify, indent=2))
    print("\n" + "=" * 60 + "\n")
'
