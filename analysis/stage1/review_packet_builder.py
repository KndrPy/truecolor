from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from analysis.stage1.stage1_runtime_contracts import (
    Stage1ContractError,
    atomic_json,
    load_json,
    sha256_file,
    stable_id,
)

REVIEW_REQUIREMENTS = (
    "source_integrity",
    "extraction_coverage",
    "author_model",
    "method_decomposition",
    "claim_grounding",
    "gap_assessment",
)

EVIDENCE_ARTIFACTS = (
    ("m01", "work_identity_state_registry.json"),
    ("m03", "document_structure.json"),
    ("m03", "document_elements.jsonl"),
    ("m06", "author_problem_models.json"),
    ("m07", "defined_job_implements.jsonl"),
    ("m08", "claim_registry.jsonl"),
    ("m11", "claim_grounding_registry.jsonl"),
    ("m12", "grounded_claim_assessment_registry.jsonl"),
)


def _records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise Stage1ContractError(f"required registry missing: {path}")
    payload = load_json(path)
    records = payload.get("records")
    if not isinstance(records, list):
        raise Stage1ContractError(f"registry requires records list: {path}")
    return [dict(item) for item in records]


def _artifact_path(stage_root: Path, m01_root: Path, module: str, filename: str) -> Path:
    return (m01_root if module == "m01" else stage_root / module) / filename


def build_snapshot(stage_root: Path, m01_root: Path) -> dict[str, Any]:
    artifacts: list[dict[str, str]] = []
    for module, filename in EVIDENCE_ARTIFACTS:
        path = _artifact_path(stage_root, m01_root, module, filename)
        if not path.is_file():
            raise Stage1ContractError(f"review evidence artifact missing: {path}")
        artifacts.append(
            {
                "module": module,
                "path": path.as_posix(),
                "sha256": sha256_file(path),
            }
        )
    identity = stable_id("REVIEW-SNAPSHOT", {item["path"]: item["sha256"] for item in artifacts})
    return {
        "schema_version": 1,
        "snapshot_id": identity,
        "artifacts": artifacts,
    }


def _work_claim_map(stage_root: Path) -> dict[str, list[str]]:
    primary = _records(stage_root / "m13" / "primary_review_registry.json")
    mapping: dict[str, list[str]] = {}
    for item in primary:
        work_id = str(item.get("work_id", ""))
        if not work_id:
            raise Stage1ContractError("primary review task missing work_id")
        claims = item.get("claim_ids", [])
        if not isinstance(claims, list):
            raise Stage1ContractError(f"primary review claim_ids must be list: {work_id}")
        mapping[work_id] = [str(value) for value in claims if str(value)]
    return mapping


def _work_identity_map(m01_root: Path) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("work_id")): item
        for item in _records(m01_root / "work_identity_state_registry.json")
        if item.get("work_id")
    }


