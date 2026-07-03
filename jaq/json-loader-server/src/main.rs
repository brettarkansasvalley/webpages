use anyhow::{Context, Result};
use axum::{
    extract::{Path, Query, State},
    http::{header, StatusCode},
    response::{Html, IntoResponse, Response},
    routing::{delete, get, post},
    Json, Router,
};
use chrono;
use jaq_all::data;
use jaq_core::Vars;
use jaq_json::{Map as JaqMap, Tag, Val};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::{
    collections::HashMap,
    fs,
    path::Path as StdPath,
    rc::Rc,
    sync::{Arc, Mutex},
};
use tower_http::cors::{Any, CorsLayer};
use tracing::info;
use tracing_subscriber;

mod query_engine;
use query_engine::execute_query;

const JSON_DIR: &str = "/home/ubuntu/jaq/loadjson";
const DB_PATH: &str = "/home/ubuntu/jaq/json-loader-server/database.db";

#[derive(Debug, Clone, Serialize, Deserialize)]
struct JsonObject {
    id: i64,
    json_data: String,
    source_file: String,
    modified_at: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct LoadResult {
    loaded_files: Vec<String>,
    total_objects: usize,
    errors: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct QueryRequest {
    filter: Option<String>,
    source_file: Option<String>,
    limit: Option<i32>,
}

// Saved Query structs
#[derive(Debug, Serialize, Deserialize)]
struct SavedQuery {
    id: Option<i64>,
    name: String,
    description: Option<String>,
    query_json: String,
    created_at: Option<String>,
}

#[derive(Debug, Deserialize)]
struct SaveQueryRequest {
    name: String,
    description: Option<String>,
    query: String,
}

// Query History structs
#[derive(Debug, Serialize)]
struct QueryHistory {
    id: i64,
    query_json: String,
    query_type: String,
    source_tab: Option<String>,
    result_count: Option<i64>,
    created_at: String,
}

#[derive(Debug, Deserialize)]
struct SaveHistoryRequest {
    query: String,
    query_type: Option<String>,
    source_tab: Option<String>,
    result_count: Option<i64>,
}

// Query Notes structs
#[derive(Debug, Serialize, Deserialize)]
struct QueryNote {
    id: i64,
    query_hash: String,
    full_query: Option<String>,
    row_hash: String,
    note_text: String,
    created_at: String,
    updated_at: String,
}

#[derive(Debug, Deserialize)]
struct SaveNoteRequest {
    query_hash: String,
    full_query: Option<String>,
    row_hash: String,
    note_text: String,
}

#[derive(Debug, Serialize)]
struct NotesResponse {
    notes: Vec<QueryNote>,
}

// Schema and Field Discovery structs
#[derive(Debug, Serialize)]
struct FieldInfo {
    name: String,
    field_type: String, // "string", "number", "boolean", "array", "object", "null"
    sample_values: Vec<serde_json::Value>,
    unique_count: Option<usize>,
    null_count: usize,
}

#[derive(Debug, Serialize)]
struct SchemaResponse {
    source_file: String,
    total_objects: usize,
    fields: Vec<FieldInfo>,
}

#[derive(Debug, Serialize)]
struct JoinSuggestion {
    left_source: String,
    left_field: String,
    right_source: String,
    right_field: String,
    match_count: usize,
    left_total: usize,
    right_total: usize,
    match_percentage: f64,
    join_type_hint: String, // "one-to-one", "one-to-many", "many-to-many"
}

#[derive(Debug, Serialize)]
struct JoinAnalysisResponse {
    suggestions: Vec<JoinSuggestion>,
}

#[derive(Clone)]
struct AppState {
    db: Arc<Mutex<Connection>>,
}

async fn load_json_files(
    State(state): State<Arc<AppState>>,
) -> Result<Json<LoadResult>, StatusCode> {
    let load_dir = StdPath::new(JSON_DIR);

    if !load_dir.exists() {
        return Err(StatusCode::NOT_FOUND);
    }

    let mut loaded_files = Vec::new();
    let mut skipped_files = Vec::new();
    let mut total_objects = 0usize;
    let mut errors = Vec::new();

    let entries = match fs::read_dir(load_dir) {
        Ok(e) => e,
        Err(_e) => {
            return Err(StatusCode::INTERNAL_SERVER_ERROR);
        }
    };

    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().map(|e| e != "json").unwrap_or(true) {
            continue;
        }

        let file_name = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("unknown")
            .to_string();

        let metadata = match fs::metadata(&path) {
            Ok(m) => m,
            Err(e) => {
                errors.push(format!("Error getting metadata for {}: {}", file_name, e));
                continue;
            }
        };

        let modified_at = metadata
            .modified()
            .ok()
            .and_then(|t| {
                let duration = t.duration_since(std::time::UNIX_EPOCH).ok()?;
                Some(duration.as_secs().to_string())
            })
            .unwrap_or_else(|| "0".to_string());

        // Check if this file with this modified_at timestamp already exists in the database
        let should_skip = {
            let db = state.db.lock().unwrap();
            let count: i64 = db
                .query_row(
                    "SELECT COUNT(*) FROM json_objects WHERE source_file = ?1 AND modified_at = ?2",
                    params![&file_name, &modified_at],
                    |row| row.get(0),
                )
                .unwrap_or(0);
            count > 0
        };

        if should_skip {
            skipped_files.push(file_name);
            continue;
        }

        // File is new or has been modified - need to load it
        let content = match fs::read_to_string(&path) {
            Ok(c) => c,
            Err(e) => {
                errors.push(format!("Error reading file {}: {}", file_name, e));
                continue;
            }
        };

        let json_array: Vec<serde_json::Value> = match serde_json::from_str(&content) {
            Ok(arr) => arr,
            Err(e) => {
                errors.push(format!("Error parsing JSON from {}: {}", file_name, e));
                continue;
            }
        };

        let mut db = state.db.lock().unwrap();

        // Clear existing records for this file before reloading (to prevent duplicates)
        if let Err(e) = db.execute(
            "DELETE FROM json_objects WHERE source_file = ?1",
            params![&file_name],
        ) {
            errors.push(format!(
                "Error clearing existing data for {}: {}",
                file_name, e
            ));
            continue;
        }

        let transaction = match db.transaction() {
            Ok(t) => t,
            Err(e) => {
                errors.push(format!(
                    "Error starting transaction for {}: {}",
                    file_name, e
                ));
                continue;
            }
        };

        let mut inserted = 0;
        for json_value in json_array {
            let json_str = serde_json::to_string(&json_value).unwrap_or_default();

            match transaction.execute(
                "INSERT INTO json_objects (json_data, source_file, modified_at) VALUES (?1, ?2, ?3)",
                params![&json_str, &file_name, &modified_at],
            ) {
                Ok(rows) => inserted += rows,
                Err(e) => {
                    errors.push(format!("Error inserting object from {}: {}", file_name, e));
                }
            }
        }

        if let Err(e) = transaction.commit() {
            errors.push(format!(
                "Error committing transaction for {}: {}",
                file_name, e
            ));
            continue;
        }

        loaded_files.push(file_name);
        total_objects += inserted;
    }

    // Add skip info to errors for visibility
    if !skipped_files.is_empty() {
        errors.push(format!(
            "Skipped {} unchanged file(s): {}",
            skipped_files.len(),
            skipped_files.join(", ")
        ));
    }

    Ok(Json(LoadResult {
        loaded_files,
        total_objects,
        errors,
    }))
}

async fn get_stats(
    State(state): State<Arc<AppState>>,
) -> Result<Json<HashMap<String, i64>>, StatusCode> {
    let db = state.db.lock().unwrap();

    let total_objects: i64 = db
        .query_row("SELECT COUNT(*) FROM json_objects", [], |row| row.get(0))
        .unwrap_or(0);

    let total_files: i64 = db
        .query_row(
            "SELECT COUNT(DISTINCT source_file) FROM json_objects",
            [],
            |row| row.get(0),
        )
        .unwrap_or(0);

    let mut stats = HashMap::new();
    stats.insert("total_objects".to_string(), total_objects);
    stats.insert("total_files".to_string(), total_files);

    Ok(Json(stats))
}

async fn get_files(State(state): State<Arc<AppState>>) -> Result<Json<Vec<String>>, StatusCode> {
    let db = state.db.lock().unwrap();

    let mut stmt =
        match db.prepare("SELECT DISTINCT source_file FROM json_objects ORDER BY source_file") {
            Ok(s) => s,
            Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
        };

    let files: Vec<String> = match stmt.query_map([], |row| row.get(0)) {
        Ok(rows) => rows.filter_map(|r| r.ok()).collect(),
        Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
    };

    Ok(Json(files))
}

async fn query_objects(
    State(state): State<Arc<AppState>>,
    Query(params): Query<QueryRequest>,
) -> Result<Json<Vec<JsonObject>>, StatusCode> {
    let db = state.db.lock().unwrap();

    let mut query =
        "SELECT id, json_data, source_file, modified_at FROM json_objects WHERE 1=1".to_string();
    let mut db_params: Vec<String> = Vec::new();

    if let Some(file) = params.source_file {
        query.push_str(" AND source_file = ?");
        db_params.push(file);
    }

    if let Some(limit) = params.limit {
        query.push_str(&format!(" LIMIT {}", limit));
    }

    let mut stmt = match db.prepare(&query) {
        Ok(s) => s,
        Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
    };

    let objects: Vec<JsonObject> =
        match stmt.query_map(rusqlite::params_from_iter(db_params), |row| {
            Ok(JsonObject {
                id: row.get(0)?,
                json_data: row.get(1)?,
                source_file: row.get(2)?,
                modified_at: row.get(3)?,
            })
        }) {
            Ok(rows) => rows.filter_map(|r| r.ok()).collect(),
            Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
        };

    // Apply jaq filter if provided
    let objects = if let Some(filter_str) = params.filter {
        match apply_jaq_filter(objects, &filter_str) {
            Ok(filtered) => filtered,
            Err(e) => {
                eprintln!("JAQ filter error: {}", e);
                vec![]
            }
        }
    } else {
        objects
    };

    Ok(Json(objects))
}

#[derive(Debug, Deserialize)]
struct QueryDslRequest {
    query: String,
    #[serde(default)]
    format: Option<String>, // "default", "json", "jsonl"
}

// Export request structs
#[derive(Debug, Deserialize)]
struct ExportRequest {
    query: String,
    format: ExportFormat,
    filename: Option<String>,
}

#[derive(Debug, Deserialize, Clone, Copy)]
#[serde(rename_all = "lowercase")]
enum ExportFormat {
    Csv,
    #[cfg(feature = "xlsx")]
    Xlsx,
    Parquet,
    Jsonl,
}

#[derive(Debug, Serialize)]
struct QueryDslResponse {
    success: bool,
    columns: Vec<String>,
    rows: Vec<Vec<serde_json::Value>>,
    total_count: usize,
    error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    performance: Option<QueryPerformanceMetrics>,
}

#[derive(Debug, Serialize)]
struct QueryPerformanceMetrics {
    execution_time_ms: u64,
    rows_scanned: usize,
    rows_returned: usize,
    query_plan: String,
}

fn rows_to_objects(
    columns: &[String],
    rows: &[Vec<serde_json::Value>],
) -> Vec<serde_json::Map<String, serde_json::Value>> {
    rows.iter()
        .map(|row| {
            let mut obj = serde_json::Map::new();
            for (i, col) in columns.iter().enumerate() {
                let value = row.get(i).cloned().unwrap_or(serde_json::Value::Null);
                obj.insert(col.clone(), value);
            }
            obj
        })
        .collect()
}

async fn query_dsl(
    State(state): State<Arc<AppState>>,
    Json(request): Json<QueryDslRequest>,
) -> Result<Response, StatusCode> {
    use std::time::Instant;

    let start_time = Instant::now();
    let db = state.db.lock().unwrap();

    // Get row count before query (for scan stats)
    let total_db_rows: usize = db
        .query_row("SELECT COUNT(*) FROM json_objects", [], |row| row.get(0))
        .unwrap_or(0);

    match execute_query(&db, &request.query) {
        Ok(result) => {
            let execution_time = start_time.elapsed().as_millis() as u64;
            let rows_returned = result.rows.len();

            // Generate simple query plan description
            let query_plan = if request.query.contains("join") || request.query.contains("JOIN") {
                format!(
                    "Table scan + Join operations (scanned ~{} rows)",
                    total_db_rows
                )
            } else {
                format!("Table scan (scanned ~{} rows)", total_db_rows)
            };

            let performance = Some(QueryPerformanceMetrics {
                execution_time_ms: execution_time,
                rows_scanned: total_db_rows,
                rows_returned,
                query_plan,
            });

            let format = request.format.as_deref().unwrap_or("default");

            match format {
                "json" => {
                    // Return array of objects with performance metadata
                    let mut response = serde_json::Map::new();
                    response.insert(
                        "data".to_string(),
                        serde_json::to_value(rows_to_objects(&result.columns, &result.rows))
                            .unwrap_or_default(),
                    );
                    response.insert(
                        "performance".to_string(),
                        serde_json::to_value(performance).unwrap_or_default(),
                    );
                    Ok((
                        [(header::CONTENT_TYPE, "application/json")],
                        serde_json::to_string(&response).unwrap_or_default(),
                    )
                        .into_response())
                }
                "jsonl" => {
                    // Return JSON lines (no performance metadata in this format)
                    let objects = rows_to_objects(&result.columns, &result.rows);
                    let lines: Vec<String> = objects
                        .into_iter()
                        .map(|obj| serde_json::to_string(&obj).unwrap_or_default())
                        .collect();
                    let body = lines.join("\n");
                    Ok(([(header::CONTENT_TYPE, "application/x-ndjson")], body).into_response())
                }
                _ => {
                    // Default format
                    Ok(Json(QueryDslResponse {
                        success: true,
                        columns: result.columns,
                        rows: result.rows,
                        total_count: result.total_count,
                        error: None,
                        performance,
                    })
                    .into_response())
                }
            }
        }
        Err(e) => {
            let format = request.format.as_deref().unwrap_or("default");
            match format {
                "json" | "jsonl" => {
                    Ok((StatusCode::BAD_REQUEST, format!("Error: {}", e)).into_response())
                }
                _ => Ok(Json(QueryDslResponse {
                    success: false,
                    columns: vec![],
                    rows: vec![],
                    total_count: 0,
                    error: Some(e.to_string()),
                    performance: None,
                })
                .into_response()),
            }
        }
    }
}

#[derive(Debug, Serialize)]
struct QueryWithNotesResponse {
    success: bool,
    query_hash: String,
    columns: Vec<String>,
    rows: Vec<Vec<serde_json::Value>>,
    notes: HashMap<String, QueryNote>,
    total_count: usize,
    error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    performance: Option<QueryPerformanceMetrics>,
}

async fn query_dsl_with_notes(
    State(state): State<Arc<AppState>>,
    Json(request): Json<QueryDslRequest>,
) -> Result<Json<QueryWithNotesResponse>, StatusCode> {
    use std::time::Instant;

    let start_time = Instant::now();
    let db = state.db.lock().unwrap();

    // Get row count before query (for scan stats)
    let total_db_rows: usize = db
        .query_row("SELECT COUNT(*) FROM json_objects", [], |row| row.get(0))
        .unwrap_or(0);

    // Generate query hash
    let query_hash = generate_query_hash(&request.query);

    match execute_query(&db, &request.query) {
        Ok(result) => {
            let execution_time = start_time.elapsed().as_millis() as u64;
            let rows_returned = result.rows.len();

            // Generate simple query plan description
            let query_plan = if request.query.contains("join") || request.query.contains("JOIN") {
                format!(
                    "Table scan + Join operations (scanned ~{} rows)",
                    total_db_rows
                )
            } else {
                format!("Table scan (scanned ~{} rows)", total_db_rows)
            };

            let performance = Some(QueryPerformanceMetrics {
                execution_time_ms: execution_time,
                rows_scanned: total_db_rows,
                rows_returned,
                query_plan,
            });

            // Fetch all notes for this query
            let notes: HashMap<String, QueryNote> = match db.prepare(
                "SELECT id, query_hash, full_query, row_hash, note_text, created_at, updated_at 
                 FROM query_notes WHERE query_hash = ?1",
            ) {
                Ok(mut stmt) => {
                    match stmt.query_map(params![&query_hash], |row| {
                        Ok(QueryNote {
                            id: row.get(0)?,
                            query_hash: row.get(1)?,
                            full_query: row.get(2)?,
                            row_hash: row.get(3)?,
                            note_text: row.get(4)?,
                            created_at: row.get(5)?,
                            updated_at: row.get(6)?,
                        })
                    }) {
                        Ok(rows) => rows
                            .filter_map(|r| r.ok())
                            .map(|n| (n.row_hash.clone(), n))
                            .collect(),
                        Err(_) => HashMap::new(),
                    }
                }
                Err(_) => HashMap::new(),
            };

            Ok(Json(QueryWithNotesResponse {
                success: true,
                query_hash,
                columns: result.columns,
                rows: result.rows,
                notes,
                total_count: result.total_count,
                error: None,
                performance,
            }))
        }
        Err(e) => Ok(Json(QueryWithNotesResponse {
            success: false,
            query_hash,
            columns: vec![],
            rows: vec![],
            notes: HashMap::new(),
            total_count: 0,
            error: Some(e.to_string()),
            performance: None,
        })),
    }
}

// Export handler
async fn export_data(
    State(state): State<Arc<AppState>>,
    Json(request): Json<ExportRequest>,
) -> Result<Response, StatusCode> {
    let db = state.db.lock().unwrap();

    match execute_query(&db, &request.query) {
        Ok(result) => {
            let filename = request.filename.unwrap_or_else(|| {
                format!(
                    "jaq_export_{}",
                    chrono::Local::now().format("%Y%m%d_%H%M%S")
                )
            });

            match request.format {
                ExportFormat::Csv => export_to_csv(&result, &filename),
                #[cfg(feature = "xlsx")]
                ExportFormat::Xlsx => export_to_xlsx(&result, &filename),
                ExportFormat::Parquet => export_to_parquet(&result, &filename),
                ExportFormat::Jsonl => export_to_jsonl(&result, &filename),
            }
        }
        Err(e) => Ok((StatusCode::BAD_REQUEST, format!("Export error: {}", e)).into_response()),
    }
}

fn export_to_csv(
    result: &query_engine::QueryResult,
    filename: &str,
) -> Result<Response, StatusCode> {
    let mut wtr = csv::WriterBuilder::new()
        .quote_style(csv::QuoteStyle::Necessary)
        .from_writer(vec![]);

    // Write headers
    wtr.write_record(&result.columns)
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

    // Write rows
    for row in &result.rows {
        let record: Vec<String> = row
            .iter()
            .map(|cell| match cell {
                serde_json::Value::Null => String::new(),
                serde_json::Value::String(s) => s.clone(),
                serde_json::Value::Number(n) => n.to_string(),
                serde_json::Value::Bool(b) => b.to_string(),
                _ => cell.to_string(),
            })
            .collect();
        wtr.write_record(&record)
            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    }

    let data = wtr
        .into_inner()
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

    Ok((
        [
            (header::CONTENT_TYPE, "text/csv; charset=utf-8"),
            (
                header::CONTENT_DISPOSITION,
                &format!("attachment; filename=\"{}.csv\"", filename),
            ),
        ],
        data,
    )
        .into_response())
}

#[cfg(feature = "xlsx")]
fn export_to_xlsx(
    result: &query_engine::QueryResult,
    filename: &str,
) -> Result<Response, StatusCode> {
    use std::io::Read;
    use xlsxwriter::{format::FormatColor, Format, Workbook};

    let temp_path = format!("/tmp/{}.xlsx", filename);

    {
        let workbook = Workbook::new(&temp_path).map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
        let mut worksheet = workbook
            .add_worksheet(None)
            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

        // Create header format
        let mut header_format = Format::new();
        header_format.set_bold();
        header_format.set_bg_color(FormatColor::Custom(0xDDDDDD));

        // Write headers
        for (col_idx, col) in result.columns.iter().enumerate() {
            worksheet
                .write_string(0, col_idx as u16, col, Some(&header_format))
                .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
        }

        // Write data rows
        for (row_idx, row) in result.rows.iter().enumerate() {
            for (col_idx, cell) in row.iter().enumerate() {
                match cell {
                    serde_json::Value::Null => {}
                    serde_json::Value::String(s) => {
                        worksheet
                            .write_string((row_idx + 1) as u32, col_idx as u16, s, None)
                            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
                    }
                    serde_json::Value::Number(n) => {
                        if let Some(i) = n.as_i64() {
                            worksheet
                                .write_number((row_idx + 1) as u32, col_idx as u16, i as f64, None)
                                .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
                        } else if let Some(f) = n.as_f64() {
                            worksheet
                                .write_number((row_idx + 1) as u32, col_idx as u16, f, None)
                                .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
                        }
                    }
                    serde_json::Value::Bool(b) => {
                        worksheet
                            .write_string(
                                (row_idx + 1) as u32,
                                col_idx as u16,
                                &b.to_string(),
                                None,
                            )
                            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
                    }
                    _ => {
                        worksheet
                            .write_string(
                                (row_idx + 1) as u32,
                                col_idx as u16,
                                &cell.to_string(),
                                None,
                            )
                            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
                    }
                }
            }
        }

        // Auto-filter for headers
        if !result.columns.is_empty() && !result.rows.is_empty() {
            let last_col = (result.columns.len() - 1) as u16;
            let last_row = result.rows.len() as u32;
            worksheet
                .autofilter(0, 0, last_row as u32, last_col)
                .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
        }

        // Close workbook
        workbook
            .close()
            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    }

    // Read file into memory
    let mut file =
        std::fs::File::open(&temp_path).map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    let mut data = Vec::new();
    file.read_to_end(&mut data)
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

    // Clean up temp file
    let _ = std::fs::remove_file(&temp_path);

    Ok((
        [
            (
                header::CONTENT_TYPE,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            (
                header::CONTENT_DISPOSITION,
                &format!("attachment; filename=\"{}.xlsx\"", filename),
            ),
        ],
        data,
    )
        .into_response())
}

#[cfg(not(feature = "xlsx"))]
fn export_to_xlsx(
    _result: &query_engine::QueryResult,
    _filename: &str,
) -> Result<Response, StatusCode> {
    Err(StatusCode::NOT_IMPLEMENTED)
}

fn export_to_parquet(
    result: &query_engine::QueryResult,
    filename: &str,
) -> Result<Response, StatusCode> {
    // Parquet export is not implemented due to dependency complexity
    // Fall back to JSONL format which is also efficient for large datasets
    export_to_jsonl(result, filename)
}

fn export_to_jsonl(
    result: &query_engine::QueryResult,
    filename: &str,
) -> Result<Response, StatusCode> {
    let mut lines = Vec::new();

    for row in &result.rows {
        let mut obj = serde_json::Map::new();
        for (i, col) in result.columns.iter().enumerate() {
            let value = row.get(i).cloned().unwrap_or(serde_json::Value::Null);
            obj.insert(col.clone(), value);
        }
        lines.push(serde_json::to_string(&obj).unwrap_or_default());
    }

    let data = lines.join("\n").into_bytes();

    Ok((
        [
            (header::CONTENT_TYPE, "application/x-ndjson"),
            (
                header::CONTENT_DISPOSITION,
                &format!("attachment; filename=\"{}.jsonl\"", filename),
            ),
        ],
        data,
    )
        .into_response())
}

// Helper function to generate row hash from a row's key columns
fn generate_row_hash(row: &[serde_json::Value], key_column_indices: &[usize]) -> String {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};

    let mut hasher = DefaultHasher::new();
    for &idx in key_column_indices {
        if let Some(value) = row.get(idx) {
            value.to_string().hash(&mut hasher);
        }
    }
    format!("{:x}", hasher.finish())
}

fn apply_jaq_filter(objects: Vec<JsonObject>, filter_str: &str) -> Result<Vec<JsonObject>> {
    use bytes::Bytes;
    use jaq_json::Num;

    let filter = data::compile(filter_str)
        .map_err(|e| anyhow::anyhow!("Filter compilation error: {:?}", e))?;

    let runner = Default::default();
    let vars = Vars::new(std::iter::empty());

    let mut results = Vec::new();

    for obj in objects {
        let json_value: serde_json::Value = match serde_json::from_str(&obj.json_data) {
            Ok(v) => v,
            Err(_) => continue,
        };

        let jaq_value = json_to_jaq_val(&json_value);
        let inputs = std::iter::once(Ok::<_, String>(jaq_value));
        let mut output_values: Vec<Val> = Vec::new();

        data::run(
            &runner,
            &filter,
            vars.clone(),
            inputs,
            |e| e.to_string(),
            |val| {
                if let Ok(v) = val {
                    output_values.push(v);
                }
                Ok(())
            },
        )
        .ok();

        // Convert JAQ output values back to JSON and create JsonObject results
        for val in output_values {
            let result_json = jaq_val_to_json(&val);
            let json_str = serde_json::to_string(&result_json).unwrap_or_default();

            // Create a new JsonObject with the transformed data
            results.push(JsonObject {
                id: obj.id,
                json_data: json_str,
                source_file: obj.source_file.clone(),
                modified_at: obj.modified_at.clone(),
            });
        }
    }

    Ok(results)
}

fn jaq_val_to_json(val: &Val) -> serde_json::Value {
    use jaq_json::Num;

    match val {
        Val::Null => serde_json::Value::Null,
        Val::Bool(b) => serde_json::Value::Bool(*b),
        Val::Num(n) => match n {
            Num::Float(f) => serde_json::Value::Number(
                serde_json::Number::from_f64(*f).unwrap_or_else(|| 0.into()),
            ),
            Num::Int(i) => serde_json::Value::Number(serde_json::Number::from(*i as i64)),
            _ => serde_json::Value::Null,
        },
        Val::Str(s, _) => {
            // Convert Bytes to string
            let s = String::from_utf8_lossy(s);
            serde_json::Value::String(s.to_string())
        }
        Val::Arr(arr) => serde_json::Value::Array(arr.iter().map(jaq_val_to_json).collect()),
        Val::Obj(obj) => {
            let map: serde_json::Map<String, serde_json::Value> = obj
                .iter()
                .filter_map(|(k, v)| {
                    // JAQ uses Str for keys
                    let key = match k {
                        Val::Str(s, _) => String::from_utf8_lossy(s).to_string(),
                        _ => return None,
                    };
                    Some((key, jaq_val_to_json(v)))
                })
                .collect();
            serde_json::Value::Object(map)
        }
    }
}

fn json_to_jaq_val(val: &serde_json::Value) -> Val {
    use bytes::Bytes;
    use jaq_json::Num;

    match val {
        serde_json::Value::Null => Val::Null,
        serde_json::Value::Bool(b) => Val::Bool(*b),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Val::Num(Num::from_integral(i))
            } else if let Some(f) = n.as_f64() {
                Val::Num(Num::Float(f))
            } else {
                Val::Null
            }
        }
        serde_json::Value::String(s) => Val::Str(Bytes::from(s.clone()), Tag::Utf8),
        serde_json::Value::Array(arr) => {
            Val::Arr(Rc::new(arr.iter().map(json_to_jaq_val).collect()))
        }
        serde_json::Value::Object(obj) => {
            let map: JaqMap = obj
                .iter()
                .map(|(k, v)| {
                    (
                        json_to_jaq_val(&serde_json::Value::String(k.clone())),
                        json_to_jaq_val(v),
                    )
                })
                .collect();
            Val::Obj(Rc::new(map))
        }
    }
}

