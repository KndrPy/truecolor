from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from analysis.prior_art.mutable_corpus import (
    CorpusPolicy,
    CorpusSnapshot,
    ExtractedDocument,
    ExtractionBackend,
    PhysicalFileRecord,
    PopplerExtractionBackend,
    normalized_doi,
    normalized_text,
    sha256_bytes,
    sha256_file,
    significant_tokens,
)
from analysis.prior_art.mutable_corpus_service import (
    atomic_write_json,
    compare_snapshot_states,
    invalidate_dependencies,
    load_snapshot,
    reconcile_corpus,
)

SCHEMA_VERSION = 2
PDF_MAGIC = b"%PDF-"
ARXIV_RE = re.compile(r"(?:arxiv\s*:\s*)?(\d{4}\.\d{4,5})(?:v(\d+))?", re.I)
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", re.I)
PMID_RE = re.compile(r"(?:pmid\s*[: ]\s*)(\d{6,9})", re.I)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
SECTION_RE = re.compile(
    r"^(abstract|introduction|background|related work|materials(?: and methods)?|methods|results|discussion|conclusion|conclusions|references|bibliography|appendix|supplementary materials?)\s*$",
    re.I,
)


class EnterpriseCorpusError(RuntimeError):
    pass


@dataclass(frozen=True)
class EnterpriseCorpusPolicy:
    include_globs: tuple[str, ...] = ("**/*.pdf", "*.pdf")
    exclude_globs: tuple[str, ...] = ()
    minimum_text_characters: int = 120
    maximum_file_bytes: int = 512 * 1024 * 1024
    maximum_files_per_run: int = 100_000
    extraction_timeout_seconds: int = 180
    allow_symbolic_links: bool = False
    title_match_threshold: float = 0.88
    author_match_threshold: float = 0.40
    abstract_match_threshold: float = 0.72
    content_match_threshold: float = 0.82
    related_work_threshold: float = 0.62
    minhash_permutations: int = 64
    minimum_scientific_signals: int = 2

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "EnterpriseCorpusPolicy":
        if not value:
            return cls()
        defaults = asdict(cls())
        unknown = sorted(set(value) - set(defaults))
        if unknown:
            raise ValueError(f"unknown enterprise corpus policy fields: {', '.join(unknown)}")
        merged = {**defaults, **value}
        for field in ("include_globs", "exclude_globs"):
            merged[field] = tuple(str(item) for item in merged[field])
        policy = cls(**merged)
        if policy.maximum_file_bytes <= 0 or policy.maximum_files_per_run <= 0:
            raise ValueError("corpus resource limits must be positive")
        if policy.minhash_permutations < 16:
            raise ValueError("minhash_permutations must be at least 16")
        return policy

    def core_policy(self) -> CorpusPolicy:
        return CorpusPolicy(
            include_globs=self.include_globs,
            exclude_globs=self.exclude_globs,
            minimum_text_characters=self.minimum_text_characters,
            title_similarity_threshold=self.title_match_threshold,
            related_similarity_threshold=self.related_work_threshold,
            version_similarity_threshold=self.content_match_threshold,
        )


@dataclass(frozen=True)
class DocumentFingerprint:
    bibliographic_sha256: str
    normalized_title: str
    normalized_authors: tuple[str, ...]
    primary_doi: str
    primary_pmid: str
    primary_arxiv_id: str
    minhash_signature: tuple[int, ...]
    section_heading_signature: tuple[str, ...]
    abstract_sha256: str
    abstract_tokens: tuple[str, ...]
    reference_dois: tuple[str, ...]


@dataclass(frozen=True)
class DocumentVersionRecord:
    version_id: str
    work_id: str
    file_id: str
    version_type: str
    version_label_confidence: str
    extracted_title: str
    extracted_authors: tuple[str, ...]
    extracted_identifiers: Mapping[str, tuple[str, ...]]
    publication_year: int | None
    venue: str
    page_count: int | None
    fingerprint: DocumentFingerprint
    current_state: str
    observed_at: str


