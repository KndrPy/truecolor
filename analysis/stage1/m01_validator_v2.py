from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from analysis.prior_art.mutable_corpus_enterprise import EnterpriseCorpusError


class M01ValidationError(EnterpriseCorpusError):
    pass


REQUIRED = (
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


def _items(value: Mapping[str, Any], field: str, name: str) -> list[Mapping[str, Any]]:
    result = value.get(field, [])
    if not isinstance(result, list) or any(not isinstance(item, Mapping) for item in result):
        raise M01ValidationError(f"{name} must contain an object {field} array")
    return list(result)


def _text(record: Mapping[str, Any], key: str, context: str) -> str:
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
    _text(value, "snapshot_id", "prior snapshot")
    files = value.get("files")
    works = value.get("works")
    if not isinstance(files, list) or not isinstance(works, list):
        raise M01ValidationError("prior snapshot requires files and works arrays")
    if any(not isinstance(item, Mapping) for item in files):
        raise M01ValidationError("prior snapshot contains malformed file records")
    _unique((_text(item, "file_id", "prior snapshot file") for item in files), "prior snapshot")


def validate_m01_artifacts(output_root: Path) -> Mapping[str, str]:
    missing = [name for name in REQUIRED if not (output_root / name).is_file()]
    if missing:
        raise M01ValidationError("required M01 artifacts absent: " + ", ".join(missing))

    preflight = _items(load_json(output_root / "corpus_preflight_report.json"), "records", "preflight")
    accepted_paths = {
        _text(item, "relative_path", "preflight record")
        for item in preflight
        if item.get("state") == "ACCEPTED"
    }
    if any(item.get("state") != "ACCEPTED" and not item.get("reasons") for item in preflight):
        raise M01ValidationError("rejected preflight record lacks reasons")

    physical = _items(load_json(output_root / "physical_file_registry.json"), "records", "physical")
    physical_ids = _unique((_text(item, "file_id", "physical record") for item in physical), "physical")
    physical_paths = _unique(
        (_text(item, "relative_path", "physical record") for item in physical), "physical paths"
    )
    hashes = [_text(item, "binary_sha256", "physical record") for item in physical]
    if any(len(value) != 64 for value in hashes):
        raise M01ValidationError("physical record contains invalid SHA-256")
    if accepted_paths != physical_paths:
        raise M01ValidationError(
            "preflight/physical totality failed "
            f"omitted={sorted(accepted_paths - physical_paths)} "
            f"unexpected={sorted(physical_paths - accepted_paths)}"
        )

    bindings = _items(
        load_json(output_root / "physical_file_version_registry.json"), "records", "bindings"
    )
    binding_files = [_text(item, "file_id", "binding") for item in bindings]
    if len(binding_files) != len(set(binding_files)) or set(binding_files) != physical_ids:
        raise M01ValidationError("physical-file/version binding is not exactly total")

    versions = _items(load_json(output_root / "document_version_registry.json"), "records", "versions")
    version_ids = _unique((_text(item, "version_id", "version") for item in versions), "versions")
    version_files = [_text(item, "file_id", "version") for item in versions]
    if len(version_files) != len(set(version_files)) or set(version_files) != physical_ids:
        raise M01ValidationError("version registry is not exactly total over physical files")

    works = _items(load_json(output_root / "scientific_work_registry.json"), "records", "works")
    work_ids = _unique((_text(item, "work_id", "work") for item in works), "works")
    represented: list[str] = []
    for work in works:
        file_ids = work.get("file_ids", [])
        if not isinstance(file_ids, list) or not file_ids:
            raise M01ValidationError("scientific work must contain file_ids")
        preferred = _text(work, "preferred_file_id", "work")
        if preferred not in file_ids or not set(file_ids) <= physical_ids:
            raise M01ValidationError("scientific work has invalid file membership")
        represented.extend(str(value) for value in file_ids)
    if set(represented) != physical_ids or len(represented) != len(set(represented)):
        raise M01ValidationError("scientific works do not partition physical files")

    for version in versions:
        if version.get("work_id") not in work_ids or version.get("file_id") not in physical_ids:
            raise M01ValidationError("version references unknown work or file")
    for binding in bindings:
        if binding.get("version_id") not in version_ids or binding.get("work_id") not in work_ids:
            raise M01ValidationError("binding references unknown version or work")

    issues = _items(load_json(output_root / "ambiguous_identity_queue.json"), "records", "issues")
    issue_ids = _unique((_text(item, "issue_id", "identity issue") for item in issues), "issues")
    del issue_ids
    issue_work_ids: set[str] = set()
    for issue in issues:
        if issue.get("state") != "AMBIGUOUS_IDENTITY":
            raise M01ValidationError("ambiguity queue contains non-ambiguous state")
        if not set(issue.get("file_ids", [])) <= physical_ids:
            raise M01ValidationError("identity issue references unknown file")
        if not set(issue.get("work_ids", [])) <= work_ids:
            raise M01ValidationError("identity issue references unknown work")
        issue_work_ids.update(str(value) for value in issue.get("work_ids", []))
    ambiguous_work_ids = {
        str(item["work_id"])
        for item in versions
        if item.get("current_state") == "AMBIGUOUS_IDENTITY"
    }
    if not ambiguous_work_ids <= issue_work_ids:
        raise M01ValidationError("ambiguous version lacks explicit identity issue")

    lifecycle = _items(
        load_json(output_root / "physical_file_lifecycle_registry.json"), "records", "lifecycle"
    )
    lifecycle_ids = [_text(item, "file_id", "lifecycle") for item in lifecycle]
    if len(lifecycle_ids) != len(set(lifecycle_ids)) or not physical_ids <= set(lifecycle_ids):
        raise M01ValidationError("lifecycle registry is incomplete or duplicated")
    lifecycle_by_id = {str(item["file_id"]): item for item in lifecycle}
    change_events = _items(load_json(output_root / "corpus_change_set.json"), "events", "change set")
    for event in change_events:
        if event.get("event_type") == "FILE_REMOVED":
            file_id = _text(event, "file_id", "removal event")
            if lifecycle_by_id.get(file_id, {}).get("current_state") != "REMOVED":
                raise M01ValidationError(f"removed file not preserved in lifecycle: {file_id}")

    projection = load_json(output_root / "stage1_review_queue_projection.json")
    tasks = projection.get("tasks", [])
    if not isinstance(tasks, list) or any(not isinstance(item, Mapping) for item in tasks):
        raise M01ValidationError("Stage 1 projection tasks are malformed")
    if projection.get("task_count") != len(tasks):
        raise M01ValidationError("Stage 1 projection count is inconsistent")
    task_work_ids = [_text(item, "work_id", "Stage 1 task") for item in tasks]
    if len(task_work_ids) != len(set(task_work_ids)) or set(task_work_ids) != work_ids:
        raise M01ValidationError("Stage 1 projection is not exactly total over works")
    for task in tasks:
        if not set(task.get("file_ids", [])) <= physical_ids:
            raise M01ValidationError("Stage 1 task references unknown file")
        if not set(task.get("version_ids", [])) <= version_ids:
            raise M01ValidationError("Stage 1 task references unknown version")

    missing_candidates = _items(
        load_json(output_root / "missing_reference_candidates.json"), "records", "missing"
    )
    allowed_states = {
        "EXPECTED_REFERENCE_MISSING",
        "PREVIOUSLY_PRESENT_NOW_REMOVED",
        "PUBLISHED_VERSION_NOT_FOUND",
        "CITED_WORK_NOT_INGESTED",
        "IDENTIFIER_KNOWN_FILE_ABSENT",
    }
    if any(_text(item, "state", "missing candidate") not in allowed_states for item in missing_candidates):
        raise M01ValidationError("missing-source registry contains unknown state")

    root_hashes = load_json(output_root / "artifact_hashes.json")
    if not root_hashes or any(not isinstance(value, str) for value in root_hashes.values()):
        raise M01ValidationError("artifact hash manifest has unsupported shape")
    verified = 0
    for name, expected in root_hashes.items():
        path = output_root / str(name)
        if not path.is_file():
            raise M01ValidationError(f"hash manifest references absent artifact: {name}")
        if _sha256(path) != expected:
            raise M01ValidationError(f"artifact hash mismatch: {name}")
        verified += 1
    if verified == 0:
        raise M01ValidationError("artifact hash manifest did not verify artifacts")

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
