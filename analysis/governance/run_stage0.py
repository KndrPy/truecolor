from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


EXPECTED_BRANCH = "analysis/canonical-stage0-refactor"
EXPECTED_BASELINE = "b7f921e4554c27d867b5c173a85dce939813f493"
EXPECTED_STAGE_COUNT = 29

REQUIRED_ASSETS = {
    "issa",
    "scin",
    "mst_e",
    "fitzpatrick17k",
    "cleanpatrick",
    "ddi",
    "ddi2",
    "mra_midas",
    "camera_sensitivities",
    "illuminant_spectra",
    "color_reference_data",
    "prior_art_corpus",
}

REQUIRED_GOVERNANCE_FILES = [
    "__init__.py",
    "program_registry.yaml",
    "data_asset_registry.yaml",
    "stage_registry.yaml",
    "legacy_evidence_registry.yaml",
    "closure_requirements.yaml",
    "falsification_policy.yaml",
    "artifact_contract.yaml",
    "seed_registry.yaml",
    "environment_registry.yaml",
    "data_governance.yaml",
    "claim_dataset_matrix.yaml",
    "deviation_register.yaml",
    "reproducibility_policy.md",
    "schemas/stage_state.schema.json",
    "templates/stage_closure_template.yaml",
    "run_stage0.py",
    "run_stage0.sh",
    "run_stage0_falsification.py",
    "STAGE_0_READY.yaml",
]


