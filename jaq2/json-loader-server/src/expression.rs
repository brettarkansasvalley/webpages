//! Expression evaluation engine for the DSL
//!
//! This module provides a functional programming expression system
//! inspired by JSONata, supporting arithmetic, comparisons, logic,
//! and variable references.

use anyhow::{anyhow, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

use crate::context::Context;
use crate::functions::FunctionRegistry;

/// An expression in the DSL expression language
/// 
/// Expressions can be evaluated against a context to produce a Value.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Expression {
    /// Literal value (number, string, boolean, null, array, object)
    Literal(Value),
    
    /// Variable reference (e.g., $, $var, or field path)
    Var(String),
    
    /// Field access: object.field
    FieldAccess {
        object: Box<Expression>,
        field: String,
    },
    
    /// Index access: array[index]
    IndexAccess {
        array: Box<Expression>,
        index: Box<Expression>,
    },
    
    // Arithmetic operations
    /// Addition: a + b
    Add(Box<Expression>, Box<Expression>),
    /// Subtraction: a - b
    Subtract(Box<Expression>, Box<Expression>),
    /// Multiplication: a * b
    Multiply(Box<Expression>, Box<Expression>),
    /// Division: a / b
    Divide(Box<Expression>, Box<Expression>),
    /// Modulo: a % b
    Modulo(Box<Expression>, Box<Expression>),
    /// Power: a ^ b
    Power(Box<Expression>, Box<Expression>),
    /// Negation: -a
    Negate(Box<Expression>),
    
    // Comparison operations
    /// Equality: a = b
    Eq(Box<Expression>, Box<Expression>),
    /// Inequality: a != b
    Ne(Box<Expression>, Box<Expression>),
    /// Less than: a < b
    Lt(Box<Expression>, Box<Expression>),
    /// Less than or equal: a <= b
    Le(Box<Expression>, Box<Expression>),
    /// Greater than: a > b
    Gt(Box<Expression>, Box<Expression>),
    /// Greater than or equal: a >= b
    Ge(Box<Expression>, Box<Expression>),
    
    // Logical operations
    /// Logical AND: a and b
    And(Box<Expression>, Box<Expression>),
    /// Logical OR: a or b
    Or(Box<Expression>, Box<Expression>),
    /// Logical NOT: not a
    Not(Box<Expression>),
    
    // String operations
    /// String concatenation: a & b
    Concat(Vec<Expression>),
    /// String contains: contains(string, substring)
    Contains {
        string: Box<Expression>,
        substring: Box<Expression>,
    },
    /// String starts with: starts_with(string, prefix)
    StartsWith {
        string: Box<Expression>,
        prefix: Box<Expression>,
    },
    /// String ends with: ends_with(string, suffix)
    EndsWith {
        string: Box<Expression>,
        suffix: Box<Expression>,
    },
    
    // Type checking
    /// Check if null
    IsNull(Box<Expression>),
    /// Check if array
    IsArray(Box<Expression>),
    /// Check if object
    IsObject(Box<Expression>),
    /// Check if string
    IsString(Box<Expression>),
    /// Check if number
    IsNumber(Box<Expression>),
    /// Check if boolean
    IsBoolean(Box<Expression>),
    
    /// Conditional: if condition then then_branch else else_branch
    If {
        condition: Box<Expression>,
        then_branch: Box<Expression>,
        else_branch: Box<Expression>,
    },
    
    /// Function call: name(args...)
    Call {
        name: String,
        args: Vec<Expression>,
    },
    
    /// Let binding: let bindings in body
    Let {
        bindings: HashMap<String, Expression>,
        body: Box<Expression>,
    },
    
    /// Map: transform each element of an array
    Map {
        array: Box<Expression>,
        function: Box<Expression>, // Lambda expression
    },
    
    /// Filter: keep elements matching predicate
    Filter {
        array: Box<Expression>,
        predicate: Box<Expression>, // Lambda expression returning boolean
    },
    
    /// Reduce: fold array to single value
    Reduce {
        array: Box<Expression>,
        function: Box<Expression>, // Lambda (acc, item) -> new_acc
        initial: Box<Expression>,
    },
    
    /// Lambda: anonymous function
    Lambda {
        params: Vec<String>,
        body: Box<Expression>,
    },
}

impl Expression {
    /// Evaluate this expression in the given context
    pub fn evaluate(&self, context: &Context) -> Result<Value> {
        match self {
            Expression::Literal(value) => Ok(value.clone()),
            Expression::Var(name) => context.get(name),
            Expression::FieldAccess { object, field } => {
                self.eval_field_access(object, field, context)
            }
            Expression::IndexAccess { array, index } => {
                self.eval_index_access(array, index, context)
            }
            Expression::Add(a, b) => self.eval_add(a, b, context),
            Expression::Subtract(a, b) => self.eval_subtract(a, b, context),
            Expression::Multiply(a, b) => self.eval_multiply(a, b, context),
            Expression::Divide(a, b) => self.eval_divide(a, b, context),
            Expression::Modulo(a, b) => self.eval_modulo(a, b, context),
            Expression::Power(a, b) => self.eval_power(a, b, context),
            Expression::Negate(a) => self.eval_negate(a, context),
            Expression::Eq(a, b) => self.eval_eq(a, b, context),
            Expression::Ne(a, b) => self.eval_ne(a, b, context),
            Expression::Lt(a, b) => self.eval_lt(a, b, context),
            Expression::Le(a, b) => self.eval_le(a, b, context),
            Expression::Gt(a, b) => self.eval_gt(a, b, context),
            Expression::Ge(a, b) => self.eval_ge(a, b, context),
            Expression::And(a, b) => self.eval_and(a, b, context),
            Expression::Or(a, b) => self.eval_or(a, b, context),
            Expression::Not(a) => self.eval_not(a, context),
            Expression::Concat(exprs) => self.eval_concat(exprs, context),
            Expression::Contains { string, substring } => {
                self.eval_contains(string, substring, context)
            }
            Expression::StartsWith { string, prefix } => {
                self.eval_starts_with(string, prefix, context)
            }
            Expression::EndsWith { string, suffix } => {
                self.eval_ends_with(string, suffix, context)
            }
            Expression::IsNull(a) => self.eval_is_null(a, context),
            Expression::IsArray(a) => self.eval_is_array(a, context),
            Expression::IsObject(a) => self.eval_is_object(a, context),
            Expression::IsString(a) => self.eval_is_string(a, context),
            Expression::IsNumber(a) => self.eval_is_number(a, context),
            Expression::IsBoolean(a) => self.eval_is_boolean(a, context),
            Expression::If { condition, then_branch, else_branch } => {
                self.eval_if(condition, then_branch, else_branch, context)
            }
            Expression::Call { name, args } => {
                // Note: This will be enhanced later with FunctionRegistry
                // For now, we need to handle simple built-in calls differently
                // This is a placeholder that will be called by evaluate_with_registry
                Err(anyhow!("Function calls require FunctionRegistry - use evaluate_with_registry()"))
            }
            Expression::Let { bindings, body } => {
                self.eval_let(bindings, body, context)
            }
            Expression::Map { array, function } => {
                self.eval_map(array, function, context)
            }
            Expression::Filter { array, predicate } => {
                self.eval_filter(array, predicate, context)
            }
            Expression::Reduce { array, function, initial } => {
                self.eval_reduce(array, function, initial, context)
            }
            Expression::Lambda { .. } => {
                // Lambda evaluates to itself (it's a value)
                Ok(Value::String("<lambda>".to_string()))
            }
        }
    }

