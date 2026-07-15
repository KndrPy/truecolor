from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from analysis.stage1.stage1_runtime_contracts import (
    Stage1ContractError,
    atomic_json,
    atomic_jsonl,
    load_json,
    load_jsonl,
    sha256_file,
    stable_id,
)

REVIEW_DISPOSITIONS = {"ACCEPT", "ACCEPT_WITH_QUALIFICATIONS", "REJECT", "INDETERMINATE"}
NOVELTY_DECISIONS = {"KILLED", "SURVIVES", "NARROWED", "INDETERMINATE"}


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _append_immutable(path: Path, record: Mapping[str, Any]) -> None:
    existing = load_jsonl(path) if path.is_file() else []
    record_id = str(record.get("event_id", ""))
    if not record_id:
        raise Stage1ContractError("immutable event requires event_id")
    if any(str(item.get("event_id")) == record_id for item in existing):
        raise Stage1ContractError(f"duplicate immutable event: {record_id}")
    atomic_jsonl(path, [*existing, dict(record)])


def _load_records(path: Path) -> list[dict[str, Any]]:
    return [dict(item) for item in load_json(path).get("records", [])]


def _write_records(path: Path, payload: Mapping[str, Any], records: Iterable[Mapping[str, Any]]) -> None:
    updated = dict(payload)
    updated["records"] = [dict(item) for item in records]
    atomic_json(path, updated)


def assign_review(registry_path: Path, task_field: str, task_id: str, reviewer_id: str, role: str) -> None:
    payload = load_json(registry_path)
    records = _load_records(registry_path)
    matched = 0
    for item in records:
        if str(item.get(task_field)) != task_id:
            continue
        if item.get("review_state") not in {"PENDING", "ASSIGNED"}:
            raise Stage1ContractError("completed review cannot be reassigned")
        existing = item.get("reviewer_id")
        if existing and existing != reviewer_id:
            raise Stage1ContractError("task already assigned to another reviewer")
        item["reviewer_id"] = reviewer_id
        item["reviewer_role"] = role
        item["assigned_at"] = item.get("assigned_at") or _utc_now()
        item["review_state"] = "ASSIGNED"
        matched += 1
    if matched != 1:
        raise Stage1ContractError(f"expected one task for {task_id}, found {matched}")
    _write_records(registry_path, payload, records)


def submit_review(
    registry_path: Path,
    task_field: str,
    task_id: str,
    reviewer_id: str,
    disposition: str,
    evidence_ids: list[str],
    rationale: str,
    source_snapshot_sha256: str,
    ledger_path: Path,
) -> None:
    if disposition not in REVIEW_DISPOSITIONS:
        raise Stage1ContractError(f"invalid review disposition: {disposition}")
    if not rationale.strip() or not evidence_ids:
        raise Stage1ContractError("review requires rationale and evidence")
    payload = load_json(registry_path)
    records = _load_records(registry_path)
    matched = 0
    for item in records:
        if str(item.get(task_field)) != task_id:
            continue
        if item.get("review_state") == "SUBMITTED":
            raise Stage1ContractError("review submission is immutable")
        if item.get("reviewer_id") != reviewer_id:
            raise Stage1ContractError("reviewer does not own task")
        event = {
            "event_id": stable_id("REVIEW-SUBMISSION", {"task": task_id, "reviewer": reviewer_id, "snapshot": source_snapshot_sha256}),
            "event_type": "REVIEW_SUBMITTED",
            "task_id": task_id,
            "reviewer_id": reviewer_id,
            "disposition": disposition,
            "evidence_ids": evidence_ids,
            "rationale": rationale,
            "source_snapshot_sha256": source_snapshot_sha256,
            "submitted_at": _utc_now(),
        }
        _append_immutable(ledger_path, event)
        item.update(
            {
                "review_state": "SUBMITTED",
                "disposition": disposition,
                "submission_event_id": event["event_id"],
                "evidence_ids": evidence_ids,
                "rationale": rationale,
                "source_snapshot_sha256": source_snapshot_sha256,
                "submitted_at": event["submitted_at"],
            }
        )
        matched += 1
    if matched != 1:
        raise Stage1ContractError(f"expected one task for {task_id}, found {matched}")
    _write_records(registry_path, payload, records)


def validate_independence(primary_path: Path, independent_path: Path) -> None:
    primary = {str(item["work_id"]): item for item in _load_records(primary_path)}
    independent = {str(item["work_id"]): item for item in _load_records(independent_path)}
    if set(primary) != set(independent):
        raise Stage1ContractError("review work sets differ")
    for work_id in primary:
        left, right = primary[work_id], independent[work_id]
        if left.get("reviewer_id") and left.get("reviewer_id") == right.get("reviewer_id"):
            raise Stage1ContractError(f"reviewer independence violated for work {work_id}")
        if left.get("source_snapshot_sha256") and right.get("source_snapshot_sha256") and left["source_snapshot_sha256"] != right["source_snapshot_sha256"]:
            raise Stage1ContractError(f"source snapshot differs for work {work_id}")


