use crate::{ConfigError, LicenseConfig};
use std::collections::BTreeSet;

const PRODUCT_LICENSE: &str = "proprietary_commercial";
const SOURCE_DISTRIBUTION: &str = "restricted";

pub(crate) fn validate(licenses: &LicenseConfig) -> Result<(), ConfigError> {
    if licenses.product_license != PRODUCT_LICENSE {
        return Err(ConfigError::Validation(format!(
            "product_license must equal {PRODUCT_LICENSE}"
        )));
    }

    if licenses.product_version != env!("CARGO_PKG_VERSION") {
        return Err(ConfigError::Validation(format!(
            "licenses.product_version must equal product version {}",
            env!("CARGO_PKG_VERSION")
        )));
    }

    if licenses.source_distribution != SOURCE_DISTRIBUTION {
        return Err(ConfigError::Validation(format!(
            "source_distribution must equal {SOURCE_DISTRIBUTION}"
        )));
    }

    if !licenses.redistribution_requires_written_agreement {
        return Err(ConfigError::Validation(
            "redistribution must require a written agreement".into(),
        ));
    }

    if licenses.default_approved.is_empty() {
        return Err(ConfigError::Validation(
            "dependency license allowlist must not be empty".into(),
        ));
    }

    let normalized: Vec<&str> = licenses
        .default_approved
        .iter()
        .map(|license| license.trim())
        .collect();

    if normalized.iter().any(|license| license.is_empty()) {
        return Err(ConfigError::Validation(
            "dependency license allowlist contains a blank license".into(),
        ));
    }

    let unique: BTreeSet<&str> = normalized.iter().copied().collect();

    if unique.len() != licenses.default_approved.len() {
        return Err(ConfigError::Validation(
            "dependency license allowlist contains duplicates".into(),
        ));
    }

    if !licenses.reject_unknown {
        return Err(ConfigError::Validation(
            "license policy must reject unknown licenses".into(),
        ));
    }

    if !licenses.reject_paid_runtime {
        return Err(ConfigError::Validation(
            "license policy must reject paid runtime dependencies".into(),
        ));
    }

    if !licenses.reject_mandatory_cloud {
        return Err(ConfigError::Validation(
            "license policy must reject mandatory cloud dependencies".into(),
        ));
    }

    Ok(())
}
