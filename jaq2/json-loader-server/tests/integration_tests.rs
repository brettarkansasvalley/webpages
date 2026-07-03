//! Integration tests for the JSON Loader Server API
//!
//! These tests use axum-test to make HTTP requests against the full application
//! without starting an actual server. They test:
//! - End-to-end API workflows
//! - Request/response serialization
//! - Error handling at the HTTP layer
//! - Cross-handler state management

use axum::http::StatusCode;
use axum_test::TestClient;
use json_loader_server::{test_utils::*, AppState};
use json_loader_server::create_app;
use serde_json::json;
use std::sync::Arc;
use tower_http::cors::{Any, CorsLayer};

// =========================================================================
// Test Setup
// =========================================================================

/// Create a test app with in-memory database
async fn setup_test_app() -> TestClient {
    let conn = create_test_db();
    let state = Arc::new(AppState::new(conn));
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);
    
    let app = create_app(state, cors);
    TestClient::new(app)
}

/// Create a test app with seeded data
async fn setup_app_with_data(
    source_file: &str,
    data: Vec<serde_json::Value>,
) -> TestClient {
    let conn = create_test_db();
    insert_test_data(&conn, source_file, data).unwrap();
    let state = Arc::new(AppState::new(conn));
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);
    
    let app = create_app(state, cors);
    TestClient::new(app)
}

// =========================================================================
// Health & Basic Endpoint Tests
// =========================================================================

#[tokio::test]
async fn test_root_endpoint_returns_html() {
    let client = setup_test_app().await;
    
    let response = client.get("/").send().await;
    
    assert_eq!(response.status(), StatusCode::OK);
    assert!(response
        .headers()
        .get("content-type")
        .unwrap()
        .to_str()
        .unwrap()
        .contains("text/html"));
}

#[tokio::test]
async fn test_stats_endpoint_empty_db() {
    let client = setup_test_app().await;
    
    let response = client.get("/stats").send().await;
    
    assert_eq!(response.status(), StatusCode::OK);
    
    let body: serde_json::Value = response.json().await;
    assert_eq!(body["total_objects"], 0);
    assert_eq!(body["total_files"], 0);
}

#[tokio::test]
async fn test_stats_endpoint_with_data() {
    let data = TestDataBuilder::new().with_orders().build();
    let client = setup_app_with_data("orders.json", data).await;
    
    let response = client.get("/stats").send().await;
    
    assert_eq!(response.status(), StatusCode::OK);
    
    let body: serde_json::Value = response.json().await;
    assert_eq!(body["total_objects"], 3);
    assert_eq!(body["total_files"], 1);
}

#[tokio::test]
async fn test_files_endpoint_lists_loaded_files() {
    let data = TestDataBuilder::new().with_orders().build();
    let client = setup_app_with_data("orders.json", data).await;
    
    let response = client.get("/files").send().await;
    
    assert_eq!(response.status(), StatusCode::OK);
    
    let body: Vec<String> = response.json().await;
    assert_eq!(body.len(), 1);
    assert_eq!(body[0], "orders.json");
}

// =========================================================================
// Simple Query Endpoint Tests
// =========================================================================

#[tokio::test]
async fn test_query_endpoint_no_filter() {
    let data = TestDataBuilder::new().with_orders().build();
    let client = setup_app_with_data("orders.json", data).await;
    
    let response = client
        .get("/query?limit=2")
        .send()
        .await;
    
    assert_eq!(response.status(), StatusCode::OK);
    
    let body: Vec<serde_json::Value> = response.json().await;
    assert_eq!(body.len(), 2);
}

#[tokio::test]
async fn test_query_endpoint_with_filter() {
    let data = TestDataBuilder::new().with_orders().build();
    let client = setup_app_with_data("orders.json", data).await;
    
    // Filter using JAQ syntax
    let response = client
        .get("/query?filter=.guid%20%7C%20contains%28%22order-001%22%29")
        .send()
        .await;
    
    assert_eq!(response.status(), StatusCode::OK);
    
    let body: Vec<serde_json::Value> = response.json().await;
    assert_eq!(body.len(), 1);
    let json_data: serde_json::Value = 
        serde_json::from_str(body[0]["json_data"].as_str().unwrap()).unwrap();
    assert_eq!(json_data["guid"], "order-001");
}

