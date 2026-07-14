use crate::{Config, ConfigError};
use sha2::{Digest, Sha256};

pub(crate) fn serialize(config: &Config) -> Result<Vec<u8>, ConfigError> {
    Ok(serde_json::to_vec(config)?)
}

pub(crate) fn sha256(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

#[cfg(test)]
mod tests {
    use super::sha256;

    #[test]
    fn sha256_is_stable_for_known_input() {
        assert_eq!(
            sha256(b"qudipi"),
            "f6755f571266bb72a64a8db8f317d07c1588d61d5e769e794d97304e56bd44c9"
        );
    }
}
