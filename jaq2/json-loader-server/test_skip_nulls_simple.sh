#!/bin/bash

# Simple test for skip_nulls functionality

echo "Testing skip_nulls DSL query..."
echo ""

QUERY='{"from":{"source_file":"shopify_feather_place_products.json","alias":"shopify"},"joins":[{"source":{"source_file":"gmc_feather_place_products.json","alias":"gmc"},"on":{"left":"shopify.variant.barcode","right":"gmc.gtin"},"join_type":"left","skip_nulls":true}],"select":[{"expr":"shopify.variant.barcode","alias":"Shopify_Barcode"},{"expr":"shopify.variant.sku","alias":"Shopify_SKU"},{"expr":"gmc.gtin","alias":"GMC_GTIN"},{"expr":"gmc.mpn","alias":"GMC_MPN"}],"limit":100000}'

echo "Running curl command..."
curl -s -X POST 'http://localhost:3000/query/dsl' \
  -H 'Content-Type: application/json' \
  -d "{\"query\":\"$QUERY\",\"format\":\"json\"}" | tee /tmp/skip_nulls_result.json | python3 -c "
import sys, json
data = json.load(sys.stdin)
rows = data.get('data', [])
print(f'Total rows returned: {len(rows)}')
matched = sum(1 for r in rows if r.get('GMC_GTIN'))
print(f'Rows with GMC match: {matched}')
print(f'Rows without GMC match: {len(rows) - matched}')
if len(rows) > 10000:
    print('WARNING: Got more than 10k rows - skip_nulls may not be working!')
else:
    print('SUCCESS: Row count looks reasonable (~5-6k expected)')
"

echo ""
echo "Full results saved to: /tmp/skip_nulls_result.json"
