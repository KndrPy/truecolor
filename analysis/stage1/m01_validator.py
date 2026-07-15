from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from analysis.prior_art.mutable_corpus_enterprise import EnterpriseCorpusError


class M01ValidationError(EnterpriseCorpusError):
    """Raised when S1-M01 cannot prove a required invariant."""


@dataclass(frozen=True)
class PhysicalFileRecordIR:
    file_id: str
    relative_path: str
    binary_sha256: str


@dataclass(frozen=True)
class DocumentVersionRecordIR:
    version_id: str
    work_id: str
    file_id: str
    current_state: str


@dataclass(frozen=True)
class ScientificWorkRecordIR:
    work_id: str
    file_ids: tuple[str, ...]
    preferred_file_id: str


@dataclass(frozen=True)
class CorpusChangeEventIR:
    event_id: str
    event_type: str
    file_id: str


@dataclass(frozen=True)
class LifecycleRecordIR:
    file_id: str
    current_state: str


@dataclass(frozen=True)
class IdentityIssueIR:
    issue_id: str
    state: str
    file_ids: tuple[str, ...]
    work_ids: tuple[str, ...]


@dataclass(frozen=True)
class MissingSourceCandidateIR:
    state: str
    source_key: str


REQUIRED_ROOT_ARTIFACTS = (
    "corpus_snapshot.json",
    "corpus_preflight_report.json",
    "physical_file_registry.json",
    "physical_file_version_registry.json",
    "document_version_registry.json",
    "scientific_work_registry.json",
    "physical_file_lifecycle_registry.json",
    "exact_duplicate_report.json",
    "version_family_report.json",
    "ambiguous_identity_queue.json",
    "missing_reference_candidates.json",
    "stage1_review_queue_projection.json",
    "corpus_change_set.json",
    "artifact_hashes.json",
)


