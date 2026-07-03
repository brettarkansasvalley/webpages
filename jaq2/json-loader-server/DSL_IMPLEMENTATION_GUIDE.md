# DSL Extension Implementation Guide

## Phase 1: Primitive Values and Date Functions

This guide provides step-by-step implementation instructions for the first phase of DSL extensions.

---

## Part A: Primitive Value Records

### Problem Statement

Some JSON files in the datalake contain primitive values instead of objects:

```bash
sqlite3 database.db "SELECT json_data FROM json_objects WHERE source_file='orders_v2_orders_20260130.json' LIMIT 3"
```

Output:
```
"c4932a6c-acb6-4869-ac9f-0de76b837778"
"090b07d9-d145-4ff0-a8a4-3fc661a71679"
"e334f0bd-02f9-4e66-b04c-f2b13a6c4e0d"
```

The current DSL expects objects with fields like `{"guid": "...", "name": "..."}`.

### Solution

Add `as_primitive` option to `Source` that wraps primitive values in an object.

### Implementation Steps

#### Step 1: Modify `Source` struct in `query_engine.rs`

```rust
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct Source {
    pub source_file: String,
    #[serde(default)]
    pub alias: Option<String>,
    /// Optional array field to explode before joining
    #[serde(default)]
    pub explode: Option<String>,
    /// Treat primitive values as objects with a single field
    #[serde(default)]
    pub as_primitive: Option<String>, // column name for the primitive value
}
```

#### Step 2: Modify `load_source` method

```rust
fn load_source(&self, source: &Source) -> Result<Vec<Value>> {
    let source_file = &source.source_file;
    let mut stmt = self.conn.prepare(
        "SELECT json_data FROM json_objects WHERE source_file = ?1"
    )?;
    
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
        result = result.into_iter()
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
        _ => value
    }
}
```

#### Step 3: Update `execute_with_context` to use new `load_source` signature

Change:
```rust
let data = self.load_source(&from.source_file)?;
```

To:
```rust
let data = self.load_source(&from)?;
```

And update the join source loading similarly.

### Usage Example

```json
{
  "from": {
    "source_file": "orders_v2_orders_20260130.json",
    "alias": "o",
    "as_primitive": "guid"
  },
  "select": [
    {"expr": "o.guid", "alias": "order_guid"}
  ]
}
```

---

## Part B: Date/Time Functions

### Problem Statement

The `hourly_sales_daily.csv` report requires extracting the hour from datetime strings:

```python
closed = _parse_iso(check.get("closedDate"))
hour = closed.hour  # Need this in DSL
```

### Solution

Add date/time function evaluation to expression parsing.

### Implementation Steps

#### Step 1: Add DateFunction enum

