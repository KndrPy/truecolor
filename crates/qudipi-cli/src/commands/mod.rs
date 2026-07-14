mod config;
mod environment;
mod registry;

use crate::cli::{Cli, Command};
use anyhow::{Context, Result};
use qudipi_config::{compile, load};

pub fn execute(cli: Cli) -> Result<()> {
    let Cli {
        config: config_path,
        output,
        command,
    } = cli;

    match command {
        Command::Environment { command } => environment::execute(command, &config_path, output),
        configured_command => {
            let config = load(&config_path)
                .with_context(|| format!("failed to load {}", config_path.display()))?;

            let compiled = compile(config)?;

            match configured_command {
                Command::Config { command } => config::execute(command, &compiled, output),
                Command::Stage { command } => registry::execute_stages(command, &compiled, output),
                Command::Asset { command } => registry::execute_assets(command, &compiled, output),
                Command::Schema { command } => {
                    registry::execute_schemas(command, &compiled, output)
                }
                Command::Operator { command } => {
                    registry::execute_operators(command, &compiled, output)
                }
                Command::Environment { .. } => {
                    unreachable!("environment command handled before config compilation")
                }
            }
        }
    }
}
