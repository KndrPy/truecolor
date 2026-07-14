use crate::{
    cli::{OutputFormat, RegistryCommand},
    output,
};
use anyhow::Result;
use qudipi_config::CompiledConfig;

pub fn execute_stages(
    command: RegistryCommand,
    compiled: &CompiledConfig,
    format: OutputFormat,
) -> Result<()> {
    match command {
        RegistryCommand::List => match format {
            OutputFormat::Text => {
                for stage in &compiled.config.stages {
                    println!("{:02}  {}", stage.id, stage.name);
                }
            }
            OutputFormat::CompactJson => {
                output::print_json(&compiled.config.stages)?;
            }
        },
    }

    Ok(())
}

pub fn execute_assets(
    command: RegistryCommand,
    compiled: &CompiledConfig,
    format: OutputFormat,
) -> Result<()> {
    match command {
        RegistryCommand::List => match format {
            OutputFormat::Text => {
                for asset in &compiled.config.assets {
                    println!("{}  {}", asset.id, asset.display_name);
                }
            }
            OutputFormat::CompactJson => {
                output::print_json(&compiled.config.assets)?;
            }
        },
    }

    Ok(())
}

pub fn execute_schemas(
    command: RegistryCommand,
    compiled: &CompiledConfig,
    format: OutputFormat,
) -> Result<()> {
    match command {
        RegistryCommand::List => match format {
            OutputFormat::Text => {
                for (schema_id, schema) in &compiled.config.schemas {
                    println!(
                        "{}  {:?}  {:?}  v{}  {}",
                        schema_id,
                        schema.schema_class,
                        schema.serialization,
                        schema.version,
                        schema.description
                    );
                }
            }
            OutputFormat::CompactJson => {
                output::print_json(&compiled.config.schemas)?;
            }
        },
    }

    Ok(())
}

pub fn execute_operators(
    command: RegistryCommand,
    compiled: &CompiledConfig,
    format: OutputFormat,
) -> Result<()> {
    match command {
        RegistryCommand::List => match format {
            OutputFormat::Text => {
                for (operator_id, operator) in &compiled.config.operators {
                    println!(
                        "{}  {:?}  {}  {} -> {}",
                        operator_id,
                        operator.engine,
                        operator.entrypoint,
                        operator.input_schema,
                        operator.output_schema
                    );
                }
            }
            OutputFormat::CompactJson => {
                output::print_json(&compiled.config.operators)?;
            }
        },
    }

    Ok(())
}
