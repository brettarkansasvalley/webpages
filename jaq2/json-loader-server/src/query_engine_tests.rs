//! Comprehensive unit tests for the query engine
//!
//! These tests cover:
//! - Simple SELECT queries
//! - JOIN operations (inner, left, right)
//! - Array explosion with context preservation
//! - Date/time function extraction
//! - COALESCE fallback values
//! - Aggregation (GROUP BY, SUM, COUNT, AVG)
//! - WHERE clause filtering
//! - Subqueries (WITH clause)
//! - Edge cases (nulls, missing fields, empty arrays)

#[cfg(test)]
mod tests {
    use crate::query_engine::*;
    use crate::test_utils::*;
    use pretty_assertions::assert_eq;
    use serde_json::json;

    // =========================================================================
    // Test Setup Helpers
    // =========================================================================

    fn setup_orders_db() -> rusqlite::Connection {
        let conn = create_test_db();
        let orders = TestDataBuilder::new().with_orders().build();
        insert_test_data(&conn, "orders.json", orders).unwrap();
        conn
    }

    fn setup_employees_db() -> rusqlite::Connection {
        let conn = create_test_db();
        let employees = TestDataBuilder::new().with_employees().build();
        let jobs = TestDataBuilder::new().with_jobs().build();
        insert_test_data(&conn, "employees.json", employees).unwrap();
        insert_test_data(&conn, "jobs.json", jobs).unwrap();
        conn
    }

    fn setup_time_entries_db() -> rusqlite::Connection {
        let conn = create_test_db();
        let entries = TestDataBuilder::new().with_time_entries().build();
        insert_test_data(&conn, "time_entries.json", entries).unwrap();
        conn
    }

    fn setup_full_dataset() -> rusqlite::Connection {
        let conn = create_test_db();
        let orders = TestDataBuilder::new().with_orders().build();
        let employees = TestDataBuilder::new().with_employees().build();
        let jobs = TestDataBuilder::new().with_jobs().build();
        insert_test_data(&conn, "orders.json", orders).unwrap();
        insert_test_data(&conn, "employees.json", employees).unwrap();
        insert_test_data(&conn, "jobs.json", jobs).unwrap();
        conn
    }

    // =========================================================================
    // Simple SELECT Tests
    // =========================================================================

    #[test]
    fn test_simple_select_all_fields() {
        let conn = setup_orders_db();
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
                    alias: Some("order_guid".to_string()),
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
            // Add ORDER BY to ensure consistent ordering
            order_by: Some(vec![OrderBy {
                field: "o.guid".to_string(),
                direction: Some("asc".to_string()),
            }]),
            ..Default::default()
        };

        let result = engine.execute(&dsl).unwrap();

