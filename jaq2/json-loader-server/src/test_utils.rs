//! Test utilities for json-loader-server
//!
//! This module provides helpers for setting up test databases,
//! inserting test data, and creating test fixtures.

use anyhow::Result;
use rusqlite::{params, Connection};
use serde_json::Value;
use std::collections::HashMap;

/// Create an in-memory SQLite database with the schema initialized
pub fn create_test_db() -> Connection {
    let conn = Connection::open_in_memory().expect("Failed to create in-memory database");
    init_schema(&conn);
    conn
}

/// Initialize the database schema
fn init_schema(conn: &Connection) {
    conn.execute(
        "CREATE TABLE json_objects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            json_data TEXT NOT NULL,
            source_file TEXT NOT NULL,
            modified_at TEXT NOT NULL,
            UNIQUE(json_data, source_file)
        )",
        [],
    )
    .expect("Failed to create json_objects table");

    conn.execute(
        "CREATE TABLE saved_queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            query_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )",
        [],
    )
    .expect("Failed to create saved_queries table");

    conn.execute(
        "CREATE TABLE query_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_hash TEXT NOT NULL,
            full_query TEXT,
            row_hash TEXT NOT NULL,
            note_text TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(query_hash, row_hash)
        )",
        [],
    )
    .expect("Failed to create query_notes table");

    conn.execute(
        "CREATE INDEX idx_query_notes_hash ON query_notes(query_hash)",
        [],
    )
    .expect("Failed to create query_notes index");
}

/// Insert test data into the database
pub fn insert_test_data(conn: &Connection, source_file: &str, data: Vec<Value>) -> Result<usize> {
    let mut count = 0;
    for (i, value) in data.iter().enumerate() {
        conn.execute(
            "INSERT INTO json_objects (json_data, source_file, modified_at) 
             VALUES (?1, ?2, ?3)
             ON CONFLICT(json_data, source_file) DO NOTHING",
            [
                value.to_string(),
                source_file.to_string(),
                format!("{}", i),
            ],
        )?;
        count += 1;
    }
    Ok(count)
}

/// Builder for creating test datasets
pub struct TestDataBuilder {
    data: Vec<Value>,
}

impl TestDataBuilder {
    pub fn new() -> Self {
        Self { data: Vec::new() }
    }

    pub fn with_orders(mut self) -> Self {
        let orders = vec![
            serde_json::json!({
                "guid": "order-001",
                "businessDate": "2024-01-15",
                "closedDate": "2024-01-15T14:30:00Z",
                "server": {"guid": "server-001", "name": "Alice"},
                "checks": [
                    {
                        "guid": "check-001",
                        "amount": 50.00,
                        "voided": false,
                        "selections": [
                            {"item": "Feather", "qty": 2, "price": 10.00},
                            {"item": "Bead", "qty": 1, "price": 30.00}
                        ]
                    },
                    {
                        "guid": "check-002",
                        "amount": 25.00,
                        "voided": false,
                        "selections": [
                            {"item": "Thread", "qty": 5, "price": 5.00}
                        ]
                    }
                ]
            }),
            serde_json::json!({
                "guid": "order-002",
                "businessDate": "2024-01-15",
                "closedDate": "2024-01-15T16:45:00Z",
                "server": {"guid": "server-002", "name": "Bob"},
                "checks": [
                    {
                        "guid": "check-003",
                        "amount": 100.00,
                        "voided": true,
                        "selections": [
                            {"item": "Premium", "qty": 1, "price": 100.00}
                        ]
                    }
                ]
            }),
            serde_json::json!({
                "guid": "order-003",
                "businessDate": "2024-01-16",
                "closedDate": "2024-01-16T09:15:00Z",
                "server": {"guid": "server-001", "name": "Alice"},
                "checks": [
                    {
                        "guid": "check-004",
                        "amount": 15.00,
                        "voided": false,
                        "selections": [
                            {"item": "Button", "qty": 3, "price": 5.00}
                        ]
                    }
                ]
            }),
        ];
        self.data.extend(orders);
        self
    }

    pub fn with_employees(mut self) -> Self {
        let employees = vec![
            serde_json::json!({
                "guid": "server-001",
                "firstName": "Alice",
                "lastName": "Johnson",
                "email": "alice@example.com",
                "jobReferences": [
                    {"guid": "job-001"},
                    {"guid": "job-002"}
                ]
            }),
            serde_json::json!({
                "guid": "server-002",
                "firstName": "Bob",
                "lastName": "Smith",
                "email": "bob@example.com",
                "jobReferences": [
                    {"guid": "job-001"}
                ]
            }),
            serde_json::json!({
                "guid": "server-003",
                "firstName": "Charlie",
                "lastName": "Brown",
                "email": "charlie@example.com",
                "jobReferences": []
            }),
        ];
        self.data.extend(employees);
        self
    }

    pub fn with_jobs(mut self) -> Self {
        let jobs = vec![
            serde_json::json!({
                "guid": "job-001",
                "title": "Server",
                "tipped": true
            }),
            serde_json::json!({
                "guid": "job-002",
                "title": "Manager",
                "tipped": false
            }),
        ];
        self.data.extend(jobs);
        self
    }

