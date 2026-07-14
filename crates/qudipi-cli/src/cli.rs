use clap::{Parser, Subcommand, ValueEnum};
use std::path::PathBuf;

#[derive(Parser)]
#[command(
    name = "qudipi",
    version,
    about = "QuDiPi Version 2.0 control-plane CLI"
)]
pub struct Cli {
    #[arg(long, default_value = "qudipi.toml")]
    pub config: PathBuf,

    #[arg(long, value_enum, default_value_t = OutputFormat::Text)]
    pub output: OutputFormat,

    #[command(subcommand)]
    pub command: Command,
}

#[derive(Clone, Copy, Debug, ValueEnum)]
pub enum OutputFormat {
    Text,
    CompactJson,
}

#[derive(Subcommand)]
pub enum Command {
    Config {
        #[command(subcommand)]
        command: ConfigCommand,
    },
    Stage {
        #[command(subcommand)]
        command: RegistryCommand,
    },
    Asset {
        #[command(subcommand)]
        command: RegistryCommand,
    },
    Schema {
        #[command(subcommand)]
        command: RegistryCommand,
    },
    Operator {
        #[command(subcommand)]
        command: RegistryCommand,
    },
    Environment {
        #[command(subcommand)]
        command: EnvironmentCommand,
    },
}

#[derive(Subcommand)]
pub enum ConfigCommand {
    Validate,

    Compile {
        #[arg(
            long,
            default_value = "artifacts/stage_00/compiled_config_manifest.json"
        )]
        destination: PathBuf,
    },

    ShowHash,

    EmitStage0Evidence {
        #[arg(long, default_value = "artifacts/stage_00")]
        destination: PathBuf,
    },
}

#[derive(Clone, Copy, Subcommand)]
pub enum RegistryCommand {
    List,
}

#[derive(Clone, Copy, Subcommand)]
pub enum EnvironmentCommand {
    Inspect,
}
