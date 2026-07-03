//! Performance benchmarks for query operations
//!
//! Run with: cargo bench

use criterion::{black_box, criterion_group, criterion_main, Criterion, BenchmarkId};
use json_loader_server::*;
use json_loader_server::test_utils::*;
use serde_json::json;

/// Setup database with N orders
fn setup_db_with_n_orders(n: usize) -> rusqlite::Connection {
    let conn = create_test_db();
    let mut orders = Vec::with_capacity(n);
    
    for i in 0..n {
        orders.push(json!({
            "guid": format!("order-{:06}", i),
            "businessDate": "2024-01-15",
            "closedDate": format!("2024-01-15T{:02}:00:00Z", i % 24),
            "server": {
                "guid": format!("server-{:03}", i % 10),
                "name": format!("Server {}", i % 10)
            },
            "checks": [
                {
                    "guid": format!("check-{:06}-1", i),
                    "amount": (i as f64) * 10.0,
                    "voided": false,
                    "selections": [
                        {"item": "Item A", "qty": 1, "price": 10.0},
                        {"item": "Item B", "qty": 2, "price": (i as f64) * 5.0}
                    ]
                },
                {
                    "guid": format!("check-{:06}-2", i),
                    "amount": (i as f64) * 5.0,
                    "voided": i % 5 == 0,
                    "selections": [
                        {"item": "Item C", "qty": 1, "price": (i as f64) * 5.0}
                    ]
                }
            ]
        }));
    }
    
    insert_test_data(&conn, "orders.json", orders).unwrap();
    conn
}

/// Benchmark simple select query
fn bench_simple_select(c: &mut Criterion) {
    let mut group = c.benchmark_group("simple_select");
    
    for size in [100, 1_000, 10_000].iter() {
        group.bench_with_input(BenchmarkId::from_parameter(size), size, |b, &size| {
            let conn = setup_db_with_n_orders(size);
            let engine = QueryEngine::new(&conn);
            
            let dsl = QueryDsl {
                from: Some(Source {
                    source_file: "orders.json".to_string(),
                    alias: Some("o".to_string()),
                    explode: None,
                    explode_with_context: None,
                    as_primitive: None,
                }),
                select: vec![
                    SelectField {
                        expr: Some("o.guid".to_string()),
                        alias: Some("guid".to_string()),
                        expression: None,
                        transform: None,
                        agg: None,
                        case: None,
                        coalesce: None,
                    },
                    SelectField {
                        expr: Some("o.businessDate".to_string()),
                        alias: Some("date".to_string()),
                        expression: None,
                        transform: None,
                        agg: None,
                        case: None,
                        coalesce: None,
                    },
                ],
                ..Default::default()
            };
            
            b.iter(|| {
                let result = engine.execute(black_box(&dsl)).unwrap();
                black_box(result);
            });
        });
    }
    
    group.finish();
}

/// Benchmark filtered query
fn bench_filtered_select(c: &mut Criterion) {
    let mut group = c.benchmark_group("filtered_select");
    
    for size in [100, 1_000, 10_000].iter() {
        group.bench_with_input(BenchmarkId::from_parameter(size), size, |b, &size| {
            let conn = setup_db_with_n_orders(size);
            let engine = QueryEngine::new(&conn);
            
            let dsl = QueryDsl {
                from: Some(Source {
                    source_file: "orders.json".to_string(),
                    alias: Some("o".to_string()),
                    explode: None,
                    explode_with_context: None,
                    as_primitive: None,
                }),
                r#where: Some(vec![Condition {
                    field: "o.businessDate".to_string(),
                    op: "=".to_string(),
                    value: Some(json!("2024-01-15")),
                    values: None,
                }]),
                select: vec![
                    SelectField {
                        expr: Some("o.guid".to_string()),
                        alias: Some("guid".to_string()),
                        expression: None,
                        transform: None,
                        agg: None,
                        case: None,
                        coalesce: None,
                    },
                ],
                ..Default::default()
            };
            
            b.iter(|| {
                let result = engine.execute(black_box(&dsl)).unwrap();
                black_box(result);
            });
        });
    }
    
    group.finish();
}

