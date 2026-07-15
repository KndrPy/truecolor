from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

SCHEMA_VERSION = 1
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", re.IGNORECASE)
ARXIV_PATTERN = re.compile(r"(?:arxiv\s*:\s*)?(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
PMID_PATTERN = re.compile(r"(?:pmid\s*[: ]\s*)(\d{6,9})", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "the",
        "to",
        "using",
        "with",
    }
)


class ExtractionBackend(Protocol):
    def extract(self, path: Path) -> "ExtractedDocument": ...


@dataclass(frozen=True)
class CorpusPolicy:
    include_globs: tuple[str, ...] = ("**/*.pdf", "*.pdf")
    exclude_globs: tuple[str, ...] = ()
    minimum_text_characters: int = 120
    title_similarity_threshold: float = 0.86
    related_similarity_threshold: float = 0.62
    version_similarity_threshold: float = 0.78
    reference_section_markers: tuple[str, ...] = (
        "references",
        "bibliography",
        "works cited",
    )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "CorpusPolicy":
        if not value:
            return cls()
        defaults = asdict(cls())
        unknown = sorted(set(value) - set(defaults))
        if unknown:
            raise ValueError(f"unknown corpus policy fields: {', '.join(unknown)}")
        merged = {**defaults, **value}
        for key in ("include_globs", "exclude_globs", "reference_section_markers"):
            merged[key] = tuple(str(item) for item in merged[key])
        return cls(**merged)


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    metadata: Mapping[str, str] = field(default_factory=dict)
    page_count: int | None = None
    extraction_backend: str = "unknown"
    extraction_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentIdentity:
    title: str
    authors: tuple[str, ...]
    year: int | None
    venue: str
    dois: tuple[str, ...]
    arxiv_ids: tuple[str, ...]
    pmids: tuple[str, ...]
    confidence: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class PhysicalFileRecord:
    file_id: str
    relative_path: str
    size_bytes: int
    binary_sha256: str
    normalized_text_sha256: str
    simhash64: str
    page_count: int | None
    extraction_backend: str
    extraction_state: str
    extraction_errors: tuple[str, ...]
    identity: DocumentIdentity
    cited_dois: tuple[str, ...]


@dataclass(frozen=True)
class WorkRecord:
    work_id: str
    canonical_title: str
    canonical_authors: tuple[str, ...]
    publication_year: int | None
    venue: str
    canonical_dois: tuple[str, ...]
    arxiv_ids: tuple[str, ...]
    pmids: tuple[str, ...]
    identity_confidence: str
    file_ids: tuple[str, ...]
    preferred_file_id: str


@dataclass(frozen=True)
class Relationship:
    relationship_type: str
    left_file_id: str
    right_file_id: str
    confidence: str
    score: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class CorpusSnapshot:
    schema: str
    schema_version: int
    corpus_root: str
    snapshot_id: str
    observed_at: str
    files: tuple[PhysicalFileRecord, ...]
    works: tuple[WorkRecord, ...]
    relationships: tuple[Relationship, ...]
    missing_reference_candidates: tuple[Mapping[str, Any], ...]
    summary: Mapping[str, int]


