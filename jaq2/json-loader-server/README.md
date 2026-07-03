# JAQ JSON Loader Server

A Rust-based web server for ingesting JSON files into SQLite with JAQ-powered querying capabilities.

## Overview

This server provides a complete solution for:
- **JSON File Ingestion**: Load JSON arrays from files and store each object in a database
- **Metadata Tracking**: Automatically captures filename and modification timestamp for each object
- **JAQ Filtering**: Use jq-compatible filters to query and transform JSON data
- **Web Interface**: Modern UI built with Shoelace web components
- **REST API**: Simple endpoints for loading, querying, and managing data

## Features

- 📥 **Batch Loading**: Load all `.json` files from a directory
- 🗄️ **SQLite Storage**: Efficient storage with metadata tracking
- 🔍 **JAQ Querying**: Full jq-compatible filter support
- 🌐 **REST API**: Clean HTTP endpoints
- 🎨 **Modern UI**: Responsive interface with Shoelace components
- 📊 **Statistics**: Track total objects and loaded files
- 🔐 **CORS Enabled**: Ready for cross-origin requests

## Architecture

### Database Schema

```sql
CREATE TABLE json_objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    json_data TEXT NOT NULL,
    source_file TEXT NOT NULL,
    modified_at TEXT NOT NULL,
    UNIQUE(json_data, source_file)
);
```

### Components

1. **Rust Backend** (`main.rs`)
   - JSON file parsing and ingestion
   - SQLite database operations
   - JAQ filter execution
   - REST API handlers

2. **Frontend** (HTML/JavaScript)
   - Shoelace web components
   - AJAX calls to backend
   - Real-time query execution

3. **Dependencies**
   - `axum 0.6`: Web framework
   - `rusqlite 0.30`: SQLite database
   - `jaq-all`: JAQ query language
   - `tokio`: Async runtime
   - `tower-http`: CORS middleware

## Installation

### Prerequisites

- Rust 1.69 or higher
- Access to JSON files in `/home/ubuntu/jaq/loadjson`

### Build from Source

```bash
cd /home/ubuntu/jaq
cargo build --release -p json-loader-server
```

The compiled binary will be at:
```
target/release/json-loader-server
```

## Usage

### Starting the Server

```bash
./target/release/json-loader-server
```

The server will start on `http://localhost:3000`

### Accessing the Web Interface

Open your browser and navigate to:
```
http://localhost:3000
```

## API Documentation

### Endpoints

#### Load JSON Files

**POST** `/load`

Loads all JSON files from the configured directory into the database.

**Response:**
```json
{
  "loaded_files": ["file1.json", "file2.json"],
  "total_objects": 150,
  "errors": []
}
```

#### Get Statistics

**GET** `/stats`

Returns database statistics.

**Response:**
```json
{
  "total_objects": 150,
  "total_files": 7
}
```

#### Get Files

**GET** `/files`

Returns list of all loaded source files.

**Response:**
```json
["gmc_feather_place_products.json", "odoo_products.json", ...]
```

#### Query Objects

**GET** `/query?filter=<filter>&source_file=<file>&limit=<limit>`

Query objects with optional JAQ filter.

**Query Parameters:**
- `filter` (optional): JAQ filter expression
- `source_file` (optional): Filter by source filename
- `limit` (optional): Maximum number of results (default: 50)

**Response:**
```json
[
  {
    "id": 1,
    "json_data": "{\"title\": \"Product Name\", ...}",
    "source_file": "products.json",
    "modified_at": "1679677057"
  }
]
```

## JAQ Filter Examples

JAQ is a jq-compatible query language. Here are common patterns:

### Field Access

```jq
.title              # Get title field
.title, .gtin      # Get multiple fields
.title, .gtin, .mpn # Get multiple fields
```

### String Operations

```jq
.title | contains("feather")     # Contains substring
.title | startswith("Peacock")    # Starts with
.title | endswith("Feather")      # Ends with
.title | length                   # String length
.title | ascii_upcase            # Uppercase
```

### Array Operations

```jq
.tags[]           # Explode array
.tags | length    # Array length
.tags[0]          # First element
.tags[-1]         # Last element
.tags[] | .       # Flatten nested arrays
```

### Object Operations

```jq
keys               # Get all keys
.values            # Get all values
length             # Number of keys
```

### Conditional Filtering

```jq
select(.title | contains("feather"))  # Filter by condition
```

### Mathematical Operations

```jq
.price * 1.1        # Multiply (10% increase)
.price + 10          # Add
.price / 2           # Divide
.price | floor        # Round down
```

### Complex Queries

```jq
# Select specific fields
{ title: .title, gtin: .gtin, mpn: .mpn }

# Nested field access
.variantId, .title, .imageLink

# Multiple conditions
select(.title | contains("feather") and (.gtin | length > 10))

# Transform and filter
map({title, gtin: .gtin}) | select(.gtin | startswith("09670"))
```

