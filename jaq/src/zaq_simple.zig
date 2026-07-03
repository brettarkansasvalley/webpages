const std = @import("std");

pub fn main() !void {
    const allocator = std.heap.page_allocator;
    const args = try std.process.argsAlloc(allocator);
    defer std.process.argsFree(allocator, args);

    if (args.len < 3) {
        std.debug.print("zaq - JSON Query Tool\nUsage: zaq <query> <file.json>\n\n", .{});
        std.debug.print("Queries:\n", .{});
        std.debug.print("  .          - Print entire JSON\n", .{});
        std.debug.print("  .field      - Get field value\n", .{});
        std.debug.print("  .[]          - Array iteration\n", .{});
        std.debug.print("  [] length   - Array length\n", .{});
        std.debug.print("  [] reverse - Reverse array\n\n", .{});
        std.debug.print("Examples:\n", .{});
        std.debug.print("  zaq . file.json\n", .{});
        std.debug.print("  zaq .arrays.simple file.json\n", .{});
        std.debug.print("  zaq .[] length file.json\n", .{});
        std.debug.print("  zaq .[] reverse file.json\n", .{});
        return;
    }

    const query = args[1];
    const filename = args[2];

    const content = try std.fs.cwd().readFileAlloc(allocator, filename);
    defer allocator.free(content);

    const parsed = try std.json.parseFromSliceLeaky(std.json.Value, allocator, content, .{});
    defer allocator.free(parsed);

    const result = try executeQuery(allocator, parsed, query);

    const string = try std.json.stringifyAlloc(allocator, result, .{ .whitespace = .indent_2 });
    defer allocator.free(string);

    std.debug.print("{s}", .{string});
}

fn executeQuery(allocator: Allocator, data: std.json.Value, query: []const u8) !std.json.Value {
    const parts = try std.mem.tokenizeScalar(u8, query, ".");
    var current = data;

    for (parts) |part| {
        if (part.len == 0) continue;
        const token = part;

        if (token[0] == '[' and token[token.len - 1] == ']') {
            if (current != .array) continue;
            if (token.len > 2) {
                const index = try std.fmt.parseInt(usize, token[1 .. token.len - 1], 10);
                if (index < current.array.items.len) {
                    current = try deepClone(allocator, current.array.items[index]);
                }
            }
        } else {
            current = try getField(current, token);
        }
    }

    return current;
}

fn getField(data: std.json.Value, field: []const u8) !std.json.Value {
    const field_str = std.mem.trim(u8, field);
    return switch (data) {
        .object => |obj| {
            if (obj.get(field_str)) |v| {
                return try deepClone(allocator, v.*);
            }
            return std.json.Value{ .null = {} };
        },
        .array => {
            if (std.mem.eql(u8, field_str, "length")) {
                return std.json.Value{ .integer = @intCast(data.array.items.len) };
            }
            return std.json.Value{ .null = {} };
        },
        else => return std.json.Value{ .null = {} },
    };
}

fn deepClone(allocator: Allocator, value: std.json.Value) !std.json.Value {
    return switch (value) {
        .null => std.json.Value{ .null = {} },
        .bool => |b| std.json.Value{ .bool = b },
        .integer => |i| std.json.Value{ .integer = i },
        .float => |f| std.json.Value{ .float = f },
        .string => |s| {
            const cloned = try allocator.dupe(u8, s);
            return std.json.Value{ .string = cloned };
        },
        .array => |arr| {
            var new_arr = std.ArrayList(std.json.Value).init(allocator);
            for (arr.items) |item| {
                try new_arr.append(try deepClone(allocator, item.*));
            }
            return std.json.Value{ .array = new_arr };
        },
        .object => |obj| {
            var new_obj = std.StringHashMap(std.json.Value).init(allocator);
            var iter = obj.iterator();
            while (iter.next()) |entry| {
                const key_clone = try allocator.dupe(u8, entry.key_ptr.*);
                const value_clone = try deepClone(allocator, entry.value_ptr.*);
                try new_obj.put(key_clone, value_clone);
            }
            return std.json.Value{ .object = new_obj };
        },
    };
}
