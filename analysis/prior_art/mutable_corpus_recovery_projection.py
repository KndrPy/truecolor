from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from analysis.prior_art.mutable_corpus_enterprise import atomic_write_json
from analysis.prior_art.mutable_corpus_service import load_snapshot

RECOVERY_STATE = "EXTRACTION_RECOVERY_REQUIRED"
RECOVERY_TASK_STATE = "AUTOMATED_EXTRACTION_RECOVERY_REQUIRED"
RECOVERY_EXTRACTION_STATES = {"INSUFFICIENT_TEXT"}


def _records(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = value.get("records", [])
    if not isinstance(records, list):
        raise ValueError("artifact records must be a list")
    return [dict(item) for item in records if isinstance(item, Mapping)]


def route_extraction_recovery(output_root: Path) -> Mapping[str, Any]:
    """Separate extraction failure from scientific classification.

    A viewer-renderable PDF with insufficient native text is routed to M02's
    automated recovery queue. It must never be classified non-scientific solely
    because the first native extractor returned little text.
    """
    output_root = output_root.resolve()
    physical_path = output_root / "physical_file_registry.json"
    versions_path = output_root / "document_version_registry.json"
    projection_path = output_root / "stage1_review_queue_projection.json"
    non_scientific_path = output_root / "non_scientific_document_report.json"

    physical_doc = load_snapshot(physical_path)
    versions_doc = load_snapshot(versions_path)
    projection = load_snapshot(projection_path)
    non_scientific = load_snapshot(non_scientific_path)

    physical_by_id = {
        str(record.get("file_id", "")): record
        for record in _records(physical_doc)
        if record.get("file_id")
    }

    recovery_records: list[dict[str, Any]] = []
    updated_versions: list[dict[str, Any]] = []
    recovery_work_ids: set[str] = set()
    recovery_file_ids: set[str] = set()

    for version in _records(versions_doc):
        physical = physical_by_id.get(str(version.get("file_id", "")), {})
        extraction_state = str(physical.get("extraction_state", ""))
        native_text_sha256 = str(physical.get("normalized_text_sha256", ""))
        should_recover = extraction_state in RECOVERY_EXTRACTION_STATES or (
            not native_text_sha256 and extraction_state != "EXTRACTED"
        )
        if should_recover:
            version["current_state"] = RECOVERY_STATE
            file_id = str(version.get("file_id", ""))
            work_id = str(version.get("work_id", ""))
            recovery_file_ids.add(file_id)
            recovery_work_ids.add(work_id)
            recovery_records.append(
                {
                    "file_id": file_id,
                    "work_id": work_id,
                    "version_id": str(version.get("version_id", "")),
                    "relative_path": str(physical.get("relative_path", "")),
                    "page_count": physical.get("page_count"),
                    "source_renderability": "PASS",
                    "native_text_state": "INSUFFICIENT",
                    "recovery_state": RECOVERY_STATE,
                    "recommended_strategy_order": [
                        "NATIVE_LAYOUT",
                        "ALTERNATE_NATIVE",
                        "SELECTIVE_PAGE_OCR_200_DPI",
                        "ENHANCED_PAGE_OCR_300_DPI",
                    ],
                    "scientificity": "UNRESOLVED_PENDING_CONTENT_RECOVERY",
                }
            )
        updated_versions.append(version)

    versions_doc = dict(versions_doc)
    versions_doc["records"] = updated_versions
    atomic_write_json(versions_path, versions_doc)

    non_scientific_doc = dict(non_scientific)
    non_scientific_doc["records"] = [
        record
        for record in _records(non_scientific)
        if str(record.get("file_id", "")) not in recovery_file_ids
    ]
    atomic_write_json(non_scientific_path, non_scientific_doc)

    tasks = projection.get("tasks", [])
    if not isinstance(tasks, list):
        raise ValueError("Stage 1 projection tasks must be a list")
    updated_tasks: list[dict[str, Any]] = []
    for raw in tasks:
        if not isinstance(raw, Mapping):
            continue
        task = dict(raw)
        if str(task.get("work_id", "")) in recovery_work_ids:
            task["task_state"] = RECOVERY_TASK_STATE
            task["next_module"] = "S1-M02"
            task["automated_recovery_required"] = True
        updated_tasks.append(task)
    projection = dict(projection)
    projection["tasks"] = updated_tasks
    projection["task_count"] = len(updated_tasks)
    atomic_write_json(projection_path, projection)

    queue = {
        "schema": "qudipi.stage1.extraction-recovery-queue",
        "schema_version": 1,
        "snapshot_id": versions_doc.get("snapshot_id"),
        "record_count": len(recovery_records),
        "records": sorted(recovery_records, key=lambda item: item["file_id"]),
    }
    atomic_write_json(output_root / "extraction_recovery_queue.json", queue)
    return queue


def finalize_extraction_recovery_contracts(output_root: Path) -> None:
    """Make generated contract projections consistent with recovery routing."""
    output_root = output_root.resolve()

    contract_path = output_root / "mutable_corpus_contract.json"
    if contract_path.is_file():
        contract = dict(load_snapshot(contract_path))
        states = list(contract.get("identity_states", []))
        if RECOVERY_STATE not in states:
            states.append(RECOVERY_STATE)
        contract["identity_states"] = states
        contract["extraction_recovery_task_state"] = RECOVERY_TASK_STATE
        contract["scientificity_separation_rule"] = (
            "EXTRACTION_FAILURE_MUST_NOT_IMPLY_NON_SCIENTIFIC"
        )
        atomic_write_json(contract_path, contract)

    queue_path = output_root / "extraction_recovery_queue.json"
    work_states_path = output_root / "work_identity_state_registry.json"
    if queue_path.is_file() and work_states_path.is_file():
        queue = load_snapshot(queue_path)
        recovery_work_ids = {
            str(item.get("work_id", ""))
            for item in _records(queue)
            if item.get("work_id")
        }
        work_states = dict(load_snapshot(work_states_path))
        updated = []
        for record in _records(work_states):
            if str(record.get("work_id", "")) in recovery_work_ids:
                record["identity_state"] = RECOVERY_STATE
            updated.append(record)
        work_states["records"] = updated
        atomic_write_json(work_states_path, work_states)
