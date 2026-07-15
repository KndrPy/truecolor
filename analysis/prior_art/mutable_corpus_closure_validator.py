from __future__ import annotations

from pathlib import Path
from typing import Mapping

from analysis.prior_art.mutable_corpus_contracts import (
    IDENTITY_STATES,
    MISSING_SOURCE_STATES,
    REQUIRED_OUTPUTS,
)
from analysis.prior_art.mutable_corpus_enterprise import EnterpriseCorpusError
from analysis.prior_art.mutable_corpus_recovery_projection import (
    RECOVERY_STATE,
    RECOVERY_TASK_STATE,
)
from analysis.prior_art.mutable_corpus_service import load_snapshot


def validate_consumer_closure(output_root: Path) -> Mapping[str, str]:
    gates: dict[str, str] = {}
    required = (*REQUIRED_OUTPUTS, "extraction_recovery_queue.json")
    missing = [name for name in required if not (output_root / name).is_file()]
    if missing:
        raise EnterpriseCorpusError(f"required corpus outputs missing: {', '.join(missing)}")
    gates["required_output_contract"] = "PASS"

    physical = load_snapshot(output_root / "physical_file_registry.json").get("records", [])
    bindings = load_snapshot(output_root / "physical_file_version_registry.json").get("records", [])
    versions = load_snapshot(output_root / "document_version_registry.json").get("records", [])
    works = load_snapshot(output_root / "scientific_work_registry.json").get("records", [])
    if {item["file_id"] for item in physical} != {item["file_id"] for item in bindings}:
        raise EnterpriseCorpusError("physical-file/version binding is not total")
    if len({item["version_id"] for item in versions}) != len(versions):
        raise EnterpriseCorpusError("document version IDs are not unique")
    if len({item["work_id"] for item in works}) != len(works):
        raise EnterpriseCorpusError("scientific work IDs are not unique")
    gates["registry_referential_integrity"] = "PASS"

    unreadable = load_snapshot(output_root / "unreadable_document_report.json").get("records", [])
    non_scientific = load_snapshot(output_root / "non_scientific_document_report.json").get("records", [])
    if any(item["current_state"] != "UNREADABLE_DOCUMENT" for item in unreadable):
        raise EnterpriseCorpusError("unreadable-document report contains another state")
    if any(item["current_state"] != "NON_SCIENTIFIC_DOCUMENT" for item in non_scientific):
        raise EnterpriseCorpusError("non-scientific report contains another state")
    gates["failure_state_preservation"] = "PASS"

    contract = load_snapshot(output_root / "mutable_corpus_contract.json")
    expected_identity_states = {*IDENTITY_STATES, RECOVERY_STATE}
    if set(contract.get("identity_states", [])) != expected_identity_states:
        raise EnterpriseCorpusError("identity state contract is incomplete")
    if set(contract.get("missing_source_states", [])) != set(MISSING_SOURCE_STATES):
        raise EnterpriseCorpusError("missing-source state contract is incomplete")
    if contract.get("extraction_recovery_task_state") != RECOVERY_TASK_STATE:
        raise EnterpriseCorpusError("extraction recovery task contract is incomplete")
    if (
        contract.get("scientificity_separation_rule")
        != "EXTRACTION_FAILURE_MUST_NOT_IMPLY_NON_SCIENTIFIC"
    ):
        raise EnterpriseCorpusError("extraction/scientificity separation rule is absent")
    gates["state_space_completeness"] = "PASS"

    queue = load_snapshot(output_root / "extraction_recovery_queue.json")
    recovery_records = queue.get("records", [])
    if not isinstance(recovery_records, list):
        raise EnterpriseCorpusError("extraction recovery queue records are invalid")
    if queue.get("record_count") != len(recovery_records):
        raise EnterpriseCorpusError("extraction recovery queue count is inconsistent")
    recovery_file_ids = {str(item.get("file_id", "")) for item in recovery_records}
    recovery_work_ids = {str(item.get("work_id", "")) for item in recovery_records}
    version_recovery_file_ids = {
        str(item.get("file_id", ""))
        for item in versions
        if item.get("current_state") == RECOVERY_STATE
    }
    if recovery_file_ids != version_recovery_file_ids:
        raise EnterpriseCorpusError("recovery queue/version state projection is not total")
    if recovery_file_ids & {str(item.get("file_id", "")) for item in non_scientific}:
        raise EnterpriseCorpusError("recovery-required source remains classified non-scientific")
    work_states = load_snapshot(output_root / "work_identity_state_registry.json").get(
        "records", []
    )
    work_state_recovery_ids = {
        str(item.get("work_id", ""))
        for item in work_states
        if item.get("identity_state") == RECOVERY_STATE
    }
    if work_state_recovery_ids != recovery_work_ids:
        raise EnterpriseCorpusError("recovery queue/work state projection is not total")
    gates["extraction_recovery_routing"] = "PASS"

    authority = load_snapshot(output_root / "scientific_authority_boundary.json")
    if authority["rules"]["silent_download"] != "PROHIBITED":
        raise EnterpriseCorpusError("silent download authority boundary is not enforced")
    if any(item["scientifically_authoritative_file_id"] for item in authority["records"]):
        raise EnterpriseCorpusError("scientific authority was assigned autonomously")
    gates["researcher_authority_boundary"] = "PASS"

    history = output_root / "history"
    if not (history / "corpus_event_ledger.jsonl").is_file():
        raise EnterpriseCorpusError("durable event ledger is missing")
    if not any((history / "snapshots").glob("SNAPSHOT-*.json")):
        raise EnterpriseCorpusError("immutable snapshot history is missing")
    gates["durable_history"] = "PASS"

    stage1 = load_snapshot(output_root / "stage1_review_queue_projection.json")
    if stage1["task_count"] != len(stage1["tasks"]):
        raise EnterpriseCorpusError("Stage 1 projection task count is inconsistent")
    recovery_task_work_ids = {
        str(item.get("work_id", ""))
        for item in stage1["tasks"]
        if item.get("task_state") == RECOVERY_TASK_STATE
    }
    if recovery_task_work_ids != recovery_work_ids:
        raise EnterpriseCorpusError("Stage 1 recovery task projection is not total")
    gates["stage1_projection"] = "PASS"

    source_paths = (
        Path(__file__).with_name("mutable_corpus_enterprise.py"),
        Path(__file__).with_name("mutable_corpus_runtime.py"),
        Path(__file__).with_name("mutable_corpus_consumer.py"),
    )
    source = "".join(path.read_text(encoding="utf-8") for path in source_paths)
    forbidden = (
        "exact_filename_" + "number",
        "configured_review_" + "record_count",
        "range(1," + " 33)",
    )
    found = [token for token in forbidden if token in source]
    if found:
        raise EnterpriseCorpusError(f"forbidden fixed-corpus coupling found: {', '.join(found)}")
    gates["fixed_count_and_filename_identity_prohibition"] = "PASS"
    return gates
