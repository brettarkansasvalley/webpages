//! Function registry for the DSL expression language
//!
//! Provides 50+ built-in functions for numeric, string, array, and object operations.

use anyhow::{anyhow, Result};
use serde_json::Value;
use std::collections::HashMap;
use std::sync::Arc;

use crate::context::Context;
use crate::expression::Expression;

/// A built-in function implementation
type BuiltinFn = Arc<dyn Fn(&[Value]) -> Result<Value> + Send + Sync>;

/// A user-defined function
#[derive(Debug, Clone)]
pub struct UserFunction {
    pub name: String,
    pub params: Vec<String>,
    pub body: Expression,
    pub doc: Option<String>,
}

/// Function registry containing built-in and user-defined functions
#[derive(Clone)]
pub struct FunctionRegistry {
    builtins: HashMap<String, BuiltinFn>,
    user_defined: HashMap<String, UserFunction>,
}

impl FunctionRegistry {
    /// Create a new registry with all built-in functions
    pub fn new() -> Self {
        let mut registry = Self {
            builtins: HashMap::new(),
            user_defined: HashMap::new(),
        };
        registry.register_all_builtins();
        registry
    }

    /// Register a built-in function
    pub fn register_builtin<F>(&mut self, name: &str, func: F)
    where
        F: Fn(&[Value]) -> Result<Value> + Send + Sync + 'static,
    {
        self.builtins.insert(name.to_string(), Arc::new(func));
    }

    /// Register a user-defined function
    pub fn register_user_function(&mut self, func: UserFunction) {
        self.user_defined.insert(func.name.clone(), func);
    }
    
    /// Register a user-defined function from a definition (for DSL integration)
    pub fn register_user_function_from_def(&mut self, name: String, def: crate::query_engine::UserFunctionDef) -> Result<()> {
        let func = UserFunction {
            name,
            params: def.params,
            body: def.body,
            doc: def.doc,
        };
        self.user_defined.insert(func.name.clone(), func);
        Ok(())
    }

    /// Call a function by name
    pub fn call(&self, name: &str, args: &[Value], context: &Context) -> Result<Value> {
        self.call_with_registry(name, args, context)
    }
    
    /// Call a function with registry support (for nested function calls)
    pub fn call_with_registry(&self, name: &str, args: &[Value], context: &Context) -> Result<Value> {
        // Check built-ins first
        if let Some(builtin) = self.builtins.get(name) {
            return builtin(args);
        }

        // Check user-defined functions
        if let Some(udf) = self.user_defined.get(name) {
            if args.len() != udf.params.len() {
                return Err(anyhow!(
                    "Function {} expects {} arguments, got {}",
                    name,
                    udf.params.len(),
                    args.len()
                ));
            }

            // Create new context with parameters bound
            let mut fn_context = context.child();
            for (param, arg) in udf.params.iter().zip(args.iter()) {
                fn_context.set(param.clone(), arg.clone());
            }

            // Use evaluate_with_registry to support nested function calls
            return udf.body.evaluate_with_registry(&fn_context, self);
        }

        Err(anyhow!("Unknown function: {}", name))
    }

    /// Check if a function exists
    pub fn has_function(&self, name: &str) -> bool {
        self.builtins.contains_key(name) || self.user_defined.contains_key(name)
    }

    /// Get list of all built-in function names
    pub fn builtin_names(&self) -> Vec<&String> {
        self.builtins.keys().collect()
    }

    /// Register all built-in functions
    fn register_all_builtins(&mut self) {
        self.register_numeric_functions();
        self.register_string_functions();
        self.register_array_functions();
        self.register_object_functions();
        self.register_type_functions();
        self.register_date_functions();
    }

