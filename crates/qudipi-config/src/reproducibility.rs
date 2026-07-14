use crate::ConfigError;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
};

const STAGE0_DIRECTORY: &str = "artifacts/stage_00";
const CAPTURE_FILE: &str = "reproducibility_capture.json";
const CLOSURE_MARKER_FILE: &str = "STAGE_00_CLOSED.json";
const HASH_MANIFEST_FILE: &str = "artifact_hashes.json";

#[derive(Debug, Serialize)]
pub struct ReproducibilitySummary {
    pub status: &'static str,
    pub verified_revision: String,
    pub source_tree: String,
    pub gate_count: usize,
    pub generated_files: Vec<String>,
}

#[derive(Debug, Serialize)]
struct ReproducibilityCapture {
    capture_schema: &'static str,
    capture_version: u32,
    status: &'static str,
    verified_revision: String,
    source_tree: String,
    clean_worktree_before_capture: bool,
    configuration_sha256: String,
    gates: Vec<GateResult>,
}

#[derive(Debug, Serialize)]
struct GateResult {
    gate: String,
    command: Vec<String>,
    status: &'static str,
    code: i32,
    stdout_sha256: String,
    stderr_sha256: String,
}

pub fn finalize_stage0_reproducibility(
    repository_root: impl AsRef<Path>,
) -> Result<ReproducibilitySummary, ConfigError> {
    let repository_root = repository_root.as_ref();
    let stage0 = repository_root.join(STAGE0_DIRECTORY);

    require_directory(&stage0)?;

    let verified_revision = git_value(repository_root, &["rev-parse", "HEAD"], "Git revision")?;

    let source_tree = git_value(
        repository_root,
        &["rev-parse", "HEAD^{tree}"],
        "Git source tree",
    )?;

    let worktree_status = git_value_allow_empty(
        repository_root,
        &["status", "--porcelain=v1", "--untracked-files=all"],
        "Git worktree status",
    )?;

    if !worktree_status.is_empty() {
        return Err(ConfigError::Validation(format!(
            "reproducibility capture requires a clean worktree; \
             unresolved paths:\n{worktree_status}"
        )));
    }

    let gates = run_reproducibility_gates(repository_root)?;

    let failed: Vec<&GateResult> = gates.iter().filter(|gate| gate.status != "PASS").collect();

    if !failed.is_empty() {
        let names = failed
            .iter()
            .map(|gate| gate.gate.as_str())
            .collect::<Vec<_>>()
            .join(", ");

        return Err(ConfigError::Validation(format!(
            "reproducibility gates failed: {names}"
        )));
    }

    let configuration_sha256 = fs::read_to_string(stage0.join("config_sha256.txt"))?
        .trim()
        .to_owned();

    validate_sha256("configuration SHA-256", &configuration_sha256)?;

    let capture = ReproducibilityCapture {
        capture_schema: "qudipi.stage0-reproducibility",
        capture_version: 1,
        status: "PASS",
        verified_revision: verified_revision.clone(),
        source_tree: source_tree.clone(),
        clean_worktree_before_capture: true,
        configuration_sha256: configuration_sha256.clone(),
        gates,
    };

    write_json(stage0.join(CAPTURE_FILE), &capture)?;

    finalize_closure_report(
        &stage0,
        &verified_revision,
        &source_tree,
        &configuration_sha256,
    )?;

    write_closure_marker(
        &stage0,
        &verified_revision,
        &source_tree,
        &configuration_sha256,
    )?;

    write_artifact_hashes(&stage0)?;

    Ok(ReproducibilitySummary {
        status: "PASS",
        verified_revision,
        source_tree,
        gate_count: capture.gates.len(),
        generated_files: vec![
            CAPTURE_FILE.to_owned(),
            "closure_gate_report.json".to_owned(),
            CLOSURE_MARKER_FILE.to_owned(),
            HASH_MANIFEST_FILE.to_owned(),
        ],
    })
}

fn run_reproducibility_gates(repository_root: &Path) -> Result<Vec<GateResult>, ConfigError> {
    let gate_specs: &[(&str, &str, &[&str])] = &[
        ("rust_format", "cargo", &["fmt", "--all", "--check"]),
        ("rust_check", "cargo", &["check", "--workspace"]),
        (
            "rust_clippy",
            "cargo",
            &[
                "clippy",
                "--workspace",
                "--all-targets",
                "--",
                "-D",
                "warnings",
            ],
        ),
        ("rust_tests", "cargo", &["test", "--workspace"]),
        (
            "config_validation",
            "cargo",
            &["run", "-q", "-p", "qudipi-cli", "--", "config", "validate"],
        ),
        (
            "python_tests",
            "python",
            &["-m", "pytest", "-q", "tests/qudipi"],
        ),
    ];

    let mut results = Vec::with_capacity(gate_specs.len());

    for (gate, program, arguments) in gate_specs {
        let output = Command::new(program)
            .args(*arguments)
            .current_dir(repository_root)
            .env("PYTHONPATH", repository_root.join("src"))
            .output()
            .map_err(|error| {
                ConfigError::Validation(format!(
                    "failed to execute reproducibility gate \
                     {gate}: {error}"
                ))
            })?;

        results.push(gate_result(gate, program, arguments, output));
    }

    Ok(results)
}

