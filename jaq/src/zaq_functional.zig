const std = @import("std");

pub fn main() !void {
    const stdout = std.io.getStdIn().writer();
    const allocator = std.heap.page_allocator;
    const args = try std.process.argsAlloc(allocator);
    defer std.process.argsFree(allocator, args);

    if (args.len < 3) {
        stdout.writeAll("zaq - JSON Query Tool\n") catch unreachable;
        stdout.writeAll("Usage: zaq <query> <file.json>\n") catch unreachable;
        stdout.writeAll("\nQueries:\n") catch unreachable;
        stdout.writeAll("  .                    - Print entire JSON\n") catch unreachable;
        stdout.writeAll("  .field              - Get field value\n") catch unreachable;
        stdout.writeAll("  .[]                  - Array iteration\n") catch unreachable;
        stdout.writeAll("  .[] | [] | length   - Array length\n") catch unreachable;
        stdout.writeAll("  .[] | [] | reverse   - Reverse array\n") catch unreachable;
        stdout.writeAll("\nExamples:\n") catch unreachable;
        stdout.writeAll("  zaq . file.json\n") catch unreachable;
        stdout.writeAll("  zaq '.field' file.json\n") catch unreachable;
        stdout.writeAll("  zaq '.[]' file.json\n") catch unreachable;
        stdout.writeAll("  zaq '.[] | [] | length' file.json\n") catch unreachable;
        return;
    }

    const query = args[1];
    const filename = args[2];

    const content = try std.fs.cwd().readFileAlloc(allocator, filename);
    defer allocator.free(content);

    const parsed = try std.json.parseFromSliceLeaky(std.json.Value, allocator, content, .{});
    defer allocator.free(parsed);

    const result = try executeQuery(allocator, parsed, query);

    try std.json.stringify(result, .{ .whitespace = .indent_2 }, stdout);
    try stdout.writeAll("\n");
}

fn executeQuery(allocator: std.mem.Allocator, data: std.json.Value, query: []const u8) !std.json.Value {
    const parts = try std.mem.tokenizeScalar(u8, query, ".");
    var current = data;

    for (parts) |part| {
        if (part.len == 0) continue;
        const token = std.mem.trim(u8, part);

        if (std.mem.eql(u8, token, "[]")) {
            if (current != .array) return std.json.Value{ .null = {} };
            current = std.json.Value{ .array = current.array };
        } else {
            current = try getField(current, token);
        }
    }

    return current;
}

fn getField(allocator: std.mem.Allocator, value: std.json.Value, field: []const u8) !std.json.Value {
    const field_str = std.mem.trim(u8, field);

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
            if (std.mem.eql(u8, field_str, "reverse")) {
                var result = std.ArrayList(std.json.Value).init(allocator);
                var i = value.array.items.len;
                while (i > 0) {
                    i -= 1;
                    try result.append(value.array.items[i]);
                }
                return std.json.Value{ .array = result };
            }
            return std.json.Value{ .null = {} };
        },
        else => return std.json.Value{ .null = {} },
    };
}
