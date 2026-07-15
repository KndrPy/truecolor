from __future__ import annotations

from pathlib import Path

import pytest

from analysis.stage1.review_packet_builder import (
    EVIDENCE_ARTIFACTS,
    build_packets,
    build_submission_template,
    validate_submission_manifest,
)
from analysis.stage1.stage1_runtime_contracts import (
    Stage1ContractError,
    atomic_json,
    atomic_jsonl,
    load_json,
)


def _write(path: Path, text: str = "{}\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    stage = tmp_path / "stage"
    m01 = tmp_path / "m01"
    for module, filename in EVIDENCE_ARTIFACTS:
        root = m01 if module == "m01" else stage / module
        if filename == "work_identity_state_registry.json":
            atomic_json(
                root / filename,
                {
                    "records": [
                        {
                            "work_id": "w1",
                            "file_id": "f1",
                            "identity_state": "CURRENT",
                        }
                    ]
                },
            )
        elif filename == "grounded_claim_assessment_registry.jsonl":
            atomic_jsonl(root / filename, [{"claim_id": "c1", "file_id": "f1"}])
        else:
            _write(root / filename)
    atomic_json(
        stage / "m13" / "primary_review_registry.json",
        {
            "records": [
                {
                    "primary_review_task_id": "p1",
                    "work_id": "w1",
                    "claim_ids": [],
                    "review_state": "ASSIGNED",
                    "reviewer_id": "primary-r",
                    "disposition": "REJECT",
                    "rationale": "must not leak",
                }
            ]
        },
    )
    atomic_json(
        stage / "m14" / "independent_review_registry.json",
        {
            "records": [
                {
                    "independent_review_task_id": "i1",
                    "work_id": "w1",
                    "review_state": "ASSIGNED",
                    "reviewer_id": "independent-r",
                }
            ]
        },
    )
    return stage, m01


def test_independent_packet_is_blind_snapshot_bound_and_claim_linked(tmp_path: Path) -> None:
    stage, m01 = _fixture(tmp_path)
    out = tmp_path / "packets"
    index = build_packets(stage, m01, "independent", out)
    assert index["packet_count"] == 1
    assert index["claim_count"] == 1
    packet = load_json(Path(index["records"][0]["packet_path"]))
    assert packet["claim_ids"] == ["c1"]
    assert packet["reviewer_id"] == "independent-r"
    assert packet["blindness_contract"]["prior_primary_disposition_visible"] is False
    for forbidden in ("disposition", "rationale", "evidence_ids", "submission_event_id"):
        assert forbidden not in packet
    assert packet["source_snapshot_sha256"] == index["source_snapshot_sha256"]


def test_primary_packet_does_not_claim_prior_disposition_visibility(tmp_path: Path) -> None:
    stage, m01 = _fixture(tmp_path)
    out = tmp_path / "packets"
    index = build_packets(stage, m01, "primary", out)
    packet = load_json(Path(index["records"][0]["packet_path"]))
    assert packet["blindness_contract"]["prior_primary_disposition_visible"] is False
    assert packet["claim_ids"] == ["c1"]


def test_submission_template_is_intentionally_incomplete(tmp_path: Path) -> None:
    stage, m01 = _fixture(tmp_path)
    out = tmp_path / "packets"
    build_packets(stage, m01, "primary", out)
    template_path = tmp_path / "submission.json"
    result = build_submission_template(out / "packet_index.json", template_path)
    record = result["records"][0]
    assert record["disposition"] is None
    assert record["evidence_ids"] == []
    status = validate_submission_manifest(template_path, out / "packet_index.json")
    assert status["ready_for_batch_submit"] is False
    assert status["incomplete_task_ids"] == ["p1"]


def test_complete_submission_validates(tmp_path: Path) -> None:
    stage, m01 = _fixture(tmp_path)
    out = tmp_path / "packets"
    build_packets(stage, m01, "primary", out)
    template_path = tmp_path / "submission.json"
    payload = build_submission_template(out / "packet_index.json", template_path)
    payload["records"][0].update(
        {
            "disposition": "ACCEPT_WITH_QUALIFICATIONS",
            "evidence_ids": ["c1"],
            "rationale": "Evidence was reviewed against the bound snapshot.",
        }
    )
    atomic_json(template_path, payload)
    status = validate_submission_manifest(template_path, out / "packet_index.json")
    assert status["ready_for_batch_submit"] is True


def test_packet_tampering_is_detected(tmp_path: Path) -> None:
    stage, m01 = _fixture(tmp_path)
    out = tmp_path / "packets"
    build_packets(stage, m01, "primary", out)
    template_path = tmp_path / "submission.json"
    payload = build_submission_template(out / "packet_index.json", template_path)
    payload["records"][0].update(
        {"disposition": "ACCEPT", "evidence_ids": ["c1"], "rationale": "reviewed"}
    )
    atomic_json(template_path, payload)
    packet_path = Path(load_json(out / "packet_index.json")["records"][0]["packet_path"])
    packet_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(Stage1ContractError, match="packet changed"):
        validate_submission_manifest(template_path, out / "packet_index.json")
