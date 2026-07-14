use super::{
    ApplicationConfig, AssetConfig, CorpusCharacterizationConfig, GovernanceConfig, LicenseConfig,
    OperatorConfig, RoleConfig, RuntimeConfig, SchemaConfig, StageConfig,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Config {
    pub application: ApplicationConfig,
    pub runtime: RuntimeConfig,
    pub governance: GovernanceConfig,
    pub licenses: LicenseConfig,
    pub corpus_characterization: CorpusCharacterizationConfig,
    pub roles: BTreeMap<String, RoleConfig>,
    pub stages: Vec<StageConfig>,
    pub assets: Vec<AssetConfig>,
    pub schemas: BTreeMap<String, SchemaConfig>,
    pub operators: BTreeMap<String, OperatorConfig>,
}
