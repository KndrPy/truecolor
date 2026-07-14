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
        "--coverage",
        required=True,
    )

    parser.add_argument(
        "--coverage-policy",
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

    coverage_path = Path(
        arguments.coverage
    ).resolve()

    coverage_policy_path = Path(
        arguments.coverage_policy
    ).resolve()

    output_directory = Path(
        arguments.output
    ).resolve()

    errors: list[str] = []

    manifest = read_json(
        manifest_path
    )

    coverage = read_json(
        coverage_path
    )

    coverage_policy = read_json(
        coverage_policy_path
    )

    queue_path = (
        output_directory
        / "corpus_disposition_queue.json"
    )

    hash_path = (
        output_directory
        / "artifact_hashes.json"
    )

    if not queue_path.is_file():
        errors.append(
            "corpus disposition queue missing"
        )

    if not hash_path.is_file():
        errors.append(
            "artifact hash manifest missing"
        )

    if errors:
        raise RuntimeError(
            "\n".join(errors)
        )

    queue = read_json(
        queue_path
    )

    pending_records = [
        record
        for record in coverage["records"]
        if record[
            "coverage_state"
        ] == "PENDING"
    ]

    tasks = queue["tasks"]

    if (
        queue[
            "pending_source_count"
        ]
        != len(pending_records)
    ):
        errors.append(
            "queue pending-source count mismatch"
        )

    if (
        queue["task_count"]
        != len(tasks)
    ):
        errors.append(
            "queue task count mismatch"
        )

    if len(tasks) != len(
        pending_records
    ):
        errors.append(
            "queue does not contain one task "
            "per pending source"
        )

    task_identities = {
        task["canonical_identity"]
        for task in tasks
    }

    pending_identities = {
        record["canonical_identity"]
        for record in pending_records
    }

    if (
        task_identities
        != pending_identities
    ):
        errors.append(
            "queue identities differ from "
            "pending coverage identities"
        )

    governed_identities = {
        member["canonical_identity"]
        for member
        in manifest["corpus"]["members"]
    }

    if not (
        task_identities
        <= governed_identities
    ):
        errors.append(
            "queue contains nongoverned identity"
        )

    allowed_roles = set(
        coverage_policy[
            "terminal_roles"
        ]
    )

    task_ids: list[str] = []

    for task_record in tasks:
        task_ids.append(
            task_record["task_id"]
        )

        task_path = (
            ROOT
            / task_record[
                "task_path"
            ]
        )

        if not task_path.is_file():
            errors.append(
                "disposition task missing: "
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
                "disposition task hash mismatch: "
                + task_record[
                    "task_path"
                ]
            )

        task = read_json(
            task_path
        )

        if (
            task[
                "task_state"
            ]
            != "PENDING_DISPOSITION"
        ):
            errors.append(
                "disposition task was "
                "prematurely advanced"
            )

        if (
            set(
                task[
                    "allowed_terminal_roles"
                ]
            )
            != allowed_roles
        ):
            errors.append(
                "task terminal roles differ "
                "from configured policy"
            )

        decision = task[
            "decision"
        ]

        populated = []

        for field, value in decision.items():
            if value is None:
                continue

            if (
                isinstance(value, str)
                and value == ""
            ):
                continue

            if (
                isinstance(
                    value,
                    (
                        list,
                        dict,
                        tuple,
                        set,
                    ),
                )
                and not value
            ):
                continue

            populated.append(field)

        if populated:
            errors.append(
                "pending task contains decision fields: "
                + ",".join(populated)
            )

        contract = task[
            "decision_contract"
        ]

        for required_flag in (
            "title_only_decision_prohibited",
            "rank_only_decision_prohibited",
            "fuzzy_identity_matching_prohibited",
            "scientific_claim_inference_prohibited",
            "terminal_role_requires_explicit_reviewer_decision",
        ):
            if (
                contract.get(
                    required_flag
                )
                is not True
            ):
                errors.append(
                    "task contract flag is not true: "
                    + required_flag
                )

    if len(task_ids) != len(
        set(task_ids)
    ):
        errors.append(
            "duplicate disposition task IDs"
        )

    hashes = read_json(
        hash_path
    )

    required_hashes = {
        queue_path.relative_to(
            ROOT
        ).as_posix()
    }

    required_hashes.update(
        task["task_path"]
        for task in tasks
    )

    if not (
        required_hashes
        <= set(hashes)
    ):
        errors.append(
            "queue or task hash entries missing"
        )

    for relative_path in required_hashes:
        path = ROOT / relative_path

        if (
            sha256_file(path)
            != hashes[
                relative_path
            ]
        ):
            errors.append(
                "queue artifact hash mismatch: "
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
        raise RuntimeError(
            "\n".join(errors)
        )

    print(
        "QUDIPI_STAGE1_DISPOSITION_QUEUE_VALIDATION=PASS"
    )

    print(
        "pending_source_count="
        f"{len(pending_records)}"
    )

    print(
        f"task_count={len(tasks)}"
    )

    print(
        "completed_task_count=0"
    )

    print(
        "stage1_state=OPEN"
    )


if __name__ == "__main__":
    main()
