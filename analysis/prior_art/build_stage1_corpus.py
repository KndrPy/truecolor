from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


ROOT = Path("analysis/prior_art")

SOURCE_DIR = ROOT / "corpus/sources"
OVERLAP_DIR = ROOT / "corpus/overlaps"
SEARCH_DIR = ROOT / "corpus/search_executions"

SOURCE_SCHEMA = (
    ROOT / "schemas/prior_art_source.schema.json"
)
OVERLAP_SCHEMA = (
    ROOT / "schemas/claim_overlap.schema.json"
)
SEARCH_SCHEMA = (
    ROOT / "schemas/search_execution.schema.json"
)

CLAIM_REGISTRY = (
    ROOT / "registry/novelty_claim_registry.yaml"
)
QUERY_REGISTRY = (
    ROOT / "registry/search_query_registry.yaml"
)

SOURCE_REGISTRY = (
    ROOT / "registry/source_registry.yaml"
)
SEARCH_EXECUTION_REGISTRY = (
    ROOT / "registry/search_execution_registry.yaml"
)
OVERLAP_REGISTRY = (
    ROOT / "registry/claim_overlap_registry.yaml"
)


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(
        path.read_text(encoding="utf-8")
    )


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(value, dict):
        raise TypeError(
            f"Expected JSON object: {path}"
        )

    return value


def yaml_records(directory: Path) -> list[tuple[Path, dict[str, Any]]]:
    rows: list[tuple[Path, dict[str, Any]]] = []

    for path in sorted(directory.glob("*.yaml")):
        value = load_yaml(path)

        if not isinstance(value, dict):
            raise TypeError(
                f"Expected YAML mapping: {path}"
            )

        rows.append((path, value))

    return rows


def validate_records(
    records: list[tuple[Path, dict[str, Any]]],
    schema_path: Path,
) -> list[dict[str, Any]]:
    validator = Draft202012Validator(
        load_json(schema_path)
    )

    errors: list[dict[str, Any]] = []

    for path, record in records:
        record_errors = sorted(
            validator.iter_errors(record),
            key=lambda error: list(error.path),
        )

        for error in record_errors:
            errors.append({
                "file": str(path),
                "path": list(error.path),
                "message": error.message,
            })

    return errors


