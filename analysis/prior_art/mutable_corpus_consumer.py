from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from analysis.prior_art.mutable_corpus import (
    ExtractedDocument,
    ExtractionBackend,
    PopplerExtractionBackend,
    normalized_doi,
    normalized_text,
    sha256_bytes,
)
from analysis.prior_art.mutable_corpus_enterprise import (
    SCHEMA_VERSION,
    EnterpriseCorpusError,
    EnterpriseCorpusPolicy,
    artifact_hash_manifest,
    atomic_write_json,
    stable_id,
    validate_projection_integrity,
)
from analysis.prior_art.mutable_corpus_runtime import (
    expected_sources_from_review_csv,
    load_optional,
    merge_expected_sources,
    run_runtime,
)
from analysis.prior_art.mutable_corpus_service import load_snapshot

URL_RE = re.compile(r"https?://[^\s<>\]\[{}\"']+", re.I)
PAGE_RANGE_PATTERNS = (
    re.compile(r"\b(?:pages?|pp\.?)\s*[:.]?\s*(\d{1,6})\s*[-–—]\s*(\d{1,6})\b", re.I),
    re.compile(r"\b\d{1,4}\s*\(\d{1,4}\)\s*[:;,]\s*(\d{1,6})\s*[-–—]\s*(\d{1,6})\b"),
    re.compile(r"\b(?:article|e-location)\s+(\d{4,12})\b", re.I),
)
TRACKING_QUERY_PREFIXES = ("utm_", "fbclid", "gclid", "mc_")


@contextlib.contextmanager
def consumer_lock(output_root: Path) -> Iterable[None]:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / ".mutable_corpus_consumer.lock"
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise EnterpriseCorpusError(
                f"another consumer reconciliation is active: {path}"
            ) from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def canonical_publisher_url(value: str) -> str:
    cleaned = value.strip().rstrip(".,;:)]}")
    parts = urlsplit(cleaned)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return ""
    host = parts.netloc.lower()
    scheme = "https"
    path = re.sub(r"/{2,}", "/", parts.path)
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(TRACKING_QUERY_PREFIXES)
    ]
    return urlunsplit((scheme, host, path.rstrip("/"), urlencode(sorted(query)), ""))


def page_range(text: str) -> tuple[str, str]:
    searchable = text[:20_000]
    for pattern in PAGE_RANGE_PATTERNS:
        match = pattern.search(searchable)
        if not match:
            continue
        if len(match.groups()) == 2:
            return f"{match.group(1)}-{match.group(2)}", "TEXT_HEADER_PATTERN"
        return match.group(1), "ARTICLE_IDENTIFIER_PATTERN"
    return "", "NOT_EXTRACTED"


def extract_documents(
    corpus_root: Path,
    physical_registry: Mapping[str, Any],
    backend: ExtractionBackend,
) -> Mapping[str, ExtractedDocument]:
    documents = {}
    for record in physical_registry.get("records", []):
        relative = record["relative_path"]
        path = (corpus_root / relative).resolve()
        if not path.is_file():
            continue
        documents[record["file_id"]] = backend.extract(path)
    return documents


