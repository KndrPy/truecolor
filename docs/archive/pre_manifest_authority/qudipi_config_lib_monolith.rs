use qudipi_domain::{
    AccessClass, AssetId, OperatorId, ProjectId, ResearchPackId, StageState, StudyId,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet, VecDeque},
    fs,
    path::Path,
};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("failed to read configuration: {0}")]
    Io(#[from] std::io::Error),
    #[error("failed to parse TOML: {0}")]
    Toml(#[from] toml::de::Error),
    #[error("configuration validation failed: {0}")]
    Validation(String),
    #[error("failed to serialize compiled configuration: {0}")]
    Serialization(#[from] serde_json::Error),
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Config {
    pub application: ApplicationConfig,
    pub runtime: RuntimeConfig,
    pub governance: GovernanceConfig,
    pub licenses: LicenseConfig,
    pub stages: Vec<StageConfig>,
    pub assets: Vec<AssetConfig>,
    pub operators: BTreeMap<String, OperatorConfig>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ApplicationConfig {
    pub id: ProjectId,
    pub phase: u8,
    pub study: StudyId,
    pub research_pack: ResearchPackId,
    pub single_config_authority: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RuntimeConfig {
    pub max_cpu_percent: u8,
    pub max_gpu_percent: u8,
    pub max_memory_gib: u32,
    pub max_concurrent_workers: u16,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GovernanceConfig {
    pub default_access_class: AccessClass,
    pub autonomous_agents: bool,
    pub autonomous_claim_adjudication: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LicenseConfig {
    pub default_approved: Vec<String>,
    pub reject_unknown: bool,
    pub reject_paid_runtime: bool,
    pub reject_mandatory_cloud: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StageConfig {
    pub id: u8,
    pub key: String,
    pub name: String,
    pub purpose: String,
    #[serde(default)]
    pub dependencies: Vec<u8>,
    #[serde(default)]
    pub required_assets: Vec<AssetId>,
    #[serde(default)]
    pub required_operators: Vec<OperatorId>,
    pub current_disposition: StageState,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AssetConfig {
    pub id: AssetId,
    pub display_name: String,
    pub asset_class: String,
    pub acquisition_status: String,
    pub license_status: String,
    pub governance_class: AccessClass,
    pub identity_unit: String,
    pub measurement_unit: String,
    #[serde(default)]
    pub allowed_roles: Vec<String>,
    #[serde(default)]
    pub prohibited_roles: Vec<String>,
    #[serde(default)]
    pub applicable_stages: Vec<u8>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct OperatorConfig {
    pub engine: Engine,
    pub entrypoint: String,
    pub input_schema: String,
    pub output_schema: String,
    pub resource_profile: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Engine {
    Rust,
    Go,
    Python,
    Wasm,
}

#[derive(Clone, Debug, Serialize)]
pub struct CompiledConfig {
    pub config_sha256: String,
    pub phase: u8,
    pub stage_count: usize,
    pub stage_id_min: u8,
    pub stage_id_max: u8,
    pub single_config_authority: bool,
    pub config: Config,
}

pub fn load(path: impl AsRef<Path>) -> Result<Config, ConfigError> {
    let text = fs::read_to_string(path)?;
    let config = toml::from_str::<Config>(&text)?;
    validate(&config)?;
    Ok(config)
}

pub fn validate(config: &Config) -> Result<(), ConfigError> {
    if config.application.phase != 1 {
        return Err(ConfigError::Validation(
            "application.phase must equal 1".into(),
        ));
    }
    if !config.application.single_config_authority {
        return Err(ConfigError::Validation(
            "single_config_authority must be true".into(),
        ));
    }
    if !(1..=100).contains(&config.runtime.max_cpu_percent)
        || !(1..=100).contains(&config.runtime.max_gpu_percent)
    {
        return Err(ConfigError::Validation(
            "CPU/GPU percentages must be within 1..=100".into(),
        ));
    }
    if config.governance.autonomous_agents || config.governance.autonomous_claim_adjudication {
        return Err(ConfigError::Validation(
            "Phase 1 prohibits autonomous agents and autonomous claim adjudication".into(),
        ));
    }
    if config.stages.len() != 34 {
        return Err(ConfigError::Validation(format!(
            "expected 34 stages, found {}",
            config.stages.len()
        )));
    }

    let stage_ids: BTreeSet<u8> = config.stages.iter().map(|stage| stage.id).collect();
    let expected: BTreeSet<u8> = (0..=33).collect();
    if stage_ids != expected {
        return Err(ConfigError::Validation(
            "stage IDs must be exactly 0..=33".into(),
        ));
    }
    if stage_ids.len() != config.stages.len() {
        return Err(ConfigError::Validation(
            "duplicate stage IDs detected".into(),
        ));
    }

    let stage_keys: BTreeSet<&str> = config.stages.iter().map(|s| s.key.as_str()).collect();
    if stage_keys.len() != config.stages.len() {
        return Err(ConfigError::Validation(
            "duplicate stage keys detected".into(),
        ));
    }

    let asset_ids: BTreeSet<&str> = config.assets.iter().map(|a| a.id.as_str()).collect();
    if asset_ids.len() != config.assets.len() {
        return Err(ConfigError::Validation(
            "duplicate asset IDs detected".into(),
        ));
    }

    let operator_ids: BTreeSet<&str> = config.operators.keys().map(String::as_str).collect();
    for stage in &config.stages {
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
        for asset in &stage.required_assets {
            if !asset_ids.contains(asset.as_str()) {
                return Err(ConfigError::Validation(format!(
                    "stage {} references unknown asset {}",
                    stage.id, asset
                )));
            }
        }
        for operator in &stage.required_operators {
            if !operator_ids.contains(operator.as_str()) {
                return Err(ConfigError::Validation(format!(
                    "stage {} references unknown operator {}",
                    stage.id, operator
                )));
            }
        }
    }
    validate_dag(&config.stages)?;

    let allowed_licenses: BTreeSet<&str> = [
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "Zlib",
    ]
    .into_iter()
    .collect();
    if config
        .licenses
        .default_approved
        .iter()
        .any(|license| !allowed_licenses.contains(license.as_str()))
    {
        return Err(ConfigError::Validation(
            "default_approved contains a non-allowlisted license".into(),
        ));
    }
    if !config.licenses.reject_unknown
        || !config.licenses.reject_paid_runtime
        || !config.licenses.reject_mandatory_cloud
    {
        return Err(ConfigError::Validation("license policy must reject unknown licenses, paid runtimes, and mandatory cloud dependencies".into()));
    }

    Ok(())
}

fn validate_dag(stages: &[StageConfig]) -> Result<(), ConfigError> {
    let mut indegree: BTreeMap<u8, usize> = stages.iter().map(|s| (s.id, 0)).collect();
    let mut adjacency: BTreeMap<u8, Vec<u8>> = BTreeMap::new();
    for stage in stages {
        for dependency in &stage.dependencies {
            *indegree.get_mut(&stage.id).expect("registered stage") += 1;
            adjacency.entry(*dependency).or_default().push(stage.id);
        }
    }
    let mut queue: VecDeque<u8> = indegree
        .iter()
        .filter_map(|(id, degree)| (*degree == 0).then_some(*id))
        .collect();
    let mut visited = 0usize;
    while let Some(current) = queue.pop_front() {
        visited += 1;
        if let Some(children) = adjacency.get(&current) {
            for child in children {
                let degree = indegree.get_mut(child).expect("registered stage");
                *degree -= 1;
                if *degree == 0 {
                    queue.push_back(*child);
                }
            }
        }
    }
    if visited != stages.len() {
        return Err(ConfigError::Validation(
            "stage dependency graph contains a cycle".into(),
        ));
    }
    Ok(())
}

pub fn compile(config: Config) -> Result<CompiledConfig, ConfigError> {
    validate(&config)?;
    let canonical = serde_json::to_vec(&config)?;
    let config_sha256 = hex::encode(Sha256::digest(canonical));
    Ok(CompiledConfig {
        config_sha256,
        phase: config.application.phase,
        stage_count: config.stages.len(),
        stage_id_min: config.stages.iter().map(|s| s.id).min().unwrap_or(0),
        stage_id_max: config.stages.iter().map(|s| s.id).max().unwrap_or(0),
        single_config_authority: config.application.single_config_authority,
        config,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_config_compiles_deterministically() {
        let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../qudipi.toml");
        let first = compile(load(&path).unwrap()).unwrap();
        let second = compile(load(&path).unwrap()).unwrap();
        assert_eq!(first.config_sha256, second.config_sha256);
        assert_eq!(first.stage_count, 34);
        assert_eq!((first.stage_id_min, first.stage_id_max), (0, 33));
    }
}
