use thiserror::Error;

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("failed to read configuration: {0}")]
    Io(#[from] std::io::Error),

    #[error("failed to parse TOML: {0}")]
    Toml(#[from] toml::de::Error),

    #[error("configuration validation failed: {0}")]
    Validation(String),

    #[error("failed to serialize compiled configuration: {0}")]
    Serialization(#[from] serde_json::Error),
}