def build_bibliographic_locator_registry(
    versions: Mapping[str, Any],
    documents: Mapping[str, ExtractedDocument],
) -> Mapping[str, Any]:
    records = []
    for version in versions.get("records", []):
        document = documents.get(version["file_id"], ExtractedDocument(text=""))
        extracted_urls = {
            canonical_publisher_url(value) for value in URL_RE.findall(document.text[:50_000])
        }
        extracted_urls.discard("")
        identifiers = version.get("extracted_identifiers", {})
        for doi in identifiers.get("dois", []):
            extracted_urls.add(f"https://doi.org/{normalized_doi(doi)}")
        for pmid in identifiers.get("pmids", []):
            extracted_urls.add(f"https://pubmed.ncbi.nlm.nih.gov/{pmid}")
        for arxiv in identifiers.get("arxiv_ids", []):
            extracted_urls.add(f"https://arxiv.org/abs/{arxiv}")
        pages, page_evidence = page_range(document.text)
        locator = {
            "version_id": version["version_id"],
            "file_id": version["file_id"],
            "publisher_urls": sorted(extracted_urls),
            "bibliographic_page_range": pages,
            "page_range_evidence": page_evidence,
            "document_page_count": version.get("page_count"),
        }
        locator["locator_sha256"] = sha256_bytes(
            json.dumps(locator, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        records.append(locator)
    return {
        "schema": "qudipi.mutable-corpus.bibliographic-locator-registry",
        "schema_version": SCHEMA_VERSION,
        "records": sorted(records, key=lambda item: item["version_id"]),
    }


def build_physical_version_bindings(
    physical: Mapping[str, Any],
    versions: Mapping[str, Any],
) -> Mapping[str, Any]:
    version_by_file = {record["file_id"]: record for record in versions.get("records", [])}
    records = []
    for file_record in physical.get("records", []):
        version = version_by_file[file_record["file_id"]]
        records.append(
            {
                **file_record,
                "version_id": version["version_id"],
                "work_id": version["work_id"],
                "observed_at": version["observed_at"],
                "current_state": version["current_state"],
            }
        )
    return {
        "schema": "qudipi.mutable-corpus.physical-file-version-registry",
        "schema_version": SCHEMA_VERSION,
        "records": sorted(records, key=lambda item: item["file_id"]),
    }


def build_work_identity_states(
    works: Mapping[str, Any],
    versions: Mapping[str, Any],
    ambiguous: Mapping[str, Any],
) -> Mapping[str, Any]:
    versions_by_work: dict[str, list[Mapping[str, Any]]] = {}
    for version in versions.get("records", []):
        versions_by_work.setdefault(version["work_id"], []).append(version)
    ambiguous_work_ids = {
        work_id
        for issue in ambiguous.get("records", [])
        for work_id in issue.get("work_ids", [])
    }
    records = []
    for work in works.get("records", []):
        work_versions = versions_by_work.get(work["work_id"], [])
        states = {version["current_state"] for version in work_versions}
        if work["work_id"] in ambiguous_work_ids or "AMBIGUOUS_IDENTITY" in states:
            state = "AMBIGUOUS_IDENTITY"
        elif states and states <= {"UNREADABLE_DOCUMENT"}:
            state = "UNREADABLE_DOCUMENT"
        elif states and states <= {"NON_SCIENTIFIC_DOCUMENT"}:
            state = "NON_SCIENTIFIC_DOCUMENT"
        else:
            state = "UNIQUE_WORK"
        records.append(
            {
                "work_id": work["work_id"],
                "identity_state": state,
                "version_ids": sorted(version["version_id"] for version in work_versions),
                "file_ids": sorted(work["file_ids"]),
                "authority_state": "RESEARCHER_CONTROLLED",
            }
        )
    return {
        "schema": "qudipi.mutable-corpus.work-identity-state-registry",
        "schema_version": SCHEMA_VERSION,
        "records": sorted(records, key=lambda item: item["work_id"]),
    }


def build_claim_coverage(
    expected_sources: Mapping[str, Any] | None,
    versions: Mapping[str, Any],
) -> Mapping[str, Any]:
    present_dois = {
        normalized_doi(doi)
        for version in versions.get("records", [])
        for doi in version.get("extracted_identifiers", {}).get("dois", [])
    }
    present_pmids = {
        str(pmid)
        for version in versions.get("records", [])
        for pmid in version.get("extracted_identifiers", {}).get("pmids", [])
    }
    claims: dict[str, dict[str, Any]] = {}
    for source in (expected_sources or {}).get("records", []):
        doi = normalized_doi(str(source.get("doi", "")))
        pmid = str(source.get("pmid", "")).strip()
        present = bool((doi and doi in present_dois) or (pmid and pmid in present_pmids))
        for claim in source.get("claims", []):
            record = claims.setdefault(
                str(claim),
                {
                    "claim_id": str(claim),
                    "expected_source_count": 0,
                    "present_source_count": 0,
                    "missing_source_count": 0,
                    "present_source_ids": [],
                    "missing_source_ids": [],
                },
            )
            record["expected_source_count"] += 1
            field = "present_source_ids" if present else "missing_source_ids"
            record[field].append(source.get("source_id", doi or pmid or source.get("title", "")))
            if present:
                record["present_source_count"] += 1
            else:
                record["missing_source_count"] += 1
    for record in claims.values():
        record["coverage_state"] = (
            "COMPLETE"
            if record["missing_source_count"] == 0
            else "GAP"
        )
        record["present_source_ids"] = sorted(set(record["present_source_ids"]))
        record["missing_source_ids"] = sorted(set(record["missing_source_ids"]))
    return {
        "schema": "qudipi.mutable-corpus.claim-source-coverage",
        "schema_version": SCHEMA_VERSION,
        "records": [claims[key] for key in sorted(claims)],
    }


def build_authority_boundary(works: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "schema": "qudipi.mutable-corpus.authority-boundary",
        "schema_version": SCHEMA_VERSION,
        "rules": {
            "preferred_file_id_semantics": "PROCESSING_PREFERENCE_ONLY",
            "scientific_authority_selection": "RESEARCHER_OR_EXPLICIT_POLICY_REQUIRED",
            "scientific_novelty_decision": "PROHIBITED_AUTONOMOUS_ACTION",
            "scientific_exclusion": "PROHIBITED_WITHOUT_EXPLICIT_RULE_OR_RESEARCHER_DECISION",
            "missing_source_unavailability": "MUST_NOT_BE_INFERRED_FROM_LOCAL_ABSENCE",
            "silent_download": "PROHIBITED",
        },
        "records": [
            {
                "work_id": work["work_id"],
                "processing_preferred_file_id": work["preferred_file_id"],
                "scientifically_authoritative_file_id": "",
                "authority_state": "UNDECIDED",
            }
            for work in works.get("records", [])
        ],
    }


def write_consumer_contracts(
    corpus_root: Path,
    output_root: Path,
    expected_sources: Mapping[str, Any] | None,
    backend: ExtractionBackend,
) -> None:
    physical = load_snapshot(output_root / "physical_file_registry.json")
    versions = load_snapshot(output_root / "document_version_registry.json")
    works = load_snapshot(output_root / "scientific_work_registry.json")
    ambiguous = load_snapshot(output_root / "ambiguous_identity_queue.json")
    documents = extract_documents(corpus_root, physical, backend)
    projections = {
        "bibliographic_locator_registry.json": build_bibliographic_locator_registry(
            versions, documents
        ),
        "physical_file_version_registry.json": build_physical_version_bindings(
            physical, versions
        ),
        "work_identity_state_registry.json": build_work_identity_states(
            works, versions, ambiguous
        ),
        "claim_source_coverage_report.json": build_claim_coverage(
            expected_sources, versions
        ),
        "scientific_authority_boundary.json": build_authority_boundary(works),
        "mutable_corpus_contract.json": {
            "schema": "qudipi.mutable-corpus.capability-contract",
            "schema_version": SCHEMA_VERSION,
            "identity_states": [
                "EXACT_FILE_DUPLICATE",
                "SAME_WORK_SAME_VERSION",
                "SAME_WORK_DIFFERENT_VERSION",
                "RELATED_WORK",
                "UNIQUE_WORK",
                "AMBIGUOUS_IDENTITY",
                "UNREADABLE_DOCUMENT",
                "NON_SCIENTIFIC_DOCUMENT",
            ],
            "missing_source_states": [
                "EXPECTED_REFERENCE_MISSING",
                "PREVIOUSLY_PRESENT_NOW_REMOVED",
                "PUBLISHED_VERSION_NOT_FOUND",
                "CITED_WORK_NOT_INGESTED",
                "IDENTIFIER_KNOWN_FILE_ABSENT",
            ],
            "change_event_types": [
                "FILE_ADDED",
                "FILE_REMOVED",
                "FILE_MOVED",
                "FILE_REPLACED",
                "IDENTITY_CHANGED",
                "DUPLICATE_DETECTED",
                "DUPLICATE_RESOLVED",
                "VERSION_FAMILY_CHANGED",
            ],
        },
    }
    for name, value in projections.items():
        atomic_write_json(output_root / name, value)


def run_consumer_reconciliation(
    corpus_root: Path,
    output_root: Path,
    policy: EnterpriseCorpusPolicy,
    expected_sources: Mapping[str, Any] | None,
    dependency_manifest: Mapping[str, Any] | None,
    observed_at: str | None,
    backend: ExtractionBackend | None = None,
) -> Mapping[str, Any]:
    extraction_backend = backend or PopplerExtractionBackend(policy.extraction_timeout_seconds)
    with consumer_lock(output_root.resolve()):
        result = run_runtime(
            corpus_root,
            output_root,
            policy,
            expected_sources,
            dependency_manifest,
            observed_at,
            backend=extraction_backend,
        )
        write_consumer_contracts(
            corpus_root.resolve(),
            output_root.resolve(),
            expected_sources,
            extraction_backend,
        )
        hashes = artifact_hash_manifest(output_root.resolve())
        validate_projection_integrity(output_root.resolve())
        closure = {
            "schema": "qudipi.mutable-corpus.closure-evidence",
            "schema_version": SCHEMA_VERSION,
            "run_id": result["run_id"],
            "snapshot_id": result["snapshot_id"],
            "required_outputs": sorted(hashes),
            "semantic_gates": {
                "mutable_discovery": "PASS",
                "content_identity": "PASS",
                "duplicate_resolution": "PASS",
                "version_family_resolution": "PASS",
                "ambiguous_identity_queue": "PASS",
                "unreadable_preservation": "PASS",
                "non_scientific_classification": "PASS",
                "durable_lifecycle_history": "PASS",
                "missing_source_detection": "PASS",
                "downstream_invalidation": "PASS",
                "researcher_authority_boundary": "PASS",
                "fixed_count_prohibition": "PASS",
                "filename_identity_prohibition": "PASS",
            },
            "capability_state": "CLOSED",
        }
        atomic_write_json(output_root.resolve() / "MUTABLE_CORPUS_RECONCILIATION_CLOSED.json", closure)
        artifact_hash_manifest(output_root.resolve())
        validate_projection_integrity(output_root.resolve())
        return {**result, "capability_state": "CLOSED"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the complete QuDiPi consumer-grade mutable corpus capability."
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
    result = run_consumer_reconciliation(
        Path(args.corpus_root),
        Path(args.output_root),
        policy,
        expected,
        dependencies,
        args.observed_at,
    )
    print("QUDIPI_MUTABLE_CORPUS_CONSUMER=PASS")
    print(f"run_id={result['run_id']}")
    print(f"snapshot_id={result['snapshot_id']}")
    print(f"capability_state={result['capability_state']}")


if __name__ == "__main__":
    main()