class PopplerExtractionBackend:
    """Extract PDF text and metadata through bounded, non-shell subprocesses."""

    def __init__(self, timeout_seconds: int = 120) -> None:
        self.timeout_seconds = timeout_seconds

    def _run(self, command: Sequence[str]) -> tuple[int, str, str]:
        try:
            result = subprocess.run(
                list(command),
                text=True,
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return 1, "", str(error)
        return result.returncode, result.stdout, result.stderr

    def extract(self, path: Path) -> ExtractedDocument:
        errors: list[str] = []
        text_status, text, text_error = self._run(
            ("pdftotext", "-enc", "UTF-8", "-layout", str(path), "-")
        )
        if text_status != 0:
            errors.append(f"pdftotext: {text_error.strip() or 'failed'}")
            text = ""

        info_status, info_text, info_error = self._run(("pdfinfo", str(path)))
        metadata: dict[str, str] = {}
        if info_status != 0:
            errors.append(f"pdfinfo: {info_error.strip() or 'failed'}")
        else:
            for line in info_text.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()

        page_count: int | None = None
        raw_pages = metadata.get("Pages", "")
        if raw_pages.isdigit():
            page_count = int(raw_pages)

        return ExtractedDocument(
            text=text,
            metadata=metadata,
            page_count=page_count,
            extraction_backend="poppler",
            extraction_errors=tuple(errors),
        )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_unicode(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(character for character in normalized if not unicodedata.combining(character))


def normalized_text(value: str) -> str:
    return " ".join(TOKEN_PATTERN.findall(normalized_unicode(value).lower()))


def normalized_doi(value: str) -> str:
    doi = value.strip().lower()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
    return doi.rstrip(".,;:)]}")


def significant_tokens(value: str) -> frozenset[str]:
    return frozenset(
        token
        for token in TOKEN_PATTERN.findall(normalized_unicode(value).lower())
        if len(token) >= 3 and token not in STOPWORDS
    )


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    if not union:
        return 0.0
    return len(left_set & right_set) / len(union)


def simhash64(value: str) -> str:
    tokens = significant_tokens(value)
    if not tokens:
        return "0" * 16
    vector = [0] * 64
    for token in tokens:
        token_hash = int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:8], "big")
        for bit in range(64):
            vector[bit] += 1 if token_hash & (1 << bit) else -1
    fingerprint = 0
    for bit, weight in enumerate(vector):
        if weight >= 0:
            fingerprint |= 1 << bit
    return f"{fingerprint:016x}"


def hamming_similarity(left: str, right: str) -> float:
    if len(left) != 16 or len(right) != 16:
        return 0.0
    distance = (int(left, 16) ^ int(right, 16)).bit_count()
    return 1.0 - distance / 64.0


def clean_line(value: str) -> str:
    return " ".join(value.replace("\x00", " ").split()).strip()


def probable_title(text: str, metadata: Mapping[str, str], filename: str) -> tuple[str, tuple[str, ...]]:
    metadata_title = clean_line(metadata.get("Title", ""))
    rejected_metadata = {"", "untitled", "microsoft word"}
    if metadata_title.lower() not in rejected_metadata and len(metadata_title) >= 12:
        return metadata_title, ("pdf_metadata_title",)

    candidates: list[tuple[float, str]] = []
    for index, line in enumerate(text.splitlines()[:120]):
        candidate = clean_line(line)
        lowered = candidate.lower()
        if not 18 <= len(candidate) <= 300:
            continue
        if lowered.startswith(("abstract", "keywords", "doi", "http", "arxiv", "copyright")):
            continue
        words = candidate.split()
        if len(words) < 3:
            continue
        alphabetic_ratio = sum(character.isalpha() for character in candidate) / max(len(candidate), 1)
        score = alphabetic_ratio + min(len(words), 20) / 25.0 - index / 250.0
        if candidate.isupper():
            score += 0.1
        candidates.append((score, candidate))
    if candidates:
        candidates.sort(key=lambda item: (-item[0], normalized_text(item[1])))
        return candidates[0][1], ("first_page_title_inference",)
    return Path(filename).stem, ("filename_fallback",)


