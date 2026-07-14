mod application;
pub(crate) mod assets;
mod governance;
mod graph;
mod licenses;
mod operators;
mod roles;
mod runtime;
mod schemas;
mod stages;

use crate::{Config, ConfigError};

pub fn validate(config: &Config) -> Result<(), ConfigError> {
    application::validate(&config.application)?;
    runtime::validate(&config.runtime)?;
    governance::validate(&config.governance)?;
    licenses::validate(&config.licenses)?;
    roles::validate(&config.roles)?;
    schemas::validate(&config.schemas)?;

    operators::validate(&config.operators, &config.schemas)?;

    stages::validate(&config.stages, &config.assets, &config.operators)?;

    assets::validate(
        &config.corpus_characterization,
        &config.roles,
        &config.assets,
        &config.stages,
    )?;

    graph::validate(&config.stages)?;

    Ok(())
}
