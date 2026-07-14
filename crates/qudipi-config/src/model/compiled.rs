use super::Config;
use serde::Serialize;

#[derive(Clone, Debug, Serialize)]
pub struct CompiledConfig {
    pub manifest_schema: String,
    pub manifest_version: u16,
    pub product_version: String,
    pub config_sha256: String,
    pub phase: u8,
    pub stage_count: usize,
    pub stage_id_min: u8,
    pub stage_id_max: u8,
    pub single_config_authority: bool,
    pub config: Config,
}