#[tokio::test]
async fn test_query_endpoint_with_source_file() {
    let conn = create_test_db();
    let orders = TestDataBuilder::new().with_orders().build();
    let employees = TestDataBuilder::new().with_employees().build();
    insert_test_data(&conn, "orders.json", orders).unwrap();
    insert_test_data(&conn, "employees.json", employees).unwrap();
    
    let state = Arc::new(AppState::new(conn));
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);
    let app = create_app(state, cors);
    let client = TestClient::new(app);
    
    let response = client
        .get("/query?source_file=orders.json&limit=10")
        .send()
        .await;
    
    assert_eq!(response.status(), StatusCode::OK);
    
    let body: Vec<serde_json::Value> = response.json().await;
    assert_eq!(body.len(), 3); // Only orders, not employees
}

// =========================================================================
// DSL Query Endpoint Tests
// =========================================================================

#[tokio::test]
async fn test_dsl_query_simple_select() {
    let data = TestDataBuilder::new().with_orders().build();
    let client = setup_app_with_data("orders.json", data).await;
    
    let query = json!({
        "query": r#"{"from": {"source_file": "orders.json", "alias": "o"}, "select": [{"expr": "o.guid", "alias": "guid"}, {"expr": "o.businessDate", "alias": "date"}]}"#
    });
    
    let response = client
        .post("/query/dsl")
        .json(&query)
        .send()
        .await;
    
    assert_eq!(response.status(), StatusCode::OK);
    
    let body: serde_json::Value = response.json().await;
    assert_eq!(body["headers"], json!(["guid", "date"]));
    assert_eq!(body["rows"].as_array().unwrap().len(), 3);
    assert_eq!(body["total_count"], 3);
}

#[tokio::test]
async fn test_dsl_query_with_where_filter() {
    let data = TestDataBuilder::new().with_orders().build();
    let client = setup_app_with_data("orders.json", data).await;
    
    let query = json!({
        "query": r#"{"from": {"source_file": "orders.json", "alias": "o"}, "where": [{"field": "o.businessDate", "op": "=", "value": "2024-01-15"}], "select": [{"expr": "o.guid", "alias": "guid"}]}"#
    });
    
    let response = client
        .post("/query/dsl")
        .json(&query)
        .send()
        .await;
    
    assert_eq!(response.status(), StatusCode::OK);
    
    let body: serde_json::Value = response.json().await;
    assert_eq!(body["rows"].as_array().unwrap().len(), 2); // Two orders on 2024-01-15
}

#[tokio::test]
async fn test_dsl_query_with_join() {
    let conn = create_test_db();
    let orders = TestDataBuilder::new().with_orders().build();
    let employees = TestDataBuilder::new().with_employees().build();
    insert_test_data(&conn, "orders.json", orders).unwrap();
    insert_test_data(&conn, "employees.json", employees).unwrap();
    
    let state = Arc::new(AppState::new(conn));
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);
    let app = create_app(state, cors);
    let client = TestClient::new(app);
    
    let query = json!({
        "query": r#"{"from": {"source_file": "orders.json", "alias": "o"}, "joins": [{"source": {"source_file": "employees.json", "alias": "e"}, "on": {"left": "o.server.guid", "right": "e.guid"}, "join_type": "inner"}], "select": [{"expr": "o.guid", "alias": "order_guid"}, {"expr": "e.firstName", "alias": "server_name"}]}"#
    });
    
    let response = client
        .post("/query/dsl")
        .json(&query)
        .send()
        .await;
    
    assert_eq!(response.status(), StatusCode::OK);
    
    let body: serde_json::Value = response.json().await;
    assert_eq!(body["rows"].as_array().unwrap().len(), 3);
    
    // Verify the join worked - should have server names
    let rows = body["rows"].as_array().unwrap();
    let names: Vec<&str> = rows
        .iter()
        .map(|r| r[1].as_str().unwrap())
        .collect();
    assert!(names.contains(&"Alice"));
    assert!(names.contains(&"Bob"));
}

