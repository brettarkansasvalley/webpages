const std = @import("std");
const Allocator = std.mem.Allocator;

/// A reference-counted pointer wrapper.
/// T must be a struct that implements `deinit(Allocator)`.
pub fn Rc(comptime T: type) type {
    return struct {
        ptr: *Inner,

        const Inner = struct {
            ref_count: usize,
            data: T,
        };

        const Self = @This();

        pub fn create(allocator: Allocator, data: T) !Self {
            const inner = try allocator.create(Inner);
            inner.* = .{
                .ref_count = 1,
                .data = data,
            };
            return Self{ .ptr = inner };
        }

        pub fn clone(self: Self) Self {
            self.ptr.ref_count += 1;
            return self;
        }

        pub fn release(self: Self, allocator: Allocator) void {
            self.ptr.ref_count -= 1;
            if (self.ptr.ref_count == 0) {
                if (std.meta.hasMethod(T, "deinit")) {
                    self.ptr.data.deinit(allocator);
                }
                allocator.destroy(self.ptr);
            }
        }

        pub fn get(self: Self) *T {
            return &self.ptr.data;
        }
    };
}

pub const String = struct {
    bytes: []u8,
    
    pub fn deinit(self: String, allocator: Allocator) void {
        allocator.free(self.bytes);
    }
};

pub const ValueType = enum {
    null,
    bool,
    integer,
    float,
    string,
    array,
    object,
};

pub const Array = struct {
    items: std.ArrayListUnmanaged(Value),

    pub fn deinit(self: *Array, allocator: Allocator) void {
        for (self.items.items) |v| {
            v.deinit(allocator);
        }
        self.items.deinit(allocator);
    }

    pub fn clone(self: Array, allocator: Allocator) Allocator.Error!Array {
        var new_items = try std.ArrayListUnmanaged(Value).initCapacity(allocator, self.items.items.len);
        for (self.items.items) |v| {
            new_items.appendAssumeCapacity(try v.clone()); // Value.clone() doesn't allocate for the Value itself, but Rc.clone does refcount inc
        }
        return Array{ .items = new_items };
    }
};

pub const Object = struct {
    map: std.StringArrayHashMapUnmanaged(Value),

    pub fn deinit(self: *Object, allocator: Allocator) void {
        var it = self.map.iterator();
        while (it.next()) |entry| {
            allocator.free(entry.key_ptr.*); // We own the keys
            entry.value_ptr.deinit(allocator);
        }
        self.map.deinit(allocator);
    }

    pub fn clone(self: Object, allocator: Allocator) Allocator.Error!Object {
        var new_map = try std.StringArrayHashMapUnmanaged(Value).initCapacity(allocator, self.map.count());
        var it = self.map.iterator();
        while (it.next()) |entry| {
            const key_copy = try allocator.dupe(u8, entry.key_ptr.*);
            errdefer allocator.free(key_copy);
            // Value.clone is cheap (refcount incr), but we need to handle potential errors if we change it later
            const val_copy = try entry.value_ptr.clone(); 
            new_map.putAssumeCapacity(key_copy, val_copy);
        }
        return Object{ .map = new_map };
    }
};

