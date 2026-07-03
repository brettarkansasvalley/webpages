const std = @import("std");
const Allocator = std.mem.Allocator;
const Ast = @import("ast.zig");
const Term = Ast.Term;
const Chunk = @import("chunk.zig").Chunk;
const OpCode = @import("chunk.zig").OpCode;
const Value = @import("value.zig").Value;
const Lexer = @import("lexer.zig").Lexer;
const Parser = @import("parser.zig").Parser;

pub const CompilerError = error{
    OutOfMemory,
    CompilationFailed,
};

pub const Compiler = struct {
    allocator: Allocator,
    chunk: *Chunk,
    
    pub fn init(allocator: Allocator, chunk: *Chunk) Compiler {
        return Compiler{
            .allocator = allocator,
            .chunk = chunk,
        };
    }
    
    pub fn compile(self: *Compiler, term: *Term) CompilerError!void {
        switch (term.*) {
            .null_literal => try self.emitOp(.op_nil, 0),
            .bool_literal => |b| try self.emitOp(if (b) .op_true else .op_false, 0),
            .int_literal => |i| {
                const val = Value.fromInteger(i);
                try self.emitConstant(val, 0);
            },
            .float_literal => |f| {
                 // Value doesn't have fromFloat yet? Let's check value.zig or add it.
                 // Assuming Value has float variant.
                 // We need to implement fromFloat in Value or manually construct.
                 // For now let's manually construct.
                 const val = Value{ .float = f };
                 try self.emitConstant(val, 0);
            },
            .str_literal => |s| {
                const val = try Value.fromString(self.allocator, s);
                try self.emitConstant(val, 0);
            },
            .array => |inner| {
                if (inner) |t| {
                    // Use collect semantics: mark stack, run expr, collect all results
                    try self.emitOp(.op_collect_start, 0);
                    try self.compile(t);
                    try self.emitOp(.op_collect_end, 0);
                } else {
                    // Empty array []
                    try self.emitOp(.op_array, 0);
                    try self.emitByte(0, 0);
                }
            },
            .object => |list| {
                // list is ArrayListUnmanaged(ObjectField)
                for (list.items) |field| {
                    // Key
                    if (field.key) |k| {
                        try self.compile(k);
                    } else {
                        // Variable punning or similar? Parser should ensure key exists or is handled.
                        // If null, maybe error or infer from val?
                        // For now assume key exists.
                        return CompilerError.CompilationFailed; 
                    }
                    
                    // Value
                    if (field.val) |v| {
                        try self.compile(v);
                    } else {
                        // Variable punning { $x } -> { "x": $x }
                        // Parser usually handles this by setting key/val.
                         return CompilerError.CompilationFailed;
                    }
                }
                
                try self.emitOp(.op_object, 0);
                try self.emitByte(@intCast(list.items.len), 0);
            },
            .binary => |b| {
                switch (b.op) {
                    .pipe => {
                        // LHS | RHS - handle generators properly
                        // Mark stack position, run LHS, then for each output run RHS
                        try self.emitOp(.op_pipe_start, 0);
                        try self.compile(b.lhs);
                        // op_pipe_each will loop: for each LHS output, set context and jump to RHS
                        const loop_start = try self.emitJump(.op_pipe_each, 0);
                        try self.compile(b.rhs);
                        try self.emitOp(.op_pipe_end, 0);
                        try self.patchJump(loop_start);
                    },
                    .comma => {
                        try self.compile(b.lhs);
                        try self.compile(b.rhs);
                    },
                    .and_op => {
                         // LHS and RHS
                         // if LHS is false, return LHS. Else return RHS.
                         try self.compile(b.lhs);
                         const jump = try self.emitJump(.op_jump_if_false, 0);
                         try self.emitOp(.op_pop, 0); // Discard LHS (it was true)
                         try self.compile(b.rhs);
                         try self.patchJump(jump);
                    },
                    .or_op => {
                         // LHS or RHS
                         // if LHS is true, return LHS. Else return RHS.
                         try self.compile(b.lhs);
                         const jump = try self.emitJump(.op_jump_if_true, 0);
                         try self.emitOp(.op_pop, 0); // Discard LHS (it was false)
                         try self.compile(b.rhs);
                         try self.patchJump(jump);
                    },
                    .alternative => {
                         // LHS // RHS - alternative operator (null coalescing)
                         // if LHS is not null/false, return LHS. Else return RHS.
                         try self.compile(b.lhs);
                         const jump = try self.emitJump(.op_jump_if_not_null, 0);
                         try self.emitOp(.op_pop, 0); // Discard LHS (it was null/false)
                         try self.compile(b.rhs);
                         try self.patchJump(jump);
                    },
                    // Arithmetic and Logic
                    .add => { try self.compile(b.lhs); try self.compile(b.rhs); try self.emitOp(.op_add, 0); },
                    .sub => { try self.compile(b.lhs); try self.compile(b.rhs); try self.emitOp(.op_subtract, 0); },
                    .mul => { try self.compile(b.lhs); try self.compile(b.rhs); try self.emitOp(.op_multiply, 0); },
                    .div => { try self.compile(b.lhs); try self.compile(b.rhs); try self.emitOp(.op_divide, 0); },
                    .rem => { try self.compile(b.lhs); try self.compile(b.rhs); try self.emitOp(.op_modulo, 0); },
                    .eq => { try self.compile(b.lhs); try self.compile(b.rhs); try self.emitOp(.op_equal, 0); },
                    .ne => { try self.compile(b.lhs); try self.compile(b.rhs); try self.emitOp(.op_not_equal, 0); },
                    .lt => { try self.compile(b.lhs); try self.compile(b.rhs); try self.emitOp(.op_less, 0); },
                    .gt => { try self.compile(b.lhs); try self.compile(b.rhs); try self.emitOp(.op_greater, 0); },
                    .le => { try self.compile(b.lhs); try self.compile(b.rhs); try self.emitOp(.op_less_equal, 0); },
                    .ge => { try self.compile(b.lhs); try self.compile(b.rhs); try self.emitOp(.op_greater_equal, 0); },
                    
                    .assign, .update => {
                        // TODO
                        return CompilerError.CompilationFailed;
                    },
                }
            },
            .if_term => |i| {
                // if cond then A else B
                try self.compile(i.cond);
                const jump_else = try self.emitJump(.op_jump_if_false, 0);
                
                try self.emitOp(.op_pop, 0); // Pop condition (true)
                try self.compile(i.then_branch);
                const jump_end = try self.emitJump(.op_jump, 0);
                
                try self.patchJump(jump_else);
                try self.emitOp(.op_pop, 0); // Pop condition (false)
                try self.compile(i.else_branch);
                
                try self.patchJump(jump_end);
            },
            .identity => {
                try self.emitOp(.op_get_input, 0);
            },
            .iterate => {
                // .[]
                // We expect context (input) to be array/object.
                try self.emitOp(.op_get_input, 0); // Get input
                try self.emitOp(.op_iterate, 0);   // Iterate it
            },
            .recurse => {
                // .. recursive descent - outputs current value and all nested values
                try self.emitOp(.op_get_input, 0);
                try self.emitOp(.op_recurse, 0);
            },
            .unary => |u| {
                try self.compile(u.term);
                switch (u.op) {
                    .neg => try self.emitOp(.op_negate, 0),
                    .not => try self.emitOp(.op_not, 0),
                }
            },
            .index => |idx| {
                try self.compile(idx.target);
                try self.compile(idx.index);
                try self.emitOp(.op_index, 0);
            },
            .slice => |s| {
                try self.compile(s.target);
                // Push start (or null for beginning)
                if (s.start) |start| {
                    try self.compile(start);
                } else {
                    try self.emitOp(.op_nil, 0);
                }
                // Push end (or null for end)
                if (s.end) |end| {
                    try self.compile(end);
                } else {
                    try self.emitOp(.op_nil, 0);
                }
                try self.emitOp(.op_slice, 0);
            },
            .call => |c| {
                try self.compileBuiltinWithArgs(c.name, c.args);
            },
            .try_term => |t| {
                // expr? - try operator, suppress errors
                // Emit try_start with jump offset to skip on error
                const try_start = try self.emitJump(.op_try_start, 0);
                try self.compile(t.term);
                try self.emitOp(.op_try_end, 0);
                try self.patchJump(try_start);
                // If catch_term provided, compile it (not common for ?)
                if (t.catch_term) |catch_t| {
                    try self.compile(catch_t);
                }
            },
            else => {},
        }
    }
    
    fn compileBuiltinWithArgs(self: *Compiler, name: []const u8, args: std.ArrayListUnmanaged(Ast.Term)) !void {
        // Handle higher-order functions with filter arguments
        if (std.mem.eql(u8, name, "map")) {
            // map(f) is equivalent to [.[] | f]
            if (args.items.len != 1) return CompilerError.CompilationFailed;
            
            try self.emitOp(.op_collect_start, 0);
            try self.emitOp(.op_pipe_start, 0);
            try self.emitOp(.op_get_input, 0);
            try self.emitOp(.op_iterate, 0);
            const loop_start = try self.emitJump(.op_pipe_each, 0);
            var arg_term = args.items[0];
            try self.compile(&arg_term);
            try self.emitOp(.op_pipe_end, 0);
            try self.patchJump(loop_start);
            try self.emitOp(.op_collect_end, 0);
            return;
        } else if (std.mem.eql(u8, name, "select")) {
            // select(f) outputs input if f is truthy, otherwise empty
            if (args.items.len != 1) return CompilerError.CompilationFailed;
            
            try self.emitOp(.op_get_input, 0);
            try self.emitOp(.op_dup, 0);  // Keep a copy of input
            try self.emitOp(.op_push_context, 0);
            var arg_term = args.items[0];
            try self.compile(&arg_term);  // Evaluate filter
            try self.emitOp(.op_pop_context, 0);
            
            // If filter result is falsy, pop the input copy (empty output)
            const jump_keep = try self.emitJump(.op_jump_if_true, 0);
            try self.emitOp(.op_pop, 0);  // Discard filter result
            try self.emitOp(.op_pop, 0);  // Discard input copy
            const jump_end = try self.emitJump(.op_jump, 0);
            
            try self.patchJump(jump_keep);
            try self.emitOp(.op_pop, 0);  // Discard filter result, keep input
            try self.patchJump(jump_end);
            return;
        }
        
        // Builtins with string argument
        if (std.mem.eql(u8, name, "has")) {
            if (args.items.len != 1) return CompilerError.CompilationFailed;
            try self.emitOp(.op_get_input, 0);
            var arg = args.items[0];
            try self.compile(&arg);
            try self.emitOp(.op_has, 0);
            return;
        } else if (std.mem.eql(u8, name, "split")) {
            if (args.items.len != 1) return CompilerError.CompilationFailed;
            try self.emitOp(.op_get_input, 0);
            var arg = args.items[0];
            try self.compile(&arg);
            try self.emitOp(.op_split, 0);
            return;
        } else if (std.mem.eql(u8, name, "join")) {
            if (args.items.len != 1) return CompilerError.CompilationFailed;
            try self.emitOp(.op_get_input, 0);
            var arg = args.items[0];
            try self.compile(&arg);
            try self.emitOp(.op_join, 0);
            return;
        } else if (std.mem.eql(u8, name, "startswith")) {
            if (args.items.len != 1) return CompilerError.CompilationFailed;
            try self.emitOp(.op_get_input, 0);
            var arg = args.items[0];
            try self.compile(&arg);
            try self.emitOp(.op_startswith, 0);
            return;
        } else if (std.mem.eql(u8, name, "endswith")) {
            if (args.items.len != 1) return CompilerError.CompilationFailed;
            try self.emitOp(.op_get_input, 0);
            var arg = args.items[0];
            try self.compile(&arg);
            try self.emitOp(.op_endswith, 0);
            return;
        } else if (std.mem.eql(u8, name, "ltrimstr")) {
            if (args.items.len != 1) return CompilerError.CompilationFailed;
            try self.emitOp(.op_get_input, 0);
            var arg = args.items[0];
            try self.compile(&arg);
            try self.emitOp(.op_ltrimstr, 0);
            return;
        } else if (std.mem.eql(u8, name, "rtrimstr")) {
            if (args.items.len != 1) return CompilerError.CompilationFailed;
            try self.emitOp(.op_get_input, 0);
            var arg = args.items[0];
            try self.compile(&arg);
            try self.emitOp(.op_rtrimstr, 0);
            return;
        } else if (std.mem.eql(u8, name, "contains")) {
            if (args.items.len != 1) return CompilerError.CompilationFailed;
            try self.emitOp(.op_get_input, 0);
            var arg = args.items[0];
            try self.compile(&arg);
            try self.emitOp(.op_contains, 0);
            return;

        } else if (std.mem.eql(u8, name, "inside")) {
            if (args.items.len != 1) return CompilerError.CompilationFailed;
            try self.emitOp(.op_get_input, 0);
            var arg = args.items[0];
            try self.compile(&arg);
            try self.emitOp(.op_inside, 0);
            return;
        } else if (std.mem.eql(u8, name, "group_by")) {
            // group_by(f) - groups array elements by f evaluation
            // Similar to map, but groups results instead of collecting
            if (args.items.len != 1) return CompilerError.CompilationFailed;
            
            // This needs special handling - we'll use a custom opcode
            // that takes the array and evaluates f on each element
            try self.emitOp(.op_get_input, 0);
            var arg_term = args.items[0];
            
            // Store the filter expression - op_group_by_iterate will use it
            // For now, emit it and let the VM handle it properly
            try self.compile(&arg_term);
            try self.emitOp(.op_group_by, 0);
            return;
        }
        
        // Regular builtins without arguments
        try self.compileBuiltin(name);
    }
    
    fn compileBuiltin(self: *Compiler, name: []const u8) !void {
        // Get input first for most builtins
        try self.emitOp(.op_get_input, 0);
        
        if (std.mem.eql(u8, name, "length")) {
            try self.emitOp(.op_length, 0);
        } else if (std.mem.eql(u8, name, "keys")) {
            try self.emitOp(.op_keys, 0);
        } else if (std.mem.eql(u8, name, "values")) {
            try self.emitOp(.op_values, 0);
        } else if (std.mem.eql(u8, name, "type")) {
            try self.emitOp(.op_type, 0);
        } else if (std.mem.eql(u8, name, "empty")) {
            _ = self.chunk.code.pop(); // Remove op_get_input
            try self.emitOp(.op_empty, 0);
        } else if (std.mem.eql(u8, name, "first")) {
            try self.emitOp(.op_first, 0);
        } else if (std.mem.eql(u8, name, "last")) {
            try self.emitOp(.op_last, 0);
        } else if (std.mem.eql(u8, name, "reverse")) {
            try self.emitOp(.op_reverse, 0);
        } else if (std.mem.eql(u8, name, "sort")) {
            try self.emitOp(.op_sort, 0);
        } else if (std.mem.eql(u8, name, "flatten")) {
            try self.emitOp(.op_flatten, 0);
        } else if (std.mem.eql(u8, name, "not")) {
            try self.emitOp(.op_not, 0);
        } else if (std.mem.eql(u8, name, "null")) {
            _ = self.chunk.code.pop();
            try self.emitOp(.op_nil, 0);
        } else if (std.mem.eql(u8, name, "true")) {
            _ = self.chunk.code.pop();
            try self.emitOp(.op_true, 0);
        } else if (std.mem.eql(u8, name, "false")) {
            _ = self.chunk.code.pop();
            try self.emitOp(.op_false, 0);
        } else if (std.mem.eql(u8, name, "tostring")) {
            try self.emitOp(.op_tostring, 0);
        } else if (std.mem.eql(u8, name, "tonumber")) {
            try self.emitOp(.op_tonumber, 0);
        } else if (std.mem.eql(u8, name, "floor")) {
            try self.emitOp(.op_floor, 0);
        } else if (std.mem.eql(u8, name, "ceil")) {
            try self.emitOp(.op_ceil, 0);
        } else if (std.mem.eql(u8, name, "round")) {
            try self.emitOp(.op_round, 0);
        } else if (std.mem.eql(u8, name, "sqrt")) {
            try self.emitOp(.op_sqrt, 0);
        } else if (std.mem.eql(u8, name, "abs")) {
            try self.emitOp(.op_abs, 0);
        } else if (std.mem.eql(u8, name, "min")) {
            try self.emitOp(.op_min, 0);
        } else if (std.mem.eql(u8, name, "max")) {
            try self.emitOp(.op_max, 0);
        } else if (std.mem.eql(u8, name, "add")) {
            try self.emitOp(.op_add_values, 0);
        } else if (std.mem.eql(u8, name, "unique")) {
            try self.emitOp(.op_unique, 0);
        } else if (std.mem.eql(u8, name, "to_entries")) {
            try self.emitOp(.op_to_entries, 0);
        } else if (std.mem.eql(u8, name, "from_entries")) {
            try self.emitOp(.op_from_entries, 0);
        } else if (std.mem.eql(u8, name, "explode")) {
            try self.emitOp(.op_explode, 0);
        } else if (std.mem.eql(u8, name, "implode")) {
            try self.emitOp(.op_implode, 0);
        } else if (std.mem.eql(u8, name, "ascii_downcase")) {
            try self.emitOp(.op_ascii_downcase, 0);
        } else if (std.mem.eql(u8, name, "ascii_upcase")) {
            try self.emitOp(.op_ascii_upcase, 0);
        } else if (std.mem.eql(u8, name, "debug")) {
            try self.emitOp(.op_debug, 0);
        } else if (std.mem.eql(u8, name, "error")) {
            try self.emitOp(.op_error_op, 0);
        } else {
            // Unknown function - for now just return identity
            // TODO: Proper error handling or user-defined functions
        }
    }
    
    fn emitOp(self: *Compiler, op: OpCode, line: usize) !void {
        try self.chunk.writeOp(self.allocator, op, line);
    }
    
    fn emitByte(self: *Compiler, byte: u8, line: usize) !void {
        try self.chunk.write(self.allocator, byte, line);
    }
    
    fn emitConstant(self: *Compiler, value: Value, line: usize) !void {
        const idx = try self.chunk.addConstant(self.allocator, value);
        // Assuming constant index fits in u8 for now
        if (idx > 255) return CompilerError.CompilationFailed; // TODO: OpConstant16
        try self.emitOp(.op_constant, line);
        try self.emitByte(@intCast(idx), line);
    }

    fn emitShort(self: *Compiler, value: u16, line: usize) !void {
        try self.chunk.writeShort(self.allocator, value, line);
    }
    
    fn emitJump(self: *Compiler, op: OpCode, line: usize) !usize {
        try self.emitOp(op, line);
        try self.emitShort(0xFFFF, line); // Placeholder
        return self.chunk.code.items.len - 2;
    }
    
    fn patchJump(self: *Compiler, offset: usize) !void {
        const jump = self.chunk.code.items.len - offset - 2;
        if (jump > std.math.maxInt(u16)) return CompilerError.CompilationFailed;
        
        const short = @as(u16, @intCast(jump));
        self.chunk.writeAt(offset, @as(u8, @intCast((short >> 8) & 0xFF)));
        self.chunk.writeAt(offset + 1, @as(u8, @intCast(short & 0xFF)));
    }
    
    fn countList(self: *Compiler, term: *Term) usize {
        switch (term.*) {
            .binary => |b| {
                if (b.op == .comma) {
                    return self.countList(b.lhs) + self.countList(b.rhs);
                }
                return 1;
            },
            else => return 1,
        }
    }
    
    fn compileList(self: *Compiler, term: *Term) CompilerError!void {
        switch (term.*) {
            .binary => |b| {
                if (b.op == .comma) {
                    try self.compileList(b.lhs);
                    try self.compileList(b.rhs);
                    return;
                }
            },
            else => {},
        }
        try self.compile(term);
    }
};

