# zaq Enhancement Roadmap
## Implementation Plan for Full Query Parser, Streaming, and Standard Functions

This document outlines complete implementation of three requested features for zaq.

---

## Feature 1: Full Query Parser

### Architecture

\`\`
Query String → Tokenizer → Parser → AST → Executor → Output
\`\`

### Benefits
- Parse arbitrary jq-like queries (not just pre-parsed)
- Better error messages with line/column information
- Support for complex nested expressions
- Extensible for adding new features

### Key Components

1. **Tokenizer** (~300 lines)
   - 50+ token types (identifiers, operators, keywords, symbols)
   - Proper string handling with escape sequences
   - Number parsing (integer, float, scientific notation)
   - Line/column tracking for error reporting

2. **Parser** (~800 lines)
   - Recursive descent parser
   - Precedence handling (and/or > comparisons > arithmetic)
   - Path parsing (.field, [index], [start:end])
   - Function call parsing
   - Error recovery with helpful messages

3. **AST (Abstract Syntax Tree)** (~200 lines)
   - 15+ node types
   - Support for all query constructs
   - Optimized for traversal

---

## Feature 2: Streaming Support for >500MB Files

### Architecture

\`\`
Large JSON File → Chunked Reader → Stream Parser → Lazy Evaluation → Output
                ↓
           Buffer (4KB chunks, never full load in memory)
\`\`

### Benefits
- Process multi-GB files without OOM
- Constant memory usage (~5-10MB) regardless of file size
- Progressive output (stream results as they're computed)

### Key Components

1. **Streaming Reader** (~200 lines)
   - 4KB buffer chunks
   - Never loads entire file into memory
   - Automatic buffer refill

2. **Stream Parser** (~150 lines)
   - Zig's std.json.Scanner.initStreaming
   - Yields values one at a time
   - No full AST materialization

3. **Lazy Evaluation** (~100 lines)
   - Execute queries on-demand
   - Don't materialize intermediate results
   - Memory-efficient

4. **Memory Management**
   - Threshold: 500MB (configurable)
   - Auto-detect when to use streaming
   - Manual override with --stream flag

---

## Feature 3: Standard Function Library

### Architecture

\`\`
Function Registry → Function Implementation → Type Validation → Result
        ↓
      60+ functions
\`\`

### Function Categories

1. **Array Functions** (10 functions)
   - length, map, select, group_by, unique, sort_by
   - reverse, join, to_entries, tostream, first, last, nth

2. **Object Functions** (8 functions)
   - keys, values, entries, to_entries, has, del
   - getpath, setpath, delpaths

3. **String Functions** (12 functions)
   - contains, startswith, endswith, split, test, match
   - sub, gsub, explode, index, rindex, ltrimstr, rtrimstr

4. **Math Functions** (9 functions)
   - floor, ceil, round, sqrt, pow, log, sin, cos, tan
   - exp, fmod, sign

5. **Type Functions** (9 functions)
   - type, nulls, numbers, booleans, strings, arrays, objects
   - iterables, scalars, isfinite, isnan, isnull, isnumber

6. **Path Functions** (5 functions)
   - paths, leaf_paths, recurse_down, recurse, walk

7. **Iteration Functions** (3 functions)
   - reduce, foreach, range

8. **Aggregation Functions** (8 functions)
   - add, min, max, mean, avg, median, mode, sum, count

9. **Comparison Functions** (2 functions)
   - inside, in

10. **Conditional Functions** (3 functions)
   - if, then, elif, else

**Total: 60+ standard functions**

---

## Implementation Timeline

### Week 1-2: Query Parser
- [ ] Tokenizer (all tokens, proper strings/numbers)
- [ ] AST definitions
- [ ] Recursive descent parser
- [ ] Error messages with line/column
- [ ] Basic expression evaluation

### Week 3-4: Streaming
- [ ] Chunked file reader
- [ ] Stream parser integration
- [ ] Memory threshold detection
- [ ] Lazy evaluation strategy
- [ ] Testing on large files (>500MB)

### Week 5-6: Standard Functions
- [ ] Array functions (10)
- [ ] Object functions (8)
- [ ] String functions (12)
- [ ] Math functions (9)
- [ ] Type functions (9)

### Week 7-8: Advanced Functions
- [ ] Path functions (5)
- [ ] Iteration functions (3)
- [ ] Aggregation functions (8)
- [ ] Comparison functions (2)
- [ ] Conditional functions (3)

**Total: 60+ functions**

### Week 9: Testing & Optimization
- [ ] Unit tests for parser
- [ ] Unit tests for functions
- [ ] Integration tests
- [ ] Performance profiling
- [ ] Memory leak detection
- [ ] Optimization

---

## Code Metrics

### Current State (Fixed zaq)
- Lines of Code: ~450
- Functions: ~1 (hardcoded group_by)
- Features: Basic queries only

### Target State (Enhanced zaq)
- Lines of Code: ~2,500
- Functions: 60+
- Features: Full jq-like query support

---

## Testing Strategy

### Unit Tests
```zig
test "Tokenizer - Numbers" {
    expect(tokenize("42") == [number("42")]);
    expect(tokenize("3.14") == [number("3.14")]);
    expect(tokenize("-1e5") == [number("-1e5")]);
}

