use crate::{ConfigError, GovernanceConfig};

pub(crate) fn validate(governance: &GovernanceConfig) -> Result<(), ConfigError> {
    if governance.autonomous_agents || governance.autonomous_claim_adjudication {
        return Err(ConfigError::Validation(
            "Phase 1 prohibits autonomous agents and autonomous claim adjudication".into(),
        ));
    }

    Ok(())
}