// Saved Query API Handlers

async fn list_saved_queries(
    State(state): State<Arc<AppState>>,
) -> Result<Json<Vec<SavedQuery>>, StatusCode> {
    let db = state.db.lock().unwrap();

    let mut stmt = match db.prepare(
        "SELECT id, name, description, query_json, created_at FROM saved_queries ORDER BY created_at DESC"
    ) {
        Ok(s) => s,
        Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
    };

    let queries: Vec<SavedQuery> = match stmt.query_map([], |row| {
        Ok(SavedQuery {
            id: row.get(0)?,
            name: row.get(1)?,
            description: row.get(2)?,
            query_json: row.get(3)?,
            created_at: row.get(4)?,
        })
    }) {
        Ok(rows) => rows.filter_map(|r| r.ok()).collect(),
        Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
    };

    Ok(Json(queries))
}

async fn save_query(
    State(state): State<Arc<AppState>>,
    Json(request): Json<SaveQueryRequest>,
) -> Result<Json<SavedQuery>, StatusCode> {
    let db = state.db.lock().unwrap();

    // Validate the query is valid JSON
    if serde_json::from_str::<serde_json::Value>(&request.query).is_err() {
        return Err(StatusCode::BAD_REQUEST);
    }

    match db.execute(
        "INSERT INTO saved_queries (name, description, query_json) VALUES (?1, ?2, ?3)",
        params![&request.name, &request.description, &request.query],
    ) {
        Ok(_) => {
            // Get the last inserted id
            let id: i64 = db.last_insert_rowid();
            Ok(Json(SavedQuery {
                id: Some(id),
                name: request.name,
                description: request.description,
                query_json: request.query,
                created_at: Some(chrono::Local::now().to_rfc3339()),
            }))
        }
        Err(rusqlite::Error::SqliteFailure(_, Some(msg))) if msg.contains("UNIQUE") => {
            Err(StatusCode::CONFLICT)
        }
        Err(_) => Err(StatusCode::INTERNAL_SERVER_ERROR),
    }
}

