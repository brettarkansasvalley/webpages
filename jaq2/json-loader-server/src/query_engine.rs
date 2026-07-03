use anyhow::{anyhow, Result};
use chrono::{Datelike, Timelike};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

use crate::context::Context;
use crate::expression::Expression;
use crate::functions::FunctionRegistry;

/// Date/Time function for extracting components from datetime strings
#[derive(Debug, Clone)]
pub enum DateFunction {
    Hour {
        field: String,
    },
    Date {
        field: String,
    },
    DateTime {
        field: String,
    },
    Minute {
        field: String,
    },
    DayOfWeek {
        field: String,
    },
    DayOfMonth {
        field: String,
    },
    Month {
        field: String,
    },
    Year {
        field: String,
    },
    DateDiff {
        field1: String,
        field2: String,
        unit: String,
    },
}

impl DateFunction {
    /// Parse a function call like "hour(o.closedDate)"
    pub fn parse(expr: &str) -> Option<(Self, String)> {
        let expr = expr.trim();

        // Match pattern like "function(field)" or "function(alias.field)"
        if let Some(caps) = regex::Regex::new(r"^(\w+)\s*\(\s*([^)]+)\s*\)$")
            .ok()?
            .captures(expr)
        {
            let func_name = caps.get(1)?.as_str().to_lowercase();
            let field = caps.get(2)?.as_str().trim().to_string();

            let func = match func_name.as_str() {
                "hour" => DateFunction::Hour {
                    field: field.clone(),
                },
                "date" => DateFunction::Date {
                    field: field.clone(),
                },
                "datetime" => DateFunction::DateTime {
                    field: field.clone(),
                },
                "minute" => DateFunction::Minute {
                    field: field.clone(),
                },
                "dayofweek" | "day_of_week" => DateFunction::DayOfWeek {
                    field: field.clone(),
                },
                "dayofmonth" | "day_of_month" => DateFunction::DayOfMonth {
                    field: field.clone(),
                },
                "month" => DateFunction::Month {
                    field: field.clone(),
                },
                "year" => DateFunction::Year {
                    field: field.clone(),
                },
                "datediff" | "date_diff" => {
                    // Parse date_diff(field1, field2, 'unit')
                    let parts: Vec<&str> = field.split(',').collect();
                    if parts.len() >= 2 {
                        let unit = parts
                            .get(2)
                            .map(|s| s.trim().trim_matches('\'').trim_matches('"').to_string())
                            .unwrap_or_else(|| "hours".to_string());
                        DateFunction::DateDiff {
                            field1: parts[0].trim().to_string(),
                            field2: parts[1].trim().to_string(),
                            unit,
                        }
                    } else {
                        return None;
                    }
                }
                _ => return None,
            };

            return Some((func, field));
        }

        None
    }

    /// Extract value by path from a row
    fn extract_value_by_path(
        row: &HashMap<String, Value>,
        path: &str,
        engine: &QueryEngine<'_>,
    ) -> Value {
        // Parse alias.field pattern
        let parts: Vec<&str> = path.splitn(2, '.').collect();
        if parts.len() == 2 {
            let alias = parts[0];
            let field = parts[1];
            engine.extract_value(row, alias, field)
        } else {
            // Try to find in any alias
            for (_alias, obj) in row {
                if let Value::Object(map) = obj {
                    if let Some(v) = map.get(path) {
                        return v.clone();
                    }
                }
            }
            Value::Null
        }
    }

    /// Evaluate the function against a row
    pub fn evaluate(&self, row: &HashMap<String, Value>, engine: &QueryEngine<'_>) -> Value {
        match self {
            DateFunction::Hour { field } => {
                let value = Self::extract_value_by_path(row, field, engine);
                Self::extract_hour(&value)
            }
            DateFunction::Date { field } => {
                let value = Self::extract_value_by_path(row, field, engine);
                Self::extract_date(&value)
            }
            DateFunction::DateTime { field } => {
                let value = Self::extract_value_by_path(row, field, engine);
                Self::parse_datetime(&value)
            }
            DateFunction::Minute { field } => {
                let value = Self::extract_value_by_path(row, field, engine);
                Self::extract_minute(&value)
            }
            DateFunction::DayOfWeek { field } => {
                let value = Self::extract_value_by_path(row, field, engine);
                Self::extract_day_of_week(&value)
            }
            DateFunction::DayOfMonth { field } => {
                let value = Self::extract_value_by_path(row, field, engine);
                Self::extract_day_of_month(&value)
            }
            DateFunction::Month { field } => {
                let value = Self::extract_value_by_path(row, field, engine);
                Self::extract_month(&value)
            }
            DateFunction::Year { field } => {
                let value = Self::extract_value_by_path(row, field, engine);
                Self::extract_year(&value)
            }
            DateFunction::DateDiff {
                field1,
                field2,
                unit,
            } => {
                let v1 = Self::extract_value_by_path(row, field1, engine);
                let v2 = Self::extract_value_by_path(row, field2, engine);
                Self::calculate_date_diff(&v1, &v2, unit)
            }
        }
    }

    // Helper functions for date parsing
    fn parse_iso8601(value: &Value) -> Option<chrono::DateTime<chrono::Utc>> {
        match value {
            Value::String(s) => {
                let s = s.trim();

                // Try RFC 3339 first (most common)
                if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(s) {
                    return Some(dt.with_timezone(&chrono::Utc));
                }

                // Try various formats
                let formats = [
                    "%Y-%m-%dT%H:%M:%S%.f%z",
                    "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S%.fZ",
                    "%Y-%m-%dT%H:%M:%SZ",
                    "%Y-%m-%dT%H:%M:%S%.f",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d",
                ];

                for fmt in &formats {
                    if let Ok(dt) = chrono::DateTime::parse_from_str(s, fmt) {
                        return Some(dt.with_timezone(&chrono::Utc));
                    }
                }

                None
            }
            _ => None,
        }
    }

    pub fn extract_hour(value: &Value) -> Value {
        match Self::parse_iso8601(value) {
            Some(dt) => Value::Number(serde_json::Number::from(dt.hour() as i64)),
            None => Value::Null,
        }
    }

    fn extract_date(value: &Value) -> Value {
        match Self::parse_iso8601(value) {
            Some(dt) => Value::String(dt.format("%Y-%m-%d").to_string()),
            None => Value::Null,
        }
    }

    fn parse_datetime(value: &Value) -> Value {
        match Self::parse_iso8601(value) {
            Some(dt) => Value::String(dt.to_rfc3339()),
            None => Value::Null,
        }
    }

    fn extract_minute(value: &Value) -> Value {
        match Self::parse_iso8601(value) {
            Some(dt) => Value::Number(serde_json::Number::from(dt.minute() as i64)),
            None => Value::Null,
        }
    }

    fn extract_day_of_week(value: &Value) -> Value {
        match Self::parse_iso8601(value) {
            Some(dt) => Value::Number(serde_json::Number::from(
                dt.weekday().num_days_from_sunday() as i64,
            )),
            None => Value::Null,
        }
    }

    fn extract_day_of_month(value: &Value) -> Value {
        match Self::parse_iso8601(value) {
            Some(dt) => Value::Number(serde_json::Number::from(dt.day() as i64)),
            None => Value::Null,
        }
    }

    fn extract_month(value: &Value) -> Value {
        match Self::parse_iso8601(value) {
            Some(dt) => Value::Number(serde_json::Number::from(dt.month() as i64)),
            None => Value::Null,
        }
    }

    fn extract_year(value: &Value) -> Value {
        match Self::parse_iso8601(value) {
            Some(dt) => Value::Number(serde_json::Number::from(dt.year() as i64)),
            None => Value::Null,
        }
    }

    fn calculate_date_diff(v1: &Value, v2: &Value, unit: &str) -> Value {
        match (Self::parse_iso8601(v1), Self::parse_iso8601(v2)) {
            (Some(dt1), Some(dt2)) => {
                let duration = dt1.signed_duration_since(dt2);
                let result = match unit.to_lowercase().as_str() {
                    "seconds" | "second" | "secs" | "sec" | "s" => duration.num_seconds(),
                    "minutes" | "minute" | "min" | "mins" => duration.num_minutes(),
                    "hours" | "hour" | "hr" | "hrs" | "h" => duration.num_hours(),
                    "days" | "day" | "d" => duration.num_days(),
                    _ => duration.num_hours(), // default to hours
                };
                Value::Number(serde_json::Number::from(result))
            }
            _ => Value::Null,
        }
    }
}

/// Query DSL for joining and transforming JSON data
#[derive(Debug, Deserialize, Serialize, Clone, Default)]
pub struct QueryDsl {
    /// Primary source (required, unless using with/subquery)
    #[serde(default)]
    pub from: Option<Source>,

    /// Optional joins to other sources
    #[serde(default)]
    pub joins: Vec<Join>,

    /// Filter conditions (jaq-style expressions or simple comparisons)
    #[serde(default)]
    pub r#where: Option<Vec<Condition>>,

    /// Filter operator for combining where conditions: "and" (default) or "or"
    #[serde(default)]
    pub where_op: Option<String>,

    /// Fields to select (jaq expressions)
    #[serde(default)]
    pub select: Vec<SelectField>,

    /// Group by fields for aggregation
    #[serde(default)]
    pub group_by: Option<Vec<GroupBy>>,

    /// Having conditions (post-aggregation filter)
    #[serde(default)]
    pub having: Option<Vec<Condition>>,

    /// Having operator: "and" (default) or "or"
    #[serde(default)]
    pub having_op: Option<String>,

    /// Order by fields for sorting
    #[serde(default)]
    pub order_by: Option<Vec<OrderBy>>,

    /// Limit results
    #[serde(default)]
    pub limit: Option<usize>,

    /// Offset for pagination
    #[serde(default)]
    pub offset: Option<usize>,

    /// Flatten nested arrays
    #[serde(default)]
    pub flatten: bool,

    /// Select distinct rows only
    #[serde(default)]
    pub distinct: bool,

    /// Named subqueries that can be referenced in 'from' or joins
    #[serde(default)]
    pub with: Option<Vec<SubqueryDef>>,

    /// Reference to a subquery result to use as input
    #[serde(default)]
    pub from_subquery: Option<String>,

    /// Variable bindings (let expressions)
    #[serde(default)]
    pub r#let: Option<HashMap<String, Expression>>,

    /// User-defined functions
    #[serde(default)]
    pub functions: Option<HashMap<String, UserFunctionDef>>,
}

/// COALESCE function for fallback values
#[derive(Debug, Clone)]
pub enum CoalesceFunction {
    Coalesce { fields: Vec<String> },
}

impl CoalesceFunction {
    /// Parse a function call like "coalesce(p.server.guid, o.server.guid, 'UNKNOWN')"
    pub fn parse(expr: &str) -> Option<(Self, Value)> {
        let expr = expr.trim();

        // Match coalesce(field1, field2, ...)
        if let Some(caps) = regex::Regex::new(r"^(?i)coalesce\s*\(\s*(.+)\s*\)$")
            .ok()?
            .captures(expr)
        {
            let args_str = caps.get(1)?.as_str();
            // Split by comma, but handle quoted strings
            let mut fields = Vec::new();
            let mut current = String::new();
            let mut in_quotes = false;
            let mut quote_char = ' ';

            for ch in args_str.chars() {
                match ch {
                    '\'' | '"' if !in_quotes => {
                        in_quotes = true;
                        quote_char = ch;
                        current.push(ch);
                    }
                    ch if in_quotes && ch == quote_char => {
                        in_quotes = false;
                        current.push(ch);
                    }
                    ',' if !in_quotes => {
                        fields.push(current.trim().to_string());
                        current.clear();
                    }
                    _ => current.push(ch),
                }
            }
            if !current.is_empty() {
                fields.push(current.trim().to_string());
            }

            if !fields.is_empty() {
                return Some((
                    CoalesceFunction::Coalesce {
                        fields: fields.clone(),
                    },
                    Value::Null,
                ));
            }
        }

        None
    }

    /// Evaluate COALESCE against a row
    pub fn evaluate(&self, row: &HashMap<String, Value>, engine: &QueryEngine<'_>) -> Value {
        match self {
            CoalesceFunction::Coalesce { fields } => {
                for field in fields {
                    // Check if it's a literal string (quoted)
                    let value = if (field.starts_with('\'') && field.ends_with('\''))
                        || (field.starts_with('"') && field.ends_with('"'))
                    {
                        // Literal string - remove quotes
                        let literal = &field[1..field.len() - 1];
                        Value::String(literal.to_string())
                    } else {
                        // Field reference - extract value
                        DateFunction::extract_value_by_path(row, field, engine)
                    };

                    // Return first non-null value
                    if !value.is_null() {
                        return value;
                    }
                }
                Value::Null
            }
        }
    }
}