```rust
#[derive(Debug, Clone)]
pub enum DateFunction {
    Hour { field: String },
    Date { field: String },
    DateTime { field: String },
    Minute { field: String },
    DayOfWeek { field: String },
    DayOfMonth { field: String },
    Month { field: String },
    Year { field: String },
    DateDiff { field1: String, field2: String, unit: String },
}

impl DateFunction {
    /// Parse a function call like "hour(o.closedDate)"
    fn parse(expr: &str) -> Option<(Self, String)> {
        // Match pattern like "function(field)" or "function(alias.field)"
        let expr = expr.trim();
        
        if let Some(caps) = regex::Regex::new(r"^(\w+)\s*\(\s*([^)]+)\s*\)$").unwrap().captures(expr) {
            let func_name = caps.get(1)?.as_str().to_lowercase();
            let field = caps.get(2)?.as_str().trim().to_string();
            
            let func = match func_name.as_str() {
                "hour" => DateFunction::Hour { field: field.clone() },
                "date" => DateFunction::Date { field: field.clone() },
                "datetime" => DateFunction::DateTime { field: field.clone() },
                "minute" => DateFunction::Minute { field: field.clone() },
                "dayofweek" | "day_of_week" => DateFunction::DayOfWeek { field: field.clone() },
                "dayofmonth" | "day_of_month" => DateFunction::DayOfMonth { field: field.clone() },
                "month" => DateFunction::Month { field: field.clone() },
                "year" => DateFunction::Year { field: field.clone() },
                "datediff" | "date_diff" => {
                    // Parse date_diff(field1, field2, 'unit')
                    let parts: Vec<&str> = field.split(',').collect();
                    if parts.len() >= 2 {
                        DateFunction::DateDiff {
                            field1: parts[0].trim().to_string(),
                            field2: parts[1].trim().to_string(),
                            unit: parts.get(2).map(|s| s.trim().trim_matches('\'').trim_matches('"').to_string())
                                .unwrap_or_else(|| "hours".to_string()),
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
    
    /// Evaluate the function against a row
    fn evaluate(&self, row: &HashMap<String, Value>, engine: &QueryEngine) -> Value {
        match self {
            DateFunction::Hour { field } => {
                let value = engine.extract_value_by_path(row, field);
                Self::extract_hour(&value)
            }
            DateFunction::Date { field } => {
                let value = engine.extract_value_by_path(row, field);
                Self::extract_date(&value)
            }
            DateFunction::DateTime { field } => {
                let value = engine.extract_value_by_path(row, field);
                Self::parse_datetime(&value)
            }
            DateFunction::Minute { field } => {
                let value = engine.extract_value_by_path(row, field);
                Self::extract_minute(&value)
            }
            DateFunction::DayOfWeek { field } => {
                let value = engine.extract_value_by_path(row, field);
                Self::extract_day_of_week(&value)
            }
            DateFunction::DayOfMonth { field } => {
                let value = engine.extract_value_by_path(row, field);
                Self::extract_day_of_month(&value)
            }
            DateFunction::Month { field } => {
                let value = engine.extract_value_by_path(row, field);
                Self::extract_month(&value)
            }
            DateFunction::Year { field } => {
                let value = engine.extract_value_by_path(row, field);
                Self::extract_year(&value)
            }
            DateFunction::DateDiff { field1, field2, unit } => {
                let v1 = engine.extract_value_by_path(row, field1);
                let v2 = engine.extract_value_by_path(row, field2);
                Self::calculate_date_diff(&v1, &v2, unit)
            }
        }
    }
    
    // Helper functions for date parsing
    fn parse_iso8601(value: &Value) -> Option<chrono::DateTime<chrono::Utc>> {
        match value {
            Value::String(s) => {
                // Try various ISO8601 formats
                let s = s.trim();
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
                
                // Try chrono's built-in parser as fallback
                if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(s) {
                    return Some(dt.with_timezone(&chrono::Utc));
                }
                
                None
            }
            _ => None
        }
    }
    
    fn extract_hour(value: &Value) -> Value {
        match Self::parse_iso8601(value) {
            Some(dt) => Value::Number(serde_json::Number::from(dt.hour() as i64)),
            None => Value::Null
        }
    }
    
    fn extract_date(value: &Value) -> Value {
        match Self::parse_iso8601(value) {
            Some(dt) => Value::String(dt.format("%Y-%m-%d").to_string()),
            None => Value::Null
        }
    }
    
    fn parse_datetime(value: &Value) -> Value {
        match Self::parse_iso8601(value) {
            Some(dt) => Value::String(dt.to_rfc3339()),
            None => Value::Null
        }
    }
    
    fn extract_minute(value: &Value) -> Value {
        match Self::parse_iso8601(value) {
            Some(dt) => Value::Number(serde_json::Number::from(dt.minute() as i64)),
            None => Value::Null
        }
    }
    
    fn extract_day_of_week(value: &Value) -> Value {
        match Self::parse_iso8601(value) {
            Some(dt) => Value::Number(serde_json::Number::from(dt.weekday().num_days_from_sunday() as i64)),
            None => Value::Null
        }
    }
    
    fn extract_day_of_month(value: &Value) -> Value {
        match Self::parse_iso8601(value) {
            Some(dt) => Value::Number(serde_json::Number::from(dt.day() as i64)),
            None => Value::Null
        }
    }
    
    fn extract_month(value: &Value) -> Value {
        match Self::parse_iso8601(value) {
            Some(dt) => Value::Number(serde_json::Number::from(dt.month() as i64)),
            None => Value::Null
        }
    }
    
    fn extract_year(value: &Value) -> Value {
        match Self::parse_iso8601(value) {
            Some(dt) => Value::Number(serde_json::Number::from(dt.year() as i64)),
            None => Value::Null
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
            _ => Value::Null
        }
    }
}
```

#### Step 2: Add helper method to QueryEngine

```rust
/// Extract value by path (e.g., "o.closedDate" or just "closedDate")
fn extract_value_by_path(&self, row: &HashMap<String, Value>, path: &str) -> Value {
    // Parse alias.field pattern
    let parts: Vec<&str> = path.splitn(2, '.').collect();
    if parts.len() == 2 {
        let alias = parts[0];
        let field = parts[1];
        self.extract_value(row, alias, field)
    } else {
        // Try to find in any alias
        for (alias, obj) in row {
            if let Value::Object(map) = obj {
                if let Some(v) = map.get(path) {
                    return v.clone();
                }
            }
        }
        Value::Null
    }
}
```

#### Step 3: Modify `evaluate_select_field` to handle date functions

```rust
fn evaluate_select_field(&self, row: &HashMap<String, Value>, field: &SelectField) -> Result<Value> {
    let expr = field.expr.as_deref().ok_or_else(|| anyhow!("Select field missing expr"))?;
    
    // Check if this is a date function call
    if let Some((date_func, _)) = DateFunction::parse(expr) {
        return Ok(date_func.evaluate(row, self));
    }
    
    // Check if this is an aggregation function
    if let Some(result) = self.try_evaluate_aggregate(row, expr) {
        return Ok(result);
    }
    
    // Regular field extraction
    let (alias, field_path) = self.parse_field_ref(expr)?;
    let value = self.extract_value(row, &alias, &field_path);
    
    // Apply transform if specified
    if let Some(transform) = &field.transform {
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
```

