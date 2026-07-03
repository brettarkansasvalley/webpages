// Test the curl parsing function
const testCurl = `curl -s -X POST 'http://localhost:3000/query/dsl' -H 'Content-Type: application/json' -d '{"query":"{\\"from\\":{\\"source_file\\":\\"gmc_feather_place_products.json\\",\\"alias\\":\\"primary\\"}}","format":"json"}'`;

function parseCurlCommand(curlCmd) {
    const dataIdx = curlCmd.search(/-d\s+|--data\s+/);
    if (dataIdx === -1) {
        throw new Error("Could not find -d or --data parameter in curl command");
    }
    
    let startIdx = curlCmd.indexOf("'", dataIdx);
    let quoteChar = "'";
    if (startIdx === -1) {
        startIdx = curlCmd.indexOf('"', dataIdx);
        quoteChar = '"';
    }
    if (startIdx === -1) {
        throw new Error("Could not find quoted data in curl command");
    }
    startIdx++;
    
    let endIdx = startIdx;
    let inEscape = false;
    while (endIdx < curlCmd.length) {
        const char = curlCmd[endIdx];
        if (inEscape) {
            inEscape = false;
        } else if (char === "\\") {
            inEscape = true;
        } else if (char === quoteChar) {
            break;
        }
        endIdx++;
    }
    
    if (endIdx >= curlCmd.length) {
        throw new Error("Could not find closing quote for data parameter");
    }
    
    let dataStr = curlCmd.substring(startIdx, endIdx);
    console.log("Extracted data string:", dataStr.substring(0, 100) + "...");
    
    dataStr = dataStr.replace(/\\"/g, '"');
    console.log("After unescaping:", dataStr.substring(0, 100) + "...");
    
    try {
        const parsed = JSON.parse(dataStr);
        return parsed;
    } catch (e) {
        throw new Error(`Invalid JSON in curl data: ${e.message}`);
    }
}

try {
    const result = parseCurlCommand(testCurl);
    console.log("SUCCESS:");
    console.log(JSON.stringify(result, null, 2));
} catch (e) {
    console.log("ERROR:", e.message);
}
