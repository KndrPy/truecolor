use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct EnvironmentReport {
    pub os: String,
    pub kernel: String,
    pub cpu: String,
    pub memory: String,
    pub gpu: String,
    pub gpu_driver: String,
    pub rust_version: String,
    pub go_version: String,
    pub python_version: String,
    pub node_version: String,
    pub pnpm_version: String,
    pub git_commit: String,
    pub git_branch: String,
    pub git_dirty: String,
    pub cargo_lock_sha256: String,
    pub qudipi_toml_sha256: String,
}
