# Functional DSL Enhancement Roadmap

## Executive Summary

This document outlines the plan to enhance the JAQ JSON Loader DSL with functional programming capabilities inspired by JSONata. The goal is to make the DSL Turing-complete while maintaining its SQL-like intuitiveness and adding powerful expression capabilities.

**Target Completion:** 8-10 weeks  
**Priority:** High - Enables complex transformations without external tools

---

## Current State vs Target State

| Capability | Current DSL | JSONata | Target DSL |
|------------|-------------|---------|------------|
| User-Defined Functions | ❌ No | ✅ Yes | ✅ Yes |
| Higher-Order Functions | ❌ No | ✅ Yes | ✅ Yes |
| Recursion | ❌ No | ✅ Yes (TCO) | ✅ Yes |
| Automatic Array Flattening | ⚠️ Manual `explode` | ✅ Automatic | ✅ Automatic |
| XPath-like Paths | ❌ Simple refs | ✅ `Account.Order.Product` | ✅ Dot notation |
| Turing Complete | ❌ No | ✅ Yes | ✅ Yes |
| Expression Complexity | Limited | Full FP | Full FP + SQL-like |

---

## Phase Overview

```
Phase 1: Expression Parser Foundation     ✅ COMPLETE
Phase 2: Function Registry                   ✅ COMPLETE
Phase 3: User-Defined Functions           ✅ COMPLETE
Phase 4: Automatic Array Flattening       ✅ COMPLETE
Phase 5: Higher-Order Functions           ✅ COMPLETE
Phase 6: Let Bindings & Variables         ████████████░░░░░░░░ 0%
Phase 7: Recursion & Tail Call Optimization ████████████░░░░░░░░ 0%
Phase 8: XPath-like Path Expressions      ████████████░░░░░░░░ 0%
```

---

## Phase 1: Expression Parser Foundation ⏳ NOT STARTED

**Duration:** 2 weeks  
**Status:** 🔵 Planned  
**Dependencies:** None

### Goals
- Create a robust expression AST (Abstract Syntax Tree)
- Implement evaluation engine for basic operations
- Support literal values, variables, and arithmetic

### Technical Design

New file: `src/expression.rs`

```rust
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(tag = "op", content = "args", rename_all = "snake_case")]
pub enum Expression {
    // Literals
    Literal(Value),
    
    // Variable reference
    Var(String),
    
    // Field access (for path expressions)
    FieldAccess {
        object: Box<Expression>,
        field: String,
    },
    
    // Arithmetic
    Add(Box<Expression>, Box<Expression>),
    Subtract(Box<Expression>, Box<Expression>),
    Multiply(Box<Expression>, Box<Expression>),
    Divide(Box<Expression>, Box<Expression>),
    Modulo(Box<Expression>, Box<Expression>),
    Power(Box<Expression>, Box<Expression>),
    Negate(Box<Expression>),
    
    // Comparison
    Eq(Box<Expression>, Box<Expression>),
    Ne(Box<Expression>, Box<Expression>),
    Lt(Box<Expression>, Box<Expression>),
    Le(Box<Expression>, Box<Expression>),
    Gt(Box<Expression>, Box<Expression>),
    Ge(Box<Expression>, Box<Expression>),
    
    // Logical
    And(Box<Expression>, Box<Expression>),
    Or(Box<Expression>, Box<Expression>),
    Not(Box<Expression>),
    
    // String operations
    Concat(Vec<Expression>),
    Contains {
        string: Box<Expression>,
        substring: Box<Expression>,
    },
    
    // Type checking
    IsNull(Box<Expression>),
    IsArray(Box<Expression>),
    IsObject(Box<Expression>),
    IsString(Box<Expression>),
    IsNumber(Box<Expression>),
}
```

### JSON Syntax Examples

```json
{
  "select": [
    {
      "expr": {
        "op": "add",
        "args": [
          {"op": "var", "args": ["o.price"]},
          {"op": "multiply", "args": [
            {"op": "var", "args": ["o.tax_rate"]},
            100
          ]}
        ]
      },
      "alias": "total"
    }
  ]
}
```

