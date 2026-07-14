use qudipi_config::{Config, ConfigError, load, validate};
use qudipi_domain::OperatorId;
use std::path::PathBuf;

fn canonical_config() -> Config {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../qudipi.toml");

    load(path).expect("canonical configuration must load")
}

fn message(error: ConfigError) -> String {
    error.to_string()
}

#[test]
fn wrong_phase_is_rejected() {
    let mut config = canonical_config();
    config.application.phase = 2;

    assert!(message(validate(&config).unwrap_err()).contains("application.phase must equal 1"));
}

#[test]
fn multiple_config_authorities_are_rejected() {
    let mut config = canonical_config();
    config.application.single_config_authority = false;

    assert!(
        message(validate(&config).unwrap_err()).contains("single_config_authority must be true")
    );
}

#[test]
fn zero_cpu_limit_is_rejected() {
    let mut config = canonical_config();
    config.runtime.max_cpu_percent = 0;

    assert!(message(validate(&config).unwrap_err()).contains("max_cpu_percent"));
}

#[test]
fn excessive_gpu_limit_is_rejected() {
    let mut config = canonical_config();
    config.runtime.max_gpu_percent = 101;

    assert!(message(validate(&config).unwrap_err()).contains("max_gpu_percent"));
}

#[test]
fn zero_memory_limit_is_rejected() {
    let mut config = canonical_config();
    config.runtime.max_memory_gib = 0;

    assert!(message(validate(&config).unwrap_err()).contains("max_memory_gib"));
}

#[test]
fn zero_worker_count_is_rejected() {
    let mut config = canonical_config();
    config.runtime.max_concurrent_workers = 0;

    assert!(message(validate(&config).unwrap_err()).contains("max_concurrent_workers"));
}

#[test]
fn autonomous_agents_are_rejected() {
    let mut config = canonical_config();
    config.governance.autonomous_agents = true;

    assert!(message(validate(&config).unwrap_err()).contains("prohibits autonomous agents"));
}

#[test]
fn autonomous_claim_adjudication_is_rejected() {
    let mut config = canonical_config();
    config.governance.autonomous_claim_adjudication = true;

    assert!(message(validate(&config).unwrap_err()).contains("prohibits autonomous agents"));
}

#[test]
fn nonproprietary_product_license_is_rejected() {
    let mut config = canonical_config();
    config.licenses.product_license = "open_source".to_string();

    assert!(message(validate(&config).unwrap_err()).contains("product_license"));
}

#[test]
fn wrong_product_version_is_rejected() {
    let mut config = canonical_config();
    config.licenses.product_version = "1.0.0".to_string();

    assert!(message(validate(&config).unwrap_err()).contains("product_version"));
}

#[test]
fn unrestricted_source_distribution_is_rejected() {
    let mut config = canonical_config();
    config.licenses.source_distribution = "public".to_string();

    assert!(message(validate(&config).unwrap_err()).contains("source_distribution"));
}

#[test]
fn redistribution_without_agreement_is_rejected() {
    let mut config = canonical_config();
    config.licenses.redistribution_requires_written_agreement = false;

    assert!(message(validate(&config).unwrap_err()).contains("written agreement"));
}

#[test]
fn empty_dependency_license_allowlist_is_rejected() {
    let mut config = canonical_config();
    config.licenses.default_approved.clear();

    assert!(message(validate(&config).unwrap_err()).contains("allowlist must not be empty"));
}

#[test]
fn duplicate_dependency_license_is_rejected() {
    let mut config = canonical_config();

    let existing = config.licenses.default_approved[0].clone();

    config.licenses.default_approved.push(existing);

    assert!(message(validate(&config).unwrap_err()).contains("contains duplicates"));
}

#[test]
fn unknown_license_rejection_cannot_be_disabled() {
    let mut config = canonical_config();
    config.licenses.reject_unknown = false;

    assert!(message(validate(&config).unwrap_err()).contains("reject unknown licenses"));
}

#[test]
fn paid_runtime_rejection_cannot_be_disabled() {
    let mut config = canonical_config();
    config.licenses.reject_paid_runtime = false;

    assert!(message(validate(&config).unwrap_err()).contains("paid runtime"));
}

#[test]
fn mandatory_cloud_rejection_cannot_be_disabled() {
    let mut config = canonical_config();
    config.licenses.reject_mandatory_cloud = false;

    assert!(message(validate(&config).unwrap_err()).contains("mandatory cloud"));
}

#[test]
fn missing_stage_is_rejected() {
    let mut config = canonical_config();
    config.stages.pop();

    assert!(message(validate(&config).unwrap_err()).contains("expected 34 stages"));
}

#[test]
fn invalid_stage_id_set_is_rejected() {
    let mut config = canonical_config();
    config.stages[33].id = 34;

    assert!(message(validate(&config).unwrap_err()).contains("stage IDs must be exactly"));
}

#[test]
fn self_dependency_is_rejected() {
    let mut config = canonical_config();
    let stage_id = config.stages[0].id;
    config.stages[0].dependencies.push(stage_id);

    assert!(message(validate(&config).unwrap_err()).contains("depends on itself"));
}

#[test]
fn unknown_dependency_is_rejected() {
    let mut config = canonical_config();
    config.stages[0].dependencies.push(99);

    assert!(message(validate(&config).unwrap_err()).contains("unknown dependency 99"));
}

#[test]
fn dependency_cycle_is_rejected() {
    let mut config = canonical_config();

    config.stages[0].dependencies.push(33);

    assert!(message(validate(&config).unwrap_err()).contains("contains a cycle"));
}

#[test]
fn unknown_operator_reference_is_rejected() {
    let mut config = canonical_config();

    config.stages[0].required_operators = vec![OperatorId::new("unknown_operator").unwrap()];

    assert!(message(validate(&config).unwrap_err()).contains("unknown operator"));
}
