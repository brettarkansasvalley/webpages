# AGENTS.md - JAQ JSON Loader Server

## Project Overview

**JAQ JSON Loader Server** is a Rust-based web server that ingests JSON files into SQLite and provides JAQ-powered querying capabilities. It is part of the larger [jaq workspace](https://github.com/01mf02/jaq) (a jq clone written in Rust).

### Key Capabilities

- **JSON File Ingestion**: Load JSON arrays from files in `/home/ubuntu/jaq/loadjson` directory
- **Metadata Tracking**: Captures filename and modification timestamp for each object
- **JAQ Filtering**: Use jq-compatible filters to query and transform JSON data
- **Query DSL**: Custom domain-specific language for joining multiple JSON sources
- **Web Interface**: Modern responsive UI built with Shoelace web components
- **REST API**: HTTP endpoints for loading, querying, and managing data
- **Schema Discovery**: Automatic schema extraction from loaded JSON files
- **Join Analysis**: Automatic detection of potential join fields between sources
- **Export Options**: CSV, Excel (.xlsx), and JSONL export with direct download from results tables
- **Data Profiler**: Click any source file to see field statistics, sample data, and data types
- **Subqueries / Nested Queries**: Chain multiple queries using WITH clause and subquery references
- **Query Notes**: Attach notes to query results for documentation
- **Saved Queries**: Save and reuse frequently used queries
- **AI Query Generation**: Generate DSL queries from natural language prompts

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Rust (Edition 2021) |
| Web Framework | Axum 0.6 |
| Database | SQLite (via rusqlite 0.30) |
| Query Language | JAQ (jaq-core, jaq-std, jaq-json, jaq-all) |
| Async Runtime | Tokio |
| CORS | tower-http |
| Frontend | HTML5 + JavaScript + Shoelace 2.17.1 |
| Serialization | serde, serde_json |
| Logging | tracing, tracing-subscriber |
| CSV Export | csv 1.3 |
| Excel Export | xlsxwriter 0.6 |
| Date/Time | chrono |
| HTTP Client | reqwest (for AI API) |

## Project Structure

```
json-loader-server/
├── Cargo.toml              # Package configuration
├── README.md               # User documentation
├── AGENTS.md               # This file
├── schema.json             # Generated schema documentation
├── database.db             # SQLite database (runtime)
├── server.pid              # Process ID file (runtime)
├── server.log              # Server logs (runtime)
├── sku_comparison_query.json  # Example query configuration
├── src/
│   ├── main.rs             # Main application with HTTP handlers (~1677 lines)
│   ├── query_engine.rs     # Query DSL engine for joins/filters (~1297 lines)
│   └── html_page.html      # Web UI (embedded in binary)
├── start.sh                # Server management script (start/stop/restart/status/logs)
├── query.sh                # Example query script (joins GMC + Shopify)
├── query_product.sh        # Query specific product by MPN/SKU
├── query_raw.sh            # Return raw JSON objects from joins
├── query_all.sh            # Return all fields from joined datasets
├── query_explore.sh        # Explore available fields
├── view_schemas.sh         # Schema viewer (shell + jq)
├── view_schemas.py         # Schema viewer (Python)
└── test_parse.js           # Test utility for curl parsing
```

## Build and Run Commands

### Prerequisites

- Rust 1.69 or higher
- SQLite3 (bundled with rusqlite)
- Python 3 (for schema viewing scripts)
- jq (for view_schemas.sh)

### Building

```bash
# Build from project root (workspace)
cd /home/ubuntu/jaq
cargo build --release -p json-loader-server

# Or build directly from project directory
cargo build --release
```

The compiled binary will be at:
```
/home/ubuntu/jaq/target/release/json-loader-server
```

### Running the Server

```bash
# Using the management script (recommended)
./start.sh start      # Start the server
./start.sh stop       # Stop the server
./start.sh restart    # Restart the server (default)
./start.sh status     # Check server status
./start.sh logs       # Follow server logs

# Or run directly
./target/release/json-loader-server
```

Server listens on `http://0.0.0.0:3000`

### Development Commands

```bash
# Run tests
cargo test -p json-loader-server

# Build for development
cargo build -p json-loader-server

# Linting
cargo clippy -p json-loader-server

# Run with debug logging
RUST_LOG=debug ./target/release/json-loader-server
```

## Configuration

Configuration is hardcoded in `src/main.rs` at lines 30-31:

```rust
const JSON_DIR: &str = "/home/ubuntu/jaq/loadjson";     // Source JSON files
const DB_PATH: &str = "/home/ubuntu/jaq/json-loader-server/database.db";
```

Modify these constants and rebuild to change paths.

## Database Schema

### Tables

```sql
-- Main storage for JSON objects
CREATE TABLE json_objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    json_data TEXT NOT NULL,
    source_file TEXT NOT NULL,
    modified_at TEXT NOT NULL,
    UNIQUE(json_data, source_file)
);

-- Saved queries for reuse
CREATE TABLE saved_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    query_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Notes attached to query results
CREATE TABLE query_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_hash TEXT NOT NULL,
    full_query TEXT,
    row_hash TEXT NOT NULL,
    note_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(query_hash, row_hash)
);

-- Index for note lookups
CREATE INDEX idx_query_notes_hash ON query_notes(query_hash);
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Web UI (HTML page) |
| POST | `/load` | Load JSON files from configured directory |
| GET | `/stats` | Get database statistics |
| GET | `/files` | List all loaded source files |
| GET | `/query` | Query objects with optional JAQ filter |
| POST | `/query/dsl` | Execute Query DSL (joins, filters, select) |
| POST | `/query/dsl/with-notes` | Execute DSL with note attachments |
| POST | `/export` | Export query results to CSV, Excel, or JSONL |
| GET | `/queries` | List saved queries |
| POST | `/queries` | Save a new query |
| DELETE | `/queries/:id` | Delete a saved query |
| GET | `/schema` | Get schema for a source file |
| GET | `/join-analysis` | Analyze potential joins between sources |
| GET | `/notes` | Get notes for a query hash |
| POST | `/notes` | Save or update a note |
| DELETE | `/notes/:id` | Delete a note |
| POST | `/ai/generate` | Generate DSL query from natural language |

## Query DSL

The custom Query DSL allows joining multiple JSON sources:

```json
{
  "from": {
    "source_file": "gmc_products.json",
    "alias": "gmc",
    "explode": "variants"
  },
  "joins": [
    {
      "source": {
        "source_file": "shopify_products.json",
        "alias": "shopify"
      },
      "on": {
        "left": "gmc.mpn",
        "right": "shopify.variants[].sku"
      },
      "join_type": "inner"
    }
  ],
  "where": [
    {"field": "gmc.mpn", "op": "!=", "value": ""}
  ],
  "select": [
    {"expr": "gmc.title", "alias": "Title"},
    {"expr": "shopify.status", "alias": "Status"}
  ],
  "flatten": false,
  "limit": 100
}
```

### Supported Operations

- **Join Types**: `inner`, `left`, `right`, `full`, `cross`
- **Array Joins**: Use `field[]` notation for array fields (e.g., `variants[].sku`)
- **Operators**: `=`, `!=`, `<`, `>`, `<=`, `>=`, `contains`, `starts_with`, `exists`
- **Wildcard Selection**: Use `alias.*` to select all fields from a source
- **Output Formats**: `default` (table), `json` (array of objects), `jsonl` (newline-delimited JSON)
- **Aggregation**: `sum`, `count`, `avg`, `min`, `max` (requires `group_by`)
- **Transforms**: `upper`, `lower`

### Subqueries / Nested Queries

The DSL supports subqueries (Common Table Expressions) that allow chaining multiple transformations:

```json
{
  "with": [
    {
      "name": "filtered_products",
      "query": {
        "from": {"source_file": "gmc_products.json", "alias": "g"},
        "where": [{"field": "g.mpn", "op": "!=", "value": ""}],
        "select": [
          {"expr": "g.mpn", "alias": "mpn"},
          {"expr": "g.title", "alias": "title"}
        ],
        "limit": 100
      }
    }
  ],
  "from_subquery": "filtered_products",
  "joins": [{
    "subquery": "another_cte",
    "alias": "other",
    "on": {"left": "filtered_products.mpn", "right": "other.sku"},
    "join_type": "inner"
  }],
  "select": [
    {"expr": "filtered_products.mpn", "alias": "MPN"},
    {"expr": "filtered_products.title", "alias": "Title"}
  ]
}
```

**Key features:**
- Define named subqueries in the `with` array
- Reference subqueries using `from_subquery` (for primary source)
- Join subqueries using `"subquery": "name"` instead of `source`
- Chain multiple transformations - output of one subquery becomes input to the next

## Export Formats

Query results can be exported in multiple formats via the `/export` endpoint or the web UI:

### Supported Formats

| Format | Extension | Content-Type | Description |
|--------|-----------|--------------|-------------|
| CSV | `.csv` | `text/csv` | Comma-separated values with proper escaping |
| Excel | `.xlsx` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | Microsoft Excel with auto-filter |
| JSON Lines | `.jsonl` | `application/x-ndjson` | Newline-delimited JSON |
| Parquet | `.parquet` | N/A | Falls back to JSONL (not yet implemented) |

### Export API

```bash
POST /export
Content-Type: application/json

{
  "query": "{\"from\": {...}, \"select\": [...]}",
  "format": "csv",
  "filename": "my_export"
}
```

Response: Binary file download with appropriate Content-Disposition header.

## Data Profiler

The Simple Query tab includes a **Source Files Explorer** that provides detailed profiling:

### Field Statistics

For each field in the source file:
- **Field Name** - The JSON path to the field
- **Data Type** - Detected type: `string`, `number`, `integer`, `boolean`, `array`, `object`, `null`
- **Null Count** - Number of records with null/empty values
- **Unique Count** - Number of distinct values
- **Sample Values** - Up to 2 example values

### API Endpoint

```bash
GET /schema?source_file=gmc_products.json
```

## Code Organization

### main.rs

Main application containing:
- HTTP route handlers (Axum) - see `main()` function at line 1632
- Database initialization (`init_database()`) at line 1470
- JAQ filter application (`apply_jaq_filter()`) at line 810
- Schema extraction (`get_schema()`) at line 1174
- Join analysis (`analyze_joins()`) at line 1287
- HTML page serving (`html_page()`) at line 1628
- Export handlers (`export_data()`, `export_to_csv()`, `export_to_xlsx()`, `export_to_jsonl()`) at line 627
- Query notes API handlers (`get_notes()`, `save_note()`, `delete_note()`) at line 1026
- Saved queries API handlers (`list_saved_queries()`, `save_query()`, `delete_saved_query()`) at line 942
- AI query generation (`ai_generate_dsl()`) at line 1552

### query_engine.rs

Query DSL engine containing:
- `QueryDsl` struct and related types at line 8
- `QueryEngine` struct for executing queries at line 155
- `execute_query()` public function at line 1283
- Join implementation with hash-based indexing (`apply_join()`) at line 298
- Pattern matching joins (`apply_pattern_join()`) at line 554
- Cross join support (`apply_cross_join()`) at line 507
- Filter application (`apply_filters()`) at line 691
- Field selection with wildcard expansion (`select_fields()`) at line 931
- Aggregation functions (`apply_group_by()`, `calculate_aggregate()`) at line 769
- Subquery/CTE support (`execute_with_context()`) at line 170

## Development Conventions

### Code Style

- Follow standard Rust formatting (`cargo fmt`)
- Use `anyhow` for error handling
- Use `tracing` for structured logging
- Mutex-protected shared state for database access (`Arc<Mutex<Connection>>`)
- Async/await pattern for HTTP handlers

### Error Handling

- Return appropriate HTTP status codes
- Log errors with context using `tracing`
- Use `anyhow::Result` for internal functions
- Return empty results instead of errors for JAQ filter failures

### Testing Strategy

- Unit tests in `query_engine.rs` (minimal - see `#[cfg(test)]` module at line 1289)
- Integration testing via shell scripts (`query.sh`, `query_product.sh`, etc.)
- Manual testing via web UI at `http://localhost:3000`

## Utility Scripts

| Script | Purpose |
|--------|---------|
| `start.sh {start\|stop\|restart\|status\|logs}` | Server management |
| `query.sh [limit]` | Example join query (GMC + Shopify) |
| `query_product.sh <sku>` | Query specific product by MPN/SKU |
| `query_raw.sh [limit] [mpn]` | Get raw JSON objects from joins |
| `query_all.sh [limit] [mpn]` | Get all fields from joined datasets |
| `query_explore.sh [mpn]` | Explore available fields |
| `view_schemas.sh` | View schema via shell + jq |
| `view_schemas.py` | View schema via Python |

## Security Considerations

- **CORS**: Configured to allow all origins (`CorsLayer::new().allow_origin(Any)`)
- **SQL Injection**: Protected via rusqlite parameterized queries
- **File Access**: Limited to configured `JSON_DIR`
- **No Authentication**: Server assumes trusted environment

## Troubleshooting

### Database Locked

Ensure only one server instance is running:
```bash
./start.sh restart
```

### Port Already in Use

Port 3000 is used by default. Kill conflicting processes:
```bash
./start.sh stop
# or manually
lsof -ti:3000 | xargs kill -9
```

### JSON Parsing Errors

Ensure JSON files are arrays of objects:
```json
[{"field": "value"}]     // Correct
{"field": "value"}       // Incorrect - needs array wrapper
```

### JAQ Filter Errors

If a JAQ filter returns no results:
- Check filter syntax matches jq syntax
- Verify field names exist in your JSON
- Test with simple filters first: `.title`
- Use `keys` to see available fields

### Build Errors

If building fails due to workspace dependencies:
```bash
cd /home/ubuntu/jaq
cargo build --release -p json-loader-server
```

## Related Documentation

- [JAQ Manual](https://gedenkt.at/jaq/manual/)
- [jq Manual](https://stedolan.github.io/jq/manual/)
- [Axum Documentation](https://docs.rs/axum/)
- [Shoelace Components](https://shoelace.style/)
- [SQLite Documentation](https://www.sqlite.org/docs.html)

## License

MIT (follows the jaq workspace license)
