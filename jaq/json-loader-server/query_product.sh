#!/bin/bash

# Query a specific product by MPN/SKU
# Usage: ./query_product.sh <sku>

API_BASE="${API_BASE:-http://localhost:3000}"

if [ -z "$1" ]; then
    echo "Usage: $0 <sku/mpn>"
    echo "Example: $0 WG-OST-BIRD--OWL"
    exit 1
fi

SKU="$1"

# Build the JSON query
JSON_QUERY=$(printf '{
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
  "where": [
    {
      "field": "primary.mpn",
      "op": "=",
      "value": "%s"
    }
  ],
  "select": [
    {
      "expr": "primary.title",
      "alias": "Title"
    },
    {
      "expr": "primary.mpn",
      "alias": "MPN"
    },
    {
      "expr": "join1.variants.barcode",
      "alias": "barcode"
    },
    {
      "expr": "join1.variants.price",
      "alias": "price"
    },
    {
      "expr": "join1.title",
      "alias": "ShopifyTitle"
    },
    {
      "expr": "join1.status",
      "alias": "Status"
    }
  ],
  "flatten": false,
  "limit": 10
}' "$SKU")

# Escape for JSON string
ESCAPED_QUERY=$(echo "$JSON_QUERY" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()), end='')")

# Build request body
REQUEST_BODY="{\"query\": $ESCAPED_QUERY}"

curl -s -X POST "$API_BASE/query/dsl" \
  -H "Content-Type: application/json" \
  -d "$REQUEST_BODY" | python3 -m json.tool
