const std = @import("std");

pub const TokenType = enum {
    eof,
    error_token,

    // Single character tokens
    dot,        // .
    comma,      // ,
    colon,      // :
    semicolon,  // ;
    pipe,       // |
    l_bracket,  // [
    r_bracket,  // ]
    l_brace,    // {
    r_brace,    // }
    l_paren,    // (
    r_paren,    // )
    
    // Operators
    plus,       // +
    minus,      // -
    star,       // *
    slash,      // /
    percent,    // %
    
    assign,     // =
    update,     // |=
    
    eq,         // ==
    ne,         // !=
    lt,         // <
    gt,         // >
    le,         // <=
    ge,         // >=
    
    recurse,    // ..
    question,   // ?
    alternative, // //
    
    // Literals
    identifier,
    variable,   // $name
    string,
    number,
    
    // Keywords
    keyword_null,
    keyword_true,
    keyword_false,
    keyword_if,
    keyword_then,
    keyword_else,
    keyword_elif,
    keyword_end,
    keyword_and,
    keyword_or,
    keyword_not,
    keyword_def,
    keyword_as,
    keyword_reduce,
    keyword_foreach,
    keyword_label,
    keyword_break,
};

pub const Token = struct {
    type: TokenType,
    start: usize,
    length: usize,
    line: usize,
    col: usize,
    
    pub fn lexeme(self: Token, source: []const u8) []const u8 {
        return source[self.start .. self.start + self.length];
    }
};

pub const Lexer = struct {
    source: []const u8,
    start: usize = 0,
    current: usize = 0,
    line: usize = 1,
    line_start: usize = 0,

    pub fn init(source: []const u8) Lexer {
        return Lexer{
            .source = source,
        };
    }

    pub fn next(self: *Lexer) Token {
        self.skipWhitespace();
        
        self.start = self.current;
        
        if (self.isAtEnd()) return self.makeToken(.eof);
        
        const c = self.advance();
        
        if (isAlpha(c)) return self.identifier();
        if (isDigit(c)) return self.number();
        
        return switch (c) {
            '(' => self.makeToken(.l_paren),
            ')' => self.makeToken(.r_paren),
            '{' => self.makeToken(.l_brace),
            '}' => self.makeToken(.r_brace),
            '[' => self.makeToken(.l_bracket),
            ']' => self.makeToken(.r_bracket),
            ';' => self.makeToken(.semicolon),
            ',' => self.makeToken(.comma),
            ':' => self.makeToken(.colon),
            '?' => self.makeToken(.question),
            '|' => if (self.match('=')) self.makeToken(.update) else self.makeToken(.pipe),
            '.' => if (self.match('.')) self.makeToken(.recurse) else self.makeToken(.dot),
            '=' => if (self.match('=')) self.makeToken(.eq) else self.makeToken(.assign),
            '!' => if (self.match('=')) self.makeToken(.ne) else self.errorToken("Unexpected character '!'. Expecting '!='."),
            '<' => if (self.match('=')) self.makeToken(.le) else self.makeToken(.lt),
            '>' => if (self.match('=')) self.makeToken(.ge) else self.makeToken(.gt),
            '+' => self.makeToken(.plus),
            '-' => self.makeToken(.minus),
            '*' => self.makeToken(.star),
            '/' => if (self.match('/')) self.makeToken(.alternative) else self.makeToken(.slash),
            '%' => self.makeToken(.percent),
            '"' => self.string(),
            '$' => self.variable(),
            
            // Comments
            '#' => {
                while (self.peek() != '\n' and !self.isAtEnd()) {
                    _ = self.advance();
                }
                return self.next();
            },
            
            else => self.errorToken("Unexpected character."),
        };
    }
    
    fn identifier(self: *Lexer) Token {
        while (isAlphaNumeric(self.peek())) {
            _ = self.advance();
        }
        
        const text = self.source[self.start..self.current];
        const token_type = checkKeyword(text);
        
        return self.makeToken(token_type);
    }
    
    fn variable(self: *Lexer) Token {
        // Skip the '$'
        while (isAlphaNumeric(self.peek())) {
            _ = self.advance();
        }
        return self.makeToken(.variable);
    }
    
    fn number(self: *Lexer) Token {
        while (isDigit(self.peek())) {
            _ = self.advance();
        }
        
        // Fraction part
        if (self.peek() == '.' and isDigit(self.peekNext())) {
            // Consume the "."
            _ = self.advance();
            
            while (isDigit(self.peek())) {
                _ = self.advance();
            }
        }
        
        // Exponent part
        if (self.peek() == 'e' or self.peek() == 'E') {
             _ = self.advance();
             if (self.peek() == '+' or self.peek() == '-') {
                 _ = self.advance();
             }
             if (!isDigit(self.peek())) return self.errorToken("Unterminated number literal.");
             while (isDigit(self.peek())) {
                 _ = self.advance();
             }
        }
        
        return self.makeToken(.number);
    }
    
    fn string(self: *Lexer) Token {
        while (self.peek() != '"' and !self.isAtEnd()) {
            if (self.peek() == '\n') {
                self.line += 1;
                self.line_start = self.current + 1;
            }
            if (self.peek() == '\\' and !self.isAtEnd()) {
                // Skip escaped char
                _ = self.advance();
            }
            _ = self.advance();
        }
        
        if (self.isAtEnd()) return self.errorToken("Unterminated string.");
        
        // Closing quote
        _ = self.advance();
        return self.makeToken(.string);
    }
    
    fn checkKeyword(text: []const u8) TokenType {
        // Simple switch for keywords
        if (std.mem.eql(u8, text, "null")) return .keyword_null;
        if (std.mem.eql(u8, text, "true")) return .keyword_true;
        if (std.mem.eql(u8, text, "false")) return .keyword_false;
        if (std.mem.eql(u8, text, "if")) return .keyword_if;
        if (std.mem.eql(u8, text, "then")) return .keyword_then;
        if (std.mem.eql(u8, text, "else")) return .keyword_else;
        if (std.mem.eql(u8, text, "elif")) return .keyword_elif;
        if (std.mem.eql(u8, text, "end")) return .keyword_end;
        if (std.mem.eql(u8, text, "and")) return .keyword_and;
        if (std.mem.eql(u8, text, "or")) return .keyword_or;
        if (std.mem.eql(u8, text, "not")) return .keyword_not;
        if (std.mem.eql(u8, text, "def")) return .keyword_def;
        if (std.mem.eql(u8, text, "as")) return .keyword_as;
        if (std.mem.eql(u8, text, "reduce")) return .keyword_reduce;
        if (std.mem.eql(u8, text, "foreach")) return .keyword_foreach;
        if (std.mem.eql(u8, text, "label")) return .keyword_label;
        if (std.mem.eql(u8, text, "break")) return .keyword_break;
        
        return .identifier;
    }
    
    fn skipWhitespace(self: *Lexer) void {
        while (true) {
            const c = self.peek();
            switch (c) {
                ' ', '\r', '\t' => {
                    _ = self.advance();
                },
                '\n' => {
                    self.line += 1;
                    _ = self.advance();
                    self.line_start = self.current;
                },
                else => return,
            }
        }
    }
    
    fn isAtEnd(self: *Lexer) bool {
        return self.current >= self.source.len;
    }
    
    fn advance(self: *Lexer) u8 {
        self.current += 1;
        return self.source[self.current - 1];
    }
    
    fn peek(self: *Lexer) u8 {
        if (self.isAtEnd()) return 0;
        return self.source[self.current];
    }
    
    fn peekNext(self: *Lexer) u8 {
        if (self.current + 1 >= self.source.len) return 0;
        return self.source[self.current + 1];
    }
    
    fn match(self: *Lexer, expected: u8) bool {
        if (self.isAtEnd()) return false;
        if (self.source[self.current] != expected) return false;
        self.current += 1;
        return true;
    }
    
    fn makeToken(self: *Lexer, token_type: TokenType) Token {
        return Token{
            .type = token_type,
            .start = self.start,
            .length = self.current - self.start,
            .line = self.line,
            .col = self.start - self.line_start + 1,
        };
    }
    
    fn errorToken(self: *Lexer, message: []const u8) Token {
        _ = message; // For now ignore the message in the token itself, could store it later
        return Token{
            .type = .error_token,
            .start = self.start,
            .length = self.current - self.start,
            .line = self.line,
            .col = self.start - self.line_start + 1,
        };
    }
};