    // =========================================================================
    // Numeric Functions
    // =========================================================================
    fn register_numeric_functions(&mut self) {
        // abs(n) - Absolute value
        self.register_builtin("abs", |args| {
            let n = get_number(args, 0)?;
            Ok(Value::Number(serde_json::Number::from_f64(n.abs()).unwrap_or(0.into())))
        });

        // floor(n) - Round down
        self.register_builtin("floor", |args| {
            let n = get_number(args, 0)?;
            Ok(Value::Number(serde_json::Number::from_f64(n.floor()).unwrap_or(0.into())))
        });

        // ceil(n) - Round up
        self.register_builtin("ceil", |args| {
            let n = get_number(args, 0)?;
            Ok(Value::Number(serde_json::Number::from_f64(n.ceil()).unwrap_or(0.into())))
        });

        // round(n, precision?) - Round to decimal places
        self.register_builtin("round", |args| {
            let n = get_number(args, 0)?;
            let precision = if args.len() > 1 {
                get_number(args, 1)? as i32
            } else {
                0
            };
            let multiplier = 10f64.powi(precision);
            let rounded = (n * multiplier).round() / multiplier;
            Ok(Value::Number(
                serde_json::Number::from_f64(rounded).unwrap_or(0.into()),
            ))
        });

        // sqrt(n) - Square root
        self.register_builtin("sqrt", |args| {
            let n = get_number(args, 0)?;
            if n < 0.0 {
                return Err(anyhow!("Cannot compute square root of negative number"));
            }
            Ok(Value::Number(
                serde_json::Number::from_f64(n.sqrt()).unwrap_or(0.into()),
            ))
        });

        // power(base, exp) - Exponentiation
        self.register_builtin("power", |args| {
            let base = get_number(args, 0)?;
            let exp = get_number(args, 1)?;
            Ok(Value::Number(
                serde_json::Number::from_f64(base.powf(exp)).unwrap_or(0.into()),
            ))
        });

        // random() - Random number 0-1
        self.register_builtin("random", |_args| {
            use std::time::{SystemTime, UNIX_EPOCH};
            let seed = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos() as u64;
            // Simple LCG random number generator
            let a = 1103515245u64;
            let c = 12345u64;
            let m = 2u64.pow(31);
            let r = (a.wrapping_mul(seed).wrapping_add(c)) % m;
            let val = r as f64 / m as f64;
            Ok(Value::Number(
                serde_json::Number::from_f64(val).unwrap_or(0.into()),
            ))
        });

        // max(arr) or max(a, b, ...) - Maximum
        self.register_builtin("max", |args| {
            if args.is_empty() {
                return Err(anyhow!("max() requires at least one argument"));
            }

            let numbers: Vec<f64> = if args.len() == 1 {
                // Single array argument
                match &args[0] {
                    Value::Array(arr) => arr.iter().filter_map(|v| v.as_f64()).collect(),
                    _ => return Err(anyhow!("max() expects an array or multiple numbers")),
                }
            } else {
                // Multiple arguments
                args.iter().filter_map(|v| v.as_f64()).collect()
            };

            numbers
                .into_iter()
                .max_by(|a, b| a.partial_cmp(b).unwrap())
                .map(|m| Value::Number(serde_json::Number::from_f64(m).unwrap_or(0.into())))
                .ok_or_else(|| anyhow!("max() could not find maximum"))
        });

        // min(arr) or min(a, b, ...) - Minimum
        self.register_builtin("min", |args| {
            if args.is_empty() {
                return Err(anyhow!("min() requires at least one argument"));
            }

            let numbers: Vec<f64> = if args.len() == 1 {
                match &args[0] {
                    Value::Array(arr) => arr.iter().filter_map(|v| v.as_f64()).collect(),
                    _ => return Err(anyhow!("min() expects an array or multiple numbers")),
                }
            } else {
                args.iter().filter_map(|v| v.as_f64()).collect()
            };

            numbers
                .into_iter()
                .min_by(|a, b| a.partial_cmp(b).unwrap())
                .map(|m| Value::Number(serde_json::Number::from_f64(m).unwrap_or(0.into())))
                .ok_or_else(|| anyhow!("min() could not find minimum"))
        });

        // sum(arr) - Sum of array
        self.register_builtin("sum", |args| {
            let arr = get_array(args, 0)?;
            let sum: f64 = arr.iter().filter_map(|v| v.as_f64()).sum();
            Ok(Value::Number(serde_json::Number::from_f64(sum).unwrap_or(0.into())))
        });

        // avg(arr) - Average of array
        self.register_builtin("avg", |args| {
            let arr = get_array(args, 0)?;
            let numbers: Vec<f64> = arr.iter().filter_map(|v| v.as_f64()).collect();
            if numbers.is_empty() {
                return Ok(Value::Null);
            }
            let avg = numbers.iter().sum::<f64>() / numbers.len() as f64;
            Ok(Value::Number(
                serde_json::Number::from_f64(avg).unwrap_or(0.into()),
            ))
        });

        // mod(a, b) - Modulo
        self.register_builtin("mod", |args| {
            let a = get_number(args, 0)?;
            let b = get_number(args, 1)?;
            if b == 0.0 {
                return Err(anyhow!("modulo by zero"));
            }
            Ok(Value::Number(serde_json::Number::from_f64(a % b).unwrap_or(0.into())))
        });
    }