#### Step 4: Modify `apply_group_by` to support expressions in group_by

Change `GroupBy` struct:

```rust
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct GroupBy {
    /// Field to group by (e.g., "primary.category")
    /// OR expression (e.g., "hour(o.closedDate)")
    pub field: String,
    /// Optional alias for the group column
    #[serde(default)]
    pub alias: Option<String>,
    /// Whether field is an expression that needs evaluation
    #[serde(default)]
    pub is_expr: Option<bool>,
}
```

Update group_by evaluation:

```rust
fn apply_group_by(
    &self,
    data: Vec<HashMap<String, Value>>,
    group_by: &[GroupBy],
    select: &[SelectField],
    having: Option<&Vec<Condition>>,
    having_op: &str,
    _limit: Option<usize>,
) -> Result<(Vec<String>, Vec<Vec<Value>>)> {
    // Step 1: Group the data by the group_by fields
    let mut groups: HashMap<String, Vec<HashMap<String, Value>>> = HashMap::new();
    
    for row in data {
        // Build group key from group_by fields
        let mut group_key_parts = Vec::new();
        for gb in group_by {
            let value = if gb.is_expr == Some(true) || DateFunction::parse(&gb.field).is_some() {
                // Evaluate as expression
                if let Some((date_func, _)) = DateFunction::parse(&gb.field) {
                    date_func.evaluate(&row, self)
                } else {
                    // Try simple field extraction
                    let (alias, field) = self.parse_field_ref(&gb.field)?;
                    self.extract_value(&row, &alias, &field)
                }
            } else {
                // Regular field reference
                let (alias, field) = self.parse_field_ref(&gb.field)?;
                self.extract_value(&row, &alias, &field)
            };
            group_key_parts.push(value.to_string());
        }
        let group_key = group_key_parts.join("|");
        
        groups.entry(group_key).or_default().push(row);
    }
    
    // ... rest of the method
}
```

### Usage Examples

#### Hourly aggregation:
```json
{
  "from": {
    "source_file": "orders.json",
    "alias": "o",
    "explode": "checks"
  },
  "group_by": [
    {"field": "hour(c.closedDate)", "alias": "hour_of_day", "is_expr": true}
  ],
  "select": [
    {"expr": "hour(c.closedDate)", "alias": "hour"},
    {"expr": "sum(c.amount)", "alias": "net_sales"}
  ]
}
```

#### Date extraction:
```json
{
  "from": {
    "source_file": "labor_v1_timeEntries_20260130.json",
    "alias": "te"
  },
  "select": [
    {"expr": "date(te.inDate)", "alias": "date_only"},
    {"expr": "hour(te.inDate)", "alias": "hour_started"},
    {"expr": "date_diff(te.outDate, te.inDate, 'hours')", "alias": "hours_worked"}
  ]
}
```

---

## Testing

### Test 1: Primitive Value Wrapping

```bash
curl -X POST http://localhost:3000/query/dsl \
  -H "Content-Type: application/json" \
  -d '{
    "query": "{\"from\":{\"source_file\":\"orders_v2_orders_20260130.json\",\"alias\":\"o\",\"as_primitive\":\"guid\"},\"select\":[{\"expr\":\"o.guid\",\"alias\":\"order_guid\"}]}"
  }'
```

### Test 2: Date Function

```bash
curl -X POST http://localhost:3000/query/dsl \
  -H "Content-Type: application/json" \
  -d '{
    "query": "{\"from\":{\"source_file\":\"labor_v1_timeEntries_20260130.json\",\"alias\":\"te\"},\"select\":[{\"expr\":\"te.guid\",\"alias\":\"guid\"},{\"expr\":\"hour(te.inDate)\",\"alias\":\"hour\"},{\"expr\":\"date(te.inDate)\",\"alias\":\"date\"}]}"
  }'
```

### Test 3: Hourly Aggregation

```bash
curl -X POST http://localhost:3000/query/dsl \
  -H "Content-Type: application/json" \
  -d '{
    "query": "{\"from\":{\"source_file\":\"labor_v1_timeEntries_20260130.json\",\"alias\":\"te\"},\"group_by\":[{\"field\":\"hour(te.inDate)\",\"is_expr\":true}],\"select\":[{\"expr\":\"hour(te.inDate)\",\"alias\":\"hour\"},{\"expr\":\"count(te.guid)\",\"alias\":\"shift_count\"}]}"
  }'
```

---

## Dependencies

Add to `Cargo.toml`:

```toml
[dependencies]
chrono = { version = "0.4", features = ["serde"] }
regex = "1.10"
```

(Note: `regex` is likely already a transitive dependency)
