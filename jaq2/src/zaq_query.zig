const std = @import("std");

pub fn main() !void {
    const allocator = std.heap.page_allocator;
    const args = try std.process.argsAlloc(allocator);
    defer std.process.argsFree(allocator, args);

    if (args.len < 3) {
        std.debug.print("Usage: zaq <query> <file.json>", .{});
        return;
    }

    const query = args[1];
    const filename = args[2];

    const content = try std.fs.cwd().readFileAlloc(allocator, filename);
    defer allocator.free(content);

    const parsed = try std.json.parseFromSliceLeaky(std.json.Value, allocator, content, .{});
    defer allocator.free(parsed);

    const result = try executeQuery(allocator, parsed, query);
    try std.json.stringify(result, .{ .whitespace = .indent_2 }, std.io.getStdErr().writer());
    try std.io.getStdErr().writer().writeAll("\n");
}

fn executeQuery(allocator: Allocator, data: std.json.Value, query: []const u8) !std.json.Value {
    const parts = try std.mem.tokenizeScalar(u8, query, ".");
    var current = data;

    for (parts) |part| {
        if (part.len == 0) continue;
        const token = std.mem.trim(u8, part);

        if (std.mem.eql(u8, token, "[]")) {
            return current;
        } else {
            current = try applyPath(current, token);
        }
    }

    return current;
}

fn applyPath(data: std.json.Value, path: []const u8) !std.json.Value {
    if (path[0] == '[' and path[path.len - 1] == ']') {
        return data;
    }

    var result = data;
    var i: usize = 0;

    while (i < path.len) {
        const token = std.mem.trim(u8, path[i..i+1]);
        i += 1;

        if (token.len == 0) continue;
        if (token[0] == '[') {
            // Array access: .[index]
            i += 1;
            const closing = std.mem.indexOfScalar(u8, path[i..]);
            if (closing == null) return std.json.Value{ .null = {} };
            const index_str = path[i..closing.?];
            const index = try std.fmt.parseInt(usize, index_str, 10);
            return try arrayAccess(data, index);
        } else {
            // Field access: .field
            return try getField(data, token);
        }
    }

    return result;
}

fn arrayAccess(data: std.json.Value, index: usize) !std.json.Value {
    return switch (data) {
        .array => |arr| {
            if (index >= arr.items.len) return std.json.Value{ .null = {} };
            return arr.items[index];
        },
        else => std.json.Value{ .null = {} },
    };
}

fn getField(data: std.json.Value, field: []const u8) !std.json.Value {
    const field_str = std.mem.trim(u8, field);

    return switch (data) {
        .object => |obj| {
            if (obj.get(field_str)) |v| {
                return v.*;
            }
            return std.json.Value{ .null = {} };
        },
        .array => {
            if (std.mem.eql(u8, field_str, "length")) {
                return std.json.Value{ .integer = @intCast(data.array.items.len) };
            }
            return std.json.Value{ .null = {} };
        },
        .string => {
            if (std.mem.eql(u8, field_str, "length")) {
                return std.json.Value{ .integer = @intCast(data.string.len) };
            }
            return std.json.Value{ .null = {} };
        },
        else => std.json.Value{ .null = {} },
    };
}
