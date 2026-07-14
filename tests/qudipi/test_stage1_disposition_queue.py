from __future__ import annotations

import hashlib
import json
from pathlib import Path

STAGE1 = Path("artifacts/stage_01")

POLICY = Path(
    "analysis/prior_art/"
    "stage1_closure/"
    "truecolor_stage1_coverage_policy.json"
)


def load_json(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def test_one_task_exists_per_pending_source() -> None:
    coverage = load_json(
        STAGE1
        / "corpus_coverage_register.json"
    )

    queue = load_json(
        STAGE1
        / "corpus_disposition_queue.json"
    )

    pending = {
        record["canonical_identity"]
        for record in coverage["records"]
        if (
            record["coverage_state"]
            == "PENDING"
        )
    }

    queued = {
        task["canonical_identity"]
        for task in queue["tasks"]
    }

    assert pending == queued

    assert (
        queue["task_count"]
        == len(pending)
    )


def test_all_tasks_begin_without_decisions() -> None:
    queue = load_json(
        STAGE1
        / "corpus_disposition_queue.json"
    )

    for task_record in queue["tasks"]:
        task = load_json(
            Path(task_record["task_path"])
        )

        assert (
            task["task_state"]
            == "PENDING_DISPOSITION"
        )

        decision = task["decision"]

        assert (
            decision[
                "selected_terminal_role"
            ]
            is None
        )

        assert (
            decision[
                "decision_reason"
            ]
            is None
        )

        assert (
            decision["evidence_basis"]
            == []
        )

        assert (
            decision["reviewer"]
            is None
        )

        assert (
            decision[
                "reviewer_attestation"
            ]
            is None
        )


def test_allowed_roles_derive_from_policy() -> None:
    policy = load_json(POLICY)

    queue = load_json(
        STAGE1
        / "corpus_disposition_queue.json"
    )

    allowed = set(
        policy["terminal_roles"]
    )

    for task_record in queue["tasks"]:
        task = load_json(
            Path(task_record["task_path"])
        )

        assert set(
            task[
                "allowed_terminal_roles"
            ]
        ) == allowed


def test_decision_contract_prohibits_inference() -> None:
    queue = load_json(
        STAGE1
        / "corpus_disposition_queue.json"
    )

    for task_record in queue["tasks"]:
        task = load_json(
            Path(task_record["task_path"])
        )

        contract = task[
            "decision_contract"
        ]

        assert (
            contract[
                "title_only_decision_prohibited"
            ]
            is True
        )

        assert (
            contract[
                "rank_only_decision_prohibited"
            ]
            is True
        )

        assert (
            contract[
                "fuzzy_identity_matching_prohibited"
            ]
            is True
        )

        assert (
            contract[
                "scientific_claim_inference_prohibited"
            ]
            is True
        )


def test_queue_and_tasks_are_hash_bound() -> None:
    queue = load_json(
        STAGE1
        / "corpus_disposition_queue.json"
    )

    hashes = load_json(
        STAGE1
        / "artifact_hashes.json"
    )

    paths = {
        "artifacts/stage_01/"
        "corpus_disposition_queue.json"
    }

    paths.update(
        task["task_path"]
        for task in queue["tasks"]
    )

    assert paths <= set(hashes)

    for relative_path in paths:
        path = Path(relative_path)

        actual = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

        assert actual == hashes[
            relative_path
        ]


def test_stage1_remains_open() -> None:
    gap = load_json(
        STAGE1
        / "stage1_gap_report.json"
    )

    assert gap["stage_state"] == "OPEN"

    assert (
        "governed_corpus_terminal_disposition"
        in gap["remaining_blockers"]
    )

    assert not (
        STAGE1
        / "STAGE_01_CLOSED.json"
    ).exists()


def test_pending_decision_fields_are_semantically_empty() -> None:
    queue = load_json(
        STAGE1
        / "corpus_disposition_queue.json"
    )

    for task_record in queue["tasks"]:
        task = load_json(
            Path(task_record["task_path"])
        )

        decision = task["decision"]

        for value in decision.values():
            if value is None:
                continue

            if isinstance(value, str):
                assert value == ""
                continue

            if isinstance(
                value,
                (
                    list,
                    dict,
                    tuple,
                    set,
                ),
            ):
                assert not value
                continue

            raise AssertionError(
                "pending decision contains "
                f"unsupported populated value: {value!r}"
            )