async fn delete_saved_query(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> Result<StatusCode, StatusCode> {
    let db = state.db.lock().unwrap();

    match db.execute("DELETE FROM saved_queries WHERE id = ?1", params![id]) {
        Ok(rows_affected) => {
            if rows_affected > 0 {
                Ok(StatusCode::NO_CONTENT)
            } else {
                Err(StatusCode::NOT_FOUND)
            }
        }
        Err(_) => Err(StatusCode::INTERNAL_SERVER_ERROR),
    }
}

// Query History API Handlers

async fn list_query_history(
    State(state): State<Arc<AppState>>,
) -> Result<Json<Vec<QueryHistory>>, StatusCode> {
    let db = state.db.lock().unwrap();

    let mut stmt = match db.prepare(
        "SELECT id, query_json, query_type, source_tab, result_count, created_at 
         FROM query_history 
         ORDER BY created_at DESC 
         LIMIT 50",
    ) {
        Ok(s) => s,
        Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
    };

    let queries: Vec<QueryHistory> = match stmt.query_map([], |row| {
        Ok(QueryHistory {
            id: row.get(0)?,
            query_json: row.get(1)?,
            query_type: row.get(2)?,
            source_tab: row.get(3)?,
            result_count: row.get(4)?,
            created_at: row.get(5)?,
        })
    }) {
        Ok(rows) => rows.filter_map(|r| r.ok()).collect(),
        Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
    };

    Ok(Json(queries))
}

async fn save_query_history(
    State(state): State<Arc<AppState>>,
    Json(request): Json<SaveHistoryRequest>,
) -> Result<Json<QueryHistory>, StatusCode> {
    let db = state.db.lock().unwrap();

    // Validate the query is valid JSON
    if serde_json::from_str::<serde_json::Value>(&request.query).is_err() {
        return Err(StatusCode::BAD_REQUEST);
    }

    let query_type = request.query_type.unwrap_or_else(|| "dsl".to_string());

    match db.execute(
        "INSERT INTO query_history (query_json, query_type, source_tab, result_count) 
         VALUES (?1, ?2, ?3, ?4)",
        params![
            &request.query,
            &query_type,
            &request.source_tab,
            &request.result_count
        ],
    ) {
        Ok(_) => {
            // Get the last inserted id
            let id: i64 = db.last_insert_rowid();

            // Clean up old entries - keep only last 50
            let _ = db.execute(
                "DELETE FROM query_history WHERE id NOT IN (
                    SELECT id FROM query_history ORDER BY created_at DESC LIMIT 50
                )",
                [],
            );

            Ok(Json(QueryHistory {
                id,
                query_json: request.query,
                query_type,
                source_tab: request.source_tab,
                result_count: request.result_count,
                created_at: chrono::Local::now().to_rfc3339(),
            }))
        }
        Err(_) => Err(StatusCode::INTERNAL_SERVER_ERROR),
    }
}