Or simplified form:

```json
{
  "select": [
    {
      "expr": {"add": [{"var": "o.price"}, {"multiply": [{"var": "o.tax"}, 100]}]},
      "alias": "total"
    }
  ]
}
```

### Acceptance Criteria
- [ ] Expression AST defined with all basic operations
- [ ] Evaluator handles arithmetic on numbers
- [ ] Evaluator handles string concatenation
- [ ] Evaluator handles comparisons (returns boolean Values)
- [ ] Evaluator handles logical operators with proper short-circuit
- [ ] Unit tests for each operation type
- [ ] Error messages are descriptive

---

## Phase 2: Function Registry ⏳ NOT STARTED

**Duration:** 1 week  
**Status:** 🔵 Planned  
**Dependencies:** Phase 1

### Goals
- Create pluggable function registry
- Implement 50+ built-in functions
- Support function overloading by arity

### Technical Design

New file: `src/functions.rs`

```rust
pub struct FunctionRegistry {
    builtins: HashMap<String, Vec<BuiltinFunction>>, // name -> overloads
    user_defined: HashMap<String, UserFunction>,
}

pub type BuiltinFunction = Arc<dyn Fn(&[Value]) -> Result<Value> + Send + Sync>;

#[derive(Debug, Clone)]
pub struct UserFunction {
    pub params: Vec<String>,
    pub body: Expression,
    pub closure: Option<Context>, // For closures
}
```

### Built-in Function Categories

#### Numeric Functions (15 functions)
- `$abs(n)` - Absolute value
- `$floor(n)` - Round down
- `$ceil(n)` - Round up
- `$round(n, precision)` - Round to decimal places
- `$sqrt(n)` - Square root
- `$power(base, exp)` - Exponentiation
- `$random()` - Random number 0-1
- `$max(arr)` - Maximum of array
- `$min(arr)` - Minimum of array
- `$sum(arr)` - Sum of array
- `$avg(arr)` - Average of array
- `$mod(a, b)` - Modulo
- `$sin/cos/tan(n)` - Trigonometric
- `$log/ln/exp(n)` - Logarithmic

#### String Functions (20 functions)
- `$length(str)` - String length
- `$uppercase(str)` - To upper
- `$lowercase(str)` - To lower
- `$trim(str)` - Remove whitespace
- `$substring(str, start, length)` - Extract substring
- `$contains(str, substr)` - Check containment
- `$startsWith(str, prefix)` - Check prefix
- `$endsWith(str, suffix)` - Check suffix
- `$split(str, delimiter)` - Split to array
- `$join(arr, separator)` - Join array
- `$replace(str, pattern, replacement)` - Replace
- `$match(str, regex)` - Regex match
- `$format(template, ...args)` - String formatting
- `$pad(str, length, char)` - Pad string
- `$urlEncode/Decode(str)` - URL encoding
- `$base64Encode/Decode(str)` - Base64

#### Array Functions (15 functions)
- `$count(arr)` - Array length
- `$append(arr1, arr2)` - Concatenate arrays
- `$sort(arr, function?)` - Sort with optional comparator
- `$reverse(arr)` - Reverse array
- `$distinct(arr)` - Remove duplicates
- `$zip(arr1, arr2, ...)` - Zip arrays together
- `$flatten(arr, depth?)` - Flatten nested arrays
- `$range(start, end, step?)` - Generate number range
- `$shuffle(arr)` - Random shuffle
- `$take(n, arr)` - Take first n
- `$drop(n, arr)` - Drop first n
- `$slice(arr, start, end)` - Array slice
- `$indexOf(arr, value)` - Find index
- `$filter(arr, predicate)` - Filter (Phase 5)
- `$map(arr, function)` - Map (Phase 5)

