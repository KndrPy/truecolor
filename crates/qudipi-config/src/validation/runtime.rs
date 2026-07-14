use crate::{ConfigError, RuntimeConfig};

pub(crate) fn validate(runtime: &RuntimeConfig) -> Result<(), ConfigError> {
    if !(1..=100).contains(&runtime.max_cpu_percent) {
        return Err(ConfigError::Validation(
            "max_cpu_percent must be within 1..=100".into(),
        ));
    }

    if !(1..=100).contains(&runtime.max_gpu_percent) {
        return Err(ConfigError::Validation(
            "max_gpu_percent must be within 1..=100".into(),
        ));
    }

    if runtime.max_memory_gib == 0 {
        return Err(ConfigError::Validation(
            "max_memory_gib must be greater than zero".into(),
        ));
    }

    if runtime.max_concurrent_workers == 0 {
        return Err(ConfigError::Validation(
            "max_concurrent_workers must be greater than zero".into(),
        ));
    }

    Ok(())
}
