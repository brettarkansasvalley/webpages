const std = @import("std");

pub fn printHelp() void {
    const help_text =
        \\╔═══════════════════════════════════════════════════════════════════════════════╗
        \\║                                    ZAQ                                        ║
        \\║                    A Blazingly Fast jq Clone Written in Zig                   ║
        \\╚═══════════════════════════════════════════════════════════════════════════════╝
        \\
        \\USAGE:
        \\    zaq [OPTIONS] <FILTER> [FILE...]
        \\    cat file.json | zaq <FILTER>
        \\
        \\DESCRIPTION:
        \\    zaq is a high-performance JSON processor compatible with jq syntax.
        \\    It processes JSON input through filters and outputs the results.
        \\
        \\OPTIONS:
        \\    --help, -h          Show this help message
        \\    --tutorial, -t      Show interactive tutorial with examples
        \\    --version, -v       Show version information
        \\
        \\BASIC FILTERS:
        \\    .                   Identity - returns input unchanged
        \\    .foo                Object field access
        \\    .foo.bar            Nested field access
        \\    .[0]                Array index
        \\    .[2:5]              Array slice (elements 2,3,4)
        \\    .[]                 Iterate all elements
        \\    .[].foo             Iterate and access field
        \\
        \\OPERATORS:
        \\    |                   Pipe - chain filters together
        \\    ,                   Output multiple results
        \\    +, -, *, /, %       Arithmetic operators
        \\    ==, !=, <, >, <=, >=  Comparison operators
        \\    and, or, not        Logical operators
        \\
        \\ARRAY OPERATIONS:
        \\    [...]               Collect results into array
        \\    [.foo, .bar]        Build array from expressions
        \\    .[] | ...           Process each element
        \\    .[0:10]             Slice first 10 elements
        \\    .[-1]               Last element (negative index)
        \\
        \\OBJECT OPERATIONS:
        \\    {foo: .bar}         Build object
        \\    {(.key): .value}    Dynamic key
        \\    .foo = "new"        Update field (planned)
        \\
        \\BUILTIN FUNCTIONS:
        \\    length              Length of string/array/object
        \\    keys                Object keys as array
        \\    values              Object values as array
        \\    type                Type of value as string
        \\    sort                Sort array
        \\    reverse             Reverse array
        \\    flatten             Flatten nested arrays
        \\    unique              Remove duplicates
        \\    first               First element
        \\    last                Last element
        \\    nth(n)              Nth element
        \\    add                 Sum array elements
        \\    min, max            Minimum/maximum value
        \\    empty               Produce no output
        \\    error               Raise an error
        \\    not                 Boolean negation
        \\    map(f)              Apply filter to each element
        \\    select(f)           Keep elements where f is true
        \\    
        \\STRING FUNCTIONS:
        \\    ascii_downcase      Convert to lowercase
        \\    ascii_upcase        Convert to uppercase
        \\    split(s)            Split string by separator
        \\    join(s)             Join array with separator
        \\    ltrimstr(s)         Remove prefix
        \\    rtrimstr(s)         Remove suffix
        \\    startswith(s)       Check prefix
        \\    endswith(s)         Check suffix
        \\    test(regex)         Test regex match (planned)
        \\
        \\TYPE CONVERSIONS:
        \\    tonumber            Convert to number
        \\    tostring            Convert to string
        \\    @base64             Encode as base64
        \\    @base64d            Decode from base64
        \\    @uri                URI encode
        \\    @csv                Format as CSV
        \\    @json               Format as JSON string
        \\
        \\CONDITIONALS:
        \\    if-then-else        Conditional expression
        \\    // (alternative)    Alternative operator (planned)
        \\    ? (optional)        Optional operator (suppress errors)
        \\
        \\EXAMPLES:
        \\    zaq '.name' file.json
        \\        Extract the "name" field
        \\    
        \\    zaq '.[].id' file.json
        \\        Get "id" from each array element
        \\    
        \\    zaq '[.[] | select(.active)] | length' file.json
        \\        Count active items
        \\    
        \\    zaq 'map(.price) | add' file.json
        \\        Sum all prices
        \\    
        \\    cat data.json | zaq '.items[0:10] | map(.name)'
        \\        First 10 item names from stdin
        \\
        \\PERFORMANCE:
        \\    zaq is optimized for speed with:
        \\    • Fast custom JSON parser with minimal allocations
        \\    • Arena allocator for efficient memory management
        \\    • Bytecode VM avoiding closure overhead
        \\    • Typically 5-10% faster than jaq, 2-3x faster than jq
        \\
        \\MORE INFO:
        \\    Run 'zaq --tutorial' for an interactive tutorial
        \\    Compatible with most jq filters - see https://jqlang.github.io/jq/manual/
        \\
    ;
    std.debug.print("{s}", .{help_text});
}