#### Object Functions (10 functions)
- `$keys(obj)` - Get keys
- `$values(obj)` - Get values
- `$lookup(obj, key)` - Safe property access
- `$spread(obj)` - Object to key-value pairs
- `$merge(arr)` - Merge objects
- `$type(value)` - Get type name
- `$exists(path)` - Check if path exists
- `$sift(obj, predicate)` - Filter object properties
- `$each(obj, function)` - Iterate over object

#### Date/Time Functions (existing + new)
- `$now()` - Current timestamp
- `$parseDate(str, format)` - Parse date string
- `$formatDate(date, format)` - Format date
- `$dateAdd/Subtract(date, amount, unit)` - Date arithmetic
- `$dateDiff(d1, d2, unit)` - Date difference
- `$epoch(date)` - To Unix timestamp
- `$fromEpoch(ms)` - From Unix timestamp

### Acceptance Criteria
- [ ] FunctionRegistry struct with registration/dispatch
- [ ] 50+ built-in functions implemented
- [ ] Type checking on function arguments
- [ ] Error messages include function name and expected args
- [ ] Functions work in SELECT, WHERE, and expressions
- [ ] Performance: 1000 function calls/sec minimum

---

## Phase 3: User-Defined Functions ⏳ NOT STARTED

**Duration:** 1 week  
**Status:** 🔵 Planned  
**Dependencies:** Phase 2

### Goals
- Allow users to define functions in DSL queries
- Support closures (functions capturing outer scope)
- Function composition

### Technical Design

```rust
// Extension to QueryDsl
#[derive(Debug, Deserialize, Clone)]
pub struct QueryDsl {
    // ... existing fields ...
    
    /// User-defined functions
    #[serde(default)]
    pub functions: Option<HashMap<String, UserFunctionDef>>,
}

#[derive(Debug, Deserialize, Clone)]
pub struct UserFunctionDef {
    pub params: Vec<String>,
    #[serde(default)]
    pub body: Expression,
    #[serde(default)]
    pub doc: Option<String>, // Documentation
}

// New expression type for function calls
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Expression {
    // ... existing variants ...
    
    /// Function call
    Call {
        name: String,
        args: Vec<Expression>,
    },
    
    /// Anonymous function (lambda)
    Lambda {
        params: Vec<String>,
        body: Box<Expression>,
    },
}
```

### JSON Syntax

```json
{
  "functions": {
    "calculateTax": {
      "params": ["amount", "rate"],
      "doc": "Calculate tax amount",
      "body": {
        "multiply": [{"var": "amount"}, {"var": "rate"}]
      }
    },
    "formatCurrency": {
      "params": ["amount", "currency"],
      "body": {
        "format": ["{} {:.2f}", {"var": "currency"}, {"var": "amount"}]
      }
    }
  },
  "from": {"source_file": "orders.json", "alias": "o"},
  "select": [
    {
      "expr": {
        "call": "calculateTax",
        "args": [{"var": "o.amount"}, 0.08]
      },
      "alias": "tax"
    }
  ]
}
```

### Lambda/Anonymous Functions

```json
{
  "from": {"source_file": "products.json", "alias": "p"},
  "select": [
    {
      "expr": {
        "call": {
          "lambda": ["price", "qty"],
          "body": {"multiply": [{"var": "price"}, {"var": "qty"}]}
        },
        "args": [{"var": "p.price"}, {"var": "p.quantity"}]
      },
      "alias": "line_total"
    }
  ]
}
```

### Acceptance Criteria
- [ ] Functions can be defined in `functions` section
- [ ] Functions can call other functions
- [ ] Functions capture lexical scope (closures)
- [ ] Recursion supported (base case for Phase 7 TCO)
- [ ] Error if function not found
- [ ] Error if wrong number of arguments
- [ ] Error if argument types incompatible

---

## Phase 4: Automatic Array Flattening ⏳ NOT STARTED

**Duration:** 3 days  
**Status:** 🔵 Planned  
**Dependencies:** Phase 1

