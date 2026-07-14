use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RoleConfig {
    pub description: String,
    pub role_class: String,
    pub derivation_mode: RoleDerivationMode,

    #[serde(default)]
    pub requires_all: Vec<String>,

    #[serde(default)]
    pub requires_any: Vec<String>,

    #[serde(default)]
    pub forbids_any: Vec<String>,

    pub risk_class: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RoleDerivationMode {
    RuleBased,
    DeclaredOnly,
    Hybrid,
}