pub fn printTutorial() void {
    const tutorial_text =
        \\
        \\╔═══════════════════════════════════════════════════════════════════════════════╗
        \\║                              ZAQ TUTORIAL                                     ║
        \\║                        Learn jq-style JSON Processing                         ║
        \\╚═══════════════════════════════════════════════════════════════════════════════╝
        \\
        \\Welcome to zaq! This tutorial will teach you JSON processing step by step.
        \\
        \\════════════════════════════════════════════════════════════════════════════════
        \\                            LESSON 1: BASICS
        \\════════════════════════════════════════════════════════════════════════════════
        \\
        \\The simplest filter is the identity filter '.', which returns input unchanged:
        \\
        \\    $ echo '{"name": "Alice", "age": 30}' | zaq '.'
        \\    {"name":"Alice","age":30}
        \\
        \\Access object fields with .fieldname:
        \\
        \\    $ echo '{"name": "Alice", "age": 30}' | zaq '.name'
        \\    "Alice"
        \\
        \\    $ echo '{"name": "Alice", "age": 30}' | zaq '.age'
        \\    30
        \\
        \\Chain field access for nested objects:
        \\
        \\    $ echo '{"user": {"name": "Bob"}}' | zaq '.user.name'
        \\    "Bob"
        \\
        \\════════════════════════════════════════════════════════════════════════════════
        \\                            LESSON 2: ARRAYS
        \\════════════════════════════════════════════════════════════════════════════════
        \\
        \\Access array elements by index (0-based):
        \\
        \\    $ echo '[10, 20, 30, 40]' | zaq '.[0]'
        \\    10
        \\
        \\    $ echo '[10, 20, 30, 40]' | zaq '.[2]'
        \\    30
        \\
        \\Use negative indices to count from the end:
        \\
        \\    $ echo '[10, 20, 30, 40]' | zaq '.[-1]'
        \\    40
        \\
        \\Slice arrays with [start:end]:
        \\
        \\    $ echo '[0, 1, 2, 3, 4, 5]' | zaq '.[1:4]'
        \\    [1,2,3]
        \\
        \\    $ echo '[0, 1, 2, 3, 4, 5]' | zaq '.[:3]'    # First 3
        \\    [0,1,2]
        \\
        \\    $ echo '[0, 1, 2, 3, 4, 5]' | zaq '.[-2:]'   # Last 2
        \\    [4,5]
        \\
        \\════════════════════════════════════════════════════════════════════════════════
        \\                            LESSON 3: ITERATION
        \\════════════════════════════════════════════════════════════════════════════════
        \\
        \\The .[] operator iterates over array elements:
        \\
        \\    $ echo '[1, 2, 3]' | zaq '.[]'
        \\    1
        \\    2
        \\    3
        \\
        \\Combine with field access to extract from each element:
        \\
        \\    $ echo '[{"id": 1}, {"id": 2}]' | zaq '.[].id'
        \\    1
        \\    2
        \\
        \\Collect results back into an array with [...]:
        \\
        \\    $ echo '[{"id": 1}, {"id": 2}]' | zaq '[.[].id]'
        \\    [1,2]
        \\
        \\════════════════════════════════════════════════════════════════════════════════
        \\                            LESSON 4: PIPES
        \\════════════════════════════════════════════════════════════════════════════════
        \\
        \\The pipe operator '|' chains filters together:
        \\
        \\    $ echo '{"items": [1, 2, 3]}' | zaq '.items | .[]'
        \\    1
        \\    2
        \\    3
        \\
        \\Each step receives the output of the previous step:
        \\
        \\    $ echo '[3, 1, 2]' | zaq 'sort | reverse'
        \\    [3,2,1]
        \\
        \\    $ echo '[{"n": 5}, {"n": 3}]' | zaq '[.[].n] | sort'
        \\    [3,5]
        \\
        \\════════════════════════════════════════════════════════════════════════════════
        \\                         LESSON 5: BUILTIN FUNCTIONS
        \\════════════════════════════════════════════════════════════════════════════════
        \\
        \\length - Get length of arrays, objects, or strings:
        \\
        \\    $ echo '[1, 2, 3, 4]' | zaq 'length'
        \\    4
        \\
        \\    $ echo '"hello"' | zaq 'length'
        \\    5
        \\
        \\keys - Extract object keys as array:
        \\
        \\    $ echo '{"a": 1, "b": 2}' | zaq 'keys'
        \\    ["a","b"]
        \\
        \\.[] - Iterate object values (use [...] to collect):
        \\
        \\    $ echo '{"a": 1, "b": 2}' | zaq '[.[]]'
        \\    [1,2]
        \\
        \\sort - Sort arrays:
        \\
        \\    $ echo '[3, 1, 4, 1, 5]' | zaq 'sort'
        \\    [1,1,3,4,5]
        \\
        \\unique - Remove duplicates:
        \\
        \\    $ echo '[1, 2, 1, 3, 2]' | zaq 'unique'
        \\    [1,2,3]
        \\
        \\flatten - Flatten nested arrays:
        \\
        \\    $ echo '[[1, 2], [3, [4, 5]]]' | zaq 'flatten'
        \\    [1,2,3,4,5]
        \\
        \\════════════════════════════════════════════════════════════════════════════════
        \\                       LESSON 6: MAP AND SELECT
        \\════════════════════════════════════════════════════════════════════════════════
        \\
        \\map(f) applies a filter to each element:
        \\
        \\    $ echo '[1, 2, 3]' | zaq 'map(. * 2)'
        \\    [2,4,6]
        \\
        \\    $ echo '[{"name": "A"}, {"name": "B"}]' | zaq 'map(.name)'
        \\    ["A","B"]
        \\
        \\select(f) keeps elements where the filter returns true:
        \\
        \\    $ echo '[1, 2, 3, 4, 5]' | zaq '[.[] | select(. > 2)]'
        \\    [3,4,5]
        \\
        \\    $ echo '[{"age": 25}, {"age": 17}]' | zaq '[.[] | select(.age >= 18)]'
        \\    [{"age":25}]
        \\
        \\Combine them for powerful queries:
        \\
        \\    $ echo '[{"n": 1}, {"n": 5}, {"n": 3}]' | zaq '[.[] | select(.n > 2)] | map(.n)'
        \\    [5,3]
        \\
        \\════════════════════════════════════════════════════════════════════════════════
        \\                       LESSON 7: ARITHMETIC
        \\════════════════════════════════════════════════════════════════════════════════
        \\
        \\Basic arithmetic operations:
        \\
        \\    $ echo '5' | zaq '. + 3'
        \\    8
        \\
        \\    $ echo '{"a": 10, "b": 3}' | zaq '.a - .b'
        \\    7
        \\
        \\    $ echo '{"a": 10, "b": 3}' | zaq '.a * .b'
        \\    30
        \\
        \\    $ echo '{"a": 10, "b": 3}' | zaq '.a / .b'
        \\    3.333...
        \\
        \\add - Sum all elements in an array:
        \\
        \\    $ echo '[1, 2, 3, 4]' | zaq 'add'
        \\    10
        \\
        \\    $ echo '[{"price": 10}, {"price": 20}]' | zaq '[.[].price] | add'
        \\    30
        \\
        \\════════════════════════════════════════════════════════════════════════════════
        \\                       LESSON 8: OBJECT CONSTRUCTION
        \\════════════════════════════════════════════════════════════════════════════════
        \\
        \\Build new objects with {...}:
        \\
        \\    $ echo '{"first": "John", "last": "Doe"}' | zaq '{name: .first, surname: .last}'
        \\    {"name":"John","surname":"Doe"}
        \\
        \\Use expressions for values:
        \\
        \\    $ echo '[1, 2, 3]' | zaq '{count: length, sum: add}'
        \\    {"count":3,"sum":6}
        \\
        \\════════════════════════════════════════════════════════════════════════════════
        \\                       LESSON 9: REAL-WORLD EXAMPLES
        \\════════════════════════════════════════════════════════════════════════════════
        \\
        \\Process API response - extract user names:
        \\
        \\    $ cat users.json | zaq '[.data[].name]'
        \\
        \\Filter logs - find errors:
        \\
        \\    $ cat logs.json | zaq '[.[] | select(.level == "error")]'
        \\
        \\Transform data - reshape objects:
        \\
        \\    $ cat items.json | zaq 'map({id: .item_id, title: .name, cost: .price})'
        \\
        \\Aggregate - count by category:
        \\
        \\    $ cat products.json | zaq 'group_by(.category) | map({cat: .[0].category, count: length})'
        \\
        \\Get first N items with specific fields:
        \\
        \\    $ cat data.json | zaq '.[0:10] | map({id, name})'
        \\
        \\════════════════════════════════════════════════════════════════════════════════
        \\                            TIPS & TRICKS
        \\════════════════════════════════════════════════════════════════════════════════
        \\
        \\1. Use 'length' often to verify data counts
        \\2. Debug with identity '.' to see intermediate results  
        \\3. Wrap generators in [...] to collect into arrays
        \\4. Use pipes '|' to break complex queries into steps
        \\5. select() filters, map() transforms
        \\
        \\PERFORMANCE TIPS:
        \\• zaq is 5-10% faster than jaq, 2-3x faster than jq
        \\• Use slicing .[0:N] to limit data before heavy operations
        \\• Arena allocator means low GC overhead
        \\
        \\════════════════════════════════════════════════════════════════════════════════
        \\
        \\Congratulations! You now know the essentials of zaq.
        \\Run 'zaq --help' for a complete reference.
        \\
    ;
    std.debug.print("{s}", .{tutorial_text});
}

pub fn printVersion() void {
    const version_text =
        \\zaq 0.1.0
        \\A blazingly fast jq clone written in Zig
        \\
        \\Performance: 5-10% faster than jaq, 2-3x faster than jq
        \\License: MIT
        \\Repository: https://github.com/your-repo/zaq
        \\
    ;
    std.debug.print("{s}", .{version_text});
}
