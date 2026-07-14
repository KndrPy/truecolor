use crate::{ApplicationConfig, ConfigError};

pub(crate) fn validate(application: &ApplicationConfig) -> Result<(), ConfigError> {
    if application.phase != 1 {
        return Err(ConfigError::Validation(
            "application.phase must equal 1".into(),
        ));
    }

    if !application.single_config_authority {
        return Err(ConfigError::Validation(
            "single_config_authority must be true".into(),
        ));
    }

    Ok(())
}