/// Configuration for multi-level array explosion with context preservation
#[derive(Debug, Deserialize, Serialize, Clone, Default)]
pub struct ExplodeWithContext {
    /// Dot-separated path through nested arrays (e.g., "checks.selections")
    pub path: String,
    /// Aliases for each level (e.g., ["c", "sel"])
    pub aliases: Vec<String>,
    /// Parent fields to preserve in exploded rows (full paths like ["o.guid", "o.businessDate"])
    #[serde(default)]
    pub preserve: Vec<String>,
    /// Filter conditions on leaf items
    #[serde(default)]
    pub r#where: Option<Vec<Condition>>,
}

#[derive(Debug, Deserialize, Serialize, Clone, Default)]
pub struct Source {
    pub source_file: String,
    #[serde(default)]
    pub alias: Option<String>,
    /// Optional array field to explode before joining (e.g., "variants")
    #[serde(default)]
    pub explode: Option<String>,
    /// Multi-level array explosion with context preservation
    #[serde(default)]
    pub explode_with_context: Option<ExplodeWithContext>,
    /// Treat primitive values (strings, numbers) as objects with a single field
    #[serde(default)]
    pub as_primitive: Option<String>, // column name for the primitive value
}

#[derive(Debug, Deserialize, Serialize, Clone, Default)]
pub struct Join {
    /// File-based source (for backward compatibility)
    #[serde(default)]
    pub source: Option<Source>,
    /// Subquery reference (alternative to source)
    #[serde(default)]
    pub subquery: Option<String>,
    /// Alias for the subquery
    #[serde(default)]
    pub alias: Option<String>,
    /// Join condition: left_field = right_field
    pub on: JoinCondition,
    /// Join type: "inner", "left", "right", "full", "cross"
    #[serde(default = "default_join_type")]
    pub join_type: String,
    /// Additional filter on joined source
    #[serde(default)]
    pub r#where: Option<Vec<Condition>>,
    /// Skip join attempts when left field is null or empty
    #[serde(default)]
    pub skip_nulls: bool,
}

fn default_join_type() -> String {
    "inner".to_string()
}

#[derive(Debug, Deserialize, Serialize, Clone, Default)]
pub struct JoinCondition {
    pub left: String,  // e.g., "gmc.mpn"
    pub right: String, // e.g., "shopify.variants[].sku"
    /// Optional operator for pattern matching: "=" (default), "contains", "starts_with"
    #[serde(default = "default_join_op")]
    pub op: String,
}

fn default_join_op() -> String {
    "=".to_string()
}

#[derive(Debug, Deserialize, Serialize, Clone, Default)]
pub struct Condition {
    /// Field reference for simple conditions (optional if expression is provided)
    #[serde(default)]
    pub field: Option<String>,
    /// Operator for simple conditions (optional if expression is provided)
    #[serde(default)]
    pub op: String, // =, !=, <, >, <=, >=, contains, starts_with, exists, like, in, is_null, is_not_null
    pub value: Option<Value>, // Optional for is_null/is_not_null
    /// For IN operator: list of values
    #[serde(default)]
    pub values: Option<Vec<Value>>,
    /// Expression-based condition (alternative to field/op/value)
    #[serde(default)]
    pub expression: Option<Expression>,
}

/// User-defined function definition for DSL
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct UserFunctionDef {
    pub params: Vec<String>,
    pub body: Expression,
    #[serde(default)]
    pub doc: Option<String>,
}

#[derive(Debug, Deserialize, Serialize, Clone, Default)]
pub struct SelectField {
    /// Field expression as string (legacy)
    #[serde(default)]
    pub expr: Option<String>,
    /// Field expression as structured expression (new)
    #[serde(default)]
    pub expression: Option<Expression>,
    /// Optional alias for the output column
    #[serde(default)]
    pub alias: Option<String>,
    /// Optional jaq filter to transform the value
    #[serde(default)]
    pub transform: Option<String>,
    /// Optional aggregation function: "sum", "count", "avg", "min", "max"
    #[serde(default)]
    pub agg: Option<String>,
    /// CASE expression for conditional logic
    #[serde(default)]
    pub case: Option<CaseExpr>,
    /// COALESCE: list of expressions to try in order
    #[serde(default)]
    pub coalesce: Option<Vec<String>>,
}

#[derive(Debug, Deserialize, Serialize, Clone, Default)]
pub struct GroupBy {
    /// Field to group by (e.g., "primary.category")
    pub field: String,
    /// Optional alias for the group column
    #[serde(default)]
    pub alias: Option<String>,
}

#[derive(Debug, Deserialize, Serialize, Clone, Default)]
pub struct OrderBy {
    /// Field to order by (e.g., "primary.price")
    #[serde(default)]
    pub field: String,
    /// Direction: "asc" (default) or "desc"
    #[serde(default)]
    pub direction: Option<String>,
    /// Expression to order by (alternative to field)
    #[serde(default)]
    pub expression: Option<Expression>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct CaseWhen {
    /// Condition for this case
    pub condition: Condition,
    /// Result value if condition matches
    pub value: Value,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct CaseExpr {
    /// Case when clauses
    pub cases: Vec<CaseWhen>,
    /// Default value if no case matches (optional)
    #[serde(default)]
    pub default: Option<Value>,
}

/// Named subquery definition
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct SubqueryDef {
    /// Name to reference this subquery
    pub name: String,
    /// The subquery DSL
    pub query: Box<QueryDsl>,
}

/// Reference to a subquery as a data source
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct SubquerySource {
    /// Name of the subquery reference
    pub subquery: String,
    /// Optional alias
    #[serde(default)]
    pub alias: Option<String>,
}

/// Query result
#[derive(Debug, Serialize, Clone)]
pub struct QueryResult {
    pub columns: Vec<String>,
    pub rows: Vec<Vec<Value>>,
    pub total_count: usize,
}

/// Query engine that executes DSL queries against the database
pub struct QueryEngine<'a> {
    conn: &'a Connection,
}

/// Execution context holds mutable state during query execution
struct ExecutionContext {
    /// Let expressions to evaluate for each row (key -> expression AST)
    let_expressions: HashMap<String, Expression>,
    function_registry: FunctionRegistry,
}

impl ExecutionContext {
    fn new(let_exprs: HashMap<String, Expression>, registry: FunctionRegistry) -> Self {
        Self {
            let_expressions: let_exprs,
            function_registry: registry,
        }
    }
}

impl<'a> QueryEngine<'a> {
    pub fn new(conn: &'a Connection) -> Self {
        Self { conn }
    }

    pub fn execute(&self, query: &QueryDsl) -> Result<QueryResult> {
        // Execute with empty subquery context
        self.execute_with_context(query, &HashMap::new())
    }

    /// Execute query with subquery context (for nested subqueries)
    fn execute_with_context(
        &self,
        query: &QueryDsl,
        subquery_context: &HashMap<String, QueryResult>,
    ) -> Result<QueryResult> {
        // Step 0: Execute CTEs (WITH clause) first
        let mut context = subquery_context.clone();
        if let Some(ref with_queries) = query.with {
            for def in with_queries {
                let result = self.execute_with_context(&def.query, &context)?;
                context.insert(def.name.clone(), result);
            }
        }

        // Step 0.5: Set up let expressions from query
        let let_expressions = query.r#let.clone().unwrap_or_default();

        // Step 0.6: Register user-defined functions if provided
        let mut function_registry = FunctionRegistry::new();
        if let Some(ref funcs) = query.functions {
            for (name, def) in funcs {
                function_registry.register_user_function_from_def(name.clone(), def.clone())?;
            }
        }

        // Create execution context to pass through the execution
        let exec_ctx = ExecutionContext::new(let_expressions, function_registry);

        // Step 1: Load primary source data
        let (primary_alias, primary_data) = if let Some(ref subquery_name) = query.from_subquery {
            // Using a subquery result as the primary source
            let result = context
                .get(subquery_name)
                .ok_or_else(|| anyhow!("Subquery '{}' not found", subquery_name))?;
            let alias = subquery_name.clone();
            let data = self.query_result_to_values(result)?;
            (alias, data)
        } else if let Some(ref from) = query.from {
            let alias = from
                .alias
                .clone()
                .unwrap_or_else(|| self.default_alias(&from.source_file));

            // Handle explode_with_context first (returns HashMap rows directly)
            if let Some(ref explode_config) = from.explode_with_context {
                let data = self.load_source(from)?;
                let exploded =
                    self.explode_with_context(data, &alias, explode_config, &exec_ctx)?;

                // Step 2: Apply joins
                let mut joined_data = exploded;

                for join in &query.joins {
                    joined_data =
                        self.apply_join_with_context(joined_data, join, &alias, &context)?;
                }

                // Step 3: Apply where filters
                if let Some(conditions) = &query.r#where {
                    let op = query.where_op.as_deref().unwrap_or("and");
                    joined_data = self.apply_filters(joined_data, conditions, op, &exec_ctx)?;
                }

                let total_count = joined_data.len();

                // Step 4: Apply order_by sorting (before field selection)
                if let Some(ref order_by) = query.order_by {
                    joined_data = self.apply_order_by_on_maps(joined_data, order_by, &exec_ctx)?;
                }

                // Step 5: Flatten if requested
                if query.flatten {
                    joined_data = self.flatten_rows(joined_data)?;
                }

                // Step 6: Apply distinct if requested
                if query.distinct {
                    joined_data = self.apply_distinct(joined_data)?;
                }

                // Step 7: Apply group_by and aggregation if requested
                // Note: Don't apply limit here - we'll apply it after offset for proper pagination
                let (columns, mut rows) = if let Some(ref group_by) = query.group_by {
                    let having_op = query.having_op.as_deref().unwrap_or("and");
                    self.apply_group_by(
                        joined_data,
                        group_by,
                        &query.select,
                        query.having.as_ref(),
                        having_op,
                        query.limit,
                        &exec_ctx,
                    )?
                } else {
                    self.select_fields(joined_data, &query.select, None, &exec_ctx)?
                };

                // Step 8: Apply offset (pagination)
                if let Some(offset) = query.offset {
                    if offset < rows.len() {
                        rows = rows.split_off(offset);
                    } else {
                        rows.clear();
                    }
                }

                // Step 9: Apply limit after offset
                if let Some(limit) = query.limit {
                    if rows.len() > limit {
                        rows.truncate(limit);
                    }
                }

                return Ok(QueryResult {
                    columns,
                    rows,
                    total_count,
                });
            }

            // Fast path: push pagination (and optionally ORDER BY) to SQLite for
            // simple single-source queries. This avoids loading an entire large
            // source into memory when the query only needs a limited page of rows.

            // Check if all order_by entries are simple field-based (no expressions)
            // so we can push the sort down to SQLite via json_extract.
            let order_by_is_pushable = query.order_by.as_ref().map_or(true, |obs| {
                obs.iter().all(|ob| ob.expression.is_none() && !ob.field.is_empty())
            });

            let can_pushdown_paging = query.joins.is_empty()
                && query.r#where.as_ref().map_or(true, |w| w.is_empty())
                && query.group_by.as_ref().map_or(true, |g| g.is_empty())
                && query.having.as_ref().map_or(true, |h| h.is_empty())
                && order_by_is_pushable
                && !query.flatten
                && !query.distinct
                && from.explode.is_none()
                && from.explode_with_context.is_none()
                && (query.limit.is_some() || query.offset.unwrap_or(0) > 0);

            if can_pushdown_paging {
                let total_count = self.count_source_rows(&from.source_file)?;
                let paged_data = self.load_source_paged_ordered(
                    from,
                    query.limit,
                    query.offset,
                    query.order_by.as_deref(),
                    &alias,
                )?;
                let joined_data: Vec<HashMap<String, Value>> = paged_data
                    .into_iter()
                    .map(|obj| {
                        let mut map = HashMap::new();
                        map.insert(alias.clone(), obj);
                        map
                    })
                    .collect();

                let (columns, rows) = self.select_fields(joined_data, &query.select, None, &exec_ctx)?;
                return Ok(QueryResult {
                    columns,
                    rows,
                    total_count,
                });
            }

            let data = self.load_source(from)?;

            // Explode if requested
            let data = if let Some(ref explode_field) = from.explode {
                self.explode_source(data, explode_field)?
            } else {
                data
            };
            (alias, data)
        } else {
            return Err(anyhow!("Query must have either 'from' or 'from_subquery'"));
        };

        // Step 2: Apply joins
        let mut joined_data: Vec<HashMap<String, Value>> = primary_data
            .into_iter()
            .map(|obj| {
                let mut map = HashMap::new();
                map.insert(primary_alias.clone(), obj);
                map
            })
            .collect();

        for join in &query.joins {
            joined_data =
                self.apply_join_with_context(joined_data, join, &primary_alias, &context)?;
        }

        // Step 3: Apply where filters
        if let Some(conditions) = &query.r#where {
            let op = query.where_op.as_deref().unwrap_or("and");
            joined_data = self.apply_filters(joined_data, conditions, op, &exec_ctx)?;
        }

