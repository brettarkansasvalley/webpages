#!/bin/bash

# JAQ JSON Loader - Query All Fields Script
# Returns all columns from both joined datasets
# Usage: ./query_all.sh [limit] [mpn_filter]

API_BASE="${API_BASE:-http://localhost:3000}"
LIMIT="${1:-10000}"
MPN_FILTER="${2:-}"

# Build WHERE clause
if [ -n "$MPN_FILTER" ]; then
    WHERE_CLAUSE="[{\"field\": \"primary.mpn\", \"op\": \"=\", \"value\": \"$MPN_FILTER\"}]"
else
    WHERE_CLAUSE="[{\"field\": \"primary.mpn\", \"op\": \"!=\", \"value\": \"\"}]"
fi

# Build comprehensive SELECT - all fields from both sources
SELECT_FIELDS='[
    {"expr": "primary.offerId", "alias": "gmc_offerId"},
    {"expr": "primary.variantId", "alias": "gmc_variantId"},
    {"expr": "primary.title", "alias": "gmc_title"},
    {"expr": "primary.mpn", "alias": "gmc_mpn"},
    {"expr": "primary.gtin", "alias": "gmc_gtin"},
    {"expr": "primary.imageLink", "alias": "gmc_imageLink"},
    {"expr": "join1.id", "alias": "shopify_id"},
    {"expr": "join1.handle", "alias": "shopify_handle"},
    {"expr": "join1.title", "alias": "shopify_title"},
    {"expr": "join1.status", "alias": "shopify_status"},
    {"expr": "join1.vendor", "alias": "shopify_vendor"},
    {"expr": "join1.productType", "alias": "shopify_productType"},
    {"expr": "join1.createdAt", "alias": "shopify_createdAt"},
    {"expr": "join1.updatedAt", "alias": "shopify_updatedAt"},
    {"expr": "join1.variants.sku", "alias": "shopify_sku"},
    {"expr": "join1.variants.barcode", "alias": "shopify_barcode"},
    {"expr": "join1.variants.price", "alias": "shopify_price"},
    {"expr": "join1.variants.inventoryQuantity", "alias": "shopify_inventory"}
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
ESCAPED_QUERY=$(echo "$JSON_QUERY" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()), end='')")

# Build request body
REQUEST_BODY="{\"query\": $ESCAPED_QUERY}"


curl -s -X POST "$API_BASE/query/dsl" \
  -H "Content-Type: application/json" \
  -d "$REQUEST_BODY" | python3 -m json.tool
