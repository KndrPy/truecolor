from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from analysis.prior_art.mutable_corpus import (
    SCHEMA_VERSION,
    CorpusPolicy,
    CorpusSnapshot,
    ExtractionBackend,
    PhysicalFileRecord,
    PopplerExtractionBackend,
    Relationship,
    build_works,
    discover_files,
    extract_referenced_dois,
    infer_identity,
    invalidated_artifacts,
    load_snapshot,
    normalized_text,
    relationship_between,
    sha256_bytes,
    sha256_file,
    simhash64,
)


class CorpusReconciliationError(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def path_file_id(relative_path: str) -> str:
    return f"FILE-{sha256_bytes(relative_path.encode('utf-8'))[:20]}"


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def validate_snapshot(snapshot: CorpusSnapshot) -> None:
    file_ids = [record.file_id for record in snapshot.files]
    paths = [record.relative_path for record in snapshot.files]
    work_ids = [record.work_id for record in snapshot.works]
    if len(file_ids) != len(set(file_ids)):
        raise CorpusReconciliationError("physical file IDs are not unique")
    if len(paths) != len(set(paths)):
        raise CorpusReconciliationError("physical file paths are not unique")
    if len(work_ids) != len(set(work_ids)):
        raise CorpusReconciliationError("scientific work IDs are not unique")
    known_files = set(file_ids)
    for relationship in snapshot.relationships:
        if relationship.left_file_id not in known_files or relationship.right_file_id not in known_files:
            raise CorpusReconciliationError("relationship references an unknown physical file")
        if relationship.left_file_id == relationship.right_file_id:
            raise CorpusReconciliationError("self-referential document relationship")
    for work in snapshot.works:
        if not work.file_ids:
            raise CorpusReconciliationError(f"work has no physical files: {work.work_id}")
        if work.preferred_file_id not in work.file_ids:
            raise CorpusReconciliationError(f"preferred file is outside work family: {work.work_id}")
        if not set(work.file_ids) <= known_files:
            raise CorpusReconciliationError(f"work references an unknown physical file: {work.work_id}")


def _missing_references(records: Sequence[PhysicalFileRecord], works: Sequence[Any]) -> tuple[Mapping[str, Any], ...]:
    corpus_dois = {doi for work in works for doi in work.canonical_dois}
    citations: dict[str, set[str]] = {}
    for record in records:
        for doi in record.cited_dois:
            if doi not in corpus_dois:
                citations.setdefault(doi, set()).add(record.file_id)
    return tuple(
        {
            "doi": doi,
            "state": "CITED_WORK_NOT_INGESTED",
            "citing_file_ids": sorted(file_ids),
            "citation_count": len(file_ids),
        }
        for doi, file_ids in sorted(citations.items())
    )


def reconcile_corpus(
    root: Path,
    output_root: Path,
    policy: CorpusPolicy | None = None,
    backend: ExtractionBackend | None = None,
    observed_at: str | None = None,
) -> CorpusSnapshot:
    policy = policy or CorpusPolicy()
    backend = backend or PopplerExtractionBackend()
    root = root.resolve()
    output_root = output_root.resolve()
    observed_at = observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    records: list[PhysicalFileRecord] = []
    for path in discover_files(root, policy):
        relative_path = path.relative_to(root).as_posix()
        binary_hash = sha256_file(path)
        extracted = backend.extract(path)
        identity = infer_identity(path, extracted)
        normalized = normalized_text(extracted.text)
        records.append(
            PhysicalFileRecord(
                file_id=path_file_id(relative_path),
                relative_path=relative_path,
                size_bytes=path.stat().st_size,
                binary_sha256=binary_hash,
                normalized_text_sha256=sha256_bytes(normalized.encode("utf-8")) if normalized else "",
                simhash64=simhash64(normalized),
                page_count=extracted.page_count,
                extraction_backend=extracted.extraction_backend,
                extraction_state=(
                    "EXTRACTED"
                    if len(normalized) >= policy.minimum_text_characters
                    else "INSUFFICIENT_TEXT"
                ),
                extraction_errors=extracted.extraction_errors,
                identity=identity,
                cited_dois=extract_referenced_dois(extracted.text, identity.dois, policy),
            )
        )

    relationships: list[Relationship] = []
    for index, left in enumerate(records):
        for right in records[index + 1 :]:
            relationship = relationship_between(left, right, policy)
            if relationship is not None:
                relationships.append(relationship)
    relationships.sort(
        key=lambda item: (
            item.relationship_type,
            item.left_file_id,
            item.right_file_id,
        )
    )
    works = build_works(records, relationships)
    missing = _missing_references(records, works)
    summary = {
        "physical_file_count": len(records),
        "scientific_work_count": len(works),
        "exact_duplicate_count": sum(
            relationship.relationship_type == "EXACT_FILE_DUPLICATE"
            for relationship in relationships
        ),
        "same_work_version_relationship_count": sum(
            relationship.relationship_type.startswith("SAME_WORK")
            for relationship in relationships
        ),
        "related_work_relationship_count": sum(
            relationship.relationship_type == "RELATED_WORK"
            for relationship in relationships
        ),
        "insufficient_text_count": sum(
            record.extraction_state != "EXTRACTED" for record in records
        ),
        "missing_reference_candidate_count": len(missing),
    }
    canonical_payload = {
        "files": [asdict(record) for record in records],
        "works": [asdict(work) for work in works],
        "relationships": [asdict(relationship) for relationship in relationships],
        "policy": asdict(policy),
    }
    snapshot_id = (
        "SNAPSHOT-"
        + sha256_bytes(canonical_json(canonical_payload).encode("utf-8"))[:24]
    )
    snapshot = CorpusSnapshot(
        schema="qudipi.mutable-corpus.snapshot",
        schema_version=SCHEMA_VERSION,
        corpus_root=str(root),
        snapshot_id=snapshot_id,
        observed_at=observed_at,
        files=tuple(records),
        works=works,
        relationships=tuple(relationships),
        missing_reference_candidates=missing,
        summary=summary,
    )
    validate_snapshot(snapshot)
    write_projection_set(output_root, snapshot, policy)
    return snapshot


def compare_snapshot_states(
    previous: Mapping[str, Any] | None,
    current: CorpusSnapshot,
) -> tuple[Mapping[str, Any], ...]:
    if not previous:
        return tuple(
            {
                "event_type": "FILE_ADDED",
                "file_id": record.file_id,
                "relative_path": record.relative_path,
                "binary_sha256": record.binary_sha256,
            }
            for record in current.files
        )

    previous_files = {item["file_id"]: item for item in previous.get("files", [])}
    current_files = {item.file_id: item for item in current.files}
    removed_ids = set(previous_files) - set(current_files)
    added_ids = set(current_files) - set(previous_files)
    removed_by_hash: dict[str, list[str]] = {}
    added_by_hash: dict[str, list[str]] = {}
    for file_id in removed_ids:
        removed_by_hash.setdefault(previous_files[file_id]["binary_sha256"], []).append(file_id)
    for file_id in added_ids:
        added_by_hash.setdefault(current_files[file_id].binary_sha256, []).append(file_id)

    events: list[Mapping[str, Any]] = []
    consumed_removed: set[str] = set()
    consumed_added: set[str] = set()
    for binary_hash in sorted(set(removed_by_hash) & set(added_by_hash)):
        old_ids = sorted(removed_by_hash[binary_hash])
        new_ids = sorted(added_by_hash[binary_hash])
        for old_id, new_id in zip(old_ids, new_ids, strict=False):
            consumed_removed.add(old_id)
            consumed_added.add(new_id)
            events.append(
                {
                    "event_type": "FILE_MOVED",
                    "previous_file_id": old_id,
                    "file_id": new_id,
                    "previous_path": previous_files[old_id]["relative_path"],
                    "relative_path": current_files[new_id].relative_path,
                    "binary_sha256": binary_hash,
                }
            )

    for file_id in sorted(added_ids - consumed_added):
        record = current_files[file_id]
        events.append(
            {
                "event_type": "FILE_ADDED",
                "file_id": file_id,
                "relative_path": record.relative_path,
                "binary_sha256": record.binary_sha256,
            }
        )
    for file_id in sorted(removed_ids - consumed_removed):
        record = previous_files[file_id]
        events.append(
            {
                "event_type": "FILE_REMOVED",
                "file_id": file_id,
                "relative_path": record["relative_path"],
                "binary_sha256": record["binary_sha256"],
            }
        )
    for file_id in sorted(set(previous_files) & set(current_files)):
        before = previous_files[file_id]
        after = current_files[file_id]
        if before["binary_sha256"] != after.binary_sha256:
            events.append(
                {
                    "event_type": "FILE_REPLACED",
                    "file_id": file_id,
                    "relative_path": after.relative_path,
                    "previous_binary_sha256": before["binary_sha256"],
                    "binary_sha256": after.binary_sha256,
                }
            )
        elif before.get("identity") != asdict(after.identity):
            events.append(
                {
                    "event_type": "IDENTITY_CHANGED",
                    "file_id": file_id,
                    "relative_path": after.relative_path,
                }
            )
    return tuple(
        sorted(
            events,
            key=lambda item: (
                str(item["event_type"]),
                str(item.get("relative_path", "")),
                str(item.get("file_id", "")),
            ),
        )
    )


def write_projection_set(
    output_root: Path,
    snapshot: CorpusSnapshot,
    policy: CorpusPolicy,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    payload = asdict(snapshot)
    projections = {
        "corpus_snapshot.json": payload,
        "physical_file_registry.json": {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot.snapshot_id,
            "records": payload["files"],
        },
        "scientific_work_registry.json": {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot.snapshot_id,
            "records": payload["works"],
        },
        "document_relationships.json": {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot.snapshot_id,
            "records": payload["relationships"],
        },
        "missing_reference_candidates.json": {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot.snapshot_id,
            "records": payload["missing_reference_candidates"],
        },
        "corpus_policy_effective.json": asdict(policy),
    }
    for name, value in projections.items():
        atomic_write_json(output_root / name, value)


def run_reconciliation(
    corpus_root: Path,
    output_root: Path,
    policy: CorpusPolicy,
    previous_snapshot: Mapping[str, Any] | None,
    dependency_manifest: Mapping[str, Any] | None,
    observed_at: str | None,
    backend: ExtractionBackend | None = None,
) -> CorpusSnapshot:
    snapshot = reconcile_corpus(
        corpus_root,
        output_root,
        policy=policy,
        backend=backend,
        observed_at=observed_at,
    )
    events = compare_snapshot_states(previous_snapshot, snapshot)
    stale = invalidated_artifacts(events, dependency_manifest)
    atomic_write_json(
        output_root / "corpus_change_set.json",
        {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot.snapshot_id,
            "events": events,
        },
    )
    atomic_write_json(
        output_root / "stale_downstream_artifact_report.json",
        {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot.snapshot_id,
            "records": stale,
        },
    )
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile an unordered, researcher-controlled scientific PDF corpus."
    )
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--policy")
    parser.add_argument("--previous-snapshot")
    parser.add_argument("--dependency-manifest")
    parser.add_argument("--observed-at")
    args = parser.parse_args()

    policy_mapping = load_snapshot(Path(args.policy)) if args.policy else None
    previous = load_snapshot(Path(args.previous_snapshot)) if args.previous_snapshot else None
    dependencies = load_snapshot(Path(args.dependency_manifest)) if args.dependency_manifest else None
    policy = CorpusPolicy.from_mapping(policy_mapping)
    snapshot = run_reconciliation(
        Path(args.corpus_root),
        Path(args.output_root),
        policy,
        previous,
        dependencies,
        args.observed_at,
    )
    change_set = load_snapshot(Path(args.output_root) / "corpus_change_set.json")
    stale = load_snapshot(Path(args.output_root) / "stale_downstream_artifact_report.json")
    print("QUDIPI_MUTABLE_CORPUS_RECONCILIATION=PASS")
    print(f"snapshot_id={snapshot.snapshot_id}")
    for key, value in snapshot.summary.items():
        print(f"{key}={value}")
    print(f"change_event_count={len(change_set['events'])}")
    print(f"stale_downstream_artifact_count={len(stale['records'])}")


if __name__ == "__main__":
    main()
