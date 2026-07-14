use serde::{Deserialize, Serialize};
use std::{fmt, str::FromStr};
use thiserror::Error;

macro_rules! id_type {
    ($name:ident) => {
        #[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            pub fn new(value: impl Into<String>) -> Result<Self, IdError> {
                let value = value.into();
                validate_id(&value)?;
                Ok(Self(value))
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                self.0.fmt(f)
            }
        }

        impl FromStr for $name {
            type Err = IdError;

            fn from_str(value: &str) -> Result<Self, Self::Err> {
                Self::new(value)
            }
        }
    };
}

#[derive(Debug, Error, Eq, PartialEq)]
pub enum IdError {
    #[error("identifier must not be empty")]
    Empty,
    #[error("identifier must start with an ASCII lowercase letter")]
    InvalidStart,
    #[error("identifier may contain only ASCII lowercase letters, digits, underscores, or hyphens")]
    InvalidCharacter,
}

fn validate_id(value: &str) -> Result<(), IdError> {
    if value.is_empty() {
        return Err(IdError::Empty);
    }
    let mut chars = value.chars();
    match chars.next() {
        Some(c) if c.is_ascii_lowercase() => {}
        _ => return Err(IdError::InvalidStart),
    }
    if chars.any(|c| !(c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-')) {
        return Err(IdError::InvalidCharacter);
    }
    Ok(())
}

id_type!(ProjectId);
id_type!(StudyId);
id_type!(ResearchPackId);
id_type!(AssetId);
id_type!(OperatorId);
id_type!(RunId);
id_type!(ArtifactId);
id_type!(ObjectId);
id_type!(ConfigSnapshotId);

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StageState {
    Open,
    Blocked,
    Verify,
    Closed,
    ClosedWithScopeRestriction,
    Falsified,
    NotTestableWithCurrentAssets,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RunState {
    Queued,
    Running,
    Paused,
    Cancelling,
    Cancelled,
    Failed,
    Completed,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AccessClass {
    Public,
    ProjectPrivate,
    LocallyGoverned,
    Restricted,
    DerivedSummary,
    ExportProhibited,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ClaimState {
    Supported,
    SupportedWithScopeRestriction,
    Inconclusive,
    Falsified,
    NotTestableWithCurrentAssets,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ArtifactClass {
    Control,
    Registry,
    ArrowIpc,
    Parquet,
    Model,
    Figure,
    Report,
    Manifest,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identifiers_accept_canonical_values() {
        assert_eq!(ProjectId::new("truecolor").unwrap().as_str(), "truecolor");
        assert_eq!(AssetId::new("arad_1k-31").unwrap().as_str(), "arad_1k-31");
    }

    #[test]
    fn identifiers_reject_noncanonical_values() {
        assert_eq!(ProjectId::new("").unwrap_err(), IdError::Empty);
        assert_eq!(
            ProjectId::new("TrueColor").unwrap_err(),
            IdError::InvalidStart
        );
        assert_eq!(
            ProjectId::new("true color").unwrap_err(),
            IdError::InvalidCharacter
        );
    }
}