def probable_authors(text: str, title: str) -> tuple[str, ...]:
    lines = [clean_line(line) for line in text.splitlines()[:140]]
    title_norm = normalized_text(title)
    title_index = next((index for index, line in enumerate(lines) if title_norm and title_norm in normalized_text(line)), -1)
    start = max(title_index + 1, 0)
    author_lines: list[str] = []
    for line in lines[start : start + 12]:
        lowered = line.lower()
        if not line:
            if author_lines:
                break
            continue
        if lowered.startswith(("abstract", "department", "university", "institute", "keywords")):
            break
        if "@" in line or len(line) > 240:
            continue
        if re.search(r"\b(?:19|20)\d{2}\b", line):
            continue
        author_lines.append(line)
    joined = " ".join(author_lines)
    parts = re.split(r"\s*(?:,|;|\band\b|\u00b7|\|)\s*", joined)
    authors = []
    for part in parts:
        value = re.sub(r"[\d*\u2020\u2021]+", "", part).strip(" .")
        words = value.split()
        if 2 <= len(words) <= 6 and all(any(character.isalpha() for character in word) for word in words):
            authors.append(value)
    return tuple(dict.fromkeys(authors[:30]))


def infer_identity(path: Path, extracted: ExtractedDocument) -> DocumentIdentity:
    searchable = "\n".join((extracted.metadata.get("Title", ""), extracted.text))
    dois = tuple(sorted({normalized_doi(match) for match in DOI_PATTERN.findall(searchable)}))
    arxiv_ids = tuple(sorted(set(ARXIV_PATTERN.findall(searchable))))
    pmids = tuple(sorted(set(PMID_PATTERN.findall(searchable))))
    title, title_evidence = probable_title(extracted.text, extracted.metadata, path.name)
    authors = probable_authors(extracted.text, title)
    years = [int(value) for value in YEAR_PATTERN.findall(searchable[:12000])]
    year = min(years, key=lambda value: abs(value - datetime.now(timezone.utc).year)) if years else None
    venue = clean_line(extracted.metadata.get("Subject", ""))

    evidence = list(title_evidence)
    if dois:
        evidence.append("doi_extracted")
    if arxiv_ids:
        evidence.append("arxiv_extracted")
    if pmids:
        evidence.append("pmid_extracted")
    if authors:
        evidence.append("authors_inferred")

    if dois or pmids:
        confidence = "HIGH"
    elif arxiv_ids or (title and authors):
        confidence = "MODERATE"
    else:
        confidence = "LOW"

    return DocumentIdentity(
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        dois=dois,
        arxiv_ids=arxiv_ids,
        pmids=pmids,
        confidence=confidence,
        evidence=tuple(evidence),
    )


def is_included(relative_path: str, policy: CorpusPolicy) -> bool:
    included = any(fnmatch.fnmatch(relative_path, pattern) for pattern in policy.include_globs)
    excluded = any(fnmatch.fnmatch(relative_path, pattern) for pattern in policy.exclude_globs)
    return included and not excluded


def discover_files(root: Path, policy: CorpusPolicy) -> tuple[Path, ...]:
    if not root.is_dir():
        raise ValueError(f"corpus root is not a directory: {root}")
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if is_included(relative, policy):
            files.append(path)
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def extract_referenced_dois(text: str, own_dois: Sequence[str], policy: CorpusPolicy) -> tuple[str, ...]:
    lowered = text.lower()
    marker_positions = [lowered.rfind(marker.lower()) for marker in policy.reference_section_markers]
    marker = max(marker_positions, default=-1)
    reference_text = text[marker:] if marker >= 0 else text
    own = set(own_dois)
    return tuple(sorted({normalized_doi(value) for value in DOI_PATTERN.findall(reference_text)} - own))