    // =========================================================================
    // String Functions
    // =========================================================================
    fn register_string_functions(&mut self) {
        // length(str) - String length
        self.register_builtin("length", |args| {
            match &args[0] {
                Value::String(s) => Ok(Value::Number((s.len() as i64).into())),
                Value::Array(a) => Ok(Value::Number((a.len() as i64).into())),
                Value::Object(o) => Ok(Value::Number((o.len() as i64).into())),
                _ => Ok(Value::Number(1.into())),
            }
        });

        // uppercase(str) - To uppercase
        self.register_builtin("uppercase", |args| {
            let s = get_string(args, 0)?;
            Ok(Value::String(s.to_uppercase()))
        });

        // lowercase(str) - To lowercase
        self.register_builtin("lowercase", |args| {
            let s = get_string(args, 0)?;
            Ok(Value::String(s.to_lowercase()))
        });

        // trim(str) - Remove whitespace
        self.register_builtin("trim", |args| {
            let s = get_string(args, 0)?;
            Ok(Value::String(s.trim().to_string()))
        });

        // substring(str, start, length?) - Extract substring
        self.register_builtin("substring", |args| {
            let s = get_string(args, 0)?;
            let start = get_number(args, 1)? as usize;
            let len = if args.len() > 2 {
                get_number(args, 2)? as usize
            } else {
                s.len() - start
            };

            if start >= s.len() {
                return Ok(Value::String("".to_string()));
            }

            let end = (start + len).min(s.len());
            Ok(Value::String(s[start..end].to_string()))
        });

        // replace(str, pattern, replacement) - Replace occurrences
        self.register_builtin("replace", |args| {
            let s = get_string(args, 0)?;
            let pattern = get_string(args, 1)?;
            let replacement = get_string(args, 2)?;
            Ok(Value::String(s.replace(&pattern, &replacement)))
        });

        // split(str, delimiter) - Split into array
        self.register_builtin("split", |args| {
            let s = get_string(args, 0)?;
            let delimiter = get_string(args, 1)?;
            let parts: Vec<Value> = s
                .split(&delimiter)
                .map(|p| Value::String(p.to_string()))
                .collect();
            Ok(Value::Array(parts))
        });

        // join(arr, separator) - Join array elements
        self.register_builtin("join", |args| {
            let arr = get_array(args, 0)?;
            let separator = if args.len() > 1 {
                get_string(args, 1)?
            } else {
                ",".to_string()
            };

            let strings: Vec<String> = arr
                .iter()
                .map(|v| match v {
                    Value::String(s) => s.clone(),
                    other => other.to_string(),
                })
                .collect();

            Ok(Value::String(strings.join(&separator)))
        });

        // format(template, ...args) - String formatting
        self.register_builtin("format", |args| {
            if args.is_empty() {
                return Err(anyhow!("format() requires at least a template string"));
            }
            let template = get_string(args, 0)?;
            let mut result = template;

            // Simple placeholder replacement: {} gets replaced sequentially
            for (i, arg) in args.iter().skip(1).enumerate() {
                let placeholder = "{}";
                let value = match arg {
                    Value::String(s) => s.clone(),
                    other => other.to_string(),
                };
                result = result.replacen(placeholder, &value, 1);
            }

            Ok(Value::String(result))
        });

        // pad(str, length, char?) - Pad string
        self.register_builtin("pad", |args| {
            let s = get_string(args, 0)?;
            let length = get_number(args, 1)? as usize;
            let pad_char = if args.len() > 2 {
                get_string(args, 2)?.chars().next().unwrap_or(' ')
            } else {
                ' '
            };

            if s.len() >= length {
                return Ok(Value::String(s));
            }

            let padding: String = std::iter::repeat(pad_char).take(length - s.len()).collect();
            Ok(Value::String(format!("{}{}", s, padding)))
        });

        // padStart(str, length, char?) - Left pad
        self.register_builtin("pad_start", |args| {
            let s = get_string(args, 0)?;
            let length = get_number(args, 1)? as usize;
            let pad_char = if args.len() > 2 {
                get_string(args, 2)?.chars().next().unwrap_or(' ')
            } else {
                ' '
            };

            if s.len() >= length {
                return Ok(Value::String(s));
            }

            let padding: String = std::iter::repeat(pad_char).take(length - s.len()).collect();
            Ok(Value::String(format!("{}{}", padding, s)))
        });
    }

