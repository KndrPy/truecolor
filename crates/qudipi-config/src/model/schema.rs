use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SchemaConfig {
    pub description: String,
    pub schema_class: SchemaClass,
    pub serialization: Serialization,
    pub version: u16,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SchemaClass {
    Control,
    Registry,
    Literature,
    Tabular,
    Spectral,
    Image,
    Tensor,
    Graph,
    Measurement,
    Statistical,
    Clinical,
    Artifact,
    Report,
    Release,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Serialization {
    Json,
    ArrowIpc,
    Parquet,
    Protobuf,
    DirectoryManifest,
}
