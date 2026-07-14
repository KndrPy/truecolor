use sha2::{Digest, Sha256};
use std::{fs, path::Path};

pub(crate) fn file_sha256(path: &Path) -> String {
    let Ok(bytes) = fs::read(path) else {
        return "NOT_AVAILABLE".to_string();
    };

    format!("{:x}", Sha256::digest(bytes))
}
