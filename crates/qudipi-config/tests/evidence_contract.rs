use qudipi_config::{compile, emit_stage0_evidence, load};
use serde_json::Value;
use std::{
    fs,
    path::PathBuf,
    time::{SystemTime, UNIX_EPOCH},
};

fn canonical_compiled() -> qudipi_config::CompiledConfig {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../qudipi.toml");

    compile(load(path).expect("canonical config must load")).expect("canonical config must compile")
}

fn temporary_directory() -> PathBuf {
    let suffix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system clock must follow Unix epoch")
        .as_nanos();

    std::env::temp_dir().join(format!("qudipi-stage0-evidence-{suffix}"))
}

#[test]
fn stage0_evidence_artifacts_are_emitted() {
    let compiled = canonical_compiled();
    let destination = temporary_directory();

    let summary =
        emit_stage0_evidence(&compiled, &destination).expect("Stage 0 evidence must emit");

    assert_eq!(summary.status, "PASS");

    for file_name in [
        "stage_registry.json",
        "asset_registry.json",
        "schema_registry.json",
        "operator_registry.json",
        "runtime_policy.json",
        "governance_policy.json",
        "license_policy.json",
        "validation_report.json",
        "closure_gate_report.json",
        "artifact_hashes.json",
        "config_sha256.txt",
    ] {
        assert!(
            destination.join(file_name).is_file(),
            "missing evidence artifact: {file_name}"
        );
    }

    let closure: Value =
        serde_json::from_slice(&fs::read(destination.join("closure_gate_report.json")).unwrap())
            .unwrap();

    assert_eq!(closure["status"], "OPEN");
    assert_eq!(closure["closure_marker_emitted"], false);

    fs::remove_dir_all(destination).unwrap();
}

#[test]
fn artifact_hash_manifest_has_no_self_hash() {
    let compiled = canonical_compiled();
    let destination = temporary_directory();

    emit_stage0_evidence(&compiled, &destination).expect("Stage 0 evidence must emit");

    let hashes: Value =
        serde_json::from_slice(&fs::read(destination.join("artifact_hashes.json")).unwrap())
            .unwrap();

    assert!(hashes.get("artifact_hashes.json").is_none());

    assert!(hashes.get("validation_report.json").is_some());

    fs::remove_dir_all(destination).unwrap();
}
