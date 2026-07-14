from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--manifest",
        required=True,
    )

    parser.add_argument(
        "--output",
        required=True,
    )

    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def main() -> None:
    arguments = parse_arguments()

    manifest_path = Path(
        arguments.manifest
    ).resolve()

    output_directory = Path(
        arguments.output
    ).resolve()

    manifest = read_json(
        manifest_path
    )

    errors = []

    required_artifacts = [
        "source_register.json",
        "evidence_register.json",
        "unsupported_field_register.json",
        "pending_field_register.json",
        "review_register.json",
        "claim_matrix_register.json",
        "novelty_kill_register.json",
        "synthesis_register.json",
        "stage1_gap_report.json",
        "stage1_generic_build_run.json",
        "artifact_hashes.json",
    ]

    for name in required_artifacts:
        path = output_directory / name

        if not path.is_file():
            errors.append(
                f"missing artifact: {name}"
            )

    if errors:
        raise RuntimeError(
            "\n".join(errors)
        )

    source_register = read_json(
        output_directory
        / "source_register.json"
    )

    evidence_register = read_json(
        output_directory
        / "evidence_register.json"
    )

    review_register = read_json(
        output_directory
        / "review_register.json"
    )

    matrix_register = read_json(
        output_directory
        / "claim_matrix_register.json"
    )

    kill_register = read_json(
        output_directory
        / "novelty_kill_register.json"
    )

    gap_report = read_json(
        output_directory
        / "stage1_gap_report.json"
    )

    run_manifest = read_json(
        output_directory
        / "stage1_generic_build_run.json"
    )

    configured_corpus_count = len(
        manifest["corpus"]["members"]
    )

    configured_evidence_count = len(
        manifest["evidence_records"]
    )

    configured_claim_count = len(
        manifest["claims"]
    )

    if (
        source_register[
            "configured_source_count"
        ]
        != configured_corpus_count
    ):
        errors.append(
            "source count differs from compiled manifest"
        )

    if (
        evidence_register[
            "configured_record_count"
        ]
        != configured_evidence_count
    ):
        errors.append(
            "evidence count differs from compiled manifest"
        )

    if (
        matrix_register[
            "configured_claim_count"
        ]
        != configured_claim_count
    ):
        errors.append(
            "matrix claim count differs from compiled manifest"
        )

    if (
        matrix_register[
            "matrix_count"
        ]
        != configured_claim_count
    ):
        errors.append(
            "one matrix was not generated per configured claim"
        )

    if (
        kill_register[
            "configured_decision_count"
        ]
        != configured_claim_count
    ):
        errors.append(
            "one kill decision was not generated per configured claim"
        )

    matrix_claim_ids = {
        record["claim_id"]
        for record
        in matrix_register["matrices"]
    }

    configured_claim_ids = {
        claim["claim_id"]
        for claim
        in manifest["claims"]
    }

    if (
        matrix_claim_ids
        != configured_claim_ids
    ):
        errors.append(
            "matrix claim identities differ from configured claims"
        )

    evidence_ids = {
        record[
            "evidence_record_id"
        ]
        for record
        in evidence_register[
            "records"
        ]
    }

    for task_record in review_register[
        "tasks"
    ]:
        task_path = (
            ROOT
            / task_record["task_path"]
        )

        if not task_path.is_file():
            errors.append(
                "review task missing: "
                + task_record[
                    "task_path"
                ]
            )
            continue

        if (
            sha256_file(task_path)
            != task_record[
                "task_sha256"
            ]
        ):
            errors.append(
                "review task hash mismatch: "
                + task_record[
                    "task_path"
                ]
            )

        task = read_json(task_path)

        if (
            task["evidence_record_id"]
            not in evidence_ids
        ):
            errors.append(
                "review task references unknown evidence record"
            )

        if (
            task["task_state"]
            != "PENDING_REVIEW"
        ):
            errors.append(
                "review task was prematurely completed"
            )

    for matrix_record in matrix_register[
        "matrices"
    ]:
        matrix_path = (
            ROOT
            / matrix_record[
                "matrix_path"
            ]
        )

        if not matrix_path.is_file():
            errors.append(
                "matrix missing: "
                + matrix_record[
                    "matrix_path"
                ]
            )
            continue

        if (
            sha256_file(matrix_path)
            != matrix_record[
                "matrix_sha256"
            ]
        ):
            errors.append(
                "matrix hash mismatch: "
                + matrix_record[
                    "matrix_path"
                ]
            )

        matrix = read_json(
            matrix_path
        )

        for row in matrix["rows"]:
            if (
                row[
                    "evidence_record_id"
                ]
                not in evidence_ids
            ):
                errors.append(
                    "matrix references unknown evidence record"
                )

    if run_manifest.get(
        "status"
    ) != "PASS":
        errors.append(
            "generic build run is not PASS"
        )

    if gap_report.get(
        "stage_state"
    ) != "OPEN":
        errors.append(
            "Stage 1 must remain OPEN"
        )

    if gap_report.get(
        "closure_marker_emitted"
    ) is not False:
        errors.append(
            "closure marker state is invalid"
        )

    if (
        output_directory
        / "STAGE_01_CLOSED.json"
    ).exists():
        errors.append(
            "Stage 1 closure marker exists prematurely"
        )

    hash_manifest = read_json(
        output_directory
        / "artifact_hashes.json"
    )

    for relative_path, expected in (
        hash_manifest.items()
    ):
        path = ROOT / relative_path

        if not path.is_file():
            errors.append(
                "hashed artifact missing: "
                + relative_path
            )
            continue

        if sha256_file(path) != expected:
            errors.append(
                "artifact hash mismatch: "
                + relative_path
            )

    if errors:
        raise RuntimeError(
            "\n".join(errors)
        )

    print(
        "QUDIPI_STAGE1_GENERIC_VALIDATION=PASS"
    )

    print(
        "configured_governed_source_count="
        f"{configured_corpus_count}"
    )

    print(
        "configured_evidence_record_count="
        f"{configured_evidence_count}"
    )

    print(
        "configured_claim_count="
        f"{configured_claim_count}"
    )

    print(
        "derived_review_task_count="
        f"{review_register['pending_task_count']}"
    )

    print(
        "derived_matrix_count="
        f"{matrix_register['matrix_count']}"
    )

    print("stage1_state=OPEN")


if __name__ == "__main__":
    main()
