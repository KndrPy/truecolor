use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RuntimeConfig {
    pub max_cpu_percent: u8,
    pub max_gpu_percent: u8,
    pub max_memory_gib: u32,
    pub max_concurrent_workers: u16,
}
