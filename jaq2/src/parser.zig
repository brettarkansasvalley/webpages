const std = @import("std");
const Allocator = std.mem.Allocator;
const Lexer = @import("lexer.zig").Lexer;
const TokenType = @import("lexer.zig").TokenType;
const Token = @import("lexer.zig").Token;
const Ast = @import("ast.zig");
const Term = Ast.Term;

pub const ParserError = error{
    UnexpectedToken,
    OutOfMemory,
    InvalidSyntax,
};

pub const Parser = struct {
    lexer: Lexer,
    allocator: Allocator,
    current: Token,
    previous: Token,
    
    pub fn init(allocator: Allocator, source: []const u8) Parser {
        const lexer = Lexer.init(source);
        // Prime the pump
        // We will call advance() once in parse() to populate current
        return Parser{
            .lexer = lexer,
            .allocator = allocator,
            .current = undefined,
            .previous = undefined,
        };
    }
    
    pub fn parse(self: *Parser) !*Term {
        self.advance();
        return self.parseTerm();
    }
    
    fn advance(self: *Parser) void {
        self.previous = self.current;
        while (true) {
            self.current = self.lexer.next();
            if (self.current.type != .error_token) break;
            // TODO: Handle error tokens better
        }
    }
    
    fn check(self: *Parser, type_: TokenType) bool {
        return self.current.type == type_;
    }
    
    fn match(self: *Parser, type_: TokenType) bool {
        if (!self.check(type_)) return false;
        self.advance();
        return true;
    }
    
    fn consume(self: *Parser, type_: TokenType, message: []const u8) !void {
        if (self.check(type_)) {
            self.advance();
            return;
        }
        _ = message;
        return ParserError.UnexpectedToken;
    }
    
    // Term priority (lowest to highest):
    // 1. Pipe |
    // 2. Comma ,
    // 3. Assignment = |=
    // 4. Logic or
    // 5. Logic and
    // 6. Comparison == != < > <= >=
    // 7. Add/Sub + -
    // 8. Mul/Div/Rem * / %
    // 9. Unary -
    // 10. Index/Call .[] .field ()
    
    fn parseTerm(self: *Parser) ParserError!*Term {
        return self.parsePipe();
    }
    
    fn parsePipe(self: *Parser) ParserError!*Term {
        var expr = try self.parseComma();
        
        while (self.match(.pipe)) {
            const rhs = try self.parseComma();
            expr = try self.createBinary(.pipe, expr, rhs);
        }
        
        return expr;
    }
    
    fn parseComma(self: *Parser) ParserError!*Term {
        var expr = try self.parseAssignment();
        
        while (self.match(.comma)) {
            const rhs = try self.parseAssignment();
            expr = try self.createBinary(.comma, expr, rhs);
        }
        
        return expr;
    }
    
    fn parseAssignment(self: *Parser) ParserError!*Term {
        // Assignment is right-associative? jq manual says: 
        // "assignment ... has lowest precedence" (actually pipe is lower generally)
        // But for parsing recursive descent:
        const expr = try self.parseAlternative();
        
        if (self.match(.assign)) {
            const rhs = try self.parseAssignment(); // Right-associative
            return self.createBinary(.assign, expr, rhs);
        } else if (self.match(.update)) {
            const rhs = try self.parseAssignment();
            return self.createBinary(.update, expr, rhs);
        }
        
        return expr;
    }
    
    fn parseAlternative(self: *Parser) ParserError!*Term {
        var expr = try self.parseLogicOr();
        
        while (self.match(.alternative)) {
            const rhs = try self.parseLogicOr();
            expr = try self.createBinary(.alternative, expr, rhs);
        }
        
        return expr;
    }
    
    fn parseLogicOr(self: *Parser) ParserError!*Term {
        var expr = try self.parseLogicAnd();
        while (self.match(.keyword_or)) {
            const rhs = try self.parseLogicAnd();
            expr = try self.createBinary(.or_op, expr, rhs);
        }
        return expr;
    }

    fn parseLogicAnd(self: *Parser) ParserError!*Term {
        var expr = try self.parseComparison();
        while (self.match(.keyword_and)) {
            const rhs = try self.parseComparison();
            expr = try self.createBinary(.and_op, expr, rhs);
        }
        return expr;
    }
    
    fn parseComparison(self: *Parser) ParserError!*Term {
        var expr = try self.parseAddSub();
        
        while (true) {
            if (self.match(.eq)) {
                const rhs = try self.parseAddSub();
                expr = try self.createBinary(.eq, expr, rhs);
            } else if (self.match(.ne)) {
                const rhs = try self.parseAddSub();
                expr = try self.createBinary(.ne, expr, rhs);
            } else if (self.match(.lt)) {
                const rhs = try self.parseAddSub();
                expr = try self.createBinary(.lt, expr, rhs);
            } else if (self.match(.le)) {
                const rhs = try self.parseAddSub();
                expr = try self.createBinary(.le, expr, rhs);
            } else if (self.match(.gt)) {
                const rhs = try self.parseAddSub();
                expr = try self.createBinary(.gt, expr, rhs);
            } else if (self.match(.ge)) {
                const rhs = try self.parseAddSub();
                expr = try self.createBinary(.ge, expr, rhs);
            } else {
                break;
            }
        }
        
        return expr;
    }
    
    fn parseAddSub(self: *Parser) ParserError!*Term {
        var expr = try self.parseMulDiv();
        
        while (true) {
            if (self.match(.plus)) {
                const rhs = try self.parseMulDiv();
                expr = try self.createBinary(.add, expr, rhs);
            } else if (self.match(.minus)) {
                const rhs = try self.parseMulDiv();
                expr = try self.createBinary(.sub, expr, rhs);
            } else {
                break;
            }
        }
        
        return expr;
    }
    
    fn parseMulDiv(self: *Parser) ParserError!*Term {
        var expr = try self.parseUnary();
        
        while (true) {
            if (self.match(.star)) {
                const rhs = try self.parseUnary();
                expr = try self.createBinary(.mul, expr, rhs);
            } else if (self.match(.slash)) {
                const rhs = try self.parseUnary();
                expr = try self.createBinary(.div, expr, rhs);
            } else if (self.match(.percent)) {
                const rhs = try self.parseUnary();
                expr = try self.createBinary(.rem, expr, rhs);
            } else {
                break;
            }
        }
        
        return expr;
    }
    
    fn parseUnary(self: *Parser) ParserError!*Term {
        if (self.match(.minus)) {
            const term = try self.parseUnary();
            return self.createUnary(.neg, term);
        }
        // TODO: not
        return self.parseCallIndex();
    }
    
    fn parseCallIndex(self: *Parser) ParserError!*Term {
        var expr = try self.parsePrimary();
        
        while (true) {
            if (self.match(.dot)) {
                // Field access .identifier or ."string"
                // When expr is a pipe (from .[]), we need to extend the pipe's RHS
                // So .[].value becomes . | (.[] | .value) not Index(. | .[], "value")
                
                if (self.match(.identifier)) {
                    const field_name = self.previous.lexeme(self.lexer.source);
                    const index_term = try self.createString(field_name);
                    const field_access = try self.createIndex(try self.createTerm(.identity), index_term, false);
                    // Pipe expr into field access
                    expr = try self.createBinary(.pipe, expr, field_access);
                } else if (self.match(.string)) {
                     const s = self.previous.lexeme(self.lexer.source);
                     const content = s[1..s.len-1];
                     const index_term = try self.createString(content);
                     const field_access = try self.createIndex(try self.createTerm(.identity), index_term, false);
                     expr = try self.createBinary(.pipe, expr, field_access);
                }
            } else if (self.match(.l_bracket)) {
                // Indexing [expr] or [] (iterate)
                if (self.match(.r_bracket)) {
                    // .[] - iterate
                    var iter_term = try self.createTerm(.iterate);
                    
                    // Check for optional: expr[]?
                    if (self.match(.question)) {
                        iter_term = try self.createTry(iter_term, null);
                    }
                    
                    // Create pipe: expr | .[] (or .[]?)
                    expr = try self.createBinary(.pipe, expr, iter_term);
                } else {
                    // [expr] or [start:end] slice
                    // Check for [:end] slice (no start)
                    if (self.match(.colon)) {
                        // [:end] - slice from beginning
                        var end_expr: ?*Term = null;
                        if (!self.check(.r_bracket)) {
                            end_expr = try self.parseTerm();
                        }
                        try self.consume(.r_bracket, "Expect ']' after slice.");
                        expr = try self.createSlice(expr, null, end_expr);
                    } else {
                        const start_expr = try self.parseTerm();
                        if (self.match(.colon)) {
                            // [start:end] or [start:]
                            var end_expr: ?*Term = null;
                            if (!self.check(.r_bracket)) {
                                end_expr = try self.parseTerm();
                            }
                            try self.consume(.r_bracket, "Expect ']' after slice.");
                            expr = try self.createSlice(expr, start_expr, end_expr);
                        } else {
                            // [expr] - simple index
                            try self.consume(.r_bracket, "Expect ']' after index.");
                            const optional = self.match(.question);
                            expr = try self.createIndex(expr, start_expr, optional);
                        }
                    }
                }
            } else if (self.match(.question)) {
                // Optional? suffix on expression itself? `expr?`
                // This usually acts as "try" or error suppression.
                // Represent as TryTerm(expr, empty)
                expr = try self.createTry(expr, null);
            } else {
                break;
            }
        }
        
        return expr;
    }
    
    fn parseObject(self: *Parser) ParserError!*Term {
        var fields = std.ArrayListUnmanaged(Ast.ObjectField){};
        errdefer fields.deinit(self.allocator);
        
        if (!self.check(.r_brace)) {
            while (true) {
                var key_term: *Term = undefined;
                var val_term: *Term = undefined;
                
                if (self.match(.identifier)) {
                    // { id ... }
                    const name = self.previous.lexeme(self.lexer.source);
                    key_term = try self.createString(name);
                    
                    if (self.match(.colon)) {
                        // { id: val }
                        val_term = try self.parseAssignment();
                    } else {
                        // { id } -> { "id": .id }
                        const id_term = try self.createTerm(.identity);
                        const index_key = try self.createString(name);
                        val_term = try self.createIndex(id_term, index_key, false);
                    }
                } else if (self.match(.string)) {
                    // { "key": val }
                    const s = self.previous.lexeme(self.lexer.source);
                    const content = s[1..s.len-1];
                    key_term = try self.createString(content);
                    try self.consume(.colon, "Expect ':' after object key.");
                    val_term = try self.parseAssignment();
                } else if (self.match(.l_paren)) {
                     // { (expr): val }
                     key_term = try self.parseTerm();
                     try self.consume(.r_paren, "Expect ')' after object key expression.");
                     try self.consume(.colon, "Expect ':' after object key.");
                     val_term = try self.parseAssignment();
                } else if (self.match(.variable)) {
                     // { $var } -> { "var": $var }
                     const name = self.previous.lexeme(self.lexer.source); // $var
                     // Strip $ for key name? jq does: {$a} -> {"a": $a}
                     const var_name = name[1..]; 
                     key_term = try self.createString(var_name);
                     val_term = try self.createVariable(name);
                } else {
                    return ParserError.UnexpectedToken;
                }
                
                try fields.append(self.allocator, Ast.ObjectField{ .key = key_term, .val = val_term });
                
                if (!self.match(.comma)) break;
            }
        }
        
        try self.consume(.r_brace, "Expect '}' after object fields.");
        return self.createTerm(Term{ .object = fields });
    }
    
    fn parsePrimary(self: *Parser) ParserError!*Term {
        if (self.match(.keyword_null)) return self.createNull();
        if (self.match(.keyword_true)) return self.createBool(true);
        if (self.match(.keyword_false)) return self.createBool(false);
        if (self.match(.number)) {
            // Parse number
            const s = self.previous.lexeme(self.lexer.source);
            if (std.mem.indexOf(u8, s, ".") != null or std.mem.indexOf(u8, s, "e") != null) {
                const f = std.fmt.parseFloat(f64, s) catch return ParserError.InvalidSyntax;
                return self.createFloat(f);
            } else {
                const i = std.fmt.parseInt(i64, s, 10) catch return ParserError.InvalidSyntax;
                return self.createInt(i);
            }
        }
        if (self.match(.string)) {
            const s = self.previous.lexeme(self.lexer.source);
            // Remove quotes
            // TODO: Unescape
            return self.createString(s[1..s.len-1]);
        }
        if (self.match(.dot)) {
            if (self.match(.identifier)) {
                const field_name = self.previous.lexeme(self.lexer.source);
                const index_term = try self.createString(field_name);
                const id_term = try self.createTerm(.identity);
                return self.createIndex(id_term, index_term, false);
            }
            if (self.match(.string)) {
                const s = self.previous.lexeme(self.lexer.source);
                const content = s[1..s.len-1];
                const index_term = try self.createString(content);
                const id_term = try self.createTerm(.identity);
                return self.createIndex(id_term, index_term, false);
            }
            return self.createTerm(.identity);
        }
        if (self.match(.recurse)) return self.createTerm(.recurse);
        
        if (self.match(.l_paren)) {
            const expr = try self.parseTerm();
            try self.consume(.r_paren, "Expect ')' after expression.");
            return expr;
        }
        
        if (self.match(.l_bracket)) {
            // Array construction `[` ... `]`
            if (self.match(.r_bracket)) {
                 // Empty array []
                 // Ast expects `array: ?*Term`.
                 return self.createArray(null);
            }
            const expr = try self.parseTerm();
            try self.consume(.r_bracket, "Expect ']' after array elements.");
            return self.createArray(expr);
        }
        
        if (self.match(.l_brace)) {
            return self.parseObject();
        }
        
        if (self.match(.variable)) {
            const name = self.previous.lexeme(self.lexer.source);
            return self.createVariable(name);
        }

        if (self.match(.identifier)) {
             // Function call
             const name = self.previous.lexeme(self.lexer.source);
             var args = std.ArrayListUnmanaged(Term){};
             
             // Check if it has arguments
             if (self.match(.l_paren)) {
                 if (!self.check(.r_paren)) {
                     while (true) {
                         const arg = try self.parseTerm();
                         try args.append(self.allocator, arg.*);
                         if (!self.match(.semicolon)) break;
                     }
                 }
                 try self.consume(.r_paren, "Expect ')' after function arguments.");
             }
             return self.createCallWithArgs(name, args);
        }
        
        // if-then-else-end
        if (self.match(.keyword_if)) {
            const cond = try self.parseTerm();
            try self.consume(.keyword_then, "Expect 'then' after if condition.");
            const then_branch = try self.parseTerm();
            
            // Handle elif chains by converting to nested if-then-else
            var else_branch: *Term = undefined;
            if (self.match(.keyword_elif)) {
                // elif is syntactic sugar for else if
                // Recursively parse as if statement
                const elif_cond = try self.parseTerm();
                try self.consume(.keyword_then, "Expect 'then' after elif condition.");
                const elif_then = try self.parseTerm();
                var elif_else: *Term = undefined;
                if (self.match(.keyword_else)) {
                    elif_else = try self.parseTerm();
                } else if (self.check(.keyword_elif)) {
                    // More elif - recurse by creating another if expression
                    // For simplicity, require else or end after elif for now
                    elif_else = try self.createNull();
                } else {
                    elif_else = try self.createNull();
                }
                try self.consume(.keyword_end, "Expect 'end' after if expression.");
                else_branch = try self.createIf(elif_cond, elif_then, elif_else);
            } else if (self.match(.keyword_else)) {
                else_branch = try self.parseTerm();
                try self.consume(.keyword_end, "Expect 'end' after if expression.");
            } else {
                try self.consume(.keyword_end, "Expect 'end' after if expression.");
                else_branch = try self.createNull();
            }
            
            return self.createIf(cond, then_branch, else_branch);
        }
        
        return ParserError.UnexpectedToken;
    }
    
    // Helpers to create AST nodes
    
    fn createTerm(self: *Parser, val: Term) ParserError!*Term {
        const ptr = self.allocator.create(Term) catch return ParserError.OutOfMemory;
        ptr.* = val;
        return ptr;
    }
    
    fn createBinary(self: *Parser, op: Ast.BinaryOp, lhs: *Term, rhs: *Term) ParserError!*Term {
        return self.createTerm(Term{ .binary = .{ .op = op, .lhs = lhs, .rhs = rhs } });
    }
    
    fn createUnary(self: *Parser, op: Ast.UnaryOp, term: *Term) ParserError!*Term {
        return self.createTerm(Term{ .unary = .{ .op = op, .term = term } });
    }
    
    fn createIndex(self: *Parser, target: *Term, index: *Term, optional: bool) ParserError!*Term {
        return self.createTerm(Term{ .index = .{ .target = target, .index = index, .optional = optional } });
    }
    
    fn createTry(self: *Parser, term: *Term, catch_term: ?*Term) ParserError!*Term {
        return self.createTerm(Term{ .try_term = .{ .term = term, .catch_term = catch_term } });
    }
    
    fn createNull(self: *Parser) ParserError!*Term {
        return self.createTerm(.null_literal);
    }
    
    fn createBool(self: *Parser, b: bool) ParserError!*Term {
        return self.createTerm(Term{ .bool_literal = b });
    }
    
    fn createInt(self: *Parser, i: i64) ParserError!*Term {
        return self.createTerm(Term{ .int_literal = i });
    }
    
    fn createFloat(self: *Parser, f: f64) ParserError!*Term {
        return self.createTerm(Term{ .float_literal = f });
    }
    
    fn createString(self: *Parser, s: []const u8) ParserError!*Term {
        const copy = self.allocator.dupe(u8, s) catch return ParserError.OutOfMemory;
        return self.createTerm(Term{ .str_literal = copy });
    }
    
    fn createArray(self: *Parser, term: ?*Term) ParserError!*Term {
        return self.createTerm(Term{ .array = term });
    }
    
    fn createObject(self: *Parser) ParserError!*Term {
        return self.createTerm(Term{ .object = .{} });
    }
    
    fn createVariable(self: *Parser, name: []const u8) ParserError!*Term {
        const copy = self.allocator.dupe(u8, name) catch return ParserError.OutOfMemory;
        return self.createTerm(Term{ .variable = copy });
    }
    
    fn createCall(self: *Parser, name: []const u8) ParserError!*Term {
        const copy = self.allocator.dupe(u8, name) catch return ParserError.OutOfMemory;
        return self.createTerm(Term{ .call = .{ .name = copy, .args = .{} } });
    }
    
    fn createCallWithArgs(self: *Parser, name: []const u8, args: std.ArrayListUnmanaged(Term)) ParserError!*Term {
        const copy = self.allocator.dupe(u8, name) catch return ParserError.OutOfMemory;
        return self.createTerm(Term{ .call = .{ .name = copy, .args = args } });
    }
    
    fn createSlice(self: *Parser, target: *Term, start: ?*Term, end: ?*Term) ParserError!*Term {
        return self.createTerm(Term{ .slice = .{ .target = target, .start = start, .end = end } });
    }
    
    fn createIf(self: *Parser, cond: *Term, then_branch: *Term, else_branch: *Term) ParserError!*Term {
        return self.createTerm(Term{ .if_term = .{ .cond = cond, .then_branch = then_branch, .else_branch = else_branch } });
    }
};

test "Parser basic" {
    const allocator = std.testing.allocator;
    const source = ". | .id";
    var parser = Parser.init(allocator, source);
    
    const ast_root = try parser.parse();
    const ast_obj = Ast.Ast{ .root = ast_root, .allocator = allocator };
    defer ast_obj.deinit();
    
    // We expect Binary(Pipe, Identity, Index(Identity, String("id")))
    // But wait, .id parses as Primary(.dot) -> loop -> .match(.identifier) -> Index
    
    // Check root is pipe
    try std.testing.expect(ast_root.* == .binary);
    try std.testing.expect(ast_root.binary.op == .pipe);
    try std.testing.expect(ast_root.binary.lhs.* == .identity);
    // rhs should be index
    try std.testing.expect(ast_root.binary.rhs.* == .index);
}
