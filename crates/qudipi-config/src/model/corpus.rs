use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CorpusCharacterizationConfig {
    pub required_details: Vec<String>,
    pub controlled_characteristics: bool,
    pub reject_unknown_roles: bool,
    pub preserve_unknown_details: bool,
}
