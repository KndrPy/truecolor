mod canonical;
mod compiler;
mod error;
mod evidence;
mod loader;
mod model;
mod reproducibility;
mod validation;

pub use compiler::compile;
pub use error::ConfigError;
pub use evidence::{Stage0EvidenceSummary, emit_stage0_evidence};
pub use loader::load;
pub use model::{
    ApplicationConfig, AssetConfig, CompiledConfig, Config, CorpusCharacterizationConfig, Engine,
    GovernanceConfig, LicenseConfig, OperatorConfig, RoleConfig, RoleDerivationMode, RuntimeConfig,
    SchemaClass, SchemaConfig, Serialization, StageAssetRequirement, StageConfig,
};
pub use reproducibility::{ReproducibilitySummary, finalize_stage0_reproducibility};
pub use validation::validate;

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

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
