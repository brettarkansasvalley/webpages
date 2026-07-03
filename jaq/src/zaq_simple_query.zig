const std = @import("std");

const JsonValue = std.json.Value;
const Allocator = std.mem.Allocator;

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

    const parsed = try std.json.parseFromSliceLeaky(JsonValue, allocator, content, .{});
    defer allocator.free(parsed);

    const result = try executeQuery(allocator, parsed, query);

    const string = try std.json.stringifyAlloc(allocator, result, .{ .whitespace = .indent_2 });
    defer allocator.free(string);

    const stdout = std.io.getStdOut();
    try stdout.writeAll(string);
}

fn executeQuery(allocator: Allocator, data: JsonValue, query: []const u8) !JsonValue {
    const parts = try std.mem.tokenizeScalar(u8, query, ".");
    var current = data;

    for (parts) |part| {
        if (part.len == 0) continue;

        const token = std.mem.trim(u8, part);

        if (token.len == 0) continue;

        if (std.mem.eql(u8, token, "[]")) {
            if (current != .array) continue;
            current = JsonValue{ .array = current.array };
        }
        else {
            current = try getField(current, token);
        }
    }

    return current;
}

fn getField(allocator: Allocator, value: JsonValue, field: []const u8) !JsonValue {
    const field_trimmed = std.mem.trim(u8, field);

    if (field_trimmed.len == 0) return value;

    return switch (value) {
        .object => |obj| {
            if (obj.get(field_trimmed)) |v| {
                return v.*;
            }
            return JsonValue{ .null = {} };
        },
        .array => {
            if (std.mem.eql(u8, field_trimmed, "length")) {
                return JsonValue{ .integer = @intCast(value.array.items.len) };
            }
            if (std.mem.eql(u8, field_trimmed, "reverse")) {
                var result = std.ArrayList(JsonValue).init(allocator);
                var i = value.array.items.len;
                while (i > 0) {
                    i -= 1;
                    try result.append(value.array.items[i]);
                }
                return JsonValue{ .array = result };
            }
            return JsonValue{ .null = {} };
        },
        else => return JsonValue{ .null = {} },
    };
}