    /// Evaluate with function registry support
    pub fn evaluate_with_registry(&self, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        match self {
            Expression::Literal(value) => Ok(value.clone()),
            Expression::Var(name) => context.get(name),
            Expression::FieldAccess { object, field } => {
                self.eval_field_access_with_registry(object, field, context, registry)
            }
            Expression::IndexAccess { array, index } => {
                self.eval_index_access_with_registry(array, index, context, registry)
            }
            Expression::Add(a, b) => self.eval_add_with_registry(a, b, context, registry),
            Expression::Subtract(a, b) => self.eval_subtract_with_registry(a, b, context, registry),
            Expression::Multiply(a, b) => self.eval_multiply_with_registry(a, b, context, registry),
            Expression::Divide(a, b) => self.eval_divide_with_registry(a, b, context, registry),
            Expression::Modulo(a, b) => self.eval_modulo_with_registry(a, b, context, registry),
            Expression::Power(a, b) => self.eval_power_with_registry(a, b, context, registry),
            Expression::Negate(a) => self.eval_negate_with_registry(a, context, registry),
            Expression::Eq(a, b) => self.eval_eq_with_registry(a, b, context, registry),
            Expression::Ne(a, b) => self.eval_ne_with_registry(a, b, context, registry),
            Expression::Lt(a, b) => self.eval_lt_with_registry(a, b, context, registry),
            Expression::Le(a, b) => self.eval_le_with_registry(a, b, context, registry),
            Expression::Gt(a, b) => self.eval_gt_with_registry(a, b, context, registry),
            Expression::Ge(a, b) => self.eval_ge_with_registry(a, b, context, registry),
            Expression::And(a, b) => self.eval_and_with_registry(a, b, context, registry),
            Expression::Or(a, b) => self.eval_or_with_registry(a, b, context, registry),
            Expression::Not(a) => self.eval_not_with_registry(a, context, registry),
            Expression::Concat(exprs) => self.eval_concat_with_registry(exprs, context, registry),
            Expression::Contains { string, substring } => {
                self.eval_contains_with_registry(string, substring, context, registry)
            }
            Expression::StartsWith { string, prefix } => {
                self.eval_starts_with_with_registry(string, prefix, context, registry)
            }
            Expression::EndsWith { string, suffix } => {
                self.eval_ends_with_with_registry(string, suffix, context, registry)
            }
            Expression::IsNull(a) => self.eval_is_null_with_registry(a, context, registry),
            Expression::IsArray(a) => self.eval_is_array_with_registry(a, context, registry),
            Expression::IsObject(a) => self.eval_is_object_with_registry(a, context, registry),
            Expression::IsString(a) => self.eval_is_string_with_registry(a, context, registry),
            Expression::IsNumber(a) => self.eval_is_number_with_registry(a, context, registry),
            Expression::IsBoolean(a) => self.eval_is_boolean_with_registry(a, context, registry),
            Expression::If { condition, then_branch, else_branch } => {
                self.eval_if_with_registry(condition, then_branch, else_branch, context, registry)
            }
            Expression::Call { name, args } => {
                let evaluated_args: Result<Vec<Value>> = args.iter()
                    .map(|a| a.evaluate_with_registry(context, registry))
                    .collect();
                registry.call_with_registry(name, &evaluated_args?, context)
            }
            Expression::Let { bindings, body } => {
                self.eval_let_with_registry(bindings, body, context, registry)
            }
            Expression::Map { array, function } => {
                self.eval_map_with_registry(array, function, context, registry)
            }
            Expression::Filter { array, predicate } => {
                self.eval_filter_with_registry(array, predicate, context, registry)
            }
            Expression::Reduce { array, function, initial } => {
                self.eval_reduce_with_registry(array, function, initial, context, registry)
            }
            Expression::Lambda { .. } => {
                Ok(Value::String("<lambda>".to_string()))
            }
        }
    }

    // Field access implementation - supports dot notation for nested access
    fn eval_field_access(&self, object: &Expression, field: &str, context: &Context) -> Result<Value> {
        let obj_val = object.evaluate(context)?;
        
        // Handle dot notation for nested field access (e.g., "variant.price")
        let fields: Vec<&str> = field.split('.').collect();
        
        let mut current = obj_val;
        for field_name in &fields {
            match current {
                Value::Object(map) => {
                    current = map.get(*field_name).cloned().unwrap_or(Value::Null);
                }
                _ => return Ok(Value::Null),
            }
        }
        
        Ok(current)
    }

    // Index access implementation
    fn eval_index_access(&self, array: &Expression, index: &Expression, context: &Context) -> Result<Value> {
        let arr_val = array.evaluate(context)?;
        let idx_val = index.evaluate(context)?;
        
        match (&arr_val, &idx_val) {
            (Value::Array(arr), Value::Number(n)) => {
                let idx = n.as_i64().unwrap_or(0) as isize;
                let len = arr.len() as isize;
                
                // Handle negative indices (Python-style)
                let actual_idx = if idx < 0 { len + idx } else { idx };
                
                if actual_idx >= 0 && actual_idx < len {
                    Ok(arr[actual_idx as usize].clone())
                } else {
                    Ok(Value::Null)
                }
            }
            (Value::Object(obj), Value::String(key)) => {
                Ok(obj.get(key).cloned().unwrap_or(Value::Null))
            }
            _ => Ok(Value::Null),
        }
    }

