//! Context management for expression evaluation
//!
//! Provides variable scoping with support for nested contexts,
// allowing for closures and hierarchical variable resolution.

use anyhow::Result;
use serde_json::Value;
use std::collections::HashMap;

/// A context for variable storage during expression evaluation
///
/// Contexts can be nested, forming a scope chain. When a variable
/// is looked up, the context checks its own variables first, then
/// falls back to parent contexts.
#[derive(Debug, Clone)]
pub struct Context {
    /// Variables defined in this scope
    variables: HashMap<String, Value>,
    /// Parent context (for nested scopes)
    parent: Option<Box<Context>>,
}

impl Context {
    /// Create a new empty context
    pub fn new() -> Self {
        Self {
            variables: HashMap::new(),
            parent: None,
        }
    }
    
    /// Create a context with a parent (for nested scopes)
    pub fn with_parent(parent: Context) -> Self {
        Self {
            variables: HashMap::new(),
            parent: Some(Box::new(parent)),
        }
    }
    
    /// Create a child context from this context
    pub fn child(&self) -> Self {
        Self {
            variables: HashMap::new(),
            parent: Some(Box::new(self.clone())),
        }
    }
    
    /// Set a variable in this context
    pub fn set(&mut self, name: String, value: Value) {
        self.variables.insert(name, value);
    }
    
    /// Get a variable, searching up the scope chain
    pub fn get(&self, name: &str) -> Result<Value> {
        // Handle special variables
        match name {
            "$" => {
                // Current context value
                return Ok(self.variables.get("$").cloned().unwrap_or(Value::Null));
            }
            "$$" => {
                // Root context - find the topmost parent
                let mut current = self;
                while let Some(ref parent) = current.parent {
                    current = parent;
                }
                return Ok(current.variables.get("$$").cloned().unwrap_or(Value::Null));
            }
            _ => {}
        }
        
        // Try to find in this scope
        if let Some(value) = self.variables.get(name) {
            return Ok(value.clone());
        }
        
        // Fall back to parent scope
        if let Some(ref parent) = self.parent {
            return parent.get(name);
        }
        
        // Variable not found - return null
        Ok(Value::Null)
    }
    
    /// Check if a variable exists in this context or any parent
    pub fn has(&self, name: &str) -> bool {
        if self.variables.contains_key(name) {
            return true;
        }
        
        if let Some(ref parent) = self.parent {
            return parent.has(name);
        }
        
        false
    }
    
    /// Remove a variable from this context only
    pub fn remove(&mut self, name: &str) -> Option<Value> {
        self.variables.remove(name)
    }
    
    /// Get all variable names in this context (not including parent)
    pub fn local_names(&self) -> Vec<&String> {
        self.variables.keys().collect()
    }
    
    /// Set the current context value ($)
    pub fn set_current(&mut self, value: Value) {
        self.variables.insert("$".to_string(), value);
    }
    
    /// Set the root context value ($$)
    pub fn set_root(&mut self, value: Value) {
        self.variables.insert("$$".to_string(), value);
    }
    
    /// Get the current context value ($)
    pub fn current(&self) -> Value {
        self.variables.get("$").cloned().unwrap_or(Value::Null)
    }
    
    /// Get the root context value ($$)
    pub fn root(&self) -> Value {
        self.get("$$").unwrap_or(Value::Null)
    }
    
    /// Create a context from a JSON object
    pub fn from_object(obj: &serde_json::Map<String, Value>) -> Self {
        let mut ctx = Self::new();
        for (key, value) in obj {
            ctx.set(key.clone(), value.clone());
        }
        ctx
    }
    
    /// Merge another context into this one (shadowing existing variables)
    pub fn merge(&mut self, other: &Context) {
        for (key, value) in &other.variables {
            self.variables.insert(key.clone(), value.clone());
        }
    }
    
    /// Create a snapshot of all visible variables (for debugging)
    pub fn snapshot(&self) -> HashMap<String, Value> {
        let mut result = HashMap::new();
        
        // First collect from parent (lower priority)
        if let Some(ref parent) = self.parent {
            result = parent.snapshot();
        }
        
        // Then overlay with local variables (higher priority)
        for (key, value) in &self.variables {
            result.insert(key.clone(), value.clone());
        }
        
        result
    }
}

impl Default for Context {
    fn default() -> Self {
        Self::new()
    }
}

/// A context builder for convenient context construction
pub struct ContextBuilder {
    context: Context,
}

impl ContextBuilder {
    pub fn new() -> Self {
        Self {
            context: Context::new(),
        }
    }
    
    pub fn with_variable(mut self, name: &str, value: Value) -> Self {
        self.context.set(name.to_string(), value);
        self
    }
    
    pub fn with_string(self, name: &str, value: &str) -> Self {
        self.with_variable(name, Value::String(value.to_string()))
    }
    
    pub fn with_number(self, name: &str, value: f64) -> Self {
        if let Some(num) = serde_json::Number::from_f64(value) {
            self.with_variable(name, Value::Number(num))
        } else {
            self
        }
    }
    
    pub fn with_int(self, name: &str, value: i64) -> Self {
        self.with_variable(name, Value::Number(value.into()))
    }
    