def relationship_between(left: PhysicalFileRecord, right: PhysicalFileRecord, policy: CorpusPolicy) -> Relationship | None:
    evidence: list[str] = []
    if left.binary_sha256 == right.binary_sha256:
        return Relationship("EXACT_FILE_DUPLICATE", left.file_id, right.file_id, "CERTAIN", 1.0, ("binary_sha256",))
    if left.normalized_text_sha256 and left.normalized_text_sha256 == right.normalized_text_sha256:
        return Relationship("SAME_WORK_SAME_VERSION", left.file_id, right.file_id, "HIGH", 1.0, ("normalized_text_sha256",))

    left_dois = set(left.identity.dois)
    right_dois = set(right.identity.dois)
    if left_dois & right_dois:
        return Relationship("SAME_WORK_SAME_VERSION", left.file_id, right.file_id, "HIGH", 1.0, ("shared_doi",))

    title_score = jaccard(significant_tokens(left.identity.title), significant_tokens(right.identity.title))
    author_score = jaccard(
        (normalized_text(author) for author in left.identity.authors),
        (normalized_text(author) for author in right.identity.authors),
    )
    content_score = hamming_similarity(left.simhash64, right.simhash64)
    aggregate = 0.55 * title_score + 0.25 * author_score + 0.20 * content_score
    if title_score >= policy.title_similarity_threshold:
        evidence.append("high_title_similarity")
    if author_score >= 0.5:
        evidence.append("author_overlap")
    if content_score >= policy.version_similarity_threshold:
        evidence.append("content_similarity")

    identifier_difference = bool((left.identity.arxiv_ids or right.identity.arxiv_ids) and not left_dois & right_dois)
    if aggregate >= policy.version_similarity_threshold and evidence:
        kind = "SAME_WORK_DIFFERENT_VERSION" if identifier_difference or left.identity.year != right.identity.year else "SAME_WORK_SAME_VERSION"
        return Relationship(kind, left.file_id, right.file_id, "MODERATE", round(aggregate, 6), tuple(evidence))
    if aggregate >= policy.related_similarity_threshold:
        return Relationship("RELATED_WORK", left.file_id, right.file_id, "MODERATE", round(aggregate, 6), tuple(evidence or ("aggregate_similarity",)))
    return None


def stable_work_key(record: PhysicalFileRecord) -> str:
    identity = record.identity
    if identity.dois:
        return f"doi:{identity.dois[0]}"
    if identity.pmids:
        return f"pmid:{identity.pmids[0]}"
    if identity.arxiv_ids:
        return f"arxiv:{identity.arxiv_ids[0]}"
    author = normalized_text(identity.authors[0]) if identity.authors else "unknown"
    return f"title:{normalized_text(identity.title)}|author:{author}|year:{identity.year or 'unknown'}"


def build_works(files: Sequence[PhysicalFileRecord], relationships: Sequence[Relationship]) -> tuple[WorkRecord, ...]:
    parent = {record.file_id: record.file_id for record in files}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for relationship in relationships:
        if relationship.relationship_type in {
            "EXACT_FILE_DUPLICATE",
            "SAME_WORK_SAME_VERSION",
            "SAME_WORK_DIFFERENT_VERSION",
        }:
            union(relationship.left_file_id, relationship.right_file_id)

    groups: dict[str, list[PhysicalFileRecord]] = {}
    for record in files:
        groups.setdefault(find(record.file_id), []).append(record)

    works = []
    confidence_rank = {"HIGH": 3, "MODERATE": 2, "LOW": 1}
    for group in groups.values():
        ordered = sorted(
            group,
            key=lambda item: (
                -confidence_rank.get(item.identity.confidence, 0),
                -len(item.identity.dois),
                -len(item.identity.authors),
                item.relative_path,
            ),
        )
        preferred = ordered[0]
        work_key = stable_work_key(preferred)
        works.append(
            WorkRecord(
                work_id=f"WORK-{sha256_bytes(work_key.encode('utf-8'))[:20]}",
                canonical_title=preferred.identity.title,
                canonical_authors=preferred.identity.authors,
                publication_year=preferred.identity.year,
                venue=preferred.identity.venue,
                canonical_dois=tuple(sorted({doi for item in group for doi in item.identity.dois})),
                arxiv_ids=tuple(sorted({identifier for item in group for identifier in item.identity.arxiv_ids})),
                pmids=tuple(sorted({identifier for item in group for identifier in item.identity.pmids})),
                identity_confidence=preferred.identity.confidence,
                file_ids=tuple(sorted(item.file_id for item in group)),
                preferred_file_id=preferred.file_id,
            )
        )
    return tuple(sorted(works, key=lambda item: item.work_id))


