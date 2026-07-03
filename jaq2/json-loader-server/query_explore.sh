#!/bin/bash

# JAQ JSON Loader - Explore All Available Fields
# Shows all fields from both datasets for exploration
# Usage: ./query_explore.sh [mpn_filter]

API_BASE="${API_BASE:-http://localhost:3000}"
MPN_FILTER="${1:-}"

echo "Exploring all available fields from joined datasets"
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

# Query with all fields
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
  "select": [
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
    {"expr": "join1.variants.sku", "alias": "variant_sku"},
    {"expr": "join1.variants.barcode", "alias": "variant_barcode"},
    {"expr": "join1.variants.price", "alias": "variant_price"},
    {"expr": "join1.variants.inventoryQuantity", "alias": "variant_inventory"},
    {"expr": "join1.variants.id", "alias": "variant_id"}
  ],
  "limit": 3
}
EOF
)

# Escape for JSON string
ESCAPED_QUERY=$(echo "$JSON_QUERY" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()), end='')")

# Build request body
REQUEST_BODY="{\"query\": $ESCAPED_QUERY}"

echo "Executing query with all available fields..."
echo ""

curl -s -X POST "$API_BASE/query/dsl" \
  -H "Content-Type: application/json" \
  -d "$REQUEST_BODY" | python3 -m json.tool

echo ""
echo "=== AVAILABLE FIELDS REFERENCE ==="
echo ""
echo "GMC Fields (prefix: 'primary.'):"
echo "  - primary.offerId"
echo "  - primary.variantId"
echo "  - primary.title"
echo "  - primary.mpn"
echo "  - primary.gtin"
echo "  - primary.imageLink"
echo ""
echo "Shopify Product Fields (prefix: 'join1.'):"
echo "  - join1.id"
echo "  - join1.handle"
echo "  - join1.title"
echo "  - join1.status"
echo "  - join1.vendor"
echo "  - join1.productType"
echo "  - join1.createdAt"
echo "  - join1.updatedAt"
echo "  - join1.images (array)"
echo ""
echo "Shopify Variant Fields (prefix: 'join1.variants.'):"
echo "  - join1.variants.sku"
echo "  - join1.variants.barcode"
echo "  - join1.variants.price"
echo "  - join1.variants.inventoryQuantity"
echo "  - join1.variants.id"