@dataclass(frozen=True)
class IdentityIssue:
    issue_id: str
    state: str
    severity: str
    file_ids: tuple[str, ...]
    work_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    evidence: Mapping[str, Any]


@dataclass(frozen=True)
class VersionRelationship:
    relationship_id: str
    relationship_type: str
    left_version_id: str
    right_version_id: str
    confidence: str
    score: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class PreflightRecord:
    relative_path: str
    state: str
    size_bytes: int
    reasons: tuple[str, ...]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_id(prefix: str, value: Any, length: int = 24) -> str:
    digest = sha256_bytes(canonical_json(value).encode("utf-8"))
    return f"{prefix}-{digest[:length]}"


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextlib.contextmanager
def exclusive_run_lock(output_root: Path) -> Iterable[None]:
    output_root.mkdir(parents=True, exist_ok=True)
    lock_path = output_root / ".mutable_corpus.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise EnterpriseCorpusError(
                f"another mutable-corpus reconciliation is active: {lock_path}"
            ) from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def preflight_corpus(root: Path, policy: EnterpriseCorpusPolicy) -> tuple[PreflightRecord, ...]:
    root = root.resolve()
    if not root.is_dir():
        raise EnterpriseCorpusError(f"corpus root is not a directory: {root}")
    records: list[PreflightRecord] = []
    candidate_count = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        included = any(path.match(pattern) for pattern in policy.include_globs)
        excluded = any(path.match(pattern) for pattern in policy.exclude_globs)
        if not included or excluded:
            continue
        candidate_count += 1
        reasons: list[str] = []
        state = "ACCEPTED"
        if candidate_count > policy.maximum_files_per_run:
            raise EnterpriseCorpusError(
                f"corpus exceeds maximum_files_per_run={policy.maximum_files_per_run}"
            )
        if path.is_symlink() and not policy.allow_symbolic_links:
            state = "REJECTED"
            reasons.append("SYMBOLIC_LINK_NOT_ALLOWED")
        if not _path_is_within(path, root):
            state = "REJECTED"
            reasons.append("PATH_ESCAPES_CORPUS_ROOT")
        size = path.stat().st_size
        if size > policy.maximum_file_bytes:
            state = "REJECTED"
            reasons.append("FILE_SIZE_LIMIT_EXCEEDED")
        try:
            with path.open("rb") as handle:
                magic = handle.read(len(PDF_MAGIC))
        except OSError as error:
            state = "REJECTED"
            reasons.append(f"FILE_READ_FAILED:{type(error).__name__}")
            magic = b""
        if magic != PDF_MAGIC:
            state = "REJECTED"
            reasons.append("INVALID_PDF_SIGNATURE")
        records.append(PreflightRecord(relative, state, size, tuple(reasons)))
    return tuple(records)


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(sorted(significant_tokens(value)))


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 0.0


def _abstract(text: str) -> str:
    lines = text.splitlines()
    start = None
    collected: list[str] = []
    for index, line in enumerate(lines):
        cleaned = " ".join(line.split()).strip()
        if start is None and cleaned.lower() in {"abstract", "summary"}:
            start = index + 1
            continue
        if start is not None:
            if SECTION_RE.match(cleaned) and cleaned.lower() not in {"abstract", "summary"}:
                break
            if cleaned:
                collected.append(cleaned)
            if sum(len(item) for item in collected) >= 6000:
                break
    return " ".join(collected)


def _section_signature(text: str) -> tuple[str, ...]:
    sections = []
    for line in text.splitlines():
        cleaned = " ".join(line.split()).strip().lower()
        if SECTION_RE.match(cleaned) and cleaned not in sections:
            sections.append(cleaned)
    return tuple(sections)


def _minhash(tokens: Iterable[str], permutations: int) -> tuple[int, ...]:
    unique = sorted(set(tokens))
    if not unique:
        return tuple(0 for _ in range(permutations))
    signature = []
    for seed in range(permutations):
        minimum = min(
            int.from_bytes(
                hashlib.sha256(f"{seed}:{token}".encode("utf-8")).digest()[:8], "big"
            )
            for token in unique
        )
        signature.append(minimum)
    return tuple(signature)


