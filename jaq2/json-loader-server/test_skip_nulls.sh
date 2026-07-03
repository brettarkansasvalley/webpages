#!/bin/bash
# Test skip_nulls functionality

echo "=========================================="
echo "Testing skip_nulls DSL query"
echo "=========================================="

# The query with skip_nulls enabled
QUERY_OBJ='{"from":{"source_file":"shopify_feather_place_products.json","alias":"shopify"},"joins":[{"source":{"source_file":"gmc_feather_place_products.json","alias":"gmc"},"on":{"left":"shopify.variant.barcode","right":"gmc.gtin"},"join_type":"left","skip_nulls":true}],"select":[{"expr":"shopify.variant.barcode","alias":"Shopify_Barcode"},{"expr":"shopify.variant.sku","alias":"Shopify_SKU"},{"expr":"gmc.gtin","alias":"GMC_GTIN"},{"expr":"gmc.mpn","alias":"GMC_MPN"}],"limit":100000}'

# Build payload with query as string
PAYLOAD=$(jq -n --arg q "$QUERY_OBJ" '{query: $q, format: "json"}')

echo "Running query with skip_nulls: true"
echo ""

curl -s -X POST 'http://localhost:3000/query/dsl' \
  -H 'Content-Type: application/json' \
  -d "$PAYLOAD" | python3 -c "
import sys, json
data = json.load(sys.stdin)
rows = data.get('data', [])
total = len(rows)
matched = sum(1 for r in rows if r.get('GMC_GTIN') is not None)
unmatched = total - matched
null_barcodes = sum(1 for r in rows if not r.get('Shopify_Barcode'))

print(f'Total rows: {total}')
print(f'Matched with GMC: {matched}')
print(f'Unmatched (null GMC): {unmatched}')
print(f'Shopify variants with null/empty barcodes: {null_barcodes}')
print('')
if total > 10000:
    print('ERROR: Got way too many rows!')
    print('Expected: ~5,800 rows (one per Shopify variant)')
    sys.exit(1)
else:
    print('SUCCESS: skip_nulls is working correctly!')
    print('The join is NOT matching null barcodes to GMC records.')
"

echo ""
echo "=========================================="
echo "Compare: query WITHOUT skip_nulls"
echo "=========================================="

QUERY_OBJ_NO_SKIP='{"from":{"source_file":"shopify_feather_place_products.json","alias":"shopify"},"joins":[{"source":{"source_file":"gmc_feather_place_products.json","alias":"gmc"},"on":{"left":"shopify.variant.barcode","right":"gmc.gtin"},"join_type":"left","skip_nulls":false}],"select":[{"expr":"shopify.variant.barcode","alias":"Shopify_Barcode"},{"expr":"gmc.gtin","alias":"GMC_GTIN"}],"limit":100000}'

PAYLOAD_NO_SKIP=$(jq -n --arg q "$QUERY_OBJ_NO_SKIP" '{query: $q, format: "json"}')

curl -s -X POST 'http://localhost:3000/query/dsl' \
  -H 'Content-Type: application/json' \
  -d "$PAYLOAD_NO_SKIP" | python3 -c "
import sys, json
data = json.load(sys.stdin)
rows = data.get('data', [])
print(f'Without skip_nulls: {len(rows)} rows')
"
