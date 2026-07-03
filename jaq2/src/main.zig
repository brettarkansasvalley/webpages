const std = @import("std");
const Allocator = std.mem.Allocator;

const Value = @import("value.zig").Value;
const Parser = @import("parser.zig").Parser;
const Ast = @import("ast.zig").Ast;
const Compiler = @import("compiler.zig").Compiler;
const Chunk = @import("chunk.zig").Chunk;
const VM = @import("vm.zig").VM;
const fast_json = @import("fast_json.zig");
const help = @import("help.zig");

pub fn main() !void {
    // Use page allocator for large allocations (faster than GPA for bulk ops)
    const page_alloc = std.heap.page_allocator;
    
    // Arena allocator for fast bump allocation during processing
    var arena = std.heap.ArenaAllocator.init(page_alloc);
    defer arena.deinit();
    const allocator = arena.allocator();

    const args = try std.process.argsAlloc(allocator);
    defer std.process.argsFree(allocator, args);

    if (args.len < 2) {
        help.printHelp();
        return;
    }

    // Parse options
    var null_input = false;
    var raw_output = false;
    var slurp = false;
    var filter_str: []const u8 = "";
    var file_args_start: usize = 2;
    
    var i: usize = 1;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.startsWith(u8, arg, "-") and arg.len > 1 and arg[1] != '-') {
            // Short flags like -n, -r, -c, -s or combined -nrc
            for (arg[1..]) |c| {
                switch (c) {
                    'n' => null_input = true,
                    'r' => raw_output = true,
                    'c' => {}, // compact is default
                    's' => slurp = true,
                    'h' => { help.printHelp(); return; },
                    't' => { help.printTutorial(); return; },
                    'v' => { help.printVersion(); return; },
                    else => {},
                }
            }
        } else if (std.mem.eql(u8, arg, "--help")) {
            help.printHelp();
            return;
        } else if (std.mem.eql(u8, arg, "--tutorial")) {
            help.printTutorial();
            return;
        } else if (std.mem.eql(u8, arg, "--version")) {
            help.printVersion();
            return;
        } else if (std.mem.eql(u8, arg, "--null-input")) {
            null_input = true;
        } else if (std.mem.eql(u8, arg, "--raw-output")) {
            raw_output = true;
        } else if (std.mem.eql(u8, arg, "--compact-output")) {
            // compact is default
        } else if (std.mem.eql(u8, arg, "--slurp")) {
            slurp = true;
        } else if (filter_str.len == 0) {
            filter_str = arg;
            file_args_start = i + 1;
        } else {
            break; // Rest are file arguments
        }
    }
    
    if (filter_str.len == 0) {
        help.printHelp();
        return;
    }
    
    // compact_output is default
    
    // Parse Filter
    var parser = Parser.init(allocator, filter_str);
    const ast_root = parser.parse() catch |err| {
        std.debug.print("Parse error: {}\n", .{err});
        return;
    };
    
    const ast = Ast{ .root = ast_root, .allocator = allocator };
    defer ast.deinit();

    // Compile
    var chunk = Chunk.init(allocator);
    defer chunk.deinit(allocator);
    
    var compiler = Compiler.init(allocator, &chunk);
    compiler.compile(ast.root) catch |err| {
        std.debug.print("Compilation error: {}\n", .{err});
        return;
    };
    // Emit return at the end to ensure VM stops
    try chunk.writeOp(allocator, .op_return, 0);

    // Prepare VM
    var vm = VM.init(allocator, &chunk);
    defer vm.deinit();

    // Process Inputs
    // Use GenericWriter to wrap File
    const StdoutWriter = std.io.GenericWriter(std.fs.File, std.fs.File.WriteError, std.fs.File.write);
    const stdout_file = std.fs.File.stdout();
    const stdout = StdoutWriter{ .context = stdout_file };
    
    if (null_input) {
        // -n: Use null as input
        try processContent(allocator, &vm, "null", stdout, raw_output);
    } else if (slurp) {
        // -s: Slurp all inputs into array
        try processSlurp(allocator, &vm, args[file_args_start..], stdout, raw_output);
    } else if (file_args_start < args.len) {
        // Read from files
        for (args[file_args_start..]) |filename| {
            try processFile(allocator, &vm, filename, stdout, raw_output);
        }
    } else {
        // Read from stdin
        try processStdin(allocator, &vm, stdout, raw_output);
    }
}

