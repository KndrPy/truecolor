from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from analysis.prior_art.mutable_corpus import (
    ExtractedDocument,
    ExtractionBackend,
    normalized_doi,
    sha256_bytes,
)
from analysis.prior_art.mutable_corpus_enterprise import (
    SCHEMA_VERSION,
    EnterpriseCorpusError,
    atomic_write_json,
)
from analysis.prior_art.mutable_corpus_service import load_snapshot

URL_RE = re.compile(r"https?://[^\s<>\]\[{}\"']+", re.I)
PAGE_RANGE_PATTERNS = (
    re.compile(r"\b(?:pages?|pp\.?)\s*[:.]?\s*(\d{1,6})\s*[-–—]\s*(\d{1,6})\b", re.I),
    re.compile(r"\b\d{1,4}\s*\(\d{1,4}\)\s*[:;,]\s*(\d{1,6})\s*[-–—]\s*(\d{1,6})\b"),
    re.compile(r"\b(?:article|e-location)\s+(\d{4,12})\b", re.I),
)
TRACKING_QUERY_PREFIXES = ("utm_", "fbclid", "gclid", "mc_")
IDENTITY_STATES = (
    "EXACT_FILE_DUPLICATE",
    "SAME_WORK_SAME_VERSION",
    "SAME_WORK_DIFFERENT_VERSION",
    "RELATED_WORK",
    "UNIQUE_WORK",
    "AMBIGUOUS_IDENTITY",
    "UNREADABLE_DOCUMENT",
    "NON_SCIENTIFIC_DOCUMENT",
)
MISSING_SOURCE_STATES = (
    "EXPECTED_REFERENCE_MISSING",
    "PREVIOUSLY_PRESENT_NOW_REMOVED",
    "PUBLISHED_VERSION_NOT_FOUND",
    "CITED_WORK_NOT_INGESTED",
    "IDENTIFIER_KNOWN_FILE_ABSENT",
)
CHANGE_EVENT_TYPES = (
    "FILE_ADDED",
    "FILE_REMOVED",
    "FILE_MOVED",
    "FILE_REPLACED",
    "IDENTITY_CHANGED",
    "DUPLICATE_DETECTED",
    "DUPLICATE_RESOLVED",
    "VERSION_FAMILY_CHANGED",
)
REQUIRED_OUTPUTS = (
    "corpus_snapshot.json",
    "scientific_work_registry.json",
    "document_version_registry.json",
    "physical_file_registry.json",
    "physical_file_version_registry.json",
    "physical_file_lifecycle_registry.json",
    "exact_duplicate_report.json",
    "version_family_report.json",
    "work_identity_state_registry.json",
    "ambiguous_identity_queue.json",
    "unreadable_document_report.json",
    "non_scientific_document_report.json",
    "corpus_change_set.json",
    "stale_downstream_artifact_report.json",
    "missing_reference_candidates.json",
    "claim_source_coverage_report.json",
    "stage1_review_queue_projection.json",
    "bibliographic_locator_registry.json",
    "scientific_authority_boundary.json",
    "reconciliation_run_manifest.json",
    "mutable_corpus_contract.json",
    "artifact_hashes.json",
)


def canonical_publisher_url(value: str) -> str:
    cleaned = value.strip().rstrip(".,;:)]}")
    parts = urlsplit(cleaned)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return ""
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(TRACKING_QUERY_PREFIXES)
    ]
    return urlunsplit(
        (
            "https",
            parts.netloc.lower(),
            re.sub(r"/{2,}", "/", parts.path).rstrip("/"),
            urlencode(sorted(query)),
            "",
        )
    )


def page_range(text: str) -> tuple[str, str]:
    for pattern in PAGE_RANGE_PATTERNS:
        match = pattern.search(text[:20_000])
        if match:
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
        path = (corpus_root / record["relative_path"]).resolve()
        if path.is_file():
            documents[record["file_id"]] = backend.extract(path)
    return documents


