//! Application setup and router configuration
//!
//! This module contains the Axum router setup and AppState,
//! separated from main.rs so they can be used in tests.

use axum::{
    Router,
    routing::{delete, get, post},
};
use rusqlite::Connection;
use std::sync::Arc;
use std::sync::Mutex;
use tower_http::cors::CorsLayer;

use crate::query_engine::execute_query;

/// Application state shared across handlers
#[derive(Clone)]
pub struct AppState {
    pub db: Arc<Mutex<Connection>>,
}

impl AppState {
    /// Create a new AppState with the given database connection
    pub fn new(conn: Connection) -> Self {
        Self {
            db: Arc::new(Mutex::new(conn)),
        }
    }
}

/// Create the Axum router with all routes
/// This is extracted into a function so tests can create the app
pub fn create_app(
    _state: Arc<AppState>,
    _cors: CorsLayer,
) -> Router {
    // NOTE: This is a simplified version for demonstration.
    // The actual implementation would include all the routes from main.rs
    // 
    // For full integration tests, you would either:
    // 1. Move all handlers to this module
    // 2. Use a test-specific router
    // 3. Export AppState and create a test harness
    
    Router::new()
        // Routes would be added here
        // .route("/stats", get(get_stats))
        // etc.
}
