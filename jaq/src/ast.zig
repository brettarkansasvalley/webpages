const std = @import("std");
const Value = @import("value.zig").Value;

pub const BinaryOp = enum {
    // Pipe
    pipe,           // |
    comma,          // ,
    
    // Assignment
    assign,         // =
    update,         // |=
    
    // Logic
    or_op,          // or
    and_op,         // and
    alternative,    // //
    
    // Math
    add,            // +
    sub,            // -
    mul,            // *
    div,            // /
    rem,            // %
    
    // Comparison
    eq,             // ==
    ne,             // !=
    lt,             // <
    gt,             // >
    le,             // <=
    ge,             // >=
};

pub const UnaryOp = enum {
    neg,            // -
    not,            // not
};

pub const Term = union(enum) {
    // Core
    identity,       // .
    recurse,        // ..
    iterate,        // .[]
    
    // Literals
    null_literal,
    bool_literal: bool,
    int_literal: i64,
    float_literal: f64,
    str_literal: []const u8,
    
    // Construction
    array: ?*Term,            // [ term ] (optional because [] is empty array)
    object: std.ArrayListUnmanaged(ObjectField), // { key: val, ... }
    
    // Operations
    binary: struct {
        op: BinaryOp,
        lhs: *Term,
        rhs: *Term,
    },
    unary: struct {
        op: UnaryOp,
        term: *Term,
    },
    
    // Path access / Indexing
    index: struct {           // term[index] or term.field
        target: *Term,
        index: *Term,         // Index is an expression, e.g. .["field"] or .[0]
        optional: bool,       // ? suffix
    },
    
    // Slice
    slice: struct {           // term[start:end]
        target: *Term,
        start: ?*Term,        // null means from beginning
        end: ?*Term,          // null means to end
    },
    
    // Control Flow
    if_term: struct {
        cond: *Term,
        then_branch: *Term,
        else_branch: *Term,
    },
    
    try_term: struct {
        term: *Term,
        catch_term: ?*Term,
    },
    
    // Variables & Functions
    variable: []const u8,     // $var
    call: struct {            // func(args...)
        name: []const u8,
        args: std.ArrayListUnmanaged(Term),
    },
    
    // Definitions
    def: struct {
        name: []const u8,
        args: std.ArrayListUnmanaged([]const u8), // Argument names
        body: *Term,
        next: *Term,          // The rest of the program where this def is visible
    },
};

pub const ObjectField = struct {
    key: ?*Term,  // Key expression (null if variable punning e.g. {$x})
    val: ?*Term,  // Value expression (null if variable punning)
};

pub const Ast = struct {
    root: *Term,
    allocator: std.mem.Allocator,
    
    pub fn deinit(self: Ast) void {
        self.freeTerm(self.root);
    }
    
    fn freeTermContents(self: Ast, term: *Term) void {
        // Free internal resources of a Term without freeing the Term itself
        switch (term.*) {
            .str_literal => |s| self.allocator.free(s),
            .variable => |v| self.allocator.free(v),
            .array => |t| if (t) |tt| self.freeTerm(tt),
            .object => |*obj| {
                for (obj.items) |*field| {
                    if (field.key) |k| self.freeTerm(k);
                    if (field.val) |v| self.freeTerm(v);
                }
                obj.deinit(self.allocator);
            },
            .binary => |*b| {
                self.freeTerm(b.lhs);
                self.freeTerm(b.rhs);
            },
            .unary => |*u| self.freeTerm(u.term),
            .index => |*i| {
                self.freeTerm(i.target);
                self.freeTerm(i.index);
            },
            .slice => |*s| {
                self.freeTerm(s.target);
                if (s.start) |start| self.freeTerm(start);
                if (s.end) |end| self.freeTerm(end);
            },
            .if_term => |*i| {
                self.freeTerm(i.cond);
                self.freeTerm(i.then_branch);
                self.freeTerm(i.else_branch);
            },
            .try_term => |*t| {
                self.freeTerm(t.term);
                if (t.catch_term) |c| self.freeTerm(c);
            },
            .call => |*c| {
                self.allocator.free(c.name);
                for (c.args.items) |*arg| {
                    self.freeTermContents(arg);
                }
                c.args.deinit(self.allocator);
            },
            .def => |*d| {
                self.allocator.free(d.name);
                for (d.args.items) |arg| {
                    self.allocator.free(arg);
                }
                d.args.deinit(self.allocator);
                self.freeTerm(d.body);
                self.freeTerm(d.next);
            },
            else => {},
        }
    }
    
    fn freeTerm(self: Ast, term: *Term) void {
        switch (term.*) {
            .str_literal => |s| self.allocator.free(s),
            .variable => |v| self.allocator.free(v),
            .array => |t| if (t) |tt| self.freeTerm(tt),
            .object => |*obj| {
                for (obj.items) |*field| {
                    if (field.key) |k| self.freeTerm(k);
                    if (field.val) |v| self.freeTerm(v);
                }
                obj.deinit(self.allocator);
            },
            .binary => |*b| {
                self.freeTerm(b.lhs);
                self.freeTerm(b.rhs);
            },
            .unary => |*u| self.freeTerm(u.term),
            .index => |*i| {
                self.freeTerm(i.target);
                self.freeTerm(i.index);
            },
            .slice => |*s| {
                self.freeTerm(s.target);
                if (s.start) |start| self.freeTerm(start);
                if (s.end) |end| self.freeTerm(end);
            },
            .if_term => |*i| {
                self.freeTerm(i.cond);
                self.freeTerm(i.then_branch);
                self.freeTerm(i.else_branch);
            },
            .try_term => |*t| {
                self.freeTerm(t.term);
                if (t.catch_term) |c| self.freeTerm(c);
            },
            .call => |*c| {
                self.allocator.free(c.name);
                for (c.args.items) |*arg| {
                    // Args are stored inline, not as pointers, so just free their contents
                    self.freeTermContents(arg);
                }
                c.args.deinit(self.allocator);
            },
            .def => |*d| {
                self.allocator.free(d.name);
                for (d.args.items) |arg| {
                    self.allocator.free(arg);
                }
                d.args.deinit(self.allocator);
                self.freeTerm(d.body);
                self.freeTerm(d.next);
            },
            else => {},
        }
        self.allocator.destroy(term);
    }
};
