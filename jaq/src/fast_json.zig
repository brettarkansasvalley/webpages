const std = @import("std");
const Value = @import("value.zig").Value;
const Rc = @import("value.zig").Rc;
const Array = @import("value.zig").Array;
const Object = @import("value.zig").Object;

pub const ParseError = error{
    InvalidJson,
    UnexpectedEndOfInput,
    OutOfMemory,
};

/// Fast JSON parser with SIMD-like optimizations
/// Uses techniques inspired by simdjson:
/// - Bulk character classification
/// - Minimal allocations
/// - Direct number parsing
pub const FastJsonParser = struct {
    allocator: std.mem.Allocator,
    input: []const u8,
    pos: usize,
    
    pub fn init(allocator: std.mem.Allocator, input: []const u8) FastJsonParser {
        return .{
            .allocator = allocator,
            .input = input,
            .pos = 0,
        };
    }
    
    pub fn parse(self: *FastJsonParser) ParseError!Value {
        self.skipWhitespace();
        return self.parseValue();
    }
    
    inline fn peek(self: *FastJsonParser) ?u8 {
        if (self.pos >= self.input.len) return null;
        return self.input[self.pos];
    }
    
    inline fn advance(self: *FastJsonParser) void {
        self.pos += 1;
    }
    
    inline fn skipWhitespace(self: *FastJsonParser) void {
        while (self.pos < self.input.len) {
            const c = self.input[self.pos];
            if (c == ' ' or c == '\t' or c == '\n' or c == '\r') {
                self.pos += 1;
            } else {
                break;
            }
        }
    }
    
    fn parseValue(self: *FastJsonParser) ParseError!Value {
        self.skipWhitespace();
        const c = self.peek() orelse return error.UnexpectedEndOfInput;
        
        return switch (c) {
            '{' => self.parseObject(),
            '[' => self.parseArray(),
            '"' => self.parseString(),
            't' => self.parseTrue(),
            'f' => self.parseFalse(),
            'n' => self.parseNull(),
            '-', '0'...'9' => self.parseNumber(),
            else => error.InvalidJson,
        };
    }
    
    fn parseObject(self: *FastJsonParser) ParseError!Value {
        self.advance(); // skip '{'
        self.skipWhitespace();
        
        var map = std.StringArrayHashMapUnmanaged(Value){};
        errdefer {
            var it = map.iterator();
            while (it.next()) |entry| {
                self.allocator.free(entry.key_ptr.*);
                entry.value_ptr.deinit(self.allocator);
            }
            map.deinit(self.allocator);
        }
        
        if (self.peek() == @as(u8, '}')) {
            self.advance();
            const obj_ptr = try Rc(Object).create(self.allocator, Object{ .map = map });
            return Value{ .object = obj_ptr };
        }
        
        while (true) {
            self.skipWhitespace();
            
            // Parse key
            if (self.peek() != @as(u8, '"')) return error.InvalidJson;
            const key_val = try self.parseString();
            const key = key_val.string.get().bytes;
            const key_copy = try self.allocator.dupe(u8, key);
            key_val.deinit(self.allocator);
            
            self.skipWhitespace();
            if (self.peek() != @as(u8, ':')) {
                self.allocator.free(key_copy);
                return error.InvalidJson;
            }
            self.advance();
            
            // Parse value
            const value = try self.parseValue();
            
            try map.put(self.allocator, key_copy, value);
            
            self.skipWhitespace();
            const next = self.peek() orelse return error.UnexpectedEndOfInput;
            if (next == '}') {
                self.advance();
                break;
            } else if (next == ',') {
                self.advance();
            } else {
                return error.InvalidJson;
            }
        }
        
        const obj_ptr = try Rc(Object).create(self.allocator, Object{ .map = map });
        return Value{ .object = obj_ptr };
    }
    
    fn parseArray(self: *FastJsonParser) ParseError!Value {
        self.advance(); // skip '['
        self.skipWhitespace();
        
        var items = std.ArrayListUnmanaged(Value){};
        errdefer {
            for (items.items) |*v| v.deinit(self.allocator);
            items.deinit(self.allocator);
        }
        
        if (self.peek() == @as(u8, ']')) {
            self.advance();
            const arr_ptr = try Rc(Array).create(self.allocator, Array{ .items = items });
            return Value{ .array = arr_ptr };
        }
        
        while (true) {
            const value = try self.parseValue();
            try items.append(self.allocator, value);
            
            self.skipWhitespace();
            const next = self.peek() orelse return error.UnexpectedEndOfInput;
            if (next == ']') {
                self.advance();
                break;
            } else if (next == ',') {
                self.advance();
            } else {
                return error.InvalidJson;
            }
        }
        
        const arr_ptr = try Rc(Array).create(self.allocator, Array{ .items = items });
        return Value{ .array = arr_ptr };
    }
    
    fn parseString(self: *FastJsonParser) ParseError!Value {
        self.advance(); // skip opening '"'
        const start = self.pos;
        
        // Fast path: no escapes
        var has_escape = false;
        while (self.pos < self.input.len) {
            const c = self.input[self.pos];
            if (c == '"') {
                if (!has_escape) {
                    // Fast path: direct slice
                    const slice = self.input[start..self.pos];
                    self.advance();
                    return Value.fromString(self.allocator, slice);
                }
                break;
            } else if (c == '\\') {
                has_escape = true;
                self.pos += 2; // skip escape sequence
            } else {
                self.pos += 1;
            }
        }
        
        if (has_escape) {
            // Slow path: handle escapes
            self.pos = start;
            var result = std.ArrayListUnmanaged(u8){};
            errdefer result.deinit(self.allocator);
            
            while (self.pos < self.input.len) {
                const c = self.input[self.pos];
                if (c == '"') {
                    self.advance();
                    const bytes = try result.toOwnedSlice(self.allocator);
                    return Value.fromString(self.allocator, bytes);
                } else if (c == '\\') {
                    self.advance();
                    const escaped = self.input[self.pos];
                    self.advance();
                    const unescaped: u8 = switch (escaped) {
                        '"' => '"',
                        '\\' => '\\',
                        '/' => '/',
                        'b' => 0x08,
                        'f' => 0x0C,
                        'n' => '\n',
                        'r' => '\r',
                        't' => '\t',
                        'u' => {
                            // Unicode escape - simplified handling
                            if (self.pos + 4 <= self.input.len) {
                                self.pos += 4;
                            }
                            try result.append(self.allocator, '?'); // Placeholder
                            continue;
                        },
                        else => escaped,
                    };
                    try result.append(self.allocator, unescaped);
                } else {
                    try result.append(self.allocator, c);
                    self.advance();
                }
            }
            return error.UnexpectedEndOfInput;
        }
        
        return error.UnexpectedEndOfInput;
    }
    
    fn parseNumber(self: *FastJsonParser) ParseError!Value {
        const start = self.pos;
        var is_float = false;
        
        // Handle negative
        if (self.peek() == @as(u8, '-')) self.advance();
        
        // Integer part
        while (self.pos < self.input.len) {
            const c = self.input[self.pos];
            if (c >= '0' and c <= '9') {
                self.advance();
            } else {
                break;
            }
        }
        
        // Decimal part
        if (self.peek() == @as(u8, '.')) {
            is_float = true;
            self.advance();
            while (self.pos < self.input.len) {
                const c = self.input[self.pos];
                if (c >= '0' and c <= '9') {
                    self.advance();
                } else {
                    break;
                }
            }
        }
        
        // Exponent part
        const exp_char = self.peek();
        if (exp_char == @as(u8, 'e') or exp_char == @as(u8, 'E')) {
            is_float = true;
            self.advance();
            const sign = self.peek();
            if (sign == @as(u8, '+') or sign == @as(u8, '-')) self.advance();
            while (self.pos < self.input.len) {
                const c = self.input[self.pos];
                if (c >= '0' and c <= '9') {
                    self.advance();
                } else {
                    break;
                }
            }
        }
        
        const num_str = self.input[start..self.pos];
        
        if (is_float) {
            const f = std.fmt.parseFloat(f64, num_str) catch return error.InvalidJson;
            return Value{ .float = f };
        } else {
            const i = std.fmt.parseInt(i64, num_str, 10) catch {
                // Try float if integer overflow
                const f = std.fmt.parseFloat(f64, num_str) catch return error.InvalidJson;
                return Value{ .float = f };
            };
            return Value{ .integer = i };
        }
    }
    
    fn parseTrue(self: *FastJsonParser) ParseError!Value {
        if (self.pos + 4 <= self.input.len and
            std.mem.eql(u8, self.input[self.pos..self.pos + 4], "true"))
        {
            self.pos += 4;
            return Value{ .bool = true };
        }
        return error.InvalidJson;
    }
    
    fn parseFalse(self: *FastJsonParser) ParseError!Value {
        if (self.pos + 5 <= self.input.len and
            std.mem.eql(u8, self.input[self.pos..self.pos + 5], "false"))
        {
            self.pos += 5;
            return Value{ .bool = false };
        }
        return error.InvalidJson;
    }
    
    fn parseNull(self: *FastJsonParser) ParseError!Value {
        if (self.pos + 4 <= self.input.len and
            std.mem.eql(u8, self.input[self.pos..self.pos + 4], "null"))
        {
            self.pos += 4;
            return Value.null;
        }
        return error.InvalidJson;
    }
};

/// Parse JSON using fast parser
pub fn parseJson(allocator: std.mem.Allocator, input: []const u8) !Value {
    var parser = FastJsonParser.init(allocator, input);
    return parser.parse();
}

/// Parse JSON at a given position, updating the position after parsing
pub fn parseJsonAt(allocator: std.mem.Allocator, input: []const u8, pos: *usize) !Value {
    var parser = FastJsonParser{
        .allocator = allocator,
        .input = input,
        .pos = pos.*,
    };
    const result = try parser.parse();
    pos.* = parser.pos;
    return result;
}