    // =========================================================================
    // Array Functions
    // =========================================================================
    fn register_array_functions(&mut self) {
        // count(arr) - Array length
        self.register_builtin("count", |args| {
            match &args[0] {
                Value::Array(a) => Ok(Value::Number((a.len() as i64).into())),
                _ => Ok(Value::Number(1.into())),
            }
        });

        // append(arr1, arr2) - Concatenate arrays
        self.register_builtin("append", |args| {
            let mut result = get_array(args, 0)?;
            let arr2 = get_array(args, 1)?;
            result.extend(arr2);
            Ok(Value::Array(result))
        });

        // reverse(arr) - Reverse array
        self.register_builtin("reverse", |args| {
            let mut arr = get_array(args, 0)?;
            arr.reverse();
            Ok(Value::Array(arr))
        });

        // distinct(arr) - Remove duplicates
        self.register_builtin("distinct", |args| {
            let arr = get_array(args, 0)?;
            let mut seen = Vec::new();
            let mut result = Vec::new();

            for item in arr {
                if !seen.contains(&item) {
                    seen.push(item.clone());
                    result.push(item);
                }
            }

            Ok(Value::Array(result))
        });

        // flatten(arr, depth?) - Flatten nested arrays
        self.register_builtin("flatten", |args| {
            let arr = get_array(args, 0)?;
            let depth = if args.len() > 1 {
                get_number(args, 1)? as usize
            } else {
                1
            };

            fn flatten_recursive(arr: Vec<Value>, depth: usize) -> Vec<Value> {
                if depth == 0 {
                    return arr;
                }

                let mut result = Vec::new();
                for item in arr {
                    match item {
                        Value::Array(nested) => {
                            result.extend(flatten_recursive(nested, depth - 1));
                        }
                        other => result.push(other),
                    }
                }
                result
            }

            Ok(Value::Array(flatten_recursive(arr, depth)))
        });

        // range(start, end, step?) - Generate number range
        self.register_builtin("range", |args| {
            let start = get_number(args, 0)? as i64;
            let end = get_number(args, 1)? as i64;
            let step = if args.len() > 2 {
                get_number(args, 2)? as i64
            } else {
                1
            };

            if step == 0 {
                return Err(anyhow!("range() step cannot be zero"));
            }

            let mut result = Vec::new();
            let mut current = start;

            if step > 0 {
                while current < end {
                    result.push(Value::Number(current.into()));
                    current += step;
                }
            } else {
                while current > end {
                    result.push(Value::Number(current.into()));
                    current += step;
                }
            }

            Ok(Value::Array(result))
        });

        // zip(arr1, arr2, ...) - Zip arrays together
        self.register_builtin("zip", |args| {
            let arrays: Vec<Vec<Value>> = args
                .iter()
                .map(|a| match a {
                    Value::Array(arr) => arr.clone(),
                    _ => vec![a.clone()],
                })
                .collect();

            if arrays.is_empty() {
                return Ok(Value::Array(vec![]));
            }

            let min_len = arrays.iter().map(|a| a.len()).min().unwrap_or(0);
            let mut result = Vec::new();

            for i in 0..min_len {
                let zipped: Vec<Value> = arrays.iter().map(|a| a[i].clone()).collect();
                result.push(Value::Array(zipped));
            }

            Ok(Value::Array(result))
        });

        // take(n, arr) - Take first n elements
        self.register_builtin("take", |args| {
            let n = get_number(args, 0)? as usize;
            let arr = get_array(args, 1)?;
            let taken: Vec<Value> = arr.into_iter().take(n).collect();
            Ok(Value::Array(taken))
        });

        // drop(n, arr) - Drop first n elements
        self.register_builtin("drop", |args| {
            let n = get_number(args, 0)? as usize;
            let arr = get_array(args, 1)?;
            let dropped: Vec<Value> = arr.into_iter().skip(n).collect();
            Ok(Value::Array(dropped))
        });

        // slice(arr, start, end?) - Array slice
        self.register_builtin("slice", |args| {
            let arr = get_array(args, 0)?;
            let len = arr.len() as f64;
            let start = get_number(args, 1)?.rem_euclid(len) as usize;
            let end = if args.len() > 2 {
                get_number(args, 2)?.rem_euclid(len) as usize
            } else {
                arr.len()
            };

            Ok(Value::Array(arr[start..end.min(arr.len())].to_vec()))
        });

        // indexOf(arr, value) - Find index of value
        self.register_builtin("index_of", |args| {
            let arr = get_array(args, 0)?;
            let value = &args[1];

            for (i, item) in arr.iter().enumerate() {
                if item == value {
                    return Ok(Value::Number((i as i64).into()));
                }
            }

            Ok(Value::Number((-1i64).into()))
        });

        // contains(arr, value) - Check if array contains value
        self.register_builtin("array_contains", |args| {
            let arr = get_array(args, 0)?;
            let value = &args[1];
            Ok(Value::Bool(arr.contains(value)))
        });
    }

