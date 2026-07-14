use crate::{
    cli::{ConfigCommand, OutputFormat},
    output,
};
use anyhow::Result;
use qudipi_config::{CompiledConfig, emit_stage0_evidence};
use std::fs;

pub fn execute(
    command: ConfigCommand,
    compiled: &CompiledConfig,
    format: OutputFormat,
) -> Result<()> {
    match command {
        ConfigCommand::Validate => match format {
            OutputFormat::Text => print_summary(compiled),
            OutputFormat::CompactJson => {
                output::print_json(compiled)?;
            }
        },

        ConfigCommand::Compile { destination } => {
            if let Some(parent) = destination.parent() {
                fs::create_dir_all(parent)?;
            }

            fs::write(&destination, serde_json::to_vec_pretty(compiled)?)?;

            match format {
                OutputFormat::Text => {
                    println!("{}", destination.display());
                }
                OutputFormat::CompactJson => {
                    output::print_json(&serde_json::json!({
                        "destination": destination,
                        "config_sha256":
                            compiled.config_sha256,
                    }))?;
                }
            }
        }

        ConfigCommand::ShowHash => match format {
            OutputFormat::Text => {
                println!("{}", compiled.config_sha256);
            }
            OutputFormat::CompactJson => {
                output::print_json(&serde_json::json!({
                    "config_sha256":
                        compiled.config_sha256,
                }))?;
            }
        },

        ConfigCommand::EmitStage0Evidence { destination } => {
            let summary = emit_stage0_evidence(compiled, &destination)?;

            match format {
                OutputFormat::Text => {
                    println!("QUDIPI_STAGE0_EVIDENCE_STATUS={}", summary.status);
                    println!("destination={}", summary.destination.display());
                    println!("generated_file_count={}", summary.generated_files.len());
                    println!("config_sha256={}", summary.config_sha256);
                }
                OutputFormat::CompactJson => {
                    output::print_json(&summary)?;
                }
            }
        }
    }

    Ok(())
}

fn print_summary(compiled: &CompiledConfig) {
    println!("QUDIPI_CONFIG_STATUS=PASS");
    println!("phase={}", compiled.phase);
    println!("stage_count={}", compiled.stage_count);
    println!("stage_id_min={}", compiled.stage_id_min);
    println!("stage_id_max={}", compiled.stage_id_max);
    println!(
        "single_config_authority={}",
        compiled.single_config_authority
    );
    println!("config_sha256={}", compiled.config_sha256);
}