fn isDigit(c: u8) bool {
    return c >= '0' and c <= '9';
}

fn isAlpha(c: u8) bool {
    return (c >= 'a' and c <= 'z') or
           (c >= 'A' and c <= 'Z') or
           c == '_';
}

fn isAlphaNumeric(c: u8) bool {
    return isAlpha(c) or isDigit(c);
}

test "Lexer basics" {
    const source = ". | map(.id)";
    var lexer = Lexer.init(source);
    
    const t1 = lexer.next();
    try std.testing.expectEqual(TokenType.dot, t1.type);
    
    const t2 = lexer.next();
    try std.testing.expectEqual(TokenType.pipe, t2.type);
    
    const t3 = lexer.next();
    try std.testing.expectEqual(TokenType.identifier, t3.type);
    try std.testing.expectEqualStrings("map", t3.lexeme(source));
    
    const t4 = lexer.next();
    try std.testing.expectEqual(TokenType.l_paren, t4.type);
    
    const t5 = lexer.next();
    try std.testing.expectEqual(TokenType.dot, t5.type);
    
    const t6 = lexer.next();
    try std.testing.expectEqual(TokenType.identifier, t6.type);
    try std.testing.expectEqualStrings("id", t6.lexeme(source));
    
    const t7 = lexer.next();
    try std.testing.expectEqual(TokenType.r_paren, t7.type);
    
    const t8 = lexer.next();
    try std.testing.expectEqual(TokenType.eof, t8.type);
}

test "Lexer operators" {
    const source = "== != <= >= .. |= $var";
    var lexer = Lexer.init(source);
    
    try std.testing.expectEqual(TokenType.eq, lexer.next().type);
    try std.testing.expectEqual(TokenType.ne, lexer.next().type);
    try std.testing.expectEqual(TokenType.le, lexer.next().type);
    try std.testing.expectEqual(TokenType.ge, lexer.next().type);
    try std.testing.expectEqual(TokenType.recurse, lexer.next().type);
    try std.testing.expectEqual(TokenType.update, lexer.next().type);
    
    const t_var = lexer.next();
    try std.testing.expectEqual(TokenType.variable, t_var.type);
    try std.testing.expectEqualStrings("$var", t_var.lexeme(source));
}
