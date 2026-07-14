from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
STAGE1 = ROOT / "artifacts" / "stage_01"

QUEUE_PATH = (
    STAGE1 / "review_work_queue.json"
)

HASH_PATH = (
    STAGE1 / "review_task_hashes.json"
)

EXPECTED_PRIMARY_TASK_COUNT = 1
EXPECTED_SECOND_REVIEW_TASK_COUNT = 5
EXPECTED_TOTAL_TASK_COUNT = 6


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def main() -> int:
    errors: list[str] = []

    if not QUEUE_PATH.is_file():
        errors.append(
            "review_work_queue.json missing"
        )

    if not HASH_PATH.is_file():
        errors.append(
            "review_task_hashes.json missing"
        )

    if errors:
        print(
            "QUDIPI_STAGE1_REVIEW_QUEUE_VALIDATION=FAIL"
        )

        for error in errors:
            print(f"ERROR  {error}")

        return 1

    queue = read_json(QUEUE_PATH)
    hashes = read_json(HASH_PATH)

    tasks = queue.get("tasks", [])

    if queue.get("queue_state") != "READY":
        errors.append(
            "review queue state is not READY"
        )

    if queue.get(
        "construction_errors"
    ) != []:
        errors.append(
            "review queue contains construction errors"
        )

    if (
        queue.get("task_count")
        != EXPECTED_TOTAL_TASK_COUNT
    ):
        errors.append(
            "review queue must contain six tasks"
        )

    if (
        queue.get(
            "primary_task_count"
        )
        != EXPECTED_PRIMARY_TASK_COUNT
    ):
        errors.append(
            "review queue must contain one "
            "primary task"
        )

    if (
        queue.get(
            "second_review_task_count"
        )
        != EXPECTED_SECOND_REVIEW_TASK_COUNT
    ):
        errors.append(
            "review queue must contain five "
            "second-review tasks"
        )

    if queue.get(
        "completed_task_count"
    ) != 0:
        errors.append(
            "review queue must begin with zero "
            "completed tasks"
        )

    task_ids = [
        task.get("task_id")
        for task in tasks
    ]

    if len(task_ids) != len(
        set(task_ids)
    ):
        errors.append(
            "duplicate review task IDs"
        )

    for task_record in tasks:
        task_path = ROOT / task_record[
            "task_path"
        ]

        if not task_path.is_file():
            errors.append(
                "missing review task: "
                f"{task_record['task_path']}"
            )
            continue

        actual_task_hash = sha256_file(
            task_path
        )

        if (
            actual_task_hash
            != task_record[
                "task_sha256"
            ]
        ):
            errors.append(
                "review task hash mismatch: "
                f"{task_record['task_path']}"
            )

        task = read_json(task_path)

        if task.get(
            "task_state"
        ) != "PENDING_REVIEW":
            errors.append(
                "review task is prematurely completed: "
                f"{task_record['task_path']}"
            )

        output = task.get(
            "review_output",
            {},
        )

        prohibited_nonempty = {
            "reviewer":
                output.get("reviewer"),
            "review_started_at":
                output.get(
                    "review_started_at"
                ),
            "review_completed_at":
                output.get(
                    "review_completed_at"
                ),
            "final_review_state":
                output.get(
                    "final_review_state"
                ),
            "reviewer_attestation":
                output.get(
                    "reviewer_attestation"
                ),
        }

        for field_name, value in (
            prohibited_nonempty.items()
        ):
            if value is not None:
                errors.append(
                    "pending review task has populated "
                    f"{field_name}: "
                    f"{task_record['task_path']}"
                )

        evidence_path = ROOT / task[
            "evidence_record_path"
        ]

        if not evidence_path.is_file():
            errors.append(
                "task evidence record missing: "
                f"{task['evidence_record_path']}"
            )
        elif (
            sha256_file(evidence_path)
            != task[
                "evidence_record_sha256"
            ]
        ):
            errors.append(
                "task evidence hash mismatch: "
                f"{task['evidence_record_path']}"
            )

    for relative_path, expected in (
        hashes.items()
    ):
        path = ROOT / relative_path

        if not path.is_file():
            errors.append(
                f"hashed review artifact missing: "
                f"{relative_path}"
            )
            continue

        if sha256_file(path) != expected:
            errors.append(
                f"review artifact hash mismatch: "
                f"{relative_path}"
            )

    if (
        STAGE1 / "STAGE_01_CLOSED.json"
    ).exists():
        errors.append(
            "Stage 1 closure marker exists "
            "before reviews"
        )

    if errors:
        print(
            "QUDIPI_STAGE1_REVIEW_QUEUE_VALIDATION=FAIL"
        )

        for error in errors:
            print(f"ERROR  {error}")

        return 1

    print(
        "QUDIPI_STAGE1_REVIEW_QUEUE_VALIDATION=PASS"
    )

    print(
        "primary_task_count="
        f"{EXPECTED_PRIMARY_TASK_COUNT}"
    )

    print(
        "second_review_task_count="
        f"{EXPECTED_SECOND_REVIEW_TASK_COUNT}"
    )

    print(
        "task_count="
        f"{EXPECTED_TOTAL_TASK_COUNT}"
    )

    print("completed_task_count=0")
    print("stage1_status=OPEN")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