async fn delete_query_history(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> Result<StatusCode, StatusCode> {
    let db = state.db.lock().unwrap();

    match db.execute("DELETE FROM query_history WHERE id = ?1", params![id]) {
        Ok(rows_affected) => {
            if rows_affected > 0 {
                Ok(StatusCode::NO_CONTENT)
            } else {
                Err(StatusCode::NOT_FOUND)
            }
        }
        Err(_) => Err(StatusCode::INTERNAL_SERVER_ERROR),
    }
}

async fn clear_query_history(State(state): State<Arc<AppState>>) -> Result<StatusCode, StatusCode> {
    let db = state.db.lock().unwrap();

    match db.execute("DELETE FROM query_history", []) {
        Ok(_) => Ok(StatusCode::NO_CONTENT),
        Err(_) => Err(StatusCode::INTERNAL_SERVER_ERROR),
    }
}

// Query Notes API Handlers

async fn get_notes(
    State(state): State<Arc<AppState>>,
    Query(params): Query<HashMap<String, String>>,
) -> Result<Json<NotesResponse>, StatusCode> {
    let query_hash = params.get("query_hash").ok_or(StatusCode::BAD_REQUEST)?;

    let db = state.db.lock().unwrap();

    let mut stmt = match db.prepare(
        "SELECT id, query_hash, full_query, row_hash, note_text, created_at, updated_at 
         FROM query_notes WHERE query_hash = ?1 ORDER BY updated_at DESC",
    ) {
        Ok(s) => s,
        Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
    };

    let notes: Vec<QueryNote> = match stmt.query_map(params![query_hash], |row| {
        Ok(QueryNote {
            id: row.get(0)?,
            query_hash: row.get(1)?,
            full_query: row.get(2)?,
            row_hash: row.get(3)?,
            note_text: row.get(4)?,
            created_at: row.get(5)?,
            updated_at: row.get(6)?,
        })
    }) {
        Ok(rows) => rows.filter_map(|r| r.ok()).collect(),
        Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
    };

    Ok(Json(NotesResponse { notes }))
}

async fn save_note(
    State(state): State<Arc<AppState>>,
    Json(request): Json<SaveNoteRequest>,
) -> Result<Json<QueryNote>, StatusCode> {
    let db = state.db.lock().unwrap();

    // Insert or replace note (UPSERT)
    let full_query = request.full_query.as_deref();
    match db.execute(
        "INSERT INTO query_notes (query_hash, full_query, row_hash, note_text) 
         VALUES (?1, ?2, ?3, ?4)
         ON CONFLICT(query_hash, row_hash) 
         DO UPDATE SET note_text = excluded.note_text, updated_at = datetime('now')",
        params![
            &request.query_hash,
            full_query,
            &request.row_hash,
            &request.note_text
        ],
    ) {
        Ok(_) => {
            // Get the last inserted/updated row
            let note: Result<QueryNote, _> = db.query_row(
                "SELECT id, query_hash, full_query, row_hash, note_text, created_at, updated_at 
                 FROM query_notes WHERE query_hash = ?1 AND row_hash = ?2",
                params![&request.query_hash, &request.row_hash],
                |row| {
                    Ok(QueryNote {
                        id: row.get(0)?,
                        query_hash: row.get(1)?,
                        full_query: row.get(2)?,
                        row_hash: row.get(3)?,
                        note_text: row.get(4)?,
                        created_at: row.get(5)?,
                        updated_at: row.get(6)?,
                    })
                },
            );

            match note {
                Ok(n) => Ok(Json(n)),
                Err(_) => Err(StatusCode::INTERNAL_SERVER_ERROR),
            }
        }
        Err(_) => Err(StatusCode::INTERNAL_SERVER_ERROR),
    }
}

async fn delete_note(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> Result<StatusCode, StatusCode> {
    let db = state.db.lock().unwrap();

    match db.execute("DELETE FROM query_notes WHERE id = ?1", params![id]) {
        Ok(rows_affected) => {
            if rows_affected > 0 {
                Ok(StatusCode::NO_CONTENT)
            } else {
                Err(StatusCode::NOT_FOUND)
            }
        }
        Err(_) => Err(StatusCode::INTERNAL_SERVER_ERROR),
    }
}

// Source file info structure
#[derive(Serialize)]
struct SourceFileInfo {
    source_file: String,
    count: i64,
}

// Cleanup API: List all source files with counts
async fn list_source_files(
    State(state): State<Arc<AppState>>,
) -> Result<Json<Vec<SourceFileInfo>>, StatusCode> {
    let db = state.db.lock().unwrap();

    let mut stmt = db.prepare(
        "SELECT source_file, COUNT(*) as count FROM json_objects GROUP BY source_file ORDER BY source_file"
    ).map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

    let files: Vec<SourceFileInfo> = stmt
        .query_map([], |row| {
            Ok(SourceFileInfo {
                source_file: row.get(0)?,
                count: row.get(1)?,
            })
        })
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?
        .filter_map(|r| r.ok())
        .collect();

    Ok(Json(files))
}

// Cleanup API: Delete records by source_file (Path param version)
async fn delete_source_file_by_path(
    State(state): State<Arc<AppState>>,
    Path(filename): Path<String>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let db = state.db.lock().unwrap();

    // Get count before deletion
    let count: i64 = match db.query_row(
        "SELECT COUNT(*) FROM json_objects WHERE source_file = ?1",
        params![filename],
        |row| row.get(0),
    ) {
        Ok(c) => c,
        Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
    };

    if count == 0 {
        return Err(StatusCode::NOT_FOUND);
    }

    match db.execute(
        "DELETE FROM json_objects WHERE source_file = ?1",
        params![filename],
    ) {
        Ok(deleted) => Ok(Json(serde_json::json!({
            "success": true,
            "message": format!("Deleted {} records from {}", deleted, filename),
            "deleted": deleted,
            "source_file": filename
        }))),
        Err(_) => Err(StatusCode::INTERNAL_SERVER_ERROR),
    }
}

// Cleanup API: Delete records by source_file (Query param version for /cleanup)
async fn delete_source_file(
    State(state): State<Arc<AppState>>,
    Query(params): Query<HashMap<String, String>>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let source_file = params.get("source_file").ok_or(StatusCode::BAD_REQUEST)?;

    let db = state.db.lock().unwrap();

    // Get count before deletion
    let count: i64 = match db.query_row(
        "SELECT COUNT(*) FROM json_objects WHERE source_file = ?1",
        params![source_file],
        |row| row.get(0),
    ) {
        Ok(c) => c,
        Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
    };

    if count == 0 {
        return Ok(Json(serde_json::json!({
            "success": false,
            "message": format!("No records found for source file: {}", source_file),
            "deleted_count": 0
        })));
    }

    match db.execute(
        "DELETE FROM json_objects WHERE source_file = ?1",
        params![source_file],
    ) {
        Ok(deleted) => Ok(Json(serde_json::json!({
            "success": true,
            "message": format!("Deleted {} records from {}", deleted, source_file),
            "deleted_count": deleted,
            "source_file": source_file
        }))),
        Err(_) => Err(StatusCode::INTERNAL_SERVER_ERROR),
    }
}

// Cleanup API: Clear all source files
async fn clear_all_source_files(
    State(state): State<Arc<AppState>>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let db = state.db.lock().unwrap();

    // Get count before deletion
    let count: i64 = db
        .query_row("SELECT COUNT(*) FROM json_objects", [], |row| row.get(0))
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

    db.execute("DELETE FROM json_objects", [])
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

    Ok(Json(serde_json::json!({
        "success": true,
        "message": format!("Cleared all data: {} records deleted", count),
        "deleted": count,
        "source_file": "*all*"
    })))
}

// Helper function to generate query hash
fn generate_query_hash(query_json: &str) -> String {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};

    let mut hasher = DefaultHasher::new();
    query_json.hash(&mut hasher);
    format!("{:x}", hasher.finish())
}

// Schema extraction helper functions
fn extract_field_type(value: &serde_json::Value) -> String {
    match value {
        serde_json::Value::Null => "null".to_string(),
        serde_json::Value::Bool(_) => "boolean".to_string(),
        serde_json::Value::Number(n) => {
            if n.is_i64() {
                "integer".to_string()
            } else {
                "number".to_string()
            }
        }
        serde_json::Value::String(_) => "string".to_string(),
        serde_json::Value::Array(_) => "array".to_string(),
        serde_json::Value::Object(_) => "object".to_string(),
    }
}

fn collect_nested_fields(
    obj: &serde_json::Map<String, serde_json::Value>,
    prefix: &str,
    fields: &mut HashSet<String>,
) {
    for (key, value) in obj {
        let field_path = if prefix.is_empty() {
            key.clone()
        } else {
            format!("{}.{}", prefix, key)
        };
        fields.insert(field_path.clone());

        // Recursively collect nested fields
        if let serde_json::Value::Object(nested) = value {
            collect_nested_fields(nested, &field_path, fields);
        }
        // For arrays, check if they contain objects
        if let serde_json::Value::Array(arr) = value {
            if let Some(first) = arr.first() {
                if let serde_json::Value::Object(nested) = first {
                    collect_nested_fields(nested, &format!("{}[]", field_path), fields);
                }
            }
        }
    }
}

async fn get_schema(
    State(state): State<Arc<AppState>>,
    Query(params): Query<HashMap<String, String>>,
) -> Result<Json<SchemaResponse>, StatusCode> {
    let source_file = params.get("source_file").ok_or(StatusCode::BAD_REQUEST)?;

    let db = state.db.lock().unwrap();

    // Get actual total count for this source file
    let total_count: i64 = match db.query_row(
        "SELECT COUNT(*) FROM json_objects WHERE source_file = ?1",
        params![source_file],
        |row| row.get(0),
    ) {
        Ok(count) => count,
        Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
    };

    // Get sample of JSON objects from the source file for field analysis
    let mut stmt =
        match db.prepare("SELECT json_data FROM json_objects WHERE source_file = ?1 LIMIT 100") {
            Ok(s) => s,
            Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
        };

    let rows = match stmt.query_map(params![source_file], |row| {
        let json_str: String = row.get(0)?;
        let value: serde_json::Value = serde_json::from_str(&json_str)
            .map_err(|e| rusqlite::Error::InvalidParameterName(e.to_string()))?;
        Ok(value)
    }) {
        Ok(rows) => rows.filter_map(|r| r.ok()).collect::<Vec<_>>(),
        Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
    };

    if rows.is_empty() {
        return Err(StatusCode::NOT_FOUND);
    }

    // Collect all field paths
    let mut all_fields: HashSet<String> = HashSet::new();
    for row in &rows {
        if let serde_json::Value::Object(obj) = row {
            collect_nested_fields(obj, "", &mut all_fields);
        }
    }

    // Analyze each field
    let mut field_infos = Vec::new();
    for field_path in all_fields {
        let mut samples = Vec::new();
        let mut null_count = 0;
        let mut unique_values: HashSet<String> = HashSet::new();
        let mut field_type = "null".to_string();

        for row in &rows {
            let value = get_nested_value(row, &field_path);

            if value.is_null() {
                null_count += 1;
            } else {
                if samples.len() < 3 {
                    samples.push(value.clone());
                }
                unique_values.insert(value.to_string());
                if field_type == "null" {
                    field_type = extract_field_type(&value);
                }
            }
        }

        field_infos.push(FieldInfo {
            name: field_path,
            field_type,
            sample_values: samples,
            unique_count: Some(unique_values.len()),
            null_count,
        });
    }

    // Sort fields alphabetically
    field_infos.sort_by(|a, b| a.name.cmp(&b.name));

    Ok(Json(SchemaResponse {
        source_file: source_file.clone(),
        total_objects: total_count as usize,
        fields: field_infos,
    }))
}

fn get_nested_value(value: &serde_json::Value, path: &str) -> serde_json::Value {
    let parts: Vec<&str> = path.split('.').collect();
    let mut current = value;

    for part in &parts {
        // Handle array notation like "variants[]"
        if part.ends_with("[]") {
            let arr_field = &part[..part.len() - 2];
            if let serde_json::Value::Object(obj) = current {
                if let Some(arr_val) = obj.get(arr_field) {
                    if let serde_json::Value::Array(arr) = arr_val {
                        // Return first element for sampling
                        if let Some(first) = arr.first() {
                            current = first;
                            continue;
                        }
                    }
                }
            }
            return serde_json::Value::Null;
        }

        if let serde_json::Value::Object(obj) = current {
            current = obj.get(*part).unwrap_or(&serde_json::Value::Null);
        } else {
            return serde_json::Value::Null;
        }
    }

    current.clone()
}

async fn analyze_joins(
    State(state): State<Arc<AppState>>,
) -> Result<Json<JoinAnalysisResponse>, StatusCode> {
    let db = state.db.lock().unwrap();

    // Get all source files
    let mut stmt = match db.prepare("SELECT DISTINCT source_file FROM json_objects") {
        Ok(s) => s,
        Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
    };

    let source_files: Vec<String> = match stmt.query_map([], |row| row.get::<_, String>(0)) {
        Ok(rows) => rows.filter_map(|r| r.ok()).collect(),
        Err(_) => return Err(StatusCode::INTERNAL_SERVER_ERROR),
    };

    let mut suggestions = Vec::new();

    // Analyze potential joins between pairs of files
    for i in 0..source_files.len() {
        for j in (i + 1)..source_files.len() {
            let left_file = &source_files[i];
            let right_file = &source_files[j];

            if let Ok(some_suggestions) = analyze_file_pair(&db, left_file, right_file) {
                suggestions.extend(some_suggestions);
            }
        }
    }

    // Sort by match percentage
    suggestions.sort_by(|a, b| b.match_percentage.partial_cmp(&a.match_percentage).unwrap());

    Ok(Json(JoinAnalysisResponse { suggestions }))
}

fn analyze_file_pair(
    db: &Connection,
    left_file: &str,
    right_file: &str,
) -> Result<Vec<JoinSuggestion>, rusqlite::Error> {
    let mut suggestions = Vec::new();

    // Get sample data from both files
    let left_data = get_sample_data(db, left_file, 1000)?;
    let right_data = get_sample_data(db, right_file, 1000)?;

    if left_data.is_empty() || right_data.is_empty() {
        return Ok(suggestions);
    }

    // Extract string fields from both sides
    let left_fields = extract_string_fields(&left_data);
    let right_fields = extract_string_fields(&right_data);

    // Try matching each pair of fields
    for (left_field, left_values) in &left_fields {
        for (right_field, right_values) in &right_fields {
            // Skip if field names suggest they're not joinable (e.g., ids, timestamps)
            if is_likely_join_field(left_field) && is_likely_join_field(right_field) {
                let matches = count_matches(left_values, right_values);

                if matches > 0 {
                    let match_percentage =
                        (matches as f64 / left_values.len().min(right_values.len()) as f64) * 100.0;

                    // Only suggest if match rate is reasonable
                    if match_percentage >= 10.0 {
                        let join_type = determine_join_type(left_values, right_values);

                        suggestions.push(JoinSuggestion {
                            left_source: left_file.to_string(),
                            left_field: left_field.clone(),
                            right_source: right_file.to_string(),
                            right_field: right_field.clone(),
                            match_count: matches,
                            left_total: left_values.len(),
                            right_total: right_values.len(),
                            match_percentage,
                            join_type_hint: join_type,
                        });
                    }
                }
            }
        }
    }

    Ok(suggestions)
}

fn get_sample_data(
    db: &Connection,
    source_file: &str,
    limit: usize,
) -> Result<Vec<serde_json::Value>, rusqlite::Error> {
    let mut stmt =
        db.prepare("SELECT json_data FROM json_objects WHERE source_file = ?1 LIMIT ?2")?;

    let rows: Vec<serde_json::Value> = stmt
        .query_map(params![source_file, limit], |row| {
            let json_str: String = row.get(0)?;
            let value: serde_json::Value = serde_json::from_str(&json_str)
                .map_err(|e| rusqlite::Error::InvalidParameterName(e.to_string()))?;
            Ok(value)
        })?
        .filter_map(|r| r.ok())
        .collect();

    Ok(rows)
}

fn extract_string_fields(data: &[serde_json::Value]) -> HashMap<String, HashSet<String>> {
    let mut fields: HashMap<String, HashSet<String>> = HashMap::new();

    for obj in data {
        if let serde_json::Value::Object(map) = obj {
            extract_string_fields_from_obj(map, "", &mut fields);
        }
    }

    fields
}

fn extract_string_fields_from_obj(
    obj: &serde_json::Map<String, serde_json::Value>,
    prefix: &str,
    fields: &mut HashMap<String, HashSet<String>>,
) {
    for (key, value) in obj {
        let field_path = if prefix.is_empty() {
            key.clone()
        } else {
            format!("{}.{}", prefix, key)
        };

        match value {
            serde_json::Value::String(s) if !s.is_empty() => {
                fields.entry(field_path).or_default().insert(s.clone());
            }
            serde_json::Value::Object(nested) => {
                extract_string_fields_from_obj(nested, &field_path, fields);
            }
            serde_json::Value::Array(arr) => {
                // Check array elements
                for item in arr {
                    if let serde_json::Value::Object(nested) = item {
                        extract_string_fields_from_obj(
                            nested,
                            &format!("{}[]", field_path),
                            fields,
                        );
                    } else if let serde_json::Value::String(s) = item {
                        if !s.is_empty() {
                            fields
                                .entry(format!("{}[]", field_path))
                                .or_default()
                                .insert(s.clone());
                        }
                    }
                }
            }
            _ => {}
        }
    }
}

fn is_likely_join_field(field_name: &str) -> bool {
    // Common join field patterns
    let join_keywords = [
        "id", "sku", "code", "mpn", "gtin", "barcode", "handle", "variant",
    ];
    let lower = field_name.to_lowercase();
    join_keywords.iter().any(|kw| lower.contains(kw))
}

fn count_matches(left: &HashSet<String>, right: &HashSet<String>) -> usize {
    left.intersection(right).count()
}

fn determine_join_type(left: &HashSet<String>, right: &HashSet<String>) -> String {
    let left_unique = left.len();
    let right_unique = right.len();
    let matches = count_matches(left, right);

    if left_unique == matches && right_unique == matches {
        "one-to-one".to_string()
    } else if left_unique > matches && right_unique == matches {
        "many-to-one".to_string()
    } else if left_unique == matches && right_unique > matches {
        "one-to-many".to_string()
    } else {
        "many-to-many".to_string()
    }
}

fn init_database() -> Result<Connection> {
    let conn = Connection::open(DB_PATH).context("Failed to open database")?;

    conn.execute(
        "CREATE TABLE IF NOT EXISTS json_objects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            json_data TEXT NOT NULL,
            source_file TEXT NOT NULL,
            modified_at TEXT NOT NULL,
            UNIQUE(json_data, source_file)
        )",
        [],
    )
    .context("Failed to create json_objects table")?;

    // Core indexes for source-scoped query performance.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_json_objects_source_file ON json_objects(source_file)",
        [],
    )
    .context("Failed to create source_file index")?;

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_json_objects_source_modified ON json_objects(source_file, modified_at)",
        [],
    )
    .context("Failed to create source_file/modified_at index")?;

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_json_objects_source_id ON json_objects(source_file, id)",
        [],
    )
    .context("Failed to create source_file/id index")?;

    conn.execute(
        "CREATE TABLE IF NOT EXISTS saved_queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            query_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )",
        [],
    )
    .context("Failed to create saved_queries table")?;

    conn.execute(
        "CREATE TABLE IF NOT EXISTS query_notes (
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
    .context("Failed to create query_notes table")?;

    // Create index for faster lookups
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_query_notes_hash ON query_notes(query_hash)",
        [],
    )
    .context("Failed to create notes index")?;

    // Create query history table
    conn.execute(
        "CREATE TABLE IF NOT EXISTS query_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_json TEXT NOT NULL,
            query_type TEXT NOT NULL DEFAULT 'dsl',
            source_tab TEXT,
            result_count INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )",
        [],
    )
    .context("Failed to create query_history table")?;

    // Create index for query history
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_query_history_created ON query_history(created_at DESC)",
        [],
    )
    .context("Failed to create query_history index")?;

    // Migration: Add full_query column if it doesn't exist
    // Check if column exists by trying to select it
    let column_exists: bool = conn
        .query_row(
            "SELECT 1 FROM pragma_table_info('query_notes') WHERE name = 'full_query'",
            [],
            |_row| Ok(true),
        )
        .unwrap_or(false);

    if !column_exists {
        conn.execute("ALTER TABLE query_notes ADD COLUMN full_query TEXT", [])
            .context("Failed to add full_query column")?;
    }

    Ok(conn)
}

