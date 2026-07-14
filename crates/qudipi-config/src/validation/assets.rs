use crate::{
    AssetConfig, ConfigError, CorpusCharacterizationConfig, RoleConfig, RoleDerivationMode,
    StageConfig,
};
use qudipi_domain::RoleId;
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum RoleDisposition {
    Allowed,
    Prohibited,
    Unresolved,
}

#[derive(Clone, Debug)]
pub(crate) struct RoleEvaluation {
    pub disposition: RoleDisposition,
    pub missing_characteristics: Vec<String>,
    pub forbidden_characteristics_present: Vec<String>,
}

pub(crate) fn validate(
    corpus: &CorpusCharacterizationConfig,
    roles: &BTreeMap<String, RoleConfig>,
    assets: &[AssetConfig],
    stages: &[StageConfig],
) -> Result<(), ConfigError> {
    validate_corpus_policy(corpus)?;
    validate_unique_asset_ids(assets)?;
    validate_asset_metadata(corpus, roles, assets)?;
    validate_asset_stage_references(assets, stages)?;
    validate_asset_stage_symmetry(assets, stages)?;
    validate_stage_requirements(roles, assets, stages)?;

    Ok(())
}

pub(crate) fn evaluate_role(
    asset: &AssetConfig,
    role_id: &str,
    role: &RoleConfig,
) -> RoleEvaluation {
    let characteristics: BTreeSet<&str> =
        asset.characteristics.iter().map(String::as_str).collect();

    let declared_allowed = asset
        .declared_allowed_roles
        .iter()
        .any(|declared| declared.as_str() == role_id);

    let declared_prohibited = asset
        .declared_prohibited_roles
        .iter()
        .any(|declared| declared.as_str() == role_id);

    if declared_prohibited {
        return RoleEvaluation {
            disposition: RoleDisposition::Prohibited,
            missing_characteristics: Vec::new(),
            forbidden_characteristics_present: Vec::new(),
        };
    }

    let missing_all: Vec<String> = role
        .requires_all
        .iter()
        .filter(|required| !characteristics.contains(required.as_str()))
        .cloned()
        .collect();

    let any_satisfied = role.requires_any.is_empty()
        || role
            .requires_any
            .iter()
            .any(|required| characteristics.contains(required.as_str()));

    let mut missing_any = Vec::new();

    if !any_satisfied {
        missing_any.extend(role.requires_any.iter().cloned());
    }

    let forbidden_present: Vec<String> = role
        .forbids_any
        .iter()
        .filter(|forbidden| characteristics.contains(forbidden.as_str()))
        .cloned()
        .collect();

    let rule_satisfied = missing_all.is_empty() && any_satisfied && forbidden_present.is_empty();

    let disposition = match role.derivation_mode {
        RoleDerivationMode::DeclaredOnly => {
            if declared_allowed {
                RoleDisposition::Allowed
            } else {
                RoleDisposition::Unresolved
            }
        }
        RoleDerivationMode::RuleBased => {
            if rule_satisfied {
                RoleDisposition::Allowed
            } else if !forbidden_present.is_empty() {
                RoleDisposition::Prohibited
            } else {
                RoleDisposition::Unresolved
            }
        }
        RoleDerivationMode::Hybrid => {
            if declared_allowed || rule_satisfied {
                RoleDisposition::Allowed
            } else if !forbidden_present.is_empty() {
                RoleDisposition::Prohibited
            } else {
                RoleDisposition::Unresolved
            }
        }
    };

    let mut missing_characteristics = missing_all;
    missing_characteristics.extend(missing_any);
    missing_characteristics.sort();
    missing_characteristics.dedup();

    RoleEvaluation {
        disposition,
        missing_characteristics,
        forbidden_characteristics_present: forbidden_present,
    }
}