    // =========================================================================
    // Object Functions
    // =========================================================================
    fn register_object_functions(&mut self) {
        // keys(obj) - Get object keys
        self.register_builtin("keys", |args| {
            match &args[0] {
                Value::Object(o) => {
                    let keys: Vec<Value> = o
                        .keys()
                        .map(|k| Value::String(k.clone()))
                        .collect();
                    Ok(Value::Array(keys))
                }
                _ => Ok(Value::Array(vec![])),
            }
        });

        // values(obj) - Get object values
        self.register_builtin("values", |args| {
            match &args[0] {
                Value::Object(o) => Ok(Value::Array(o.values().cloned().collect())),
                _ => Ok(Value::Array(vec![])),
            }
        });

        // lookup(obj, key) - Safe property access
        self.register_builtin("lookup", |args| {
            let obj = get_object(args, 0)?;
            let key = get_string(args, 1)?;
            Ok(obj.get(&key).cloned().unwrap_or(Value::Null))
        });

        // spread(obj) - Object to key-value pairs
        self.register_builtin("spread", |args| {
            match &args[0] {
                Value::Object(o) => {
                    let pairs: Vec<Value> = o
                        .iter()
                        .map(|(k, v)| {
                            let mut pair = serde_json::Map::new();
                            pair.insert("key".to_string(), Value::String(k.clone()));
                            pair.insert("value".to_string(), v.clone());
                            Value::Object(pair)
                        })
                        .collect();
                    Ok(Value::Array(pairs))
                }
                _ => Ok(Value::Array(vec![])),
            }
        });

        // merge(arr) - Merge array of objects
        self.register_builtin("merge", |args| {
            let arr = get_array(args, 0)?;
            let mut result = serde_json::Map::new();

            for item in arr {
                if let Value::Object(o) = item {
                    for (k, v) in o {
                        result.insert(k, v);
                    }
                }
            }

            Ok(Value::Object(result))
        });

        // entries(obj) - Object to [key, value] pairs
        self.register_builtin("entries", |args| {
            match &args[0] {
                Value::Object(o) => {
                    let entries: Vec<Value> = o
                        .iter()
                        .map(|(k, v)| {
                            Value::Array(vec![Value::String(k.clone()), v.clone()])
                        })
                        .collect();
                    Ok(Value::Array(entries))
                }
                _ => Ok(Value::Array(vec![])),
            }
        });

        // from_entries(arr) - [key, value] pairs to object
        self.register_builtin("from_entries", |args| {
            let arr = get_array(args, 0)?;
            let mut result = serde_json::Map::new();

            for item in arr {
                if let Value::Array(pair) = item {
                    if pair.len() >= 2 {
                        let key = match &pair[0] {
                            Value::String(s) => s.clone(),
                            other => other.to_string(),
                        };
                        result.insert(key, pair[1].clone());
                    }
                }
            }

            Ok(Value::Object(result))
        });
    }

