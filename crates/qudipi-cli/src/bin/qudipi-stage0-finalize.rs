use anyhow::{Context, Result};
use qudipi_config::finalize_stage0_reproducibility;
use std::env;

fn main() -> Result<()> {
    let repository_root = env::current_dir().context("failed to resolve repository root")?;

    let summary = finalize_stage0_reproducibility(&repository_root)
        .context("Stage 0 reproducibility finalization failed")?;

    println!("QUDIPI_STAGE0_FINALIZATION_STATUS=PASS");
    println!("verified_revision={}", summary.verified_revision);
    println!("source_tree={}", summary.source_tree);
    println!("gate_count={}", summary.gate_count);

    for generated_file in summary.generated_files {
        println!("generated_file={generated_file}");
    }

    Ok(())
}
