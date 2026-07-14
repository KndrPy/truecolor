mod cli;
mod commands;
mod output;

use anyhow::Result;
use clap::Parser;
use cli::Cli;

fn main() -> Result<()> {
    commands::execute(Cli::parse())
}
