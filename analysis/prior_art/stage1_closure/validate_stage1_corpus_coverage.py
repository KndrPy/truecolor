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
        "--policy",
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


def main() -> int:
    arguments = parse_arguments()

    manifest_path = Path(
        arguments.manifest
    ).resolve()

    policy_path = Path(
        arguments.policy
    ).resolve()

    output_directory = Path(
        arguments.output
    ).resolve()

    errors: list[str] = []

    manifest = read_json(
        manifest_path
    )

    policy = read_json(
        policy_path
    )

    coverage_path = (
        output_directory
        / "corpus_coverage_register.json"
    )

    gap_path = (
        output_directory
        / "corpus_coverage_gap_report.json"
    )

    stage_gap_path = (
        output_directory
        / "stage1_gap_report.json"
    )

    hash_path = (
        output_directory
        / "artifact_hashes.json"
    )

    for path in (
        coverage_path,
        gap_path,
        stage_gap_path,
        hash_path,
    ):
        if not path.is_file():
            errors.append(
                "missing artifact: "
                + path.relative_to(
                    ROOT
                ).as_posix()
            )

    if errors:
        print(
            "QUDIPI_STAGE1_CORPUS_COVERAGE_VALIDATION=FAIL"
        )

        for error in errors:
            print(f"ERROR  {error}")

        return 1

    coverage = read_json(
        coverage_path
    )

    gap = read_json(
        gap_path
    )

    stage_gap = read_json(
        stage_gap_path
    )

    corpus_members = (
        manifest["corpus"]["members"]
    )

    evidence_records = (
        manifest["evidence_records"]
    )

    terminal_roles = set(
        policy["terminal_roles"]
    )

    evidence_role = policy[
        "evidence_record_role"
    ]

    records = coverage["records"]

    if (
        coverage[
            "configured_governed_source_count"
        ]
        != len(corpus_members)
    ):
        errors.append(
            "coverage source count differs "
            "from compiled manifest"
        )

    if len(records) != len(
        corpus_members
    ):
        errors.append(
            "coverage register does not contain "
            "one record per governed source"
        )

    canonical_identities = [
        record[
            "canonical_identity"
        ]
        for record in records
    ]

    if len(canonical_identities) != len(
        set(canonical_identities)
    ):
        errors.append(
            "coverage register contains duplicate "
            "canonical identities"
        )

    evidence_by_identity = {
        record["canonical_identity"]:
            record
        for record in evidence_records
    }

    for record in records:
        identity = record[
            "canonical_identity"
        ]

        state = record[
            "coverage_state"
        ]

        role = record[
            "coverage_role"
        ]

        evidence = evidence_by_identity.get(
            identity
        )

        if evidence is not None:
            if role != evidence_role:
                errors.append(
                    "evidence-covered source lacks "
                    "configured evidence role: "
                    + identity
                )

            if (
                record[
                    "evidence_record_id"
                ]
                != evidence[
                    "evidence_record_id"
                ]
            ):
                errors.append(
                    "coverage evidence identity mismatch: "
                    + identity
                )

        if state == "TERMINAL":
            if role not in terminal_roles:
                errors.append(
                    "terminal record has nonterminal role: "
                    + identity
                )

        if (
            role
            in {
                "EXCLUDED_WITH_REASON",
                "TERMINAL_SOURCE_UNAVAILABLE",
            }
            and not record.get(
                "coverage_reason"
            )
        ):
            errors.append(
                "reason-required terminal role "
                "has no reason: "
                + identity
            )

    pending_count = sum(
        1
        for record in records
        if record[
            "coverage_state"
        ] == "PENDING"
    )

    invalid_count = sum(
        1
        for record in records
        if record[
            "coverage_state"
        ] == "INVALID"
    )

    if (
        pending_count
        != coverage[
            "pending_disposition_count"
        ]
    ):
        errors.append(
            "pending coverage count mismatch"
        )

    if (
        invalid_count
        != coverage[
            "invalid_disposition_count"
        ]
    ):
        errors.append(
            "invalid coverage count mismatch"
        )

    if (
        "governed_corpus_evidence_coverage"
        in stage_gap[
            "remaining_blockers"
        ]
    ):
        errors.append(
            "obsolete full-evidence coverage blocker remains"
        )

    if (
        pending_count
        and (
            "governed_corpus_terminal_disposition"
            not in stage_gap[
                "remaining_blockers"
            ]
        )
    ):
        errors.append(
            "pending corpus dispositions lack blocker"
        )

    if (
        stage_gap.get(
            "full_extraction_is_not_required_for_all_governed_sources"
        )
        is not True
    ):
        errors.append(
            "role-aware extraction boundary not recorded"
        )

    if (
        gap[
            "pending_disposition_count"
        ]
        != pending_count
    ):
        errors.append(
            "coverage gap pending count mismatch"
        )

    hashes = read_json(
        hash_path
    )

    for relative_path, expected in (
        hashes.items()
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

    if (
        output_directory
        / "STAGE_01_CLOSED.json"
    ).exists():
        errors.append(
            "Stage 1 closure marker exists prematurely"
        )

    if errors:
        print(
            "QUDIPI_STAGE1_CORPUS_COVERAGE_VALIDATION=FAIL"
        )

        for error in errors:
            print(f"ERROR  {error}")

        return 1

    print(
        "QUDIPI_STAGE1_CORPUS_COVERAGE_VALIDATION=PASS"
    )

    print(
        "configured_governed_source_count="
        f"{len(corpus_members)}"
    )

    print(
        "terminal_coverage_count="
        f"{coverage['terminal_coverage_count']}"
    )

    print(
        "pending_disposition_count="
        f"{pending_count}"
    )

    print(
        "invalid_disposition_count="
        f"{invalid_count}"
    )

    print("stage1_state=OPEN")

    return 0


if __name__ == "__main__":
    main()
