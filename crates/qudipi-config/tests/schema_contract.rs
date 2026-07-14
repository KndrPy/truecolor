use qudipi_config::{Config, ConfigError, load, validate};
use qudipi_domain::SchemaId;
use std::path::PathBuf;

fn canonical_config() -> Config {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../qudipi.toml");

    load(path).expect("canonical configuration must load")
}

fn validation_message(error: ConfigError) -> String {
    error.to_string()
}

#[test]
fn canonical_schema_registry_is_valid() {
    let config = canonical_config();

    validate(&config).expect("canonical schema registry must validate");
}

#[test]
fn empty_schema_registry_is_rejected() {
    let mut config = canonical_config();
    config.schemas.clear();

    let message =
        validation_message(validate(&config).expect_err("empty schema registry must be rejected"));

    assert!(
        message.contains("schema registry must not be empty"),
        "unexpected validation message: {message}"
    );
}

#[test]
fn blank_schema_description_is_rejected() {
    let mut config = canonical_config();

    let schema = config
        .schemas
        .values_mut()
        .next()
        .expect("canonical schema registry must not be empty");

    schema.description = " ".to_string();

    let message = validation_message(
        validate(&config).expect_err("blank schema descriptions must be rejected"),
    );

    assert!(
        message.contains("non-empty description"),
        "unexpected validation message: {message}"
    );
}

#[test]
fn zero_schema_version_is_rejected() {
    let mut config = canonical_config();

    let schema = config
        .schemas
        .values_mut()
        .next()
        .expect("canonical schema registry must not be empty");

    schema.version = 0;

    let message =
        validation_message(validate(&config).expect_err("zero schema version must be rejected"));

    assert!(
        message.contains("version must be greater than zero"),
        "unexpected validation message: {message}"
    );
}

#[test]
fn unknown_operator_input_schema_is_rejected() {
    let mut config = canonical_config();

    let operator = config
        .operators
        .values_mut()
        .next()
        .expect("canonical operator registry must not be empty");

    operator.input_schema = SchemaId::new("unknown_input_schema_v1").unwrap();

    let message =
        validation_message(validate(&config).expect_err("unknown input schema must be rejected"));

    assert!(
        message.contains("unknown input schema"),
        "unexpected validation message: {message}"
    );
}

#[test]
fn unknown_operator_output_schema_is_rejected() {
    let mut config = canonical_config();

    let operator = config
        .operators
        .values_mut()
        .next()
        .expect("canonical operator registry must not be empty");

    operator.output_schema = SchemaId::new("unknown_output_schema_v1").unwrap();

    let message =
        validation_message(validate(&config).expect_err("unknown output schema must be rejected"));

    assert!(
        message.contains("unknown output schema"),
        "unexpected validation message: {message}"
    );
}

#[test]
fn blank_operator_entrypoint_is_rejected() {
    let mut config = canonical_config();

    let operator = config
        .operators
        .values_mut()
        .next()
        .expect("canonical operator registry must not be empty");

    operator.entrypoint = " ".to_string();

    let message = validation_message(
        validate(&config).expect_err("blank operator entrypoint must be rejected"),
    );

    assert!(
        message.contains("non-empty entrypoint"),
        "unexpected validation message: {message}"
    );
}