fn validate_corpus_policy(corpus: &CorpusCharacterizationConfig) -> Result<(), ConfigError> {
    if corpus.required_details.is_empty() {
        return Err(ConfigError::Validation(
            "corpus characterization required_details must not be empty".into(),
        ));
    }

    let details: BTreeSet<&str> = corpus.required_details.iter().map(String::as_str).collect();

    if details.len() != corpus.required_details.len() {
        return Err(ConfigError::Validation(
            "corpus characterization contains duplicate required details".into(),
        ));
    }

    if !corpus.reject_unknown_roles {
        return Err(ConfigError::Validation(
            "corpus characterization must reject unknown roles".into(),
        ));
    }

    if !corpus.preserve_unknown_details {
        return Err(ConfigError::Validation(
            "corpus characterization must preserve unknown details".into(),
        ));
    }

    Ok(())
}

fn validate_unique_asset_ids(assets: &[AssetConfig]) -> Result<(), ConfigError> {
    let asset_ids: BTreeSet<&str> = assets.iter().map(|asset| asset.id.as_str()).collect();

    if asset_ids.len() != assets.len() {
        return Err(ConfigError::Validation(
            "duplicate asset IDs detected".into(),
        ));
    }

    Ok(())
}

fn validate_asset_metadata(
    corpus: &CorpusCharacterizationConfig,
    roles: &BTreeMap<String, RoleConfig>,
    assets: &[AssetConfig],
) -> Result<(), ConfigError> {
    for asset in assets {
        let characteristics: BTreeSet<&str> =
            asset.characteristics.iter().map(String::as_str).collect();

        if characteristics.len() != asset.characteristics.len() {
            return Err(ConfigError::Validation(format!(
                "asset {} contains duplicate characteristics",
                asset.id
            )));
        }

        let unknown: BTreeSet<&str> = asset.unknown_details.iter().map(String::as_str).collect();

        if unknown.len() != asset.unknown_details.len() {
            return Err(ConfigError::Validation(format!(
                "asset {} contains duplicate unknown details",
                asset.id
            )));
        }

        for required_detail in &corpus.required_details {
            let known = asset
                .known_details
                .get(required_detail)
                .is_some_and(|value| !value.trim().is_empty());

            let explicitly_unknown = unknown.contains(required_detail.as_str());

            if known == explicitly_unknown {
                return Err(ConfigError::Validation(format!(
                    "asset {} must classify required detail {} as exactly one of known or unknown",
                    asset.id, required_detail
                )));
            }
        }

        validate_role_references(
            asset,
            roles,
            &asset.declared_allowed_roles,
            "declared allowed",
        )?;

        validate_role_references(
            asset,
            roles,
            &asset.declared_prohibited_roles,
            "declared prohibited",
        )?;

        let allowed: BTreeSet<&str> = asset
            .declared_allowed_roles
            .iter()
            .map(RoleId::as_str)
            .collect();

        let prohibited: BTreeSet<&str> = asset
            .declared_prohibited_roles
            .iter()
            .map(RoleId::as_str)
            .collect();

        let overlap: Vec<&str> = allowed.intersection(&prohibited).copied().collect();

        if !overlap.is_empty() {
            return Err(ConfigError::Validation(format!(
                "asset {} declares roles as both allowed and prohibited: {:?}",
                asset.id, overlap
            )));
        }
    }

    Ok(())
}

fn validate_role_references(
    asset: &AssetConfig,
    roles: &BTreeMap<String, RoleConfig>,
    references: &[RoleId],
    field: &str,
) -> Result<(), ConfigError> {
    let unique: BTreeSet<&str> = references.iter().map(RoleId::as_str).collect();

    if unique.len() != references.len() {
        return Err(ConfigError::Validation(format!(
            "asset {} contains duplicate {} roles",
            asset.id, field
        )));
    }

    for role in references {
        if !roles.contains_key(role.as_str()) {
            return Err(ConfigError::Validation(format!(
                "asset {} references unknown {} role {}",
                asset.id, field, role
            )));
        }
    }

    Ok(())
}

