use crate::{AssetConfig, ConfigError, OperatorConfig, StageConfig};
use std::collections::{BTreeMap, BTreeSet};

pub(crate) fn validate(
    stages: &[StageConfig],
    assets: &[AssetConfig],
    operators: &BTreeMap<String, OperatorConfig>,
) -> Result<(), ConfigError> {
    validate_stage_count(stages)?;
    validate_stage_id_set(stages)?;
    validate_unique_stage_keys(stages)?;

    let stage_ids: BTreeSet<u8> = stages.iter().map(|stage| stage.id).collect();

    let asset_ids: BTreeSet<&str> = assets.iter().map(|asset| asset.id.as_str()).collect();

    let operator_ids: BTreeSet<&str> = operators.keys().map(String::as_str).collect();

    for stage in stages {
        validate_no_duplicate_references(stage)?;
        validate_stage_dependencies(stage, &stage_ids)?;
        validate_stage_assets(stage, &asset_ids)?;
        validate_stage_operators(stage, &operator_ids)?;
    }

    Ok(())
}

fn validate_stage_count(stages: &[StageConfig]) -> Result<(), ConfigError> {
    if stages.len() != 34 {
        return Err(ConfigError::Validation(format!(
            "expected 34 stages, found {}",
            stages.len()
        )));
    }

    Ok(())
}

fn validate_stage_id_set(stages: &[StageConfig]) -> Result<(), ConfigError> {
    let stage_ids: BTreeSet<u8> = stages.iter().map(|stage| stage.id).collect();

    let expected_stage_ids: BTreeSet<u8> = (0..=33).collect();

    if stage_ids != expected_stage_ids {
        return Err(ConfigError::Validation(
            "stage IDs must be exactly 0..=33".into(),
        ));
    }

    if stage_ids.len() != stages.len() {
        return Err(ConfigError::Validation(
            "duplicate stage IDs detected".into(),
        ));
    }

    Ok(())
}

fn validate_unique_stage_keys(stages: &[StageConfig]) -> Result<(), ConfigError> {
    let stage_keys: BTreeSet<&str> = stages.iter().map(|stage| stage.key.as_str()).collect();

    if stage_keys.len() != stages.len() {
        return Err(ConfigError::Validation(
            "duplicate stage keys detected".into(),
        ));
    }

    Ok(())
}

fn validate_no_duplicate_references(stage: &StageConfig) -> Result<(), ConfigError> {
    let dependencies: BTreeSet<u8> = stage.dependencies.iter().copied().collect();

    if dependencies.len() != stage.dependencies.len() {
        return Err(ConfigError::Validation(format!(
            "stage {} contains duplicate dependencies",
            stage.id
        )));
    }

    let assets: BTreeSet<&str> = stage
        .required_assets
        .iter()
        .map(|asset| asset.as_str())
        .collect();

    if assets.len() != stage.required_assets.len() {
        return Err(ConfigError::Validation(format!(
            "stage {} contains duplicate required assets",
            stage.id
        )));
    }

    let operators: BTreeSet<&str> = stage
        .required_operators
        .iter()
        .map(|operator| operator.as_str())
        .collect();

    if operators.len() != stage.required_operators.len() {
        return Err(ConfigError::Validation(format!(
            "stage {} contains duplicate required operators",
            stage.id
        )));
    }

    Ok(())
}

fn validate_stage_dependencies(
    stage: &StageConfig,
    stage_ids: &BTreeSet<u8>,
) -> Result<(), ConfigError> {
    if stage.dependencies.contains(&stage.id) {
        return Err(ConfigError::Validation(format!(
            "stage {} depends on itself",
            stage.id
        )));
    }

    for dependency in &stage.dependencies {
        if !stage_ids.contains(dependency) {
            return Err(ConfigError::Validation(format!(
                "stage {} references unknown dependency {}",
                stage.id, dependency
            )));
        }
    }

    Ok(())
}

fn validate_stage_assets(
    stage: &StageConfig,
    asset_ids: &BTreeSet<&str>,
) -> Result<(), ConfigError> {
    for asset in &stage.required_assets {
        if !asset_ids.contains(asset.as_str()) {
            return Err(ConfigError::Validation(format!(
                "stage {} references unknown asset {}",
                stage.id, asset
            )));
        }
    }

    Ok(())
}

fn validate_stage_operators(
    stage: &StageConfig,
    operator_ids: &BTreeSet<&str>,
) -> Result<(), ConfigError> {
    for operator in &stage.required_operators {
        if !operator_ids.contains(operator.as_str()) {
            return Err(ConfigError::Validation(format!(
                "stage {} references unknown operator {}",
                stage.id, operator
            )));
        }
    }

    Ok(())
}
