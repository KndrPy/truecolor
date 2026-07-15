from __future__ import annotations

from typing import Mapping

from analysis.prior_art.mutable_corpus import CorpusSnapshot, PhysicalFileRecord
from analysis.prior_art.mutable_corpus_enterprise import (
    DocumentVersionRecord,
    EnterpriseCorpusPolicy,
    _scientific_state,
    _version_type,
    fingerprint_document,
    stable_id,
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
