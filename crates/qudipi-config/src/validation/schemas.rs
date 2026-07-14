use crate::{ConfigError, SchemaConfig};
use qudipi_domain::SchemaId;
use std::collections::BTreeMap;

pub(crate) fn validate(schemas: &BTreeMap<String, SchemaConfig>) -> Result<(), ConfigError> {
    if schemas.is_empty() {
        return Err(ConfigError::Validation(
            "schema registry must not be empty".into(),
        ));
    }

    for (schema_id, schema) in schemas {
        SchemaId::new(schema_id.clone()).map_err(|error| {
            ConfigError::Validation(format!("invalid schema ID {schema_id}: {error}"))
        })?;

        if schema.description.trim().is_empty() {
            return Err(ConfigError::Validation(format!(
                "schema {schema_id} must have a non-empty description"
            )));
        }

        if schema.version == 0 {
            return Err(ConfigError::Validation(format!(
                "schema {schema_id} version must be greater than zero"
            )));
        }
    }

    Ok(())
}