def build_packets(
    stage_root: Path,
    m01_root: Path,
    plane: str,
    output_root: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    if plane not in {"primary", "independent"}:
        raise Stage1ContractError(f"unsupported review plane: {plane}")
    if output_root.exists() and any(output_root.iterdir()) and not overwrite:
        raise Stage1ContractError(f"refusing to overwrite non-empty packet directory: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    snapshot = build_snapshot(stage_root, m01_root)
    snapshot_path = output_root / "source_snapshot.json"
    atomic_json(snapshot_path, snapshot)
    snapshot_sha256 = sha256_file(snapshot_path)

    if plane == "primary":
        registry_path = stage_root / "m13" / "primary_review_registry.json"
        task_field = "primary_review_task_id"
    else:
        registry_path = stage_root / "m14" / "independent_review_registry.json"
        task_field = "independent_review_task_id"

    tasks = _records(registry_path)
    claim_map = _work_claim_map(stage_root)
    identities = _work_identity_map(m01_root)
    index: list[dict[str, Any]] = []

    for task in tasks:
        task_id = str(task.get(task_field, ""))
        work_id = str(task.get("work_id", ""))
        reviewer_id = str(task.get("reviewer_id", ""))
        if not task_id or not work_id:
            raise Stage1ContractError(f"review task missing identity in {registry_path}")
        if task.get("review_state") not in {"ASSIGNED", "PENDING"}:
            continue
        packet = {
            "schema_version": 1,
            "packet_id": stable_id("REVIEW-PACKET", {"plane": plane, "task": task_id, "snapshot": snapshot_sha256}),
            "review_plane": plane,
            "task_id": task_id,
            "work_id": work_id,
            "reviewer_id": reviewer_id or None,
            "review_state": task.get("review_state"),
            "identity_state": identities.get(work_id, {}).get("identity_state"),
            "claim_ids": claim_map.get(work_id, []),
            "review_requirements": list(task.get("review_requirements") or REVIEW_REQUIREMENTS),
            "source_snapshot_path": snapshot_path.as_posix(),
            "source_snapshot_sha256": snapshot_sha256,
            "evidence_artifacts": snapshot["artifacts"],
            "blindness_contract": {
                "primary_disposition_visible": plane == "primary",
                "other_reviewer_identity_visible": False,
                "other_review_rationale_visible": False,
                "other_review_evidence_visible": False,
            },
            "submission_requirements": {
                "allowed_dispositions": ["ACCEPT", "ACCEPT_WITH_QUALIFICATIONS", "REJECT", "INDETERMINATE"],
                "evidence_ids_required": True,
                "rationale_required": True,
                "source_snapshot_sha256_required": snapshot_sha256,
            },
        }
        # Never carry a prior disposition, rationale, evidence list, or submission event into a packet.
        forbidden = {"disposition", "rationale", "evidence_ids", "submission_event_id", "submitted_at"}
        if forbidden.intersection(packet):
            raise Stage1ContractError("review packet leaked prior review outcome fields")
        packet_path = output_root / f"{task_id}.json"
        atomic_json(packet_path, packet)
        index.append(
            {
                "task_id": task_id,
                "work_id": work_id,
                "packet_path": packet_path.as_posix(),
                "packet_sha256": sha256_file(packet_path),
                "source_snapshot_sha256": snapshot_sha256,
            }
        )

    manifest = {
        "schema_version": 1,
        "plane": plane,
        "source_snapshot_path": snapshot_path.as_posix(),
        "source_snapshot_sha256": snapshot_sha256,
        "packet_count": len(index),
        "records": index,
    }
    atomic_json(output_root / "packet_index.json", manifest)
    return manifest


def build_submission_template(packet_index: Path, output: Path, overwrite: bool = False) -> dict[str, Any]:
    if output.exists() and not overwrite:
        raise Stage1ContractError(f"refusing to overwrite submission template: {output}")
    payload = load_json(packet_index)
    plane = str(payload.get("plane", ""))
    if plane not in {"primary", "independent"}:
        raise Stage1ContractError("packet index has invalid plane")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise Stage1ContractError("packet index requires records")
    template_records: list[dict[str, Any]] = []
    for item in records:
        packet_path = Path(str(item.get("packet_path", "")))
        packet = load_json(packet_path)
        template_records.append(
            {
                "task_id": packet["task_id"],
                "reviewer_id": packet.get("reviewer_id"),
                "disposition": None,
                "evidence_ids": [],
                "rationale": None,
                "source_snapshot": packet["source_snapshot_sha256"],
                "packet_id": packet["packet_id"],
                "packet_sha256": sha256_file(packet_path),
            }
        )
    result = {
        "schema_version": 1,
        "plane": plane,
        "source_snapshot_sha256": payload["source_snapshot_sha256"],
        "records": template_records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(output, result)
    return result


def validate_submission_manifest(manifest: Path, packet_index: Path) -> dict[str, Any]:
    submission = load_json(manifest)
    index = load_json(packet_index)
    if submission.get("plane") != index.get("plane"):
        raise Stage1ContractError("submission plane differs from packet plane")
    expected = {str(item["task_id"]): item for item in index.get("records", [])}
    records = submission.get("records")
    if not isinstance(records, list):
        raise Stage1ContractError("submission manifest requires records")
    seen: set[str] = set()
    incomplete: list[str] = []
    for item in records:
        task_id = str(item.get("task_id", ""))
        if task_id not in expected:
            raise Stage1ContractError(f"submission task not in packet index: {task_id}")
        if task_id in seen:
            raise Stage1ContractError(f"duplicate submission task: {task_id}")
        seen.add(task_id)
        packet_path = Path(expected[task_id]["packet_path"])
        if sha256_file(packet_path) != expected[task_id]["packet_sha256"]:
            raise Stage1ContractError(f"review packet changed after issuance: {task_id}")
        if item.get("source_snapshot") != index.get("source_snapshot_sha256"):
            raise Stage1ContractError(f"source snapshot mismatch: {task_id}")
        if not item.get("disposition") or not item.get("evidence_ids") or not str(item.get("rationale") or "").strip():
            incomplete.append(task_id)
    missing = sorted(set(expected) - seen)
    result = {
        "schema_version": 1,
        "plane": index.get("plane"),
        "expected": len(expected),
        "present": len(seen),
        "missing_task_ids": missing,
        "incomplete_task_ids": incomplete,
        "ready_for_batch_submit": not missing and not incomplete,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Build blind, immutable Stage 1 scientific review packets")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build-packets")
    build.add_argument("--stage-root", required=True)
    build.add_argument("--m01-root", required=True)
    build.add_argument("--plane", choices=("primary", "independent"), required=True)
    build.add_argument("--output-root", required=True)
    build.add_argument("--overwrite", action="store_true")

    template = sub.add_parser("build-submission-template")
    template.add_argument("--packet-index", required=True)
    template.add_argument("--output", required=True)
    template.add_argument("--overwrite", action="store_true")

    validate = sub.add_parser("validate-submission")
    validate.add_argument("--packet-index", required=True)
    validate.add_argument("--manifest", required=True)

    args = parser.parse_args()
    if args.command == "build-packets":
        result = build_packets(Path(args.stage_root), Path(args.m01_root), args.plane, Path(args.output_root), args.overwrite)
    elif args.command == "build-submission-template":
        result = build_submission_template(Path(args.packet_index), Path(args.output), args.overwrite)
    else:
        result = validate_submission_manifest(Path(args.manifest), Path(args.packet_index))
    print(json.dumps(result, indent=2))
    print(f"TRUECOLOR_STAGE1_REVIEW_PACKET_{args.command.upper().replace('-', '_')}=PASS")


if __name__ == "__main__":
    main()