def build_bibliographic_locator_registry(
    versions: Mapping[str, Any],
    documents: Mapping[str, ExtractedDocument],
) -> Mapping[str, Any]:
    records = []
    for version in versions.get("records", []):
        document = documents.get(version["file_id"], ExtractedDocument(text=""))
        urls = {canonical_publisher_url(value) for value in URL_RE.findall(document.text[:50_000])}
        urls.discard("")
        identifiers = version.get("extracted_identifiers", {})
        for doi in identifiers.get("dois", []):
            urls.add(f"https://doi.org/{normalized_doi(doi)}")
        for pmid in identifiers.get("pmids", []):
            urls.add(f"https://pubmed.ncbi.nlm.nih.gov/{pmid}")
        for arxiv in identifiers.get("arxiv_ids", []):
            urls.add(f"https://arxiv.org/abs/{arxiv}")
        pages, evidence = page_range(document.text)
        record = {
            "version_id": version["version_id"],
            "file_id": version["file_id"],
            "publisher_urls": sorted(urls),
            "bibliographic_page_range": pages,
            "page_range_evidence": evidence,
            "document_page_count": version.get("page_count"),
        }
        record["locator_sha256"] = sha256_bytes(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        records.append(record)
    return {
        "schema": "qudipi.mutable-corpus.bibliographic-locator-registry",
        "schema_version": SCHEMA_VERSION,
        "records": sorted(records, key=lambda item: item["version_id"]),
    }


def build_physical_version_registry(
    physical: Mapping[str, Any],
    versions: Mapping[str, Any],
) -> Mapping[str, Any]:
    version_by_file = {record["file_id"]: record for record in versions.get("records", [])}
    records = []
    for physical_record in physical.get("records", []):
        version = version_by_file.get(physical_record["file_id"])
        if version is None:
            raise EnterpriseCorpusError(
                f"physical file has no document version: {physical_record['file_id']}"
            )
        records.append(
            {
                **physical_record,
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
            source_id = source.get("source_id", doi or pmid or source.get("title", ""))
            if present:
                record["present_source_count"] += 1
                record["present_source_ids"].append(source_id)
            else:
                record["missing_source_count"] += 1
                record["missing_source_ids"].append(source_id)
    for record in claims.values():
        record["coverage_state"] = "COMPLETE" if not record["missing_source_count"] else "GAP"
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


def write_contract_projections(
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
        "bibliographic_locator_registry.json": build_bibliographic_locator_registry(versions, documents),
        "physical_file_version_registry.json": build_physical_version_registry(physical, versions),
        "work_identity_state_registry.json": build_work_identity_states(works, versions, ambiguous),
        "claim_source_coverage_report.json": build_claim_coverage(expected_sources, versions),
        "scientific_authority_boundary.json": build_authority_boundary(works),
        "mutable_corpus_contract.json": {
            "schema": "qudipi.mutable-corpus.capability-contract",
            "schema_version": SCHEMA_VERSION,
            "identity_states": IDENTITY_STATES,
            "missing_source_states": MISSING_SOURCE_STATES,
            "change_event_types": CHANGE_EVENT_TYPES,
        },
    }
    for name, value in projections.items():
        atomic_write_json(output_root / name, value)


def validate_closure(output_root: Path) -> Mapping[str, str]:
    gates: dict[str, str] = {}
    missing = [name for name in REQUIRED_OUTPUTS if not (output_root / name).is_file()]
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
    if set(contract["identity_states"]) != set(IDENTITY_STATES):
        raise EnterpriseCorpusError("identity state contract is incomplete")
    if set(contract["missing_source_states"]) != set(MISSING_SOURCE_STATES):
        raise EnterpriseCorpusError("missing-source state contract is incomplete")
    gates["state_space_completeness"] = "PASS"

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
    gates["stage1_projection"] = "PASS"

    source = "".join(
        path.read_text(encoding="utf-8")
        for path in (
            Path(__file__).with_name("mutable_corpus_enterprise.py"),
            Path(__file__).with_name("mutable_corpus_runtime.py"),
            Path(__file__),
        )
    )
    forbidden = ("exact_filename_number", "configured_review_record_count", "range(1, 33)")
    found = [token for token in forbidden if token in source]
    if found:
        raise EnterpriseCorpusError(f"forbidden fixed-corpus coupling found: {', '.join(found)}")
    gates["fixed_count_and_filename_identity_prohibition"] = "PASS"
    return gates