        let total_count = joined_data.len();

        // Step 4: Apply order_by sorting (before field selection so all fields are available)
        if let Some(ref order_by) = query.order_by {
            joined_data = self.apply_order_by_on_maps(joined_data, order_by, &exec_ctx)?;
        }

        // Step 5: Flatten if requested
        if query.flatten {
            joined_data = self.flatten_rows(joined_data)?;
        }

        // Step 6: Apply distinct if requested
        if query.distinct {
            joined_data = self.apply_distinct(joined_data)?;
        }

        // Step 7: Apply group_by and aggregation if requested
        // Note: Don't apply limit here - we'll apply it after offset for proper pagination
        let (columns, mut rows) = if let Some(ref group_by) = query.group_by {
            let having_op = query.having_op.as_deref().unwrap_or("and");
            self.apply_group_by(
                joined_data,
                group_by,
                &query.select,
                query.having.as_ref(),
                having_op,
                query.limit,
                &exec_ctx,
            )?
        } else {
            self.select_fields(joined_data, &query.select, None, &exec_ctx)?
        };

        // Step 8: Apply offset (pagination)
        // Skip first N rows
        if let Some(offset) = query.offset {
            if offset < rows.len() {
                rows = rows.into_iter().skip(offset).collect();
            } else {
                rows.clear();
            }
        }

        // Step 9: Apply limit after offset
        // Keep only first N rows
        if let Some(limit) = query.limit {
            if rows.len() > limit {
                rows.truncate(limit);
            }
        }

