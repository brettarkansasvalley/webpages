# Learn Page Updates - New DSL Features Documented

## Summary

The Learn page (`http://localhost:3000/#Learn`) has been updated with comprehensive documentation for all new DSL features.

## New Sections Added

### 1. 📦 Primitive Value Records
**Location:** `#learn-primitive`

Documents how to query JSON files containing primitive values (strings, numbers) instead of objects.

**Examples:**
- Query order GUIDs from `orders_v2_orders_20260130.json`
- Query payment GUIDs from `orders_v2_payments_20260130.json`
- Toast data source overview

**Key Feature:** `as_primitive` option

### 2. 📅 Date/Time Functions
**Location:** `#learn-dates`

Documents all date extraction and manipulation functions.

**Functions Covered:**
| Function | Description |
|----------|-------------|
| `hour(field)` | Extract hour (0-23) |
| `date(field)` | Extract date (YYYY-MM-DD) |
| `minute(field)` | Extract minute (0-59) |
| `day_of_week(field)` | Day of week (0=Sunday) |
| `month(field)` | Month (1-12) |
| `year(field)` | Year |
| `date_diff(f1, f2, unit)` | Calculate difference |

**Examples:**
- Group shifts by hour of day
- Calculate hours worked per shift
- Sales by hour

### 3. 💥 Array Explosion with Context
**Location:** `#learn-explode`

Documents multi-level array traversal while preserving parent context.

**Examples:**
- Single-level: Explode order checks
- Multi-level: Orders → Checks → Selections
- Item mix report with aggregations
- Deep nesting (3 levels): Selections → Discounts

**Key Feature:** `explode_with_context` with `path`, `aliases`, `preserve`, and `where`

### 4. 🔀 COALESCE Function
**Location:** `#learn-coalesce`

Documents fallback value selection for attribution.

**Examples:**
- Server attribution fallback (payment → order → default)
- Net sales by employee with COALESCE in GROUP BY

**Syntax:** `coalesce(field1, field2, 'literal', ...)`

### 5. 🔢 Arithmetic Expressions
**Location:** `#learn-arithmetic`

Documents mathematical operations in SELECT expressions.

**Operators:**
| Operator | Description | Example |
|----------|-------------|---------|
| `*` | Multiplication | `c.amount * 2` |
| `/` | Division | `p.amount / p.total` |
| `+` | Addition | `price + tax` |
| `-` | Subtraction | `total - discount` |

**Examples:**
- Simple multiplication
- Weighted calculations
- Combining with COALESCE for attributed sales

## Navigation Updates

The sidebar navigation now includes links to all new sections:

```
Contents
├── Overview
├── Basic Queries
├── Joins
├── Filters & Conditions
├── Array Handling
├── Aggregation
├── Subqueries (WITH)
├── Transforms
├── Primitive Values        [NEW]
├── Date Functions          [NEW]
├── Explode Context         [NEW]
├── COALESCE                [NEW]
├── Arithmetic              [NEW]
├── Advanced Examples
└── cURL API
```

## Interactive Examples

Each new section includes:
- **Syntax documentation** - Clear explanation of the feature
- **Code examples** - JSON DSL queries with syntax highlighting
- **"Try It" buttons** - Click to load the query into the DSL Query tab
- **Real data examples** - Using actual Toast data files

## Try It Workflow

1. Visit http://localhost:3000/#Learn
2. Navigate to any new section
3. Click **"Try It"** button on any example
4. Query loads automatically into the DSL Query tab
5. Click **"Run DSL Query"** to execute

## Example Queries Available

### Primitive Values
- `learn-query-prim1` - Order GUIDs
- `learn-query-prim2` - Payment GUIDs

### Date Functions
- `learn-query-date1` - Shifts by hour
- `learn-query-date2` - Hours worked calculation
- `learn-query-date3` - Hourly sales

### Explode with Context
- `learn-query-explode1` - Single-level (checks)
- `learn-query-explode2` - Multi-level (selections)
- `learn-query-explode3` - Item mix report
- `learn-query-explode4` - Deep nesting (discounts)

### COALESCE
- `learn-query-coal1` - Attribution fallback
- `learn-query-coal2` - Net sales by employee

### Arithmetic
- `learn-query-arith1` - Simple multiplication
- `learn-query-arith2` - Weighted calculation
- `learn-query-arith3` - Attributed sales

## Data Sources Documented

The Learn page now includes information about Toast data sources:

| Source File | Description |
|-------------|-------------|
| `labor_v1_employees.json` | Employee master data |
| `labor_v1_timeEntries_20260130.json` | Shift time punches |
| `cashmgmt_v1_entries_20260130.json` | Cash transactions |
| `orders_full_YYYYMMDD.json` | Complete order data |

## Files Modified

- `/home/ubuntu/jaq/json-loader-server/src/html_page.html`
  - Added 5 new documentation sections (~400 lines)
  - Updated navigation sidebar
  - Added 15 new interactive examples

## Verification

To verify the updates:

1. Open http://localhost:3000/#Learn
2. Check sidebar shows all new sections
3. Click through each new section
4. Click "Try It" buttons to load queries
5. Run queries to confirm they work
