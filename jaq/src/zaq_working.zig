const std = @import("std");

pub fn main() !void {
    const stdout = std.io.getStdOut();
    const writer = stdout.writer();
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

    try std.json.stringify(result, .{ .whitespace = .indent_2 }, writer);
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
                const index = try std.fmt.parseInt(usize, token[1..token.len-1], 10);
                if (index < current.array.items.len) {
                    current = current.array.items[index];
                }
            }
        } else {
            current = try getField(current, token);
        }
    }

    return current;
}

fn getField(value: std.json.Value, field: []const u8) !std.json.Value {
    const field_str = std.mem.trim(u8, field);

    if (field_str.len == 0) return value;

    return switch (value) {
        .object => |obj| {
            if (obj.get(field_str)) |v| {
                return v.*;
            }
            return std.json.Value{ .null = {} };
        },
        .array => {
            if (std.mem.eql(u8, field_str, "length")) {
                return std.json.Value{ .integer = @intCast(value.array.items.len) };
            }
            return std.json.Value{ .null = {} };
        },
        else => return std.json.Value{ .null = {} },
    };
}