#[tokio::test]
async fn test_dsl_query_with_group_by() {
    let data = TestDataBuilder::new().with_orders().build();
    let client = setup_app_with_data("orders.json", data).await;
    
    let query = json!({
        "query": r#"{"from": {"source_file": "orders.json", "alias": "o"}, "group_by": [{"field": "o.businessDate"}], "select": [{"expr": "o.businessDate", "alias": "date"}, {"expr": "count(o.guid)", "alias": "order_count", "agg": "count"}]}"#
    });
    
    let response = client
        .post("/query/dsl")
        .json(&query)
        .send()
        .await;
    
    assert_eq!(response.status(), StatusCode::OK);
    
    let body: serde_json::Value = response.json().await;
    let rows = body["rows"].as_array().unwrap();
    assert_eq!(rows.len(), 2); // Two dates
}

#[tokio::test]
async fn test_dsl_query_invalid_json_returns_400() {
    let client = setup_test_app().await;
    
    let query = json!({
        "query": "this is not valid json"
    });
    
    let response = client
        .post("/query/dsl")
        .json(&query)
        .send()
        .await;
    
    // Should return 400 Bad Request, not 500
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn test_dsl_query_nonexistent_source_file() {
    let client = setup_test_app().await;
    
    let query = json!({
        "query": r#"{"from": {"source_file": "nonexistent.json", "alias": "n"}, "select": [{"expr": "n.id", "alias": "id"}]}"#
    });
    
    let response = client
        .post("/query/dsl")
        .json(&query)
        .send()
        .await;
    
    // Returns empty result, not error
    assert_eq!(response.status(), StatusCode::OK);
    
    let body: serde_json::Value = response.json().await;
    assert_eq!(body["rows"].as_array().unwrap().len(), 0);
}

// =========================================================================
// Schema Endpoint Tests
// =========================================================================

#[tokio::test]
async fn test_schema_endpoint() {
    let data = TestDataBuilder::new().with_orders().build();
    let client = setup_app_with_data("orders.json", data).await;
    
    let response = client
        .get("/schema?source_file=orders.json")
        .send()
        .await;
    
    assert_eq!(response.status(), StatusCode::OK);
    
    let body: serde_json::Value = response.json().await;
    assert_eq!(body["source_file"], "orders.json");
    assert_eq!(body["total_objects"], 3);
    
    let fields = body["fields"].as_array().unwrap();
    assert!(!fields.is_empty());
    
    // Should have field info for 'guid', 'businessDate', etc.
    let field_names: Vec<&str> = fields
        .iter()
        .map(|f| f["name"].as_str().unwrap())
        .collect();
    assert!(field_names.contains(&"guid"));
    assert!(field_names.contains(&"businessDate"));
}

#[tokio::test]
async fn test_schema_endpoint_not_found() {
    let client = setup_test_app().await;
    
    let response = client
        .get("/schema?source_file=nonexistent.json")
        .send()
        .await;
    
    assert_eq!(response.status(), StatusCode::NOT_FOUND);
}

// =========================================================================
// Join Analysis Endpoint Tests
// =========================================================================

#[tokio::test]
async fn test_join_analysis_endpoint() {
    let conn = create_test_db();
    let orders = TestDataBuilder::new().with_orders().build();
    let employees = TestDataBuilder::new().with_employees().build();
    insert_test_data(&conn, "orders.json", orders).unwrap();
    insert_test_data(&conn, "employees.json", employees).unwrap();
    
    let state = Arc::new(AppState::new(conn));
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);
    let app = create_app(state, cors);
    let client = TestClient::new(app);
    
    let response = client.get("/join-analysis").send().await;
    
    assert_eq!(response.status(), StatusCode::OK);
    
    let body: serde_json::Value = response.json().await;
    let suggestions = body["suggestions"].as_array().unwrap();
    
    // Should find join suggestions between orders and employees
    assert!(!suggestions.is_empty());
}

// =========================================================================
// Export Endpoint Tests
// =========================================================================

#[tokio::test]
async fn test_export_csv() {
    let data = TestDataBuilder::new().with_orders().build();
    let client = setup_app_with_data("orders.json", data).await;
    
    let export_request = json!({
        "query": r#"{"from": {"source_file": "orders.json", "alias": "o"}, "select": [{"expr": "o.guid", "alias": "guid"}, {"expr": "o.businessDate", "alias": "date"}], "limit": 2}"#,
        "format": "csv",
        "filename": "test_export"
    });
    
    let response = client
        .post("/export")
        .json(&export_request)
        .send()
        .await;
    
    assert_eq!(response.status(), StatusCode::OK);
    assert!(response
        .headers()
        .get("content-type")
        .unwrap()
        .to_str()
        .unwrap()
        .contains("text/csv"));
    
    let body = response.text().await;
    assert!(body.contains("guid,date")); // CSV header
    assert!(body.contains("order-001")); // Data row
}