### Goals
- Access nested arrays without explicit `explode`
- JSONata-style "do the right thing" array handling
- Maintain backward compatibility with explicit `explode`

### Technical Design

Modify existing field access in `query_engine.rs`:

```rust
impl QueryEngine<'_> {
    /// Extract value with automatic array flattening
    fn extract_value_auto_flatten(
        &self,
        row: &HashMap<String, Value>,
        alias: &str,
        path: &str,
    ) -> Value {
        let parts: Vec<&str> = path.split('.').collect();
        let base_value = row.get(alias).cloned().unwrap_or(Value::Null);
        
        self.navigate_with_flatten(base_value, &parts)
    }
    
    fn navigate_with_flatten(&self, value: Value, path: &[&str]) -> Value {
        if path.is_empty() {
            return value;
        }
        
        match value {
            Value::Array(arr) => {
                // Automatic flattening: apply to each element
                let results: Vec<Value> = arr
                    .into_iter()
                    .filter_map(|item| {
                        let result = self.navigate_with_flatten(item, path);
                        if result.is_null() { None } else { Some(result) }
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
            Value::Object(mut obj) if !path.is_empty() => {
                let key = path[0];
                match obj.remove(key) {
                    Some(next_value) => self.navigate_with_flatten(next_value, &path[1..]),
                    None => Value::Null,
                }
            }
            _ => Value::Null,
        }
    }
}
```

### Behavior Examples

**Before (Current):**
```json
{
  "from": {"source_file": "shopify.json", "alias": "s", "explode": "variants"},
  "select": [{"expr": "s.variants.sku", "alias": "sku"}]
}
// Must use explode to access variants.sku
```

**After (Automatic):**
```json
{
  "from": {"source_file": "shopify.json", "alias": "s"},
  "select": [{"expr": "s.variants.sku", "alias": "all_skus"}]
}
// Automatically returns array of all variant SKUs
```

### Configuration Option

Allow disabling auto-flatten per query:

```json
{
  "from": {"source_file": "data.json", "alias": "d"},
  "options": {"auto_flatten": false},
  "select": [...]
}
```

### Acceptance Criteria
- [ ] `a.b.c` on array field returns array of values
- [ ] Nested arrays are recursively flattened
- [ ] Single-element arrays unwrap to scalar
- [ ] Empty results return null, not empty array
- [ ] Explicit `explode` still works for fine-grained control
- [ ] Performance: <10% overhead vs explicit explode

---

## Phase 5: Higher-Order Functions ⏳ NOT STARTED

**Duration:** 1 week  
**Status:** 🔵 Planned  
**Dependencies:** Phase 2, Phase 3

### Goals
- Implement `map`, `filter`, `reduce` as expression operators
- Support anonymous functions as arguments
- Enable functional data transformation patterns

### Technical Design

```rust
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Expression {
    // ... existing variants ...
    
    /// Map: transform each element
    Map {
        array: Box<Expression>,
        function: Box<Expression>, // Lambda or function reference
    },
    
    /// Filter: keep elements matching predicate
    Filter {
        array: Box<Expression>,
        predicate: Box<Expression>,
    },
    
    /// Reduce: fold array to single value
    Reduce {
        array: Box<Expression>,
        function: Box<Expression>, // (accumulator, current) -> new_acc
        initial: Box<Expression>,
    },
    
    /// Single: find one matching element
    Single {
        array: Box<Expression>,
        predicate: Box<Expression>,
    },
    
    /// ForEach: execute for side effects (return null)
    ForEach {
        array: Box<Expression>,
        function: Box<Expression>,
    },
}
```

### JSON Syntax

**Map Example:**
```json
{
  "from": {"source_file": "orders.json", "alias": "o"},
  "select": [
    {
      "expr": {
        "map": {
          "array": {"var": "o.items"},
          "function": {
            "object": {
              "product": {"var": "name"},
              "line_total": {
                "multiply": [{"var": "price"}, {"var": "quantity"}]
              }
            }
          }
        }
      },
      "alias": "enriched_items"
    }
  ]
}
```

