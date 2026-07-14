use qudipi_domain::SchemaId;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct OperatorConfig {
    pub engine: Engine,
    pub entrypoint: String,
    pub input_schema: SchemaId,
    pub output_schema: SchemaId,
    pub resource_profile: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Engine {
    Rust,
    Go,
    Python,
    Wasm,
}