def _minhash_similarity(left: Sequence[int], right: Sequence[int]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    return sum(a == b for a, b in zip(left, right, strict=True)) / len(left)


def _primary_identifier(values: Sequence[str]) -> str:
    return values[0] if values else ""


def _version_type(record: PhysicalFileRecord, text: str) -> tuple[str, str]:
    searchable = normalized_text(
        " ".join((record.identity.title, record.identity.venue, text[:20_000]))
    )
    if any(term in searchable for term in ("corrigendum", "erratum", "correction to")):
        return "CORRECTION", "HIGH"
    if any(term in searchable for term in ("supplementary material", "supplemental material")):
        return "SUPPLEMENT", "HIGH"
    if record.identity.arxiv_ids or any(
        term in searchable for term in ("preprint", "biorxiv", "medrxiv")
    ):
        return "PREPRINT", "HIGH"
    if any(term in searchable for term in ("proceedings", "conference", "workshop")):
        return "CONFERENCE", "MODERATE"
    if record.identity.dois and any(
        term in searchable for term in ("journal", "volume", "article")
    ):
        return "JOURNAL", "MODERATE"
    if record.identity.dois:
        return "PUBLISHED", "MODERATE"
    return "UNCLASSIFIED", "LOW"


def _scientific_state(record: PhysicalFileRecord, text: str, policy: EnterpriseCorpusPolicy) -> str:
    if record.extraction_errors and record.extraction_state != "EXTRACTED":
        return "UNREADABLE_DOCUMENT"
    signals = 0
    lowered = normalized_text(text[:40_000])
    if record.identity.dois or record.identity.pmids or record.identity.arxiv_ids:
        signals += 1
    if record.identity.authors:
        signals += 1
    if "abstract" in lowered:
        signals += 1
    if "references" in lowered or "bibliography" in lowered:
        signals += 1
    if any(term in lowered for term in ("methods", "results", "discussion")):
        signals += 1
    if signals < policy.minimum_scientific_signals:
        return "NON_SCIENTIFIC_DOCUMENT"
    if record.identity.confidence == "LOW" or not record.identity.title.strip():
        return "AMBIGUOUS_IDENTITY"
    return "ACTIVE"


def fingerprint_document(
    record: PhysicalFileRecord,
    text: str,
    policy: EnterpriseCorpusPolicy,
) -> DocumentFingerprint:
    abstract = _abstract(text)
    abstract_tokens = _tokens(abstract)
    authors = tuple(sorted(normalized_text(author) for author in record.identity.authors))
    title = normalized_text(record.identity.title)
    primary_doi = _primary_identifier(record.identity.dois)
    primary_pmid = _primary_identifier(record.identity.pmids)
    primary_arxiv = _primary_identifier(record.identity.arxiv_ids)
    bibliographic = {
        "title": title,
        "authors": authors,
        "year": record.identity.year,
        "venue": normalized_text(record.identity.venue),
        "doi": primary_doi,
        "pmid": primary_pmid,
        "arxiv": primary_arxiv,
    }
    return DocumentFingerprint(
        bibliographic_sha256=sha256_bytes(canonical_json(bibliographic).encode("utf-8")),
        normalized_title=title,
        normalized_authors=authors,
        primary_doi=primary_doi,
        primary_pmid=primary_pmid,
        primary_arxiv_id=primary_arxiv,
        minhash_signature=_minhash(_tokens(text), policy.minhash_permutations),
        section_heading_signature=_section_signature(text),
        abstract_sha256=sha256_bytes(normalized_text(abstract).encode("utf-8")) if abstract else "",
        abstract_tokens=abstract_tokens,
        reference_dois=record.cited_dois,
    )


def build_document_versions(
    snapshot: CorpusSnapshot,
    text_by_file_id: Mapping[str, str],
    policy: EnterpriseCorpusPolicy,
) -> tuple[DocumentVersionRecord, ...]:
    work_by_file = {
        file_id: work.work_id for work in snapshot.works for file_id in work.file_ids
    }
    versions = []
    for record in snapshot.files:
        text = text_by_file_id.get(record.file_id, "")
        fingerprint = fingerprint_document(record, text, policy)
        version_type, confidence = _version_type(record, text)
        version_key = {
            "work_id": work_by_file[record.file_id],
            "bibliographic_sha256": fingerprint.bibliographic_sha256,
            "normalized_text_sha256": record.normalized_text_sha256,
            "version_type": version_type,
        }
        versions.append(
            DocumentVersionRecord(
                version_id=stable_id("VERSION", version_key),
                work_id=work_by_file[record.file_id],
                file_id=record.file_id,
                version_type=version_type,
                version_label_confidence=confidence,
                extracted_title=record.identity.title,
                extracted_authors=record.identity.authors,
                extracted_identifiers={
                    "dois": record.identity.dois,
                    "pmids": record.identity.pmids,
                    "arxiv_ids": record.identity.arxiv_ids,
                },
                publication_year=record.identity.year,
                venue=record.identity.venue,
                page_count=record.page_count,
                fingerprint=fingerprint,
                current_state=_scientific_state(record, text, policy),
                observed_at=snapshot.observed_at,
            )
        )
    return tuple(sorted(versions, key=lambda item: item.version_id))


def infer_version_relationships(
    versions: Sequence[DocumentVersionRecord],
    records: Mapping[str, PhysicalFileRecord],
    policy: EnterpriseCorpusPolicy,
) -> tuple[tuple[VersionRelationship, ...], tuple[IdentityIssue, ...]]:
    relationships: list[VersionRelationship] = []
    issues: list[IdentityIssue] = []
    for index, left in enumerate(versions):
        for right in versions[index + 1 :]:
            left_file = records[left.file_id]
            right_file = records[right.file_id]
            evidence: list[str] = []
            if left_file.binary_sha256 == right_file.binary_sha256:
                relation = "EXACT_FILE_DUPLICATE"
                score = 1.0
                confidence = "CERTAIN"
                evidence.append("binary_sha256")
            else:
                left_doi = left.fingerprint.primary_doi
                right_doi = right.fingerprint.primary_doi
                same_doi = bool(left_doi and left_doi == right_doi)
                title_score = _jaccard(
                    _tokens(left.extracted_title), _tokens(right.extracted_title)
                )
                author_score = _jaccard(
                    left.fingerprint.normalized_authors,
                    right.fingerprint.normalized_authors,
                )
                abstract_score = _jaccard(
                    left.fingerprint.abstract_tokens, right.fingerprint.abstract_tokens
                )
                content_score = _minhash_similarity(
                    left.fingerprint.minhash_signature,
                    right.fingerprint.minhash_signature,
                )
                reference_score = _jaccard(
                    left.fingerprint.reference_dois, right.fingerprint.reference_dois
                )
                score = round(
                    0.32 * title_score
                    + 0.18 * author_score
                    + 0.22 * abstract_score
                    + 0.20 * content_score
                    + 0.08 * reference_score,
                    6,
                )
                distinct_dois = bool(left_doi and right_doi and left_doi != right_doi)
                if same_doi:
                    relation = "SAME_WORK_SAME_VERSION"
                    confidence = "HIGH"
                    evidence.append("shared_primary_doi")
                elif (
                    distinct_dois
                    and title_score >= policy.title_match_threshold
                    and author_score >= policy.author_match_threshold
                ):
                    issue_payload = {
                        "left_doi": left_doi,
                        "right_doi": right_doi,
                        "title_score": title_score,
                        "author_score": author_score,
                    }
                    issues.append(
                        IdentityIssue(
                            issue_id=stable_id("ISSUE", issue_payload),
                            state="AMBIGUOUS_IDENTITY",
                            severity="HIGH",
                            file_ids=tuple(sorted((left.file_id, right.file_id))),
                            work_ids=tuple(sorted((left.work_id, right.work_id))),
                            reasons=("CONFLICTING_PRIMARY_DOI_WITH_HIGH_BIBLIOGRAPHIC_SIMILARITY",),
                            evidence=issue_payload,
                        )
                    )
                    relation = "AMBIGUOUS_IDENTITY"
                    confidence = "HIGH"
                    evidence.append("conflicting_primary_doi")
                elif (
                    score >= policy.content_match_threshold
                    and title_score >= policy.title_match_threshold
                    and author_score >= policy.author_match_threshold
                ):
                    relation = (
                        "SAME_WORK_DIFFERENT_VERSION"
                        if left.version_type != right.version_type
                        else "SAME_WORK_SAME_VERSION"
                    )
                    confidence = "MODERATE"
                    evidence.extend(("bibliographic_similarity", "content_similarity"))
                elif score >= policy.related_work_threshold:
                    relation = "RELATED_WORK"
                    confidence = "MODERATE"
                    evidence.append("aggregate_similarity")
                else:
                    continue
            relation_payload = {
                "type": relation,
                "left": left.version_id,
                "right": right.version_id,
            }
            relationships.append(
                VersionRelationship(
                    relationship_id=stable_id("REL", relation_payload),
                    relationship_type=relation,
                    left_version_id=min(left.version_id, right.version_id),
                    right_version_id=max(left.version_id, right.version_id),
                    confidence=confidence,
                    score=score,
                    evidence=tuple(evidence),
                )
            )
    return (
        tuple(sorted(relationships, key=lambda item: item.relationship_id)),
        tuple(sorted(issues, key=lambda item: item.issue_id)),
    )


def _expected_source_records(value: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...]:
    if not value:
        return ()
    records = value.get("records", value.get("sources", []))
    if not isinstance(records, list):
        raise EnterpriseCorpusError("expected-source registry must contain a records array")
    normalized = []
    for record in records:
        if not isinstance(record, Mapping):
            raise EnterpriseCorpusError("expected-source record must be an object")
        normalized.append(record)
    return tuple(normalized)


def build_missing_source_report(
    snapshot: CorpusSnapshot,
    versions: Sequence[DocumentVersionRecord],
    events: Sequence[Mapping[str, Any]],
    expected_sources: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any], ...]:
    present_dois = {
        doi for version in versions for doi in version.extracted_identifiers.get("dois", ())
    }
    present_pmids = {
        pmid for version in versions for pmid in version.extracted_identifiers.get("pmids", ())
    }
    records: list[Mapping[str, Any]] = list(snapshot.missing_reference_candidates)
    for event in events:
        if event["event_type"] == "FILE_REMOVED":
            records.append(
                {
                    "state": "PREVIOUSLY_PRESENT_NOW_REMOVED",
                    "file_id": event["file_id"],
                    "relative_path": event["relative_path"],
                    "binary_sha256": event["binary_sha256"],
                }
            )
    for source in _expected_source_records(expected_sources):
        doi = normalized_doi(str(source.get("doi", "")))
        pmid = str(source.get("pmid", "")).strip()
        required = bool(source.get("required", True))
        if not required:
            continue
        present = bool((doi and doi in present_dois) or (pmid and pmid in present_pmids))
        if not present:
            state = "EXPECTED_REFERENCE_MISSING"
            if doi or pmid:
                state = "IDENTIFIER_KNOWN_FILE_ABSENT"
            records.append(
                {
                    "state": state,
                    "source_id": source.get("source_id", ""),
                    "title": source.get("title", ""),
                    "doi": doi,
                    "pmid": pmid,
                    "claims": source.get("claims", []),
                }
            )
    work_versions: dict[str, set[str]] = {}
    for version in versions:
        work_versions.setdefault(version.work_id, set()).add(version.version_type)
    for work_id, types in sorted(work_versions.items()):
        if "PREPRINT" in types and not types & {"JOURNAL", "PUBLISHED"}:
            records.append(
                {
                    "state": "PUBLISHED_VERSION_NOT_FOUND",
                    "work_id": work_id,
                    "present_version_types": sorted(types),
                }
            )
    deduplicated: dict[str, Mapping[str, Any]] = {}
    for record in records:
        key = canonical_json(record)
        deduplicated[key] = record
    return tuple(deduplicated[key] for key in sorted(deduplicated))


