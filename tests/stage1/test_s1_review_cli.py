from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.stage1.review_cli import (
    _reject_placeholder,
    _transactional_files,
    batch_adjudicate,
    build_parser,
    generate_assignment_manifest,
    list_pending,
    recompute_m15,
)
from analysis.stage1.stage1_runtime_contracts import Stage1ContractError, atomic_json, load_json


def _registry(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, {"schema_version": 1, "records": records})


def test_all_required_commands_are_exposed() -> None:
    parser = build_parser()
    actions = next(action for action in parser._actions if getattr(action, "choices", None))
    assert {
        "assign-primary",
        "assign-independent",
        "submit-primary",
        "submit-independent",
        "validate-independence",
        "resolve-review",
        "adjudicate-claim",
        "batch-adjudicate",
        "batch-assign",
        "batch-submit",
        "status",
        "list-pending",
        "generate-assignment-manifest",
        "recompute-m15",
        "recompute-m17",
    } <= set(actions.choices)


def test_transaction_does_not_publish_partial_failure(tmp_path: Path) -> None:
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    first.write_text("old-a", encoding="utf-8")
    second.write_text("old-b", encoding="utf-8")

    def fail(mapping: dict[Path, Path]) -> None:
        mapping[first].write_text("new-a", encoding="utf-8")
        raise Stage1ContractError("stop")

    with pytest.raises(Stage1ContractError):
        _transactional_files([first, second], fail)
    assert first.read_text(encoding="utf-8") == "old-a"
    assert second.read_text(encoding="utf-8") == "old-b"


def test_batch_adjudication_rejects_duplicate_claims_before_mutation(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    registry = stage / "m16" / "novelty_adjudication_registry.json"
    _registry(registry, [{"claim_id": "c1", "review_state": "PENDING_NOVELTY_REVIEW"}])
    before = registry.read_bytes()
    manifest = tmp_path / "manifest.json"
    record = {
        "claim_id": "c1",
        "adjudicator_id": "a1",
        "decision": "INDETERMINATE",
        "relevant_source_ids": ["s1"],
        "overlap_matrix": [{"source_id": "s1", "overlap": "partial"}],
        "single_source_anticipation": "not established",
        "multi_source_combination": "not established",
        "temporal_priority": "unresolved",
        "rationale": "Evidence remains incomplete.",
    }
    atomic_json(manifest, {"records": [record, record]})
    args = build_parser().parse_args(["batch-adjudicate", "--stage-root", str(stage), "--manifest", str(manifest)])
    with pytest.raises(Stage1ContractError, match="duplicate claim_id"):
        batch_adjudicate(args)
    assert registry.read_bytes() == before


def test_recompute_m15_preserves_immutable_completed_resolution(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    _registry(stage / "m13" / "primary_review_registry.json", [{"work_id": "w1", "disposition": "ACCEPT", "primary_review_task_id": "p1"}])
    _registry(stage / "m14" / "independent_review_registry.json", [{"work_id": "w1", "disposition": "REJECT", "independent_review_task_id": "i1"}])
    _registry(stage / "m15" / "review_conflict_resolution_registry.json", [{
        "work_id": "w1",
        "resolution_state": "RESOLVED",
        "resolved_disposition": "ACCEPT_WITH_QUALIFICATIONS",
        "resolution_evidence": ["e1"],
        "resolution_rationale": "resolved by panel",
        "resolver_id": "r1",
        "resolution_event_id": "event1",
    }])
    args = build_parser().parse_args(["recompute-m15", "--stage-root", str(stage)])
    recompute_m15(args)
    record = load_json(stage / "m15" / "review_conflict_resolution_registry.json")["records"][0]
    assert record["resolution_state"] == "RESOLVED"
    assert record["resolved_disposition"] == "ACCEPT_WITH_QUALIFICATIONS"
    assert record["resolution_event_id"] == "event1"


def test_source_snapshot_accepts_hash_or_file_path(tmp_path: Path) -> None:
    from analysis.stage1.review_cli import _snapshot

    source = tmp_path / "source.bin"
    source.write_bytes(b"abc")
    assert len(_snapshot(str(source))) == 64
    assert _snapshot("already-a-hash") == "already-a-hash"


def test_placeholder_values_are_rejected_with_discovery_guidance() -> None:
    with pytest.raises(Stage1ContractError, match="list-pending"):
        _reject_placeholder("<PRIMARY_TASK_ID>", "task_id")


def test_generate_assignment_manifest_uses_real_pending_tasks(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    _registry(
        stage / "m13" / "primary_review_registry.json",
        [
            {
                "primary_review_task_id": "PRIMARY-1",
                "work_id": "WORK-1",
                "review_state": "PENDING",
            },
            {
                "primary_review_task_id": "PRIMARY-2",
                "work_id": "WORK-2",
                "review_state": "SUBMITTED",
            },
        ],
    )
    output = tmp_path / "assignments.json"
    args = build_parser().parse_args(
        [
            "generate-assignment-manifest",
            "--stage-root",
            str(stage),
            "--plane",
            "primary",
            "--reviewer-id",
            "reviewer-a",
            "--role",
            "PRIMARY_SCIENTIFIC_REVIEWER",
            "--output",
            str(output),
        ]
    )
    generate_assignment_manifest(args)
    payload = load_json(output)
    assert payload["records"] == [
        {
            "task_id": "PRIMARY-1",
            "work_id": "WORK-1",
            "reviewer_id": "reviewer-a",
            "role": "PRIMARY_SCIENTIFIC_REVIEWER",
        }
    ]


def test_list_pending_reports_real_task_ids(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stage = tmp_path / "stage"
    _registry(
        stage / "m13" / "primary_review_registry.json",
        [
            {
                "primary_review_task_id": "PRIMARY-1",
                "work_id": "WORK-1",
                "review_state": "PENDING",
            }
        ],
    )
    args = build_parser().parse_args(
        [
            "list-pending",
            "--stage-root",
            str(stage),
            "--plane",
            "primary",
            "--limit",
            "10",
        ]
    )
    list_pending(args)
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_pending"] == 1
    assert payload["records"][0]["task_id"] == "PRIMARY-1"