fn gate_result(gate: &str, program: &str, arguments: &[&str], output: Output) -> GateResult {
    let code = output.status.code().unwrap_or(255);

    GateResult {
        gate: gate.to_owned(),
        command: std::iter::once(program.to_owned())
            .chain(arguments.iter().map(|argument| (*argument).to_owned()))
            .collect(),
        status: if output.status.success() {
            "PASS"
        } else {
            "FAIL"
        },
        code,
        stdout_sha256: sha256_bytes(&output.stdout),
        stderr_sha256: sha256_bytes(&output.stderr),
    }
}

fn finalize_closure_report(
    stage0: &Path,
    verified_revision: &str,
    source_tree: &str,
    configuration_sha256: &str,
) -> Result<(), ConfigError> {
    let path = stage0.join("closure_gate_report.json");

    let mut report: Value = serde_json::from_slice(&fs::read(&path)?)?;

    let object = report.as_object_mut().ok_or_else(|| {
        ConfigError::Validation(
            "closure_gate_report.json must contain \
             a JSON object"
                .into(),
        )
    })?;

    object.insert("status".into(), Value::String("CLOSED".into()));

    object.insert("closure_marker_emitted".into(), Value::Bool(true));

    object.insert("remaining_blockers".into(), Value::Array(Vec::new()));

    object.insert(
        "verified_revision".into(),
        Value::String(verified_revision.to_owned()),
    );

    object.insert(
        "verified_source_tree".into(),
        Value::String(source_tree.to_owned()),
    );

    object.insert(
        "configuration_sha256".into(),
        Value::String(configuration_sha256.to_owned()),
    );

    object.insert(
        "reproducibility_capture".into(),
        Value::String(CAPTURE_FILE.into()),
    );

    write_json(path, &report)
}

fn write_closure_marker(
    stage0: &Path,
    verified_revision: &str,
    source_tree: &str,
    configuration_sha256: &str,
) -> Result<(), ConfigError> {
    let marker = json!({
        "marker_schema": "qudipi.stage-closure",
        "marker_version": 1,
        "stage_id": 0,
        "status": "CLOSED",
        "verified_revision": verified_revision,
        "verified_source_tree": source_tree,
        "configuration_sha256": configuration_sha256,
        "reproducibility_capture": CAPTURE_FILE,
        "closure_gate_report": "closure_gate_report.json"
    });

    write_json(stage0.join(CLOSURE_MARKER_FILE), &marker)
}

fn write_artifact_hashes(stage0: &Path) -> Result<(), ConfigError> {
    let mut hashes = BTreeMap::new();

    for entry in fs::read_dir(stage0)? {
        let entry = entry?;
        let path = entry.path();

        if !path.is_file() {
            continue;
        }

        let Some(file_name) = path.file_name().and_then(|name| name.to_str()) else {
            continue;
        };

        if file_name == HASH_MANIFEST_FILE {
            continue;
        }

        hashes.insert(file_name.to_owned(), sha256_bytes(&fs::read(&path)?));
    }

    write_json(stage0.join(HASH_MANIFEST_FILE), &hashes)
}

fn git_value(
    repository_root: &Path,
    arguments: &[&str],
    label: &str,
) -> Result<String, ConfigError> {
    let value = git_value_allow_empty(repository_root, arguments, label)?;

    if value.is_empty() {
        return Err(ConfigError::Validation(format!(
            "{label} returned an empty value"
        )));
    }

    Ok(value)
}

fn git_value_allow_empty(
    repository_root: &Path,
    arguments: &[&str],
    label: &str,
) -> Result<String, ConfigError> {
    let output = Command::new("git")
        .args(arguments)
        .current_dir(repository_root)
        .output()
        .map_err(|error| ConfigError::Validation(format!("failed to execute {label}: {error}")))?;

    if !output.status.success() {
        return Err(ConfigError::Validation(format!(
            "{label} failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        )));
    }

    Ok(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

fn require_directory(path: &Path) -> Result<(), ConfigError> {
    if !path.is_dir() {
        return Err(ConfigError::Validation(format!(
            "required directory does not exist: {}",
            path.display()
        )));
    }

    Ok(())
}

fn validate_sha256(label: &str, value: &str) -> Result<(), ConfigError> {
    let valid = value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit());

    if !valid {
        return Err(ConfigError::Validation(format!(
            "{label} is not a valid SHA-256 digest"
        )));
    }

    Ok(())
}

fn write_json(path: PathBuf, value: &impl Serialize) -> Result<(), ConfigError> {
    let mut bytes = serde_json::to_vec_pretty(value)?;
    bytes.push(b'\n');
    fs::write(path, bytes)?;

    Ok(())
}

fn sha256_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
