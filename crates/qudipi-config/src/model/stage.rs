use qudipi_domain::{AssetId, OperatorId, RequirementId, RoleId};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StageConfig {
    pub id: u8,
    pub key: String,
    pub name: String,
    pub purpose: String,
    pub dependencies: Vec<u8>,
    pub required_assets: Vec<AssetId>,
    pub required_operators: Vec<OperatorId>,
    pub current_disposition: String,

    #[serde(default)]
    pub asset_requirements: Vec<StageAssetRequirement>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StageAssetRequirement {
    pub requirement_id: RequirementId,
    pub minimum_assets: usize,

    #[serde(default)]
    pub required_characteristics: Vec<String>,

    #[serde(default)]
    pub accepted_roles: Vec<RoleId>,
}