    // Arithmetic operations
    fn eval_add(&self, a: &Expression, b: &Expression, context: &Context) -> Result<Value> {
        let left = a.evaluate(context)?;
        let right = b.evaluate(context)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                let result = l.as_f64().unwrap_or(0.0) + r.as_f64().unwrap_or(0.0);
                Ok(Value::Number(serde_json::Number::from_f64(result).unwrap_or(0.into())))
            }
            (Value::String(l), Value::String(r)) => {
                Ok(Value::String(format!("{}{}", l, r)))
            }
            (Value::Array(l), Value::Array(r)) => {
                let mut result = l.clone();
                result.extend(r.iter().cloned());
                Ok(Value::Array(result))
            }
            _ => Err(anyhow!("Cannot add {:?} and {:?}", left, right)),
        }
    }

    fn eval_subtract(&self, a: &Expression, b: &Expression, context: &Context) -> Result<Value> {
        let left = a.evaluate(context)?;
        let right = b.evaluate(context)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                let result = l.as_f64().unwrap_or(0.0) - r.as_f64().unwrap_or(0.0);
                Ok(Value::Number(serde_json::Number::from_f64(result).unwrap_or(0.into())))
            }
            _ => Err(anyhow!("Cannot subtract {:?} from {:?}", right, left)),
        }
    }

    fn eval_multiply(&self, a: &Expression, b: &Expression, context: &Context) -> Result<Value> {
        let left = a.evaluate(context)?;
        let right = b.evaluate(context)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                let result = l.as_f64().unwrap_or(0.0) * r.as_f64().unwrap_or(0.0);
                Ok(Value::Number(serde_json::Number::from_f64(result).unwrap_or(0.into())))
            }
            _ => Err(anyhow!("Cannot multiply {:?} and {:?}", left, right)),
        }
    }

    fn eval_divide(&self, a: &Expression, b: &Expression, context: &Context) -> Result<Value> {
        let left = a.evaluate(context)?;
        let right = b.evaluate(context)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                let divisor = r.as_f64().unwrap_or(0.0);
                if divisor == 0.0 {
                    return Err(anyhow!("Division by zero"));
                }
                let result = l.as_f64().unwrap_or(0.0) / divisor;
                Ok(Value::Number(serde_json::Number::from_f64(result).unwrap_or(0.into())))
            }
            _ => Err(anyhow!("Cannot divide {:?} by {:?}", left, right)),
        }
    }

    fn eval_modulo(&self, a: &Expression, b: &Expression, context: &Context) -> Result<Value> {
        let left = a.evaluate(context)?;
        let right = b.evaluate(context)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                let divisor = r.as_f64().unwrap_or(1.0);
                if divisor == 0.0 {
                    return Err(anyhow!("Modulo by zero"));
                }
                let result = l.as_f64().unwrap_or(0.0) % divisor;
                Ok(Value::Number(serde_json::Number::from_f64(result).unwrap_or(0.into())))
            }
            _ => Err(anyhow!("Cannot compute modulo of {:?} and {:?}", left, right)),
        }
    }

    fn eval_power(&self, a: &Expression, b: &Expression, context: &Context) -> Result<Value> {
        let left = a.evaluate(context)?;
        let right = b.evaluate(context)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                let base = l.as_f64().unwrap_or(0.0);
                let exp = r.as_f64().unwrap_or(0.0);
                let result = base.powf(exp);
                Ok(Value::Number(serde_json::Number::from_f64(result).unwrap_or(0.into())))
            }
            _ => Err(anyhow!("Cannot raise {:?} to power of {:?}", left, right)),
        }
    }

    fn eval_negate(&self, a: &Expression, context: &Context) -> Result<Value> {
        let val = a.evaluate(context)?;
        
        match val {
            Value::Number(n) => {
                let result = -n.as_f64().unwrap_or(0.0);
                Ok(Value::Number(serde_json::Number::from_f64(result).unwrap_or(0.into())))
            }
            _ => Err(anyhow!("Cannot negate {:?}", val)),
        }
    }

    // Comparison operations
    fn eval_eq(&self, a: &Expression, b: &Expression, context: &Context) -> Result<Value> {
        let left = a.evaluate(context)?;
        let right = b.evaluate(context)?;
        Ok(Value::Bool(Self::json_equals(&left, &right)))
    }

    fn eval_ne(&self, a: &Expression, b: &Expression, context: &Context) -> Result<Value> {
        let left = a.evaluate(context)?;
        let right = b.evaluate(context)?;
        Ok(Value::Bool(!Self::json_equals(&left, &right)))
    }

    fn eval_lt(&self, a: &Expression, b: &Expression, context: &Context) -> Result<Value> {
        let left = a.evaluate(context)?;
        let right = b.evaluate(context)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                Ok(Value::Bool(l.as_f64().unwrap_or(0.0) < r.as_f64().unwrap_or(0.0)))
            }
            (Value::String(l), Value::String(r)) => Ok(Value::Bool(l < r)),
            _ => Ok(Value::Bool(false)),
        }
    }

    fn eval_le(&self, a: &Expression, b: &Expression, context: &Context) -> Result<Value> {
        let left = a.evaluate(context)?;
        let right = b.evaluate(context)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                Ok(Value::Bool(l.as_f64().unwrap_or(0.0) <= r.as_f64().unwrap_or(0.0)))
            }
            (Value::String(l), Value::String(r)) => Ok(Value::Bool(l <= r)),
            _ => Ok(Value::Bool(false)),
        }
    }

    fn eval_gt(&self, a: &Expression, b: &Expression, context: &Context) -> Result<Value> {
        let left = a.evaluate(context)?;
        let right = b.evaluate(context)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                Ok(Value::Bool(l.as_f64().unwrap_or(0.0) > r.as_f64().unwrap_or(0.0)))
            }
            (Value::String(l), Value::String(r)) => Ok(Value::Bool(l > r)),
            _ => Ok(Value::Bool(false)),
        }
    }

    fn eval_ge(&self, a: &Expression, b: &Expression, context: &Context) -> Result<Value> {
        let left = a.evaluate(context)?;
        let right = b.evaluate(context)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                Ok(Value::Bool(l.as_f64().unwrap_or(0.0) >= r.as_f64().unwrap_or(0.0)))
            }
            (Value::String(l), Value::String(r)) => Ok(Value::Bool(l >= r)),
            _ => Ok(Value::Bool(false)),
        }
    }

    // Logical operations
    fn eval_and(&self, a: &Expression, b: &Expression, context: &Context) -> Result<Value> {
        let left = a.evaluate(context)?;
        
        // Short-circuit evaluation
        if !Self::is_truthy(&left) {
            return Ok(Value::Bool(false));
        }
        
        let right = b.evaluate(context)?;
        Ok(Value::Bool(Self::is_truthy(&right)))
    }

    fn eval_or(&self, a: &Expression, b: &Expression, context: &Context) -> Result<Value> {
        let left = a.evaluate(context)?;
        
        // Short-circuit evaluation
        if Self::is_truthy(&left) {
            return Ok(Value::Bool(true));
        }
        
        let right = b.evaluate(context)?;
        Ok(Value::Bool(Self::is_truthy(&right)))
    }

    fn eval_not(&self, a: &Expression, context: &Context) -> Result<Value> {
        let val = a.evaluate(context)?;
        Ok(Value::Bool(!Self::is_truthy(&val)))
    }

    // String operations
    fn eval_concat(&self, exprs: &[Expression], context: &Context) -> Result<Value> {
        let mut result = String::new();
        
        for expr in exprs {
            let val = expr.evaluate(context)?;
            match val {
                Value::String(s) => result.push_str(&s),
                Value::Number(n) => result.push_str(&n.to_string()),
                Value::Bool(b) => result.push_str(&b.to_string()),
                Value::Null => {} // Skip nulls
                other => result.push_str(&other.to_string()),
            }
        }
        
        Ok(Value::String(result))
    }

    fn eval_contains(&self, string: &Expression, substring: &Expression, context: &Context) -> Result<Value> {
        let str_val = string.evaluate(context)?;
        let sub_val = substring.evaluate(context)?;
        
        match (&str_val, &sub_val) {
            (Value::String(s), Value::String(sub)) => Ok(Value::Bool(s.contains(sub))),
            _ => Ok(Value::Bool(false)),
        }
    }

    fn eval_starts_with(&self, string: &Expression, prefix: &Expression, context: &Context) -> Result<Value> {
        let str_val = string.evaluate(context)?;
        let pre_val = prefix.evaluate(context)?;
        
        match (&str_val, &pre_val) {
            (Value::String(s), Value::String(p)) => Ok(Value::Bool(s.starts_with(p))),
            _ => Ok(Value::Bool(false)),
        }
    }

    fn eval_ends_with(&self, string: &Expression, suffix: &Expression, context: &Context) -> Result<Value> {
        let str_val = string.evaluate(context)?;
        let suf_val = suffix.evaluate(context)?;
        
        match (&str_val, &suf_val) {
            (Value::String(s), Value::String(x)) => Ok(Value::Bool(s.ends_with(x))),
            _ => Ok(Value::Bool(false)),
        }
    }

    // Type checking
    fn eval_is_null(&self, a: &Expression, context: &Context) -> Result<Value> {
        let val = a.evaluate(context)?;
        Ok(Value::Bool(matches!(val, Value::Null)))
    }

    fn eval_is_array(&self, a: &Expression, context: &Context) -> Result<Value> {
        let val = a.evaluate(context)?;
        Ok(Value::Bool(matches!(val, Value::Array(_))))
    }

    fn eval_is_object(&self, a: &Expression, context: &Context) -> Result<Value> {
        let val = a.evaluate(context)?;
        Ok(Value::Bool(matches!(val, Value::Object(_))))
    }

    fn eval_is_string(&self, a: &Expression, context: &Context) -> Result<Value> {
        let val = a.evaluate(context)?;
        Ok(Value::Bool(matches!(val, Value::String(_))))
    }

    fn eval_is_number(&self, a: &Expression, context: &Context) -> Result<Value> {
        let val = a.evaluate(context)?;
        Ok(Value::Bool(matches!(val, Value::Number(_))))
    }

    fn eval_is_boolean(&self, a: &Expression, context: &Context) -> Result<Value> {
        let val = a.evaluate(context)?;
        Ok(Value::Bool(matches!(val, Value::Bool(_))))
    }

    // Conditional
    fn eval_if(&self, condition: &Expression, then_branch: &Expression, else_branch: &Expression, context: &Context) -> Result<Value> {
        let cond_val = condition.evaluate(context)?;
        
        if Self::is_truthy(&cond_val) {
            then_branch.evaluate(context)
        } else {
            else_branch.evaluate(context)
        }
    }

    // Let binding
    fn eval_let(&self, bindings: &HashMap<String, Expression>, body: &Expression, context: &Context) -> Result<Value> {
        let mut new_context = context.child();
        
        for (name, expr) in bindings {
            let value = expr.evaluate(context)?;
            new_context.set(name.clone(), value);
        }
        
        body.evaluate(&new_context)
    }

    // Let binding with registry
    fn eval_let_with_registry(&self, bindings: &HashMap<String, Expression>, body: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let mut new_context = context.child();
        
        for (name, expr) in bindings {
            let value = expr.evaluate_with_registry(context, registry)?;
            new_context.set(name.clone(), value);
        }
        
        body.evaluate_with_registry(&new_context, registry)
    }

    // Map implementation
    fn eval_map(&self, array: &Expression, function: &Expression, context: &Context) -> Result<Value> {
        let arr_val = array.evaluate(context)?;
        
        match arr_val {
            Value::Array(items) => {
                let results: Result<Vec<Value>> = items.iter().enumerate().map(|(i, item)| {
                    let mut item_context = context.child();
                    item_context.set("$".to_string(), item.clone());
                    item_context.set("$i".to_string(), Value::Number((i as i64).into()));
                    
                    // If function is a Lambda, bind parameters
                    if let Expression::Lambda { params, body } = function {
                        if let Some(param) = params.first() {
                            item_context.set(param.clone(), item.clone());
                        }
                        body.evaluate(&item_context)
                    } else {
                        function.evaluate(&item_context)
                    }
                }).collect();
                
                Ok(Value::Array(results?))
            }
            _ => Ok(Value::Array(vec![])),
        }
    }

    // Map with registry
    fn eval_map_with_registry(&self, array: &Expression, function: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let arr_val = array.evaluate_with_registry(context, registry)?;
        
        match arr_val {
            Value::Array(items) => {
                let results: Result<Vec<Value>> = items.iter().enumerate().map(|(i, item)| {
                    let mut item_context = context.child();
                    item_context.set("$".to_string(), item.clone());
                    item_context.set("$i".to_string(), Value::Number((i as i64).into()));
                    
                    // If function is a Lambda, bind parameters
                    if let Expression::Lambda { params, body } = function {
                        if let Some(param) = params.first() {
                            item_context.set(param.clone(), item.clone());
                        }
                        body.evaluate_with_registry(&item_context, registry)
                    } else {
                        function.evaluate_with_registry(&item_context, registry)
                    }
                }).collect();
                
                Ok(Value::Array(results?))
            }
            _ => Ok(Value::Array(vec![])),
        }
    }

    // Filter implementation
    fn eval_filter(&self, array: &Expression, predicate: &Expression, context: &Context) -> Result<Value> {
        let arr_val = array.evaluate(context)?;
        
        match arr_val {
            Value::Array(items) => {
                let mut results = Vec::new();
                for (i, item) in items.iter().enumerate() {
                    let mut item_context = context.child();
                    item_context.set("$".to_string(), item.clone());
                    item_context.set("$i".to_string(), Value::Number((i as i64).into()));
                    
                    let pred_val = if let Expression::Lambda { params, body } = predicate {
                        if let Some(param) = params.first() {
                            item_context.set(param.clone(), item.clone());
                        }
                        body.evaluate(&item_context)?
                    } else {
                        predicate.evaluate(&item_context)?
                    };
                    
                    if Self::is_truthy(&pred_val) {
                        results.push(item.clone());
                    }
                }
                Ok(Value::Array(results))
            }
            _ => Ok(Value::Array(vec![])),
        }
    }

    // Filter with registry
    fn eval_filter_with_registry(&self, array: &Expression, predicate: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let arr_val = array.evaluate_with_registry(context, registry)?;
        
        match arr_val {
            Value::Array(items) => {
                let mut results = Vec::new();
                for (i, item) in items.iter().enumerate() {
                    let mut item_context = context.child();
                    item_context.set("$".to_string(), item.clone());
                    item_context.set("$i".to_string(), Value::Number((i as i64).into()));
                    
                    let pred_val = if let Expression::Lambda { params, body } = predicate {
                        if let Some(param) = params.first() {
                            item_context.set(param.clone(), item.clone());
                        }
                        body.evaluate_with_registry(&item_context, registry)?
                    } else {
                        predicate.evaluate_with_registry(&item_context, registry)?
                    };
                    
                    if Self::is_truthy(&pred_val) {
                        results.push(item.clone());
                    }
                }
                Ok(Value::Array(results))
            }
            _ => Ok(Value::Array(vec![])),
        }
    }

    // Reduce implementation
    fn eval_reduce(&self, array: &Expression, function: &Expression, initial: &Expression, context: &Context) -> Result<Value> {
        let arr_val = array.evaluate(context)?;
        let mut acc = initial.evaluate(context)?;
        
        match arr_val {
            Value::Array(items) => {
                for (i, item) in items.iter().enumerate() {
                    let mut item_context = context.child();
                    item_context.set("$acc".to_string(), acc.clone());
                    item_context.set("$".to_string(), item.clone());
                    item_context.set("$i".to_string(), Value::Number((i as i64).into()));
                    
                    acc = if let Expression::Lambda { params, body } = function {
                        // Bind accumulator and current item
                        if let Some(p) = params.get(0) {
                            item_context.set(p.clone(), acc.clone());
                        }
                        if let Some(p) = params.get(1) {
                            item_context.set(p.clone(), item.clone());
                        }
                        body.evaluate(&item_context)?
                    } else {
                        function.evaluate(&item_context)?
                    };
                }
                Ok(acc)
            }
            _ => Ok(acc),
        }
    }

    // Reduce with registry
    fn eval_reduce_with_registry(&self, array: &Expression, function: &Expression, initial: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let arr_val = array.evaluate_with_registry(context, registry)?;
        let mut acc = initial.evaluate_with_registry(context, registry)?;
        
        match arr_val {
            Value::Array(items) => {
                for (i, item) in items.iter().enumerate() {
                    let mut item_context = context.child();
                    item_context.set("$acc".to_string(), acc.clone());
                    item_context.set("$".to_string(), item.clone());
                    item_context.set("$i".to_string(), Value::Number((i as i64).into()));
                    
                    acc = if let Expression::Lambda { params, body } = function {
                        if let Some(p) = params.get(0) {
                            item_context.set(p.clone(), acc.clone());
                        }
                        if let Some(p) = params.get(1) {
                            item_context.set(p.clone(), item.clone());
                        }
                        body.evaluate_with_registry(&item_context, registry)?
                    } else {
                        function.evaluate_with_registry(&item_context, registry)?
                    };
                }
                Ok(acc)
            }
            _ => Ok(acc),
        }
    }

    // Helper: Deep equality comparison for JSON values
    fn json_equals(a: &Value, b: &Value) -> bool {
        match (a, b) {
            (Value::Null, Value::Null) => true,
            (Value::Bool(a), Value::Bool(b)) => a == b,
            (Value::Number(a), Value::Number(b)) => {
                // Compare as floats to handle integer/float equality
                let af = a.as_f64().unwrap_or(f64::NAN);
                let bf = b.as_f64().unwrap_or(f64::NAN);
                af == bf
            }
            (Value::String(a), Value::String(b)) => a == b,
            (Value::Array(a), Value::Array(b)) => {
                if a.len() != b.len() {
                    return false;
                }
                a.iter().zip(b.iter()).all(|(x, y)| Self::json_equals(x, y))
            }
            (Value::Object(a), Value::Object(b)) => {
                if a.len() != b.len() {
                    return false;
                }
                a.iter().all(|(key, val)| {
                    b.get(key).map(|bval| Self::json_equals(val, bval)).unwrap_or(false)
                })
            }
            _ => false,
        }
    }

    /// Helper: Check if a value is truthy
    /// - false, null, 0, "", [] are falsy
    /// - Everything else is truthy
    pub fn is_truthy(value: &Value) -> bool {
        match value {
            Value::Null => false,
            Value::Bool(b) => *b,
            Value::Number(n) => n.as_f64().map(|f| f != 0.0).unwrap_or(false),
            Value::String(s) => !s.is_empty(),
            Value::Array(a) => !a.is_empty(),
            Value::Object(o) => !o.is_empty(),
        }
    }
    // Registry-aware helper functions for evaluate_with_registry
    
    fn eval_field_access_with_registry(&self, object: &Expression, field: &str, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let obj_val = object.evaluate_with_registry(context, registry)?;
        
        let fields: Vec<&str> = field.split('.').collect();
        let mut current = obj_val;
        for field_name in &fields {
            match current {
                Value::Object(map) => {
                    current = map.get(*field_name).cloned().unwrap_or(Value::Null);
                }
                _ => return Ok(Value::Null),
            }
        }
        Ok(current)
    }

    fn eval_index_access_with_registry(&self, array: &Expression, index: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let arr_val = array.evaluate_with_registry(context, registry)?;
        let idx_val = index.evaluate_with_registry(context, registry)?;
        
        match (&arr_val, &idx_val) {
            (Value::Array(arr), Value::Number(n)) => {
                let idx = n.as_i64().unwrap_or(0) as isize;
                let len = arr.len() as isize;
                let actual_idx = if idx < 0 { len + idx } else { idx };
                
                if actual_idx >= 0 && actual_idx < len {
                    Ok(arr[actual_idx as usize].clone())
                } else {
                    Ok(Value::Null)
                }
            }
            _ => Ok(Value::Null),
        }
    }

    fn eval_add_with_registry(&self, a: &Expression, b: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let left = a.evaluate_with_registry(context, registry)?;
        let right = b.evaluate_with_registry(context, registry)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                let result = l.as_f64().unwrap_or(0.0) + r.as_f64().unwrap_or(0.0);
                Ok(Value::Number(serde_json::Number::from_f64(result).unwrap_or(0.into())))
            }
            (Value::String(l), Value::String(r)) => Ok(Value::String(format!("{}{}", l, r))),
            (Value::Array(l), Value::Array(r)) => {
                let mut result = l.clone();
                result.extend(r.clone());
                Ok(Value::Array(result))
            }
            _ => Err(anyhow!("Cannot add {:?} and {:?}", left, right)),
        }
    }

    fn eval_subtract_with_registry(&self, a: &Expression, b: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let left = a.evaluate_with_registry(context, registry)?;
        let right = b.evaluate_with_registry(context, registry)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                let result = l.as_f64().unwrap_or(0.0) - r.as_f64().unwrap_or(0.0);
                Ok(Value::Number(serde_json::Number::from_f64(result).unwrap_or(0.into())))
            }
            _ => Err(anyhow!("Cannot subtract {:?} from {:?}", right, left)),
        }
    }

    fn eval_multiply_with_registry(&self, a: &Expression, b: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let left = a.evaluate_with_registry(context, registry)?;
        let right = b.evaluate_with_registry(context, registry)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                let result = l.as_f64().unwrap_or(0.0) * r.as_f64().unwrap_or(0.0);
                Ok(Value::Number(serde_json::Number::from_f64(result).unwrap_or(0.into())))
            }
            _ => Err(anyhow!("Cannot multiply {:?} and {:?}", left, right)),
        }
    }

    fn eval_divide_with_registry(&self, a: &Expression, b: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let left = a.evaluate_with_registry(context, registry)?;
        let right = b.evaluate_with_registry(context, registry)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                let divisor = r.as_f64().unwrap_or(0.0);
                if divisor == 0.0 {
                    return Err(anyhow!("Division by zero"));
                }
                let result = l.as_f64().unwrap_or(0.0) / divisor;
                Ok(Value::Number(serde_json::Number::from_f64(result).unwrap_or(0.into())))
            }
            _ => Err(anyhow!("Cannot divide {:?} by {:?}", left, right)),
        }
    }

    fn eval_modulo_with_registry(&self, a: &Expression, b: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let left = a.evaluate_with_registry(context, registry)?;
        let right = b.evaluate_with_registry(context, registry)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                let result = l.as_f64().unwrap_or(0.0) % r.as_f64().unwrap_or(0.0);
                Ok(Value::Number(serde_json::Number::from_f64(result).unwrap_or(0.into())))
            }
            _ => Err(anyhow!("Cannot compute modulo of {:?} and {:?}", left, right)),
        }
    }

    fn eval_power_with_registry(&self, a: &Expression, b: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let left = a.evaluate_with_registry(context, registry)?;
        let right = b.evaluate_with_registry(context, registry)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                let result = l.as_f64().unwrap_or(0.0).powf(r.as_f64().unwrap_or(0.0));
                Ok(Value::Number(serde_json::Number::from_f64(result).unwrap_or(0.into())))
            }
            _ => Err(anyhow!("Cannot raise {:?} to power {:?}", left, right)),
        }
    }

    fn eval_negate_with_registry(&self, a: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let val = a.evaluate_with_registry(context, registry)?;
        
        match &val {
            Value::Number(n) => {
                let result = -n.as_f64().unwrap_or(0.0);
                Ok(Value::Number(serde_json::Number::from_f64(result).unwrap_or(0.into())))
            }
            _ => Err(anyhow!("Cannot negate {:?}", val)),
        }
    }

    fn eval_eq_with_registry(&self, a: &Expression, b: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let left = a.evaluate_with_registry(context, registry)?;
        let right = b.evaluate_with_registry(context, registry)?;
        Ok(Value::Bool(Self::json_equals(&left, &right)))
    }

    fn eval_ne_with_registry(&self, a: &Expression, b: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let left = a.evaluate_with_registry(context, registry)?;
        let right = b.evaluate_with_registry(context, registry)?;
        Ok(Value::Bool(!Self::json_equals(&left, &right)))
    }

    fn eval_lt_with_registry(&self, a: &Expression, b: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let left = a.evaluate_with_registry(context, registry)?;
        let right = b.evaluate_with_registry(context, registry)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                Ok(Value::Bool(l.as_f64().unwrap_or(0.0) < r.as_f64().unwrap_or(0.0)))
            }
            (Value::String(l), Value::String(r)) => Ok(Value::Bool(l < r)),
            _ => Ok(Value::Bool(false)),
        }
    }

    fn eval_le_with_registry(&self, a: &Expression, b: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let left = a.evaluate_with_registry(context, registry)?;
        let right = b.evaluate_with_registry(context, registry)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                Ok(Value::Bool(l.as_f64().unwrap_or(0.0) <= r.as_f64().unwrap_or(0.0)))
            }
            (Value::String(l), Value::String(r)) => Ok(Value::Bool(l <= r)),
            _ => Ok(Value::Bool(false)),
        }
    }

    fn eval_gt_with_registry(&self, a: &Expression, b: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let left = a.evaluate_with_registry(context, registry)?;
        let right = b.evaluate_with_registry(context, registry)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                Ok(Value::Bool(l.as_f64().unwrap_or(0.0) > r.as_f64().unwrap_or(0.0)))
            }
            (Value::String(l), Value::String(r)) => Ok(Value::Bool(l > r)),
            _ => Ok(Value::Bool(false)),
        }
    }

    fn eval_ge_with_registry(&self, a: &Expression, b: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let left = a.evaluate_with_registry(context, registry)?;
        let right = b.evaluate_with_registry(context, registry)?;
        
        match (&left, &right) {
            (Value::Number(l), Value::Number(r)) => {
                Ok(Value::Bool(l.as_f64().unwrap_or(0.0) >= r.as_f64().unwrap_or(0.0)))
            }
            (Value::String(l), Value::String(r)) => Ok(Value::Bool(l >= r)),
            _ => Ok(Value::Bool(false)),
        }
    }

    fn eval_and_with_registry(&self, a: &Expression, b: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let left = a.evaluate_with_registry(context, registry)?;
        
        match left {
            Value::Bool(false) => Ok(Value::Bool(false)),
            Value::Bool(true) => {
                let right = b.evaluate_with_registry(context, registry)?;
                match right {
                    Value::Bool(b) => Ok(Value::Bool(b)),
                    _ => Err(anyhow!("Right side of AND must be boolean")),
                }
            }
            _ => Err(anyhow!("Left side of AND must be boolean")),
        }
    }

    fn eval_or_with_registry(&self, a: &Expression, b: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let left = a.evaluate_with_registry(context, registry)?;
        
        match left {
            Value::Bool(true) => Ok(Value::Bool(true)),
            Value::Bool(false) => {
                let right = b.evaluate_with_registry(context, registry)?;
                match right {
                    Value::Bool(b) => Ok(Value::Bool(b)),
                    _ => Err(anyhow!("Right side of OR must be boolean")),
                }
            }
            _ => Err(anyhow!("Left side of OR must be boolean")),
        }
    }

    fn eval_not_with_registry(&self, a: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let val = a.evaluate_with_registry(context, registry)?;
        
        match val {
            Value::Bool(b) => Ok(Value::Bool(!b)),
            _ => Err(anyhow!("NOT requires boolean operand")),
        }
    }

    fn eval_concat_with_registry(&self, exprs: &[Expression], context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let mut result = String::new();
        
        for expr in exprs {
            let val = expr.evaluate_with_registry(context, registry)?;
            match val {
                Value::String(s) => result.push_str(&s),
                Value::Number(n) => result.push_str(&n.to_string()),
                Value::Bool(b) => result.push_str(&b.to_string()),
                Value::Null => {}
                _ => result.push_str(&val.to_string()),
            }
        }
        
        Ok(Value::String(result))
    }

    fn eval_contains_with_registry(&self, string: &Expression, substring: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let str_val = string.evaluate_with_registry(context, registry)?;
        let sub_val = substring.evaluate_with_registry(context, registry)?;
        
        match (&str_val, &sub_val) {
            (Value::String(s), Value::String(sub)) => Ok(Value::Bool(s.contains(sub))),
            _ => Ok(Value::Bool(false)),
        }
    }

    fn eval_starts_with_with_registry(&self, string: &Expression, prefix: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let str_val = string.evaluate_with_registry(context, registry)?;
        let pre_val = prefix.evaluate_with_registry(context, registry)?;
        
        match (&str_val, &pre_val) {
            (Value::String(s), Value::String(p)) => Ok(Value::Bool(s.starts_with(p))),
            _ => Ok(Value::Bool(false)),
        }
    }

    fn eval_ends_with_with_registry(&self, string: &Expression, suffix: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let str_val = string.evaluate_with_registry(context, registry)?;
        let suf_val = suffix.evaluate_with_registry(context, registry)?;
        
        match (&str_val, &suf_val) {
            (Value::String(s), Value::String(x)) => Ok(Value::Bool(s.ends_with(x))),
            _ => Ok(Value::Bool(false)),
        }
    }

    fn eval_is_null_with_registry(&self, a: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let val = a.evaluate_with_registry(context, registry)?;
        Ok(Value::Bool(matches!(val, Value::Null)))
    }

    fn eval_is_array_with_registry(&self, a: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let val = a.evaluate_with_registry(context, registry)?;
        Ok(Value::Bool(matches!(val, Value::Array(_))))
    }

    fn eval_is_object_with_registry(&self, a: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let val = a.evaluate_with_registry(context, registry)?;
        Ok(Value::Bool(matches!(val, Value::Object(_))))
    }

    fn eval_is_string_with_registry(&self, a: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let val = a.evaluate_with_registry(context, registry)?;
        Ok(Value::Bool(matches!(val, Value::String(_))))
    }

    fn eval_is_number_with_registry(&self, a: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let val = a.evaluate_with_registry(context, registry)?;
        Ok(Value::Bool(matches!(val, Value::Number(_))))
    }

    fn eval_is_boolean_with_registry(&self, a: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let val = a.evaluate_with_registry(context, registry)?;
        Ok(Value::Bool(matches!(val, Value::Bool(_))))
    }

    fn eval_if_with_registry(&self, condition: &Expression, then_branch: &Expression, else_branch: &Expression, context: &Context, registry: &FunctionRegistry) -> Result<Value> {
        let cond_val = condition.evaluate_with_registry(context, registry)?;
        
        match cond_val {
            Value::Bool(true) => then_branch.evaluate_with_registry(context, registry),
            Value::Bool(false) => else_branch.evaluate_with_registry(context, registry),
            _ => Err(anyhow!("IF condition must be boolean")),
        }
    }
}