test "Compiler basic" {
    const allocator = std.testing.allocator;
    var chunk = Chunk.init(allocator);
    defer chunk.deinit(allocator);
    
    var compiler = Compiler.init(allocator, &chunk);
    
    // Manual AST construction for testing
    var term_int = Term{ .int_literal = 42 };
    
    try compiler.compile(&term_int);
    
    try std.testing.expectEqual(chunk.code.items.len, 2); // OpConstant + Index
    try std.testing.expectEqual(chunk.code.items[0], @intFromEnum(OpCode.op_constant));
}

test "Compiler if" {
    const allocator = std.testing.allocator;
    var chunk = Chunk.init(allocator);
    defer chunk.deinit(allocator);
    
    var compiler = Compiler.init(allocator, &chunk);
    
    // if true then 1 else 2
    var term_true = Term{ .bool_literal = true };
    var term_1 = Term{ .int_literal = 1 };
    var term_2 = Term{ .int_literal = 2 };
    var term_if = Term{ .if_term = .{ .cond = &term_true, .then_branch = &term_1, .else_branch = &term_2 } };
    
    try compiler.compile(&term_if);
    
    // Expected:
    // OpTrue
    // OpJumpIfFalse (offset)
    // OpPop
    // OpConstant(1)
    // OpJump (offset)
    // OpPop (target of JumpIfFalse)
    // OpConstant(2)
    // Target of Jump
    
    // Just check it compiled something reasonable
    try std.testing.expect(chunk.code.items.len > 5);
}
