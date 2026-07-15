from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.stage1.review_execution import (
    adjudicate_claim,
    assign_review,
    progress,
    resolve_conflict,
    submit_review,
    validate_independence,
)
from analysis.stage1.stage1_runtime_contracts import Stage1ContractError, atomic_json


def _registry(path: Path, records: list[dict]) -> None:
    atomic_json(path, {"schema_version": 1, "records": records})


def test_assignment_and_submission_are_owner_bound_and_immutable(tmp_path: Path) -> None:
    registry = tmp_path / "primary.json"
    ledger = tmp_path / "ledger.jsonl"
    _registry(registry, [{"primary_review_task_id": "T1", "work_id": "W1", "review_state": "PENDING", "disposition": None}])
    assign_review(registry, "primary_review_task_id", "T1", "R1", "PRIMARY")
    submit_review(registry, "primary_review_task_id", "T1", "R1", "ACCEPT", ["E1"], "Grounded review", "abc", ledger)
    data = json.loads(registry.read_text())
    assert data["records"][0]["review_state"] == "SUBMITTED"
    with pytest.raises(Stage1ContractError, match="immutable"):
        submit_review(registry, "primary_review_task_id", "T1", "R1", "REJECT", ["E2"], "Changed", "abc", ledger)


def test_independent_reviewer_identity_and_snapshot_are_enforced(tmp_path: Path) -> None:
    primary = tmp_path / "primary.json"
    second = tmp_path / "second.json"
    _registry(primary, [{"work_id": "W1", "reviewer_id": "R1", "source_snapshot_sha256": "A"}])
    _registry(second, [{"work_id": "W1", "reviewer_id": "R1", "source_snapshot_sha256": "A"}])
    with pytest.raises(Stage1ContractError, match="independence"):
        validate_independence(primary, second)
    _registry(second, [{"work_id": "W1", "reviewer_id": "R2", "source_snapshot_sha256": "B"}])
    with pytest.raises(Stage1ContractError, match="snapshot"):
        validate_independence(primary, second)


def test_conflict_resolution_requires_evidence_and_is_immutable(tmp_path: Path) -> None:
    registry = tmp_path / "resolution.json"
    ledger = tmp_path / "ledger.jsonl"
    _registry(registry, [{"work_id": "W1", "resolution_state": "CONFLICT_REQUIRES_RESOLUTION", "resolved_disposition": None}])
    resolve_conflict(registry, "W1", "R3", "ACCEPT_WITH_QUALIFICATIONS", ["E1"], "Resolved from evidence", ledger)
    with pytest.raises(Stage1ContractError, match="immutable"):
        resolve_conflict(registry, "W1", "R3", "REJECT", ["E2"], "Changed", ledger)


def test_adjudication_requires_comparison_evidence_and_is_immutable(tmp_path: Path) -> None:
    registry = tmp_path / "novelty.json"
    ledger = tmp_path / "ledger.jsonl"
    _registry(registry, [{"claim_id": "C1", "review_state": "PENDING_NOVELTY_REVIEW", "novelty_decision": "INDETERMINATE"}])
    adjudicate_claim(
        registry, "C1", "A1", "NARROWED", ["S1"], [{"source_id": "S1", "overlap": "PARTIAL"}],
        "NOT_ANTICIPATED", "COMBINATION_RELEVANT", "PRIORITY_ESTABLISHED", "Evidence-based narrowing", ledger,
    )
    with pytest.raises(Stage1ContractError, match="immutable"):
        adjudicate_claim(
            registry, "C1", "A1", "SURVIVES", ["S1"], [{"source_id": "S1"}],
            "NO", "NO", "YES", "Changed", ledger,
        )


def test_progress_is_resumable_and_counted_from_registry_state(tmp_path: Path) -> None:
    for name in ("m13", "m14", "m15", "m16"):
        (tmp_path / name).mkdir()
    _registry(tmp_path / "m13" / "primary_review_registry.json", [{"review_state": "SUBMITTED"}, {"review_state": "PENDING"}])
    _registry(tmp_path / "m14" / "independent_review_registry.json", [{"review_state": "SUBMITTED"}])
    _registry(tmp_path / "m15" / "review_conflict_resolution_registry.json", [{"resolution_state": "RESOLVED", "resolved_disposition": "ACCEPT"}])
    _registry(tmp_path / "m16" / "novelty_adjudication_registry.json", [{"review_state": "ADJUDICATED"}, {"review_state": "PENDING_NOVELTY_REVIEW"}])
    state = progress(tmp_path)
    assert state["primary"] == {"total": 2, "submitted": 1}
    assert state["adjudications"] == {"total": 2, "adjudicated": 1}