fn validate_asset_stage_references(
    assets: &[AssetConfig],
    stages: &[StageConfig],
) -> Result<(), ConfigError> {
    let stage_ids: BTreeSet<u8> = stages.iter().map(|stage| stage.id).collect();

    for asset in assets {
        let applicable: BTreeSet<u8> = asset.applicable_stages.iter().copied().collect();

        if applicable.len() != asset.applicable_stages.len() {
            return Err(ConfigError::Validation(format!(
                "asset {} contains duplicate applicable stage IDs",
                asset.id
            )));
        }

        for stage_id in &asset.applicable_stages {
            if !stage_ids.contains(stage_id) {
                return Err(ConfigError::Validation(format!(
                    "asset {} references unknown applicable stage {}",
                    asset.id, stage_id
                )));
            }
        }
    }

    Ok(())
}

fn validate_asset_stage_symmetry(
    assets: &[AssetConfig],
    stages: &[StageConfig],
) -> Result<(), ConfigError> {
    let assets_by_id: BTreeMap<&str, &AssetConfig> = assets
        .iter()
        .map(|asset| (asset.id.as_str(), asset))
        .collect();

    let stages_by_id: BTreeMap<u8, &StageConfig> =
        stages.iter().map(|stage| (stage.id, stage)).collect();

    for stage in stages {
        for asset_id in &stage.required_assets {
            let asset = assets_by_id.get(asset_id.as_str()).ok_or_else(|| {
                ConfigError::Validation(format!(
                    "stage {} references unknown asset {}",
                    stage.id, asset_id
                ))
            })?;

            if !asset.applicable_stages.contains(&stage.id) {
                return Err(ConfigError::Validation(format!(
                    "asset-stage mapping is asymmetric: stage {} requires asset {}",
                    stage.id, asset_id
                )));
            }
        }
    }

    for asset in assets {
        for stage_id in &asset.applicable_stages {
            let stage = stages_by_id.get(stage_id).ok_or_else(|| {
                ConfigError::Validation(format!(
                    "asset {} references unknown applicable stage {}",
                    asset.id, stage_id
                ))
            })?;

            if !stage.required_assets.contains(&asset.id) {
                return Err(ConfigError::Validation(format!(
                    "asset-stage mapping is asymmetric: asset {} applies to stage {}",
                    asset.id, stage_id
                )));
            }
        }
    }

    Ok(())
}

fn validate_stage_requirements(
    roles: &BTreeMap<String, RoleConfig>,
    assets: &[AssetConfig],
    stages: &[StageConfig],
) -> Result<(), ConfigError> {
    for stage in stages {
        let requirement_ids: BTreeSet<&str> = stage
            .asset_requirements
            .iter()
            .map(|requirement| requirement.requirement_id.as_str())
            .collect();

        if requirement_ids.len() != stage.asset_requirements.len() {
            return Err(ConfigError::Validation(format!(
                "stage {} contains duplicate asset requirement IDs",
                stage.id
            )));
        }

        for requirement in &stage.asset_requirements {
            if requirement.minimum_assets == 0 {
                return Err(ConfigError::Validation(format!(
                    "stage {} requirement {} minimum_assets must be greater than zero",
                    stage.id, requirement.requirement_id
                )));
            }

            for role_id in &requirement.accepted_roles {
                if !roles.contains_key(role_id.as_str()) {
                    return Err(ConfigError::Validation(format!(
                        "stage {} requirement {} references unknown role {}",
                        stage.id, requirement.requirement_id, role_id
                    )));
                }
            }

            let matching = assets
                .iter()
                .filter(|asset| {
                    let characteristics: BTreeSet<&str> =
                        asset.characteristics.iter().map(String::as_str).collect();

                    let characteristics_match = requirement
                        .required_characteristics
                        .iter()
                        .all(|required| characteristics.contains(required.as_str()));

                    let role_match = requirement.accepted_roles.is_empty()
                        || requirement.accepted_roles.iter().any(|role_id| {
                            roles.get(role_id.as_str()).is_some_and(|role| {
                                evaluate_role(asset, role_id.as_str(), role).disposition
                                    == RoleDisposition::Allowed
                            })
                        });

                    characteristics_match && role_match
                })
                .count();

            if matching < requirement.minimum_assets {
                return Err(ConfigError::Validation(format!(
                    "stage {} requirement {} needs at least {} matching assets but found {}",
                    stage.id, requirement.requirement_id, requirement.minimum_assets, matching
                )));
            }
        }
    }

    Ok(())
}