// AI Proxy structs
#[derive(Debug, Deserialize)]
struct AiQueryRequest {
    prompt: String,
    file_context: String,
}

#[derive(Debug, Serialize)]
struct AiQueryResponse {
    dsl_query: serde_json::Value,
}

async fn ai_generate_dsl(Json(request): Json<AiQueryRequest>) -> Result<Response, StatusCode> {
    use std::collections::HashSet;

    // Parse files mentioned in the prompt
    let files: Vec<&str> = request
        .prompt
        .lines()
        .filter(|line| line.trim().ends_with(".json"))
        .map(|line| line.trim())
        .collect();

    // Determine what type of matching the user wants
    let prompt_lower = request.prompt.to_lowercase();
    let match_type = if prompt_lower.contains("barcode")
        || prompt_lower.contains("gtin")
        || prompt_lower.contains("ean")
        || prompt_lower.contains("upc")
    {
        "barcode"
    } else if prompt_lower.contains("sku") || prompt_lower.contains("default_code") {
        "sku"
    } else if prompt_lower.contains("mpn") || prompt_lower.contains("part number") {
        "mpn"
    } else {
        "auto" // Try to detect from schema
    };

    // Helper function to extract all field paths from a JSON value
    fn extract_field_paths(value: &serde_json::Value, prefix: &str, paths: &mut Vec<String>) {
        match value {
            serde_json::Value::Object(obj) => {
                for (key, val) in obj {
                    let path = if prefix.is_empty() {
                        key.clone()
                    } else {
                        format!("{}.{}", prefix, key)
                    };
                    paths.push(path.clone());
                    // Recurse into nested objects (but not arrays)
                    if val.is_object() && !val.is_array() {
                        extract_field_paths(val, &path, paths);
                    }
                }
            }
            _ => {}
        }
    }

    // Helper to find best matching field
    fn find_matching_field(fields: &[String], match_type: &str) -> Option<String> {
        // Priority order for different match types
        let patterns: Vec<&str> = match match_type {
            "barcode" => vec!["barcode", "gtin", "ean", "upc", "isbn"],
            "sku" => vec!["sku", "default_code", "item_code", "product_code"],
            "mpn" => vec!["mpn", "manufacturer_part_number", "part_number"],
            _ => vec!["sku", "barcode", "gtin", "mpn", "default_code"],
        };

        for pattern in patterns {
            for field in fields {
                let field_lower = field.to_lowercase();
                if field_lower.contains(pattern) {
                    return Some(field.clone());
                }
            }
        }
        None
    }

    // Analyze each file to find potential join fields
    #[derive(Debug)]
    struct FileAnalysis {
        source_file: String,
        alias: String,
        fields: Vec<String>,
        barcode_field: Option<String>,
        sku_field: Option<String>,
        mpn_field: Option<String>,
    }

    let mut analyses = Vec::new();

    for file in &files {
        let alias = file
            .trim_end_matches(".json")
            .replace("_", "")
            .replace("-", "");

        // Try to load sample data from the database
        let sample_data = if let Ok(conn) = rusqlite::Connection::open(DB_PATH) {
            if let Ok(mut stmt) =
                conn.prepare("SELECT json_data FROM json_objects WHERE source_file = ?1 LIMIT 1")
            {
                let json_str: Result<String, _> = stmt.query_row([file], |row| row.get(0));
                json_str.ok().and_then(|s| serde_json::from_str(&s).ok())
            } else {
                None
            }
        } else {
            None
        };

        let mut fields = Vec::new();
        let mut barcode_field = None;
        let mut sku_field = None;
        let mut mpn_field = None;

        if let Some(sample) = sample_data {
            extract_field_paths(&sample, "", &mut fields);

            // Also look in nested structures
            if let Some(obj) = sample.as_object() {
                // Check for variant structures (Shopify style)
                if let Some(variants) = obj.get("variants") {
                    if let Some(arr) = variants.as_array() {
                        if let Some(first) = arr.first() {
                            extract_field_paths(first, "variants", &mut fields);
                        }
                    }
                }
                // Check for variant structure (nested object style)
                if let Some(variant) = obj.get("variant") {
                    extract_field_paths(variant, "variant", &mut fields);
                }
            }

            barcode_field = find_matching_field(&fields, "barcode");
            sku_field = find_matching_field(&fields, "sku");
            mpn_field = find_matching_field(&fields, "mpn");
        }

        analyses.push(FileAnalysis {
            source_file: file.to_string(),
            alias,
            fields,
            barcode_field,
            sku_field,
            mpn_field,
        });
    }

    // If we have files, generate a star join query based on analysis
    if analyses.len() >= 2 {
        let primary = &analyses[0];
        let primary_alias = &primary.alias;

        // Determine which field to use for joining
        let (primary_field, field_type) = match match_type {
            "barcode" => {
                if let Some(ref field) = primary.barcode_field {
                    (format!("{}.{}", primary_alias, field), "barcode")
                } else if let Some(ref field) = primary.mpn_field {
                    (format!("{}.{}", primary_alias, field), "mpn")
                } else {
                    (format!("{}.mpn", primary_alias), "mpn")
                }
            }
            "sku" => {
                if let Some(ref field) = primary.sku_field {
                    (format!("{}.{}", primary_alias, field), "sku")
                } else if let Some(ref field) = primary.mpn_field {
                    (format!("{}.{}", primary_alias, field), "mpn")
                } else {
                    (format!("{}.mpn", primary_alias), "mpn")
                }
            }
            _ => {
                // Auto-detect: prefer barcode > sku > mpn
                if let Some(ref field) = primary.barcode_field {
                    (format!("{}.{}", primary_alias, field), "barcode")
                } else if let Some(ref field) = primary.sku_field {
                    (format!("{}.{}", primary_alias, field), "sku")
                } else if let Some(ref field) = primary.mpn_field {
                    (format!("{}.{}", primary_alias, field), "mpn")
                } else {
                    (format!("{}.mpn", primary_alias), "mpn")
                }
            }
        };

        let mut joins = vec![];
        let mut select =
            vec![serde_json::json!({"expr": format!("{}.*", primary_alias), "alias": "primary"})];

        for (i, analysis) in analyses.iter().skip(1).enumerate() {
            let alias = format!("join{}", i + 1);

            // Find the best matching field in this file
            let join_field = match field_type {
                "barcode" => analysis
                    .barcode_field
                    .clone()
                    .or_else(|| analysis.mpn_field.clone())
                    .unwrap_or_else(|| "mpn".to_string()),
                "sku" => analysis
                    .sku_field
                    .clone()
                    .or_else(|| analysis.mpn_field.clone())
                    .unwrap_or_else(|| {
                        if analysis.source_file.contains("shopify") {
                            "variants[].sku".to_string()
                        } else {
                            "default_code".to_string()
                        }
                    }),
                _ => analysis
                    .sku_field
                    .clone()
                    .or_else(|| analysis.barcode_field.clone())
                    .or_else(|| analysis.mpn_field.clone())
                    .unwrap_or_else(|| {
                        if analysis.source_file.contains("shopify") {
                            "variants[].sku".to_string()
                        } else {
                            "mpn".to_string()
                        }
                    }),
            };

            // Build the full field path with alias
            let full_join_field = if join_field.contains(".") {
                format!("{}.{}", alias, join_field)
            } else {
                format!("{}.{}", alias, join_field)
            };

            joins.push(serde_json::json!({
                "source": {
                    "source_file": &analysis.source_file,
                    "alias": alias
                },
                "on": {
                    "left": &primary_field,
                    "right": &full_join_field,
                    "op": "="
                },
                "join_type": "left"
            }));

            select.push(serde_json::json!({
                "expr": format!("{}.*", alias),
                "alias": alias
            }));
        }

        // Build where clause based on primary field
        let where_field = primary_field.clone();
        let dsl_query = serde_json::json!({
            "from": {
                "source_file": &primary.source_file,
                "alias": primary_alias
            },
            "joins": joins,
            "where": [{"field": where_field, "op": "!=", "value": ""}],
            "select": select,
            "flatten": false,
            "limit": 10000
        });

        return Ok((StatusCode::OK, Json(dsl_query)).into_response());
    }

    // Fallback: return a simple query
    let dsl_query = serde_json::json!({
        "from": {
            "source_file": "gmc_feather_place_products.json",
            "alias": "primary"
        },
        "select": [{"expr": "primary.*"}],
        "limit": 100
    });

    Ok((StatusCode::OK, Json(dsl_query)).into_response())
}

