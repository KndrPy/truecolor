# QuDiPi Stage 0 / WP-00.1

This additive package implements the first bounded Phase 1 work package:

- Rust workspace foundation
- one authoritative `qudipi.toml`
- all 34 stage registrations
- canonical identifiers and state enums
- semantic validation and DAG validation
- deterministic compiled-config SHA-256
- CLI validation, compile, hash, and registry inspection

It intentionally does not implement asset ingestion, Arrow data processing, Go orchestration, Python analysis, TUI, desktop, web, or visualization.

## Validate

```bash
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo run -p qudipi-cli -- config validate
cargo run -p qudipi-cli -- config compile
cargo run -p qudipi-cli -- config show-hash
```
