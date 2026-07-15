from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from analysis.prior_art.mutable_corpus_enterprise import (
    SCHEMA_VERSION,
    EnterpriseCorpusPolicy,
    append_event_ledger,
    artifact_hash_manifest,
    atomic_write_json,
    canonical_json,
    run_enterprise_reconciliation,
    stable_id,
    validate_projection_integrity,
)
from analysis.prior_art.mutable_corpus_service import (
    changed_source_ids,
    invalidate_dependencies,
    load_snapshot,
)


def load_optional(path: Path | None) -> Mapping[str, Any] | None:
    return load_snapshot(path) if path and path.is_file() else None


def expected_sources_from_review_csv(path: Path | None) -> Mapping[str, Any] | None:
    if path is None or not path.is_file():
        return None
    records = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            records.append(
                {
                    "source_id": row.get("canonical_identity", ""),
                    "title": row.get("title", ""),
                    "doi": row.get("doi", ""),
                    "pmid": row.get("pmid", ""),
                    "required": True,
                    "origin": path.as_posix(),
                }
            )
    return {"schema_version": SCHEMA_VERSION, "records": records}


def merge_expected_sources(
    explicit: Mapping[str, Any] | None,
    review: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    records = []
    for source in (explicit, review):
        if source:
            records.extend(source.get("records", source.get("sources", [])))
    if not records:
        return None
    deduplicated = {}
    for record in records:
        key = canonical_json(
            {
                "source_id": record.get("source_id", ""),
                "doi": record.get("doi", ""),
                "pmid": record.get("pmid", ""),
                "title": record.get("title", ""),
            }
        )
        deduplicated[key] = record
    return {
        "schema_version": SCHEMA_VERSION,
        "records": [deduplicated[key] for key in sorted(deduplicated)],
    }


def relationship_key(record: Mapping[str, Any]) -> str:
    return canonical_json(
        {
            "type": record.get("relationship_type", ""),
            "left": record.get("left_version_id", ""),
            "right": record.get("right_version_id", ""),
        }
    )


def relationship_change_events(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    previous_records = previous.get("records", []) if previous else []
    current_records = current.get("records", [])
    previous_by_key = {relationship_key(record): record for record in previous_records}
    current_by_key = {relationship_key(record): record for record in current_records}
    events = []
    for key in sorted(current_by_key.keys() - previous_by_key.keys()):
        record = current_by_key[key]
        event_type = (
            "DUPLICATE_DETECTED"
            if record.get("relationship_type") == "EXACT_FILE_DUPLICATE"
            else "VERSION_FAMILY_CHANGED"
        )
        events.append(
            {
                "event_type": event_type,
                "change_type": "RELATIONSHIP_ADDED",
                "relationship_id": record.get("relationship_id", ""),
                "relationship_type": record.get("relationship_type", ""),
                "left_version_id": record.get("left_version_id", ""),
                "right_version_id": record.get("right_version_id", ""),
            }
        )
    for key in sorted(previous_by_key.keys() - current_by_key.keys()):
        record = previous_by_key[key]
        event_type = (
            "DUPLICATE_RESOLVED"
            if record.get("relationship_type") == "EXACT_FILE_DUPLICATE"
            else "VERSION_FAMILY_CHANGED"
        )
        events.append(
            {
                "event_type": event_type,
                "change_type": "RELATIONSHIP_REMOVED",
                "relationship_id": record.get("relationship_id", ""),
                "relationship_type": record.get("relationship_type", ""),
                "left_version_id": record.get("left_version_id", ""),
                "right_version_id": record.get("right_version_id", ""),
            }
        )
    return tuple(events)


def build_physical_lifecycle_registry(
    previous: Mapping[str, Any] | None,
    current_snapshot: Mapping[str, Any],
    observed_at: str,
) -> Mapping[str, Any]:
    prior = {
        record["file_id"]: dict(record)
        for record in (previous.get("records", []) if previous else [])
    }
    current_ids = set()
    for file_record in current_snapshot.get("files", []):
        file_id = file_record["file_id"]
        current_ids.add(file_id)
        record = prior.get(
            file_id,
            {
                "file_id": file_id,
                "first_seen_at": observed_at,
                "path_history": [],
                "binary_sha256_history": [],
            },
        )
        path = file_record["relative_path"]
        binary_hash = file_record["binary_sha256"]
        if not record["path_history"] or record["path_history"][-1]["path"] != path:
            record["path_history"].append({"path": path, "observed_at": observed_at})
        if (
            not record["binary_sha256_history"]
            or record["binary_sha256_history"][-1]["binary_sha256"] != binary_hash
        ):
            record["binary_sha256_history"].append(
                {"binary_sha256": binary_hash, "observed_at": observed_at}
            )
        record.update(
            {
                "current_state": "PRESENT",
                "current_path": path,
                "current_binary_sha256": binary_hash,
                "last_seen_at": observed_at,
                "removed_at": "",
            }
        )
        prior[file_id] = record
    for file_id, record in prior.items():
        if file_id not in current_ids and record.get("current_state") == "PRESENT":
            record["current_state"] = "REMOVED"
            record["removed_at"] = observed_at
    return {
        "schema": "qudipi.mutable-corpus.physical-file-lifecycle-registry",
        "schema_version": SCHEMA_VERSION,
        "records": [prior[file_id] for file_id in sorted(prior)],
    }


def _relationship_event_source_ids(
    events: Sequence[Mapping[str, Any]],
    version_registry: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    file_by_version = {
        record["version_id"]: record["file_id"]
        for record in version_registry.get("records", [])
    }
    enriched = []
    for event in events:
        value = dict(event)
        source_ids = sorted(
            {
                file_by_version.get(str(event.get("left_version_id", "")), ""),
                file_by_version.get(str(event.get("right_version_id", "")), ""),
            }
            - {""}
        )
        if source_ids:
            value["source_file_ids"] = source_ids
            value["file_id"] = source_ids[0]
        enriched.append(value)
    return tuple(enriched)


def run_runtime(
    corpus_root: Path,
    output_root: Path,
    policy: EnterpriseCorpusPolicy,
    expected_sources: Mapping[str, Any] | None,
    dependency_manifest: Mapping[str, Any] | None,
    observed_at: str | None,
    backend: Any = None,
) -> Mapping[str, Any]:
    output_root = output_root.resolve()
    previous_family = load_optional(output_root / "version_family_report.json")
    previous_duplicates = load_optional(output_root / "exact_duplicate_report.json")
    previous_lifecycle = load_optional(output_root / "physical_file_lifecycle_registry.json")
    result = run_enterprise_reconciliation(
        corpus_root,
        output_root,
        policy=policy,
        expected_sources=expected_sources,
        dependency_manifest=dependency_manifest,
        backend=backend,
        observed_at=observed_at,
    )
    snapshot = load_snapshot(output_root / "corpus_snapshot.json")
    version_registry = load_snapshot(output_root / "document_version_registry.json")
    current_family = load_snapshot(output_root / "version_family_report.json")
    current_duplicates = load_snapshot(output_root / "exact_duplicate_report.json")
    change_set = load_snapshot(output_root / "corpus_change_set.json")
    relationship_events = (
        relationship_change_events(previous_family, current_family)
        + relationship_change_events(previous_duplicates, current_duplicates)
    )
    relationship_events = _relationship_event_source_ids(
        relationship_events, version_registry
    )
    all_events = tuple(change_set.get("events", [])) + relationship_events
    all_events = tuple(
        sorted(
            {canonical_json(event): event for event in all_events}.values(),
            key=lambda event: (
                str(event.get("event_type", "")),
                str(event.get("file_id", "")),
                str(event.get("relationship_id", "")),
            ),
        )
    )
    atomic_write_json(
        output_root / "corpus_change_set.json",
        {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot["snapshot_id"],
            "events": all_events,
        },
    )
    stale = invalidate_dependencies(all_events, dependency_manifest)
    atomic_write_json(
        output_root / "stale_downstream_artifact_report.json",
        {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot["snapshot_id"],
            "records": stale,
        },
    )
    lifecycle = build_physical_lifecycle_registry(
        previous_lifecycle,
        snapshot,
        snapshot["observed_at"],
    )
    atomic_write_json(output_root / "physical_file_lifecycle_registry.json", lifecycle)
    append_event_ledger(output_root, snapshot["snapshot_id"], all_events)
    run_manifest = {
        "schema": "qudipi.mutable-corpus.run-manifest",
        "schema_version": SCHEMA_VERSION,
        "run_id": stable_id(
            "RUN",
            {
                "snapshot_id": snapshot["snapshot_id"],
                "observed_at": snapshot["observed_at"],
                "event_count": len(all_events),
            },
        ),
        "snapshot_id": snapshot["snapshot_id"],
        "observed_at": snapshot["observed_at"],
        "input": {
            "corpus_root": str(corpus_root.resolve()),
            "policy_sha256": stable_id("POLICY", asdict(policy)),
            "expected_source_count": len(expected_sources.get("records", []))
            if expected_sources
            else 0,
        },
        "output": {
            "event_count": len(all_events),
            "changed_source_count": len(changed_source_ids(all_events)),
            "stale_artifact_count": len(stale),
            "physical_lifecycle_record_count": len(lifecycle["records"]),
        },
    }
    atomic_write_json(output_root / "reconciliation_run_manifest.json", run_manifest)
    artifact_hash_manifest(output_root)
    validate_projection_integrity(output_root)
    return {
        **result,
        "event_count": len(all_events),
        "stale_artifact_count": len(stale),
        "run_id": run_manifest["run_id"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run QuDiPi's durable mutable-corpus reconciliation capability."
    )
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--policy")
    parser.add_argument("--expected-sources")
    parser.add_argument("--prior-review-csv")
    parser.add_argument("--dependency-manifest")
    parser.add_argument("--observed-at")
    args = parser.parse_args()
    policy = EnterpriseCorpusPolicy.from_mapping(
        load_optional(Path(args.policy)) if args.policy else None
    )
    explicit = load_optional(Path(args.expected_sources)) if args.expected_sources else None
    review = expected_sources_from_review_csv(
        Path(args.prior_review_csv) if args.prior_review_csv else None
    )
    expected = merge_expected_sources(explicit, review)
    dependencies = (
        load_optional(Path(args.dependency_manifest))
        if args.dependency_manifest
        else None
    )
    result = run_runtime(
        Path(args.corpus_root),
        Path(args.output_root),
        policy,
        expected,
        dependencies,
        args.observed_at,
    )
    print("QUDIPI_MUTABLE_CORPUS_RUNTIME=PASS")
    print(f"run_id={result['run_id']}")
    print(f"snapshot_id={result['snapshot_id']}")
    print(f"event_count={result['event_count']}")
    print(f"stale_artifact_count={result['stale_artifact_count']}")


if __name__ == "__main__":
    main()
