# AGENTS.md - Project Guide for AI Coding Agents

## Project Overview

This repository contains **jaq**, a high-performance Rust implementation of the JSON query tool `jq`, along with **zaq**, an experimental Zig-based implementation. The project aims to provide a faster, more correct, and simpler alternative to the original jq.

**Key Characteristics:**
- Language: Rust (primary) + Zig (experimental)
- MSRV (Minimum Supported Rust Version): 1.69 (jaq-core), 1.70 (jaq CLI)
- License: MIT
- Repository: https://github.com/01mf02/jaq

## Architecture

### Rust Workspace (jaq)

The project is organized as a Cargo workspace with these crates:

| Crate | Purpose | Version |
|-------|---------|---------|
| `jaq-core` | Core interpreter, compiler, and filter engine | 3.0.0-beta |
| `jaq-std` | Standard library functions (map, select, etc.) | 3.0.0-beta |
| `jaq-json` | JSON value types and parsing | 2.0.0-beta |
| `jaq-fmts` | Additional format support (YAML, CBOR, TOML, XML) | 0.1.0-beta |
| `jaq-all` | Convenience crate that aggregates all above | 0.1.0-beta |
| `jaq` | Command-line application | 3.0.0-beta |
| `jaq-play` | WebAssembly playground (WASM target) | 0.0.0 |
| `json-loader-server` | JSON loading server component | - |

### Zig Implementation (zaq)

An experimental Zig-based implementation located in `src/`:

| File | Purpose |
|------|---------|
| `main.zig` | CLI entry point |
| `lexer.zig` | Query tokenizer |
| `parser.zig` | Recursive descent parser |
| `ast.zig` | Abstract syntax tree definitions |
| `compiler.zig` | AST to bytecode compiler |
| `vm.zig` | Virtual machine for query execution |
| `value.zig` | JSON value representation |
| `fast_json.zig` | Optimized JSON parser |
| `chunk.zig` | Bytecode chunk management |
| `help.zig` | Help text and documentation |

## Build System

### Rust (jaq)

```bash
# Build all crates
cargo build --release

# Run tests
cargo test --verbose

# Build just the CLI binary (outputs to target/release/jaq)
cargo build --release -p jaq

# Install locally
cargo install --locked --path jaq

# Check without default features (for no-std environments)
cd jaq-core && cargo check --no-default-features
```

**Build Features:**
- `jaq`: `mimalloc` (default) - use mimalloc allocator
- `jaq-core`: `std` (default) - enable standard library support
- `jaq-all`: `formats` (default) - enable all format support

### Zig (zaq)

```bash
# Build zaq binary (requires Zig)
zig build

# Run tests
zig build test

# The binary outputs to zig-out/bin/zaq
```

## Testing Strategy

### Rust Tests

Tests are organized per crate:

```
jaq-core/tests/     # Core interpreter tests
jaq-std/tests/      # Standard library tests
jaq-json/tests/     # JSON handling tests
jaq-fmts/tests/     # Format tests
jaq/src/tests.rs    # CLI unit test runner
jaq/tests/golden.rs # Golden/integration tests
```

**Running Tests:**
```bash
# All tests
cargo test

# Specific crate
cargo test -p jaq-core

# Unit test mode for jaq CLI
cargo run -- test test_file.txt
```

**Test File Format** (for `jaq test`):
```
# Comments start with #
filter_expression
input_json
expected_output_line_1
expected_output_line_2

next_filter
...
```

### Zig Tests

```bash
# Run all Zig tests
zig test src/main.zig

# Individual module tests
zig test src/lexer.zig
zig test src/parser.zig
zig test src/vm.zig
```

### Fuzzing

Fuzzing targets exist in `jaq-core/fuzz/`:
```bash
cd jaq-core/fuzz
cargo check  # Verify fuzz targets compile
```

## Code Organization Conventions

### Rust Code Style

- **No unsafe code**: `#![forbid(unsafe_code)]` in jaq-core
- **No-std support**: Core crates support `no_std` environments
- **Documentation**: Required for public APIs (`#![warn(missing_docs)]`)
- **Error handling**: Custom error types with `thiserror` pattern
- **Module structure**:
  - Core types in `lib.rs`
  - Implementation in submodules
  - Re-exports for convenient access

### Zig Code Style

- **Memory management**: Use ArenaAllocator for short-lived allocations
- **Error handling**: Zig error unions with explicit error types
- **Naming**: `snake_case` for functions/variables, `PascalCase` for types
- **File size limit**: 1GB max read in one go (for non-streaming mode)

## CI/CD Workflows

GitHub Actions workflows in `.github/workflows/`:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `test.yml` | Push/PR | Cross-compilation tests (i686, x86_64) |
| `check.yml` | Push/PR | Build, clippy, feature checks |
| `msrv.yml` | Push/PR | Minimum Rust version verification |
| `release.yml` | Tag push | Multi-platform binary releases |
| `playground.yml` | Push/PR | WASM playground deployment |
| `docs.yml` | Push | Documentation generation |

## Development Guidelines

### Adding New Features

1. **Core functionality**: Add to `jaq-core/src/`
2. **Standard functions**: Add to `jaq-std/src/`
3. **New formats**: Extend `jaq-fmts/src/`
4. **CLI features**: Modify `jaq/src/main.rs` and `jaq/src/cli.rs`

### Benchmarking

```bash
# Compare jaq with other implementations
./bench.sh target/release/jaq /usr/bin/jq /usr/bin/gojq

# Output is JSON format for further processing
```

Benchmarks are defined in `examples/benches/` with corresponding `.jq` files.

### Security Considerations

- The core has been audited by Radically Open Security
- Fuzzing targets maintained for critical parsing code
- No unsafe code in core library
- Careful handling of untrusted JSON input

## Key Files Reference

| File | Purpose |
|------|---------|
| `Cargo.toml` | Workspace definition |
| `build.zig` | Zig build configuration |
| `bench.sh` | Performance benchmarking script |
| `test_data.json` | Test data for examples |
| `complex_queries.sh` | Complex query examples |
| `README.md` | User-facing documentation |
| `LICENSE-MIT` | MIT license text |

## External Dependencies

### Key Rust Dependencies

- `typed-arena` - Fast arena allocation
- `dyn-clone` - Clone trait for trait objects
- `once_cell` - Lazy static initialization
- `mimalloc` - Alternative memory allocator
- `rustyline` - Interactive CLI
- `codesnake` - Error reporting with source locations
- `serde_json` - JSON serialization (dev/test only)

### Key Zig Features

- Standard library JSON streaming parser
- General Purpose Allocator (GPA) for debug builds
- Page allocator for production
- Arena allocation pattern for query processing

## Contact & Resources

- **Author**: Michael Färber <michael.faerber@gedenkt.at>
- **Manual**: https://gedenkt.at/jaq/manual/
- **Playground**: https://gedenkt.at/jaq/
- **Crates**: https://crates.io/crates/jaq-core
- **Documentation**: https://docs.rs/jaq-core
