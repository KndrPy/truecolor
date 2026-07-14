use crate::{EnvironmentReport, hashing::file_sha256};
use std::{env, fs, path::Path, process::Command};

const NOT_AVAILABLE: &str = "NOT_AVAILABLE";

pub fn inspect(config_path: &Path) -> EnvironmentReport {
    EnvironmentReport {
        os: env::consts::OS.to_string(),
        kernel: command_output("uname", &["-sr"]),
        cpu: detect_cpu(),
        memory: detect_memory(),
        gpu: detect_gpu(),
        gpu_driver: detect_gpu_driver(),
        rust_version: command_output("rustc", &["--version"]),
        go_version: command_output("go", &["version"]),
        python_version: detect_python(),
        node_version: command_output("node", &["--version"]),
        pnpm_version: command_output("pnpm", &["--version"]),
        git_commit: command_output("git", &["rev-parse", "HEAD"]),
        git_branch: command_output("git", &["branch", "--show-current"]),
        git_dirty: detect_git_dirty(),
        cargo_lock_sha256: file_sha256(Path::new("Cargo.lock")),
        qudipi_toml_sha256: file_sha256(config_path),
    }
}

fn command_output(program: &str, args: &[&str]) -> String {
    match Command::new(program).args(args).output() {
        Ok(output) if output.status.success() => {
            let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
            let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();

            if !stdout.is_empty() {
                stdout
            } else if !stderr.is_empty() {
                stderr
            } else {
                NOT_AVAILABLE.to_string()
            }
        }
        _ => NOT_AVAILABLE.to_string(),
    }
}

fn detect_python() -> String {
    let python = command_output("python", &["--version"]);

    if python == NOT_AVAILABLE {
        command_output("python3", &["--version"])
    } else {
        python
    }
}

fn detect_cpu() -> String {
    #[cfg(target_os = "linux")]
    {
        if let Ok(content) = fs::read_to_string("/proc/cpuinfo") {
            for line in content.lines() {
                if let Some((key, value)) = line.split_once(':') {
                    if key.trim() == "model name" {
                        return value.trim().to_string();
                    }
                }
            }
        }
    }

    #[cfg(target_os = "macos")]
    {
        return command_output("sysctl", &["-n", "machdep.cpu.brand_string"]);
    }

    #[cfg(target_os = "windows")]
    {
        return env::var("PROCESSOR_IDENTIFIER").unwrap_or_else(|_| NOT_AVAILABLE.to_string());
    }

    NOT_AVAILABLE.to_string()
}

fn detect_memory() -> String {
    #[cfg(target_os = "linux")]
    {
        if let Ok(content) = fs::read_to_string("/proc/meminfo") {
            for line in content.lines() {
                if let Some(value) = line.strip_prefix("MemTotal:") {
                    return value.trim().to_string();
                }
            }
        }
    }

    #[cfg(target_os = "macos")]
    {
        return command_output("sysctl", &["-n", "hw.memsize"]);
    }

    NOT_AVAILABLE.to_string()
}

fn detect_gpu() -> String {
    let nvidia = command_output("nvidia-smi", &["--query-gpu=name", "--format=csv,noheader"]);

    if nvidia != NOT_AVAILABLE {
        return normalize_multiline(&nvidia);
    }

    let rocm = command_output("rocm-smi", &["--showproductname"]);

    if rocm != NOT_AVAILABLE {
        return normalize_multiline(&rocm);
    }

    let pci = command_output("lspci", &[]);

    if pci == NOT_AVAILABLE {
        return pci;
    }

    let matches = pci
        .lines()
        .filter(|line| {
            let normalized = line.to_ascii_lowercase();
            normalized.contains("vga compatible controller")
                || normalized.contains("3d controller")
                || normalized.contains("display controller")
        })
        .collect::<Vec<_>>()
        .join(" | ");

    if matches.is_empty() {
        NOT_AVAILABLE.to_string()
    } else {
        matches
    }
}

fn detect_gpu_driver() -> String {
    let nvidia = command_output(
        "nvidia-smi",
        &["--query-gpu=driver_version", "--format=csv,noheader"],
    );

    if nvidia != NOT_AVAILABLE {
        return normalize_multiline(&nvidia);
    }

    let rocm = command_output("rocm-smi", &["--showdriverversion"]);

    if rocm != NOT_AVAILABLE {
        normalize_multiline(&rocm)
    } else {
        NOT_AVAILABLE.to_string()
    }
}

fn detect_git_dirty() -> String {
    match Command::new("git").args(["status", "--porcelain"]).output() {
        Ok(output) if output.status.success() => {
            if output.stdout.is_empty() {
                "false".to_string()
            } else {
                "true".to_string()
            }
        }
        _ => NOT_AVAILABLE.to_string(),
    }
}

fn normalize_multiline(value: &str) -> String {
    value
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .collect::<Vec<_>>()
        .join(" | ")
}

#[cfg(test)]
mod tests {
    use super::normalize_multiline;

    #[test]
    fn multiline_output_is_normalized() {
        assert_eq!(normalize_multiline("first\n\n second \n"), "first | second");
    }
}