**Filter Example:**
```json
{
  "from": {"source_file": "products.json", "alias": "p"},
  "select": [
    {
      "expr": {
        "filter": {
          "array": {"var": "p.variants"},
          "predicate": {
            "gt": [{"var": "inventory_quantity"}, 0]
          }
        }
      },
      "alias": "in_stock_variants"
    }
  ]
}
```

**Reduce Example:**
```json
{
  "from": {"source_file": "orders.json", "alias": "o"},
  "select": [
    {
      "expr": {
        "reduce": {
          "array": {"var": "o.items.price"},
          "function": {"add": [{"var": "$acc"}, {"var": "$"}]},
          "initial": 0
        }
      },
      "alias": "total"
    }
  ]
}
```

### Acceptance Criteria
- [ ] `$map`, `$filter`, `$reduce` work with arrays
- [ ] Anonymous functions can be passed as arguments
- [ ] Context variables `$` (current) and `$acc` (accumulator) work
- [ ] Index available as `$i` in callbacks
- [ ] Nested higher-order functions work
- [ ] Error if function argument is not callable
- [ ] Empty arrays return empty (map/filter) or initial (reduce)

---

## Phase 6: Let Bindings & Variables ⏳ NOT STARTED

**Duration:** 3 days  
**Status:** 🔵 Planned  
**Dependencies:** Phase 1

### Goals
- Allow intermediate variable bindings
- Support nested scopes
- Enable complex expressions without repetition

### Technical Design

```rust
// Extension to QueryDsl
#[derive(Debug, Deserialize, Clone)]
pub struct QueryDsl {
    // ... existing fields ...
    
    /// Variable bindings
    #[serde(default)]
    pub r#let: Option<HashMap<String, Expression>>,
}

// New expression for let-binding within expressions
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub enum Expression {
    // ... existing ...
    
    /// Let binding: creates new scope with variables
    Let {
        bindings: HashMap<String, Expression>,
        body: Box<Expression>,
    },
}
```

### JSON Syntax

**Query-level Let:**
```json
{
  "from": {"source_file": "orders.json", "alias": "o"},
  "let": {
    "subtotal": {
      "reduce": {
        "array": {"var": "o.items.price"},
        "function": "add",
        "initial": 0
      }
    },
    "tax_rate": 0.08,
    "tax_amount": {
      "multiply": [{"var": "subtotal"}, {"var": "tax_rate"}]
    }
  },
  "select": [
    {"expr": {"var": "o.order_id"}, "alias": "order"},
    {"expr": {"var": "subtotal"}, "alias": "subtotal"},
    {"expr": {"var": "tax_amount"}, "alias": "tax"},
    {
      "expr": {"add": [{"var": "subtotal"}, {"var": "tax_amount"}]},
      "alias": "total"
    }
  ]
}
```

**Expression-level Let:**
```json
{
  "from": {"source_file": "products.json", "alias": "p"},
  "select": [
    {
      "expr": {
        "let": {
          "discounted": {"multiply": [{"var": "p.price"}, 0.9]},
          "tax": {"multiply": [{"var": "discounted"}, 0.08]}
        },
        "body": {
          "add": [{"var": "discounted"}, {"var": "tax"}]
        }
      },
      "alias": "final_price"
    }
  ]
}
```

### Acceptance Criteria
- [ ] Variables defined in `let` are available in query
- [ ] Variables can reference other variables (dependency order)
- [ ] Nested scopes shadow outer variables
- [ ] Variables work in WHERE, SELECT, HAVING, ORDER BY
- [ ] Cyclic dependencies detected and error
- [ ] Undefined variables return null with warning

---

## Phase 7: Recursion & Tail Call Optimization ⏳ NOT STARTED

**Duration:** 1 week  
**Status:** 🔵 Planned  
**Dependencies:** Phase 3

