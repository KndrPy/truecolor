use crate::{ConfigError, RoleConfig};
use qudipi_domain::RoleId;
use std::collections::{BTreeMap, BTreeSet};

pub(crate) fn validate(roles: &BTreeMap<String, RoleConfig>) -> Result<(), ConfigError> {
    if roles.is_empty() {
        return Err(ConfigError::Validation(
            "role registry must not be empty".into(),
        ));
    }

    for (role_id, role) in roles {
        RoleId::new(role_id.clone()).map_err(|error| {
            ConfigError::Validation(format!("invalid role ID {role_id}: {error}"))
        })?;

        if role.description.trim().is_empty() {
            return Err(ConfigError::Validation(format!(
                "role {role_id} must have a non-empty description"
            )));
        }

        if role.role_class.trim().is_empty() {
            return Err(ConfigError::Validation(format!(
                "role {role_id} must have a non-empty role_class"
            )));
        }

        if role.risk_class.trim().is_empty() {
            return Err(ConfigError::Validation(format!(
                "role {role_id} must have a non-empty risk_class"
            )));
        }

        validate_unique_rule_terms(role_id, "requires_all", &role.requires_all)?;

        validate_unique_rule_terms(role_id, "requires_any", &role.requires_any)?;

        validate_unique_rule_terms(role_id, "forbids_any", &role.forbids_any)?;

        let required: BTreeSet<&str> = role
            .requires_all
            .iter()
            .chain(role.requires_any.iter())
            .map(String::as_str)
            .collect();

        let forbidden: BTreeSet<&str> = role.forbids_any.iter().map(String::as_str).collect();

        let overlap: Vec<&str> = required.intersection(&forbidden).copied().collect();

        if !overlap.is_empty() {
            return Err(ConfigError::Validation(format!(
                "role {role_id} both requires and forbids characteristics: {:?}",
                overlap
            )));
        }
    }

    Ok(())
}

fn validate_unique_rule_terms(
    role_id: &str,
    field: &str,
    values: &[String],
) -> Result<(), ConfigError> {
    let unique: BTreeSet<&str> = values.iter().map(String::as_str).collect();

    if unique.len() != values.len() {
        return Err(ConfigError::Validation(format!(
            "role {role_id} contains duplicate {field} characteristics"
        )));
    }

    if values.iter().any(|value| value.trim().is_empty()) {
        return Err(ConfigError::Validation(format!(
            "role {role_id} contains a blank {field} characteristic"
        )));
    }

    Ok(())
}