    pub fn with_bool(self, name: &str, value: bool) -> Self {
        self.with_variable(name, Value::Bool(value))
    }
    
    pub fn with_null(self, name: &str) -> Self {
        self.with_variable(name, Value::Null)
    }
    
    pub fn with_current(mut self, value: Value) -> Self {
        self.context.set_current(value);
        self
    }
    
    pub fn with_root(mut self, value: Value) -> Self {
        self.context.set_root(value);
        self
    }
    
    pub fn build(self) -> Context {
        self.context
    }
}

impl Default for ContextBuilder {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_basic_context() {
        let mut ctx = Context::new();
        ctx.set("x".to_string(), Value::Number(10.into()));
        
        assert_eq!(ctx.get("x").unwrap(), Value::Number(10.into()));
        assert_eq!(ctx.get("y").unwrap(), Value::Null); // Not found
    }

    #[test]
    fn test_nested_context() {
        let mut parent = Context::new();
        parent.set("x".to_string(), Value::Number(10.into()));
        parent.set("y".to_string(), Value::Number(20.into()));
        
        let mut child = Context::with_parent(parent);
        child.set("y".to_string(), Value::Number(30.into())); // Shadows parent's y
        
        // x inherited from parent
        assert_eq!(child.get("x").unwrap(), Value::Number(10.into()));
        // y is shadowed in child
        assert_eq!(child.get("y").unwrap(), Value::Number(30.into()));
    }

    #[test]
    fn test_special_variables() {
        let mut ctx = Context::new();
        ctx.set_current(Value::String("current".to_string()));
        ctx.set_root(Value::String("root".to_string()));
        
        assert_eq!(ctx.get("$").unwrap(), Value::String("current".to_string()));
        assert_eq!(ctx.get("$$").unwrap(), Value::String("root".to_string()));
    }

    #[test]
    fn test_root_in_nested_context() {
        let mut root = Context::new();
        root.set_root(Value::String("root_data".to_string()));
        
        let child = Context::with_parent(root);
        let grandchild = Context::with_parent(child);
        
        // $$ should find the root value through all levels
        assert_eq!(grandchild.get("$$").unwrap(), Value::String("root_data".to_string()));
    }

    #[test]
    fn test_from_object() {
        let mut obj = serde_json::Map::new();
        obj.insert("name".to_string(), Value::String("John".to_string()));
        obj.insert("age".to_string(), Value::Number(30.into()));
        
        let ctx = Context::from_object(&obj);
        
        assert_eq!(ctx.get("name").unwrap(), Value::String("John".to_string()));
        assert_eq!(ctx.get("age").unwrap(), Value::Number(30.into()));
    }

    #[test]
    fn test_context_builder() {
        let ctx = ContextBuilder::new()
            .with_string("name", "Alice")
            .with_int("age", 25)
            .with_number("height", 5.6)
            .with_bool("active", true)
            .with_null("deleted")
            .with_current(Value::String("current_item".to_string()))
            .build();
        
        assert_eq!(ctx.get("name").unwrap(), Value::String("Alice".to_string()));
        assert_eq!(ctx.get("age").unwrap(), Value::Number(25.into()));
        assert_eq!(ctx.get("active").unwrap(), Value::Bool(true));
        assert_eq!(ctx.get("deleted").unwrap(), Value::Null);
        assert_eq!(ctx.current(), Value::String("current_item".to_string()));
    }

    #[test]
    fn test_snapshot() {
        let mut parent = Context::new();
        parent.set("a".to_string(), Value::Number(1.into()));
        parent.set("b".to_string(), Value::Number(2.into()));
        
        let mut child = Context::with_parent(parent);
        child.set("b".to_string(), Value::Number(20.into())); // Override
        child.set("c".to_string(), Value::Number(3.into()));
        
        let snapshot = child.snapshot();
        
        assert_eq!(snapshot.get("a"), Some(&Value::Number(1.into())));
        assert_eq!(snapshot.get("b"), Some(&Value::Number(20.into()))); // Child's value
        assert_eq!(snapshot.get("c"), Some(&Value::Number(3.into())));
    }

    #[test]
    fn test_has() {
        let mut ctx = Context::new();
        ctx.set("x".to_string(), Value::Number(10.into()));
        
        let child = Context::with_parent(ctx);
        
        assert!(child.has("x")); // In parent
        assert!(!child.has("y")); // Nowhere
    }

    #[test]
    fn test_merge() {
        let mut ctx1 = Context::new();
        ctx1.set("a".to_string(), Value::Number(1.into()));
        ctx1.set("b".to_string(), Value::Number(2.into()));
        
        let mut ctx2 = Context::new();
        ctx2.set("b".to_string(), Value::Number(20.into())); // Will override
        ctx2.set("c".to_string(), Value::Number(3.into()));
        
        ctx1.merge(&ctx2);
        
        assert_eq!(ctx1.get("a").unwrap(), Value::Number(1.into()));
        assert_eq!(ctx1.get("b").unwrap(), Value::Number(20.into())); // Overridden
        assert_eq!(ctx1.get("c").unwrap(), Value::Number(3.into()));
    }
}