    // =========================================================================
    // Type Functions
    // =========================================================================
    fn register_type_functions(&mut self) {
        // type(value) - Get type name
        self.register_builtin("type", |args| {
            let type_name = match &args[0] {
                Value::Null => "null",
                Value::Bool(_) => "boolean",
                Value::Number(_) => "number",
                Value::String(_) => "string",
                Value::Array(_) => "array",
                Value::Object(_) => "object",
            };
            Ok(Value::String(type_name.to_string()))
        });

        // to_number(value) - Convert to number
        self.register_builtin("to_number", |args| {
            match &args[0] {
                Value::Number(n) => Ok(Value::Number(n.clone())),
                Value::String(s) => match s.parse::<f64>() {
                    Ok(n) => Ok(Value::Number(
                        serde_json::Number::from_f64(n).unwrap_or(0.into()),
                    )),
                    Err(_) => Ok(Value::Null),
                },
                Value::Bool(true) => Ok(Value::Number(1.into())),
                Value::Bool(false) => Ok(Value::Number(0.into())),
                _ => Ok(Value::Null),
            }
        });

        // to_string(value) - Convert to string
        self.register_builtin("to_string", |args| {
            match &args[0] {
                Value::String(s) => Ok(Value::String(s.clone())),
                other => Ok(Value::String(other.to_string())),
            }
        });
    }

    // =========================================================================
    // Date/Time Functions
    // =========================================================================
    fn register_date_functions(&mut self) {
        // now() - Current timestamp (ISO 8601)
        self.register_builtin("now", |_args| {
            use chrono::Utc;
            Ok(Value::String(Utc::now().to_rfc3339()))
        });

        // today() - Current date (YYYY-MM-DD)
        self.register_builtin("today", |_args| {
            use chrono::Utc;
            Ok(Value::String(Utc::now().format("%Y-%m-%d").to_string()))
        });

        // millis() - Current time in milliseconds since epoch
        self.register_builtin("millis", |_args| {
            use std::time::{SystemTime, UNIX_EPOCH};
            let millis = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as i64;
            Ok(Value::Number(millis.into()))
        });
    }
}

impl Default for FunctionRegistry {
    fn default() -> Self {
        Self::new()
    }
}

// ============================================================================
// Helper Functions
// ============================================================================

fn get_number(args: &[Value], index: usize) -> Result<f64> {
    args.get(index)
        .and_then(|v| v.as_f64())
        .ok_or_else(|| anyhow!("Argument {} must be a number", index))
}

