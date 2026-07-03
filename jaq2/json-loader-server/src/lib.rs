//! JSON Loader Server - Library exports for testing
//!
//! This module re-exports the internal types so they can be used
//! in integration tests and benchmarks.

pub mod app;
pub mod context;
pub mod expression;
pub mod functions;
pub mod query_engine;

#[cfg(test)]
pub mod test_utils;

#[cfg(test)]
mod query_engine_tests;

// Re-export main types for convenience
pub use query_engine::{
    QueryDsl, QueryEngine, QueryResult, Source, Join, JoinCondition,
    Condition, SelectField, GroupBy, OrderBy, SubqueryDef, ExplodeWithContext,
    DateFunction, CoalesceFunction,
};

pub use context::{Context, ContextBuilder};
pub use expression::Expression;
pub use functions::FunctionRegistry;
pub use app::{AppState, create_app};
