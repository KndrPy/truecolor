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
            "Build a generic human-review queue for "
            "unresolved Stage 1 corpus dispositions."
        )
    )

    parser.add_argument(
        "--manifest",
        required=True,
    )

    parser.add_argument(
        "--coverage",
        required=True,
    )

    parser.add_argument(
        "--coverage-policy",
        required=True,
    )

    parser.add_argument(
        "--disposition-evidence",
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


def rebuild_hashes(
    output_directory: Path,
) -> None:
    hash_path = (
        output_directory
        / "artifact_hashes.json"
    )

    hashes: dict[str, str] = {}

    for path in sorted(
        output_directory.rglob("*.json")
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


def role_contracts(
    policy: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    reason_required_roles = {
        mapping["role"]
        for mapping
        in policy.get(
            "explicit_role_mappings",
            [],
        )
        if mapping.get(
            "reason_required",
            False,
        )
    }

    contracts: dict[
        str,
        dict[str, Any],
    ] = {}

    for role in policy[
        "terminal_roles"
    ]:
        contracts[role] = {
            "reason_required":
                role in reason_required_roles,
            "evidence_basis_required":
                True,
            "reviewer_attestation_required":
                True,
        }

    return contracts


def main() -> None:
    arguments = parse_arguments()

    manifest_path = Path(
        arguments.manifest
    ).resolve()

    coverage_path = Path(
        arguments.coverage
    ).resolve()

    coverage_policy_path = Path(
        arguments.coverage_policy
    ).resolve()

    disposition_evidence_path = Path(
        arguments.disposition_evidence
    ).resolve()

    output_directory = Path(
        arguments.output
    ).resolve()

    task_directory = (
        output_directory
        / "disposition_tasks"
    )

    task_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    for path in task_directory.glob(
        "*.json"
    ):
        path.unlink()

    manifest = read_json(
        manifest_path
    )

    coverage = read_json(
        coverage_path
    )

    coverage_policy = read_json(
        coverage_policy_path
    )

    disposition_evidence = read_json(
        disposition_evidence_path
    )

    governed_by_identity = {
        member["canonical_identity"]:
            member
        for member
        in manifest["corpus"]["members"]
    }

    observations_by_identity: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    for observation in disposition_evidence.get(
        "observations",
        [],
    ):
        identity = observation[
            "canonical_identity"
        ]

        observations_by_identity.setdefault(
            identity,
            [],
        ).append(
            observation
        )

    allowed_roles = list(
        coverage_policy[
            "terminal_roles"
        ]
    )

    contracts = role_contracts(
        coverage_policy
    )

    pending_records = [
        record
        for record in coverage["records"]
        if record[
            "coverage_state"
        ] == "PENDING"
    ]

    task_records: list[
        dict[str, Any]
    ] = []

    for record in sorted(
        pending_records,
        key=lambda item: item[
            "canonical_identity"
        ],
    ):
        identity = record[
            "canonical_identity"
        ]

        member = governed_by_identity[
            identity
        ]

        observations = sorted(
            observations_by_identity.get(
                identity,
                [],
            ),
            key=lambda item: (
                item.get(
                    "source_precedence",
                    0,
                ),
                item.get(
                    "source_id",
                    "",
                ),
                item.get(
                    "source_record_index",
                    0,
                ),
            ),
        )

        task_id = stable_id(
            "DISPOSITION-TASK",
            identity,
        )

        task = {
            "task_schema":
                "qudipi.stage1.corpus-disposition-task",
            "task_version": 1,
            "task_id": task_id,
            "task_state":
                "PENDING_DISPOSITION",
            "corpus_member_id":
                record[
                    "corpus_member_id"
                ],
            "canonical_identity":
                identity,
            "current_coverage_state":
                record[
                    "coverage_state"
                ],
            "current_coverage_role":
                record[
                    "coverage_role"
                ],
            "source_metadata":
                member.get(
                    "source_metadata",
                    {},
                ),
            "existing_disposition_observations":
                observations,
            "allowed_terminal_roles":
                allowed_roles,
            "decision_contract": {
                "role_contracts":
                    contracts,
                "title_only_decision_prohibited":
                    True,
                "rank_only_decision_prohibited":
                    True,
                "fuzzy_identity_matching_prohibited":
                    True,
                "scientific_claim_inference_prohibited":
                    True,
                "terminal_role_requires_explicit_reviewer_decision":
                    True,
            },
            "decision": {
                "selected_terminal_role":
                    None,
                "decision_reason":
                    None,
                "evidence_basis": [],
                "reviewer": None,
                "reviewed_at": None,
                "reviewer_attestation":
                    None,
            },
        }

        task_path = (
            task_directory
            / (
                task_id.lower()
                .replace("-", "_")
                + ".json"
            )
        )

        write_json(
            task_path,
            task,
        )

        task_records.append(
            {
                "task_id":
                    task_id,
                "task_state":
                    task[
                        "task_state"
                    ],
                "corpus_member_id":
                    task[
                        "corpus_member_id"
                    ],
                "canonical_identity":
                    identity,
                "existing_observation_count":
                    len(observations),
                "task_path":
                    task_path.relative_to(
                        ROOT
                    ).as_posix(),
                "task_sha256":
                    sha256_file(
                        task_path
                    ),
            }
        )

    queue_path = (
        output_directory
        / "corpus_disposition_queue.json"
    )

    write_json(
        queue_path,
        {
            "queue_schema":
                "qudipi.stage1.corpus-disposition-queue",
            "queue_version": 1,
            "manifest_path":
                manifest_path.relative_to(
                    ROOT
                ).as_posix(),
            "manifest_sha256":
                sha256_file(
                    manifest_path
                ),
            "coverage_path":
                coverage_path.relative_to(
                    ROOT
                ).as_posix(),
            "coverage_sha256":
                sha256_file(
                    coverage_path
                ),
            "coverage_policy_path":
                coverage_policy_path.relative_to(
                    ROOT
                ).as_posix(),
            "coverage_policy_sha256":
                sha256_file(
                    coverage_policy_path
                ),
            "disposition_evidence_path":
                disposition_evidence_path.relative_to(
                    ROOT
                ).as_posix(),
            "disposition_evidence_sha256":
                sha256_file(
                    disposition_evidence_path
                ),
            "pending_source_count":
                len(pending_records),
            "task_count":
                len(task_records),
            "completed_task_count": 0,
            "queue_state": (
                "READY"
                if task_records
                else "EMPTY"
            ),
            "tasks":
                task_records,
        },
    )

    stage_gap_path = (
        output_directory
        / "stage1_gap_report.json"
    )

    stage_gap = read_json(
        stage_gap_path
    )

    stage_gap[
        "corpus_disposition_queue_path"
    ] = queue_path.relative_to(
        ROOT
    ).as_posix()

    stage_gap[
        "pending_corpus_disposition_task_count"
    ] = len(task_records)

    blockers = list(
        stage_gap.get(
            "remaining_blockers",
            [],
        )
    )

    if (
        task_records
        and (
            "governed_corpus_terminal_disposition"
            not in blockers
        )
    ):
        blockers.append(
            "governed_corpus_terminal_disposition"
        )

    stage_gap[
        "remaining_blockers"
    ] = blockers

    write_json(
        stage_gap_path,
        stage_gap,
    )

    rebuild_hashes(
        output_directory
    )

    print(
        "QUDIPI_STAGE1_DISPOSITION_QUEUE_BUILD=PASS"
    )

    print(
        "pending_source_count="
        f"{len(pending_records)}"
    )

    print(
        "task_count="
        f"{len(task_records)}"
    )

    print(
        "completed_task_count=0"
    )

    print(
        "queue_state="
        + (
            "READY"
            if task_records
            else "EMPTY"
        )
    )


if __name__ == "__main__":
    main()
