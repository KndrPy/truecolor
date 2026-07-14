use crate::{CompiledConfig, Config, ConfigError, canonical, validation::validate};

const MANIFEST_SCHEMA: &str = "qudipi.compiled-config";
const MANIFEST_VERSION: u16 = 1;

pub fn compile(config: Config) -> Result<CompiledConfig, ConfigError> {
    validate(&config)?;

    let canonical = canonical::serialize(&config)?;
    let config_sha256 = canonical::sha256(&canonical);

    Ok(CompiledConfig {
        manifest_schema: MANIFEST_SCHEMA.to_string(),
        manifest_version: MANIFEST_VERSION,
        product_version: env!("CARGO_PKG_VERSION").to_string(),
        config_sha256,
        phase: config.application.phase,
        stage_count: config.stages.len(),
        stage_id_min: config
            .stages
            .iter()
            .map(|stage| stage.id)
            .min()
            .unwrap_or(0),
        stage_id_max: config
            .stages
            .iter()
            .map(|stage| stage.id)
            .max()
            .unwrap_or(0),
        single_config_authority: config.application.single_config_authority,
        config,
    })
}