def resolve_conflict(
    resolution_path: Path,
    work_id: str,
    resolver_id: str,
    disposition: str,
    evidence_ids: list[str],
    rationale: str,
    ledger_path: Path,
) -> None:
    if disposition not in REVIEW_DISPOSITIONS:
        raise Stage1ContractError(f"invalid resolved disposition: {disposition}")
    if not evidence_ids or not rationale.strip():
        raise Stage1ContractError("resolution requires evidence and rationale")
    payload = load_json(resolution_path)
    records = _load_records(resolution_path)
    matched = 0
    for item in records:
        if str(item.get("work_id")) != work_id:
            continue
        if item.get("resolution_state") == "RESOLVED":
            raise Stage1ContractError("resolution is immutable")
        event = {
            "event_id": stable_id("REVIEW-RESOLUTION", {"work": work_id, "resolver": resolver_id, "disposition": disposition}),
            "event_type": "REVIEW_CONFLICT_RESOLVED",
            "work_id": work_id,
            "resolver_id": resolver_id,
            "resolved_disposition": disposition,
            "evidence_ids": evidence_ids,
            "rationale": rationale,
            "resolved_at": _utc_now(),
        }
        _append_immutable(ledger_path, event)
        item.update(
            {
                "resolution_state": "RESOLVED",
                "resolved_disposition": disposition,
                "resolution_evidence": evidence_ids,
                "resolution_rationale": rationale,
                "resolver_id": resolver_id,
                "resolution_event_id": event["event_id"],
            }
        )
        matched += 1
    if matched != 1:
        raise Stage1ContractError(f"expected one resolution for {work_id}, found {matched}")
    _write_records(resolution_path, payload, records)


def adjudicate_claim(
    registry_path: Path,
    claim_id: str,
    adjudicator_id: str,
    decision: str,
    relevant_source_ids: list[str],
    overlap_matrix: list[Mapping[str, Any]],
    single_source_anticipation: str,
    multi_source_combination: str,
    temporal_priority: str,
    rationale: str,
    ledger_path: Path,
) -> None:
    if decision not in NOVELTY_DECISIONS:
        raise Stage1ContractError(f"invalid novelty decision: {decision}")
    if not relevant_source_ids or not overlap_matrix or not rationale.strip():
        raise Stage1ContractError("adjudication requires sources, overlap matrix, and rationale")
    payload = load_json(registry_path)
    records = _load_records(registry_path)
    matched = 0
    for item in records:
        if str(item.get("claim_id")) != claim_id:
            continue
        if item.get("review_state") == "ADJUDICATED":
            raise Stage1ContractError("adjudication is immutable")
        event = {
            "event_id": stable_id("NOVELTY-ADJUDICATION", {"claim": claim_id, "adjudicator": adjudicator_id, "decision": decision}),
            "event_type": "NOVELTY_ADJUDICATED",
            "claim_id": claim_id,
            "adjudicator_id": adjudicator_id,
            "decision": decision,
            "relevant_source_ids": relevant_source_ids,
            "overlap_matrix": overlap_matrix,
            "single_source_anticipation": single_source_anticipation,
            "multi_source_combination": multi_source_combination,
            "temporal_priority": temporal_priority,
            "rationale": rationale,
            "adjudicated_at": _utc_now(),
        }
        _append_immutable(ledger_path, event)
        item.update(
            {
                "relevant_source_ids": relevant_source_ids,
                "overlap_matrix": overlap_matrix,
                "single_source_anticipation": single_source_anticipation,
                "multi_source_combination": multi_source_combination,
                "temporal_priority": temporal_priority,
                "novelty_decision": decision,
                "decision_authority": adjudicator_id,
                "decision_rationale": rationale,
                "adjudication_event_id": event["event_id"],
                "review_state": "ADJUDICATED",
            }
        )
        matched += 1
    if matched != 1:
        raise Stage1ContractError(f"expected one claim for {claim_id}, found {matched}")
    _write_records(registry_path, payload, records)


def progress(stage_root: Path) -> Mapping[str, Any]:
    primary = _load_records(stage_root / "m13" / "primary_review_registry.json")
    independent = _load_records(stage_root / "m14" / "independent_review_registry.json")
    resolutions = _load_records(stage_root / "m15" / "review_conflict_resolution_registry.json")
    adjudications = _load_records(stage_root / "m16" / "novelty_adjudication_registry.json")
    return {
        "primary": {
            "total": len(primary),
            "submitted": sum(item.get("review_state") == "SUBMITTED" for item in primary),
        },
        "independent": {
            "total": len(independent),
            "submitted": sum(item.get("review_state") == "SUBMITTED" for item in independent),
        },
        "resolutions": {
            "total": len(resolutions),
            "resolved": sum(
                bool(
                    item.get("resolution_state") in {"AGREEMENT", "RESOLVED"}
                    and item.get("resolved_disposition")
                )
                for item in resolutions
            ),
        },
        "adjudications": {
            "total": len(adjudications),
            "adjudicated": sum(item.get("review_state") == "ADJUDICATED" for item in adjudications),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Durable Stage 1 review execution utility")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--stage-root", required=True)
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(progress(Path(args.stage_root)), indent=2))


if __name__ == "__main__":
    main()
