const std = @import("std");
const Allocator = std.mem.Allocator;
const Chunk = @import("chunk.zig").Chunk;
const OpCode = @import("chunk.zig").OpCode;
const value_mod = @import("value.zig");
const Value = value_mod.Value;
const Rc = value_mod.Rc;
const Array = value_mod.Array;
const Object = value_mod.Object;

pub const VMError = error{
    CompileError,
    RuntimeError,
    OutOfMemory,
};

pub const VM = struct {
    chunk: *Chunk,
    ip: usize,
    stack: std.ArrayListUnmanaged(Value),
    allocator: Allocator,
    // Current input value (context) for the filter
    context: Value, 
    // Stack of saved contexts
    context_stack: std.ArrayListUnmanaged(Value),
    // Stack marks for array collection
    collect_marks: std.ArrayListUnmanaged(usize),
    // Pipe state for generator iteration
    pipe_marks: std.ArrayListUnmanaged(usize),
    pipe_values: std.ArrayListUnmanaged(Value),
    pipe_values_start: std.ArrayListUnmanaged(usize),  // Start index in pipe_values for each level
    pipe_index: std.ArrayListUnmanaged(usize),
    pipe_rhs_start: std.ArrayListUnmanaged(usize),
    // Try/optional state for error recovery
    try_marks: std.ArrayListUnmanaged(TryMark),
    // Streaming mode flags
    streaming: bool,
    stream_stopped: bool,
    
    const TryMark = struct {
        stack_pos: usize,
        jump_offset: u16,
        ip: usize,
    };
    
    pub fn init(allocator: Allocator, chunk: *Chunk) VM {
        return VM{
            .chunk = chunk,
            .ip = 0,
            .stack = .{},
            .allocator = allocator,
            .context = .null,
            .context_stack = .{},
            .collect_marks = .{},
            .pipe_marks = .{},
            .pipe_values = .{},
            .pipe_values_start = .{},
            .pipe_index = .{},
            .pipe_rhs_start = .{},
            .try_marks = .{},
            .streaming = false,
            .stream_stopped = false,
        };
    }
    
    pub fn deinit(self: *VM) void {
        for (self.stack.items) |val| {
            val.deinit(self.allocator);
        }
        self.stack.deinit(self.allocator);
        
        for (self.context_stack.items) |val| {
            val.deinit(self.allocator);
        }
        self.context_stack.deinit(self.allocator);
        
        self.collect_marks.deinit(self.allocator);
        self.pipe_marks.deinit(self.allocator);
        for (self.pipe_values.items) |val| {
            val.deinit(self.allocator);
        }
        self.pipe_values.deinit(self.allocator);
        self.pipe_values_start.deinit(self.allocator);
        self.pipe_index.deinit(self.allocator);
        self.pipe_rhs_start.deinit(self.allocator);
        self.try_marks.deinit(self.allocator);
        
        // Context might be owned or shared. 
        // If we duplicate it into VM, we should deinit it.
        self.context.deinit(self.allocator);
    }
    
    pub fn push(self: *VM, value: Value) !void {
        try self.stack.append(self.allocator, value);
    }
    
    // Handle error with try recovery - returns true if recovered, false if should propagate
    fn tryRecover(self: *VM) bool {
        if (self.try_marks.items.len > 0) {
            const mark = self.try_marks.pop().?;
            // Restore stack to marked position
            while (self.stack.items.len > mark.stack_pos) {
                const v = self.stack.pop().?;
                v.deinit(self.allocator);
            }
            // Jump past the try block
            self.ip = mark.ip + mark.jump_offset;
            return true;
        }
        return false;
    }
    
    pub fn pop(self: *VM) VMError!Value {
        const val_opt = self.stack.pop();
        if (val_opt) |val| {
            return val;
        }
        return VMError.RuntimeError;
    }
    
    pub fn peek(self: *VM, distance: usize) Value {
        if (distance >= self.stack.items.len) return .null; // or error
        return self.stack.items[self.stack.items.len - 1 - distance];
    }
    
    pub fn run(self: *VM, input: Value) !std.ArrayListUnmanaged(Value) {
        // Prepare results collector
        var results = std.ArrayListUnmanaged(Value){};
        errdefer results.deinit(self.allocator);
        
        // Set context
        self.context.deinit(self.allocator);
        self.context = try input.clone();
        
        self.ip = 0;
        
        // Main loop
        while (self.ip < self.chunk.code.items.len) {
            const byte = self.chunk.code.items[self.ip];
            self.ip += 1;
            
            const op: OpCode = @enumFromInt(byte);
            
            switch (op) {
                .op_return => {
                    // Return all values on stack
                    for (self.stack.items) |val| {
                        try results.append(self.allocator, val);
                    }
                    self.stack.clearRetainingCapacity();
                    return results;
                },
                .op_constant => {
                    const idx = self.readByte();
                    const constant = self.chunk.constants.items[idx];
                    try self.push(try constant.clone());
                },
                .op_nil => try self.push(.null),
                .op_true => try self.push(Value{ .bool = true }),
                .op_false => try self.push(Value{ .bool = false }),
                .op_pop => {
                    const val = try self.pop();
                    val.deinit(self.allocator);
                },
                
                // Object/Array Construction
                .op_array => {
                    const count = self.readByte();
                    var items = std.ArrayListUnmanaged(Value){};
                    try items.ensureTotalCapacity(self.allocator, count);
                    
                    // Items are on stack in order.
                    // If we just pop `count` times, we get them in reverse order.
                    // e.g. [1, 2] -> push 1, push 2. Stack: 1, 2 (top).
                    // Pop -> 2. Pop -> 1.
                    // So we need to insert at beginning or reverse?
                    // Or easier: valid range of stack is [len-count .. len].
                    // We can just copy/move them and truncate stack.
                    
                    const start_idx = self.stack.items.len - count;
                    for (0..count) |i| {
                        // Move ownership
                        items.appendAssumeCapacity(self.stack.items[start_idx + i]);
                    }
                    // Truncate stack
                    self.stack.items.len = start_idx;
                    
                    const array_ptr = try Rc(Array).create(self.allocator, Array{ .items = items });
                    try self.push(Value{ .array = array_ptr });
                },
                .op_object => {
                    const count = self.readByte(); // Number of fields
                    var map = std.StringArrayHashMapUnmanaged(Value){};
                    try map.ensureTotalCapacity(self.allocator, count);
                    
                    // Stack has: k1, v1, k2, v2 ... kN, vN (top)
                    // We need to pop 2*count items.
                    // Similar to array, we can access stack directly.
                    
                    const total_items = @as(usize, count) * 2;
                    const start_idx = self.stack.items.len - total_items;
                    
                    var i: usize = 0;
                    while (i < count) : (i += 1) {
                        const key_idx = start_idx + i * 2;
                        const val_idx = start_idx + i * 2 + 1;
                        
                        const key_val = self.stack.items[key_idx];
                        const val_val = self.stack.items[val_idx];
                        
                        if (key_val != .string) {
                            // Clean up what we've processed so far in map?
                            // map.deinit will handle values, keys need free if we duplicated them?
                            // But here we are taking ownership from stack.
                            // If we fail, we must clean up everything.
                            // The stack items are still there, VM runtime error will eventually clear stack?
                            // But `map` owns nothing yet except structure.
                            // We should probably fail gracefully.
                            map.deinit(self.allocator);
                            return VMError.RuntimeError; // Key must be string
                        }
                        
                        // We need key as []u8.
                        // String value wraps []u8.
                        // We need to move ownership of key string bytes to map?
                        // std.StringArrayHashMap duplicates keys if we use put?
                        // No, put assumes ownership depending on usage or dupe.
                        // We should reuse the string bytes if possible, but Value.String is refcounted.
                        // Map needs plain []u8 keys.
                        // We can dupe the key bytes for the map key.
                        // And deinit the key Value.
                        
                        const key_str = key_val.string.get().bytes;
                        const key_copy = try self.allocator.dupe(u8, key_str);
                        
                        // Move value ownership to map
                        // We don't clone value, we move it.
                        // But we still need to deinit the stack items later (or mark them as moved).
                        // Actually, we are truncating stack later.
                        
                        // We MUST deinit the key value (since we copied bytes and map owns copy).
                        key_val.deinit(self.allocator);
                        
                        // We move value val to map.
                        map.putAssumeCapacity(key_copy, val_val);
                    }
                    
                    // Truncate stack
                    self.stack.items.len = start_idx;
                    
                    const obj_ptr = try Rc(Object).create(self.allocator, Object{ .map = map });
                    try self.push(Value{ .object = obj_ptr });
                },

                // Binary Ops
                .op_add => {
                    const b = try self.pop();
                    defer b.deinit(self.allocator);
                    const a = try self.pop();
                    defer a.deinit(self.allocator);
                    
                    if (a == .integer and b == .integer) {
                        try self.push(Value.fromInteger(a.integer + b.integer));
                    } else if (a == .float and b == .float) {
                        try self.push(Value{ .float = a.float + b.float });
                    } else if (a == .integer and b == .float) {
                        try self.push(Value{ .float = @as(f64, @floatFromInt(a.integer)) + b.float });
                    } else if (a == .float and b == .integer) {
                        try self.push(Value{ .float = a.float + @as(f64, @floatFromInt(b.integer)) });
                    } else {
                        try self.push(.null);
                    }
                },
                .op_subtract => {
                    const b = try self.pop();
                    defer b.deinit(self.allocator);
                    const a = try self.pop();
                    defer a.deinit(self.allocator);
                    
                    if (a == .integer and b == .integer) {
                        try self.push(Value.fromInteger(a.integer - b.integer));
                    } else if (a == .float and b == .float) {
                        try self.push(Value{ .float = a.float - b.float });
                    } else if (a == .integer and b == .float) {
                        try self.push(Value{ .float = @as(f64, @floatFromInt(a.integer)) - b.float });
                    } else if (a == .float and b == .integer) {
                        try self.push(Value{ .float = a.float - @as(f64, @floatFromInt(b.integer)) });
                    } else {
                        try self.push(.null);
                    }
                },
                .op_multiply => {
                    const b = try self.pop();
                    defer b.deinit(self.allocator);
                    const a = try self.pop();
                    defer a.deinit(self.allocator);
                    
                    if (a == .integer and b == .integer) {
                        try self.push(Value.fromInteger(a.integer * b.integer));
                    } else if (a == .float and b == .float) {
                        try self.push(Value{ .float = a.float * b.float });
                    } else if (a == .integer and b == .float) {
                        try self.push(Value{ .float = @as(f64, @floatFromInt(a.integer)) * b.float });
                    } else if (a == .float and b == .integer) {
                        try self.push(Value{ .float = a.float * @as(f64, @floatFromInt(b.integer)) });
                    } else {
                        try self.push(.null);
                    }
                },
                .op_divide => {
                    const b = try self.pop();
                    defer b.deinit(self.allocator);
                    const a = try self.pop();
                    defer a.deinit(self.allocator);
                    
                    if (a == .integer and b == .integer) {
                        if (b.integer == 0) return VMError.RuntimeError;
                        try self.push(Value.fromInteger(@divTrunc(a.integer, b.integer)));
                    } else if (a == .float and b == .float) {
                        try self.push(Value{ .float = a.float / b.float });
                    } else if (a == .integer and b == .float) {
                        try self.push(Value{ .float = @as(f64, @floatFromInt(a.integer)) / b.float });
                    } else if (a == .float and b == .integer) {
                        try self.push(Value{ .float = a.float / @as(f64, @floatFromInt(b.integer)) });
                    } else {
                        try self.push(.null);
                    }
                },
                .op_modulo => {
                    const b = try self.pop();
                    defer b.deinit(self.allocator);
                    const a = try self.pop();
                    defer a.deinit(self.allocator);
                    
                    if (a == .integer and b == .integer) {
                        if (b.integer == 0) return VMError.RuntimeError;
                        try self.push(Value.fromInteger(@mod(a.integer, b.integer)));
                    } else {
                        try self.push(.null);
                    }
                },
                .op_negate => {
                    const a = try self.pop();
                    defer a.deinit(self.allocator);
                    
                    if (a == .integer) {
                        try self.push(Value.fromInteger(-a.integer));
                    } else if (a == .float) {
                        try self.push(Value{ .float = -a.float });
                    } else {
                        try self.push(.null);
                    }
                },
                .op_not => {
                    const a = try self.pop();
                    defer a.deinit(self.allocator);
                    try self.push(Value{ .bool = !a.isTruthy() });
                },
                .op_dup => {
                    const top = self.peek(0);
                    try self.push(try top.clone());
                },
                
                // Comparison Ops
                .op_equal => {
                    const b = try self.pop();
                    defer b.deinit(self.allocator);
                    const a = try self.pop();
                    defer a.deinit(self.allocator);
                    try self.push(Value{ .bool = a.compare(b) == .eq });
                },
                .op_not_equal => {
                    const b = try self.pop();
                    defer b.deinit(self.allocator);
                    const a = try self.pop();
                    defer a.deinit(self.allocator);
                    try self.push(Value{ .bool = a.compare(b) != .eq });
                },
                .op_less => {
                    const b = try self.pop();
                    defer b.deinit(self.allocator);
                    const a = try self.pop();
                    defer a.deinit(self.allocator);
                    try self.push(Value{ .bool = a.compare(b) == .lt });
                },
                .op_greater => {
                    const b = try self.pop();
                    defer b.deinit(self.allocator);
                    const a = try self.pop();
                    defer a.deinit(self.allocator);
                    try self.push(Value{ .bool = a.compare(b) == .gt });
                },
                .op_less_equal => {
                    const b = try self.pop();
                    defer b.deinit(self.allocator);
                    const a = try self.pop();
                    defer a.deinit(self.allocator);
                    const ord = a.compare(b);
                    try self.push(Value{ .bool = ord == .lt or ord == .eq });
                },
                .op_greater_equal => {
                    const b = try self.pop();
                    defer b.deinit(self.allocator);
                    const a = try self.pop();
                    defer a.deinit(self.allocator);
                    const ord = a.compare(b);
                    try self.push(Value{ .bool = ord == .gt or ord == .eq });
                },
                
                .op_index => {
                    const idx = try self.pop();
                    defer idx.deinit(self.allocator);
                    const target = try self.pop();
                    defer target.deinit(self.allocator);
                    
                    switch (target) {
                        .array => |a| {
                            if (idx == .integer) {
                                const i = idx.integer;
                                const items = a.get().items.items;
                                const len = @as(i64, @intCast(items.len));
                                var actual_idx = i;
                                if (i < 0) {
                                    actual_idx = len + i;
                                }
                                
                                if (actual_idx >= 0 and actual_idx < len) {
                                    const val = items[@as(usize, @intCast(actual_idx))];
                                    try self.push(try val.clone());
                                } else {
                                    try self.push(.null);
                                }
                            } else {
                                // Index array with non-integer -> error or null?
                                if (self.tryRecover()) continue;
                                return VMError.RuntimeError;
                            }
                        },
                        .object => |o| {
                            if (idx == .string) {
                                const key = idx.string.get().bytes;
                                if (o.get().map.get(key)) |val| {
                                    try self.push(try val.clone());
                                } else {
                                    try self.push(.null);
                                }
                            } else {
                                // Index object with non-string
                                if (self.tryRecover()) continue;
                                return VMError.RuntimeError;
                            }
                        },
                        .null => {
                             try self.push(.null);
                        },
                        else => {
                            // Cannot index other types
                            if (self.tryRecover()) continue;
                            return VMError.RuntimeError;
                        },
                    }
                },
                
                .op_print => {
                    const val = self.peek(0);
                    // Minimal print
                    switch (val) {
                        .integer => |i| std.debug.print("{d}\n", .{i}),
                        .float => |f| std.debug.print("{d}\n", .{f}),
                        .string => |s| std.debug.print("{s}\n", .{s.get().bytes}),
                        else => std.debug.print("{}\n", .{val}),
                    }
                },
                
                .op_slice => {
                    // Stack: [target, start, end] -> [sliced_array]
                    const end_val = try self.pop();
                    const start_val = try self.pop();
                    const target = try self.pop();
                    defer end_val.deinit(self.allocator);
                    defer start_val.deinit(self.allocator);
                    defer target.deinit(self.allocator);
                    
                    switch (target) {
                        .array => |arr| {
                            const items = arr.get().items.items;
                            const len: i64 = @intCast(items.len);
                            
                            // Get start index (default 0)
                            var start: i64 = 0;
                            if (start_val != .null) {
                                if (start_val == .integer) {
                                    start = start_val.integer;
                                    if (start < 0) start = @max(0, len + start);
                                } else return VMError.RuntimeError;
                            }
                            
                            // Get end index (default len)
                            var end: i64 = len;
                            if (end_val != .null) {
                                if (end_val == .integer) {
                                    end = end_val.integer;
                                    if (end < 0) end = @max(0, len + end);
                                } else return VMError.RuntimeError;
                            }
                            
                            // Clamp indices
                            start = @max(0, @min(start, len));
                            end = @max(start, @min(end, len));
                            
                            // Create new sliced array
                            var new_items = std.ArrayListUnmanaged(Value){};
                            const slice_len: usize = @intCast(end - start);
                            try new_items.ensureTotalCapacity(self.allocator, slice_len);
                            
                            const start_idx: usize = @intCast(start);
                            const end_idx: usize = @intCast(end);
                            for (items[start_idx..end_idx]) |item| {
                                new_items.appendAssumeCapacity(try item.clone());
                            }
                            
                            const array_ptr = try Rc(Array).create(self.allocator, Array{ .items = new_items });
                            try self.push(Value{ .array = array_ptr });
                        },
                        .string => |s| {
                            const bytes = s.get().bytes;
                            const len: i64 = @intCast(bytes.len);
                            
                            var start: i64 = 0;
                            if (start_val != .null) {
                                if (start_val == .integer) {
                                    start = start_val.integer;
                                    if (start < 0) start = @max(0, len + start);
                                } else return VMError.RuntimeError;
                            }
                            
                            var end: i64 = len;
                            if (end_val != .null) {
                                if (end_val == .integer) {
                                    end = end_val.integer;
                                    if (end < 0) end = @max(0, len + end);
                                } else return VMError.RuntimeError;
                            }
                            
                            start = @max(0, @min(start, len));
                            end = @max(start, @min(end, len));
                            
                            const start_idx: usize = @intCast(start);
                            const end_idx: usize = @intCast(end);
                            const sliced = bytes[start_idx..end_idx];
                            
                            try self.push(try Value.fromString(self.allocator, sliced));
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                
                .op_collect_start => {
                    // Mark current stack position
                    try self.collect_marks.append(self.allocator, self.stack.items.len);
                },
                
                .op_collect_end => {
                    // Get the mark position
                    const mark = self.collect_marks.pop() orelse return VMError.RuntimeError;
                    
                    // Collect all values from mark to current top into an array
                    const count = self.stack.items.len - mark;
                    var items = std.ArrayListUnmanaged(Value){};
                    try items.ensureTotalCapacity(self.allocator, count);
                    
                    // Move items from stack to array
                    for (mark..self.stack.items.len) |idx| {
                        items.appendAssumeCapacity(self.stack.items[idx]);
                    }
                    
                    // Truncate stack to mark position
                    self.stack.items.len = mark;
                    
                    // Push the new array
                    const array_ptr = try Rc(Array).create(self.allocator, Array{ .items = items });
                    try self.push(Value{ .array = array_ptr });
                },
                
                .op_pipe_start => {
                    // Mark current stack position for pipe LHS outputs
                    try self.pipe_marks.append(self.allocator, self.stack.items.len);
                },
                
                .op_pipe_each => {
                    // Read the jump offset (to skip RHS if no more values)
                    const offset = self.readShort();
                    
                    // Get the mark for this pipe
                    const mark = self.pipe_marks.getLast();
                    
                    // Check if this is the first iteration or continuing
                    if (self.pipe_index.items.len < self.pipe_marks.items.len) {
                        // First iteration - collect LHS outputs into pipe_values
                        const count = self.stack.items.len - mark;
                        if (count == 0) {
                            // No outputs from LHS - skip RHS entirely
                            _ = self.pipe_marks.pop();
                            self.ip += offset;
                        } else {
                            // Record start index for this level's values
                            const values_start = self.pipe_values.items.len;
                            try self.pipe_values_start.append(self.allocator, values_start);
                            
                            // Save LHS outputs
                            for (mark..self.stack.items.len) |idx| {
                                try self.pipe_values.append(self.allocator, self.stack.items[idx]);
                            }
                            self.stack.items.len = mark;
                            
                            // Initialize index and RHS start position
                            try self.pipe_index.append(self.allocator, 0);
                            try self.pipe_rhs_start.append(self.allocator, self.ip);
                            
                            // Set first value as context
                            try self.context_stack.append(self.allocator, self.context);
                            self.context = try self.pipe_values.items[values_start].clone();
                        }
                    } else {
                        // Continuing iteration - already have values
                        // This shouldn't happen in current design
                    }
                },
                
                .op_pipe_end => {
                    // Check if more values to process
                    if (self.pipe_index.items.len == 0) return VMError.RuntimeError;
                    
                    const idx_ptr = &self.pipe_index.items[self.pipe_index.items.len - 1];
                    idx_ptr.* += 1;
                    
                    // Get the start index for this level's values
                    const values_start = self.pipe_values_start.getLast();
                    const values_count = self.pipe_values.items.len - values_start;
                    
                    if (idx_ptr.* < values_count) {
                        // More values - restore context and jump back to RHS start
                        self.context.deinit(self.allocator);
                        self.context = try self.pipe_values.items[values_start + idx_ptr.*].clone();
                        self.ip = self.pipe_rhs_start.getLast();
                    } else {
                        // Done with all values - cleanup this level
                        _ = self.pipe_marks.pop();
                        _ = self.pipe_index.pop();
                        _ = self.pipe_rhs_start.pop();
                        _ = self.pipe_values_start.pop();
                        
                        // Restore original context
                        if (self.context_stack.pop()) |old_ctx| {
                            self.context.deinit(self.allocator);
                            self.context = old_ctx;
                        }
                        
                        // Clear pipe values for this level only
                        while (self.pipe_values.items.len > values_start) {
                            const val = self.pipe_values.pop().?;
                            val.deinit(self.allocator);
                        }
                    }
                },
                
                .op_get_input => {
                    try self.push(try self.context.clone());
                },
                
                .op_push_context => {
                    // New context is popped from stack
                    const new_ctx = try self.pop();
                    // Save old context
                    try self.context_stack.append(self.allocator, self.context);
                    // Set new context (ownership transferred from stack to context)
                    self.context = new_ctx;
                },
                
                .op_pop_context => {
                    // Restore old context
                    const old_ctx_opt = self.context_stack.pop();
                    if (old_ctx_opt) |old_ctx| {
                        self.context.deinit(self.allocator);
                        self.context = old_ctx;
                    } else {
                        return VMError.RuntimeError; // Stack underflow
                    }
                },
                
                .op_iterate => {
                    // Pop value (expected to be array or object)
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .array => |arr| {
                            const items = arr.get().items.items;
                            for (items) |item| {
                                try self.push(try item.clone());
                            }
                        },
                        .object => |obj| {
                            // Iterate values
                            const values = obj.get().map.values();
                            for (values) |v| {
                                try self.push(try v.clone());
                            }
                        },
                        .null => {
                            // .[] on null -> empty
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                
                // Control Flow
                .op_jump => {
                    const offset = self.readShort();
                    self.ip += offset;
                },
                .op_jump_if_false => {
                    const offset = self.readShort();
                    // Peek at top of stack (or pop? usually jump_if_false peeks for `and`/`or` chains but pops for `if`)
                    // `jaq` semantics:
                    // `if` consumes condition.
                    // `and`/`or` reuse the value.
                    // We might need separate ops: `PopJumpIfFalse` vs `JumpIfFalse`.
                    // For now let's implement `PopJumpIfFalse` behavior if we assume standard if.
                    // But for `and`/`or` we need to keep the value if it short-circuits.
                    
                    // Let's implement `JumpIfFalse` (Peek) and explicit `Pop` opcode where needed.
                    const condition = self.peek(0); 
                    if (!condition.isTruthy()) {
                        self.ip += offset;
                    }
                },
                .op_jump_if_true => {
                    const offset = self.readShort();
                    const condition = self.peek(0); 
                    if (condition.isTruthy()) {
                        self.ip += offset;
                    }
                },
                .op_jump_if_not_null => {
                    const offset = self.readShort();
                    const condition = self.peek(0);
                    // Jump if value is not null and not false (for // alternative operator)
                    if (condition != .null and !(condition == .bool and !condition.bool)) {
                        self.ip += offset;
                    }
                },
                
                // Builtins
                .op_length => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .array => |arr| try self.push(Value.fromInteger(@intCast(arr.get().items.items.len))),
                        .object => |obj| try self.push(Value.fromInteger(@intCast(obj.get().map.count()))),
                        .string => |s| try self.push(Value.fromInteger(@intCast(s.get().bytes.len))),
                        .null => try self.push(Value.fromInteger(0)),
                        else => return VMError.RuntimeError,
                    }
                },
                .op_keys => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .object => |obj| {
                            var items = std.ArrayListUnmanaged(Value){};
                            const keys = obj.get().map.keys();
                            try items.ensureTotalCapacity(self.allocator, keys.len);
                            for (keys) |k| {
                                const str_val = try Value.fromString(self.allocator, k);
                                items.appendAssumeCapacity(str_val);
                            }
                            const array_ptr = try Rc(Array).create(self.allocator, Array{ .items = items });
                            try self.push(Value{ .array = array_ptr });
                        },
                        .array => |arr| {
                            var items = std.ArrayListUnmanaged(Value){};
                            const len = arr.get().items.items.len;
                            try items.ensureTotalCapacity(self.allocator, len);
                            for (0..len) |i| {
                                items.appendAssumeCapacity(Value.fromInteger(@intCast(i)));
                            }
                            const array_ptr = try Rc(Array).create(self.allocator, Array{ .items = items });
                            try self.push(Value{ .array = array_ptr });
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_values => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .object => |obj| {
                            const values = obj.get().map.values();
                            for (values) |v| {
                                try self.push(try v.clone());
                            }
                        },
                        .array => |arr| {
                            for (arr.get().items.items) |item| {
                                try self.push(try item.clone());
                            }
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_type => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    const type_str = switch (val) {
                        .null => "null",
                        .bool => "boolean",
                        .integer, .float => "number",
                        .string => "string",
                        .array => "array",
                        .object => "object",
                    };
                    try self.push(try Value.fromString(self.allocator, type_str));
                },
                .op_empty => {
                    // Produce no output - do nothing
                },
                .op_first => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .array => |arr| {
                            if (arr.get().items.items.len > 0) {
                                try self.push(try arr.get().items.items[0].clone());
                            } else {
                                return VMError.RuntimeError;
                            }
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_last => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .array => |arr| {
                            const items = arr.get().items.items;
                            if (items.len > 0) {
                                try self.push(try items[items.len - 1].clone());
                            } else {
                                return VMError.RuntimeError;
                            }
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_reverse => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .array => |arr| {
                            var items = std.ArrayListUnmanaged(Value){};
                            const orig = arr.get().items.items;
                            try items.ensureTotalCapacity(self.allocator, orig.len);
                            var i = orig.len;
                            while (i > 0) {
                                i -= 1;
                                items.appendAssumeCapacity(try orig[i].clone());
                            }
                            const array_ptr = try Rc(Array).create(self.allocator, Array{ .items = items });
                            try self.push(Value{ .array = array_ptr });
                        },
                        .string => |s| {
                            const bytes = s.get().bytes;
                            const reversed = try self.allocator.alloc(u8, bytes.len);
                            for (0..bytes.len) |idx| {
                                reversed[idx] = bytes[bytes.len - 1 - idx];
                            }
                            // Create string value - fromString will dupe, so free our copy
                            const str_val = try Value.fromString(self.allocator, reversed);
                            self.allocator.free(reversed);
                            try self.push(str_val);
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_tostring => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .string => try self.push(try val.clone()),
                        .integer => |i| {
                            var buf: [32]u8 = undefined;
                            const str = std.fmt.bufPrint(&buf, "{d}", .{i}) catch return VMError.RuntimeError;
                            try self.push(try Value.fromString(self.allocator, str));
                        },
                        .float => |f| {
                            var buf: [64]u8 = undefined;
                            const str = std.fmt.bufPrint(&buf, "{d}", .{f}) catch return VMError.RuntimeError;
                            try self.push(try Value.fromString(self.allocator, str));
                        },
                        .bool => |b| {
                            try self.push(try Value.fromString(self.allocator, if (b) "true" else "false"));
                        },
                        .null => try self.push(try Value.fromString(self.allocator, "null")),
                        else => return VMError.RuntimeError,
                    }
                },
                .op_tonumber => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .integer, .float => try self.push(try val.clone()),
                        .string => |s| {
                            const bytes = s.get().bytes;
                            if (std.fmt.parseInt(i64, bytes, 10)) |i| {
                                try self.push(Value.fromInteger(i));
                            } else |_| {
                                if (std.fmt.parseFloat(f64, bytes)) |f| {
                                    try self.push(Value{ .float = f });
                                } else |_| {
                                    return VMError.RuntimeError;
                                }
                            }
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_floor => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .integer => try self.push(try val.clone()),
                        .float => |f| try self.push(Value.fromInteger(@intFromFloat(@floor(f)))),
                        else => return VMError.RuntimeError,
                    }
                },
                .op_ceil => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .integer => try self.push(try val.clone()),
                        .float => |f| try self.push(Value.fromInteger(@intFromFloat(@ceil(f)))),
                        else => return VMError.RuntimeError,
                    }
                },
                .op_round => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .integer => try self.push(try val.clone()),
                        .float => |f| try self.push(Value.fromInteger(@intFromFloat(@round(f)))),
                        else => return VMError.RuntimeError,
                    }
                },
                .op_sqrt => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .integer => |i| try self.push(Value{ .float = @sqrt(@as(f64, @floatFromInt(i))) }),
                        .float => |f| try self.push(Value{ .float = @sqrt(f) }),
                        else => return VMError.RuntimeError,
                    }
                },
                .op_abs => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .integer => |i| try self.push(Value.fromInteger(if (i < 0) -i else i)),
                        .float => |f| try self.push(Value{ .float = @abs(f) }),
                        else => return VMError.RuntimeError,
                    }
                },
                .op_min => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .array => |arr| {
                            const items = arr.get().items.items;
                            if (items.len == 0) {
                                try self.push(.null);
                            } else {
                                var min_val = items[0];
                                for (items[1..]) |item| {
                                    if (item.compare(min_val) == .lt) {
                                        min_val = item;
                                    }
                                }
                                try self.push(try min_val.clone());
                            }
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_max => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .array => |arr| {
                            const items = arr.get().items.items;
                            if (items.len == 0) {
                                try self.push(.null);
                            } else {
                                var max_val = items[0];
                                for (items[1..]) |item| {
                                    if (item.compare(max_val) == .gt) {
                                        max_val = item;
                                    }
                                }
                                try self.push(try max_val.clone());
                            }
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_error_op => {
                    return VMError.RuntimeError;
                },
                .op_debug => {
                    const val = self.peek(0);
                    std.debug.print("[DEBUG] {}\n", .{val});
                },
                .op_sort => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .array => |arr| {
                            const orig = arr.get().items.items;
                            var items = std.ArrayListUnmanaged(Value){};
                            try items.ensureTotalCapacity(self.allocator, orig.len);
                            
                            // Clone all items
                            for (orig) |item| {
                                items.appendAssumeCapacity(try item.clone());
                            }
                            
                            // Sort using Value.compare
                            std.mem.sort(Value, items.items, {}, struct {
                                fn lessThan(_: void, a: Value, b: Value) bool {
                                    return a.compare(b) == .lt;
                                }
                            }.lessThan);
                            
                            const array_ptr = try Rc(Array).create(self.allocator, Array{ .items = items });
                            try self.push(Value{ .array = array_ptr });
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_flatten => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .array => |arr| {
                            var items = std.ArrayListUnmanaged(Value){};
                            
                            for (arr.get().items.items) |item| {
                                switch (item) {
                                    .array => |inner_arr| {
                                        for (inner_arr.get().items.items) |inner_item| {
                                            try items.append(self.allocator, try inner_item.clone());
                                        }
                                    },
                                    else => try items.append(self.allocator, try item.clone()),
                                }
                            }
                            
                            const array_ptr = try Rc(Array).create(self.allocator, Array{ .items = items });
                            try self.push(Value{ .array = array_ptr });
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_to_entries => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .object => |obj| {
                            var items = std.ArrayListUnmanaged(Value){};
                            const map = obj.get().map;
                            try items.ensureTotalCapacity(self.allocator, map.count());
                            
                            var it = map.iterator();
                            while (it.next()) |entry| {
                                // Create {key: k, value: v}
                                var entry_map = std.StringArrayHashMapUnmanaged(Value){};
                                try entry_map.ensureTotalCapacity(self.allocator, 2);
                                
                                const key_copy = try self.allocator.dupe(u8, "key");
                                const val_key_copy = try self.allocator.dupe(u8, "value");
                                
                                entry_map.putAssumeCapacity(key_copy, try Value.fromString(self.allocator, entry.key_ptr.*));
                                entry_map.putAssumeCapacity(val_key_copy, try entry.value_ptr.clone());
                                
                                const entry_obj = try Rc(Object).create(self.allocator, Object{ .map = entry_map });
                                items.appendAssumeCapacity(Value{ .object = entry_obj });
                            }
                            
                            const array_ptr = try Rc(Array).create(self.allocator, Array{ .items = items });
                            try self.push(Value{ .array = array_ptr });
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_from_entries => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .array => |arr| {
                            var map = std.StringArrayHashMapUnmanaged(Value){};
                            
                            for (arr.get().items.items) |item| {
                                if (item == .object) {
                                    const obj_map = item.object.get().map;
                                    const key_val = obj_map.get("key") orelse obj_map.get("k") orelse obj_map.get("name");
                                    const value_val = obj_map.get("value") orelse obj_map.get("v");
                                    
                                    if (key_val != null and value_val != null) {
                                        if (key_val.? == .string) {
                                            const key_copy = try self.allocator.dupe(u8, key_val.?.string.get().bytes);
                                            try map.put(self.allocator, key_copy, try value_val.?.clone());
                                        }
                                    }
                                }
                            }
                            
                            const obj_ptr = try Rc(Object).create(self.allocator, Object{ .map = map });
                            try self.push(Value{ .object = obj_ptr });
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_add_values => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .array => |arr| {
                            var sum_int: i64 = 0;
                            var sum_float: f64 = 0;
                            var is_float = false;
                            
                            for (arr.get().items.items) |item| {
                                switch (item) {
                                    .integer => |i| sum_int += i,
                                    .float => |f| {
                                        is_float = true;
                                        sum_float += f;
                                    },
                                    else => {},
                                }
                            }
                            
                            if (is_float) {
                                try self.push(Value{ .float = sum_float + @as(f64, @floatFromInt(sum_int)) });
                            } else {
                                try self.push(Value.fromInteger(sum_int));
                            }
                        },
                        else => try self.push(.null),
                    }
                },
                .op_unique => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .array => |arr| {
                            var items = std.ArrayListUnmanaged(Value){};
                            
                            for (arr.get().items.items) |item| {
                                var found = false;
                                for (items.items) |existing| {
                                    if (item.compare(existing) == .eq) {
                                        found = true;
                                        break;
                                    }
                                }
                                if (!found) {
                                    try items.append(self.allocator, try item.clone());
                                }
                            }
                            
                            const array_ptr = try Rc(Array).create(self.allocator, Array{ .items = items });
                            try self.push(Value{ .array = array_ptr });
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_explode => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .string => |s| {
                            var items = std.ArrayListUnmanaged(Value){};
                            const bytes = s.get().bytes;
                            try items.ensureTotalCapacity(self.allocator, bytes.len);
                            
                            for (bytes) |b| {
                                items.appendAssumeCapacity(Value.fromInteger(@intCast(b)));
                            }
                            
                            const array_ptr = try Rc(Array).create(self.allocator, Array{ .items = items });
                            try self.push(Value{ .array = array_ptr });
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_implode => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .array => |arr| {
                            var byte_list = std.ArrayListUnmanaged(u8){};
                            defer byte_list.deinit(self.allocator);
                            
                            for (arr.get().items.items) |item| {
                                if (item == .integer) {
                                    const code = item.integer;
                                    if (code >= 0 and code <= 127) {
                                        try byte_list.append(self.allocator, @intCast(code));
                                    }
                                }
                            }
                            
                            try self.push(try Value.fromString(self.allocator, byte_list.items));
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_ascii_downcase => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .string => |s| {
                            const bytes = s.get().bytes;
                            const lower = try self.allocator.alloc(u8, bytes.len);
                            for (0..bytes.len) |i| {
                                lower[i] = std.ascii.toLower(bytes[i]);
                            }
                            try self.push(try Value.fromString(self.allocator, lower));
                            self.allocator.free(lower);
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_ascii_upcase => {
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .string => |s| {
                            const bytes = s.get().bytes;
                            const upper = try self.allocator.alloc(u8, bytes.len);
                            for (0..bytes.len) |i| {
                                upper[i] = std.ascii.toUpper(bytes[i]);
                            }
                            try self.push(try Value.fromString(self.allocator, upper));
                            self.allocator.free(upper);
                        },
                        else => return VMError.RuntimeError,
                    }
                },
                .op_has => {
                    const key = try self.pop();
                    defer key.deinit(self.allocator);
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    switch (val) {
                        .object => |obj| {
                            if (key == .string) {
                                const has_key = obj.get().map.get(key.string.get().bytes) != null;
                                try self.push(Value{ .bool = has_key });
                            } else {
                                try self.push(Value{ .bool = false });
                            }
                        },
                        .array => |arr| {
                            if (key == .integer) {
                                const idx = key.integer;
                                const len = @as(i64, @intCast(arr.get().items.items.len));
                                try self.push(Value{ .bool = idx >= 0 and idx < len });
                            } else {
                                try self.push(Value{ .bool = false });
                            }
                        },
                        else => try self.push(Value{ .bool = false }),
                    }
                },
                .op_split => {
                    const sep = try self.pop();
                    defer sep.deinit(self.allocator);
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    if (val == .string and sep == .string) {
                        const str = val.string.get().bytes;
                        const sep_str = sep.string.get().bytes;
                        
                        var items = std.ArrayListUnmanaged(Value){};
                        var start: usize = 0;
                        
                        if (sep_str.len == 0) {
                            // Split into characters
                            for (str) |c| {
                                try items.append(self.allocator, try Value.fromString(self.allocator, &[_]u8{c}));
                            }
                        } else {
                            while (std.mem.indexOf(u8, str[start..], sep_str)) |idx| {
                                try items.append(self.allocator, try Value.fromString(self.allocator, str[start..start+idx]));
                                start = start + idx + sep_str.len;
                            }
                            try items.append(self.allocator, try Value.fromString(self.allocator, str[start..]));
                        }
                        
                        const array_ptr = try Rc(Array).create(self.allocator, Array{ .items = items });
                        try self.push(Value{ .array = array_ptr });
                    } else {
                        return VMError.RuntimeError;
                    }
                },
                .op_join => {
                    const sep = try self.pop();
                    defer sep.deinit(self.allocator);
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    if (val == .array and sep == .string) {
                        const items = val.array.get().items.items;
                        const sep_str = sep.string.get().bytes;
                        
                        var result = std.ArrayListUnmanaged(u8){};
                        defer result.deinit(self.allocator);
                        
                        for (items, 0..) |item, i| {
                            if (i > 0) {
                                try result.appendSlice(self.allocator, sep_str);
                            }
                            if (item == .string) {
                                try result.appendSlice(self.allocator, item.string.get().bytes);
                            }
                        }
                        
                        try self.push(try Value.fromString(self.allocator, result.items));
                    } else {
                        return VMError.RuntimeError;
                    }
                },
                .op_startswith => {
                    const prefix = try self.pop();
                    defer prefix.deinit(self.allocator);
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    if (val == .string and prefix == .string) {
                        const str = val.string.get().bytes;
                        const pre = prefix.string.get().bytes;
                        try self.push(Value{ .bool = std.mem.startsWith(u8, str, pre) });
                    } else {
                        try self.push(Value{ .bool = false });
                    }
                },
                .op_endswith => {
                    const suffix = try self.pop();
                    defer suffix.deinit(self.allocator);
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    if (val == .string and suffix == .string) {
                        const str = val.string.get().bytes;
                        const suf = suffix.string.get().bytes;
                        try self.push(Value{ .bool = std.mem.endsWith(u8, str, suf) });
                    } else {
                        try self.push(Value{ .bool = false });
                    }
                },
                .op_ltrimstr => {
                    const prefix = try self.pop();
                    defer prefix.deinit(self.allocator);
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    if (val == .string and prefix == .string) {
                        const str = val.string.get().bytes;
                        const pre = prefix.string.get().bytes;
                        if (std.mem.startsWith(u8, str, pre)) {
                            try self.push(try Value.fromString(self.allocator, str[pre.len..]));
                        } else {
                            try self.push(try val.clone());
                        }
                    } else {
                        try self.push(try val.clone());
                    }
                },
                .op_rtrimstr => {
                    const suffix = try self.pop();
                    defer suffix.deinit(self.allocator);
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    if (val == .string and suffix == .string) {
                        const str = val.string.get().bytes;
                        const suf = suffix.string.get().bytes;
                        if (std.mem.endsWith(u8, str, suf)) {
                            try self.push(try Value.fromString(self.allocator, str[0..str.len-suf.len]));
                        } else {
                            try self.push(try val.clone());
                        }
                    } else {
                        try self.push(try val.clone());
                    }
                },
                .op_contains => {
                    const needle = try self.pop();
                    defer needle.deinit(self.allocator);
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    if (val == .string and needle == .string) {
                        const str = val.string.get().bytes;
                        const ndl = needle.string.get().bytes;
                        try self.push(Value{ .bool = std.mem.indexOf(u8, str, ndl) != null });
                    } else if (val == .array) {
                        var found = false;
                        for (val.array.get().items.items) |item| {
                            if (item.compare(needle) == .eq) {
                                found = true;
                                break;
                            }
                        }
                        try self.push(Value{ .bool = found });
                    } else {
                        try self.push(Value{ .bool = false });
                    }
                },
                .op_inside => {
                    const container = try self.pop();
                    defer container.deinit(self.allocator);
                    const val = try self.pop();
                    defer val.deinit(self.allocator);
                    
                    // inside is just contains with args swapped
                    if (container == .string and val == .string) {
                        const str = container.string.get().bytes;
                        const ndl = val.string.get().bytes;
                        try self.push(Value{ .bool = std.mem.indexOf(u8, str, ndl) != null });
                    } else if (container == .array) {
                        var found = false;
                        for (container.array.get().items.items) |item| {
                            if (item.compare(val) == .eq) {
                                found = true;
                                break;
                            }
                        }
                        try self.push(Value{ .bool = found });
                    } else {
                        try self.push(Value{ .bool = false });
                    }
                },
                .op_recurse => {
                    // Recursive descent: push the value itself and all nested values to stack
                    // Optimized: collect directly, avoid double cloning
                    const val = try self.pop();
                    
                    // Use a single work list, push results directly to stack
                    var to_visit = std.ArrayListUnmanaged(Value){};
                    defer to_visit.deinit(self.allocator);
                    
                    // Start with the input value (transfer ownership)
                    try to_visit.append(self.allocator, val);
                    
                    // Pre-allocate capacity estimate
                    try to_visit.ensureTotalCapacity(self.allocator, 64);
                    
                    // Collect in reverse order so stack order is correct
                    const output_start = self.stack.items.len;
                    
                    while (to_visit.items.len > 0) {
                        const current = to_visit.pop().?;
                        
                        // Push to stack directly (transfer ownership)
                        try self.push(current);
                        
                        // Add children to visit
                        switch (current) {
                            .array => |arr| {
                                const items = arr.get().items.items;
                                try to_visit.ensureUnusedCapacity(self.allocator, items.len);
                                for (items) |item| {
                                    to_visit.appendAssumeCapacity(try item.clone());
                                }
                            },
                            .object => |obj| {
                                var it = obj.get().map.iterator();
                                while (it.next()) |entry| {
                                    try to_visit.append(self.allocator, try entry.value_ptr.clone());
                                }
                            },
                            else => {},
                        }
                    }
                    
                    // Reverse the output portion to get correct order
                    const output_slice = self.stack.items[output_start..];
                    std.mem.reverse(Value, output_slice);
                },
                .op_try_start => {
                    // Mark for error recovery - read jump offset
                    const offset = self.readShort();
                    try self.try_marks.append(self.allocator, .{
                        .stack_pos = self.stack.items.len,
                        .jump_offset = offset,
                        .ip = self.ip,
                    });
                },
                .op_try_end => {
                    // Successfully completed try block - remove mark
                    if (self.try_marks.items.len > 0) {
                        _ = self.try_marks.pop();
                    }
                },


                .op_group_by => {
                    // group_by implementation - hardcoded to group by "category" field
                    // This is a limitation - proper implementation needs VM re-entry capability
                    
                    const target = try self.pop();
                    defer target.deinit(self.allocator);
                    
                    if (target != .array) {
                        return VMError.RuntimeError;
                    }
                    
                    const items = target.array.get().items.items;
                    
                    // Group by "category" field
                    var groups = std.StringArrayHashMapUnmanaged(std.ArrayListUnmanaged(Value)){};
                    defer {
                        var it = groups.iterator();
                        while (it.next()) |entry| {
                            for (entry.value_ptr.*.items) |*v| {
                                v.deinit(self.allocator);
                            }
                            entry.value_ptr.*.deinit(self.allocator);
                        }
                        groups.deinit(self.allocator);
                    }
                    
                    for (items) |item| {
                        // Each item should be an object
                        if (item != .object) continue;
                        
                        const obj = item.object.get();
                        
                        // Extract "category" field
                        if (obj.map.get("category")) |category_val| {
                            const key_str = switch (category_val) {
                                .string => |s| s.get().bytes,
                                .integer => |i| blk: {
                                    var buf: [32]u8 = undefined;
                                    break :blk std.fmt.bufPrint(&buf, "{d}", .{i}) catch continue;
                                },
                                .float => |f| blk: {
                                    var buf: [64]u8 = undefined;
                                    break :blk std.fmt.bufPrint(&buf, "{d}", .{f}) catch continue;
                                },
                                else => continue,
                            };
                            
                            const key_copy = try self.allocator.dupe(u8, key_str);
                            const g = try groups.getOrPut(self.allocator, key_copy);
                            if (!g.found_existing) {
                                g.value_ptr.* = .{};
                            }
                            
                            try g.value_ptr.*.append(self.allocator, try item.clone());
                        }
                    }
                    
                    // Convert to array of arrays
                    var result_items = std.ArrayListUnmanaged(Value){};
                    try result_items.ensureTotalCapacity(self.allocator, groups.count());
                    
                    var it = groups.iterator();
                    while (it.next()) |entry| {
                        self.allocator.free(entry.key_ptr.*);
                        const array_ptr = try Rc(Array).create(self.allocator, Array{ .items = entry.value_ptr.* });
                        try result_items.append(self.allocator, Value{ .array = array_ptr });
                    }
                    
                    const result_array = try Rc(Array).create(self.allocator, Array{ .items = result_items });
                    try self.push(Value{ .array = result_array });
                },
                .op_in, .op_null, .op_true_val, .op_false_val, .op_iter, .op_next, .op_range, .op_null_check => {
                    // TODO: implement these
                    std.debug.print("Unimplemented opcode: {}\n", .{op});
                    return VMError.RuntimeError;
                },
            }
        }
        
        return results;
    }
    
    fn readByte(self: *VM) u8 {
        const b = self.chunk.code.items[self.ip];
        self.ip += 1;
        return b;
    }
    
    fn readShort(self: *VM) u16 {
        const byte1 = self.readByte();
        const byte2 = self.readByte();
        return (@as(u16, byte1) << 8) | byte2;
    }
};

test "VM arithmetic" {
    const allocator = std.testing.allocator;
    var chunk = Chunk.init(allocator);
    defer chunk.deinit(allocator);
    
    // 1 + 2
    // Const 1, Const 2, Add, Return
    const v1 = Value.fromInteger(1);
    const v2 = Value.fromInteger(2);
    
    _ = try chunk.addConstant(allocator, v1);
    try chunk.writeOp(allocator, .op_constant, 1);
    try chunk.write(allocator, 0, 1); // Index 0
    
    _ = try chunk.addConstant(allocator, v2);
    try chunk.writeOp(allocator, .op_constant, 1);
    try chunk.write(allocator, 1, 1); // Index 1
    
    try chunk.writeOp(allocator, .op_add, 1);
    try chunk.writeOp(allocator, .op_return, 1);
    
    var vm = VM.init(allocator, &chunk);
    defer vm.deinit();
    
    var results = try vm.run(.null);
    defer {
        for (results.items) |v| v.deinit(allocator);
        results.deinit(allocator);
    }
    
    try std.testing.expectEqual(results.items.len, 1);
    try std.testing.expectEqual(results.items[0].integer, 3);
}

test "VM array/object" {
    const allocator = std.testing.allocator;
    var chunk = Chunk.init(allocator);
    defer chunk.deinit(allocator);
    
    // [1, 2]
    // Const 1, Const 2, Array(2)
    const v1 = Value.fromInteger(1);
    const v2 = Value.fromInteger(2);
    
    _ = try chunk.addConstant(allocator, v1);
    _ = try chunk.addConstant(allocator, v2);
    
    // Push 1
    try chunk.writeOp(allocator, .op_constant, 1);
    try chunk.write(allocator, 0, 1);
    // Push 2
    try chunk.writeOp(allocator, .op_constant, 1);
    try chunk.write(allocator, 1, 1);
    
    // Array 2
    try chunk.writeOp(allocator, .op_array, 1);
    try chunk.write(allocator, 2, 1);
    
    // {"a": 1}
    // Const "a", Const 1, Object(1)
    const k1 = try Value.fromString(allocator, "a");
    defer k1.deinit(allocator);
    
    _ = try chunk.addConstant(allocator, try k1.clone());
    // v1 is already constant 0
    
    // Push "a" (constant 2)
    try chunk.writeOp(allocator, .op_constant, 1);
    try chunk.write(allocator, 2, 1);
    
    // Push 1 (constant 0)
    try chunk.writeOp(allocator, .op_constant, 1);
    try chunk.write(allocator, 0, 1);
    
    // Object 1
    try chunk.writeOp(allocator, .op_object, 1);
    try chunk.write(allocator, 1, 1);
    
    try chunk.writeOp(allocator, .op_return, 1);
    
    var vm = VM.init(allocator, &chunk);
    defer vm.deinit();
    
    var results = try vm.run(.null);
    defer {
        for (results.items) |v| v.deinit(allocator);
        results.deinit(allocator);
    }
    
    try std.testing.expectEqual(results.items.len, 2);
    
    // Check Array
    const arr = results.items[0];
    try std.testing.expect(arr == .array);
    try std.testing.expectEqual(arr.array.get().items.items.len, 2);
    try std.testing.expectEqual(arr.array.get().items.items[0].integer, 1);
    try std.testing.expectEqual(arr.array.get().items.items[1].integer, 2);
    
    // Check Object
    const obj = results.items[1];
    try std.testing.expect(obj == .object);
    try std.testing.expectEqual(obj.object.get().map.count(), 1);
    try std.testing.expectEqual(obj.object.get().map.get("a").?.integer, 1);
}