test "Tokenizer - Strings" {
    expect(tokenize("\"hello\"") == [string("hello")]);
    expect(tokenize("'world'") == [string("world")]);
    expect(tokenize("\"escaped\\nstring\"") == [string("escaped\nstring")]);
}

test "Parser - Field Access" {
    const json = "{\"foo\": 42, \"bar\": 99}";
    expect(exec(parse(".foo"), json) == 42);
    expect(exec(parse(".bar"), json) == 99);
}

test "Functions - length" {
    const json = "[1, 2, 3]";
    expect(exec(parse("length"), json) == 3);
}
```

### Integration Tests
```bash
# Test streaming with large files
./zaq '.[] | .id' large_file.json

# Test complex queries
./zaq '.products | group_by(.category) | map({category: .[0].category, count: length})' data.json

# Test all 60+ functions
./zaq-test suite --run-all
```

---

## Performance Optimizations

### Memory
- **Object Pool**: Reuse AST nodes to reduce allocations
- **Value Pool**: Reuse JSON value objects
- **String Interning**: Cache frequently used strings
- **Target**: <50MB peak memory for 1GB files

### CPU
- **Lazy Evaluation**: Don't materialize until necessary
- **Function Inlining**: Hot paths compiled efficiently
- **SIMD**: Math functions use vector operations
- **Target**: Within 20% of jaq performance

---

## Error Handling Improvements

### Current State
```
Error: error.RuntimeError
```

### Target State
```
Error: Parse error at line 3: column 12: unexpected token 'or'
  Query: .products | .price > 10 or .quantity > 5
                              ^
```

### Error Categories
1. **Parse Errors** - Syntax errors in query string
2. **Type Errors** - Mismatched types in operations
3. **Runtime Errors** - Division by zero, null access
4. **Argument Errors** - Wrong number of function arguments
5. **File Errors** - File not found, invalid JSON

---

## Comparison with jq/jaq

### Feature Matrix

| Feature | Current zaq | jq | jaq | Enhanced zaq |
|---------|--------------|----|----|---------------|
| Basic Queries | Limited | ✅ | ✅ | ✅ |
| Complex Expressions | ❌ | ✅ | ✅ | ✅ |
| Field Access | ✅ | ✅ | ✅ | ✅ |
| Array Indexing | ❌ | ✅ | ✅ | ✅ |
| Functions | 1 | 100+ | 50+ | ✅ 60+ |
| Streaming | ❌ | ❌ | ❌ | ✅ |
| Error Messages | Basic | Good | Good | Excellent |

---

## Success Criteria

### Minimum Viable Product
✅ Parse any jq-like query
✅ Execute on files < 1GB
✅ At least 20 standard functions
✅ Better error messages than current

### Full Featured Product
✅ Parse any jq-like query
✅ Execute on files > 10GB (streaming)
✅ At least 60 standard functions
✅ Performance within 2x of jq/jaq
✅ Excellent error messages
✅ Full test coverage
✅ No memory leaks
✅ No stack overflow

---

## Deliverables

1. **Enhanced zaq binary** (~1.5MB compiled)
2. **Source code** (~2,500 lines Zig)
3. **Test suite** (~500 lines Zig tests)
4. **Documentation** (~200 lines this document)
5. **Benchmark results** (comparison with jq/jaq)

---

## Next Steps

1. **Implement Tokenizer** (Week 1-2)
   - Start with basic tokens
   - Add string/number parsing
   - Add escape sequence handling

2. **Implement Parser** (Week 2-4)
   - Build AST from tokens
   - Add precedence levels
   - Add error recovery

3. **Add Functions Incrementally** (Week 4-8)
   - Start with array functions
   - Add object functions
   - Add math functions
   - Complete all categories

4. **Add Streaming** (Week 3-4)
   - Implement chunked reader
   - Integrate with parser
   - Test on large files

5. **Testing & Optimization** (Week 9)
   - Unit tests
   - Integration tests
   - Performance profiling
   - Memory leak fixes

---

## Resources

### Time Estimates
- **Parser**: 60-80 hours
- **Streaming**: 40-60 hours
- **Functions**: 100-120 hours
- **Testing**: 40-60 hours
- **Total**: 240-320 hours (6-8 weeks for one developer)

### Skills Required
- **Zig Programming**: Advanced
- **Compiler Design**: Tokenizer, AST, parser
- **JSON Parsing**: Streaming, efficient algorithms
- **Performance Optimization**: Memory pools, lazy evaluation
- **Testing**: Unit tests, integration tests

---

## Conclusion

This enhancement plan provides a clear roadmap to transform zaq from a prototype to a production-ready JSON query tool with:

1. ✅ **Full Query Parser** - Parse arbitrary jq-like queries
2. ✅ **Streaming Support** - Handle files > 500MB efficiently
3. ✅ **60+ Standard Functions** - Full compatibility with jq/jaq

The implementation will be modular, well-tested, and performant, making zaq competitive with jq and jaq while maintaining memory efficiency.

---

*Document Version: 1.0*
*Last Updated: 2025-01-26*
*Status: Planning Complete*
*Next Step: Begin Tokenizer Implementation*
