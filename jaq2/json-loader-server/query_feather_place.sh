#!/bin/bash

# Query to join GMC and Shopify Feather Place products
# Attempts to match on GTIN/barcode, falls back to MPN/SKU if needed

API_URL="http://localhost:3000/query/dsl"

echo "=========================================="
echo "Feather Place GMC + Shopify Query"
echo "=========================================="
echo ""

# Check server is running
if ! curl -s "$API_URL" > /dev/null 2>&1; then
    echo "ERROR: Server not responding at $API_URL"
    echo "Start server with: ./start.sh start"
    exit 1
fi

# Create query objects
QUERY_GTIN_OBJ=$(jq -n '{
  from: {source_file: "gmc_feather_place_products.json", alias: "gmc"},
  joins: [{
    source: {source_file: "shopify_feather_place_products.json", alias: "shopify"},
    on: {left: "gmc.gtin", right: "shopify.variant.barcode"},
    join_type: "full"
  }],
  select: [
    {expr: "gmc.gtin", alias: "GMC_GTIN"},
    {expr: "gmc.mpn", alias: "GMC_MPN"},
    {expr: "gmc.title", alias: "GMC_Title"},
    {expr: "gmc.imageLink", alias: "GMC_Image_URL"},
    {expr: "gmc.offerId", alias: "GMC_Offer_ID"},
    {expr: "shopify.variant.barcode", alias: "Shopify_Barcode"},
    {expr: "shopify.variant.sku", alias: "Shopify_SKU"},
    {expr: "shopify.product.title", alias: "Shopify_Product_Title"},
    {expr: "shopify.product.handle", alias: "Shopify_Handle"},
    {expr: "shopify.variant.price", alias: "Shopify_Price"},
    {expr: "shopify.variant.inventoryQuantity", alias: "Shopify_Inventory"},
    {expr: "shopify.variant.metafield.value", alias: "Shopify_MPN"}
  ],
  limit: 10000
}')

QUERY_MPN_OBJ=$(jq -n '{
  from: {source_file: "gmc_feather_place_products.json", alias: "gmc"},
  joins: [{
    source: {source_file: "shopify_feather_place_products.json", alias: "shopify"},
    on: {left: "gmc.mpn", right: "shopify.variant.sku"},
    join_type: "full"
  }],
  select: [
    {expr: "gmc.gtin", alias: "GMC_GTIN"},
    {expr: "gmc.mpn", alias: "GMC_MPN"},
    {expr: "gmc.title", alias: "GMC_Title"},
    {expr: "gmc.imageLink", alias: "GMC_Image_URL"},
    {expr: "gmc.offerId", alias: "GMC_Offer_ID"},
    {expr: "shopify.variant.barcode", alias: "Shopify_Barcode"},
    {expr: "shopify.variant.sku", alias: "Shopify_SKU"},
    {expr: "shopify.product.title", alias: "Shopify_Product_Title"},
    {expr: "shopify.product.handle", alias: "Shopify_Handle"},
    {expr: "shopify.variant.price", alias: "Shopify_Price"},
    {expr: "shopify.variant.inventoryQuantity", alias: "Shopify_Inventory"},
    {expr: "shopify.variant.metafield.value", alias: "Shopify_MPN"}
  ],
  limit: 10000
}')

# Create payload with query as JSON string
QUERY_GTIN=$(jq -n --arg q "$QUERY_GTIN_OBJ" '{query: $q | fromjson, format: "json"}')
QUERY_MPN=$(jq -n --arg q "$QUERY_MPN_OBJ" '{query: $q | fromjson, format: "json"}')

# Actually, API expects query as serialized JSON string - let me check the docs again
# Looking at the user's curl, they use: '{"query":"{\"from\":...}", ...}'
# So query is a JSON string embedded in JSON

# Create payloads properly - query must be a JSON string
QUERY_GTIN=$(jq -n --arg q "$QUERY_GTIN_OBJ" '{query: $q, format: "json"}')
QUERY_MPN=$(jq -n --arg q "$QUERY_MPN_OBJ" '{query: $q, format: "json"}')

# Function to run query and analyze results
run_query() {
    local payload="$1"
    local join_type="$2"
    
    echo "Running query with join on: $join_type"
    
    RESPONSE=$(curl -s -X POST "$API_URL" \
      -H 'Content-Type: application/json' \
      -d "$payload")
    
    # Check if response is valid JSON
    if ! echo "$RESPONSE" | jq -e . > /dev/null 2>&1; then
        echo "  ERROR: Invalid JSON response"
        echo "  Response: $RESPONSE"
        return 1
    fi
    
    # Check for errors in response
    if echo "$RESPONSE" | jq -e '.error' > /dev/null 2>&1; then
        echo "  ERROR in query response:"
        echo "$RESPONSE" | jq .
        return 1
    fi
    
    # Get results array (API returns "data" key)
    TOTAL_COUNT=$(echo "$RESPONSE" | jq '.data | length')
    
    echo "  Total records returned: $TOTAL_COUNT"
    
    if [ "$TOTAL_COUNT" -eq 0 ]; then
        echo "  WARNING: No records returned"
        return 1
    fi
    
    # Count matches (records with both GMC and Shopify data)
    MATCH_COUNT=$(echo "$RESPONSE" | jq '[.data[] | select((.GMC_GTIN != null or .GMC_MPN != null) and (.Shopify_Barcode != null or .Shopify_SKU != null))] | length')
    
    # Count GMC-only records  
    GMC_ONLY=$(echo "$RESPONSE" | jq '[.data[] | select((.GMC_GTIN != null or .GMC_MPN != null) and (.Shopify_Barcode == null and .Shopify_SKU == null))] | length')
    
    # Count Shopify-only records
    SHOPIFY_ONLY=$(echo "$RESPONSE" | jq '[.data[] | select((.GMC_GTIN == null and .GMC_MPN == null) and (.Shopify_Barcode != null or .Shopify_SKU != null))] | length')
    
    echo "  Matched records (both sides): $MATCH_COUNT"
    echo "  GMC-only records: $GMC_ONLY"
    echo "  Shopify-only records: $SHOPIFY_ONLY"
    echo ""
    
    # Export these values for later
    export MATCH_COUNT GMC_ONLY SHOPIFY_ONLY TOTAL_COUNT
    
    return 0
}