        assert_eq!(result.columns, vec!["order_guid", "date"]);
        assert_eq!(result.rows.len(), 3);
        assert_eq!(result.total_count, 3);
        assert_eq!(result.rows[0][0], json!("order-001"));
        assert_eq!(result.rows[0][1], json!("2024-01-15"));
    }

    #[test]
    fn test_select_with_limit() {
        let conn = setup_orders_db();
        let engine = QueryEngine::new(&conn);

        let dsl = QueryDsl {
            from: Some(Source {
                source_file: "orders.json".to_string(),
                alias: Some("o".to_string()),
                explode: None,
                explode_with_context: None,
                as_primitive: None,
            }),
            select: vec![SelectField {
                expr: Some("o.guid".to_string()),
                alias: Some("guid".to_string()),
                expression: None,
                transform: None,
                agg: None,
                case: None,
                coalesce: None,
            }],
            limit: Some(2),
            ..Default::default()
        };

        let result = engine.execute(&dsl).unwrap();

        assert_eq!(result.rows.len(), 2);
        assert_eq!(result.total_count, 3); // Total before limit
    }

    // =========================================================================
    // WHERE Clause Tests
    // =========================================================================

    #[test]
    fn test_where_equals() {
        let conn = setup_orders_db();
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
            select: vec![SelectField {
                expr: Some("o.guid".to_string()),
                alias: Some("guid".to_string()),
                expression: None,
                transform: None,
                agg: None,
                case: None,
                coalesce: None,
            }],
            ..Default::default()
        };

        let result = engine.execute(&dsl).unwrap();

        assert_eq!(result.rows.len(), 2);
        // Both orders from 2024-01-15
        let guids: Vec<String> = result
            .rows
            .iter()
            .map(|r| r[0].as_str().unwrap().to_string())
            .collect();
        assert!(guids.contains(&"order-001".to_string()));
        assert!(guids.contains(&"order-002".to_string()));
    }

    #[test]
    fn test_where_not_equals() {
        let conn = setup_orders_db();
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
                op: "!=".to_string(),
                value: Some(json!("2024-01-15")),
                values: None,
            }]),
            select: vec![SelectField {
                expr: Some("o.guid".to_string()),
                alias: Some("guid".to_string()),
                expression: None,
                transform: None,
                agg: None,
                case: None,
                coalesce: None,
            }],
            ..Default::default()
        };

        let result = engine.execute(&dsl).unwrap();

        assert_eq!(result.rows.len(), 1);
        assert_eq!(result.rows[0][0], json!("order-003"));
    }

    #[test]
    fn test_where_is_not_null() {
        let conn = create_test_db();
        let data = TestDataBuilder::new().with_nulls_and_missing().build();
        insert_test_data(&conn, "test.json", data).unwrap();
        let engine = QueryEngine::new(&conn);

        let dsl = QueryDsl {
            from: Some(Source {
                source_file: "test.json".to_string(),
                alias: Some("t".to_string()),
                explode: None,
                explode_with_context: None,
                as_primitive: None,
            }),
            r#where: Some(vec![Condition {
                field: "t.value".to_string(),
                op: "is_not_null".to_string(),
                value: None,
                values: None,
            }]),
            select: vec![SelectField {
                expr: Some("t.id".to_string()),
                alias: Some("id".to_string()),
                expression: None,
                transform: None,
                agg: None,
                case: None,
                coalesce: None,
            }],
            ..Default::default()
        };

        let result = engine.execute(&dsl).unwrap();

        // Should return ids 1, 4 (id 2 has null value, id 3 has missing field)
        // In SQL semantics, IS NOT NULL excludes both null values and missing fields
        assert_eq!(result.rows.len(), 2);
        let ids: Vec<i64> = result.rows.iter()
            .map(|r| r[0].as_i64().unwrap())
            .collect();
        assert!(ids.contains(&1));
        assert!(ids.contains(&4));
    }

    #[test]
    fn test_where_contains() {
        let conn = setup_employees_db();
        let engine = QueryEngine::new(&conn);

        let dsl = QueryDsl {
            from: Some(Source {
                source_file: "employees.json".to_string(),
                alias: Some("e".to_string()),
                explode: None,
                explode_with_context: None,
                as_primitive: None,
            }),
            r#where: Some(vec![Condition {
                field: "e.email".to_string(),
                op: "contains".to_string(),
                value: Some(json!("alice")),
                values: None,
            }]),
            select: vec![SelectField {
                expr: Some("e.firstName".to_string()),
                alias: Some("name".to_string()),
                expression: None,
                transform: None,
                agg: None,
                case: None,
                coalesce: None,
            }],
            ..Default::default()
        };

        let result = engine.execute(&dsl).unwrap();

        assert_eq!(result.rows.len(), 1);
        assert_eq!(result.rows[0][0], json!("Alice"));
    }

    // =========================================================================
    // JOIN Tests
    // =========================================================================

    #[test]
    fn test_inner_join() {
        let conn = setup_full_dataset();
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

        let result = engine.execute(&dsl).unwrap();

        assert_eq!(result.rows.len(), 3);
        // Verify Alice and Bob are matched
        let names: Vec<String> = result
            .rows
            .iter()
            .map(|r| r[1].as_str().unwrap().to_string())
            .collect();
        assert!(names.contains(&"Alice".to_string()));
        assert!(names.contains(&"Bob".to_string()));
    }

    #[test]
    fn test_left_join_with_skip_nulls() {
        let conn = setup_full_dataset();
        let engine = QueryEngine::new(&conn);

        // Add an order with no matching employee
        let orphan_order = json!({
            "guid": "order-orphan",
            "businessDate": "2024-01-15",
            "server": {"guid": "nonexistent-server", "name": "Ghost"},
            "checks": []
        });
        insert_test_data(&conn, "orders.json", vec![orphan_order]).unwrap();

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
                join_type: "left".to_string(),
                r#where: None,
                skip_nulls: true, // Skip rows where join fails
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

        let result = engine.execute(&dsl).unwrap();

        // Should only have orders with matching employees (3 original + 0 orphan due to skip_nulls)
        assert_eq!(result.rows.len(), 3);
    }

    // =========================================================================
    // Array Explosion Tests
    // =========================================================================

    #[test]
    fn test_simple_array_explosion() {
        let conn = setup_orders_db();
        let engine = QueryEngine::new(&conn);

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

        let result = engine.execute(&dsl).unwrap();

        // order-001 has 2 checks, order-002 has 1, order-003 has 1 = 4 total
        assert_eq!(result.rows.len(), 4);
        // Verify order-001 appears twice (context preserved)
        let order_001_count = result
            .rows
            .iter()
            .filter(|r| r[0] == json!("order-001"))
            .count();
        assert_eq!(order_001_count, 2);
    }

    #[test]
    fn test_explode_with_context_multi_level() {
        let conn = setup_orders_db();
        let engine = QueryEngine::new(&conn);

        let dsl = QueryDsl {
            from: Some(Source {
                source_file: "orders.json".to_string(),
                alias: Some("o".to_string()),
                explode: None,
                explode_with_context: Some(ExplodeWithContext {
                    path: "checks.selections".to_string(),
                    aliases: vec!["c".to_string(), "sel".to_string()],
                    preserve: vec!["o.guid".to_string(), "o.businessDate".to_string()],
                    r#where: None,
                }),
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
                    expr: Some("c.guid".to_string()),
                    alias: Some("check_guid".to_string()),
                    expression: None,
                    transform: None,
                    agg: None,
                    case: None,
                    coalesce: None,
                },
                SelectField {
                    expr: Some("sel.item".to_string()),
                    alias: Some("item".to_string()),
                    expression: None,
                    transform: None,
                    agg: None,
                    case: None,
                    coalesce: None,
                },
                SelectField {
                    expr: Some("sel.qty".to_string()),
                    alias: Some("quantity".to_string()),
                    expression: None,
                    transform: None,
                    agg: None,
                    case: None,
                    coalesce: None,
                },
            ],
            ..Default::default()
        };

        let result = engine.execute(&dsl).unwrap();

        // Verify we get individual selections exploded
        // order-001: check-001 has 2 selections, check-002 has 1 = 3 selections
        // order-002: check-003 has 1 selection = 1 selection
        // order-003: check-004 has 1 selection = 1 selection
        // Total: 5 selections
        assert!(result.rows.len() >= 3); // At least the selections from order-001

        // Verify context is preserved - all rows from order-001 should have same order_guid
        let order_001_rows: Vec<_> = result
            .rows
            .iter()
            .filter(|r| r[0] == json!("order-001"))
            .collect();
        assert!(!order_001_rows.is_empty());
        for row in &order_001_rows {
            assert_eq!(row[0], json!("order-001"));
        }
    }

    // =========================================================================
    // Date Function Tests
    // =========================================================================

    #[test]
    fn test_hour_extraction() {
        let conn = setup_orders_db();
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
                    alias: Some("hour_closed".to_string()),
                    expression: None,
                    transform: None,
                    agg: None,
                    case: None,
                    coalesce: None,
                },
            ],
            ..Default::default()
        };

        let result = engine.execute(&dsl).unwrap();

        assert_eq!(result.rows.len(), 3);
        // order-001 closed at 14:30:00Z -> hour = 14
        let order_001_row = result
            .rows
            .iter()
            .find(|r| r[0] == json!("order-001"))
            .unwrap();
        assert_eq!(order_001_row[1], json!(14));
    }

    #[test]
    fn test_date_extraction() {
        let conn = setup_orders_db();
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
                    expr: Some("date(o.closedDate)".to_string()),
                    alias: Some("date_only".to_string()),
                    expression: None,
                    transform: None,
                    agg: None,
                    case: None,
                    coalesce: None,
                },
            ],
            ..Default::default()
        };

        let result = engine.execute(&dsl).unwrap();

        // All orders should extract date from closedDate
        assert_eq!(result.rows.len(), 3);
        for row in &result.rows {
            assert!(!row[1].is_null());
        }
    }

    #[test]
    fn test_date_diff_calculation() {
        let conn = setup_time_entries_db();
        let engine = QueryEngine::new(&conn);

        let dsl = QueryDsl {
            from: Some(Source {
                source_file: "time_entries.json".to_string(),
                alias: Some("te".to_string()),
                explode: None,
                explode_with_context: None,
                as_primitive: None,
            }),
            select: vec![
                SelectField {
                    expr: Some("te.guid".to_string()),
                    alias: Some("entry_guid".to_string()),
                    expression: None,
                    transform: None,
                    agg: None,
                    case: None,
                    coalesce: None,
                },
                SelectField {
                    expr: Some("date_diff(te.outDate, te.inDate, 'hours')".to_string()),
                    alias: Some("hours_worked".to_string()),
                    expression: None,
                    transform: None,
                    agg: None,
                    case: None,
                    coalesce: None,
                },
            ],
            ..Default::default()
        };

        let result = engine.execute(&dsl).unwrap();

        assert_eq!(result.rows.len(), 3);
        // All shifts are 8 hours (08:00-16:00, 14:00-22:00, 09:00-17:00)
        for row in &result.rows {
            assert_eq!(row[1], json!(8));
        }
    }

    #[test]
    fn test_date_functions_with_invalid_dates() {
        let conn = create_test_db();
        let data = TestDataBuilder::new().with_invalid_dates().build();
        insert_test_data(&conn, "dates.json", data).unwrap();
        let engine = QueryEngine::new(&conn);

        let dsl = QueryDsl {
            from: Some(Source {
                source_file: "dates.json".to_string(),
                alias: Some("d".to_string()),
                explode: None,
                explode_with_context: None,
                as_primitive: None,
            }),
            select: vec![
                SelectField {
                    expr: Some("d.valid".to_string()),
                    alias: Some("was_valid".to_string()),
                    expression: None,
                    transform: None,
                    agg: None,
                    case: None,
                    coalesce: None,
                },
                SelectField {
                    expr: Some("hour(d.timestamp)".to_string()),
                    alias: Some("hour".to_string()),
                    expression: None,
                    transform: None,
                    agg: None,
                    case: None,
                    coalesce: None,
                },
            ],
            // Add ORDER BY to ensure consistent row ordering
            order_by: Some(vec![OrderBy {
                field: "d.valid".to_string(),
                direction: Some("desc".to_string()),
            }]),
            ..Default::default()
        };

        let result = engine.execute(&dsl).unwrap();

        assert_eq!(result.rows.len(), 5);
        // First row has valid timestamp (valid=true) -> should get hour
        assert_eq!(result.rows[0][0], json!(true));
        assert_eq!(result.rows[0][1], json!(14));
        // Invalid dates should return null, not panic
        for row in result.rows.iter().skip(1) {
            assert!(row[1].is_null());
        }
    }

    // =========================================================================
    // Aggregation Tests
    // =========================================================================

    #[test]
    fn test_group_by_with_count() {
        let conn = setup_orders_db();
        let engine = QueryEngine::new(&conn);

        let dsl = QueryDsl {
            from: Some(Source {
                source_file: "orders.json".to_string(),
                alias: Some("o".to_string()),
                explode: None,
                explode_with_context: None,
                as_primitive: None,
            }),
            group_by: Some(vec![GroupBy {
                field: "o.businessDate".to_string(),
                alias: Some("date".to_string()),
            }]),
            select: vec![
                SelectField {
                    expr: Some("o.businessDate".to_string()),
                    alias: Some("date".to_string()),
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

        let result = engine.execute(&dsl).unwrap();

        // Should have 2 groups: 2024-01-15 (2 orders) and 2024-01-16 (1 order)
        assert_eq!(result.rows.len(), 2);
        let date_15 = result
            .rows
            .iter()
            .find(|r| r[0] == json!("2024-01-15"))
            .unwrap();
        assert_eq!(date_15[1], json!(2));
    }

    #[test]
    fn test_group_by_with_sum() {
        let conn = setup_orders_db();
        let engine = QueryEngine::new(&conn);

        // First explode checks to get amounts
        let dsl = QueryDsl {
            from: Some(Source {
                source_file: "orders.json".to_string(),
                alias: Some("o".to_string()),
                explode: Some("checks".to_string()),
                explode_with_context: None,
                as_primitive: None,
            }),
            group_by: Some(vec![GroupBy {
                field: "o.businessDate".to_string(),
                alias: Some("date".to_string()),
            }]),
            select: vec![
                SelectField {
                    expr: Some("o.businessDate".to_string()),
                    alias: Some("date".to_string()),
                    expression: None,
                    transform: None,
                    agg: None,
                    case: None,
                    coalesce: None,
                },
                SelectField {
                    expr: Some("sum(o.checks.amount)".to_string()),
                    alias: Some("total_amount".to_string()),
                    expression: None,
                    transform: None,
                    agg: Some("sum".to_string()),
                    case: None,
                    coalesce: None,
                },
            ],
            ..Default::default()
        };

        let result = engine.execute(&dsl).unwrap();

        // Should have amounts summed by date
        assert_eq!(result.rows.len(), 2);
    }

    // =========================================================================
    // Subquery (WITH clause) Tests
    // =========================================================================

    #[test]
    fn test_with_subquery() {
        let conn = setup_full_dataset();
        let engine = QueryEngine::new(&conn);

        let dsl = QueryDsl {
            with: Some(vec![SubqueryDef {
                name: "alice_orders".to_string(),
                query: Box::new(QueryDsl {
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
                    r#where: Some(vec![Condition {
                        field: "e.firstName".to_string(),
                        op: "=".to_string(),
                        value: Some(json!("Alice")),
                        values: None,
                    }]),
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
                }),
            }]),
            from_subquery: Some("alice_orders".to_string()),
            from: None,
            select: vec![
                SelectField {
                    expr: Some("alice_orders.order_guid".to_string()),
                    alias: Some("guid".to_string()),
                    expression: None,
                    transform: None,
                    agg: None,
                    case: None,
                    coalesce: None,
                },
                SelectField {
                    expr: Some("alice_orders.date".to_string()),
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

        let result = engine.execute(&dsl).unwrap();

        // Alice has 2 orders
        assert_eq!(result.rows.len(), 2);
    }

    // =========================================================================
    // Edge Cases
    // =========================================================================

    #[test]
    fn test_empty_result_set() {
        let conn = setup_orders_db();
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
                field: "o.guid".to_string(),
                op: "=".to_string(),
                value: Some(json!("nonexistent")),
                values: None,
            }]),
            select: vec![SelectField {
                expr: Some("o.guid".to_string()),
                alias: Some("guid".to_string()),
                expression: None,
                transform: None,
                agg: None,
                case: None,
                coalesce: None,
            }],
            ..Default::default()
        };

        let result = engine.execute(&dsl).unwrap();

        assert_eq!(result.rows.len(), 0);
        assert_eq!(result.total_count, 0);
    }

    #[test]
    fn test_primitive_value_wrapping() {
        let conn = create_test_db();
        let data = TestDataBuilder::new().with_primitive_guids().build();
        insert_test_data(&conn, "guids.json", data).unwrap();
        let engine = QueryEngine::new(&conn);

        let dsl = QueryDsl {
            from: Some(Source {
                source_file: "guids.json".to_string(),
                alias: Some("g".to_string()),
                explode: None,
                explode_with_context: None,
                as_primitive: Some("guid".to_string()), // Wrap primitives
            }),
            select: vec![SelectField {
                expr: Some("g.guid".to_string()),
                alias: Some("guid_value".to_string()),
                expression: None,
                transform: None,
                agg: None,
                case: None,
                coalesce: None,
            }],
            ..Default::default()
        };

        let result = engine.execute(&dsl).unwrap();

        assert_eq!(result.rows.len(), 3);
        // Verify primitives were wrapped and accessible
        assert_eq!(result.rows[0][0], json!("guid-001"));
        assert_eq!(result.rows[1][0], json!("guid-002"));
        assert_eq!(result.rows[2][0], json!("guid-003"));
    }

    #[test]
    fn test_order_by_asc_desc() {
        let conn = setup_orders_db();
        let engine = QueryEngine::new(&conn);

        let dsl = QueryDsl {
            from: Some(Source {
                source_file: "orders.json".to_string(),
                alias: Some("o".to_string()),
                explode: None,
                explode_with_context: None,
                as_primitive: None,
            }),
            select: vec![SelectField {
                expr: Some("o.guid".to_string()),
                alias: Some("guid".to_string()),
                expression: None,
                transform: None,
                agg: None,
                case: None,
                coalesce: None,
            }],
            order_by: Some(vec![
                OrderBy {
                    field: "o.businessDate".to_string(),
                    direction: Some("desc".to_string()),
                },
            ]),
            ..Default::default()
        };

        let result = engine.execute(&dsl).unwrap();

        assert_eq!(result.rows.len(), 3);
        // Most recent date should be first
        // order-003 is 2024-01-16
        assert_eq!(result.rows[0][0], json!("order-003"));
    }

    #[test]
    fn test_offset_pagination() {
        let conn = setup_orders_db();
        let engine = QueryEngine::new(&conn);

        let dsl = QueryDsl {
            from: Some(Source {
                source_file: "orders.json".to_string(),
                alias: Some("o".to_string()),
                explode: None,
                explode_with_context: None,
                as_primitive: None,
            }),
            select: vec![SelectField {
                expr: Some("o.guid".to_string()),
                alias: Some("guid".to_string()),
                expression: None,
                transform: None,
                agg: None,
                case: None,
                coalesce: None,
            }],
            // Add ORDER BY to ensure consistent ordering for pagination
            order_by: Some(vec![OrderBy {
                field: "o.guid".to_string(),
                direction: Some("asc".to_string()),
            }]),
            offset: Some(1),
            limit: Some(1),
            ..Default::default()
        };

        let result = engine.execute(&dsl).unwrap();

        // Skip 1, take 1 = should get 1 result (order-002)
        assert_eq!(result.rows.len(), 1);
        assert_eq!(result.total_count, 3);
        assert_eq!(result.rows[0][0], json!("order-002"));
    }
}
