const std = @import("std");
const Value = @import("value.zig").Value;
const Allocator = std.mem.Allocator;

pub const OpCode = enum(u8) {
    // Stack manipulation
    op_return,      // Return from current frame
    op_constant,    // Load constant
    op_nil,         // Push null
    op_true,        // Push true
    op_false,       // Push false
    op_pop,         // Pop stack
    op_dup,         // Duplicate top
    
    // Binary Ops
    op_add,
    op_subtract,
    op_multiply,
    op_divide,
    op_modulo,
    op_equal,
    op_not_equal,
    op_less,
    op_greater,
    op_less_equal,
    op_greater_equal,
    
    // Unary Ops
    op_negate,
    op_not,
    
    // Object/Array Construction
    op_array,       // Create array from N stack items
    op_object,      // Create object from N stack items (key, val pairs)
    
    // Path/Index
    op_index,       // val[idx]
    
    // Iteration
    op_iterate,
    
    // Control Flow
    op_jump,        // Unconditional jump
    op_jump_if_false, // Jump if top is false/null (does not pop)
    op_jump_if_true,  // Jump if top is true (does not pop)
    op_jump_if_not_null, // Jump if top is not null/false (for // operator)
    
    // Iteration / Generators
    op_iter,        // Initialize iterator for top of stack
    op_next,        // Get next value from iterator, jump if done
    
    // Special
    op_get_input,   // Push current input (context)
    op_push_context, // Pop stack, set as context, save old context
    op_pop_context,  // Restore old context
    op_print,       // For debugging/output
    op_slice,       // Array slice [start:end]
    
    // Array collection (for [expr] semantics)
    op_collect_start,  // Mark stack position for collection
    op_collect_end,    // Collect all values since mark into array
    
    // Pipe with generator support
    op_pipe_start,     // Mark stack position for pipe LHS outputs
    op_pipe_each,      // For each value since mark: set context, run RHS, collect outputs
    op_pipe_end,       // End of pipe RHS section
    
    // Builtins
    op_length,      // length
    op_keys,        // keys
    op_values,      // values (alias for .[] on objects)
    op_type,        // type
    op_empty,       // empty (produce no output)
    op_first,       // first
    op_last,        // last
    op_reverse,     // reverse
    op_sort,        // sort
    op_flatten,     // flatten
    op_null,        // null
    op_true_val,    // true
    op_false_val,   // false
    op_has,         // has(key)
    op_in,          // in(obj)
    op_contains,    // contains
    op_inside,      // inside
    op_tostring,    // tostring
    op_tonumber,    // tonumber
    op_floor,       // floor
    op_ceil,        // ceil (alias: ceil)
    op_round,       // round
    op_sqrt,        // sqrt
    op_min,         // min
    op_max,         // max
    op_abs,         // abs
    op_error_op,    // error
    op_debug,       // debug
    op_to_entries,  // to_entries
    op_from_entries, // from_entries
    op_add_values,  // add (sum array)
    op_unique,      // unique
    op_group_by,    // group_by
    op_split,       // split
    op_join,        // join
    op_ascii_downcase, // ascii_downcase
    op_ascii_upcase,   // ascii_upcase
    op_startswith,  // startswith
    op_endswith,    // endswith
    op_ltrimstr,    // ltrimstr
    op_rtrimstr,    // rtrimstr
    op_explode,     // explode (string to codepoints)
    op_implode,     // implode (codepoints to string)
    op_range,       // range generator
    op_null_check,  // null check for has
    op_recurse,     // .. recursive descent
    op_try_start,   // Start try block (mark for error recovery)
    op_try_end,     // End try block (remove mark)
};

pub const Chunk = struct {
    code: std.ArrayListUnmanaged(u8),
    lines: std.ArrayListUnmanaged(usize),
    constants: std.ArrayListUnmanaged(Value),
    
    pub fn init(allocator: Allocator) Chunk {
        _ = allocator;
        return Chunk{
            .code = .{},
            .lines = .{},
            .constants = .{},
        };
    }
    
    pub fn deinit(self: *Chunk, allocator: Allocator) void {
        self.code.deinit(allocator);
        self.lines.deinit(allocator);
        for (self.constants.items) |*val| {
            val.deinit(allocator);
        }
        self.constants.deinit(allocator);
    }
    
    pub fn write(self: *Chunk, allocator: Allocator, byte: u8, line: usize) !void {
        try self.code.append(allocator, byte);
        try self.lines.append(allocator, line);
    }
    
    pub fn writeOp(self: *Chunk, allocator: Allocator, op: OpCode, line: usize) !void {
        try self.write(allocator, @intFromEnum(op), line);
    }
    
    pub fn writeShort(self: *Chunk, allocator: Allocator, short: u16, line: usize) !void {
        try self.write(allocator, @as(u8, @intCast((short >> 8) & 0xFF)), line);
        try self.write(allocator, @as(u8, @intCast(short & 0xFF)), line);
    }
    
    pub fn writeAt(self: *Chunk, offset: usize, byte: u8) void {
        self.code.items[offset] = byte;
    }
    
    pub fn addConstant(self: *Chunk, allocator: Allocator, value: Value) !usize {
        try self.constants.append(allocator, value);
        return self.constants.items.len - 1;
    }
};
