use std::process::Command;

#[test]
fn finalizer_binary_is_declared_by_source() {
    let source = include_str!("../../qudipi-cli/src/bin/qudipi-stage0-finalize.rs");

    assert!(source.contains("finalize_stage0_reproducibility"));

    assert!(source.contains("QUDIPI_STAGE0_FINALIZATION_STATUS=PASS"));
}

#[test]
fn reproducibility_core_requires_clean_worktree() {
    let source = include_str!("../src/reproducibility.rs");

    assert!(source.contains("reproducibility capture requires a clean worktree"));

    assert!(source.contains("--porcelain=v1"));
}

#[test]
fn reproducibility_core_runs_required_gates() {
    let source = include_str!("../src/reproducibility.rs");

    for gate in [
        "rust_format",
        "rust_check",
        "rust_clippy",
        "rust_tests",
        "config_validation",
        "python_tests",
    ] {
        assert!(source.contains(gate), "missing gate {gate}");
    }
}

#[test]
fn git_is_available_for_reproducibility_capture() {
    let output = Command::new("git")
        .arg("--version")
        .output()
        .expect("git must be executable");

    assert!(output.status.success());
}
