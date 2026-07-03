# Testing Guide for JSON Loader Server

This document explains how to run and maintain the comprehensive test suite.

## Quick Start

```bash
# Run all tests
cargo test

# Run only unit tests
cargo test --lib

# Run only integration tests
cargo test --test integration_tests

# Run tests with output
cargo test -- --nocapture

# Run a specific test
cargo test test_simple_select

# Run tests matching a pattern
cargo test dsl_query

# Run benchmarks
cargo bench
```

## Test Structure

### 1. Unit Tests (`src/query_engine_tests.rs`)

These tests verify individual components of the query engine:

- **Simple SELECT** - Basic field extraction
- **WHERE clauses** - Filtering with various operators
- **JOINs** - Inner, left, right joins with skip_nulls
- **Array explosion** - explode and explode_with_context
- **Date functions** - hour(), date(), date_diff()
- **Aggregation** - GROUP BY with COUNT, SUM, AVG
- **Subqueries** - WITH clause (CTEs)
- **Edge cases** - nulls, empty results, primitive values

**Key features:**
- Uses in-memory SQLite database for fast, isolated tests
- `TestDataBuilder` helper for creating realistic test data
- Custom macros for assertions (`assert_query_result!`, `assert_cell_eq!`)

### 2. Integration Tests (`tests/integration_tests.rs`)

These tests verify the HTTP API end-to-end:

- **Health endpoints** - `/stats`, `/files`, `/`
- **Query endpoints** - `/query`, `/query/dsl`
- **Schema discovery** - `/schema`, `/join-analysis`
- **Export functionality** - `/export` (CSV, JSONL)
- **Saved queries** - `/queries` CRUD operations
- **Concurrent requests** - Verify no deadlocks
- **Error handling** - 400/404/500 responses

**Key features:**
- Uses `axum-test` to test HTTP layer without starting server
- Each test gets fresh in-memory database
- Tests request/response serialization

### 3. Benchmarks (`benches/query_benchmark.rs`)

Performance tests for different operations:

- **Simple select** - Baseline read performance
- **Filtered select** - WHERE clause evaluation
- **Array explosion** - Nested array expansion
- **Group by** - Aggregation performance
- **Date extraction** - Function evaluation
- **Joins** - Multi-table queries
- **Complex queries** - Combined operations

## Writing New Tests

### Unit Test Example

```rust
#[test]
fn test_my_new_feature() {
    // 1. Setup
    let conn = create_test_db();
    let data = vec![
        json!({"id": 1, "name": "Test"}),
    ];
    insert_test_data(&conn, "test.json", data).unwrap();
    
    // 2. Execute
    let engine = QueryEngine::new(&conn);
    let dsl = QueryDsl {
        from: Some(Source {
            source_file: "test.json".to_string(),
            alias: Some("t".to_string()),
            ..Default::default()
        }),
        select: vec![SelectField {
            expr: Some("t.name".to_string()),
            alias: Some("name".to_string()),
            ..Default::default()
        }],
        ..Default::default()
    };
    
    let result = engine.execute(&dsl).unwrap();
    
    // 3. Assert
    assert_eq!(result.columns, vec!["name"]);
    assert_eq!(result.rows.len(), 1);
    assert_eq!(result.rows[0][0], json!("Test"));
}
```

### Integration Test Example

```rust
#[tokio::test]
async fn test_my_api_endpoint() {
    // 1. Setup
    let data = TestDataBuilder::new().with_orders().build();
    let client = setup_app_with_data("orders.json", data).await;
    
    // 2. Execute
    let query = json!({
        "query": r#"{"from": {"source_file": "orders.json", "alias": "o"}, "select": [{"expr": "o.guid", "alias": "guid"}]}"#
    });
    
    let response = client
        .post("/query/dsl")
        .json(&query)
        .send()
        .await;
    
    // 3. Assert
    assert_eq!(response.status(), StatusCode::OK);
    
    let body: serde_json::Value = response.json().await;
    assert_eq!(body["rows"].as_array().unwrap().len(), 3);
}
```

## Test Data Builders

The `TestDataBuilder` provides convenient test data:

```rust
// Pre-built datasets
let data = TestDataBuilder::new()
    .with_orders()           // 3 orders with checks/selections
    .with_employees()        // 3 employees with job references
    .with_jobs()             // 2 job types
    .with_time_entries()     // 3 time clock entries
    .with_primitive_guids()  // Simple string GUIDs
    .with_nulls_and_missing() // Edge cases
    .with_invalid_dates()    // Date parsing edge cases
    .build();
```

## Debugging Failed Tests

### Enable Debug Output

```rust
#[test]
fn test_something() {
    // Add this to see the actual result
    let result = engine.execute(&dsl).unwrap();
    println!("Result: {:?}", result);  // Use --nocapture to see
    
    // Or use pretty_assertions for better diffs
    assert_eq!(result.rows, expected_rows);
}
```

### Run Single Test with Backtrace

```bash
RUST_BACKTRACE=1 cargo test test_name -- --nocapture
```

### Inspect Test Database

For debugging, you can write test data to a file:

```rust
#[test]
fn debug_test() {
    let conn = rusqlite::Connection::open("/tmp/debug.db").unwrap();
    // ... setup test data
    // Inspect with: sqlite3 /tmp/debug.db
}
```

## Continuous Integration

Example GitHub Actions workflow:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Install Rust
        uses: dtolnay/rust-action@stable
      
      - name: Run tests
        run: cargo test --all-features
      
      - name: Run benchmarks (check)
        run: cargo bench --no-run
```

## Code Coverage

Install and run tarpaulin:

```bash
cargo install cargo-tarpaulin
cargo tarpaulin --out Html
# Open tarpaulin-report.html
```

## Performance Regression Testing

Run benchmarks and compare:

```bash
# Baseline
cargo bench -- --save-baseline main

# After changes
cargo bench -- --baseline main

# View results - shows percentage change
```

## Best Practices

1. **Isolation** - Each test creates its own database; no shared state
2. **Speed** - Use in-memory SQLite; avoid file I/O in unit tests
3. **Coverage** - Test edge cases: nulls, empty arrays, invalid dates
4. **Naming** - Descriptive names: `test_<feature>_<scenario>_<expected>`
5. **Assertions** - One logical assertion per test; use multiple tests
6. **Documentation** - Complex tests should have comments explaining the scenario

## Troubleshooting

### "Database is locked" errors

This shouldn't happen with in-memory databases, but if testing with file DBs:
- Ensure only one test uses the database at a time
- Use `DROP TABLE IF EXISTS` between tests

### "No such table" errors

Make sure `create_test_db()` is called before inserting data.

### Integration tests hang

Likely a deadlock with the database mutex:
- Check that you're not holding the mutex across an await point
- Use `Mutex::lock()` carefully in async code

### Benchmarks are slow

- Use `--release` flag: `cargo bench` (this is default)
- Reduce data sizes in benchmarks for faster iteration
- Use `criterion` for statistical significance

## Summary

| Test Type | Command | Time | Purpose |
|-----------|---------|------|---------|
| Unit | `cargo test --lib` | ~1s | Fast feedback during development |
| Integration | `cargo test --test integration_tests` | ~5s | Verify API contracts |
| All | `cargo test` | ~10s | Pre-commit validation |
| Benchmarks | `cargo bench` | ~60s | Performance tracking |

Run the full suite before committing, unit tests during development.