/// Benchmark array explosion
fn bench_array_explosion(c: &mut Criterion) {
    let mut group = c.benchmark_group("array_explosion");
    
    for size in [100, 1_000, 5_000].iter() {
        group.bench_with_input(BenchmarkId::from_parameter(size), size, |b, &size| {
            let conn = setup_db_with_n_orders(size);
            let engine = QueryEngine::new(&conn);
            
            // Explode checks - each order has 2 checks
            let dsl = QueryDsl {
                from: Some(Source {
                    source_file: "orders.json".to_string(),
                    alias: Some("o".to_string()),
                    explode: Some("checks".to_string()),
                    explode_with_context: None,
                    as_primitive: None,
                }),
                select: vec![
                    SelectField {
                        expr: Some("o.guid".to_string()),
                        alias: Some("order_guid".to_string()),
                        expression: None,
                        transform: None,
                        agg: None,
                        case: None,
                        coalesce: None,
                    },
                    SelectField {
                        expr: Some("o.checks.guid".to_string()),
                        alias: Some("check_guid".to_string()),
                        expression: None,
                        transform: None,
                        agg: None,
                        case: None,
                        coalesce: None,
                    },
                    SelectField {
                        expr: Some("o.checks.amount".to_string()),
                        alias: Some("amount".to_string()),
                        expression: None,
                        transform: None,
                        agg: None,
                        case: None,
                        coalesce: None,
                    },
                ],
                ..Default::default()
            };
            
            b.iter(|| {
                let result = engine.execute(black_box(&dsl)).unwrap();
                black_box(result);
            });
        });
    }
    
    group.finish();
}

/// Benchmark aggregation with group_by
fn bench_group_by(c: &mut Criterion) {
    let mut group = c.benchmark_group("group_by");
    
    for size in [100, 1_000, 10_000].iter() {
        group.bench_with_input(BenchmarkId::from_parameter(size), size, |b, &size| {
            let conn = setup_db_with_n_orders(size);
            let engine = QueryEngine::new(&conn);
            
            // Group by server and count
            let dsl = QueryDsl {
                from: Some(Source {
                    source_file: "orders.json".to_string(),
                    alias: Some("o".to_string()),
                    explode: None,
                    explode_with_context: None,
                    as_primitive: None,
                }),
                group_by: Some(vec![GroupBy {
                    field: "o.server.guid".to_string(),
                    alias: Some("server_guid".to_string()),
                }]),
                select: vec![
                    SelectField {
                        expr: Some("o.server.guid".to_string()),
                        alias: Some("server".to_string()),
                        expression: None,
                        transform: None,
                        agg: None,
                        case: None,
                        coalesce: None,
                    },
                    SelectField {
                        expr: Some("count(o.guid)".to_string()),
                        alias: Some("order_count".to_string()),
                        expression: None,
                        transform: None,
                        agg: Some("count".to_string()),
                        case: None,
                        coalesce: None,
                    },
                ],
                ..Default::default()
            };
            
            b.iter(|| {
                let result = engine.execute(black_box(&dsl)).unwrap();
                black_box(result);
            });
        });
    }
    
    group.finish();
}

/// Benchmark date function extraction
fn bench_date_extraction(c: &mut Criterion) {
    let mut group = c.benchmark_group("date_extraction");
    
    for size in [100, 1_000, 10_000].iter() {
        group.bench_with_input(BenchmarkId::from_parameter(size), size, |b, &size| {
            let conn = setup_db_with_n_orders(size);
            let engine = QueryEngine::new(&conn);
            
            let dsl = QueryDsl {
                from: Some(Source {
                    source_file: "orders.json".to_string(),
                    alias: Some("o".to_string()),
                    explode: None,
                    explode_with_context: None,
                    as_primitive: None,
                }),
                select: vec![
                    SelectField {
                        expr: Some("o.guid".to_string()),
                        alias: Some("guid".to_string()),
                        expression: None,
                        transform: None,
                        agg: None,
                        case: None,
                        coalesce: None,
                    },
                    SelectField {
                        expr: Some("hour(o.closedDate)".to_string()),
                        alias: Some("hour".to_string()),
                        expression: None,
                        transform: None,
                        agg: None,
                        case: None,
                        coalesce: None,
                    },
                    SelectField {
                        expr: Some("date(o.closedDate)".to_string()),
                        alias: Some("date".to_string()),
                        expression: None,
                        transform: None,
                        agg: None,
                        case: None,
                        coalesce: None,
                    },
                ],
                ..Default::default()
            };
            
            b.iter(|| {
                let result = engine.execute(black_box(&dsl)).unwrap();
                black_box(result);
            });
        });
    }
    
    group.finish();
}