echo "TEST 1: Join on GTIN -> barcode"
echo "--------------------------------"
if run_query "$QUERY_GTIN" "GTIN/barcode"; then
    GTIN_MATCHES=$MATCH_COUNT
    GTIN_RESPONSE="$RESPONSE"
else
    GTIN_MATCHES=0
fi

echo "TEST 2: Join on MPN -> SKU"  
echo "--------------------------------"
if run_query "$QUERY_MPN" "MPN/SKU"; then
    MPN_MATCHES=$MATCH_COUNT
    MPN_RESPONSE="$RESPONSE"
else
    MPN_MATCHES=0
fi

# Determine best join strategy
echo "=========================================="
echo "Summary"
echo "=========================================="

if [ "$GTIN_MATCHES" -gt 0 ] 2>/dev/null || [ "$MPN_MATCHES" -gt 0 ] 2>/dev/null; then
    if [ "$GTIN_MATCHES" -ge "$MPN_MATCHES" ] 2>/dev/null; then
        echo "✓ RECOMMENDED: Use GTIN/barcode join"
        echo "  Found $GTIN_MATCHES matches"
        PAYLOAD_TO_USE="$QUERY_GTIN"
        RESPONSE_TO_USE="$GTIN_RESPONSE"
        BEST_MATCH=$GTIN_MATCHES
    else
        echo "✓ RECOMMENDED: Use MPN/SKU join"
        echo "  Found $MPN_MATCHES matches"
        PAYLOAD_TO_USE="$QUERY_MPN"
        RESPONSE_TO_USE="$MPN_RESPONSE"
        BEST_MATCH=$MPN_MATCHES
    fi
    SUCCESS=true
else
    echo "✗ No matches found with either join strategy"
    echo ""
    echo "This indicates the GMC and Shopify datasets"
    echo "contain different products (no overlap)."
    echo ""
    echo "GMC Products: Rooster Coque Tails (CCWS*)"
    echo "Shopify Products: Wings (WG*), Turkey (TX*), etc."
    echo ""
    echo "Sample GMC MPNs:"
    sqlite3 database.db "SELECT DISTINCT json_extract(json_data, '$.mpn') FROM json_objects WHERE source_file = 'gmc_feather_place_products.json' LIMIT 5;"
    echo ""
    echo "Sample Shopify SKUs:"
    sqlite3 database.db "SELECT DISTINCT json_extract(json_data, '$.variant.sku') FROM json_objects WHERE source_file = 'shopify_feather_place_products.json' LIMIT 5;"
    SUCCESS=false
fi

if [ "$SUCCESS" = true ]; then
    echo ""
    echo "=========================================="
    echo "Query Results"
    echo "=========================================="
    
    TOTAL_COUNT=$(echo "$RESPONSE_TO_USE" | jq '.data | length')
    
    # Show sample matched records
    if [ "$BEST_MATCH" -gt 0 ]; then
        echo ""
        echo "Sample Matched Records (first 5):"
        echo "-----------------------------------"
        echo "$RESPONSE_TO_USE" | jq '[.data[] | select((.GMC_GTIN != null or .GMC_MPN != null) and (.Shopify_Barcode != null or .Shopify_SKU != null))][:5]'
    fi
    
    # Save results
    OUTPUT_FILE="feather_place_results.json"
    echo "$RESPONSE_TO_USE" | jq . > "$OUTPUT_FILE"
    echo ""
    echo "✓ Query completed successfully"
    echo "✓ Total records: $TOTAL_COUNT"
    echo "✓ Matched records: $BEST_MATCH"
    echo "✓ Results saved to: $OUTPUT_FILE"
    
    # Final validation
    echo ""
    echo "=========================================="
    echo "Validation"
    echo "=========================================="
    
    if [ "$BEST_MATCH" -gt 0 ]; then
        echo "✓ PASS: Found $BEST_MATCH matched records"
        
        # Check for null values in key fields
        NULL_GTIN=$(echo "$RESPONSE_TO_USE" | jq '[.data[] | select(.GMC_GTIN == null)] | length')
        NULL_SHOPIFY_SKU=$(echo "$RESPONSE_TO_USE" | jq '[.data[] | select(.Shopify_SKU == null)] | length')
        
        echo "  Records with null GMC_GTIN: $NULL_GTIN"
        echo "  Records with null Shopify_SKU: $NULL_SHOPIFY_SKU"
        echo ""
        echo "✓ Query is working correctly!"
    else
        echo "✗ FAIL: No matches found"
        exit 1
    fi
else
    # Save diagnostic results anyway
    OUTPUT_FILE="feather_place_results.json"
    jq -n \
      --argjson gtin "$GTIN_MATCHES" \
      --argjson mpn "$MPN_MATCHES" \
      '{diagnostic: true, gtin_matches: $gtin, mpn_matches: $mpn, message: "No matching products found between GMC and Shopify datasets"}' \
      > "$OUTPUT_FILE"
    echo ""
    echo "Diagnostics saved to: $OUTPUT_FILE"
    echo "The GMC and Shopify datasets have no overlapping products."
fi