def load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise M01ValidationError(f"invalid JSON artifact {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise M01ValidationError(f"artifact root must be an object: {path}")
    return value


def records(value: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    result = value.get("records", [])
    if not isinstance(result, list) or any(not isinstance(item, Mapping) for item in result):
        raise M01ValidationError(f"{name} must contain an object records array")
    return list(result)


def _required_text(record: Mapping[str, Any], key: str, context: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise M01ValidationError(f"{context} requires non-empty {key}")
    return value


def _unique(values: Iterable[str], context: str) -> set[str]:
    items = list(values)
    if len(items) != len(set(items)):
        raise M01ValidationError(f"duplicate identity in {context}")
    return set(items)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_prior_snapshot(value: Mapping[str, Any]) -> None:
    if value.get("schema") != "qudipi.mutable-corpus.snapshot":
        raise M01ValidationError("prior snapshot has unsupported schema")
    _required_text(value, "snapshot_id", "prior snapshot")
    files = value.get("files")
    works = value.get("works")
    if not isinstance(files, list) or not isinstance(works, list):
        raise M01ValidationError("prior snapshot requires files and works arrays")
    file_ids = _unique(
        _required_text(item, "file_id", "prior snapshot file")
        for item in files
        if isinstance(item, Mapping)
    )
    if len(file_ids) != len(files):
        raise M01ValidationError("prior snapshot contains malformed file records")


def validate_m01_artifacts(output_root: Path) -> Mapping[str, str]:
    missing = [name for name in REQUIRED_ROOT_ARTIFACTS if not (output_root / name).is_file()]
    if missing:
        raise M01ValidationError("required M01 artifacts absent: " + ", ".join(missing))

    preflight = records(load_json(output_root / "corpus_preflight_report.json"), "preflight")
    accepted_paths = {
        _required_text(item, "relative_path", "preflight record")
        for item in preflight
        if item.get("state") == "ACCEPTED"
    }
    rejected_without_reason = [
        item.get("relative_path", "")
        for item in preflight
        if item.get("state") != "ACCEPTED" and not item.get("reasons")
    ]
    if rejected_without_reason:
        raise M01ValidationError("rejected preflight records lack reasons")

    physical_raw = records(load_json(output_root / "physical_file_registry.json"), "physical registry")
    physical = [
        PhysicalFileRecordIR(
            file_id=_required_text(item, "file_id", "physical record"),
            relative_path=_required_text(item, "relative_path", "physical record"),
            binary_sha256=_required_text(item, "binary_sha256", "physical record"),
        )
        for item in physical_raw
    ]
    physical_ids = _unique((item.file_id for item in physical), "physical registry")
    physical_paths = _unique((item.relative_path for item in physical), "physical paths")
    if accepted_paths != physical_paths:
        omitted = sorted(accepted_paths - physical_paths)
        unexpected = sorted(physical_paths - accepted_paths)
        raise M01ValidationError(
            f"preflight/physical totality failed omitted={omitted} unexpected={unexpected}"
        )

    bindings_raw = records(
        load_json(output_root / "physical_file_version_registry.json"),
        "physical/version bindings",
    )
    binding_file_ids = [
        _required_text(item, "file_id", "physical/version binding") for item in bindings_raw
    ]
    if len(binding_file_ids) != len(set(binding_file_ids)):
        raise M01ValidationError("physical file has more than one version binding")
    if set(binding_file_ids) != physical_ids:
        raise M01ValidationError("physical-file/version binding is not total")

    versions_raw = records(load_json(output_root / "document_version_registry.json"), "version registry")
    versions = [
        DocumentVersionRecordIR(
            version_id=_required_text(item, "version_id", "version record"),
            work_id=_required_text(item, "work_id", "version record"),
            file_id=_required_text(item, "file_id", "version record"),
            current_state=_required_text(item, "current_state", "version record"),
        )
        for item in versions_raw
    ]
    version_ids = _unique((item.version_id for item in versions), "version registry")
    if {item.file_id for item in versions} != physical_ids:
        raise M01ValidationError("version registry does not cover every physical file exactly once")

    works_raw = records(load_json(output_root / "scientific_work_registry.json"), "work registry")
    works = [
        ScientificWorkRecordIR(
            work_id=_required_text(item, "work_id", "work record"),
            file_ids=tuple(str(value) for value in item.get("file_ids", [])),
            preferred_file_id=_required_text(item, "preferred_file_id", "work record"),
        )
        for item in works_raw
    ]
    work_ids = _unique((item.work_id for item in works), "scientific work registry")
    represented_files: list[str] = []
    for work in works:
        if not work.file_ids:
            raise M01ValidationError(f"scientific work has no files: {work.work_id}")
        if work.preferred_file_id not in work.file_ids:
            raise M01ValidationError(f"preferred file outside work: {work.work_id}")
        if not set(work.file_ids) <= physical_ids:
            raise M01ValidationError(f"work references unknown physical file: {work.work_id}")
        represented_files.extend(work.file_ids)
    if set(represented_files) != physical_ids:
        raise M01ValidationError("scientific works do not represent every physical file")
    if len(represented_files) != len(set(represented_files)):
        raise M01ValidationError("physical file is assigned to multiple scientific works")
    for version in versions:
        if version.work_id not in work_ids:
            raise M01ValidationError(f"version references unknown work: {version.version_id}")
        if version.file_id not in physical_ids:
            raise M01ValidationError(f"version references unknown file: {version.version_id}")
    for binding in bindings_raw:
        if binding.get("version_id") not in version_ids or binding.get("work_id") not in work_ids:
            raise M01ValidationError("binding references unknown version or work")

    ambiguous_raw = records(load_json(output_root / "ambiguous_identity_queue.json"), "ambiguity queue")
    issues = [
        IdentityIssueIR(
            issue_id=_required_text(item, "issue_id", "identity issue"),
            state=_required_text(item, "state", "identity issue"),
            file_ids=tuple(str(value) for value in item.get("file_ids", [])),
            work_ids=tuple(str(value) for value in item.get("work_ids", [])),
        )
        for item in ambiguous_raw
    ]
    _unique((item.issue_id for item in issues), "identity issue queue")
    for issue in issues:
        if issue.state != "AMBIGUOUS_IDENTITY":
            raise M01ValidationError("ambiguity queue contains a non-ambiguous state")
        if not set(issue.file_ids) <= physical_ids or not set(issue.work_ids) <= work_ids:
            raise M01ValidationError("identity issue references unknown records")
    ambiguous_version_works = {
        item.work_id for item in versions if item.current_state == "AMBIGUOUS_IDENTITY"
    }
    issue_work_ids = {work_id for issue in issues for work_id in issue.work_ids}
    if not ambiguous_version_works <= issue_work_ids:
        raise M01ValidationError("ambiguous version state lacks explicit identity issue")

    lifecycle_raw = records(
        load_json(output_root / "physical_file_lifecycle_registry.json"), "lifecycle registry"
    )
    lifecycle_ids = [
        _required_text(item, "file_id", "lifecycle record") for item in lifecycle_raw
    ]
    if len(lifecycle_ids) != len(set(lifecycle_ids)):
        raise M01ValidationError("duplicate lifecycle identity")
    if not physical_ids <= set(lifecycle_ids):
        raise M01ValidationError("current physical file lacks lifecycle record")

    change_set = records(load_json(output_root / "corpus_change_set.json"), "change set")
    removed_ids = {
        _required_text(item, "file_id", "removal event")
        for item in change_set
        if item.get("event_type") == "FILE_REMOVED"
    }
    lifecycle_by_id = {item["file_id"]: item for item in lifecycle_raw}
    for file_id in removed_ids:
        lifecycle = lifecycle_by_id.get(file_id)
        if lifecycle is None or lifecycle.get("current_state") != "REMOVED":
            raise M01ValidationError(f"removed file not preserved in lifecycle: {file_id}")

    projection = load_json(output_root / "stage1_review_queue_projection.json")
    tasks = projection.get("tasks", [])
    if not isinstance(tasks, list) or projection.get("task_count") != len(tasks):
        raise M01ValidationError("Stage 1 projection count is inconsistent")
    task_work_ids = [_required_text(item, "work_id", "Stage 1 task") for item in tasks]
    if len(task_work_ids) != len(set(task_work_ids)):
        raise M01ValidationError("Stage 1 projection has duplicate work tasks")
    if set(task_work_ids) != work_ids:
        raise M01ValidationError("Stage 1 projection is not total over current works")
    for task in tasks:
        if not set(task.get("file_ids", [])) <= physical_ids:
            raise M01ValidationError("Stage 1 task references unknown file")
        if not set(task.get("version_ids", [])) <= version_ids:
            raise M01ValidationError("Stage 1 task references unknown version")

    missing_raw = records(
        load_json(output_root / "missing_reference_candidates.json"), "missing candidates"
    )
    allowed_missing_states = {
        "EXPECTED_REFERENCE_MISSING",
        "PREVIOUSLY_PRESENT_NOW_REMOVED",
        "PUBLISHED_VERSION_NOT_FOUND",
        "CITED_WORK_NOT_INGESTED",
        "IDENTIFIER_KNOWN_FILE_ABSENT",
    }
    for item in missing_raw:
        state = _required_text(item, "state", "missing source candidate")
        if state not in allowed_missing_states:
            raise M01ValidationError(f"unknown missing-source state: {state}")

    hash_manifest = load_json(output_root / "artifact_hashes.json")
    manifest_records = hash_manifest.get("records", hash_manifest.get("artifacts", []))
    if isinstance(manifest_records, Mapping):
        expected_hashes = {str(key): str(value) for key, value in manifest_records.items()}
    elif isinstance(manifest_records, list):
        expected_hashes = {
            str(item.get("path", item.get("artifact", item.get("name", "")))): str(
                item.get("sha256", "")
            )
            for item in manifest_records
            if isinstance(item, Mapping)
        }
    else:
        raise M01ValidationError("artifact hash manifest has unsupported shape")
    if not expected_hashes:
        raise M01ValidationError("artifact hash manifest is empty")
    verified = 0
    for relative, expected in expected_hashes.items():
        candidate = output_root / relative
        if candidate.name == "artifact_hashes.json" or not candidate.is_file() or not expected:
            continue
        if _sha256(candidate) != expected:
            raise M01ValidationError(f"artifact hash mismatch: {relative}")
        verified += 1
    if verified == 0:
        raise M01ValidationError("artifact hash manifest did not verify any artifact")

    return {
        "accepted_file_totality": "PASS",
        "physical_identity_uniqueness": "PASS",
        "physical_version_totality": "PASS",
        "version_work_referential_integrity": "PASS",
        "work_file_partition_integrity": "PASS",
        "removal_history_preservation": "PASS",
        "ambiguity_explicitness": "PASS",
        "stage1_projection_totality": "PASS",
        "missing_candidate_state_integrity": "PASS",
        "artifact_hash_integrity": "PASS",
    }