### Goals
- Support recursive functions
- Implement Tail Call Optimization (TCO) to prevent stack overflow
- Enable algorithms like tree traversal, factorial, fibonacci

### Technical Design

```rust
// Detect tail calls during evaluation

#[derive(Debug, Clone)]
pub enum EvalResult {
    Value(Value),
    TailCall { // Indicates TCO opportunity
        function: String,
        args: Vec<Value>,
    },
}

pub struct Evaluator {
    max_recursion_depth: usize,
    enable_tco: bool,
}

impl Evaluator {
    pub fn evaluate_with_tco(&self, expr: &Expression, context: &Context) -> Result<Value> {
        let mut current_expr = expr.clone();
        let mut current_context = context.clone();
        let mut stack_depth = 0;
        
        loop {
            match self.evaluate_expr(&current_expr, &current_context)? {
                EvalResult::Value(v) => return Ok(v),
                EvalResult::TailCall { function, args } => {
                    if stack_depth > self.max_recursion_depth {
                        return Err(anyhow!("Maximum recursion depth exceeded"));
                    }
                    
                    // Get function and prepare new context
                    let func = self.registry.get(&function)?;
                    current_context = self.prepare_call_context(&func, args)?;
                    current_expr = func.body.clone();
                    stack_depth += 1;
                }
            }
        }
    }
}
```

### JSON Syntax

**Factorial with Recursion:**
```json
{
  "functions": {
    "factorial": {
      "params": ["n"],
      "doc": "Calculate n! using recursion",
      "body": {
        "if": {
          "condition": {"lte": [{"var": "n"}, 1]},
          "then": 1,
          "else": {
            "multiply": [
              {"var": "n"},
              {"call": "factorial", "args": [{"subtract": [{"var": "n"}, 1]}]}
            ]
          }
        }
      }
    }
  },
  "from": {"source_file": "test.json", "alias": "t"},
  "select": [
    {"expr": {"call": "factorial", "args": [10]}, "alias": "fact_10"}
  ]
}
```

**Factorial with TCO (Tail Recursive):**
```json
{
  "functions": {
    "factorial_tco": {
      "params": ["n"],
      "body": {
        "call": "factorial_acc",
        "args": [{"var": "n"}, 1]
      }
    },
    "factorial_acc": {
      "params": ["n", "acc"],
      "doc": "Accumulator version for TCO",
      "body": {
        "if": {
          "condition": {"lte": [{"var": "n"}, 1]},
          "then": {"var": "acc"},
          "else": {
            "call": "factorial_acc",
            "args": [
              {"subtract": [{"var": "n"}, 1]},
              {"multiply": [{"var": "n"}, {"var": "acc"}]}
            ]
          }
        }
      }
    }
  },
  "from": {"source_file": "test.json", "alias": "t"},
  "select": [
    {"expr": {"call": "factorial_tco", "args": [1000]}, "alias": "fact_1000"}
  ]
}
```

### Acceptance Criteria
- [ ] Recursive functions execute correctly
- [ ] TCO prevents stack overflow for tail-recursive functions
- [ ] `factorial(1000)` works without stack overflow (with TCO)
- [ ] Non-tail recursion limited by max_depth (safety)
- [ ] Clear error on stack overflow
- [ ] Can traverse deeply nested JSON structures

---

## Phase 8: XPath-like Path Expressions ⏳ NOT STARTED

**Duration:** 3 days  
**Status:** 🔵 Planned  
**Dependencies:** Phase 4

### Goals
- Support dot-notation paths: `Account.Order.Product`
- Descendant selector: `**` (like JSONata `**`)
- Parent traversal: `^` or parent reference
- Predicates in paths: `Account.Order[Status='Completed']`

### Technical Design

