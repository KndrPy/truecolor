use qudipi_domain::{AccessClass, AssetId, RoleId};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

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
    pub characteristics: Vec<String>,

    #[serde(default)]
    pub known_details: BTreeMap<String, String>,

    #[serde(default)]
    pub unknown_details: Vec<String>,

    #[serde(default, alias = "allowed_roles")]
    pub declared_allowed_roles: Vec<RoleId>,

    #[serde(default, alias = "prohibited_roles")]
    pub declared_prohibited_roles: Vec<RoleId>,

    #[serde(default)]
    pub applicable_stages: Vec<u8>,
}