/// Benchmark join operation
fn bench_join(c: &mut Criterion) {
    let mut group = c.benchmark_group("join");
    
    for size in [100, 1_000, 5_000].iter() {
        group.bench_with_input(BenchmarkId::from_parameter(size), size, |b, &size| {
            let conn = setup_db_with_n_orders(size);
            
            // Create employees (10 unique servers)
            let mut employees = Vec::new();
            for i in 0..10 {
                employees.push(json!({
                    "guid": format!("server-{:03}", i),
                    "firstName": format!("Server {}", i),
                    "email": format!("server{}@example.com", i)
                }));
            }
            insert_test_data(&conn, "employees.json", employees).unwrap();
            
            let engine = QueryEngine::new(&conn);
            
            let dsl = QueryDsl {
                from: Some(Source {
                    source_file: "orders.json".to_string(),
                    alias: Some("o".to_string()),
                    explode: None,
                    explode_with_context: None,
                    as_primitive: None,
                }),
                joins: vec![Join {
                    source: Some(Source {
                        source_file: "employees.json".to_string(),
                        alias: Some("e".to_string()),
                        explode: None,
                        explode_with_context: None,
                        as_primitive: None,
                    }),
                    subquery: None,
                    alias: None,
                    on: JoinCondition {
                        left: "o.server.guid".to_string(),
                        right: "e.guid".to_string(),
                        op: "=".to_string(),
                    },
                    join_type: "inner".to_string(),
                    r#where: None,
                    skip_nulls: false,
                }],
                select: vec![
                    SelectField {
                        expr: Some("o.guid".to_string()),
                        alias: Some("order_guid".to_string()),
                        expression: None,
                        transform: None,
                        agg: None,
                        case: None,
                        coalesce: None,
                    },
                    SelectField {
                        expr: Some("e.firstName".to_string()),
                        alias: Some("server_name".to_string()),
                        expression: None,
                        transform: None,
                        agg: None,
                        case: None,
                        coalesce: None,
                    },
                ],
                ..Default::default()
            };
            
            b.iter(|| {
                let result = engine.execute(black_box(&dsl)).unwrap();
                black_box(result);
            });
        });
    }
    
    group.finish();
}

/// Benchmark complex multi-operation query
fn bench_complex_query(c: &mut Criterion) {
    let mut group = c.benchmark_group("complex_query");
    
    for size in [100, 1_000, 5_000].iter() {
        group.bench_with_input(BenchmarkId::from_parameter(size), size, |b, &size| {
            let conn = setup_db_with_n_orders(size);
            
            // Add employees
            let mut employees = Vec::new();
            for i in 0..10 {
                employees.push(json!({
                    "guid": format!("server-{:03}", i),
                    "firstName": format!("Server {}", i),
                    "email": format!("server{}@example.com", i)
                }));
            }
            insert_test_data(&conn, "employees.json", employees).unwrap();
            
            let engine = QueryEngine::new(&conn);
            
            // Complex query: join + explode + filter + aggregate
            let dsl = QueryDsl {
                from: Some(Source {
                    source_file: "orders.json".to_string(),
                    alias: Some("o".to_string()),
                    explode: Some("checks".to_string()),
                    explode_with_context: None,
                    as_primitive: None,
                }),
                joins: vec![Join {
                    source: Some(Source {
                        source_file: "employees.json".to_string(),
                        alias: Some("e".to_string()),
                        explode: None,
                        explode_with_context: None,
                        as_primitive: None,
                    }),
                    subquery: None,
                    alias: None,
                    on: JoinCondition {
                        left: "o.server.guid".to_string(),
                        right: "e.guid".to_string(),
                        op: "=".to_string(),
                    },
                    join_type: "inner".to_string(),
                    r#where: None,
                    skip_nulls: false,
                }],
                r#where: Some(vec![Condition {
                    field: "o.checks.voided".to_string(),
                    op: "=".to_string(),
                    value: Some(json!(false)),
                    values: None,
                }]),
                group_by: Some(vec![GroupBy {
                    field: "e.firstName".to_string(),
                    alias: Some("server".to_string()),
                }]),
                select: vec![
                    SelectField {
                        expr: Some("e.firstName".to_string()),
                        alias: Some("server".to_string()),
                        expression: None,
                        transform: None,
                        agg: None,
                        case: None,
                        coalesce: None,
                    },
                    SelectField {
                        expr: Some("sum(o.checks.amount)".to_string()),
                        alias: Some("total_sales".to_string()),
                        expression: None,
                        transform: None,
                        agg: Some("sum".to_string()),
                        case: None,
                        coalesce: None,
                    },
                    SelectField {
                        expr: Some("count(o.checks.guid)".to_string()),
                        alias: Some("check_count".to_string()),
                        expression: None,
                        transform: None,
                        agg: Some("count".to_string()),
                        case: None,
                        coalesce: None,
                    },
                ],
                ..Default::default()
            };
            
            b.iter(|| {
                let result = engine.execute(black_box(&dsl)).unwrap();
                black_box(result);
            });
        });
    }
    
    group.finish();
}

criterion_group!(
    benches,
    bench_simple_select,
    bench_filtered_select,
    bench_array_explosion,
    bench_group_by,
    bench_date_extraction,
    bench_join,
    bench_complex_query
);
criterion_main!(benches);