```rust
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub enum PathSegment {
    Field(String),           // .field
    Index(usize),            // [0]
    Predicate(Expression),   // [Price > 100]
    Descendant(String),      // **.field (recursive descent)
    Wildcard,                // [*] or just *
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct PathExpression {
    pub root: Option<String>, // Alias or null for root
    pub segments: Vec<PathSegment>,
}

impl Expression {
    fn eval_path(&self, path: &PathExpression, context: &Context) -> Result<Value> {
        // Implementation details...
    }
    
    fn collect_descendants(&self, value: &Value, target: &str, results: &mut Vec<Value>) {
        match value {
            Value::Object(obj) => {
                if let Some(v) = obj.get(target) {
                    results.push(v.clone());
                }
                for v in obj.values() {
                    self.collect_descendants(v, target, results);
                }
            }
            Value::Array(arr) => {
                for v in arr {
                    self.collect_descendants(v, target, results);
                }
            }
            _ => {}
        }
    }
}
```

### JSON Syntax

**Basic Path:**
```json
{
  "from": {"source_file": "account.json", "alias": "a"},
  "select": [
    {"path": "a.Order.Product.Price", "alias": "prices"}
  ]
}
```

**With Predicates:**
```json
{
  "from": {"source_file": "account.json", "alias": "a"},
  "select": [
    {
      "path": "a.Order[Status='Shipped'].Product[Price > 100].Name",
      "alias": "expensive_shipped_products"
    }
  ]
}
```

**Descendant Search:**
```json
{
  "from": {"source_file": "nested.json", "alias": "n"},
  "select": [
    {"path": "n.**.email", "alias": "all_emails_anywhere"}
  ]
}
```

**Shorthand Syntax:**
```json
{
  "from": {"source_file": "data.json", "alias": "d"},
  "select": [
    {"expr": "d.Order.Product.Price", "alias": "prices"},
    {"expr": "d.**.id", "alias": "all_ids"}
  ]
}
```

### Acceptance Criteria
- [ ] Dot notation paths work: `a.b.c`
- [ ] Array access: `[0]`, `[-1]`, `[start:end]`
- [ ] Predicates: `[field > 100]`, `[name = 'test']`
- [ ] Descendant search: `**.fieldname`
- [ ] Wildcards: `*` matches any field
- [ ] Paths work in SELECT, WHERE, ORDER BY, expressions
- [ ] Performance: path resolution < 1ms per row

---

## Integration Plan

### Modified Files

| File | Changes |
|------|---------|
| `src/expression.rs` | New - Expression AST and evaluator |
| `src/functions.rs` | New - Function registry and builtins |
| `src/query_engine.rs` | Integrate expression evaluation |
| `src/main.rs` | Update API endpoints if needed |
| `src/html_page.html` | Update Learn page with new features |

### Backward Compatibility

All existing queries will continue to work. New features are opt-in:
- New syntax in `expr` fields (strings auto-detected)
- New top-level `functions` section
- New `let` clause
- New `path` alternative to `expr`

### Testing Strategy

1. **Unit Tests:** Each phase has comprehensive unit tests
2. **Integration Tests:** Full DSL queries in `dsl_examples/`
3. **Property Tests:** Random expression generation
4. **Performance Tests:** Benchmark against JSONata for equivalent queries

---

## Progress Tracking

### Phase 1: Expression Parser Foundation
| Task | Status | Notes |
|------|--------|-------|
| Create expression.rs module | ⬜ Not Started | |
| Define Expression enum | ⬜ Not Started | |
| Implement evaluate() for literals | ⬜ Not Started | |
| Implement arithmetic operators | ⬜ Not Started | |
| Implement comparison operators | ⬜ Not Started | |
| Implement logical operators | ⬜ Not Started | |
| Unit tests | ⬜ Not Started | |
| **Phase 1 Complete** | ✅ DONE | |

### Phase 2: Function Registry
| Task | Status | Notes |
|------|--------|-------|
| Create functions.rs module | ⬜ Not Started | |
| FunctionRegistry struct | ⬜ Not Started | |
| Numeric functions (15) | ⬜ Not Started | |
| String functions (20) | ⬜ Not Started | |
| Array functions (15) | ⬜ Not Started | |
| Object functions (10) | ⬜ Not Started | |
| Date/time functions | ⬜ Not Started | |
| Unit tests | ⬜ Not Started | |
| **Phase 2 Complete** | ✅ DONE | |

