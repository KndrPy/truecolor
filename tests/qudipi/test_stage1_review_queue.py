from __future__ import annotations

import hashlib
import json
from pathlib import Path

STAGE1 = Path("artifacts/stage_01")


def load_json(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def test_review_queue_has_exact_task_counts() -> None:
    queue = load_json(
        STAGE1 / "review_work_queue.json"
    )

    assert queue["queue_state"] == "READY"
    assert queue["construction_errors"] == []

    assert queue[
        "primary_task_count"
    ] == 1

    assert queue[
        "second_review_task_count"
    ] == 5

    assert queue["task_count"] == 6
    assert queue["completed_task_count"] == 0


def test_review_task_ids_are_unique() -> None:
    queue = load_json(
        STAGE1 / "review_work_queue.json"
    )

    task_ids = [
        task["task_id"]
        for task in queue["tasks"]
    ]

    assert len(task_ids) == len(
        set(task_ids)
    )


def test_all_review_tasks_are_pending() -> None:
    queue = load_json(
        STAGE1 / "review_work_queue.json"
    )

    for task_record in queue["tasks"]:
        task = load_json(
            Path(task_record["task_path"])
        )

        assert (
            task["task_state"]
            == "PENDING_REVIEW"
        )

        output = task["review_output"]

        assert output["reviewer"] is None
        assert (
            output["review_completed_at"]
            is None
        )
        assert (
            output["final_review_state"]
            is None
        )
        assert (
            output["reviewer_attestation"]
            is None
        )


def test_primary_task_is_paper_five() -> None:
    queue = load_json(
        STAGE1 / "review_work_queue.json"
    )

    primary_tasks = [
        task
        for task in queue["tasks"]
        if task["task_type"]
        == "PRIMARY_SCIENTIFIC_REVIEW"
    ]

    assert len(primary_tasks) == 1

    task = load_json(
        Path(primary_tasks[0]["task_path"])
    )

    assert task["source_id"] == "PA-0005"

    assert (
        task["canonical_key"]
        == "doi:10.1111/jdv.17076"
    )

    assert len(
        task["pending_field_names"]
    ) == 24


def test_second_review_tasks_require_independence() -> None:
    queue = load_json(
        STAGE1 / "review_work_queue.json"
    )

    second_tasks = [
        task
        for task in queue["tasks"]
        if task["task_type"]
        == "INDEPENDENT_SECOND_REVIEW"
    ]

    assert len(second_tasks) == 5

    for task_record in second_tasks:
        task = load_json(
            Path(task_record["task_path"])
        )

        assert (
            task["required_independence"]
            is True
        )


def test_review_tasks_are_hash_bound() -> None:
    queue = load_json(
        STAGE1 / "review_work_queue.json"
    )

    for task_record in queue["tasks"]:
        task_path = Path(
            task_record["task_path"]
        )

        actual_task_hash = hashlib.sha256(
            task_path.read_bytes()
        ).hexdigest()

        assert actual_task_hash == (
            task_record["task_sha256"]
        )

        task = load_json(task_path)

        evidence_path = Path(
            task["evidence_record_path"]
        )

        actual_evidence_hash = (
            hashlib.sha256(
                evidence_path.read_bytes()
            ).hexdigest()
        )

        assert actual_evidence_hash == (
            task[
                "evidence_record_sha256"
            ]
        )


def test_review_queue_does_not_close_stage1() -> None:
    gap = load_json(
        STAGE1 / "stage1_gap_report.json"
    )

    assert gap["status"] == "OPEN"

    assert not (
        STAGE1 / "STAGE_01_CLOSED.json"
    ).exists()