def build_stage1_projection(
    snapshot: CorpusSnapshot,
    versions: Sequence[DocumentVersionRecord],
    issues: Sequence[IdentityIssue],
) -> Mapping[str, Any]:
    versions_by_work: dict[str, list[DocumentVersionRecord]] = {}
    for version in versions:
        versions_by_work.setdefault(version.work_id, []).append(version)
    issue_work_ids = {work_id for issue in issues for work_id in issue.work_ids}
    tasks = []
    for work in snapshot.works:
        work_versions = sorted(versions_by_work.get(work.work_id, []), key=lambda item: item.version_id)
        states = sorted({version.current_state for version in work_versions})
        task_state = "READY_FOR_EVIDENCE_EXTRACTION"
        if work.work_id in issue_work_ids or "AMBIGUOUS_IDENTITY" in states:
            task_state = "IDENTITY_REVIEW_REQUIRED"
        elif "UNREADABLE_DOCUMENT" in states:
            task_state = "SOURCE_RECOVERY_REQUIRED"
        elif states and all(state == "NON_SCIENTIFIC_DOCUMENT" for state in states):
            task_state = "NON_SCIENTIFIC_REVIEW_REQUIRED"
        tasks.append(
            {
                "task_id": stable_id("CORPUS-TASK", work.work_id),
                "work_id": work.work_id,
                "canonical_title": work.canonical_title,
                "canonical_identifiers": {
                    "dois": work.canonical_dois,
                    "pmids": work.pmids,
                    "arxiv_ids": work.arxiv_ids,
                },
                "version_ids": [version.version_id for version in work_versions],
                "file_ids": list(work.file_ids),
                "task_state": task_state,
                "authority_boundary": "RESEARCHER_OR_POLICY_DECISION_REQUIRED_FOR_EXCLUSION_OR_SCIENTIFIC_ADJUDICATION",
            }
        )
    return {
        "schema": "qudipi.stage1.mutable-corpus-review-projection",
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": snapshot.snapshot_id,
        "task_count": len(tasks),
        "tasks": sorted(tasks, key=lambda item: item["task_id"]),
    }