/// Parse a simple string expression into an Expression
/// This handles basic field paths like "a.b.c" or simple variable names
pub fn parse_simple_expression(expr: &str) -> Expression {
    let expr = expr.trim();
    
    // Check if it's a numeric literal
    if let Ok(n) = expr.parse::<i64>() {
        return Expression::Literal(Value::Number(n.into()));
    }
    if let Ok(n) = expr.parse::<f64>() {
        if let Some(num) = serde_json::Number::from_f64(n) {
            return Expression::Literal(Value::Number(num));
        }
    }
    
    // Check if it's a string literal (quoted)
    if (expr.starts_with('"') && expr.ends_with('"')) ||
       (expr.starts_with('\'') && expr.ends_with('\'')) {
        let content = &expr[1..expr.len()-1];
        return Expression::Literal(Value::String(content.to_string()));
    }
    
    // Check if it's a boolean literal
    if expr == "true" {
        return Expression::Literal(Value::Bool(true));
    }
    if expr == "false" {
        return Expression::Literal(Value::Bool(false));
    }
    
    // Check if it's null
    if expr == "null" {
        return Expression::Literal(Value::Null);
    }
    
    // Otherwise, treat as a variable/field reference
    Expression::Var(expr.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_context() -> Context {
        let mut ctx = Context::new();
        ctx.set("x".to_string(), Value::Number(10.into()));
        ctx.set("y".to_string(), Value::Number(5.into()));
        ctx.set("name".to_string(), Value::String("test".to_string()));
        ctx.set("items".to_string(), Value::Array(vec![
            Value::Number(1.into()),
            Value::Number(2.into()),
            Value::Number(3.into()),
        ]));
        ctx
    }

    // Helper to compare numbers (handles float vs int equality)
    fn assert_number_eq(actual: Value, expected: i64) {
        match actual {
            Value::Number(n) => {
                let actual_f = n.as_f64().unwrap_or(f64::NAN);
                let expected_f = expected as f64;
                assert!((actual_f - expected_f).abs() < f64::EPSILON,
                    "Expected {} but got {}", expected, actual_f);
            }
            _ => panic!("Expected number but got {:?}", actual),
        }
    }

    #[test]
    fn test_literal() {
        let ctx = Context::new();
        let expr = Expression::Literal(Value::Number(42.into()));
        assert_eq!(expr.evaluate(&ctx).unwrap(), Value::Number(42.into()));
    }

    #[test]
    fn test_variable() {
        let ctx = test_context();
        let expr = Expression::Var("x".to_string());
        assert_eq!(expr.evaluate(&ctx).unwrap(), Value::Number(10.into()));
    }

    #[test]
    fn test_arithmetic() {
        let ctx = test_context();
        
        // x + y = 15
        let expr = Expression::Add(
            Box::new(Expression::Var("x".to_string())),
            Box::new(Expression::Var("y".to_string())),
        );
        let result = expr.evaluate(&ctx).unwrap();
        assert_number_eq(result, 15);
        
        // x - y = 5
        let expr = Expression::Subtract(
            Box::new(Expression::Var("x".to_string())),
            Box::new(Expression::Var("y".to_string())),
        );
        let result = expr.evaluate(&ctx).unwrap();
        assert_number_eq(result, 5);
        
        // x * y = 50
        let expr = Expression::Multiply(
            Box::new(Expression::Var("x".to_string())),
            Box::new(Expression::Var("y".to_string())),
        );
        let result = expr.evaluate(&ctx).unwrap();
        assert_number_eq(result, 50);
        
        // x / y = 2
        let expr = Expression::Divide(
            Box::new(Expression::Var("x".to_string())),
            Box::new(Expression::Var("y".to_string())),
        );
        let result = expr.evaluate(&ctx).unwrap();
        assert_number_eq(result, 2);
    }

    #[test]
    fn test_comparison() {
        let ctx = test_context();
        
        // x > y = true
        let expr = Expression::Gt(
            Box::new(Expression::Var("x".to_string())),
            Box::new(Expression::Var("y".to_string())),
        );
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result, Value::Bool(true));
        
        // x < y = false
        let expr = Expression::Lt(
            Box::new(Expression::Var("x".to_string())),
            Box::new(Expression::Var("y".to_string())),
        );
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result, Value::Bool(false));
        
        // x = 10 = true
        let expr = Expression::Eq(
            Box::new(Expression::Var("x".to_string())),
            Box::new(Expression::Literal(Value::Number(10.into()))),
        );
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result, Value::Bool(true));
    }

    #[test]
    fn test_logical() {
        let ctx = test_context();
        
        // x > 5 and y < 10 = true
        let expr = Expression::And(
            Box::new(Expression::Gt(
                Box::new(Expression::Var("x".to_string())),
                Box::new(Expression::Literal(Value::Number(5.into()))),
            )),
            Box::new(Expression::Lt(
                Box::new(Expression::Var("y".to_string())),
                Box::new(Expression::Literal(Value::Number(10.into()))),
            )),
        );
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result, Value::Bool(true));
        
        // not false = true
        let expr = Expression::Not(Box::new(Expression::Literal(Value::Bool(false))));
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result, Value::Bool(true));
    }

    #[test]
    fn test_short_circuit() {
        let ctx = Context::new();
        
        // false and (should_not_evaluate) = false
        // If short-circuit works, the undefined variable won't cause an error
        let expr = Expression::And(
            Box::new(Expression::Literal(Value::Bool(false))),
            Box::new(Expression::Var("undefined_var".to_string())),
        );
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result, Value::Bool(false));
        
        // true or (should_not_evaluate) = true
        let expr = Expression::Or(
            Box::new(Expression::Literal(Value::Bool(true))),
            Box::new(Expression::Var("undefined_var".to_string())),
        );
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result, Value::Bool(true));
    }

    #[test]
    fn test_conditional() {
        let ctx = test_context();
        
        // if x > 5 then "big" else "small" = "big"
        let expr = Expression::If {
            condition: Box::new(Expression::Gt(
                Box::new(Expression::Var("x".to_string())),
                Box::new(Expression::Literal(Value::Number(5.into()))),
            )),
            then_branch: Box::new(Expression::Literal(Value::String("big".to_string()))),
            else_branch: Box::new(Expression::Literal(Value::String("small".to_string()))),
        };
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result, Value::String("big".to_string()));
    }

    #[test]
    fn test_string_concat() {
        let ctx = test_context();
        
        // "Hello" & " " & "World" = "Hello World"
        let expr = Expression::Concat(vec![
            Expression::Literal(Value::String("Hello".to_string())),
            Expression::Literal(Value::String(" ".to_string())),
            Expression::Literal(Value::String("World".to_string())),
        ]);
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result, Value::String("Hello World".to_string()));
    }

    #[test]
    fn test_contains() {
        let ctx = Context::new();
        
        let expr = Expression::Contains {
            string: Box::new(Expression::Literal(Value::String("hello world".to_string()))),
            substring: Box::new(Expression::Literal(Value::String("world".to_string()))),
        };
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result, Value::Bool(true));
        
        let expr = Expression::Contains {
            string: Box::new(Expression::Literal(Value::String("hello world".to_string()))),
            substring: Box::new(Expression::Literal(Value::String("foo".to_string()))),
        };
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result, Value::Bool(false));
    }

    #[test]
    fn test_type_checking() {
        let ctx = Context::new();
        
        // is_number(42) = true
        let expr = Expression::IsNumber(Box::new(Expression::Literal(Value::Number(42.into()))));
        assert_eq!(expr.evaluate(&ctx).unwrap(), Value::Bool(true));
        
        // is_string("test") = true
        let expr = Expression::IsString(Box::new(Expression::Literal(Value::String("test".to_string()))));
        assert_eq!(expr.evaluate(&ctx).unwrap(), Value::Bool(true));
        
        // is_array([1,2,3]) = true
        let expr = Expression::IsArray(Box::new(Expression::Literal(Value::Array(vec![
            Value::Number(1.into()),
        ]))));
        assert_eq!(expr.evaluate(&ctx).unwrap(), Value::Bool(true));
        
        // is_null(null) = true
        let expr = Expression::IsNull(Box::new(Expression::Literal(Value::Null)));
        assert_eq!(expr.evaluate(&ctx).unwrap(), Value::Bool(true));
    }

    #[test]
    fn test_field_access() {
        let mut ctx = Context::new();
        let mut obj = serde_json::Map::new();
        obj.insert("name".to_string(), Value::String("John".to_string()));
        obj.insert("age".to_string(), Value::Number(30.into()));
        ctx.set("person".to_string(), Value::Object(obj));
        
        // person.name = "John"
        let expr = Expression::FieldAccess {
            object: Box::new(Expression::Var("person".to_string())),
            field: "name".to_string(),
        };
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result, Value::String("John".to_string()));
    }

    #[test]
    fn test_index_access() {
        let ctx = test_context();
        
        // items[0] = 1
        let expr = Expression::IndexAccess {
            array: Box::new(Expression::Var("items".to_string())),
            index: Box::new(Expression::Literal(Value::Number(0.into()))),
        };
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result, Value::Number(1.into()));
        
        // items[-1] = 3 (last element)
        let expr = Expression::IndexAccess {
            array: Box::new(Expression::Var("items".to_string())),
            index: Box::new(Expression::Literal(Value::Number((-1).into()))),
        };
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result, Value::Number(3.into()));
    }

    #[test]
    fn test_parse_simple_expression() {
        // Numbers
        let expr = parse_simple_expression("42");
        assert!(matches!(expr, Expression::Literal(Value::Number(_))));
        
        // Strings
        let expr = parse_simple_expression("\"hello\"");
        assert!(matches!(expr, Expression::Literal(Value::String(s)) if s == "hello"));
        
        // Booleans
        let expr = parse_simple_expression("true");
        assert!(matches!(expr, Expression::Literal(Value::Bool(true))));
        
        // Null
        let expr = parse_simple_expression("null");
        assert!(matches!(expr, Expression::Literal(Value::Null)));
        
        // Variables
        let expr = parse_simple_expression("foo.bar");
        assert!(matches!(expr, Expression::Var(s) if s == "foo.bar"));
    }

    #[test]
    fn test_map() {
        let mut ctx = Context::new();
        ctx.set("numbers".to_string(), Value::Array(vec![
            Value::Number(1.into()),
            Value::Number(2.into()),
            Value::Number(3.into()),
        ]));
        
        // Map: multiply each by 2
        let expr = Expression::Map {
            array: Box::new(Expression::Var("numbers".to_string())),
            function: Box::new(Expression::Multiply(
                Box::new(Expression::Var("$".to_string())),
                Box::new(Expression::Literal(Value::Number(2.into()))),
            )),
        };
        
        let result = expr.evaluate(&ctx).unwrap();
        if let Value::Array(arr) = result {
            assert_eq!(arr.len(), 3);
            assert_eq!(arr[0].as_f64(), Some(2.0));
            assert_eq!(arr[1].as_f64(), Some(4.0));
            assert_eq!(arr[2].as_f64(), Some(6.0));
        } else {
            panic!("Expected array");
        }
    }

    #[test]
    fn test_filter() {
        let mut ctx = Context::new();
        ctx.set("numbers".to_string(), Value::Array(vec![
            Value::Number(1.into()),
            Value::Number(5.into()),
            Value::Number(2.into()),
            Value::Number(8.into()),
        ]));
        
        // Filter: keep elements > 3
        let expr = Expression::Filter {
            array: Box::new(Expression::Var("numbers".to_string())),
            predicate: Box::new(Expression::Gt(
                Box::new(Expression::Var("$".to_string())),
                Box::new(Expression::Literal(Value::Number(3.into()))),
            )),
        };
        
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result, Value::Array(vec![
            Value::Number(5.into()),
            Value::Number(8.into()),
        ]));
    }

    #[test]
    fn test_reduce() {
        let mut ctx = Context::new();
        ctx.set("numbers".to_string(), Value::Array(vec![
            Value::Number(1.into()),
            Value::Number(2.into()),
            Value::Number(3.into()),
        ]));
        
        // Reduce: sum all elements
        let expr = Expression::Reduce {
            array: Box::new(Expression::Var("numbers".to_string())),
            function: Box::new(Expression::Add(
                Box::new(Expression::Var("$acc".to_string())),
                Box::new(Expression::Var("$".to_string())),
            )),
            initial: Box::new(Expression::Literal(Value::Number(0.into()))),
        };
        
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result.as_f64(), Some(6.0));
    }

    #[test]
    fn test_lambda() {
        let mut ctx = Context::new();
        ctx.set("numbers".to_string(), Value::Array(vec![
            Value::Number(1.into()),
            Value::Number(2.into()),
            Value::Number(3.into()),
        ]));
        
        // Map with lambda: (x) => x * 2
        let expr = Expression::Map {
            array: Box::new(Expression::Var("numbers".to_string())),
            function: Box::new(Expression::Lambda {
                params: vec!["x".to_string()],
                body: Box::new(Expression::Multiply(
                    Box::new(Expression::Var("x".to_string())),
                    Box::new(Expression::Literal(Value::Number(2.into()))),
                )),
            }),
        };
        
        let result = expr.evaluate(&ctx).unwrap();
        if let Value::Array(arr) = result {
            assert_eq!(arr.len(), 3);
            assert_eq!(arr[0].as_f64(), Some(2.0));
            assert_eq!(arr[1].as_f64(), Some(4.0));
            assert_eq!(arr[2].as_f64(), Some(6.0));
        } else {
            panic!("Expected array");
        }
    }

    #[test]
    fn test_let_binding() {
        let ctx = Context::new();
        
        // let x = 10, y = 5 in x + y
        let mut bindings = HashMap::new();
        bindings.insert("x".to_string(), Expression::Literal(Value::Number(10.into())));
        bindings.insert("y".to_string(), Expression::Literal(Value::Number(5.into())));
        
        let expr = Expression::Let {
            bindings,
            body: Box::new(Expression::Add(
                Box::new(Expression::Var("x".to_string())),
                Box::new(Expression::Var("y".to_string())),
            )),
        };
        
        let result = expr.evaluate(&ctx).unwrap();
        assert_eq!(result.as_f64(), Some(15.0));
    }

}
