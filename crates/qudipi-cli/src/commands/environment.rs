use crate::{
    cli::{EnvironmentCommand, OutputFormat},
    output,
};
use anyhow::Result;
use qudipi_environment::{EnvironmentReport, inspect};
use std::path::Path;

pub fn execute(
    command: EnvironmentCommand,
    config_path: &Path,
    format: OutputFormat,
) -> Result<()> {
    match command {
        EnvironmentCommand::Inspect => {
            let report = inspect(config_path);

            match format {
                OutputFormat::Text => print_report(&report),
                OutputFormat::CompactJson => output::print_json(&report)?,
            }
        }
    }

    Ok(())
}

fn print_report(report: &EnvironmentReport) {
    println!("QUDIPI_ENVIRONMENT_STATUS=PASS");
    println!("os={}", report.os);
    println!("kernel={}", report.kernel);
    println!("cpu={}", report.cpu);
    println!("memory={}", report.memory);
    println!("gpu={}", report.gpu);
    println!("gpu_driver={}", report.gpu_driver);
    println!("rust_version={}", report.rust_version);
    println!("go_version={}", report.go_version);
    println!("python_version={}", report.python_version);
    println!("node_version={}", report.node_version);
    println!("pnpm_version={}", report.pnpm_version);
    println!("git_commit={}", report.git_commit);
    println!("git_branch={}", report.git_branch);
    println!("git_dirty={}", report.git_dirty);
    println!("cargo_lock_sha256={}", report.cargo_lock_sha256);
    println!("qudipi_toml_sha256={}", report.qudipi_toml_sha256);
}
