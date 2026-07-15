from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from analysis.prior_art.mutable_corpus import (
    ARXIV_PATTERN,
    DOI_PATTERN,
    PMID_PATTERN,
    YEAR_PATTERN,
    CorpusSnapshot,
    DocumentIdentity,
    ExtractedDocument,
    PhysicalFileRecord,
    clean_line,
    normalized_doi,
    probable_authors,
    probable_title,
)
from analysis.prior_art.mutable_corpus_enterprise import (
    DocumentVersionRecord,
    EnterpriseCorpusPolicy,
    IdentityIssue,
    VersionRelationship,
    _jaccard,
    _minhash_similarity,
    _scientific_state,
    _tokens,
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


def infer_version_relationships(
    versions: Sequence[DocumentVersionRecord],
    records: Mapping[str, PhysicalFileRecord],
    policy: EnterpriseCorpusPolicy,
) -> tuple[tuple[VersionRelationship, ...], tuple[IdentityIssue, ...]]:
    """Resolve relationships using independent, conservative evidence channels."""
    relationships: list[VersionRelationship] = []
    issues: list[IdentityIssue] = []
    published_types = {"JOURNAL", "PUBLISHED", "CONFERENCE"}

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
                left_pmid = left.fingerprint.primary_pmid
                right_pmid = right.fingerprint.primary_pmid
                same_doi = bool(left_doi and left_doi == right_doi)
                same_pmid = bool(left_pmid and left_pmid == right_pmid)
                distinct_dois = bool(left_doi and right_doi and left_doi != right_doi)
                distinct_pmids = bool(left_pmid and right_pmid and left_pmid != right_pmid)

                title_score = _jaccard(
                    _tokens(left.extracted_title), _tokens(right.extracted_title)
                )
                author_score = _jaccard(
                    left.fingerprint.normalized_authors,
                    right.fingerprint.normalized_authors,
                )
                abstract_score = _jaccard(
                    left.fingerprint.abstract_tokens,
                    right.fingerprint.abstract_tokens,
                )
                content_score = _minhash_similarity(
                    left.fingerprint.minhash_signature,
                    right.fingerprint.minhash_signature,
                )
                reference_score = _jaccard(
                    left.fingerprint.reference_dois,
                    right.fingerprint.reference_dois,
                )
                score = round(
                    0.32 * title_score
                    + 0.18 * author_score
                    + 0.22 * abstract_score
                    + 0.20 * content_score
                    + 0.08 * reference_score,
                    6,
                )
                strong_title = title_score >= policy.title_match_threshold
                strong_content = content_score >= policy.content_match_threshold
                related_content = content_score >= policy.related_work_threshold
                strong_abstract = abstract_score >= policy.abstract_match_threshold
                exact_abstract = bool(
                    left.fingerprint.abstract_sha256
                    and left.fingerprint.abstract_sha256
                    == right.fingerprint.abstract_sha256
                )
                author_support = author_score >= policy.author_match_threshold
                strong_bibliographic_convergence = strong_title and (
                    author_support or strong_abstract or strong_content or exact_abstract
                )

                if same_doi or same_pmid:
                    relation = "SAME_WORK_SAME_VERSION"
                    confidence = "HIGH"
                    evidence.append("shared_primary_doi" if same_doi else "shared_primary_pmid")
                elif (distinct_dois or distinct_pmids) and strong_bibliographic_convergence:
                    issue_payload = {
                        "left_doi": left_doi,
                        "right_doi": right_doi,
                        "left_pmid": left_pmid,
                        "right_pmid": right_pmid,
                        "title_score": title_score,
                        "author_score": author_score,
                        "abstract_score": abstract_score,
                        "content_score": content_score,
                    }
                    reason = (
                        "CONFLICTING_PRIMARY_DOI_WITH_HIGH_BIBLIOGRAPHIC_SIMILARITY"
                        if distinct_dois
                        else "CONFLICTING_PRIMARY_PMID_WITH_HIGH_BIBLIOGRAPHIC_SIMILARITY"
                    )
                    issues.append(
                        IdentityIssue(
                            issue_id=stable_id("ISSUE", issue_payload),
                            state="AMBIGUOUS_IDENTITY",
                            severity="HIGH",
                            file_ids=tuple(sorted((left.file_id, right.file_id))),
                            work_ids=tuple(sorted((left.work_id, right.work_id))),
                            reasons=(reason,),
                            evidence=issue_payload,
                        )
                    )
                    relation = "AMBIGUOUS_IDENTITY"
                    confidence = "HIGH"
                    evidence.append("conflicting_primary_identifier")
                else:
                    preprint_published_pair = (
                        left.version_type == "PREPRINT" and right.version_type in published_types
                    ) or (
                        right.version_type == "PREPRINT" and left.version_type in published_types
                    )
                    same_version_evidence = bool(
                        left_file.normalized_text_sha256
                        and left_file.normalized_text_sha256
                        == right_file.normalized_text_sha256
                    )
                    version_family_evidence = strong_title and (
                        exact_abstract
                        or (strong_abstract and related_content)
                        or (strong_content and author_support)
                    )

                    if same_version_evidence:
                        relation = "SAME_WORK_SAME_VERSION"
                        confidence = "HIGH"
                        evidence.append("normalized_text_sha256")
                    elif preprint_published_pair and version_family_evidence:
                        relation = "SAME_WORK_DIFFERENT_VERSION"
                        confidence = "HIGH"
                        evidence.extend(("preprint_published_pair", "high_title_similarity"))
                        if exact_abstract:
                            evidence.append("exact_abstract_fingerprint")
                        elif strong_abstract:
                            evidence.append("abstract_similarity")
                        if strong_content:
                            evidence.append("content_similarity")
                        elif related_content:
                            evidence.append("related_content_similarity")
                        if author_support:
                            evidence.append("author_overlap")
                    elif version_family_evidence:
                        relation = (
                            "SAME_WORK_DIFFERENT_VERSION"
                            if left.version_type != right.version_type
                            else "SAME_WORK_SAME_VERSION"
                        )
                        confidence = "MODERATE"
                        evidence.extend(("bibliographic_similarity", "independent_version_evidence"))
                    elif score >= policy.related_work_threshold:
                        relation = "RELATED_WORK"
                        confidence = "MODERATE"
                        evidence.append("aggregate_similarity")
                    else:
                        continue

            relationship_payload = {
                "type": relation,
                "left": min(left.version_id, right.version_id),
                "right": max(left.version_id, right.version_id),
            }
            relationships.append(
                VersionRelationship(
                    relationship_id=stable_id("REL", relationship_payload),
                    relationship_type=relation,
                    left_version_id=relationship_payload["left"],
                    right_version_id=relationship_payload["right"],
                    confidence=confidence,
                    score=score,
                    evidence=tuple(evidence),
                )
            )

    return (
        tuple(sorted(relationships, key=lambda item: item.relationship_id)),
        tuple(sorted(issues, key=lambda item: item.issue_id)),
    )
