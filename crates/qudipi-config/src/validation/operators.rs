use crate::{ConfigError, OperatorConfig, SchemaConfig};
use qudipi_domain::OperatorId;
use std::collections::BTreeMap;

pub(crate) fn validate(
    operators: &BTreeMap<String, OperatorConfig>,
    schemas: &BTreeMap<String, SchemaConfig>,
) -> Result<(), ConfigError> {
    if operators.is_empty() {
        return Err(ConfigError::Validation(
            "operator registry must not be empty".into(),
        ));
    }

    for (operator_id, operator) in operators {
        OperatorId::new(operator_id.clone()).map_err(|error| {
            ConfigError::Validation(format!("invalid operator ID {operator_id}: {error}"))
        })?;

        if operator.entrypoint.trim().is_empty() {
            return Err(ConfigError::Validation(format!(
                "operator {operator_id} must have a non-empty entrypoint"
            )));
        }

        if operator.resource_profile.trim().is_empty() {
            return Err(ConfigError::Validation(format!(
                "operator {operator_id} must have a non-empty resource profile"
            )));
        }

        if !schemas.contains_key(operator.input_schema.as_str()) {
            return Err(ConfigError::Validation(format!(
                "operator {operator_id} references unknown input schema {}",
                operator.input_schema
            )));
        }

        if !schemas.contains_key(operator.output_schema.as_str()) {
            return Err(ConfigError::Validation(format!(
                "operator {operator_id} references unknown output schema {}",
                operator.output_schema
            )));
        }
    }

    Ok(())
}
