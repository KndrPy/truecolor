use crate::{Config, ConfigError, validation::validate};
use std::{fs, path::Path};

pub fn load(path: impl AsRef<Path>) -> Result<Config, ConfigError> {
    let text = fs::read_to_string(path)?;
    let config = toml::from_str::<Config>(&text)?;
    validate(&config)?;
    Ok(config)
}