### Phase 3: User-Defined Functions
| Task | Status | Notes |
|------|--------|-------|
| UserFunctionDef struct | ⬜ Not Started | |
| Add functions to QueryDsl | ⬜ Not Started | |
| Function call expression | ⬜ Not Started | |
| Lambda expression | ⬜ Not Started | |
| Closure capture | ⬜ Not Started | |
| Function composition | ⬜ Not Started | |
| Unit tests | ⬜ Not Started | |
| **Phase 3 Complete** | ⬜ | |

### Phase 4: Automatic Array Flattening
| Task | Status | Notes |
|------|--------|-------|
| Modify extract_value | ⬜ Not Started | |
| Implement navigate_with_flatten | ⬜ Not Started | |
| Auto-flatten configuration | ⬜ Not Started | |
| Backward compatibility | ⬜ Not Started | |
| Performance tests | ⬜ Not Started | |
| **Phase 4 Complete** | ⬜ | |

### Phase 5: Higher-Order Functions
| Task | Status | Notes |
|------|--------|-------|
| Map expression | ⬜ Not Started | |
| Filter expression | ⬜ Not Started | |
| Reduce expression | ⬜ Not Started | |
| Single/ForEach expressions | ⬜ Not Started | |
| Context variables ($, $acc, $i) | ⬜ Not Started | |
| Nested HOF support | ⬜ Not Started | |
| Unit tests | ⬜ Not Started | |
| **Phase 5 Complete** | ⬜ | |

### Phase 6: Let Bindings & Variables
| Task | Status | Notes |
|------|--------|-------|
| Add let to QueryDsl | ⬜ Not Started | |
| Let expression variant | ⬜ Not Started | |
| Context hierarchy | ⬜ Not Started | |
| Dependency resolution | ⬜ Not Started | |
| Cyclic dependency detection | ⬜ Not Started | |
| Unit tests | ⬜ Not Started | |
| **Phase 6 Complete** | ⬜ | |

### Phase 7: Recursion & TCO
| Task | Status | Notes |
|------|--------|-------|
| Tail call detection | ⬜ Not Started | |
| EvalResult enum | ⬜ Not Started | |
| TCO loop implementation | ⬜ Not Started | |
| Recursion depth limits | ⬜ Not Started | |
| Config options | ⬜ Not Started | |
| Unit tests | ⬜ Not Started | |
| **Phase 7 Complete** | ⬜ | |

### Phase 8: XPath-like Path Expressions
| Task | Status | Notes |
|------|--------|-------|
| PathSegment enum | ⬜ Not Started | |
| PathExpression struct | ⬜ Not Started | |
| Basic dot notation | ⬜ Not Started | |
| Array indexing | ⬜ Not Started | |
| Predicates | ⬜ Not Started | |
| Descendant search | ⬜ Not Started | |
| Shorthand syntax | ⬜ Not Started | |
| Unit tests | ⬜ Not Started | |
| **Phase 8 Complete** | ⬜ | |

---

## Success Metrics

After all phases complete:

| Metric | Target |
|--------|--------|
| Feature parity with JSONata | 90%+ |
| Backward compatibility | 100% |
| Query performance | Within 20% of JSONata for equivalent operations |
| Lines of code (new) | < 3000 |
| Test coverage | > 85% |
| Documentation | Complete Learn page updates |

---

## Next Steps

1. **Review and approve roadmap** - Confirm scope and priorities
2. **Set up feature branch** - `git checkout -b feature/functional-dsl`
3. **Begin Phase 1** - Expression parser foundation
4. **Weekly check-ins** - Track progress against roadmap
5. **Demo after Phase 5** - Higher-order functions milestone

---

*Document Version: 1.0*  
*Created: 2026-02-07*  
*Status: Planning Phase*
