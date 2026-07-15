from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from analysis.prior_art.mutable_corpus import (
    ARXIV_PATTERN,
    DOI_PATTERN,
    PMID_PATTERN,
    YEAR_PATTERN,
    CorpusSnapshot,
    DocumentIdentity,
    ExtractedDocument,
    clean_line,
    normalized_doi,
    probable_authors,
    probable_title,
)
from analysis.prior_art.mutable_corpus_enterprise import (
    DocumentVersionRecord,
    EnterpriseCorpusPolicy,
    _scientific_state,
    _version_type,
    fingerprint_document,
    stable_id,
)


def infer_primary_identity(path: Path, extracted: ExtractedDocument) -> DocumentIdentity:
    text = extracted.text
    lowered = text.lower()
    reference_positions = [
        position
        for marker in ("\nreferences", "\nbibliography", "\nworks cited")
        if (position := lowered.find(marker)) >= 0
    ]
    bibliographic_region = text[: min(reference_positions) if reference_positions else 20_000]
    header_region = bibliographic_region[:8_000]
    searchable = "\n".join(
        (
            extracted.metadata.get("Title", ""),
            extracted.metadata.get("Subject", ""),
            header_region,
        )
    )
    dois = tuple(
        dict.fromkeys(
            normalized_doi(match) for match in DOI_PATTERN.findall(searchable)
        )
    )
    arxiv_ids = tuple(dict.fromkeys(ARXIV_PATTERN.findall(searchable)))
    pmids = tuple(dict.fromkeys(PMID_PATTERN.findall(searchable)))
    title, title_evidence = probable_title(text, extracted.metadata, path.name)
    authors = probable_authors(text, title)
    year_values = [int(value) for value in YEAR_PATTERN.findall(searchable)]
    current_year = datetime.now(timezone.utc).year
    plausible_years = [value for value in year_values if 1900 <= value <= current_year + 1]
    year = plausible_years[0] if plausible_years else None
    venue = clean_line(extracted.metadata.get("Subject", ""))
    evidence = list(title_evidence)
    if dois:
        evidence.append("primary_doi_from_bibliographic_region")
    if arxiv_ids:
        evidence.append("primary_arxiv_from_bibliographic_region")
    if pmids:
        evidence.append("primary_pmid_from_bibliographic_region")
    if authors:
        evidence.append("authors_inferred")
    if extracted.extraction_errors:
        evidence.append("extraction_errors_present")
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
        dois=dois[:1],
        arxiv_ids=arxiv_ids[:1],
        pmids=pmids[:1],
        confidence=confidence,
        evidence=tuple(evidence),
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
            "file_id": record.file_id,
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