fn get_string(args: &[Value], index: usize) -> Result<String> {
    match args.get(index) {
        Some(Value::String(s)) => Ok(s.clone()),
        Some(other) => Ok(other.to_string()),
        None => Err(anyhow!("Missing argument {}", index)),
    }
}

fn get_array(args: &[Value], index: usize) -> Result<Vec<Value>> {
    match args.get(index) {
        Some(Value::Array(a)) => Ok(a.clone()),
        Some(other) => Err(anyhow!("Argument {} must be an array, got {:?}", index, other)),
        None => Err(anyhow!("Missing argument {}", index)),
    }
}

fn get_object(args: &[Value], index: usize) -> Result<serde_json::Map<String, Value>> {
    match args.get(index) {
        Some(Value::Object(o)) => Ok(o.clone()),
        Some(other) => Err(anyhow!("Argument {} must be an object, got {:?}", index, other)),
        None => Err(anyhow!("Missing argument {}", index)),
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    fn test_registry() -> FunctionRegistry {
        FunctionRegistry::new()
    }

    fn test_context() -> Context {
        Context::new()
    }

    #[test]
    fn test_abs() {
        let reg = test_registry();
        let ctx = test_context();
        
        let result = reg.call("abs", &[Value::Number((-5).into())], &ctx).unwrap();
        assert_eq!(result.as_f64(), Some(5.0));
        
        let result = reg.call("abs", &[Value::Number(5.into())], &ctx).unwrap();
        assert_eq!(result.as_f64(), Some(5.0));
    }

    #[test]
    fn test_round() {
        let reg = test_registry();
        let ctx = test_context();
        
        let result = reg.call("round", &[Value::Number(serde_json::Number::from_f64(3.14159).unwrap())], &ctx).unwrap();
        assert_eq!(result.as_f64(), Some(3.0));
        
        let result = reg.call("round", &[Value::Number(serde_json::Number::from_f64(3.14159).unwrap()), Value::Number(2.into())], &ctx).unwrap();
        assert_eq!(result.as_f64(), Some(3.14));
    }

    #[test]
    fn test_sum() {
        let reg = test_registry();
        let ctx = test_context();
        
        let arr = Value::Array(vec![
            Value::Number(1.into()),
            Value::Number(2.into()),
            Value::Number(3.into()),
        ]);
        let result = reg.call("sum", &[arr], &ctx).unwrap();
        assert_eq!(result.as_f64(), Some(6.0));
    }

    #[test]
    fn test_max_min() {
        let reg = test_registry();
        let ctx = test_context();
        
        let arr = Value::Array(vec![
            Value::Number(3.into()),
            Value::Number(1.into()),
            Value::Number(4.into()),
            Value::Number(2.into()),
        ]);
        
        let result = reg.call("max", &[arr.clone()], &ctx).unwrap();
        assert_eq!(result.as_f64(), Some(4.0));
        
        let result = reg.call("min", &[arr], &ctx).unwrap();
        assert_eq!(result.as_f64(), Some(1.0));
    }

    #[test]
    fn test_uppercase_lowercase() {
        let reg = test_registry();
        let ctx = test_context();
        
        let result = reg.call("uppercase", &[Value::String("hello".to_string())], &ctx).unwrap();
        assert_eq!(result, Value::String("HELLO".to_string()));
        
        let result = reg.call("lowercase", &[Value::String("WORLD".to_string())], &ctx).unwrap();
        assert_eq!(result, Value::String("world".to_string()));
    }

    #[test]
    fn test_split_join() {
        let reg = test_registry();
        let ctx = test_context();
        
        let result = reg.call("split", &[Value::String("a,b,c".to_string()), Value::String(",".to_string())], &ctx).unwrap();
        assert_eq!(result, Value::Array(vec![
            Value::String("a".to_string()),
            Value::String("b".to_string()),
            Value::String("c".to_string()),
        ]));
        
        let result = reg.call("join", &[result, Value::String("-".to_string())], &ctx).unwrap();
        assert_eq!(result, Value::String("a-b-c".to_string()));
    }

    #[test]
    fn test_range() {
        let reg = test_registry();
        let ctx = test_context();
        
        let result = reg.call("range", &[Value::Number(0.into()), Value::Number(5.into())], &ctx).unwrap();
        assert_eq!(result, Value::Array(vec![
            Value::Number(0.into()),
            Value::Number(1.into()),
            Value::Number(2.into()),
            Value::Number(3.into()),
            Value::Number(4.into()),
        ]));
    }

    #[test]
    fn test_distinct() {
        let reg = test_registry();
        let ctx = test_context();
        
        let arr = Value::Array(vec![
            Value::Number(1.into()),
            Value::Number(2.into()),
            Value::Number(1.into()),
            Value::Number(3.into()),
        ]);
        let result = reg.call("distinct", &[arr], &ctx).unwrap();
        assert_eq!(result, Value::Array(vec![
            Value::Number(1.into()),
            Value::Number(2.into()),
            Value::Number(3.into()),
        ]));
    }

    #[test]
    fn test_keys_values() {
        let reg = test_registry();
        let ctx = test_context();
        
        let mut obj = serde_json::Map::new();
        obj.insert("a".to_string(), Value::Number(1.into()));
        obj.insert("b".to_string(), Value::Number(2.into()));
        
        let result = reg.call("keys", &[Value::Object(obj.clone())], &ctx).unwrap();
        assert!(matches!(result, Value::Array(arr) if arr.len() == 2));
        
        let result = reg.call("values", &[Value::Object(obj)], &ctx).unwrap();
        assert_eq!(result, Value::Array(vec![
            Value::Number(1.into()),
            Value::Number(2.into()),
        ]));
    }

    #[test]
    fn test_merge() {
        let reg = test_registry();
        let ctx = test_context();
        
        let mut obj1 = serde_json::Map::new();
        obj1.insert("a".to_string(), Value::Number(1.into()));
        
        let mut obj2 = serde_json::Map::new();
        obj2.insert("b".to_string(), Value::Number(2.into()));
        
        let arr = Value::Array(vec![Value::Object(obj1), Value::Object(obj2)]);
        let result = reg.call("merge", &[arr], &ctx).unwrap();
        
        if let Value::Object(o) = result {
            assert_eq!(o.get("a"), Some(&Value::Number(1.into())));
            assert_eq!(o.get("b"), Some(&Value::Number(2.into())));
        } else {
            panic!("Expected object");
        }
    }

    #[test]
    fn test_type() {
        let reg = test_registry();
        let ctx = test_context();
        
        assert_eq!(reg.call("type", &[Value::Null], &ctx).unwrap(), Value::String("null".to_string()));
        assert_eq!(reg.call("type", &[Value::Bool(true)], &ctx).unwrap(), Value::String("boolean".to_string()));
        assert_eq!(reg.call("type", &[Value::Number(42.into())], &ctx).unwrap(), Value::String("number".to_string()));
        assert_eq!(reg.call("type", &[Value::String("test".to_string())], &ctx).unwrap(), Value::String("string".to_string()));
        assert_eq!(reg.call("type", &[Value::Array(vec![])], &ctx).unwrap(), Value::String("array".to_string()));
        assert_eq!(reg.call("type", &[Value::Object(serde_json::Map::new())], &ctx).unwrap(), Value::String("object".to_string()));
    }

    #[test]
    fn test_zip() {
        let reg = test_registry();
        let ctx = test_context();
        
        let arr1 = Value::Array(vec![Value::Number(1.into()), Value::Number(2.into())]);
        let arr2 = Value::Array(vec![Value::String("a".to_string()), Value::String("b".to_string())]);
        
        let result = reg.call("zip", &[arr1, arr2], &ctx).unwrap();
        assert_eq!(result, Value::Array(vec![
            Value::Array(vec![Value::Number(1.into()), Value::String("a".to_string())]),
            Value::Array(vec![Value::Number(2.into()), Value::String("b".to_string())]),
        ]));
    }
}
