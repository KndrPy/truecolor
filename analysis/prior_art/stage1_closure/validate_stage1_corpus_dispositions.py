from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--manifest",
        required=True,
    )

    parser.add_argument(
        "--coverage",
        required=True,
    )

    parser.add_argument(
        "--source-config",
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
    args = arguments()

    manifest_path = Path(
        args.manifest
    ).resolve()

    coverage_path = Path(
        args.coverage
    ).resolve()

    source_config_path = Path(
        args.source_config
    ).resolve()

    output_directory = Path(
        args.output
    ).resolve()

    errors: list[str] = []

    manifest = read_json(
        manifest_path
    )

    coverage = read_json(
        coverage_path
    )

    source_config = read_json(
        source_config_path
    )

    required_paths = [
        output_directory
        / "corpus_disposition_evidence_register.json",
        output_directory
        / "corpus_disposition_reconciliation_report.json",
        output_directory
        / "corpus_disposition_conflict_report.json",
        output_directory
        / "corpus_disposition_unmapped_report.json",
        output_directory
        / "stage1_gap_report.json",
        output_directory
        / "artifact_hashes.json",
    ]

    for path in required_paths:
        if not path.is_file():
            errors.append(
                "missing disposition artifact: "
                + path.relative_to(
                    ROOT
                ).as_posix()
            )

    if errors:
        print(
            "QUDIPI_STAGE1_DISPOSITION_VALIDATION=FAIL"
        )

        for error in errors:
            print(f"ERROR  {error}")

        return 1

    evidence = read_json(
        required_paths[0]
    )

    report = read_json(
        required_paths[1]
    )

    conflicts = read_json(
        required_paths[2]
    )

    unmapped = read_json(
        required_paths[3]
    )

    stage_gap = read_json(
        required_paths[4]
    )

    governed_identities = {
        member["canonical_identity"]
        for member
        in manifest["corpus"]["members"]
    }

    coverage_records = (
        coverage["records"]
    )

    coverage_identities = {
        record["canonical_identity"]
        for record in coverage_records
    }

    if (
        governed_identities
        != coverage_identities
    ):
        errors.append(
            "coverage identities differ from "
            "compiled governed corpus"
        )

    if (
        report[
            "configured_governed_source_count"
        ]
        != len(governed_identities)
    ):
        errors.append(
            "reconciliation source count mismatch"
        )

    terminal_count = sum(
        1
        for record in coverage_records
        if record[
            "coverage_state"
        ]
        == "TERMINAL"
    )

    pending_count = sum(
        1
        for record in coverage_records
        if record[
            "coverage_state"
        ]
        == "PENDING"
    )

    if (
        terminal_count
        != report[
            "terminal_coverage_count"
        ]
    ):
        errors.append(
            "terminal reconciliation count mismatch"
        )

    if (
        pending_count
        != report[
            "pending_disposition_count"
        ]
    ):
        errors.append(
            "pending reconciliation count mismatch"
        )

    observations = evidence[
        "observations"
    ]

    observation_ids = [
        item["observation_id"]
        for item in observations
    ]

    if len(observation_ids) != len(
        set(observation_ids)
    ):
        errors.append(
            "duplicate disposition observation IDs"
        )

    observation_by_id = {
        item["observation_id"]:
            item
        for item in observations
    }

    for record in coverage_records:
        derivation = record.get(
            "derivation",
            {},
        )

        if (
            derivation.get("method")
            != (
                "explicit_existing_"
                "artifact_disposition"
            )
        ):
            continue

        observation_id = derivation.get(
            "observation_id"
        )

        if observation_id not in (
            observation_by_id
        ):
            errors.append(
                "terminal disposition lacks registered "
                "evidence observation: "
                + record[
                    "canonical_identity"
                ]
            )
            continue

        observation = observation_by_id[
            observation_id
        ]

        if (
            observation[
                "observation_state"
            ]
            != "MAPPED"
        ):
            errors.append(
                "terminal disposition uses nonmapped "
                "observation"
            )

        if (
            record["coverage_role"]
            != observation["mapped_role"]
        ):
            errors.append(
                "terminal role differs from mapped "
                "disposition observation"
            )

    if (
        conflicts["conflict_count"]
        and (
            "conflicting_corpus_dispositions"
            not in stage_gap[
                "remaining_blockers"
            ]
        )
    ):
        errors.append(
            "conflicts exist without Stage 1 blocker"
        )

    if (
        unmapped["identity_count"]
        and (
            "unmapped_explicit_corpus_dispositions"
            not in stage_gap[
                "remaining_blockers"
            ]
        )
    ):
        errors.append(
            "unmapped explicit dispositions exist "
            "without Stage 1 blocker"
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
            "pending dispositions exist without "
            "Stage 1 blocker"
        )

    if (
        source_config[
            "identity_policy"
        ][
            "title_matching_prohibited"
        ]
        is not True
    ):
        errors.append(
            "title matching is not prohibited"
        )

    if (
        source_config[
            "identity_policy"
        ][
            "fuzzy_matching_prohibited"
        ]
        is not True
    ):
        errors.append(
            "fuzzy matching is not prohibited"
        )

    hashes = read_json(
        output_directory
        / "artifact_hashes.json"
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
            "QUDIPI_STAGE1_DISPOSITION_VALIDATION=FAIL"
        )

        for error in errors:
            print(f"ERROR  {error}")

        return 1

    print(
        "QUDIPI_STAGE1_DISPOSITION_VALIDATION=PASS"
    )

    print(
        "configured_governed_source_count="
        f"{len(governed_identities)}"
    )

    print(
        "terminal_coverage_count="
        f"{terminal_count}"
    )

    print(
        "pending_disposition_count="
        f"{pending_count}"
    )

    print(
        "conflict_count="
        f"{conflicts['conflict_count']}"
    )

    print(
        "unmapped_identity_count="
        f"{unmapped['identity_count']}"
    )

    print("stage1_state=OPEN")

    return 0


if __name__ == "__main__":
    main()