    pub fn with_time_entries(mut self) -> Self {
        let entries = vec![
            serde_json::json!({
                "guid": "time-001",
                "employeeReference": {"guid": "server-001"},
                "businessDate": "2024-01-15",
                "inDate": "2024-01-15T08:00:00Z",
                "outDate": "2024-01-15T16:00:00Z",
                "regularHours": 8.0
            }),
            serde_json::json!({
                "guid": "time-002",
                "employeeReference": {"guid": "server-002"},
                "businessDate": "2024-01-15",
                "inDate": "2024-01-15T14:00:00Z",
                "outDate": "2024-01-15T22:00:00Z",
                "regularHours": 8.0
            }),
            serde_json::json!({
                "guid": "time-003",
                "employeeReference": {"guid": "server-001"},
                "businessDate": "2024-01-16",
                "inDate": "2024-01-16T09:00:00Z",
                "outDate": "2024-01-16T17:00:00Z",
                "regularHours": 8.0
            }),
        ];
        self.data.extend(entries);
        self
    }

    pub fn with_primitive_guids(mut self) -> Self {
        // Simulating primitive value records (just GUIDs)
        let guids = vec![
            Value::String("guid-001".to_string()),
            Value::String("guid-002".to_string()),
            Value::String("guid-003".to_string()),
        ];
        self.data.extend(guids);
        self
    }

    pub fn with_nulls_and_missing(mut self) -> Self {
        let data = vec![
            serde_json::json!({"id": 1, "value": 100, "name": "Complete"}),
            serde_json::json!({"id": 2, "value": null, "name": "Null Value"}),
            serde_json::json!({"id": 3, "name": "Missing Value"}),
            serde_json::json!({"id": 4, "value": 0, "name": "Zero Value"}),
        ];
        self.data.extend(data);
        self
    }

    pub fn with_invalid_dates(mut self) -> Self {
        let data = vec![
            serde_json::json!({"timestamp": "2024-01-15T14:30:00Z", "valid": true}),
            serde_json::json!({"timestamp": "invalid-date", "valid": false}),
            serde_json::json!({"timestamp": null, "valid": false}),
            serde_json::json!({"valid": false}),
            serde_json::json!({"timestamp": "", "valid": false}),
        ];
        self.data.extend(data);
        self
    }

    pub fn build(self) -> Vec<Value> {
        self.data
    }
}

impl Default for TestDataBuilder {
    fn default() -> Self {
        Self::new()
    }
}

/// Assert that a query result matches expected structure
#[macro_export]
macro_rules! assert_query_result {
    ($result:expr, columns = $cols:expr, row_count = $count:expr) => {
        assert_eq!($result.columns, $cols, "Column mismatch");
        assert_eq!($result.rows.len(), $count, "Row count mismatch");
    };
}

/// Assert that a specific cell value matches expected
#[macro_export]
macro_rules! assert_cell_eq {
    ($result:expr, row = $row:expr, col = $col:expr, expected = $expected:expr) => {
        let actual = &$result.rows[$row][$col];
        assert_eq!(
            actual, &$expected,
            "Cell mismatch at row {}, col {}: expected {:?}, got {:?}",
            $row, $col, $expected, actual
        );
    };
}

/// Helper to find column index by name
pub fn col_index(result: &crate::query_engine::QueryResult, name: &str) -> Option<usize> {
    result.columns.iter().position(|c| c == name)
}

/// Helper to extract a column's values as a Vec
pub fn get_column_values(
    result: &crate::query_engine::QueryResult,
    col_name: &str,
) -> Option<Vec<Value>> {
    let idx = col_index(result, col_name)?;
    Some(result.rows.iter().map(|row| row[idx].clone()).collect())
}

/// Verify that all values in a column satisfy a predicate
pub fn all_values_satisfy(
    result: &crate::query_engine::QueryResult,
    col_name: &str,
    predicate: impl Fn(&Value) -> bool,
) -> bool {
    if let Some(values) = get_column_values(result, col_name) {
        values.iter().all(|v| predicate(v))
    } else {
        false
    }
}

/// Create a HashMap from key-value pairs for test data
#[macro_export]
macro_rules! hashmap {
    ($($key:expr => $value:expr),*) => {
        {
            let mut map = ::std::collections::HashMap::new();
            $(
                map.insert($key, $value);
            )*
            map
        }
    };
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_create_test_db() {
        let conn = create_test_db();
        // Verify tables exist
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert!(count >= 3); // At least our 3 tables
    }

    #[test]
    fn test_insert_and_retrieve() {
        let conn = create_test_db();
        let data = vec![
            serde_json::json!({"id": 1, "name": "Test"}),
            serde_json::json!({"id": 2, "name": "Test 2"}),
        ];

        let count = insert_test_data(&conn, "test.json", data).unwrap();
        assert_eq!(count, 2);

        let retrieved: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM json_objects WHERE source_file = ?1",
                ["test.json"],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(retrieved, 2);
    }

    #[test]
    fn test_data_builder() {
        let data = TestDataBuilder::new()
            .with_orders()
            .with_employees()
            .build();

        assert_eq!(data.len(), 6); // 3 orders + 3 employees
    }
}