fn html_page() -> String {
    include_str!("html_page.html").to_string()
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt::init();
    info!("Starting JSON Loader Server");

    let conn = init_database().context("Failed to initialize database")?;
    info!("Database initialized at {}", DB_PATH);

    let state = Arc::new(AppState {
        db: Arc::new(Mutex::new(conn)),
    });

    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    let app = Router::new()
        .route("/", get(|| async { Html(html_page()) }))
        .route("/load", post(load_json_files))
        .route("/stats", get(get_stats))
        .route("/files", get(get_files))
        .route("/query", get(query_objects))
        .route("/query/dsl", post(query_dsl))
        .route("/query/dsl/with-notes", post(query_dsl_with_notes))
        .route("/export", post(export_data))
        .route("/queries", get(list_saved_queries))
        .route("/queries", post(save_query))
        .route("/queries/:id", delete(delete_saved_query))
        .route("/history", get(list_query_history))
        .route("/history", post(save_query_history))
        .route("/history/:id", delete(delete_query_history))
        .route("/history/clear", post(clear_query_history))
        .route("/schema", get(get_schema))
        .route("/join-analysis", get(analyze_joins))
        .route("/source-files", get(list_source_files))
        .route(
            "/source-files/:filename",
            delete(delete_source_file_by_path),
        )
        .route("/source-files", delete(clear_all_source_files))
        .route("/cleanup", delete(delete_source_file))
        .route("/notes", get(get_notes))
        .route("/notes", post(save_note))
        .route("/notes/:id", delete(delete_note))
        .route("/ai/generate", post(ai_generate_dsl))
        .layer(cors)
        .with_state(state);

    info!("Server listening on http://0.0.0.0:3000");

    axum::Server::bind(&"0.0.0.0:3000".parse()?)
        .serve(app.into_make_service())
        .await?;

    Ok(())
}