def append_event_ledger(output_root: Path, snapshot_id: str, events: Sequence[Mapping[str, Any]]) -> None:
    ledger = output_root / "history" / "corpus_event_ledger.jsonl"
    existing: dict[str, Mapping[str, Any]] = {}
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            existing[str(record["event_id"])] = record
    for event in events:
        payload = {"snapshot_id": snapshot_id, **event}
        event_id = stable_id("EVENT", payload)
        existing[event_id] = {"event_id": event_id, **payload}
    serialized = "".join(
        canonical_json(existing[event_id]) + "\n" for event_id in sorted(existing)
    )
    atomic_write_text(ledger, serialized)


def write_history_snapshot(output_root: Path, snapshot: CorpusSnapshot) -> None:
    path = output_root / "history" / "snapshots" / f"{snapshot.snapshot_id}.json"
    if not path.exists():
        atomic_write_json(path, asdict(snapshot))


def artifact_hash_manifest(output_root: Path) -> Mapping[str, str]:
    manifest_path = output_root / "artifact_hashes.json"
    hashes = {}
    for path in sorted(output_root.glob("*.json")):
        if path == manifest_path:
            continue
        hashes[path.name] = sha256_file(path)
    atomic_write_json(manifest_path, hashes)
    return hashes


def validate_projection_integrity(output_root: Path) -> None:
    manifest = load_snapshot(output_root / "artifact_hashes.json")
    for name, expected in manifest.items():
        path = output_root / name
        if not path.is_file():
            raise EnterpriseCorpusError(f"missing projection declared in hash manifest: {name}")
        actual = sha256_file(path)
        if actual != expected:
            raise EnterpriseCorpusError(f"projection hash mismatch: {name}")
    version_registry = load_snapshot(output_root / "document_version_registry.json")
    versions = version_registry.get("records", [])
    version_ids = [record["version_id"] for record in versions]
    if len(version_ids) != len(set(version_ids)):
        raise EnterpriseCorpusError("document version identifiers are not unique")