def duplicates(values: list[str]) -> list[str]:
    counts = Counter(values)

    return sorted(
        value
        for value, count in counts.items()
        if count > 1
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "results",
    )

    parser.add_argument(
        "--require-complete-search",
        action="store_true",
    )

    parser.add_argument(
        "--require-complete-overlap",
        action="store_true",
    )

    args = parser.parse_args()
    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    sources = yaml_records(SOURCE_DIR)
    overlaps = yaml_records(OVERLAP_DIR)
    searches = yaml_records(SEARCH_DIR)

    source_errors = validate_records(
        sources,
        SOURCE_SCHEMA,
    )

    overlap_errors = validate_records(
        overlaps,
        OVERLAP_SCHEMA,
    )

    search_errors = validate_records(
        searches,
        SEARCH_SCHEMA,
    )

    claim_registry = load_yaml(CLAIM_REGISTRY)
    query_registry = load_yaml(QUERY_REGISTRY)

    claim_ids = {
        row["claim_id"]
        for row in claim_registry["claims"]
    }

    query_by_id = {
        row["query_id"]: row
        for row in query_registry["query_families"]
    }

    required_domains = {
        row["domain"]
        for row in query_registry["query_families"]
    }

    source_rows = [
        row
        for _, row in sources
    ]

    overlap_rows = [
        row
        for _, row in overlaps
    ]

    search_rows = [
        row
        for _, row in searches
    ]

    source_ids = [
        row["source_id"]
        for row in source_rows
    ]

    canonical_keys = [
        row["canonical_key"].strip().lower()
        for row in source_rows
    ]

    overlap_keys = [
        (
            row["claim_id"],
            row["source_id"],
        )
        for row in overlap_rows
    ]

    search_ids = [
        row["execution_id"]
        for row in search_rows
    ]

    query_execution_ids = [
        row["query_family_id"]
        for row in search_rows
    ]

    source_id_set = set(source_ids)

    unresolved_source_references = sorted({
        row["source_id"]
        for row in overlap_rows
        if row["source_id"] not in source_id_set
    })

    unresolved_claim_references = sorted({
        row["claim_id"]
        for row in overlap_rows
        if row["claim_id"] not in claim_ids
    })

    invalid_search_query_references = sorted({
        row["query_family_id"]
        for row in search_rows
        if row["query_family_id"] not in query_by_id
    })

    unresolved_search_source_references = sorted({
        source_id
        for row in search_rows
        for source_id in row["included_source_ids"]
        if source_id not in source_id_set
    })

    search_domain_mismatches: list[dict[str, str]] = []

    for row in search_rows:
        query_id = row["query_family_id"]

        if query_id not in query_by_id:
            continue

        expected_domain = query_by_id[query_id][
            "domain"
        ]

        if row["domain"] != expected_domain:
            search_domain_mismatches.append({
                "execution_id": row[
                    "execution_id"
                ],
                "query_family_id": query_id,
                "expected_domain": expected_domain,
                "observed_domain": row["domain"],
            })

    completed_domains = {
        row["domain"]
        for row in search_rows
        if row["status"] == "COMPLETE"
    }

    completed_query_families = {
        row["query_family_id"]
        for row in search_rows
        if row["status"] == "COMPLETE"
    }

    overlap_by_claim: dict[str, set[str]] = defaultdict(
        set
    )

    for row in overlap_rows:
        overlap_by_claim[row["claim_id"]].add(
            row["source_id"]
        )

    claims_without_overlap_records = sorted(
        claim_id
        for claim_id in claim_ids
        if not overlap_by_claim[claim_id]
    )

    source_claim_references = {
        claim_id
        for row in source_rows
        for claim_id in row[
            "claims_addressed"
        ]
    }

    invalid_source_claim_references = sorted(
        source_claim_references - claim_ids
    )

    source_domain_references = {
        domain
        for row in source_rows
        for domain in row["domains"]
    }

    invalid_source_domain_references = sorted(
        source_domain_references
        - required_domains
    )

    gates = {
        "source_records_schema_valid": (
            not source_errors
        ),
        "overlap_records_schema_valid": (
            not overlap_errors
        ),
        "search_records_schema_valid": (
            not search_errors
        ),
        "source_ids_unique": (
            not duplicates(source_ids)
        ),
        "source_canonical_keys_unique": (
            not duplicates(canonical_keys)
        ),
        "overlap_pairs_unique": (
            not duplicates([
                f"{claim_id}|{source_id}"
                for claim_id, source_id
                in overlap_keys
            ])
        ),
        "search_execution_ids_unique": (
            not duplicates(search_ids)
        ),
        "overlap_source_references_resolved": (
            not unresolved_source_references
        ),
        "overlap_claim_references_resolved": (
            not unresolved_claim_references
        ),
        "source_claim_references_resolved": (
            not invalid_source_claim_references
        ),
        "source_domain_references_resolved": (
            not invalid_source_domain_references
        ),
        "search_query_references_resolved": (
            not invalid_search_query_references
        ),
        "search_source_references_resolved": (
            not unresolved_search_source_references
        ),
        "search_domains_match_query_registry": (
            not search_domain_mismatches
        ),
    }

    if args.require_complete_search:
        gates.update({
            "all_query_families_executed": (
                set(query_by_id)
                <= completed_query_families
            ),
            "all_domains_completed": (
                required_domains
                <= completed_domains
            ),
            "all_searches_include_backward_review": (
                bool(search_rows)
                and all(
                    row["backward_reference_search"]
                    for row in search_rows
                    if row["status"] == "COMPLETE"
                )
            ),
            "all_searches_include_forward_review": (
                bool(search_rows)
                and all(
                    row["forward_citation_search"]
                    for row in search_rows
                    if row["status"] == "COMPLETE"
                )
            ),
            "all_searches_include_preprint_review": (
                bool(search_rows)
                and all(
                    row["current_preprint_search"]
                    for row in search_rows
                    if row["status"] == "COMPLETE"
                )
            ),
        })

    if args.require_complete_overlap:
        gates.update({
            "source_corpus_nonempty": bool(
                source_rows
            ),
            "overlap_corpus_nonempty": bool(
                overlap_rows
            ),
            "all_claims_have_overlap_records": (
                bool(overlap_rows)
                and not claims_without_overlap_records
            ),
            "all_sources_fully_extracted": (
                bool(source_rows)
                and all(
                    row["extraction_status"]
                    in {
                        "EXTRACTED",
                        "SECOND_PASS_VALIDATED",
                    }
                    for row in source_rows
                )
            ),
            "all_overlap_records_adjudicated": (
                bool(overlap_rows)
                and all(
                    row["overlap_state"]
                    != "UNRESOLVED"
                    for row in overlap_rows
                )
            ),
        })

    all_passed = all(gates.values())

    source_registry = {
        "registry_version": "1.0.0",
        "source_count": len(source_rows),
        "sources": sorted(
            source_rows,
            key=lambda row: row["source_id"],
        ),
    }

    search_registry = {
        "registry_version": "1.0.0",
        "execution_count": len(search_rows),
        "executions": sorted(
            search_rows,
            key=lambda row: row["execution_id"],
        ),
    }

    overlap_registry = {
        "registry_version": "1.0.0",
        "overlap_count": len(overlap_rows),
        "overlaps": sorted(
            overlap_rows,
            key=lambda row: (
                row["claim_id"],
                row["source_id"],
            ),
        ),
    }

    SOURCE_REGISTRY.write_text(
        yaml.safe_dump(
            source_registry,
            sort_keys=False,
            width=100,
        ),
        encoding="utf-8",
    )

    SEARCH_EXECUTION_REGISTRY.write_text(
        yaml.safe_dump(
            search_registry,
            sort_keys=False,
            width=100,
        ),
        encoding="utf-8",
    )

    OVERLAP_REGISTRY.write_text(
        yaml.safe_dump(
            overlap_registry,
            sort_keys=False,
            width=100,
        ),
        encoding="utf-8",
    )

    summary = {
        "stage": 1,
        "status": (
            "PASS"
            if all_passed
            else "OPEN_FAILED_GATES"
        ),
        "source_count": len(source_rows),
        "overlap_count": len(overlap_rows),
        "search_execution_count": len(
            search_rows
        ),
        "completed_domain_count": len(
            completed_domains
        ),
        "required_domain_count": len(
            required_domains
        ),
        "claims_without_overlap_records": (
            claims_without_overlap_records
        ),
        "duplicate_source_ids": (
            duplicates(source_ids)
        ),
        "duplicate_canonical_keys": (
            duplicates(canonical_keys)
        ),
        "unresolved_source_references": (
            unresolved_source_references
        ),
        "unresolved_claim_references": (
            unresolved_claim_references
        ),
        "invalid_source_claim_references": (
            invalid_source_claim_references
        ),
        "invalid_source_domain_references": (
            invalid_source_domain_references
        ),
        "invalid_search_query_references": (
            invalid_search_query_references
        ),
        "unresolved_search_source_references": (
            unresolved_search_source_references
        ),
        "search_domain_mismatches": (
            search_domain_mismatches
        ),
        "source_schema_errors": source_errors,
        "overlap_schema_errors": overlap_errors,
        "search_schema_errors": search_errors,
        "gates": gates,
        "failed_gates": [
            name
            for name, passed in gates.items()
            if not passed
        ],
    }

    summary_path = (
        args.output_dir
        / "stage1_corpus_summary.json"
    )

    summary_path.write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    governed_files = [
        path
        for directory in [
            SOURCE_DIR,
            OVERLAP_DIR,
            SEARCH_DIR,
        ]
        for path in sorted(
            directory.glob("*.yaml")
        )
    ]

    governed_files.extend([
        SOURCE_REGISTRY,
        SEARCH_EXECUTION_REGISTRY,
        OVERLAP_REGISTRY,
    ])

    manifest = [
        {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in governed_files
        if path.is_file()
    ]

    (
        args.output_dir
        / "stage1_corpus_manifest.json"
    ).write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
    )

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