## JSON File Format

JSON files should be arrays of objects:

```json
[
  {
    "offerId": "shopify_US_8195229843764_44749333627188",
    "variantId": "44749333627188",
    "title": "Peacock Feather Eyes Dyed Stem Lt Turquoise",
    "imageLink": "https://cdn.shopify.com/s/files/1/0743/0461/8804/products/...",
    "gtin": "096709743683",
    "mpn": "B470-25--LT"
  },
  {
    "offerId": "shopify_US_8195157623092_44749203439924",
    "variantId": "44749203439924",
    "title": "Natural Duck Plumage Mallard Feather For Sale",
    "imageLink": "https://cdn.shopify.com/s/files/...",
    "gtin": "096709051252",
    "mpn": "BDPMN--N"
  }
]
```

## Configuration

Constants are defined at the top of `src/main.rs`:

```rust
const JSON_DIR: &str = "/home/ubuntu/jaq/loadjson";
const DB_PATH: &str = "/home/ubuntu/jaq/json-loader-server/database.db";
```

Modify these as needed for your environment.

## Troubleshooting

### Database Locked Error

If you encounter database locking, ensure only one instance of the server is running.

### JSON Parsing Errors

Check that your JSON files contain valid JSON arrays. Each file should be:
- A valid JSON array `[]`
- Containing objects `{}`
- Properly formatted with quoted strings

Example of **correct** format:
```json
[
  {"field1": "value1", "field2": "value2"},
  {"field1": "value3", "field2": "value4"}
]
```

Example of **incorrect** format:
```json
{"field1": "value1", "field2": "value2"}  // Missing array wrapper
```

### JAQ Filter Errors

If a JAQ filter returns no results:
- Check filter syntax matches jq syntax
- Verify field names exist in your JSON
- Test with simple filters first: `.title`
- Use `keys` to see available fields

### CORS Errors in Browser

The server is configured to allow all origins for development. If you encounter CORS issues, check your browser's network tab for details.

### Port Already in Use

If port 3000 is already in use, modify the port in `main.rs`:
```rust
let listener = TcpListener::bind("0.0.0.0:8080").await?;
```

## Development

### Running Tests

```bash
cargo test -p json-loader-server
```

### Building for Development

```bash
cargo build -p json-loader-server
```

### Linting

```bash
cargo clippy -p json-loader-server
```

### Running with Debug Logging

```bash
RUST_LOG=debug ./target/release/json-loader-server
```

## Performance Considerations

- **Bulk Inserts**: Uses SQLite transactions for efficient bulk loading
- **Parameterized Queries**: Prevents SQL injection
- **Indexing**: UNIQUE constraint on (json_data, source_file) prevents duplicates
- **JAQ Filtering**: Applied in-memory after database query for flexibility

## License

This project follows the same license as the jaq workspace (MIT).

## Contributing

Contributions are welcome! Please ensure:
- Code follows Rust best practices
- All tests pass
- New features include documentation
- Database schema changes are documented

## Support

For issues related to:
- **JAQ queries**: Refer to [JAQ Manual](https://gedenkt.at/jaq/manual/)
- **jq syntax**: Visit [jq Manual](https://stedolan.github.io/jq/manual/)
- **Rust/Axum**: Check the official documentation
- **SQLite**: See [SQLite Documentation](https://www.sqlite.org/docs.html)
- **Shoelace Components**: Visit [Shoelace Documentation](https://shoelace.style/)

## Example Workflow

1. **Start the server:**
   ```bash
   ./target/release/json-loader-server
   ```

2. **Open web interface:**
   Navigate to `http://localhost:3000`

3. **Load JSON files:**
   Click "Load JSON Files" button

4. **Query data:**
   - Enter JAQ filter: `.title | contains("feather")`
   - Optionally select source file
   - Set limit
   - Click "Execute Query"

5. **View results:**
   - See matching objects with full JSON data
   - View metadata (filename, modification time)
   - Copy results as needed

## Advanced Usage

### Cross-File Queries

Query across multiple files:
```bash
# All objects with "feather" in title, regardless of source file
GET /query?filter=.title%20%7C%20contains(%22feather%22)
```

### File-Specific Queries

Query specific files:
```bash
# Only from gmc_feather_place_products.json
GET /query?source_file=gmc_feather_place_products.json
```

### Combined Queries

Filter by file and content:
```bash
# Feather products from GMC file with specific GTIN prefix
GET /query?source_file=gmc_feather_place_products.json&filter=.gtin%20%7C%20startswith(%2209670%22)
```

## System Requirements

- **OS**: Linux, macOS, or Windows
- **RAM**: 512MB minimum (1GB+ recommended for large datasets)
- **Storage**: Disk space for SQLite database (depends on data size)
- **Network**: TCP port 3000 (configurable)