def run(
    command: list[str],
    *,
    required: bool = True,
) -> str:
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )

    if required and completed.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )

    return completed.stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(value, dict):
        raise TypeError(
            f"Expected mapping in {path}"
        )

    return value


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def capture_optional(
    command: list[str],
) -> str:
    if not command_exists(command[0]):
        return "UNAVAILABLE"

    return run(
        command,
        required=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "analysis/governance/results"
        ),
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
    )
    args = parser.parse_args()

    repo = Path.cwd()
    governance = repo / "analysis/governance"
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)

    branch = run(
        ["git", "branch", "--show-current"]
    )
    head = run(
        ["git", "rev-parse", "HEAD"]
    )
    origin_main = run(
        ["git", "rev-parse", "origin/main"]
    )
    merge_base = run(
        [
            "git",
            "merge-base",
            "HEAD",
            "origin/main",
        ]
    )

    baseline_is_ancestor = (
        subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                EXPECTED_BASELINE,
                "HEAD",
            ],
            text=True,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )

    status_lines = [
        line
        for line in run(
            ["git", "status", "--porcelain=v1"],
            required=False,
        ).splitlines()
        if line
    ]

    permitted_dirty = {
        " M .gitignore",
    }

    unexpected_dirty = [
        line
        for line in status_lines
        if line not in permitted_dirty
        and not line.startswith("?? analysis/governance/")
    ]

    required_file_results = {
        relative: (
            governance / relative
        ).is_file()
        for relative in REQUIRED_GOVERNANCE_FILES
    }

    program = load_yaml(
        governance / "program_registry.yaml"
    )
    assets = load_yaml(
        governance / "data_asset_registry.yaml"
    )
    stages = load_yaml(
        governance / "stage_registry.yaml"
    )
    closure = load_yaml(
        governance / "closure_requirements.yaml"
    )
    artifact = load_yaml(
        governance / "artifact_contract.yaml"
    )
    falsification = load_yaml(
        governance / "falsification_policy.yaml"
    )

    registered_assets = set(
        assets["assets"]
    )

    stage_rows = stages["stages"]
    stage_ids = [
        row["stage"]
        for row in stage_rows
    ]
    stage_states = [
        row["state"]
        for row in stage_rows
    ]

    gitignore = (
        repo / ".gitignore"
    ).read_text(encoding="utf-8")

    required_ignore_rules = [
        "__pycache__/",
        "*.py[cod]",
        "work/",
    ]

    raw_data_tracked = run(
        [
            "git",
            "ls-files",
            "data",
            "datasets",
        ],
        required=False,
    ).splitlines()

    prohibited_extensions = {
        ".jpg",
        ".jpeg",
        ".png",
        ".tif",
        ".tiff",
        ".bmp",
        ".dcm",
        ".nii",
        ".nii.gz",
    }

    tracked_prohibited_data = [
        path
        for path in raw_data_tracked
        if any(
            path.lower().endswith(extension)
            for extension in prohibited_extensions
        )
    ]

    gates = {
        "expected_branch": (
            branch == EXPECTED_BRANCH
        ),
        "origin_main_matches_frozen_baseline": (
            origin_main == EXPECTED_BASELINE
        ),
        "head_descends_from_frozen_baseline": (
            baseline_is_ancestor
        ),
        "merge_base_matches_baseline": (
            merge_base == EXPECTED_BASELINE
        ),
        "required_governance_files_exist": (
            all(required_file_results.values())
        ),
        "stage_count_exact": (
            len(stage_rows)
            == EXPECTED_STAGE_COUNT
        ),
        "stage_ids_exact": (
            stage_ids
            == list(range(EXPECTED_STAGE_COUNT))
        ),
        "all_stages_open_at_initialization": (
            all(
                state == "OPEN"
                for state in stage_states
            )
        ),
        "required_assets_registered": (
            REQUIRED_ASSETS
            <= registered_assets
        ),
        "scin_registered": (
            "scin" in registered_assets
        ),
        "no_partial_stage_state": (
            "PARTIAL"
            not in program[
                "allowed_stage_states"
            ]
        ),
        "closure_contract_complete": (
            len(
                closure["required_sections"]
            )
            == 14
        ),
        "negative_result_is_complete": bool(
            closure[
                "negative_result_is_complete"
            ]
        ),
        "falsification_required": (
            len(falsification["rules"]) >= 5
        ),
        "artifact_hash_required": bool(
            artifact[
                "artifact_requirements"
            ]["sha256_required"]
        ),
        "gitignore_hygiene": all(
            rule in gitignore
            for rule in required_ignore_rules
        ),
        "no_tracked_raw_image_data": (
            len(tracked_prohibited_data) == 0
        ),
        "unexpected_dirty_files_absent": (
            args.allow_dirty
            or len(unexpected_dirty) == 0
        ),
    }

    environment = {
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "git_version": run(
            ["git", "--version"]
        ),
        "branch": branch,
        "head": head,
        "origin_main": origin_main,
        "merge_base": merge_base,
        "cpu": capture_optional(
            ["lscpu"]
        ),
        "memory": capture_optional(
            ["free", "-h"]
        ),
        "gpu_nvidia": capture_optional(
            [
                "nvidia-smi",
                "--query-gpu="
                "name,driver_version,memory.total",
                "--format=csv,noheader",
            ]
        ),
        "gpu_rocm": capture_optional(
            ["rocminfo"]
        ),
        "environment_variables": {
            "SOURCE_DATE_EPOCH": os.environ.get(
                "SOURCE_DATE_EPOCH",
                "UNSET",
            ),
            "PYTHONHASHSEED": os.environ.get(
                "PYTHONHASHSEED",
                "UNSET",
            ),
        },
    }

    pip_freeze = run(
        [
            sys.executable,
            "-m",
            "pip",
            "freeze",
        ],
        required=False,
    )

    manifest_rows = []

    for relative in sorted(
        REQUIRED_GOVERNANCE_FILES
    ):
        path = governance / relative

        if not path.is_file():
            continue

        manifest_rows.append({
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })

    status = (
        "READY_FOR_STAGE_0_CLOSURE"
        if all(gates.values())
        else "OPEN_FAILED_GATES"
    )

    summary = {
        "stage": 0,
        "name": (
            "program_governance_and_"
            "reproducibility_foundation"
        ),
        "status": status,
        "branch": branch,
        "head": head,
        "origin_main": origin_main,
        "baseline_commit": EXPECTED_BASELINE,
        "canonical_stage_count": len(stage_rows),
        "registered_data_asset_count": len(
            registered_assets
        ),
        "scin_registered": (
            "scin" in registered_assets
        ),
        "required_assets": sorted(
            REQUIRED_ASSETS
        ),
        "gates": gates,
        "failed_gates": [
            name
            for name, passed in gates.items()
            if not passed
        ],
        "unexpected_dirty_files": (
            unexpected_dirty
        ),
        "tracked_prohibited_data": (
            tracked_prohibited_data
        ),
    }

    (output / "stage0_summary.json").write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    (output / "environment_capture.json").write_text(
        json.dumps(
            environment,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    (output / "pip_freeze.txt").write_text(
        pip_freeze + "\n",
        encoding="utf-8",
    )

    (output / "governance_manifest.json").write_text(
        json.dumps(
            manifest_rows,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    (output / "stage0_validation_report.md").write_text(
        "# TrueColor Canonical Stage 0 Validation\n\n"
        f"Status: **{status}**\n\n"
        f"- Branch: `{branch}`\n"
        f"- HEAD: `{head}`\n"
        f"- Canonical stages: `{len(stage_rows)}`\n"
        f"- Registered assets: `{len(registered_assets)}`\n"
        f"- SCIN registered: `{str('scin' in registered_assets).lower()}`\n"
        f"- Passed gates: `{sum(gates.values())}/{len(gates)}`\n"
        f"- Failed gates: `{', '.join(summary['failed_gates']) or 'none'}`\n",
        encoding="utf-8",
    )

    evidence_files = [
        output / "stage0_summary.json",
        output / "environment_capture.json",
        output / "pip_freeze.txt",
        output / "governance_manifest.json",
        output / "stage0_validation_report.md",
    ]

    evidence_manifest = []

    for path in evidence_files:
        evidence_manifest.append({
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })

    (output / "sha256_manifest.json").write_text(
        json.dumps(
            evidence_manifest,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
    )

    return 0 if all(gates.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
