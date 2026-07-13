from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


STAGE0_CLOSURE_COMMIT = (
    "c72d9dc0583be782d35078d14f64601cd26917fc"
)

EXPECTED_BRANCH = (
    "analysis/canonical-stage0-refactor"
)

REQUIRED_CLAIMS = {
    "TC-NOV-001",
    "TC-NOV-002",
    "TC-NOV-003",
    "TC-NOV-004",
    "TC-NOV-005",
    "TC-NOV-006",
}

REQUIRED_DOMAINS = {
    "skin_tissue_optical_forward_models",
    "skin_reflectance_inverse_models",
    "melanin_hemoglobin_and_scattering_identifiability",
    "spectral_reflectance_geometry_and_dimension",
    "camera_spectral_sensitivity_and_observation_operators",
    "camera_metamerism_and_spectral_reconstruction",
    "multispectral_band_selection_and_measurement_design",
    "fisher_information_and_cramer_rao_skin_imaging",
    "skin_colorimetry_ita_and_color_measurement",
    "capture_variability_white_balance_and_illumination",
    "dermatology_ai_fairness_and_skin_tone",
    "dermatology_dataset_duplicates_labels_and_quality",
    "clinical_external_validation_and_domain_shift",
    "physics_informed_clinical_image_analysis",
}


def run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )

    return completed.stdout.strip()


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(value, dict):
        raise TypeError(
            f"Expected mapping: {path}"
        )

    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "analysis/prior_art/results"
        ),
    )

    parser.add_argument(
        "--require-corpus",
        action="store_true",
    )

    args = parser.parse_args()

    root = Path("analysis/prior_art")
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)

    branch = run(
        ["git", "branch", "--show-current"]
    )

    head = run(
        ["git", "rev-parse", "HEAD"]
    )

    stage0_ancestor = (
        subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                STAGE0_CLOSURE_COMMIT,
                "HEAD",
            ],
            text=True,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )

    protocol = load_yaml(
        root
        / "protocol"
        / "stage1_protocol.yaml"
    )

    claims = load_yaml(
        root
        / "registry"
        / "novelty_claim_registry.yaml"
    )

    queries = load_yaml(
        root
        / "registry"
        / "search_query_registry.yaml"
    )

    sources = load_yaml(
        root
        / "registry"
        / "source_registry.yaml"
    )

    executions = load_yaml(
        root
        / "registry"
        / "search_execution_registry.yaml"
    )

    source_schema = json.loads(
        (
            root
            / "schemas"
            / "prior_art_source.schema.json"
        ).read_text(encoding="utf-8")
    )

    claim_ids = {
        row["claim_id"]
        for row in claims["claims"]
    }

    query_domains = {
        row["domain"]
        for row in queries["query_families"]
    }

    protocol_domains = set(
        protocol["required_search_domains"]
    )

    source_errors: list[dict[str, Any]] = []

    validator = Draft202012Validator(
        source_schema
    )

    for source in sources["sources"]:
        errors = sorted(
            validator.iter_errors(source),
            key=lambda error: list(error.path),
        )

        for error in errors:
            source_errors.append({
                "source_id": source.get(
                    "source_id",
                    "UNKNOWN",
                ),
                "path": list(error.path),
                "message": error.message,
            })

    source_ids = [
        row["source_id"]
        for row in sources["sources"]
    ]

    duplicate_source_ids = sorted({
        source_id
        for source_id in source_ids
        if source_ids.count(source_id) > 1
    })

    completed_domains = {
        row["domain"]
        for row in executions["executions"]
        if row.get("status") == "COMPLETE"
    }

    gates = {
        "expected_branch": (
            branch == EXPECTED_BRANCH
        ),
        "stage0_closure_is_ancestor": (
            stage0_ancestor
        ),
        "stage_number_correct": (
            protocol["stage"] == 1
        ),
        "stage_state_open": (
            protocol["state"] == "OPEN"
        ),
        "required_claims_registered": (
            REQUIRED_CLAIMS <= claim_ids
        ),
        "all_claims_have_kill_conditions": all(
            bool(row.get("kill_condition"))
            for row in claims["claims"]
        ),
        "required_domains_registered": (
            REQUIRED_DOMAINS
            <= protocol_domains
        ),
        "query_domains_are_registered": (
            query_domains <= protocol_domains
        ),
        "all_required_domains_have_query_families": (
            protocol_domains <= query_domains
        ),
        "query_domains_exactly_match_protocol": (
            query_domains == protocol_domains
        ),
        "query_family_domains_unique": (
            len(query_domains)
            == len(queries["query_families"])
        ),
        "source_records_schema_valid": (
            len(source_errors) == 0
        ),
        "source_ids_unique": (
            len(duplicate_source_ids) == 0
        ),
    }

    if args.require_corpus:
        gates.update({
            "source_corpus_nonempty": (
                len(sources["sources"]) > 0
            ),
            "all_domains_executed": (
                protocol_domains
                <= completed_domains
            ),
            "all_sources_extracted": all(
                row.get("extraction_status")
                in {
                    "EXTRACTED",
                    "SECOND_PASS_VALIDATED",
                    "EXCLUDED",
                }
                for row in sources["sources"]
            ),
        })

    status = (
        "READY_FOR_CORPUS_POPULATION"
        if all(gates.values())
        and not args.require_corpus
        else (
            "READY_FOR_NOVELTY_ADJUDICATION"
            if all(gates.values())
            else "OPEN_FAILED_GATES"
        )
    )

    summary = {
        "stage": 1,
        "name": (
            "prior_art_extraction_and_"
            "novelty_boundary"
        ),
        "status": status,
        "branch": branch,
        "head": head,
        "stage0_closure_commit": (
            STAGE0_CLOSURE_COMMIT
        ),
        "claim_count": len(
            claims["claims"]
        ),
        "query_family_count": len(
            queries["query_families"]
        ),
        "required_domain_count": len(
            protocol_domains
        ),
        "source_count": len(
            sources["sources"]
        ),
        "search_execution_count": len(
            executions["executions"]
        ),
        "gates": gates,
        "failed_gates": [
            name
            for name, passed in gates.items()
            if not passed
        ],
        "source_schema_errors": source_errors,
        "duplicate_source_ids": (
            duplicate_source_ids
        ),
    }

    (output / "stage1_entry_summary.json").write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    governed_files = [
        root / "protocol/stage1_protocol.yaml",
        root / "registry/novelty_claim_registry.yaml",
        root / "registry/search_query_registry.yaml",
        root / "registry/source_registry.yaml",
        root / "registry/search_execution_registry.yaml",
        root / "registry/stage1_deviation_register.yaml",
        root / "schemas/prior_art_source.schema.json",
        root / "schemas/claim_overlap.schema.json",
        root / "templates/source_record_template.yaml",
        root / "templates/claim_overlap_template.yaml",
        root / "STAGE_1_READY.yaml",
        root / "run_stage1.py",
        root / "run_stage1.sh",
    ]

    manifest = [
        {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in governed_files
        if path.is_file()
    ]

    (
        output
        / "stage1_protocol_manifest.json"
    ).write_text(
        json.dumps(
            manifest,
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