def snapshot_corpus(
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
    raw_text_by_file: dict[str, str] = {}
    for path in discover_files(root, policy):
        relative_path = path.relative_to(root).as_posix()
        binary_hash = sha256_file(path)
        extracted = backend.extract(path)
        identity = infer_identity(path, extracted)
        normalized = normalized_text(extracted.text)
        file_id = f"FILE-{binary_hash[:20]}"
        extraction_state = "EXTRACTED" if len(normalized) >= policy.minimum_text_characters else "INSUFFICIENT_TEXT"
        record = PhysicalFileRecord(
            file_id=file_id,
            relative_path=relative_path,
            size_bytes=path.stat().st_size,
            binary_sha256=binary_hash,
            normalized_text_sha256=sha256_bytes(normalized.encode("utf-8")) if normalized else "",
            simhash64=simhash64(normalized),
            page_count=extracted.page_count,
            extraction_backend=extracted.extraction_backend,
            extraction_state=extraction_state,
            extraction_errors=extracted.extraction_errors,
            identity=identity,
            cited_dois=extract_referenced_dois(extracted.text, identity.dois, policy),
        )
        records.append(record)
        raw_text_by_file[file_id] = normalized

    relationships = []
    for index, left in enumerate(records):
        for right in records[index + 1 :]:
            relationship = relationship_between(left, right, policy)
            if relationship is not None:
                relationships.append(relationship)
    relationships.sort(key=lambda item: (item.relationship_type, item.left_file_id, item.right_file_id))

    works = build_works(records, relationships)
    corpus_dois = {doi for work in works for doi in work.canonical_dois}
    citations: dict[str, set[str]] = {}
    for record in records:
        for doi in record.cited_dois:
            if doi not in corpus_dois:
                citations.setdefault(doi, set()).add(record.file_id)
    missing = tuple(
        {
            "doi": doi,
            "state": "CITED_WORK_NOT_INGESTED",
            "citing_file_ids": sorted(file_ids),
            "citation_count": len(file_ids),
        }
        for doi, file_ids in sorted(citations.items())
    )

    summary = {
        "physical_file_count": len(records),
        "scientific_work_count": len(works),
        "exact_duplicate_count": sum(item.relationship_type == "EXACT_FILE_DUPLICATE" for item in relationships),
        "same_work_version_relationship_count": sum(item.relationship_type.startswith("SAME_WORK") for item in relationships),
        "related_work_relationship_count": sum(item.relationship_type == "RELATED_WORK" for item in relationships),
        "insufficient_text_count": sum(item.extraction_state != "EXTRACTED" for item in records),
        "missing_reference_candidate_count": len(missing),
    }
    canonical_payload = {
        "files": [asdict(item) for item in records],
        "works": [asdict(item) for item in works],
        "relationships": [asdict(item) for item in relationships],
        "policy": asdict(policy),
    }
    snapshot_id = f"SNAPSHOT-{sha256_bytes(json.dumps(canonical_payload, sort_keys=True, separators=(',', ':')).encode('utf-8'))[:24]}"
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
    write_snapshot(output_root, snapshot, policy)
    return snapshot


def load_snapshot(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compare_snapshots(previous: Mapping[str, Any] | None, current: CorpusSnapshot) -> tuple[Mapping[str, Any], ...]:
    if not previous:
        return tuple(
            {"event_type": "FILE_ADDED", "file_id": record.file_id, "relative_path": record.relative_path}
            for record in current.files
        )
    previous_files = {item["file_id"]: item for item in previous.get("files", [])}
    current_files = {item.file_id: item for item in current.files}
    events: list[Mapping[str, Any]] = []
    for file_id in sorted(current_files.keys() - previous_files.keys()):
        record = current_files[file_id]
        events.append({"event_type": "FILE_ADDED", "file_id": file_id, "relative_path": record.relative_path})
    for file_id in sorted(previous_files.keys() - current_files.keys()):
        record = previous_files[file_id]
        events.append({"event_type": "FILE_REMOVED", "file_id": file_id, "relative_path": record["relative_path"]})
    for file_id in sorted(previous_files.keys() & current_files.keys()):
        before = previous_files[file_id]
        after = current_files[file_id]
        if before["relative_path"] != after.relative_path:
            events.append(
                {
                    "event_type": "FILE_MOVED",
                    "file_id": file_id,
                    "previous_path": before["relative_path"],
                    "relative_path": after.relative_path,
                }
            )
        if before.get("identity") != asdict(after.identity):
            events.append({"event_type": "IDENTITY_CHANGED", "file_id": file_id, "relative_path": after.relative_path})
    return tuple(events)


def invalidated_artifacts(events: Sequence[Mapping[str, Any]], dependency_manifest: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...]:
    if not dependency_manifest or not events:
        return ()
    changed_ids = {str(event.get("file_id", "")) for event in events}
    invalidated = []
    for artifact in dependency_manifest.get("artifacts", []):
        dependencies = set(str(value) for value in artifact.get("source_file_ids", []))
        overlap = sorted(changed_ids & dependencies)
        if overlap:
            invalidated.append(
                {
                    "artifact_path": artifact.get("artifact_path", ""),
                    "state": "STALE",
                    "changed_source_file_ids": overlap,
                }
            )
    return tuple(sorted(invalidated, key=lambda item: item["artifact_path"]))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_snapshot(output_root: Path, snapshot: CorpusSnapshot, policy: CorpusPolicy) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    payload = asdict(snapshot)
    write_json(output_root / "corpus_snapshot.json", payload)
    write_json(output_root / "physical_file_registry.json", {"schema_version": SCHEMA_VERSION, "records": payload["files"]})
    write_json(output_root / "scientific_work_registry.json", {"schema_version": SCHEMA_VERSION, "records": payload["works"]})
    write_json(output_root / "document_relationships.json", {"schema_version": SCHEMA_VERSION, "records": payload["relationships"]})
    write_json(output_root / "missing_reference_candidates.json", {"schema_version": SCHEMA_VERSION, "records": payload["missing_reference_candidates"]})
    write_json(output_root / "corpus_policy_effective.json", asdict(policy))


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover and reconcile a researcher-controlled scientific PDF corpus.")
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--policy")
    parser.add_argument("--previous-snapshot")
    parser.add_argument("--dependency-manifest")
    parser.add_argument("--observed-at")
    args = parser.parse_args()

    policy_value = load_snapshot(Path(args.policy)) if args.policy else None
    policy = CorpusPolicy.from_mapping(policy_value)
    previous = load_snapshot(Path(args.previous_snapshot)) if args.previous_snapshot else None
    dependency_manifest = load_snapshot(Path(args.dependency_manifest)) if args.dependency_manifest else None

    snapshot = snapshot_corpus(
        Path(args.corpus_root),
        Path(args.output_root),
        policy=policy,
        observed_at=args.observed_at,
    )
    events = compare_snapshots(previous, snapshot)
    stale = invalidated_artifacts(events, dependency_manifest)
    write_json(
        Path(args.output_root) / "corpus_change_set.json",
        {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot.snapshot_id,
            "events": events,
        },
    )
    write_json(
        Path(args.output_root) / "stale_downstream_artifact_report.json",
        {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot.snapshot_id,
            "records": stale,
        },
    )
    print("QUDIPI_MUTABLE_CORPUS_RECONCILIATION=PASS")
    print(f"snapshot_id={snapshot.snapshot_id}")
    for key, value in snapshot.summary.items():
        print(f"{key}={value}")
    print(f"change_event_count={len(events)}")
    print(f"stale_downstream_artifact_count={len(stale)}")


if __name__ == "__main__":
    main()