#[tokio::test]
async fn test_export_jsonl() {
    let data = TestDataBuilder::new().with_orders().build();
    let client = setup_app_with_data("orders.json", data).await;
    
    let export_request = json!({
        "query": r#"{"from": {"source_file": "orders.json", "alias": "o"}, "select": [{"expr": "o.guid", "alias": "guid"}], "limit": 2}"#,
        "format": "jsonl",
        "filename": "test_export"
    });
    
    let response = client
        .post("/export")
        .json(&export_request)
        .send()
        .await;
    
    assert_eq!(response.status(), StatusCode::OK);
    
    let body = response.text().await;
    let lines: Vec<&str> = body.lines().collect();
    assert_eq!(lines.len(), 2); // 2 JSON lines
    
    // Verify each line is valid JSON
    for line in lines {
        let _: serde_json::Value = serde_json::from_str(line).unwrap();
    }
}

// =========================================================================
// Saved Queries Endpoint Tests
// =========================================================================

#[tokio::test]
async fn test_saved_queries_crud() {
    let client = setup_test_app().await;
    
    // 1. List saved queries (should be empty)
    let response = client.get("/queries").send().await;
    assert_eq!(response.status(), StatusCode::OK);
    let body: Vec<serde_json::Value> = response.json().await;
    assert!(body.is_empty());
    
    // 2. Save a query
    let save_request = json!({
        "name": "Test Query",
        "description": "A test query",
        "query": r#"{"from": {"source_file": "test.json", "alias": "t"}, "select": [{"expr": "t.id", "alias": "id"}]}"#
    });
    
    let response = client
        .post("/queries")
        .json(&save_request)
        .send()
        .await;
    assert_eq!(response.status(), StatusCode::OK);
    
    // 3. List saved queries (should have 1)
    let response = client.get("/queries").send().await;
    let body: Vec<serde_json::Value> = response.json().await;
    assert_eq!(body.len(), 1);
    assert_eq!(body[0]["name"], "Test Query");
    
    let query_id = body[0]["id"].as_i64().unwrap();
    
    // 4. Delete the query
    let response = client
        .delete(&format!("/queries/{}" , query_id))
        .send()
        .await;
    assert_eq!(response.status(), StatusCode::OK);
    
    // 5. List saved queries (should be empty again)
    let response = client.get("/queries").send().await;
    let body: Vec<serde_json::Value> = response.json().await;
    assert!(body.is_empty());
}

// =========================================================================
// Concurrent Request Tests
// =========================================================================

#[tokio::test]
async fn test_concurrent_queries() {
    let data = TestDataBuilder::new().with_orders().build();
    let client = setup_app_with_data("orders.json", data).await;
    
    // Spawn 10 concurrent requests
    let mut handles = vec![];
    
    for i in 0..10 {
        let client = client.clone();
        let handle = tokio::spawn(async move {
            let query = json!({
                "query": format!(
                    r#"{{"from": {{"source_file": "orders.json", "alias": "o"}}, "select": [{{"expr": "o.guid", "alias": "guid"}}], "limit": {}}}"#,
                    i + 1
                )
            });
            
            client
                .post("/query/dsl")
                .json(&query)
                .send()
                .await
        });
        handles.push(handle);
    }
    
    // All should complete successfully
    for handle in handles {
        let response = handle.await.unwrap();
        assert_eq!(response.status(), StatusCode::OK);
    }
}

// =========================================================================
// Error Handling Tests
// =========================================================================

#[tokio::test]
async fn test_invalid_dsl_syntax() {
    let client = setup_test_app().await;
    
    let query = json!({
        "query": r#"{"from": "not an object", "select": []}"#  // Invalid: from should be object
    });
    
    let response = client
        .post("/query/dsl")
        .json(&query)
        .send()
        .await;
    
    // Should handle gracefully
    assert!(response.status().is_success() || response.status().is_client_error());
}

#[tokio::test]
async fn test_missing_required_fields() {
    let client = setup_test_app().await;
    
    // Missing 'query' field entirely
    let query = json!({});
    
    let response = client
        .post("/query/dsl")
        .json(&query)
        .send()
        .await;
    
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}
