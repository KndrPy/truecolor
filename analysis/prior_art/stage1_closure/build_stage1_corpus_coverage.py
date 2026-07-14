from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Derive role-aware Stage 1 corpus coverage "
            "from a compiled research-pack instance."
        )
    )

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


def write_json(
    path: Path,
    value: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def stable_id(
    prefix: str,
    *values: str,
) -> str:
    material = "\x1f".join(values)

    suffix = hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()[:16]

    return f"{prefix}-{suffix}"


def normalize_scalar(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, bool):
        return (
            "true"
            if value
            else "false"
        )

    return (
        str(value)
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )


def first_metadata_value(
    metadata: dict[str, Any],
    fields: list[str],
) -> tuple[str | None, Any]:
    normalized_lookup = {
        str(key).strip().lower():
            value
        for key, value in metadata.items()
    }

    for field in fields:
        normalized_field = (
            field.strip().lower()
        )

        if normalized_field in normalized_lookup:
            value = normalized_lookup[
                normalized_field
            ]

            if value not in {
                None,
                "",
            }:
                return field, value

    return None, None


def explicit_policy_match(
    metadata: dict[str, Any],
    mappings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for mapping in mappings:
        metadata_fields = list(
            mapping.get(
                "metadata_fields",
                [],
            )
        )

        matched_field, raw_value = (
            first_metadata_value(
                metadata,
                metadata_fields,
            )
        )

        if matched_field is None:
            continue

        normalized_value = (
            normalize_scalar(raw_value)
        )

        accepted_values = {
            normalize_scalar(value)
            for value in mapping.get(
                "accepted_values",
                [],
            )
        }

        if (
            normalized_value
            not in accepted_values
        ):
            continue

        reason_field, reason_value = (
            first_metadata_value(
                metadata,
                list(
                    mapping.get(
                        "reason_fields",
                        [],
                    )
                ),
            )
        )

        reason_required = bool(
            mapping.get(
                "reason_required",
                False,
            )
        )

        reason_text = (
            str(reason_value).strip()
            if reason_value not in {
                None,
                "",
            }
            else None
        )

        if (
            reason_required
            and not reason_text
        ):
            return {
                "role": None,
                "state": "INVALID",
                "reason": None,
                "derivation": {
                    "matched_field":
                        matched_field,
                    "matched_value":
                        raw_value,
                    "reason_field":
                        reason_field,
                    "failure":
                        "required_reason_missing",
                },
            }

        return {
            "role": mapping["role"],
            "state": "TERMINAL",
            "reason": reason_text,
            "derivation": {
                "matched_field":
                    matched_field,
                "matched_value":
                    raw_value,
                "reason_field":
                    reason_field,
                "mapping_role":
                    mapping["role"],
            },
        }

    return None


def rebuild_artifact_hashes(
    output_directory: Path,
) -> None:
    hash_path = (
        output_directory
        / "artifact_hashes.json"
    )

    hashes: dict[str, str] = {}

    for path in sorted(
        output_directory.rglob(
            "*.json"
        )
    ):
        if path == hash_path:
            continue

        hashes[
            path.relative_to(
                ROOT
            ).as_posix()
        ] = sha256_file(path)

    write_json(
        hash_path,
        hashes,
    )


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

    manifest = read_json(
        manifest_path
    )

    policy = read_json(
        policy_path
    )

    corpus_members = (
        manifest.get(
            "corpus",
            {},
        ).get(
            "members",
            [],
        )
    )

    evidence_records = (
        manifest.get(
            "evidence_records",
            [],
        )
    )

    evidence_by_identity = {
        record["canonical_identity"]:
            record
        for record in evidence_records
    }

    terminal_roles = set(
        policy.get(
            "terminal_roles",
            [],
        )
    )

    pending_role = policy[
        "pending_role"
    ]

    evidence_role = policy[
        "evidence_record_role"
    ]

    mappings = list(
        policy.get(
            "explicit_role_mappings",
            [],
        )
    )

    coverage_records: list[
        dict[str, Any]
    ] = []

    invalid_records: list[
        dict[str, Any]
    ] = []

    for member in corpus_members:
        canonical_identity = member[
            "canonical_identity"
        ]

        evidence = evidence_by_identity.get(
            canonical_identity
        )

        if evidence is not None:
            coverage = {
                "role": evidence_role,
                "state": "TERMINAL",
                "reason": (
                    "Configured scientific evidence "
                    "record exists."
                ),
                "derivation": {
                    "method":
                        "evidence_record_membership",
                    "evidence_record_id":
                        evidence[
                            "evidence_record_id"
                        ],
                },
            }
        else:
            metadata = member.get(
                "source_metadata",
                {},
            )

            coverage = explicit_policy_match(
                metadata,
                mappings,
            )

            if coverage is None:
                coverage = {
                    "role": pending_role,
                    "state": "PENDING",
                    "reason": None,
                    "derivation": {
                        "method":
                            "no_explicit_terminal_"
                            "disposition_found",
                    },
                }

        coverage_record = {
            "coverage_record_id":
                stable_id(
                    "COVERAGE",
                    canonical_identity,
                ),
            "corpus_member_id":
                member[
                    "corpus_member_id"
                ],
            "canonical_identity":
                canonical_identity,
            "coverage_role":
                coverage["role"],
            "coverage_state":
                coverage["state"],
            "coverage_reason":
                coverage["reason"],
            "derivation":
                coverage["derivation"],
            "evidence_record_id": (
                evidence[
                    "evidence_record_id"
                ]
                if evidence is not None
                else None
            ),
            "source_metadata":
                member.get(
                    "source_metadata",
                    {},
                ),
        }

        coverage_records.append(
            coverage_record
        )

        if coverage[
            "state"
        ] == "INVALID":
            invalid_records.append(
                coverage_record
            )

    terminal_records = [
        record
        for record in coverage_records
        if (
            record[
                "coverage_state"
            ]
            == "TERMINAL"
            and record[
                "coverage_role"
            ]
            in terminal_roles
        )
    ]

    pending_records = [
        record
        for record in coverage_records
        if record[
            "coverage_state"
        ] == "PENDING"
    ]

    role_counts: dict[str, int] = {}

    for record in coverage_records:
        role = (
            record[
                "coverage_role"
            ]
            or "INVALID"
        )

        role_counts[role] = (
            role_counts.get(
                role,
                0,
            )
            + 1
        )

    coverage_register_path = (
        output_directory
        / "corpus_coverage_register.json"
    )

    coverage_gap_path = (
        output_directory
        / "corpus_coverage_gap_report.json"
    )

    write_json(
        coverage_register_path,
        {
            "register_schema":
                "qudipi.stage1.corpus-coverage-register",
            "register_version": 1,
            "policy_id":
                policy["policy_id"],
            "policy_path":
                policy_path.relative_to(
                    ROOT
                ).as_posix(),
            "policy_sha256":
                sha256_file(
                    policy_path
                ),
            "configured_governed_source_count":
                len(corpus_members),
            "terminal_coverage_count":
                len(terminal_records),
            "pending_disposition_count":
                len(pending_records),
            "invalid_disposition_count":
                len(invalid_records),
            "role_counts":
                role_counts,
            "records":
                coverage_records,
        },
    )

    write_json(
        coverage_gap_path,
        {
            "report_schema":
                "qudipi.stage1.corpus-coverage-gap-report",
            "report_version": 1,
            "policy_id":
                policy["policy_id"],
            "stage_state": (
                "COMPLETE"
                if (
                    not pending_records
                    and not invalid_records
                )
                else "OPEN"
            ),
            "configured_governed_source_count":
                len(corpus_members),
            "terminal_coverage_count":
                len(terminal_records),
            "pending_disposition_count":
                len(pending_records),
            "invalid_disposition_count":
                len(invalid_records),
            "pending_corpus_members": [
                {
                    "coverage_record_id":
                        record[
                            "coverage_record_id"
                        ],
                    "corpus_member_id":
                        record[
                            "corpus_member_id"
                        ],
                    "canonical_identity":
                        record[
                            "canonical_identity"
                        ],
                    "coverage_role":
                        record[
                            "coverage_role"
                        ],
                }
                for record in pending_records
            ],
            "invalid_corpus_members": [
                {
                    "coverage_record_id":
                        record[
                            "coverage_record_id"
                        ],
                    "corpus_member_id":
                        record[
                            "corpus_member_id"
                        ],
                    "canonical_identity":
                        record[
                            "canonical_identity"
                        ],
                    "derivation":
                        record[
                            "derivation"
                        ],
                }
                for record in invalid_records
            ],
        },
    )

    stage_gap_path = (
        output_directory
        / "stage1_gap_report.json"
    )

    stage_gap = read_json(
        stage_gap_path
    )

    blockers = [
        blocker
        for blocker
        in stage_gap.get(
            "remaining_blockers",
            [],
        )
        if blocker
        != "governed_corpus_evidence_coverage"
    ]

    if pending_records:
        blockers.append(
            "governed_corpus_terminal_disposition"
        )

    if invalid_records:
        blockers.append(
            "invalid_corpus_dispositions"
        )

    stage_gap[
        "remaining_blockers"
    ] = list(
        dict.fromkeys(blockers)
    )

    stage_gap[
        "corpus_coverage_policy_id"
    ] = policy["policy_id"]

    stage_gap[
        "terminal_coverage_count"
    ] = len(terminal_records)

    stage_gap[
        "pending_corpus_disposition_count"
    ] = len(pending_records)

    stage_gap[
        "invalid_corpus_disposition_count"
    ] = len(invalid_records)

    stage_gap[
        "full_extraction_is_not_required_for_all_governed_sources"
    ] = True

    write_json(
        stage_gap_path,
        stage_gap,
    )

    rebuild_artifact_hashes(
        output_directory
    )

    print(
        "QUDIPI_STAGE1_CORPUS_COVERAGE_BUILD=PASS"
    )

    print(
        "configured_governed_source_count="
        f"{len(corpus_members)}"
    )

    print(
        "terminal_coverage_count="
        f"{len(terminal_records)}"
    )

    print(
        "pending_disposition_count="
        f"{len(pending_records)}"
    )

    print(
        "invalid_disposition_count="
        f"{len(invalid_records)}"
    )

    for role, count in sorted(
        role_counts.items()
    ):
        print(
            f"coverage_role.{role}={count}"
        )

    return 0


if __name__ == "__main__":
    main()