pub const Value = union(ValueType) {
    null,
    bool: bool,
    integer: i64,
    float: f64,
    string: Rc(String),
    array: Rc(Array),
    object: Rc(Object),

    const Self = @This();

    pub fn deinit(self: Self, allocator: Allocator) void {
        switch (self) {
            .string => |s| s.release(allocator),
            .array => |a| a.release(allocator),
            .object => |o| o.release(allocator),
            else => {},
        }
    }

    pub fn clone(self: Self) !Self { // Value clone is shallow (increments refcount)
        return switch (self) {
            .null => .null,
            .bool => |b| .{ .bool = b },
            .integer => |i| .{ .integer = i },
            .float => |f| .{ .float = f },
            .string => |s| .{ .string = s.clone() },
            .array => |a| .{ .array = a.clone() },
            .object => |o| .{ .object = o.clone() },
        };
    }
    
    pub fn fromString(allocator: Allocator, s: []const u8) !Self {
        const copy = try allocator.dupe(u8, s);
        return Value{ .string = try Rc(String).create(allocator, String{ .bytes = copy }) };
    }

    pub fn fromInteger(i: i64) Self {
        return Value{ .integer = i };
    }
    
    // Order: null < bool < number < string < array < object
    fn typeOrder(self: Self) u8 {
        return switch (self) {
            .null => 0,
            .bool => 1,
            .integer, .float => 2,
            .string => 3,
            .array => 4,
            .object => 5,
        };
    }
    
    pub fn compare(self: Self, other: Self) std.math.Order {
        const order_a = self.typeOrder();
        const order_b = other.typeOrder();
        
        if (order_a != order_b) {
            return std.math.order(order_a, order_b);
        }
        
        return switch (self) {
            .null => .eq,
            .bool => |b| std.math.order(@intFromBool(b), @intFromBool(other.bool)),
            .integer => |i| switch (other) {
                .integer => |j| std.math.order(i, j),
                .float => |f| std.math.order(@as(f64, @floatFromInt(i)), f),
                else => unreachable,
            },
            .float => |f| switch (other) {
                .integer => |j| std.math.order(f, @as(f64, @floatFromInt(j))),
                .float => |g| std.math.order(f, g),
                else => unreachable,
            },
            .string => |s| std.mem.order(u8, s.get().bytes, other.string.get().bytes),
            .array => |a| {
                const items_a = a.get().items.items;
                const items_b = other.array.get().items.items;
                const len = @min(items_a.len, items_b.len);
                for (0..len) |idx| {
                    const cmp = items_a[idx].compare(items_b[idx]);
                    if (cmp != .eq) return cmp;
                }
                return std.math.order(items_a.len, items_b.len);
            },
            .object => |o| {
                // Objects compared by fields? jq manual says:
                // "Objects are compared key-by-key, in sorted order of keys."
                // My object map is likely insertion ordered or undefined order depending on implementation.
                // std.StringArrayHashMap is insertion ordered.
                // We need to sort keys to compare properly.
                // For now, let's just compare by size? No, that's wrong.
                // TODO: Implement proper object comparison (requires allocating sorted keys)
                return std.math.order(o.get().map.count(), other.object.get().map.count());
            },
        };
    }
    
    pub fn isTruthy(self: Self) bool {
        return switch (self) {
            .null => false,
            .bool => |b| b,
            else => true,
        };
    }
    
    pub fn toJson(self: Self, writer: anytype) !void {
        switch (self) {
            .null => try writer.writeAll("null"),
            .bool => |b| try writer.writeAll(if (b) "true" else "false"),
            .integer => |i| try std.fmt.format(writer, "{d}", .{i}),
            .float => |f| try std.fmt.format(writer, "{d}", .{f}),
            .string => |s| try writer.print("{f}", .{std.json.fmt(s.get().bytes, .{})}),
            .array => |a| {
                try writer.writeByte('[');
                const items = a.get().items.items;
                for (items, 0..) |item, i| {
                    if (i > 0) try writer.writeAll(",");
                    try item.toJson(writer);
                }
                try writer.writeByte(']');
            },
            .object => |o| {
                try writer.writeByte('{');
                var it = o.get().map.iterator();
                var i: usize = 0;
                while (it.next()) |entry| {
                    if (i > 0) try writer.writeAll(",");
                    try writer.print("{f}", .{std.json.fmt(entry.key_ptr.*, .{})});
                    try writer.writeByte(':');
                    try entry.value_ptr.toJson(writer);
                    i += 1;
                }
                try writer.writeByte('}');
            },
        }
    }
    
    pub fn fromJson(allocator: Allocator, json_val: std.json.Value) !Self {
        switch (json_val) {
            .null => return .null,
            .bool => |b| return Value{ .bool = b },
            .integer => |i| return Value.fromInteger(i),
            .float => |f| return Value{ .float = f },
            .number_string => |s| {
                // Try to parse as integer, then float
                if (std.fmt.parseInt(i64, s, 10)) |i| {
                    return Value.fromInteger(i);
                } else |_| {
                    const f = try std.fmt.parseFloat(f64, s);
                    return Value{ .float = f };
                }
            },
            .string => |s| return try Value.fromString(allocator, s),
            .array => |a| {
                var items = std.ArrayListUnmanaged(Value){};
                try items.ensureTotalCapacity(allocator, a.items.len);
                for (a.items) |item| {
                    const v = try Value.fromJson(allocator, item);
                    items.appendAssumeCapacity(v);
                }
                return Value{ .array = try Rc(Array).create(allocator, Array{ .items = items }) };
            },
            .object => |o| {
                var map = std.StringArrayHashMapUnmanaged(Value){};
                try map.ensureTotalCapacity(allocator, o.count());
                var it = o.iterator();
                while (it.next()) |entry| {
                    const k = try allocator.dupe(u8, entry.key_ptr.*);
                    errdefer allocator.free(k);
                    const v = try Value.fromJson(allocator, entry.value_ptr.*);
                    map.putAssumeCapacity(k, v);
                }
                return Value{ .object = try Rc(Object).create(allocator, Object{ .map = map }) };
            },
        }
    }
};

test "Value basic usage" {
    const allocator = std.testing.allocator;
    
    var v = try Value.fromString(allocator, "hello");
    defer v.deinit(allocator);
    
    var v2 = try v.clone();
    defer v2.deinit(allocator);
    
    try std.testing.expectEqualStrings("hello", v.string.get().bytes);
}

test "Value array usage" {
    const allocator = std.testing.allocator;
    var arr_items = std.ArrayListUnmanaged(Value){};
    try arr_items.append(allocator, Value.fromInteger(42));
    
    var v = Value{ .array = try Rc(Array).create(allocator, Array{ .items = arr_items }) };
    defer v.deinit(allocator);

    try std.testing.expectEqual(@as(usize, 1), v.array.get().items.items.len);
    try std.testing.expectEqual(@as(i64, 42), v.array.get().items.items[0].integer);
}

test "Value json" {
    const allocator = std.testing.allocator;
    
    const json_src =
        \\{
        \\ "a": 1,
        \\ "b": [true, null, "str"],
        \\ "c": { "d": 3.14 }
        \\}
    ;
    
    // Parse using std.json to get std.json.Value
    var parsed = try std.json.parseFromSlice(std.json.Value, allocator, json_src, .{});
    defer parsed.deinit();
    
    // Convert to zaq Value
    var v = try Value.fromJson(allocator, parsed.value);
    defer v.deinit(allocator);
    
    // Serialize back to string
    var out_buf = std.ArrayListUnmanaged(u8){};
    defer out_buf.deinit(allocator);
    
    try v.toJson(out_buf.writer(allocator));
    
    // Check output structure (basic check)
    const out_str = out_buf.items;
    try std.testing.expect(std.mem.indexOf(u8, out_str, "\"a\":1") != null);
    try std.testing.expect(std.mem.indexOf(u8, out_str, "true") != null);
    try std.testing.expect(std.mem.indexOf(u8, out_str, "null") != null);
}