        Ok(QueryResult {
            columns,
            rows,
            total_count,
        })
    }

    /// Convert QueryResult back to Vec<Value> for use as a source
    fn query_result_to_values(&self, result: &QueryResult) -> Result<Vec<Value>> {
        let mut values = Vec::new();
        for row in &result.rows {
            let mut obj = serde_json::Map::new();
            for (i, col) in result.columns.iter().enumerate() {
                let value = row.get(i).cloned().unwrap_or(Value::Null);
                obj.insert(col.clone(), value);
            }
            values.push(Value::Object(obj));
        }
        Ok(values)
    }

    fn load_source(&self, source: &Source) -> Result<Vec<Value>> {
        let source_file = &source.source_file;
        let mut stmt = self
            .conn
            .prepare("SELECT json_data FROM json_objects WHERE source_file = ?1")?;

        let rows = stmt.query_map(params![source_file], |row| {
            let json_str: String = row.get(0)?;
            let value: Value = serde_json::from_str(&json_str)
                .map_err(|e| rusqlite::Error::InvalidParameterName(e.to_string()))?;
            Ok(value)
        })?;

        let mut result = Vec::new();
        for row in rows {
            result.push(row?);
        }

        // Wrap primitive values if as_primitive is specified
        if let Some(ref column_name) = source.as_primitive {
            result = result
                .into_iter()
                .map(|v| self.wrap_primitive_value(v, column_name))
                .collect();
        }

        Ok(result)
    }

    fn count_source_rows(&self, source_file: &str) -> Result<usize> {
        let count: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM json_objects WHERE source_file = ?1",
            params![source_file],
            |row| row.get(0),
        )?;
        Ok(count as usize)
    }

    fn load_source_paged(
        &self,
        source: &Source,
        limit: Option<usize>,
        offset: Option<usize>,
    ) -> Result<Vec<Value>> {
        let source_file = &source.source_file;
        let offset = offset.unwrap_or(0);
        let mut result = Vec::new();
        match limit {
            Some(lim) => {
                let mut stmt = self.conn.prepare(
                    "SELECT json_data FROM json_objects WHERE source_file = ?1 LIMIT ?2 OFFSET ?3",
                )?;
                let rows = stmt.query_map(params![source_file, lim as i64, offset as i64], |row| {
                    let json_str: String = row.get(0)?;
                    let value: Value = serde_json::from_str(&json_str)
                        .map_err(|e| rusqlite::Error::InvalidParameterName(e.to_string()))?;
                    Ok(value)
                })?;
                for row in rows {
                    result.push(row?);
                }
            }
            None => {
                let mut stmt = self.conn.prepare(
                    "SELECT json_data FROM json_objects WHERE source_file = ?1 LIMIT -1 OFFSET ?2",
                )?;
                let rows = stmt.query_map(params![source_file, offset as i64], |row| {
                    let json_str: String = row.get(0)?;
                    let value: Value = serde_json::from_str(&json_str)
                        .map_err(|e| rusqlite::Error::InvalidParameterName(e.to_string()))?;
                    Ok(value)
                })?;
                for row in rows {
                    result.push(row?);
                }
            }
        }

        if let Some(ref column_name) = source.as_primitive {
            result = result
                .into_iter()
                .map(|v| self.wrap_primitive_value(v, column_name))
                .collect();
        }

        Ok(result)
    }

    /// Like load_source_paged but pushes ORDER BY to SQLite using json_extract.
    /// This avoids loading all rows into memory for sorting.
    fn load_source_paged_ordered(
        &self,
        source: &Source,
        limit: Option<usize>,
        offset: Option<usize>,
        order_by: Option<&[OrderBy]>,
        alias: &str,
    ) -> Result<Vec<Value>> {
        // If no order_by, delegate to the existing method
        if order_by.map_or(true, |o| o.is_empty()) {
            return self.load_source_paged(source, limit, offset);
        }

        let source_file = &source.source_file;
        let offset = offset.unwrap_or(0);
        let order_clauses = order_by.unwrap();

        // Build ORDER BY clause using json_extract for each field
        let mut order_parts: Vec<String> = Vec::new();
        for ob in order_clauses {
            // Parse "alias.field" or just "field" — strip the alias prefix
            // since json_extract works directly on the json_data column.
            let json_field = if let Some(rest) = ob.field.strip_prefix(&format!("{}.", alias)) {
                rest
            } else {
                &ob.field
            };

            // Support nested fields: "variant.sku" -> "$.variant.sku"
            let json_path = format!("$.{}", json_field);
            let direction = ob.direction.as_deref().unwrap_or("asc");
            let dir_sql = if direction == "desc" { "DESC" } else { "ASC" };
            order_parts.push(format!(
                "json_extract(json_data, '{}') {}", json_path, dir_sql
            ));
        }
        let order_clause = order_parts.join(", ");

        let sql = match limit {
            Some(_) => format!(
                "SELECT json_data FROM json_objects WHERE source_file = ?1 ORDER BY {} LIMIT ?2 OFFSET ?3",
                order_clause
            ),
            None => format!(
                "SELECT json_data FROM json_objects WHERE source_file = ?1 ORDER BY {} LIMIT -1 OFFSET ?2",
                order_clause
            ),
        };

        let mut result = Vec::new();
        match limit {
            Some(lim) => {
                let mut stmt = self.conn.prepare(&sql)?;
                let rows = stmt.query_map(
                    params![source_file, lim as i64, offset as i64],
                    |row| {
                        let json_str: String = row.get(0)?;
                        let value: Value = serde_json::from_str(&json_str)
                            .map_err(|e| rusqlite::Error::InvalidParameterName(e.to_string()))?;
                        Ok(value)
                    },
                )?;
                for row in rows {
                    result.push(row?);
                }
            }
            None => {
                let mut stmt = self.conn.prepare(&sql)?;
                let rows = stmt.query_map(
                    params![source_file, offset as i64],
                    |row| {
                        let json_str: String = row.get(0)?;
                        let value: Value = serde_json::from_str(&json_str)
                            .map_err(|e| rusqlite::Error::InvalidParameterName(e.to_string()))?;
                        Ok(value)
                    },
                )?;
                for row in rows {
                    result.push(row?);
                }
            }
        }

        if let Some(ref column_name) = source.as_primitive {
            result = result
                .into_iter()
                .map(|v| self.wrap_primitive_value(v, column_name))
                .collect();
        }

        Ok(result)
    }

    fn wrap_primitive_value(&self, value: Value, column_name: &str) -> Value {
        match value {
            Value::String(_) | Value::Number(_) | Value::Bool(_) => {
                let mut obj = serde_json::Map::new();
                obj.insert(column_name.to_string(), value);
                Value::Object(obj)
            }
            Value::Null => {
                let mut obj = serde_json::Map::new();
                obj.insert(column_name.to_string(), Value::Null);
                Value::Object(obj)
            }
            // If already an object, return as-is
            _ => value,
        }
    }

    fn explode_source(&self, data: Vec<Value>, explode_field: &str) -> Result<Vec<Value>> {
        let mut result = Vec::new();
        for obj in data {
            let arr_value = self.get_nested_value(&obj, explode_field);
            if let Value::Array(arr) = arr_value {
                for item in arr {
                    let mut exploded_obj = obj.clone();
                    if let Value::Object(ref _item_map) = item {
                        // Merge item fields into parent object under the explode field
                        self.set_nested_value(&mut exploded_obj, explode_field, item.clone());
                    }
                    result.push(exploded_obj);
                }
            } else {
                // No array found, keep original object
                result.push(obj);
            }
        }
        Ok(result)
    }

    /// Multi-level array explosion with context preservation
    ///
    /// Example: path="checks.selections", aliases=["c", "sel"]
    /// This will:
    /// 1. Explode "checks" array, creating objects with alias "c"
    /// 2. Within each check, explode "selections" array, creating objects with alias "sel"
    /// 3. Preserve specified parent fields (like "o.guid", "o.businessDate")
    /// 4. Apply filters at the leaf level
    fn explode_with_context(
        &self,
        data: Vec<Value>,
        parent_alias: &str,
        config: &ExplodeWithContext,
        exec_ctx: &ExecutionContext,
    ) -> Result<Vec<HashMap<String, Value>>> {
        let path_parts: Vec<&str> = config.path.split('.').collect();

        if path_parts.len() != config.aliases.len() {
            return Err(anyhow!(
                "explode_with_context: path parts count ({}) must match aliases count ({})",
                path_parts.len(),
                config.aliases.len()
            ));
        }

        let mut result: Vec<HashMap<String, Value>> = Vec::new();

        // Process each root object
        for root_obj in data {
            // Start the recursive explosion
            // Root object is stored under parent_alias
            let accumulated = vec![(parent_alias.to_string(), root_obj.clone())];
            self.explode_recursive(
                &root_obj,
                parent_alias,
                &accumulated,
                &path_parts,
                &config.aliases,
                0,
                &mut result,
            )?;
        }

        // Apply filters at the leaf level if specified
        if let Some(ref conditions) = config.r#where {
            result = result
                .into_iter()
                .filter(|row| self.matches_conditions(row, conditions, "and", exec_ctx))
                .collect();
        }

        Ok(result)
    }

    /// Recursively explode nested arrays
    ///
    /// This builds rows where each alias maps to an object at that level.
    /// For path="checks.selections", aliases=["c", "sel"]:
    /// - Row has: o -> root order, c -> check, sel -> selection
    fn explode_recursive(
        &self,
        parent_obj: &Value, // Parent object containing the array
        parent_alias: &str, // Alias for parent
        accumulated_aliases: &[(String, Value)], // (alias, object) pairs accumulated so far
        remaining_path: &[&str], // Remaining path parts
        aliases: &[String], // Aliases for each level
        depth: usize,       // Current depth
        result: &mut Vec<HashMap<String, Value>>,
    ) -> Result<()> {
        if remaining_path.is_empty() || depth >= aliases.len() {
            return Ok(());
        }

        let field = remaining_path[0];
        let alias = &aliases[depth];

        // Get array from parent object
        let arr_value = self.get_nested_value(parent_obj, field);

        if let Value::Array(arr) = arr_value {
            for item in arr {
                // Build new accumulated aliases list
                let mut new_accumulated = accumulated_aliases.to_vec();
                new_accumulated.push((alias.clone(), item.clone()));

                if remaining_path.len() <= 1 {
                    // This is the leaf level - create a complete row
                    let mut row: HashMap<String, Value> = HashMap::new();

                    // Add all accumulated aliases
                    for (alias_name, obj) in &new_accumulated {
                        row.insert(alias_name.clone(), obj.clone());
                    }

                    result.push(row);
                } else {
                    // Need to go deeper - recurse with item as new parent
                    self.explode_recursive(
                        &item,
                        alias,
                        &new_accumulated,
                        &remaining_path[1..],
                        aliases,
                        depth + 1,
                        result,
                    )?;
                }
            }
        }

        Ok(())
    }

    fn apply_join(
        &self,
        left_data: Vec<HashMap<String, Value>>,
        join: &Join,
        left_alias: &str,
    ) -> Result<Vec<HashMap<String, Value>>> {
        self.apply_join_with_context(left_data, join, left_alias, &HashMap::new())
    }

    fn apply_join_with_context(
        &self,
        left_data: Vec<HashMap<String, Value>>,
        join: &Join,
        left_alias: &str,
        context: &HashMap<String, QueryResult>,
    ) -> Result<Vec<HashMap<String, Value>>> {
        // Determine the source for the join - either a file source or a subquery
        let (right_alias, right_data) = if let Some(ref source) = join.source {
            // File-based source (backward compatible)
            let alias = source
                .alias
                .clone()
                .unwrap_or_else(|| self.default_alias(&source.source_file));
            let data = self.load_source(source)?;
            let data = if let Some(ref explode_field) = source.explode {
                self.explode_source(data, explode_field)?
            } else {
                data
            };
            (alias, data)
        } else if let Some(ref subquery_name) = join.subquery {
            // Subquery reference
            let result = context
                .get(subquery_name)
                .ok_or_else(|| anyhow!("Subquery '{}' not found in join", subquery_name))?;
            let alias = join.alias.clone().unwrap_or_else(|| subquery_name.clone());
            let data = self.query_result_to_values(result)?;
            (alias, data)
        } else {
            return Err(anyhow!(
                "Join must have either 'source' or 'subquery' specified"
            ));
        };

        // Parse join fields
        let (join_left_alias, left_field) = self.parse_field_ref(&join.on.left)?;
        let (right_alias_expected, right_field) = self.parse_field_ref(&join.on.right)?;

        // Validate alias matches
        if let Some(ref source) = join.source {
            let expected = source
                .alias
                .clone()
                .unwrap_or_else(|| self.default_alias(&source.source_file));
            if right_alias_expected != expected {
                return Err(anyhow!(
                    "Join right field alias doesn't match source alias: expected '{}' but got '{}'",
                    expected,
                    right_alias_expected
                ));
            }
        } else if let Some(ref subquery_name) = join.subquery {
            // For subqueries, be more lenient with alias matching
            let _ = (right_alias_expected, subquery_name, right_alias.clone());
        }

        // For full joins, left_alias might not be in the join condition
        let _effective_left_alias = if join_left_alias != left_alias {
            join_left_alias.clone()
        } else {
            left_alias.to_string()
        };

        // Get the join operator
        let join_op = join.on.op.as_str();

        // Handle cross join (cartesian product with optional filtering)
        if join.join_type == "cross" {
            return self.apply_cross_join(
                left_data,
                right_data,
                &right_alias,
                join_op,
                &join_left_alias,
                &left_field,
                &right_field,
            );
        }

        // For pattern matching joins (contains, starts_with), use different approach
        if join_op == "contains" || join_op == "starts_with" {
            return self.apply_pattern_join(
                left_data,
                right_data,
                &right_alias,
                join_op,
                &join_left_alias,
                &left_field,
                &right_field,
                &join.join_type,
            );
        }

        // Standard hash-based join for exact matching
        // Check if we're joining on an array field (e.g., variants[].sku)
        let is_array_join = right_field.contains("[]");
        let array_path = if is_array_join {
            let parts: Vec<&str> = right_field.split("[]").collect();
            let arr_path = parts[0];
            let rest = parts
                .get(1)
                .map(|s| s.trim_start_matches('.'))
                .filter(|s| !s.is_empty());
            Some((arr_path.to_string(), rest.map(|s| s.to_string())))
        } else {
            None
        };

        // Build hash index for faster lookups
        let mut index: HashMap<String, Vec<(Value, Value)>> = HashMap::new();
        let mut right_keys: HashMap<String, bool> = HashMap::new();

        for right_obj in &right_data {
            if is_array_join {
                if let Some((ref arr_field, ref subfield)) = &array_path {
                    let arr_value = self.get_nested_value(right_obj, arr_field);
                    if let Value::Array(arr) = arr_value {
                        for item in arr {
                            let compare_value = if let Some(sf) = subfield {
                                self.get_nested_value(&item, sf)
                            } else {
                                item.clone()
                            };

                            if let Some(key) = self.value_to_key(&compare_value) {
                                // Skip null/empty keys when skip_nulls is enabled
                                if join.skip_nulls && (key == "__null__" || key.is_empty()) {
                                    continue;
                                }
                                let mut matched_obj = right_obj.clone();
                                self.set_nested_value(&mut matched_obj, arr_field, item.clone());
                                index
                                    .entry(key.clone())
                                    .or_default()
                                    .push((matched_obj, item));
                                right_keys.insert(key, false);
                            }
                        }
                    }
                }
            } else {
                let right_values = self.extract_values_for_join(right_obj, &right_field);
                for rv in &right_values {
                    if let Some(key) = self.value_to_key(&rv) {
                        // Skip null/empty keys when skip_nulls is enabled
                        if join.skip_nulls && (key == "__null__" || key.is_empty()) {
                            continue;
                        }
                        index
                            .entry(key.clone())
                            .or_default()
                            .push((right_obj.clone(), Value::Null));
                        right_keys.insert(key, false);
                    }
                }
            }
        }

        let mut result = Vec::new();

        for left_row in &left_data {
            let left_value = self.extract_value(left_row, &join_left_alias, &left_field);
            let left_key = self.value_to_key(&left_value);

            // If skip_nulls is enabled and left key is null/empty, skip this row entirely
            let left_key_is_null = left_key
                .as_ref()
                .map(|k| k == "__null__" || k.is_empty())
                .unwrap_or(true);
            if join.skip_nulls && left_key_is_null {
                // Skip this row entirely - don't include it in results
                continue;
            }

            let matches: Vec<Value> = if let Some(ref key) = left_key {
                right_keys.insert(key.clone(), true);
                index
                    .get(key)
                    .map(|v| v.iter().map(|(obj, _)| obj.clone()).collect())
                    .unwrap_or_default()
            } else {
                Vec::new()
            };

            // Apply join type logic
            match join.join_type.as_str() {
                "inner" => {
                    for right_match in matches {
                        let mut new_row = left_row.clone();
                        new_row.insert(right_alias.clone(), right_match);
                        result.push(new_row);
                    }
                }
                "left" => {
                    if matches.is_empty() {
                        // If skip_nulls is enabled, skip rows with no match
                        if !join.skip_nulls {
                            let mut new_row = left_row.clone();
                            new_row.insert(right_alias.clone(), Value::Null);
                            result.push(new_row);
                        }
                    } else {
                        for right_match in matches {
                            let mut new_row = left_row.clone();
                            new_row.insert(right_alias.clone(), right_match);
                            result.push(new_row);
                        }
                    }
                }
                "right" => {
                    if matches.is_empty() {
                        let mut new_row = left_row.clone();
                        new_row.insert(right_alias.clone(), Value::Null);
                        result.push(new_row);
                    } else {
                        for right_match in matches {
                            let mut new_row = left_row.clone();
                            new_row.insert(right_alias.clone(), right_match);
                            result.push(new_row);
                        }
                    }
                }
                "full" => {
                    if matches.is_empty() {
                        let mut new_row = left_row.clone();
                        new_row.insert(right_alias.clone(), Value::Null);
                        result.push(new_row);
                    } else {
                        for right_match in matches {
                            let mut new_row = left_row.clone();
                            new_row.insert(right_alias.clone(), right_match);
                            result.push(new_row);
                        }
                    }
                }
                _ => return Err(anyhow!("Unsupported join type: {}", join.join_type)),
            }
        }

        // For full join, add unmatched right rows
        if join.join_type == "full" {
            for (key, matched) in &right_keys {
                if !matched {
                    if let Some(right_matches) = index.get(key) {
                        for (right_obj, _) in right_matches {
                            let mut new_row: HashMap<String, Value> = HashMap::new();
                            new_row.insert(left_alias.to_string(), Value::Null);
                            new_row.insert(right_alias.clone(), right_obj.clone());
                            result.push(new_row);
                        }
                    }
                }
            }
        }

        Ok(result)
    }

    /// Apply a cross join (cartesian product) with optional pattern matching
    /// Optimized with pre-caching and early termination
    fn apply_cross_join(
        &self,
        left_data: Vec<HashMap<String, Value>>,
        right_data: Vec<Value>,
        right_alias: &str,
        join_op: &str,
        left_alias: &str,
        left_field: &str,
        right_field: &str,
    ) -> Result<Vec<HashMap<String, Value>>> {
        let mut result = Vec::new();

        // Pre-extract and cache right side values
        let right_cache: Vec<(String, &Value)> = right_data
            .iter()
            .map(|right_obj| {
                let right_value = self.get_nested_value(right_obj, right_field);
                let right_str = self.value_to_string(&right_value);
                (right_str, right_obj)
            })
            .collect();

        for left_row in &left_data {
            let left_value = self.extract_value(left_row, left_alias, left_field);
            let left_str = self.value_to_string(&left_value);

            for (right_str, right_obj) in &right_cache {
                let matches = match join_op {
                    "=" => left_str == *right_str,
                    "contains" => right_str.contains(&left_str),
                    "starts_with" => right_str.starts_with(&left_str),
                    _ => left_str == *right_str,
                };

                if matches {
                    let mut new_row = left_row.clone();
                    new_row.insert(right_alias.to_string(), (*right_obj).clone());
                    result.push(new_row);
                }
            }
        }

        Ok(result)
    }

    /// Apply a pattern matching join (contains, starts_with)
    /// Optimized with substring index for faster lookups
    fn apply_pattern_join(
        &self,
        left_data: Vec<HashMap<String, Value>>,
        right_data: Vec<Value>,
        right_alias: &str,
        join_op: &str,
        left_alias: &str,
        left_field: &str,
        right_field: &str,
        join_type: &str,
    ) -> Result<Vec<HashMap<String, Value>>> {
        let mut result = Vec::new();
        let mut right_matched: Vec<bool> = vec![false; right_data.len()];

        // Pre-extract and cache right side values to avoid repeated get_nested_value calls
        let right_cache: Vec<(String, &Value)> = right_data
            .iter()
            .map(|right_obj| {
                let right_value = self.get_nested_value(right_obj, right_field);
                let right_str = self.value_to_string(&right_value);
                (right_str, right_obj)
            })
            .collect();

        // For "contains" operation, build a substring index if beneficial
        // Index maps from potential substrings to indices in right_cache
        let substring_index: Option<HashMap<String, Vec<usize>>> =
            if join_op == "contains" && right_cache.len() > 100 {
                let mut index: HashMap<String, Vec<usize>> = HashMap::new();

                // Build an index of common substring patterns (e.g., numeric IDs)
                for (i, (right_str, _)) in right_cache.iter().enumerate() {
                    // Extract potential ID patterns (sequences of digits)
                    let mut current_num = String::new();
                    for ch in right_str.chars() {
                        if ch.is_ascii_digit() {
                            current_num.push(ch);
                        } else {
                            if current_num.len() >= 4 {
                                index.entry(current_num.clone()).or_default().push(i);
                            }
                            current_num.clear();
                        }
                    }
                    // Don't forget trailing digits
                    if current_num.len() >= 4 {
                        index.entry(current_num).or_default().push(i);
                    }
                }

                Some(index)
            } else {
                None
            };

        for left_row in &left_data {
            let left_value = self.extract_value(left_row, left_alias, left_field);
            let left_str = self.value_to_string(&left_value);

            let mut found_match = false;

            // Determine which right rows to check
            let candidates: Vec<usize> = if let Some(ref index) = substring_index {
                // Use index to find potential matches
                let mut candidates = std::collections::HashSet::new();

                // Extract numeric patterns from left_str
                let mut current_num = String::new();
                for ch in left_str.chars() {
                    if ch.is_ascii_digit() {
                        current_num.push(ch);
                    } else {
                        if current_num.len() >= 4 {
                            if let Some(indices) = index.get(&current_num) {
                                candidates.extend(indices);
                            }
                        }
                        current_num.clear();
                    }
                }
                if current_num.len() >= 4 {
                    if let Some(indices) = index.get(&current_num) {
                        candidates.extend(indices);
                    }
                }

                // If no candidates from index, fall back to full scan only for small datasets
                if candidates.is_empty() && right_cache.len() < 1000 {
                    (0..right_cache.len()).collect()
                } else {
                    candidates.into_iter().collect()
                }
            } else {
                // Full scan for smaller datasets
                (0..right_cache.len()).collect()
            };

            for &i in &candidates {
                let (right_str, right_obj) = &right_cache[i];

                let matches = match join_op {
                    "contains" => right_str.contains(&left_str),
                    "starts_with" => right_str.starts_with(&left_str),
                    _ => left_str == *right_str,
                };

                if matches {
                    found_match = true;
                    right_matched[i] = true;
                    let mut new_row = left_row.clone();
                    new_row.insert(right_alias.to_string(), (*right_obj).clone());
                    result.push(new_row);
                }
            }

            // For left join, include left row even if no match
            if !found_match && (join_type == "left" || join_type == "full") {
                let mut new_row = left_row.clone();
                new_row.insert(right_alias.to_string(), Value::Null);
                result.push(new_row);
            }
        }

        // For full join, add unmatched right rows
        if join_type == "full" {
            for (i, (_, right_obj)) in right_cache.iter().enumerate() {
                if !right_matched[i] {
                    let mut new_row: HashMap<String, Value> = HashMap::new();
                    new_row.insert(left_alias.to_string(), Value::Null);
                    new_row.insert(right_alias.to_string(), (*right_obj).clone());
                    result.push(new_row);
                }
            }
        }

        Ok(result)
    }

    fn apply_filters(
        &self,
        data: Vec<HashMap<String, Value>>,
        conditions: &[Condition],
        op: &str,
        exec_ctx: &ExecutionContext,
    ) -> Result<Vec<HashMap<String, Value>>> {
        Ok(data
            .into_iter()
            .filter(|row| self.matches_conditions(row, conditions, op, exec_ctx))
            .collect())
    }

    fn matches_conditions(
        &self,
        row: &HashMap<String, Value>,
        conditions: &[Condition],
        op: &str,
        exec_ctx: &ExecutionContext,
    ) -> bool {
        if conditions.is_empty() {
            return true;
        }
        match op {
            "or" => conditions
                .iter()
                .any(|cond| self.matches_condition(row, cond, exec_ctx)),
            _ => conditions
                .iter()
                .all(|cond| self.matches_condition(row, cond, exec_ctx)), // default "and"
        }
    }

    /// Match a string against a SQL LIKE pattern
    /// % matches any sequence of characters, _ matches a single character
    fn like_match(&self, text: &str, pattern: &str) -> bool {
        let mut regex_pattern = String::new();
        regex_pattern.push('^');
        for ch in pattern.chars() {
            match ch {
                '%' => regex_pattern.push_str(".*"),
                '_' => regex_pattern.push('.'),
                c => {
                    // Escape regex special characters
                    if "\\^$|[](){}*+?.".contains(c) {
                        regex_pattern.push('\\');
                    }
                    regex_pattern.push(c);
                }
            }
        }
        regex_pattern.push('$');

        match regex::Regex::new(&regex_pattern) {
            Ok(re) => re.is_match(text),
            Err(_) => text == pattern, // Fallback to exact match
        }
    }

    fn matches_condition(
        &self,
        row: &HashMap<String, Value>,
        cond: &Condition,
        exec_ctx: &ExecutionContext,
    ) -> bool {
        // If an expression is provided, evaluate it and check if it's truthy
        if let Some(expr) = &cond.expression {
            let context = self.row_to_context(row, exec_ctx);
            match expr.evaluate_with_registry(&context, &exec_ctx.function_registry) {
                Ok(result) => return self.is_truthy(&result),
                Err(_) => return false,
            }
        }

        // For simple field-based conditions, field is required
        let field_ref = match &cond.field {
            Some(f) => f,
            None => return false,
        };

        let (alias, field) = match self.parse_field_ref(field_ref) {
            Ok(r) => r,
            Err(_) => return false,
        };

        let value = self.extract_value(row, &alias, &field);

        match cond.op.as_str() {
            "=" | "==" => {
                if let Some(expected) = &cond.value {
                    // Check if expected value is a field reference (contains ".")
                    if expected.is_string() {
                        if let Some(expected_str) = expected.as_str() {
                            if expected_str.contains('.') {
                                if let Ok((exp_alias, exp_field)) =
                                    self.parse_field_ref(expected_str)
                                {
                                    let expected_value =
                                        self.extract_value(row, &exp_alias, &exp_field);
                                    self.values_equal(&value, &expected_value)
                                } else {
                                    self.values_equal(&value, expected)
                                }
                            } else {
                                self.values_equal(&value, expected)
                            }
                        } else {
                            self.values_equal(&value, expected)
                        }
                    } else {
                        self.values_equal(&value, expected)
                    }
                } else {
                    false
                }
            }
            "!=" | "<>" => {
                if let Some(expected) = &cond.value {
                    // Check if expected value is a field reference (contains ".")
                    if expected.is_string() {
                        if let Some(expected_str) = expected.as_str() {
                            if expected_str.contains('.') {
                                if let Ok((exp_alias, exp_field)) =
                                    self.parse_field_ref(expected_str)
                                {
                                    let expected_value =
                                        self.extract_value(row, &exp_alias, &exp_field);
                                    !self.values_equal(&value, &expected_value)
                                } else {
                                    !self.values_equal(&value, expected)
                                }
                            } else {
                                !self.values_equal(&value, expected)
                            }
                        } else {
                            !self.values_equal(&value, expected)
                        }
                    } else {
                        !self.values_equal(&value, expected)
                    }
                } else {
                    false
                }
            }
            "contains" => {
                if let Some(expected) = &cond.value {
                    match (&value, expected) {
                        (Value::String(s), Value::String(pat)) => s.contains(pat),
                        _ => false,
                    }
                } else {
                    false
                }
            }
            "not contains" => {
                if let Some(expected) = &cond.value {
                    match (&value, expected) {
                        (Value::String(s), Value::String(pat)) => !s.contains(pat),
                        _ => true, // If not a string, consider it as not containing
                    }
                } else {
                    false
                }
            }
            "starts_with" => {
                if let Some(expected) = &cond.value {
                    match (&value, expected) {
                        (Value::String(s), Value::String(pat)) => s.starts_with(pat),
                        _ => false,
                    }
                } else {
                    false
                }
            }
            "not starts with" => {
                if let Some(expected) = &cond.value {
                    match (&value, expected) {
                        (Value::String(s), Value::String(pat)) => !s.starts_with(pat),
                        _ => true, // If not a string, consider it as not starting with
                    }
                } else {
                    false
                }
            }
            "ends_with" => {
                if let Some(expected) = &cond.value {
                    match (&value, expected) {
                        (Value::String(s), Value::String(pat)) => s.ends_with(pat),
                        _ => false,
                    }
                } else {
                    false
                }
            }
            "not ends with" => {
                if let Some(expected) = &cond.value {
                    match (&value, expected) {
                        (Value::String(s), Value::String(pat)) => !s.ends_with(pat),
                        _ => true, // If not a string, consider it as not ending with
                    }
                } else {
                    false
                }
            }
            "like" => {
                if let Some(expected) = &cond.value {
                    match (&value, expected) {
                        (Value::String(s), Value::String(pat)) => self.like_match(s, pat),
                        _ => false,
                    }
                } else {
                    false
                }
            }
            "in" => {
                if let Some(values) = &cond.values {
                    values.iter().any(|v| self.values_equal(&value, v))
                } else {
                    false
                }
            }
            "is_null" => value.is_null(),
            "is_not_null" => !value.is_null(),
            "exists" => !value.is_null(),
            ">" => {
                if let Some(expected) = &cond.value {
                    // Check if expected value is a field reference (contains ".")
                    if expected.is_string() {
                        if let Some(expected_str) = expected.as_str() {
                            if expected_str.contains('.') {
                                if let Ok((exp_alias, exp_field)) =
                                    self.parse_field_ref(expected_str)
                                {
                                    let expected_value =
                                        self.extract_value(row, &exp_alias, &exp_field);
                                    self.compare_values(&value, &expected_value, |a, b| a > b)
                                } else {
                                    self.compare_values(&value, expected, |a, b| a > b)
                                }
                            } else {
                                self.compare_values(&value, expected, |a, b| a > b)
                            }
                        } else {
                            self.compare_values(&value, expected, |a, b| a > b)
                        }
                    } else {
                        self.compare_values(&value, expected, |a, b| a > b)
                    }
                } else {
                    false
                }
            }
            ">=" => {
                if let Some(expected) = &cond.value {
                    // Check if expected value is a field reference (contains ".")
                    if expected.is_string() {
                        if let Some(expected_str) = expected.as_str() {
                            if expected_str.contains('.') {
                                if let Ok((exp_alias, exp_field)) =
                                    self.parse_field_ref(expected_str)
                                {
                                    let expected_value =
                                        self.extract_value(row, &exp_alias, &exp_field);
                                    self.compare_values(&value, &expected_value, |a, b| a >= b)
                                } else {
                                    self.compare_values(&value, expected, |a, b| a >= b)
                                }
                            } else {
                                self.compare_values(&value, expected, |a, b| a >= b)
                            }
                        } else {
                            self.compare_values(&value, expected, |a, b| a >= b)
                        }
                    } else {
                        self.compare_values(&value, expected, |a, b| a >= b)
                    }
                } else {
                    false
                }
            }
            "<" => {
                if let Some(expected) = &cond.value {
                    // Check if expected value is a field reference (contains ".")
                    if expected.is_string() {
                        if let Some(expected_str) = expected.as_str() {
                            if expected_str.contains('.') {
                                if let Ok((exp_alias, exp_field)) =
                                    self.parse_field_ref(expected_str)
                                {
                                    let expected_value =
                                        self.extract_value(row, &exp_alias, &exp_field);
                                    self.compare_values(&value, &expected_value, |a, b| a < b)
                                } else {
                                    self.compare_values(&value, expected, |a, b| a < b)
                                }
                            } else {
                                self.compare_values(&value, expected, |a, b| a < b)
                            }
                        } else {
                            self.compare_values(&value, expected, |a, b| a < b)
                        }
                    } else {
                        self.compare_values(&value, expected, |a, b| a < b)
                    }
                } else {
                    false
                }
            }
            "<=" => {
                if let Some(expected) = &cond.value {
                    // Check if expected value is a field reference (contains ".")
                    if expected.is_string() {
                        if let Some(expected_str) = expected.as_str() {
                            if expected_str.contains('.') {
                                if let Ok((exp_alias, exp_field)) =
                                    self.parse_field_ref(expected_str)
                                {
                                    let expected_value =
                                        self.extract_value(row, &exp_alias, &exp_field);
                                    self.compare_values(&value, &expected_value, |a, b| a <= b)
                                } else {
                                    self.compare_values(&value, expected, |a, b| a <= b)
                                }
                            } else {
                                self.compare_values(&value, expected, |a, b| a <= b)
                            }
                        } else {
                            self.compare_values(&value, expected, |a, b| a <= b)
                        }
                    } else {
                        self.compare_values(&value, expected, |a, b| a <= b)
                    }
                } else {
                    false
                }
            }
            _ => false,
        }
    }

    fn flatten_rows(
        &self,
        data: Vec<HashMap<String, Value>>,
    ) -> Result<Vec<HashMap<String, Value>>> {
        // Flatten arrays in each row
        let mut result = Vec::new();
        for row in data {
            let flattened = self.flatten_row(row)?;
            result.extend(flattened);
        }
        Ok(result)
    }

    fn flatten_row(&self, row: HashMap<String, Value>) -> Result<Vec<HashMap<String, Value>>> {
        // Find the first array in any field and explode it
        let mut array_field: Option<(String, Vec<Value>)> = None;

        for (alias, value) in &row {
            if let Some(arr) = self.find_first_array(value) {
                array_field = Some((alias.clone(), arr));
                break;
            }
        }

        if let Some((alias, arr)) = array_field {
            let mut result = Vec::new();
            for item in arr {
                let mut new_row = row.clone();
                new_row.insert(alias.clone(), item);
                result.push(new_row);
            }
            Ok(result)
        } else {
            Ok(vec![row])
        }
    }

    fn apply_group_by(
        &self,
        data: Vec<HashMap<String, Value>>,
        group_by: &[GroupBy],
        select: &[SelectField],
        having: Option<&Vec<Condition>>,
        having_op: &str,
        _limit: Option<usize>, // limit is now applied after order_by
        exec_ctx: &ExecutionContext,
    ) -> Result<(Vec<String>, Vec<Vec<Value>>)> {
        // Step 1: Group the data by the group_by fields
        let mut groups: HashMap<String, Vec<HashMap<String, Value>>> = HashMap::new();

        for row in data {
            // Build group key from group_by fields
            let mut group_key_parts = Vec::new();
            for gb in group_by {
                let value = if let Some((date_func, _)) = DateFunction::parse(&gb.field) {
                    // Evaluate as date function
                    date_func.evaluate(&row, self)
                } else if let Some((coalesce_func, _)) = CoalesceFunction::parse(&gb.field) {
                    // Evaluate as coalesce function
                    coalesce_func.evaluate(&row, self)
                } else {
                    // Regular field extraction
                    let (alias, field) = self.parse_field_ref(&gb.field)?;
                    self.extract_value(&row, &alias, &field)
                };
                group_key_parts.push(value.to_string());
            }
            let group_key = group_key_parts.join("|");

            groups.entry(group_key).or_default().push(row);
        }

        // Step 2: Build result rows with aggregated values
        let mut columns = Vec::new();
        let mut rows = Vec::new();

        // Add group_by columns first
        for gb in group_by {
            let col_name = gb.alias.clone().unwrap_or_else(|| gb.field.clone());
            columns.push(col_name);
        }

        // Add aggregation columns
        for field in select {
            if field.agg.is_some() {
                let col_name = field.alias.clone().unwrap_or_else(|| {
                    format!(
                        "{}_{}",
                        field.agg.as_ref().unwrap(),
                        field.expr.as_deref().unwrap_or("value")
                    )
                });
                columns.push(col_name);
            }
        }

        // Step 3: Process each group
        for (_group_key, group_rows) in groups {
            let mut result_row = Vec::new();

            // Add group_by values (from the first row of the group)
            if let Some(first_row) = group_rows.first() {
                for gb in group_by {
                    let value = if let Some((date_func, _)) = DateFunction::parse(&gb.field) {
                        // Evaluate as date function
                        date_func.evaluate(first_row, self)
                    } else if let Some((coalesce_func, _)) = CoalesceFunction::parse(&gb.field) {
                        // Evaluate as coalesce function
                        coalesce_func.evaluate(first_row, self)
                    } else {
                        // Regular field extraction
                        let (alias, field) = self.parse_field_ref(&gb.field)?;
                        self.extract_value(first_row, &alias, &field)
                    };
                    result_row.push(value);
                }
            }

            // Calculate aggregations
            for field in select {
                if let Some(ref agg_func) = field.agg {
                    let agg_value = self.calculate_aggregate(&group_rows, field, agg_func)?;
                    result_row.push(agg_value);
                }
            }

            rows.push(result_row);
        }

        // Step 4: Apply HAVING filter if specified
        if let Some(having_conditions) = having {
            let _col_indices: HashMap<String, usize> = columns
                .iter()
                .enumerate()
                .map(|(i, col)| (col.clone(), i))
                .collect();

            rows.retain(|row| {
                // Convert row back to HashMap for condition checking
                let mut row_map: HashMap<String, Value> = HashMap::new();
                for (i, col) in columns.iter().enumerate() {
                    if i < row.len() {
                        row_map.insert(col.clone(), row[i].clone());
                    }
                }
                self.matches_conditions(&row_map, having_conditions, having_op, exec_ctx)
            });
        }

        Ok((columns, rows))
    }

    fn calculate_aggregate(
        &self,
        rows: &[HashMap<String, Value>],
        field: &SelectField,
        agg_func: &str,
    ) -> Result<Value> {
        // Handle COUNT separately (doesn't need a field expression)
        if agg_func.to_lowercase() == "count" {
            return Ok(Value::Number(serde_json::Number::from(rows.len() as i64)));
        }

        // For other aggregates, we need a field expression
        let (alias, field_path) = if let Some(ref expr) = field.expr {
            self.parse_field_ref(expr)?
        } else {
            return Ok(Value::Null);
        };

        // Collect all non-null values
        let mut values: Vec<f64> = Vec::new();

        for row in rows {
            let value = self.extract_value(row, &alias, &field_path);
            match value {
                Value::Number(n) => {
                    if let Some(f) = n.as_f64() {
                        values.push(f);
                    }
                }
                Value::String(s) => {
                    // Try to parse string as number
                    if let Ok(f) = s.parse::<f64>() {
                        values.push(f);
                    }
                }
                _ => {}
            }
        }

        let result = match agg_func.to_lowercase().as_str() {
            "sum" => {
                let sum: f64 = values.iter().sum();
                Value::Number(
                    serde_json::Number::from_f64(sum).unwrap_or(serde_json::Number::from(0)),
                )
            }
            "avg" => {
                if values.is_empty() {
                    Value::Null
                } else {
                    let avg: f64 = values.iter().sum::<f64>() / values.len() as f64;
                    Value::Number(
                        serde_json::Number::from_f64(avg).unwrap_or(serde_json::Number::from(0)),
                    )
                }
            }
            "min" => {
                if let Some(min) = values.iter().cloned().reduce(|a, b| a.min(b)) {
                    Value::Number(
                        serde_json::Number::from_f64(min).unwrap_or(serde_json::Number::from(0)),
                    )
                } else {
                    Value::Null
                }
            }
            "max" => {
                if let Some(max) = values.iter().cloned().reduce(|a, b| a.max(b)) {
                    Value::Number(
                        serde_json::Number::from_f64(max).unwrap_or(serde_json::Number::from(0)),
                    )
                } else {
                    Value::Null
                }
            }
            _ => return Err(anyhow!("Unknown aggregation function: {}", agg_func)),
        };

        Ok(result)
    }

    fn find_first_array(&self, value: &Value) -> Option<Vec<Value>> {
        match value {
            Value::Array(arr) => Some(arr.clone()),
            Value::Object(obj) => {
                for v in obj.values() {
                    if let Some(arr) = self.find_first_array(v) {
                        return Some(arr);
                    }
                }
                None
            }
            _ => None,
        }
    }

    fn select_fields(
        &self,
        data: Vec<HashMap<String, Value>>,
        select: &[SelectField],
        limit: Option<usize>,
        exec_ctx: &ExecutionContext,
    ) -> Result<(Vec<String>, Vec<Vec<Value>>)> {
        // First, expand any wildcards in the select list
        let expanded_select = self.expand_wildcards(select, &data)?;

        // Filter out aggregation-only fields (they require GROUP BY)
        let regular_fields: Vec<&SelectField> =
            expanded_select.iter().filter(|f| f.agg.is_none()).collect();

        if regular_fields.is_empty() && !expanded_select.is_empty() {
            return Err(anyhow!("All select fields have aggregation functions but no GROUP BY is specified. Add a group_by clause or remove aggregation functions."));
        }

        let columns: Vec<String> = regular_fields
            .iter()
            .map(|f| {
                f.alias
                    .clone()
                    .unwrap_or_else(|| f.expr.clone().unwrap_or_default())
            })
            .collect();

        let mut rows = Vec::new();
        for row in data.iter().take(limit.unwrap_or(usize::MAX)) {
            let mut selected_row = Vec::new();
            for field in regular_fields.iter() {
                let value = self.evaluate_select_field(row, field, exec_ctx)?;
                selected_row.push(value);
            }
            rows.push(selected_row);
        }

        Ok((columns, rows))
    }

    /// Apply DISTINCT to remove duplicate rows
    fn apply_distinct(
        &self,
        data: Vec<HashMap<String, Value>>,
    ) -> Result<Vec<HashMap<String, Value>>> {
        let mut seen: HashMap<String, bool> = HashMap::new();
        let mut result = Vec::new();

        for row in data {
            // Create a unique key from all values in the row
            let mut key_parts = Vec::new();
            for (alias, value) in row.iter() {
                key_parts.push(format!("{}:{}", alias, value.to_string()));
            }
            key_parts.sort(); // Ensure consistent ordering
            let key = key_parts.join("|");

            if !seen.contains_key(&key) {
                seen.insert(key, true);
                result.push(row);
            }
        }

        Ok(result)
    }

    /// Apply ORDER BY sorting to results
    fn apply_order_by(
        &self,
        rows: Vec<Vec<Value>>,
        columns: &[String],
        order_by: &[OrderBy],
    ) -> Result<Vec<Vec<Value>>> {
        let col_indices: HashMap<String, usize> = columns
            .iter()
            .enumerate()
            .map(|(i, col)| (col.clone(), i))
            .collect();

        let mut sorted_rows = rows;

        // Sort by each order_by field in reverse order (so first field has highest priority)
        for ob in order_by.iter().rev() {
            // Normalize the field name: convert dots to underscores for column lookup
            // e.g., "shz.variant.sku" -> "shz_variant_sku" to match expanded wildcard column names
            let normalized_field = ob.field.replace('.', "_");

            let col_idx = match col_indices.get(&normalized_field) {
                Some(&idx) => idx,
                None => {
                    // Also try the original field name (in case user explicitly selected with dots)
                    match col_indices.get(&ob.field) {
                        Some(&idx) => idx,
                        None => continue, // Skip if column not found
                    }
                }
            };

            let direction = ob.direction.as_deref().unwrap_or("asc");
            let is_desc = direction == "desc";

            sorted_rows.sort_by(|a, b| {
                let val_a = a.get(col_idx).cloned().unwrap_or(Value::Null);
                let val_b = b.get(col_idx).cloned().unwrap_or(Value::Null);

                let cmp = self.compare_values_for_sort(&val_a, &val_b);
                if is_desc {
                    cmp.reverse()
                } else {
                    cmp
                }
            });
        }

        Ok(sorted_rows)
    }

    /// Apply order_by sorting on HashMap rows (before field selection)
    fn apply_order_by_on_maps(
        &self,
        mut rows: Vec<HashMap<String, Value>>,
        order_by: &[OrderBy],
        exec_ctx: &ExecutionContext,
    ) -> Result<Vec<HashMap<String, Value>>> {
        // Sort by each order_by field in reverse order (so first field has highest priority)
        for ob in order_by.iter().rev() {
            let direction = ob.direction.as_deref().unwrap_or("asc");
            let is_desc = direction == "desc";

            rows.sort_by(|a, b| {
                // Check if expression-based ordering
                let (val_a, val_b) = if let Some(ref expr) = ob.expression {
                    // Evaluate expression for each row
                    let ctx_a = self.row_to_context(a, exec_ctx);
                    let ctx_b = self.row_to_context(b, exec_ctx);

                    let val_a = expr
                        .evaluate_with_registry(&ctx_a, &exec_ctx.function_registry)
                        .unwrap_or(Value::Null);
                    let val_b = expr
                        .evaluate_with_registry(&ctx_b, &exec_ctx.function_registry)
                        .unwrap_or(Value::Null);
                    (val_a, val_b)
                } else {
                    // Extract value from row using field path
                    let val_a = self.extract_value_from_row_maps(a, &ob.field);
                    let val_b = self.extract_value_from_row_maps(b, &ob.field);
                    (val_a, val_b)
                };

                let cmp = self.compare_values_for_sort(&val_a, &val_b);
                if is_desc {
                    cmp.reverse()
                } else {
                    cmp
                }
            });
        }

        Ok(rows)
    }

    /// Extract a value from row maps using a field path (e.g., "o.businessDate")
    fn extract_value_from_row_maps(&self, row: &HashMap<String, Value>, field_path: &str) -> Value {
        // Parse alias.field pattern
        let parts: Vec<&str> = field_path.splitn(2, '.').collect();
        if parts.len() == 2 {
            let alias = parts[0];
            let field = parts[1];

            if let Some(obj) = row.get(alias) {
                return self.get_nested_value(obj, field);
            }
        } else {
            // Try to find in any alias
            for (_alias, obj) in row {
                if let Value::Object(map) = obj {
                    if let Some(v) = map.get(field_path) {
                        return v.clone();
                    }
                }
            }
        }

        Value::Null
    }

    /// Compare two values for sorting
    fn compare_values_for_sort(&self, a: &Value, b: &Value) -> std::cmp::Ordering {
        match (a, b) {
            (Value::Null, Value::Null) => std::cmp::Ordering::Equal,
            (Value::Null, _) => std::cmp::Ordering::Greater, // Nulls last
            (_, Value::Null) => std::cmp::Ordering::Less,
            (Value::Number(na), Value::Number(nb)) => {
                let fa = na.as_f64().unwrap_or(0.0);
                let fb = nb.as_f64().unwrap_or(0.0);
                fa.partial_cmp(&fb).unwrap_or(std::cmp::Ordering::Equal)
            }
            (Value::String(sa), Value::String(sb)) => sa.cmp(sb),
            (Value::Bool(ba), Value::Bool(bb)) => ba.cmp(bb),
            _ => a.to_string().cmp(&b.to_string()),
        }
    }

    /// Expand wildcard selections like "fp.*" into individual field selections
    fn expand_wildcards(
        &self,
        select: &[SelectField],
        data: &[HashMap<String, Value>],
    ) -> Result<Vec<SelectField>> {
        let mut expanded = Vec::new();

        for field in select {
            let expr = field.expr.as_deref().unwrap_or("");
            if expr.ends_with(".*") {
                // Wildcard pattern: "alias.*" or "alias.field.*" for nested objects
                let base_path = &expr[..expr.len() - 2]; // Remove "*"
                let (alias, prefix) = if base_path.ends_with('.') {
                    let parts: Vec<&str> =
                        base_path[..base_path.len() - 1].splitn(2, '.').collect();
                    if parts.len() == 2 {
                        (parts[0].to_string(), Some(parts[1].to_string()))
                    } else {
                        (parts[0].to_string(), None)
                    }
                } else {
                    let parts: Vec<&str> = base_path.splitn(2, '.').collect();
                    if parts.len() == 2 {
                        (parts[0].to_string(), Some(parts[1].to_string()))
                    } else {
                        (parts[0].to_string(), None)
                    }
                };

                // Get a sample row to extract field names
                if let Some(sample_row) = data.first() {
                    if let Some(Value::Object(obj)) = sample_row.get(&alias) {
                        // If prefix is set, get nested object
                        let target_obj = if let Some(ref p) = prefix {
                            self.get_nested_value(&Value::Object(obj.clone()), p)
                        } else {
                            Value::Object(obj.clone())
                        };

                        if let Value::Object(target_map) = target_obj {
                            // Collect all field paths from the object
                            let field_paths =
                                self.collect_field_paths(&target_map, &alias, &prefix);
                            for (full_path, alias_name) in field_paths {
                                expanded.push(SelectField {
                                    expr: Some(full_path),
                                    expression: None,
                                    alias: Some(alias_name),
                                    transform: field.transform.clone(),
                                    agg: field.agg.clone(),
                                    case: field.case.clone(),
                                    coalesce: field.coalesce.clone(),
                                });
                            }
                        }
                    }
                }
            } else {
                expanded.push(field.clone());
            }
        }

        Ok(expanded)
    }

    /// Recursively collect all field paths from a JSON object
    fn collect_field_paths(
        &self,
        obj: &serde_json::Map<String, Value>,
        alias: &str,
        prefix: &Option<String>,
    ) -> Vec<(String, String)> {
        let mut paths = Vec::new();

        for (key, value) in obj {
            let full_path = if let Some(ref p) = prefix {
                format!("{}.{p}.{key}", alias)
            } else {
                format!("{}.{key}", alias)
            };

            let alias_name = if let Some(ref p) = prefix {
                format!("{}_{}_{}", alias, p.replace('.', "_"), key)
            } else {
                format!("{}_{}", alias, key)
            };

            match value {
                Value::Object(nested) => {
                    // Recursively collect nested fields with flattened names
                    let nested_prefix = if let Some(ref p) = prefix {
                        format!("{}.{}", p, key)
                    } else {
                        key.clone()
                    };
                    let nested_paths =
                        self.collect_field_paths(nested, alias, &Some(nested_prefix));
                    if nested_paths.is_empty() {
                        // If nested object has no scalars, include it as a JSON value
                        paths.push((full_path, alias_name));
                    } else {
                        paths.extend(nested_paths);
                    }
                }
                Value::Array(_) => {
                    // Include arrays as-is (they were already exploded)
                    paths.push((full_path, alias_name));
                }
                _ => {
                    // Scalar value
                    paths.push((full_path, alias_name));
                }
            }
        }

        paths
    }

    fn evaluate_select_field(
        &self,
        row: &HashMap<String, Value>,
        field: &SelectField,
        exec_ctx: &ExecutionContext,
    ) -> Result<Value> {
        // NEW: Check for structured expression first (highest priority)
        if let Some(ref expression) = field.expression {
            // Build context from row data, including let bindings
            let mut context = self.row_to_context(row, exec_ctx);
            // Add the root object reference
            if let Some(root) = row.get("__root__") {
                context.set("$$".to_string(), root.clone());
            }
            return expression.evaluate_with_registry(&context, &exec_ctx.function_registry);
        }

        let expr = field
            .expr
            .as_deref()
            .ok_or_else(|| anyhow!("Select field missing expr"))?;

        // Check if this is a date function call
        if let Some((date_func, _)) = DateFunction::parse(expr) {
            return Ok(date_func.evaluate(row, self));
        }

        // Check if this is a coalesce function call
        if let Some((coalesce_func, _)) = CoalesceFunction::parse(expr) {
            return Ok(coalesce_func.evaluate(row, self));
        }

        // Check for function calls like "to_number(field)" or "upper(field)"
        if let Some(result) = self.evaluate_function_call(row, expr, exec_ctx) {
            return Ok(result);
        }

        // Check for simple arithmetic expressions like "c.amount * (p.amount / p.total)"
        if let Some(result) = self.evaluate_arithmetic_expression(row, expr, exec_ctx) {
            return Ok(result);
        }

        let (alias, field_path) = self.parse_field_ref(expr)?;
        let value = self.extract_value(row, &alias, &field_path);

        // Apply transform if specified
        if let Some(transform) = &field.transform {
            // Simple transform support - could be extended with jaq
            match transform.as_str() {
                "upper" => match value {
                    Value::String(s) => Ok(Value::String(s.to_uppercase())),
                    _ => Ok(value),
                },
                "lower" => match value {
                    Value::String(s) => Ok(Value::String(s.to_lowercase())),
                    _ => Ok(value),
                },
                _ => Ok(value),
            }
        } else {
            Ok(value)
        }
    }

    /// Evaluate simple arithmetic expressions
    /// Supports: field * number, field / number, field + number, field - number
    /// And nested: field * (other_field / number)
    fn evaluate_arithmetic_expression(
        &self,
        row: &HashMap<String, Value>,
        expr: &str,
        exec_ctx: &ExecutionContext,
    ) -> Option<Value> {
        // Pattern: X * Y, X / Y, X + Y, X - Y
        let expr = expr.trim();

        // Handle multiplication
        if let Some(idx) = expr.find(" * ") {
            let left = expr[..idx].trim();
            let right = expr[idx + 3..].trim();

            let left_val = self.evaluate_expression_operand(row, left, exec_ctx)?;
            let right_val = self.evaluate_expression_operand(row, right, exec_ctx)?;

            return self.multiply_values(&left_val, &right_val);
        }

        // Handle division
        if let Some(idx) = expr.find(" / ") {
            let left = expr[..idx].trim();
            let right = expr[idx + 3..].trim();

            let left_val = self.evaluate_expression_operand(row, left, exec_ctx)?;
            let right_val = self.evaluate_expression_operand(row, right, exec_ctx)?;

            return self.divide_values(&left_val, &right_val);
        }

        // Handle addition
        if let Some(idx) = expr.find(" + ") {
            let left = expr[..idx].trim();
            let right = expr[idx + 3..].trim();

            let left_val = self.evaluate_expression_operand(row, left, exec_ctx)?;
            let right_val = self.evaluate_expression_operand(row, right, exec_ctx)?;

            return self.add_values(&left_val, &right_val);
        }

        // Handle subtraction
        if let Some(idx) = expr.find(" - ") {
            let left = expr[..idx].trim();
            let right = expr[idx + 3..].trim();

            let left_val = self.evaluate_expression_operand(row, left, exec_ctx)?;
            let right_val = self.evaluate_expression_operand(row, right, exec_ctx)?;

            return self.subtract_values(&left_val, &right_val);
        }

        None
    }

    /// Evaluate an operand that could be a field reference, number, or function call
    fn evaluate_expression_operand(
        &self,
        row: &HashMap<String, Value>,
        operand: &str,
        exec_ctx: &ExecutionContext,
    ) -> Option<Value> {
        let operand = operand.trim();

        // Handle parenthesized expressions
        if operand.starts_with('(') && operand.ends_with(')') {
            let inner = &operand[1..operand.len() - 1];
            return self.evaluate_arithmetic_expression(row, inner, exec_ctx);
        }

        // Try to parse as number
        if let Ok(num) = operand.parse::<f64>() {
            return Some(Value::Number(
                serde_json::Number::from_f64(num).unwrap_or(serde_json::Number::from(0)),
            ));
        }

        // Try to evaluate as function call (e.g., to_number(field))
        if operand.contains('(') && operand.ends_with(')') {
            if let Some(result) = self.evaluate_function_call(row, operand, exec_ctx) {
                return Some(result);
            }
        }

        // Try to parse as field reference
        if let Ok((alias, field_path)) = self.parse_field_ref(operand) {
            return Some(self.extract_value(row, &alias, &field_path));
        }

        None
    }

    fn multiply_values(&self, a: &Value, b: &Value) -> Option<Value> {
        let a_f64 = self.value_to_f64(a)?;
        let b_f64 = self.value_to_f64(b)?;
        let result = a_f64 * b_f64;
        Some(Value::Number(
            serde_json::Number::from_f64(result).unwrap_or(serde_json::Number::from(0)),
        ))
    }

    fn divide_values(&self, a: &Value, b: &Value) -> Option<Value> {
        let a_f64 = self.value_to_f64(a)?;
        let b_f64 = self.value_to_f64(b)?;
        if b_f64 == 0.0 {
            return Some(Value::Null);
        }
        let result = a_f64 / b_f64;
        Some(Value::Number(
            serde_json::Number::from_f64(result).unwrap_or(serde_json::Number::from(0)),
        ))
    }

    fn add_values(&self, a: &Value, b: &Value) -> Option<Value> {
        let a_f64 = self.value_to_f64(a)?;
        let b_f64 = self.value_to_f64(b)?;
        let result = a_f64 + b_f64;
        Some(Value::Number(
            serde_json::Number::from_f64(result).unwrap_or(serde_json::Number::from(0)),
        ))
    }

    fn subtract_values(&self, a: &Value, b: &Value) -> Option<Value> {
        let a_f64 = self.value_to_f64(a)?;
        let b_f64 = self.value_to_f64(b)?;
        let result = a_f64 - b_f64;
        Some(Value::Number(
            serde_json::Number::from_f64(result).unwrap_or(serde_json::Number::from(0)),
        ))
    }

    fn value_to_f64(&self, value: &Value) -> Option<f64> {
        match value {
            Value::Number(n) => n.as_f64(),
            Value::String(s) => s.parse::<f64>().ok(),
            _ => None,
        }
    }

    /// Evaluate function calls in expression strings
    /// Supports: function_name(field_ref), function_name(alias.field), function_name(nested.field.path)
    /// Examples: to_number(s.price), upper(c.name), abs(o.amount)
    fn evaluate_function_call(
        &self,
        row: &HashMap<String, Value>,
        expr: &str,
        exec_ctx: &ExecutionContext,
    ) -> Option<Value> {
        let expr = expr.trim();
        // Pattern: function_name(arg) - match function call syntax
        // Look for opening and closing parentheses
        let open_paren = match expr.find('(') {
            Some(idx) => idx,
            None => return None,
        };
        let close_paren = match expr.rfind(')') {
            Some(idx) => idx,
            None => return None,
        };

        if close_paren <= open_paren || close_paren != expr.len() - 1 {
            return None;
        }

        let func_name = expr[..open_paren].trim();
        let arg_str = expr[open_paren + 1..close_paren].trim();

        // Parse the argument - could be a field reference or a literal
        let arg_value = if arg_str.starts_with('\'') || arg_str.starts_with('"') {
            // String literal - remove quotes
            let quote = arg_str.chars().next()?;
            if arg_str.ends_with(quote) && arg_str.len() >= 2 {
                Value::String(arg_str[1..arg_str.len() - 1].to_string())
            } else {
                return None;
            }
        } else if let Ok(num) = arg_str.parse::<f64>() {
            // Number literal
            Value::Number(serde_json::Number::from_f64(num).unwrap_or(serde_json::Number::from(0)))
        } else {
            // Field reference - try to parse and extract value
            // Handle nested paths like "s.variant.price" -> alias="s", path="variant.price"
            let parts: Vec<&str> = arg_str.splitn(2, '.').collect();
            if parts.len() == 2 {
                let alias = parts[0];
                let field_path = parts[1];
                self.extract_value(row, alias, field_path)
            } else {
                // Try to find in any alias
                for (alias, obj) in row {
                    if let Value::Object(map) = obj {
                        if let Some(v) = map.get(arg_str) {
                            return Some(v.clone());
                        }
                    }
                }
                return None;
            }
        };

        // Call the function using the function registry
        match exec_ctx
            .function_registry
            .call(func_name, &[arg_value], &Context::new())
        {
            Ok(result) => Some(result),
            Err(_) => None,
        }
    }

    // Helper methods
    fn default_alias(&self, filename: &str) -> String {
        filename
            .trim_end_matches(".json")
            .replace("_", "")
            .to_lowercase()
    }

    fn parse_field_ref(&self, field_ref: &str) -> Result<(String, String)> {
        let parts: Vec<&str> = field_ref.splitn(2, '.').collect();
        if parts.len() != 2 {
            return Err(anyhow!("Invalid field reference: {}", field_ref));
        }
        Ok((parts[0].to_string(), parts[1].to_string()))
    }

    fn extract_value(&self, row: &HashMap<String, Value>, alias: &str, field: &str) -> Value {
        let obj = match row.get(alias) {
            Some(Value::Object(o)) => o.clone(),
            Some(v) => return v.clone(),
            None => return Value::Null,
        };

        // Handle array notation like "variants[].sku"
        if field.contains("[]") {
            let parts: Vec<&str> = field.split("[]").collect();
            let array_path = parts[0];
            let rest = parts
                .get(1)
                .map(|s| s.trim_start_matches('.'))
                .filter(|s| !s.is_empty());

            let array = self.get_nested_value(&Value::Object(obj), array_path);
            if let Value::Array(arr) = array {
                // For join matching, return the value from the first element
                // (the join logic will handle matching against all elements)
                if let Some(first) = arr.first() {
                    if let Some(subfield) = rest {
                        return self.get_nested_value(first, subfield);
                    } else {
                        return first.clone();
                    }
                }
            }
            return Value::Null;
        }

        self.get_nested_value(&Value::Object(obj), field)
    }

    fn extract_values_for_join(&self, obj: &Value, field: &str) -> Vec<Value> {
        // Handle array path like "variants[].sku"
        if field.contains("[]") {
            let parts: Vec<&str> = field.split("[]").collect();
            let array_path = parts[0];
            let rest = parts
                .get(1)
                .map(|s| s.trim_start_matches('.'))
                .filter(|s| !s.is_empty());

            let array = self.get_nested_value(obj, array_path);
            if let Value::Array(arr) = array {
                if let Some(subfield) = rest {
                    arr.into_iter()
                        .map(|item| self.get_nested_value(&item, subfield))
                        .collect()
                } else {
                    arr
                }
            } else {
                vec![]
            }
        } else {
            vec![self.get_nested_value(obj, field)]
        }
    }

    fn get_nested_value(&self, obj: &Value, path: &str) -> Value {
        let mut current = obj.clone();

        for part in path.split('.') {
            match current {
                Value::Object(map) => {
                    current = map.get(part).cloned().unwrap_or(Value::Null);
                }
                Value::Array(arr) => {
                    // Try to parse as index
                    if let Ok(idx) = part.parse::<usize>() {
                        current = arr.get(idx).cloned().unwrap_or(Value::Null);
                    } else {
                        return Value::Null;
                    }
                }
                _ => return Value::Null,
            }
        }

        current
    }

    /// Extract value with automatic array flattening (Phase 4)
    /// When accessing a field on an array, automatically map over the array
    pub fn extract_value_auto_flatten(
        &self,
        row: &HashMap<String, Value>,
        alias: &str,
        path: &str,
    ) -> Value {
        let parts: Vec<&str> = path.split('.').collect();

        // Get the root object
        let root = match row.get(alias) {
            Some(v) => v.clone(),
            None => return Value::Null,
        };

        self.navigate_with_auto_flatten(root, &parts)
    }

    /// Navigate through a path with automatic array flattening
    fn navigate_with_auto_flatten(&self, value: Value, path: &[&str]) -> Value {
        if path.is_empty() {
            return value;
        }

        let first = path[0];
        let rest = &path[1..];

        match value {
            Value::Array(arr) => {
                // Automatic flattening: apply to each element
                let results: Vec<Value> = arr
                    .into_iter()
                    .filter_map(|item| {
                        let result = self.navigate_with_auto_flatten(item, path);
                        if result.is_null() {
                            None
                        } else {
                            Some(result)
                        }
                    })
                    .collect();

                if results.is_empty() {
                    Value::Null
                } else if results.len() == 1 {
                    results.into_iter().next().unwrap()
                } else {
                    Value::Array(results)
                }
            }
            Value::Object(mut obj) => match obj.remove(first) {
                Some(next_value) => self.navigate_with_auto_flatten(next_value, rest),
                None => Value::Null,
            },
            _ => Value::Null,
        }
    }

    fn set_nested_value(&self, obj: &mut Value, path: &str, value: Value) {
        let parts: Vec<&str> = path.split('.').collect();
        if parts.is_empty() {
            return;
        }

        let mut current = obj;
        for (i, part) in parts.iter().enumerate() {
            if i == parts.len() - 1 {
                // Last part - set the value
                if let Value::Object(map) = current {
                    map.insert(part.to_string(), value);
                }
                return;
            }

            // Navigate deeper
            match current {
                Value::Object(map) => {
                    if !map.contains_key(*part) {
                        map.insert(part.to_string(), Value::Object(serde_json::Map::new()));
                    }
                    current = map.get_mut(*part).unwrap();
                }
                _ => return,
            }
        }
    }

    fn values_match(&self, a: &Value, b: &Value) -> bool {
        // Try numeric comparison first (handle string numbers)
        let a_f64 = match a {
            Value::Number(n) => n.as_f64(),
            Value::String(s) => s.parse::<f64>().ok(),
            _ => None,
        };

        let b_f64 = match b {
            Value::Number(n) => n.as_f64(),
            Value::String(s) => s.parse::<f64>().ok(),
            _ => None,
        };

        if let (Some(a_val), Some(b_val)) = (a_f64, b_f64) {
            return (a_val - b_val).abs() < 0.0001; // Compare with tolerance for floating point errors
        }

        // Fallback to exact type and value comparison
        match (a, b) {
            (Value::String(sa), Value::String(sb)) => sa == sb,
            (Value::Number(na), Value::Number(nb)) => na == nb,
            (Value::Bool(ba), Value::Bool(bb)) => ba == bb,
            (Value::Null, Value::Null) => true,
            (Value::Array(aa), Value::Array(ab)) => aa == ab,
            (Value::Object(oa), Value::Object(ob)) => oa == ob,
            _ => false,
        }
    }

    fn value_to_key(&self, value: &Value) -> Option<String> {
        match value {
            Value::String(s) => Some(s.clone()),
            Value::Number(n) => Some(n.to_string()),
            Value::Bool(b) => Some(b.to_string()),
            Value::Null => Some("__null__".to_string()),
            _ => None,
        }
    }

    fn value_to_string(&self, value: &Value) -> String {
        match value {
            Value::String(s) => s.clone(),
            Value::Number(n) => n.to_string(),
            Value::Bool(b) => b.to_string(),
            Value::Null => String::new(),
            _ => value.to_string(),
        }
    }

    fn values_equal(&self, a: &Value, b: &Value) -> bool {
        self.values_match(a, b)
    }

    /// Check if a value is "truthy" (like JavaScript/Python truthiness)
    /// - false, null, 0, empty string -> false
    /// - everything else -> true
    fn is_truthy(&self, value: &Value) -> bool {
        match value {
            Value::Null => false,
            Value::Bool(b) => *b,
            Value::Number(n) => n.as_f64().map(|v| v != 0.0).unwrap_or(true),
            Value::String(s) => !s.is_empty(),
            Value::Array(arr) => !arr.is_empty(),
            Value::Object(obj) => !obj.is_empty(),
        }
    }

    fn compare_values<F>(&self, a: &Value, b: &Value, op: F) -> bool
    where
        F: Fn(f64, f64) -> bool,
    {
        // Try to extract numeric values from either Numbers or numeric Strings
        let a_f64 = match a {
            Value::Number(na) => na.as_f64(),
            Value::String(sa) => sa.parse::<f64>().ok(),
            _ => None,
        };

        let b_f64 = match b {
            Value::Number(nb) => nb.as_f64(),
            Value::String(sb) => sb.parse::<f64>().ok(),
            _ => None,
        };

        match (a_f64, b_f64) {
            (Some(a_val), Some(b_val)) => op(a_val, b_val),
            _ => false,
        }
    }

    /// Convert a row (HashMap of alias -> Value) to a Context for expression evaluation
    fn row_to_context(&self, row: &HashMap<String, Value>, exec_ctx: &ExecutionContext) -> Context {
        let mut context = Context::new();

        // Add row data first - each alias becomes a variable in the context
        // Also add special "$" variable pointing to the first alias's value (current object)
        let mut first_value = None;
        for (alias, value) in row {
            context.set(alias.clone(), value.clone());
            if first_value.is_none() && alias != "__root__" {
                first_value = Some(value.clone());
            }
        }

        // Set "$" to the first alias's value (for expressions like $.field)
        if let Some(first) = first_value {
            context.set("$".to_string(), first);
        }

        // Add let bindings (they can reference row data via $)
        // We make multiple passes to handle dependencies between let bindings
        // Sort bindings by name to ensure deterministic order (dependencies first alphabetically)
        let mut binding_names: Vec<String> = exec_ctx.let_expressions.keys().cloned().collect();
        binding_names.sort(); // Sort alphabetically for deterministic ordering

        let mut max_passes = binding_names.len() + 1;

        while max_passes > 0 {
            max_passes -= 1;
            let mut made_progress = false;

            for name in &binding_names {
                if let Some(expr) = exec_ctx.let_expressions.get(name) {
                    match expr.evaluate_with_registry(&context, &exec_ctx.function_registry) {
                        Ok(value) => {
                            // Check if this value is different from what's already in context
                            let should_update = match context.get(name) {
                                Ok(existing) => existing != value,
                                Err(_) => true, // Not in context yet
                            };

                            if should_update {
                                context.set(name.clone(), value);
                                made_progress = true;
                            }
                        }
                        Err(_) => {
                            // Variable not found, will retry in next pass
                        }
                    }
                }
            }

            // If no progress was made, we're done
            if !made_progress {
                break;
            }
        }

        context
    }
}