def _capturing_backend(
    backend: ExtractionBackend,
    text_by_path: dict[str, str],
) -> ExtractionBackend:
    class CapturingBackend:
        def extract(self, path: Path) -> ExtractedDocument:
            extracted = backend.extract(path)
            text_by_path[path.resolve().as_posix()] = extracted.text
            return extracted

    return CapturingBackend()


def run_enterprise_reconciliation(
    corpus_root: Path,
    output_root: Path,
    policy: EnterpriseCorpusPolicy | None = None,
    expected_sources: Mapping[str, Any] | None = None,
    dependency_manifest: Mapping[str, Any] | None = None,
    backend: ExtractionBackend | None = None,
    observed_at: str | None = None,
) -> Mapping[str, Any]:
    policy = policy or EnterpriseCorpusPolicy()
    observed_at = observed_at or utc_now()
    corpus_root = corpus_root.resolve()
    output_root = output_root.resolve()
    with exclusive_run_lock(output_root):
        previous_path = output_root / "corpus_snapshot.json"
        previous = load_snapshot(previous_path) if previous_path.is_file() else None
        preflight = preflight_corpus(corpus_root, policy)
        rejected = [record for record in preflight if record.state != "ACCEPTED"]
        if rejected:
            atomic_write_json(
                output_root / "corpus_preflight_report.json",
                {"schema_version": SCHEMA_VERSION, "records": [asdict(item) for item in preflight]},
            )
            raise EnterpriseCorpusError(
                f"corpus preflight rejected {len(rejected)} file(s); inspect corpus_preflight_report.json"
            )
        text_by_path: dict[str, str] = {}
        extraction_backend = backend or PopplerExtractionBackend(policy.extraction_timeout_seconds)
        snapshot = reconcile_corpus(
            corpus_root,
            output_root,
            policy=policy.core_policy(),
            backend=_capturing_backend(extraction_backend, text_by_path),
            observed_at=observed_at,
        )
        text_by_file_id = {
            record.file_id: text_by_path.get((corpus_root / record.relative_path).resolve().as_posix(), "")
            for record in snapshot.files
        }
        events = compare_snapshot_states(previous, snapshot)
        stale = invalidate_dependencies(events, dependency_manifest)
        versions = build_document_versions(snapshot, text_by_file_id, policy)
        record_by_file_id = {record.file_id: record for record in snapshot.files}
        version_relationships, identity_issues = infer_version_relationships(
            versions, record_by_file_id, policy
        )
        missing = build_missing_source_report(
            snapshot, versions, events, expected_sources
        )
        unreadable = [version for version in versions if version.current_state == "UNREADABLE_DOCUMENT"]
        non_scientific = [version for version in versions if version.current_state == "NON_SCIENTIFIC_DOCUMENT"]
        ambiguous = list(identity_issues) + [
            IdentityIssue(
                issue_id=stable_id("ISSUE", {"file_id": version.file_id, "state": version.current_state}),
                state="AMBIGUOUS_IDENTITY",
                severity="MEDIUM",
                file_ids=(version.file_id,),
                work_ids=(version.work_id,),
                reasons=("LOW_CONFIDENCE_DOCUMENT_IDENTITY",),
                evidence={"version_id": version.version_id},
            )
            for version in versions
            if version.current_state == "AMBIGUOUS_IDENTITY"
        ]
        exact_duplicates = [
            relationship
            for relationship in version_relationships
            if relationship.relationship_type == "EXACT_FILE_DUPLICATE"
        ]
        version_families = [
            relationship
            for relationship in version_relationships
            if relationship.relationship_type in {
                "SAME_WORK_SAME_VERSION",
                "SAME_WORK_DIFFERENT_VERSION",
                "RELATED_WORK",
            }
        ]
        projections = {
            "corpus_preflight_report.json": {
                "schema_version": SCHEMA_VERSION,
                "records": [asdict(item) for item in preflight],
            },
            "document_version_registry.json": {
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": snapshot.snapshot_id,
                "records": [asdict(item) for item in versions],
            },
            "exact_duplicate_report.json": {
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": snapshot.snapshot_id,
                "records": [asdict(item) for item in exact_duplicates],
            },
            "version_family_report.json": {
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": snapshot.snapshot_id,
                "records": [asdict(item) for item in version_families],
            },
            "ambiguous_identity_queue.json": {
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": snapshot.snapshot_id,
                "records": [asdict(item) for item in sorted(ambiguous, key=lambda item: item.issue_id)],
            },
            "unreadable_document_report.json": {
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": snapshot.snapshot_id,
                "records": [asdict(item) for item in unreadable],
            },
            "non_scientific_document_report.json": {
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": snapshot.snapshot_id,
                "records": [asdict(item) for item in non_scientific],
            },
            "corpus_change_set.json": {
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": snapshot.snapshot_id,
                "events": events,
            },
            "stale_downstream_artifact_report.json": {
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": snapshot.snapshot_id,
                "records": stale,
            },
            "missing_reference_candidates.json": {
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": snapshot.snapshot_id,
                "records": missing,
            },
            "stage1_review_queue_projection.json": build_stage1_projection(
                snapshot, versions, ambiguous
            ),
            "corpus_policy_effective.json": asdict(policy),
        }
        for name, value in projections.items():
            atomic_write_json(output_root / name, value)
        write_history_snapshot(output_root, snapshot)
        append_event_ledger(output_root, snapshot.snapshot_id, events)
        hashes = artifact_hash_manifest(output_root)
        validate_projection_integrity(output_root)
        summary = {
            **snapshot.summary,
            "document_version_count": len(versions),
            "ambiguous_identity_count": len(ambiguous),
            "unreadable_document_count": len(unreadable),
            "non_scientific_document_count": len(non_scientific),
            "version_relationship_count": len(version_relationships),
            "change_event_count": len(events),
            "stale_downstream_artifact_count": len(stale),
            "artifact_hash_count": len(hashes),
        }
        atomic_write_json(
            output_root / "enterprise_reconciliation_summary.json",
            {
                "schema": "qudipi.mutable-corpus.enterprise-summary",
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": snapshot.snapshot_id,
                "observed_at": observed_at,
                "summary": summary,
            },
        )
        artifact_hash_manifest(output_root)
        validate_projection_integrity(output_root)
        return {
            "snapshot_id": snapshot.snapshot_id,
            "summary": summary,
            "output_root": output_root.as_posix(),
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Durably reconcile a mutable researcher-controlled scientific corpus."
    )
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--policy")
    parser.add_argument("--expected-sources")
    parser.add_argument("--dependency-manifest")
    parser.add_argument("--observed-at")
    args = parser.parse_args()
    policy = EnterpriseCorpusPolicy.from_mapping(
        load_snapshot(Path(args.policy)) if args.policy else None
    )
    expected = load_snapshot(Path(args.expected_sources)) if args.expected_sources else None
    dependencies = (
        load_snapshot(Path(args.dependency_manifest))
        if args.dependency_manifest
        else None
    )
    result = run_enterprise_reconciliation(
        Path(args.corpus_root),
        Path(args.output_root),
        policy=policy,
        expected_sources=expected,
        dependency_manifest=dependencies,
        observed_at=args.observed_at,
    )
    print("QUDIPI_MUTABLE_CORPUS_ENTERPRISE_RECONCILIATION=PASS")
    print(f"snapshot_id={result['snapshot_id']}")
    for key, value in result["summary"].items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
