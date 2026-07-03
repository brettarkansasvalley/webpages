#!/bin/bash

# JAQ JSON Loader Query Script
# Usage: ./query.sh [limit]

API_BASE="${API_BASE:-http://localhost:3000}"
LIMIT="${1:-10}"

curl -s -X POST "$API_BASE/query/dsl" \
  -H "Content-Type: application/json" \
  -d "{
    \"query\": \"{\\\"from\\\": {\\\"source_file\\\": \\\"gmc_zucker_products.json\\\", \\\"alias\\\": \\\"primary\\\"}, \\\"joins\\\": [{\\\"source\\\": {\\\"source_file\\\": \\\"shopify_zucker_products.json\\\", \\\"alias\\\": \\\"join1\\\"}, \\\"on\\\": {\\\"left\\\": \\\"primary.mpn\\\", \\\"right\\\": \\\"join1.variants[].sku\\\"}, \\\"join_type\\\": \\\"inner\\\"}], \\\"where\\\": [{\\\"field\\\": \\\"primary.mpn\\\", \\\"op\\\": \\\"!=\\\", \\\"value\\\": \\\"\\\"}], \\\"select\\\": [{\\\"expr\\\": \\\"primary.title\\\", \\\"alias\\\": \\\"Title\\\"}, {\\\"expr\\\": \\\"primary.mpn\\\", \\\"alias\\\": \\\"MPN\\\"}, {\\\"expr\\\": \\\"join1.variants.barcode\\\", \\\"alias\\\": \\\"barcode\\\"}, {\\\"expr\\\": \\\"join1.title\\\", \\\"alias\\\": \\\"ShopifyTitle\\\"}], \\\"flatten\\\": false, \\\"limit\\\": $LIMIT}\"
  }" | python3 -m json.tool 2>/dev/null || curl -s -X POST "$API_BASE/query/dsl" \
  -H "Content-Type: application/json" \
  -d "{
    \"query\": \"{\\\"from\\\": {\\\"source_file\\\": \\\"gmc_zucker_products.json\\\", \\\"alias\\\": \\\"primary\\\"}, \\\"joins\\\": [{\\\"source\\\": {\\\"source_file\\\": \\\"shopify_zucker_products.json\\\", \\\"alias\\\": \\\"join1\\\"}, \\\"on\\\": {\\\"left\\\": \\\"primary.mpn\\\", \\\"right\\\": \\\"join1.variants[].sku\\\"}, \\\"join_type\\\": \\\"inner\\\"}], \\\"where\\\": [{\\\"field\\\": \\\"primary.mpn\\\", \\\"op\\\": \\\"!=\\\", \\\"value\\\": \\\"\\\"}], \\\"select\\\": [{\\\"expr\\\": \\\"primary.title\\\", \\\"alias\\\": \\\"Title\\\"}, {\\\"expr\\\": \\\"primary.mpn\\\", \\\"alias\\\": \\\"MPN\\\"}, {\\\"expr\\\": \\\"join1.variants.barcode\\\", \\\"alias\\\": \\\"barcode\\\"}, {\\\"expr\\\": \\\"join1.title\\\", \\\"alias\\\": \\\"ShopifyTitle\\\"}], \\\"flatten\\\": false, \\\"limit\\\": $LIMIT}\"
  }"