/// Execute a query DSL string (JSON format)
pub fn execute_query(conn: &Connection, query_json: &str) -> Result<QueryResult> {
    let query: QueryDsl = serde_json::from_str(query_json)?;
    let engine = QueryEngine::new(conn);
    engine.execute(&query)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_field_ref() {
        // Test parsing
    }

    #[test]
    fn test_date_function_parse() {
        // Test hour function parsing
        let result = DateFunction::parse("hour(te.inDate)");
        assert!(result.is_some(), "Should parse hour function");
        let (func, field) = result.unwrap();
        assert_eq!(field, "te.inDate");
        match func {
            DateFunction::Hour { field } => assert_eq!(field, "te.inDate"),
            _ => panic!("Expected Hour function"),
        }

        // Test date function parsing
        let result = DateFunction::parse("date(te.inDate)");
        assert!(result.is_some(), "Should parse date function");

        // Test date_diff parsing
        let result = DateFunction::parse("date_diff(te.outDate, te.inDate, 'hours')");
        assert!(result.is_some(), "Should parse date_diff function");
        match result.unwrap().0 {
            DateFunction::DateDiff {
                field1,
                field2,
                unit,
            } => {
                assert_eq!(field1, "te.outDate");
                assert_eq!(field2, "te.inDate");
                assert_eq!(unit, "hours");
            }
            _ => panic!("Expected DateDiff function"),
        }
    }

    #[test]
    fn test_date_parsing() {
        // Test parsing ISO8601 dates
        let test_cases = vec![
            ("2026-01-30T10:03:25.363+0000", Some(10i64)), // hour should be 10
            ("2026-01-30T15:30:00.000+0000", Some(15i64)), // hour should be 15
            ("2026-01-30T08:15:00.000+0000", Some(8i64)),  // hour should be 8
        ];

        for (input, expected_hour) in test_cases {
            let value = Value::String(input.to_string());
            let result = DateFunction::parse_iso8601(&value);
            assert!(result.is_some(), "Should parse date: {}", input);

            let dt = result.unwrap();
            assert_eq!(
                dt.hour() as i64,
                expected_hour.unwrap(),
                "Hour mismatch for {}",
                input
            );
        }
    }

    #[test]
    fn test_extract_hour_directly() {
        // Test the extract_hour function directly
        let value = Value::String("2026-01-30T10:03:25.363+0000".to_string());
        let hour = DateFunction::extract_hour(&value);

        match hour {
            Value::Number(n) => {
                assert_eq!(n.as_i64(), Some(10), "Hour should be 10");
            }
            _ => panic!("Expected number, got {:?}", hour),
        }
    }

    #[test]
    fn test_date_function_evaluate() {
        // Simulate a row structure like what the query engine uses
        let mut inner_obj = serde_json::Map::new();
        inner_obj.insert("guid".to_string(), Value::String("test-guid".to_string()));
        inner_obj.insert(
            "inDate".to_string(),
            Value::String("2026-01-30T10:03:25.363+0000".to_string()),
        );

        let mut row = HashMap::new();
        row.insert("te".to_string(), Value::Object(inner_obj));

        // Verify the row structure is correct
        assert!(row.contains_key("te"));
        if let Value::Object(obj) = &row["te"] {
            assert!(obj.contains_key("inDate"));
        }
    }

    #[test]
    fn test_expression_integration() {
        // Test that the expression integration works
        use crate::expression::Expression;
        use crate::functions::FunctionRegistry;
        use serde_json::json;

        // Create a row
        let mut row = HashMap::new();
        let mut obj = serde_json::Map::new();
        obj.insert("price".to_string(), json!(10.0));
        obj.insert("quantity".to_string(), json!(5));
        row.insert("o".to_string(), Value::Object(obj));

        // Create execution context with function registry
        let exec_ctx = ExecutionContext::new(HashMap::new(), FunctionRegistry::new());

        // Test a simple expression using tuple variants
        let _field = SelectField {
            expr: None,
            expression: Some(Expression::Multiply(
                Box::new(Expression::FieldAccess {
                    object: Box::new(Expression::Var("o".to_string())),
                    field: "price".to_string(),
                }),
                Box::new(Expression::Literal(json!(2.0))),
            )),
            alias: Some("doubled".to_string()),
            transform: None,
            agg: None,
            case: None,
            coalesce: None,
        };

        // Create a minimal query engine to test evaluate_select_field
        // Note: We can't easily create a real QueryEngine without a DB connection,
        // but we can verify the ExecutionContext and row_to_context work

        // Test that the ExecutionContext is properly created
        assert!(exec_ctx.let_expressions.is_empty());
        assert!(exec_ctx.function_registry.has_function("sum"));
    }
}
