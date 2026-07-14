use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LicenseConfig {
    pub product_license: String,
    pub product_version: String,
    pub source_distribution: String,
    pub redistribution_requires_written_agreement: bool,
    pub default_approved: Vec<String>,
    pub reject_unknown: bool,
    pub reject_paid_runtime: bool,
    pub reject_mandatory_cloud: bool,
}
