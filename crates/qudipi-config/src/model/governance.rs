use qudipi_domain::AccessClass;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GovernanceConfig {
    pub default_access_class: AccessClass,
    pub autonomous_agents: bool,
    pub autonomous_claim_adjudication: bool,
}