fn processFile(allocator: Allocator, vm: *VM, filename: []const u8, writer: anytype, raw_output: bool) !void {
    const file = try std.fs.cwd().openFile(filename, .{});
    defer file.close();
    
    // Read whole file (up to 1GB)
    const content = try file.readToEndAlloc(allocator, 1024 * 1024 * 1024);
    defer allocator.free(content);
    
    try processContent(allocator, vm, content, writer, raw_output);
}

fn processStdin(allocator: Allocator, vm: *VM, writer: anytype, raw_output: bool) !void {
    const stdin = std.fs.File.stdin();
    // Read whole stdin (up to 1GB)
    const content = try stdin.readToEndAlloc(allocator, 1024 * 1024 * 1024);
    defer allocator.free(content);
    
    try processContent(allocator, vm, content, writer, raw_output);
}

fn processSlurp(allocator: Allocator, vm: *VM, files: []const [:0]const u8, writer: anytype, raw_output: bool) !void {
    const value_mod = @import("value.zig");
    const Rc = value_mod.Rc;
    const Array = value_mod.Array;
    
    var collected = std.ArrayListUnmanaged(Value){};
    defer {
        for (collected.items) |v| v.deinit(allocator);
        collected.deinit(allocator);
    }
    
    if (files.len == 0) {
        // Read from stdin - parse each JSON value
        const stdin = std.fs.File.stdin();
        const content = try stdin.readToEndAlloc(allocator, 1024 * 1024 * 1024);
        defer allocator.free(content);
        
        // Parse potentially multiple JSON values from content
        var pos: usize = 0;
        while (pos < content.len) {
            // Skip whitespace
            while (pos < content.len and (content[pos] == ' ' or content[pos] == '\n' or content[pos] == '\r' or content[pos] == '\t')) {
                pos += 1;
            }
            if (pos >= content.len) break;
            
            // Parse one JSON value
            const val = fast_json.parseJsonAt(allocator, content, &pos) catch break;
            try collected.append(allocator, val);
        }
    } else {
        // Read from files
        for (files) |filename| {
            const file = try std.fs.cwd().openFile(filename, .{});
            defer file.close();
            const content = try file.readToEndAlloc(allocator, 1024 * 1024 * 1024);
            defer allocator.free(content);
            
            const val = fast_json.parseJson(allocator, content) catch continue;
            try collected.append(allocator, val);
        }
    }
    
    // Create array from collected values
    var items = std.ArrayListUnmanaged(Value){};
    for (collected.items) |v| {
        try items.append(allocator, try v.clone());
    }
    const array_ptr = try Rc(Array).create(allocator, Array{ .items = items });
    const input_val = Value{ .array = array_ptr };
    defer input_val.deinit(allocator);
    
    // Run VM with the array
    var results = try vm.run(input_val);
    defer {
        for (results.items) |val| val.deinit(allocator);
        results.deinit(allocator);
    }
    
    for (results.items) |res| {
        if (raw_output and res == .string) {
            writer.writeAll(res.string.get().bytes) catch return;
        } else {
            res.toJson(writer) catch return;
        }
        writer.writeByte('\n') catch return;
    }
}

fn processContent(allocator: Allocator, vm: *VM, content: []const u8, writer: anytype, raw_output: bool) !void {
    if (content.len == 0) return;

    // Use fast JSON parser for better performance
    const input_val = fast_json.parseJson(allocator, content) catch {
        std.debug.print("Invalid JSON input\n", .{});
        return;
    };
    defer input_val.deinit(allocator);
    
    // Run VM
    var results = vm.run(input_val) catch |err| {
        std.debug.print("error: {}\n", .{err});
        return;
    };
    
    defer {
        for (results.items) |val| {
            val.deinit(allocator);
        }
        results.deinit(allocator);
    }
    
    for (results.items) |res| {
        if (raw_output and res == .string) {
            writer.writeAll(res.string.get().bytes) catch return;
        } else {
            res.toJson(writer) catch return;
        }
        writer.writeByte('\n') catch return;
    }
}

test {
    _ = @import("value.zig");
    _ = @import("lexer.zig");
    _ = @import("parser.zig");
    _ = @import("compiler.zig");
    _ = @import("vm.zig");
}
