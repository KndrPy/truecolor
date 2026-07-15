from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.prior_art.mutable_corpus import ExtractedDocument
from analysis.prior_art.mutable_corpus_enterprise import (
    EnterpriseCorpusError,
    EnterpriseCorpusPolicy,
    run_enterprise_reconciliation,
)
from analysis.prior_art.mutable_corpus_runtime import run_runtime


class FakeBackend:
    def __init__(self, documents: dict[str, ExtractedDocument]) -> None:
        self.documents = documents

    def extract(self, path: Path) -> ExtractedDocument:
        return self.documents[path.name]


def scientific_document(
    title: str,
    body: str,
    *,
    doi: str = "",
    arxiv: str = "",
    authors: str = "Ada Researcher and Bruno Scientist",
    venue: str = "Journal of Reproducible Research",
    year: int = 2025,
    errors: tuple[str, ...] = (),
) -> ExtractedDocument:
    identifiers = []
    if doi:
        identifiers.append(f"https://doi.org/{doi}")
    if arxiv:
        identifiers.append(f"arXiv:{arxiv}")
    text = (
        f"{title}\n"
        f"{authors}\n"
        f"{venue} {year}\n"
        + "\n".join(identifiers)
        + "\n\nAbstract\n"
        + body
        + "\n\nIntroduction\n"
        + body
        + "\n\nMethods\n"
        + body
        + "\n\nResults\n"
        + body
        + "\n\nReferences\n"
    )
    return ExtractedDocument(
        text=text,
        metadata={"Title": title, "Subject": venue, "Pages": "12"},
        page_count=12,
        extraction_backend="fake",
        extraction_errors=errors,
    )


def write_pdf(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\n" + payload)


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_required_enterprise_outputs_are_emitted_without_fixed_count(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "arbitrary-name.pdf", b"one")
    backend = FakeBackend(
        {
            "arbitrary-name.pdf": scientific_document(
                "Spectral Reconstruction of Human Skin",
                "Controlled acquisition and quantitative validation. " * 30,
                doi="10.1000/skin.1",
            )
        }
    )
    result = run_enterprise_reconciliation(
        corpus,
        output,
        backend=backend,
        observed_at="2026-07-15T00:00:00Z",
    )
    assert result["summary"]["physical_file_count"] == 1
    required = {
        "corpus_snapshot.json",
        "scientific_work_registry.json",
        "document_version_registry.json",
        "physical_file_registry.json",
        "exact_duplicate_report.json",
        "version_family_report.json",
        "ambiguous_identity_queue.json",
        "unreadable_document_report.json",
        "non_scientific_document_report.json",
        "corpus_change_set.json",
        "stale_downstream_artifact_report.json",
        "missing_reference_candidates.json",
        "stage1_review_queue_projection.json",
        "artifact_hashes.json",
    }
    assert required <= {path.name for path in output.iterdir() if path.is_file()}
    versions = load(output / "document_version_registry.json")["records"]
    assert len(versions) == 1
    assert versions[0]["fingerprint"]["minhash_signature"]
    assert versions[0]["fingerprint"]["section_heading_signature"]
    assert versions[0]["fingerprint"]["abstract_sha256"]
    assert versions[0]["current_state"] == "ACTIVE"


def test_copy_is_exact_duplicate_but_remains_two_physical_files(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    payload = b"identical-publisher-pdf"
    write_pdf(corpus / "first.pdf", payload)
    write_pdf(corpus / "renamed-copy.pdf", payload)
    extracted = scientific_document(
        "One Scientific Work",
        "The same controlled study and results. " * 30,
        doi="10.1000/duplicate.1",
    )
    run_enterprise_reconciliation(
        corpus,
        output,
        backend=FakeBackend({"first.pdf": extracted, "renamed-copy.pdf": extracted}),
        observed_at="2026-07-15T00:00:00Z",
    )
    files = load(output / "physical_file_registry.json")["records"]
    duplicates = load(output / "exact_duplicate_report.json")["records"]
    works = load(output / "scientific_work_registry.json")["records"]
    assert len(files) == 2
    assert len({record["file_id"] for record in files}) == 2
    assert len(duplicates) == 1
    assert len(works) == 1


def test_preprint_and_journal_are_grouped_as_version_family(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "draft.pdf", b"draft")
    write_pdf(corpus / "publisher.pdf", b"publisher")
    body = "A shared experimental design, cohort, model, measurements, and findings. " * 50
    backend = FakeBackend(
        {
            "draft.pdf": scientific_document(
                "A Durable Spectral Reconstruction Method",
                body,
                arxiv="2501.12345",
                venue="arXiv preprint",
                year=2025,
            ),
            "publisher.pdf": scientific_document(
                "A Durable Spectral Reconstruction Method",
                body,
                doi="10.1000/durable.2026",
                venue="Journal of Durable Science",
                year=2026,
            ),
        }
    )
    run_enterprise_reconciliation(
        corpus,
        output,
        backend=backend,
        observed_at="2026-07-15T00:00:00Z",
    )
    versions = load(output / "document_version_registry.json")["records"]
    relations = load(output / "version_family_report.json")["records"]
    assert {record["version_type"] for record in versions} == {"PREPRINT", "JOURNAL"}
    assert any(
        record["relationship_type"] == "SAME_WORK_DIFFERENT_VERSION"
        for record in relations
    )


def test_conflicting_doi_and_high_bibliographic_similarity_is_ambiguous(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "left.pdf", b"left")
    write_pdf(corpus / "right.pdf", b"right")
    body = "The identical title and author evidence creates an identifier conflict. " * 40
    backend = FakeBackend(
        {
            "left.pdf": scientific_document(
                "Conflicting Scientific Identity",
                body,
                doi="10.1000/conflict.left",
            ),
            "right.pdf": scientific_document(
                "Conflicting Scientific Identity",
                body,
                doi="10.1000/conflict.right",
            ),
        }
    )
    run_enterprise_reconciliation(
        corpus,
        output,
        backend=backend,
        observed_at="2026-07-15T00:00:00Z",
    )
    issues = load(output / "ambiguous_identity_queue.json")["records"]
    assert any(
        "CONFLICTING_PRIMARY_DOI_WITH_HIGH_BIBLIOGRAPHIC_SIMILARITY"
        in record["reasons"]
        for record in issues
    )
    works = load(output / "scientific_work_registry.json")["records"]
    assert len(works) == 2


def test_unreadable_and_non_scientific_documents_are_preserved(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "broken.pdf", b"broken")
    write_pdf(corpus / "brochure.pdf", b"brochure")
    backend = FakeBackend(
        {
            "broken.pdf": ExtractedDocument(
                text="",
                metadata={},
                page_count=None,
                extraction_backend="fake",
                extraction_errors=("parser failure",),
            ),
            "brochure.pdf": ExtractedDocument(
                text="Product brochure and contact information",
                metadata={"Title": "Product brochure"},
                page_count=1,
                extraction_backend="fake",
            ),
        }
    )
    run_enterprise_reconciliation(
        corpus,
        output,
        backend=backend,
        observed_at="2026-07-15T00:00:00Z",
    )
    unreadable = load(output / "unreadable_document_report.json")["records"]
    non_scientific = load(output / "non_scientific_document_report.json")["records"]
    assert len(unreadable) == 1
    assert unreadable[0]["current_state"] == "UNREADABLE_DOCUMENT"
    assert len(non_scientific) == 1
    assert non_scientific[0]["current_state"] == "NON_SCIENTIFIC_DOCUMENT"


def test_invalid_pdf_signature_is_rejected_with_evidence(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    corpus.mkdir()
    (corpus / "fake.pdf").write_bytes(b"not-a-pdf")
    with pytest.raises(EnterpriseCorpusError):
        run_enterprise_reconciliation(
            corpus,
            output,
            backend=FakeBackend({}),
            observed_at="2026-07-15T00:00:00Z",
        )
    report = load(output / "corpus_preflight_report.json")
    assert report["records"][0]["state"] == "REJECTED"
    assert "INVALID_PDF_SIGNATURE" in report["records"][0]["reasons"]


def test_runtime_retains_removal_history_and_emits_relationship_events(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "original.pdf", b"same")
    write_pdf(corpus / "copy.pdf", b"same")
    extracted = scientific_document(
        "Persistent Lifecycle",
        "Persistent scientific evidence. " * 40,
        doi="10.1000/lifecycle.1",
    )
    first_backend = FakeBackend({"original.pdf": extracted, "copy.pdf": extracted})
    run_runtime(
        corpus,
        output,
        EnterpriseCorpusPolicy(),
        None,
        None,
        "2026-07-15T00:00:00Z",
        backend=first_backend,
    )
    first_events = load(output / "corpus_change_set.json")["events"]
    assert any(event["event_type"] == "DUPLICATE_DETECTED" for event in first_events)
    (corpus / "copy.pdf").unlink()
    second_backend = FakeBackend({"original.pdf": extracted})
    run_runtime(
        corpus,
        output,
        EnterpriseCorpusPolicy(),
        None,
        None,
        "2026-07-15T01:00:00Z",
        backend=second_backend,
    )
    lifecycle = load(output / "physical_file_lifecycle_registry.json")["records"]
    assert {record["current_state"] for record in lifecycle} == {"PRESENT", "REMOVED"}
    events = load(output / "corpus_change_set.json")["events"]
    assert any(event["event_type"] == "FILE_REMOVED" for event in events)
    assert any(event["event_type"] == "DUPLICATE_RESOLVED" for event in events)
    ledger = (output / "history" / "corpus_event_ledger.jsonl").read_text(encoding="utf-8")
    assert "FILE_REMOVED" in ledger
    assert "DUPLICATE_DETECTED" in ledger


def test_runtime_detects_rename_without_new_scientific_work(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    original = corpus / "001.pdf"
    write_pdf(original, b"stable")
    extracted = scientific_document(
        "Identity Independent of Filename",
        "Stable scientific content. " * 40,
        doi="10.1000/rename.1",
    )
    run_runtime(
        corpus,
        output,
        EnterpriseCorpusPolicy(),
        None,
        None,
        "2026-07-15T00:00:00Z",
        backend=FakeBackend({"001.pdf": extracted}),
    )
    original.rename(corpus / "researcher-renamed-anything.pdf")
    run_runtime(
        corpus,
        output,
        EnterpriseCorpusPolicy(),
        None,
        None,
        "2026-07-15T01:00:00Z",
        backend=FakeBackend({"researcher-renamed-anything.pdf": extracted}),
    )
    events = load(output / "corpus_change_set.json")["events"]
    assert [event["event_type"] for event in events].count("FILE_MOVED") == 1
    works = load(output / "scientific_work_registry.json")["records"]
    assert len(works) == 1


def test_replacement_and_dependency_invalidation_are_durable(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    path = corpus / "paper.pdf"
    write_pdf(path, b"version-one")
    first_document = scientific_document(
        "First Identity",
        "First scientific body. " * 40,
        doi="10.1000/first.1",
    )
    run_runtime(
        corpus,
        output,
        EnterpriseCorpusPolicy(),
        None,
        None,
        "2026-07-15T00:00:00Z",
        backend=FakeBackend({"paper.pdf": first_document}),
    )
    first_file_id = load(output / "physical_file_registry.json")["records"][0]["file_id"]
    write_pdf(path, b"version-two")
    dependencies = {
        "artifacts": [
            {"artifact_path": "derived/evidence.json", "source_file_ids": [first_file_id]}
        ]
    }
    second_document = scientific_document(
        "Second Identity",
        "Second scientific body. " * 40,
        doi="10.1000/second.1",
    )
    run_runtime(
        corpus,
        output,
        EnterpriseCorpusPolicy(),
        None,
        dependencies,
        "2026-07-15T01:00:00Z",
        backend=FakeBackend({"paper.pdf": second_document}),
    )
    events = load(output / "corpus_change_set.json")["events"]
    assert any(event["event_type"] == "FILE_REPLACED" for event in events)
    stale = load(output / "stale_downstream_artifact_report.json")["records"]
    assert stale[0]["artifact_path"] == "derived/evidence.json"


def test_expected_sources_claims_and_prior_identifiers_are_reported_without_download(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "present.pdf", b"present")
    expected = {
        "records": [
            {
                "source_id": "EXPECTED-1",
                "title": "Absent Required Source",
                "doi": "10.1000/absent.1",
                "required": True,
                "claims": ["CLAIM-1"],
            }
        ]
    }
    run_enterprise_reconciliation(
        corpus,
        output,
        expected_sources=expected,
        backend=FakeBackend(
            {
                "present.pdf": scientific_document(
                    "Present Source",
                    "Present scientific body. " * 40,
                    doi="10.1000/present.1",
                )
            }
        ),
        observed_at="2026-07-15T00:00:00Z",
    )
    missing = load(output / "missing_reference_candidates.json")["records"]
    assert any(
        record["state"] == "IDENTIFIER_KNOWN_FILE_ABSENT"
        and record["claims"] == ["CLAIM-1"]
        for record in missing
    )


def test_generic_code_does_not_use_filename_numbering_or_fixed_corpus_count() -> None:
    enterprise_source = Path(
        "analysis/prior_art/mutable_corpus_enterprise.py"
    ).read_text(encoding="utf-8")
    runtime_source = Path(
        "analysis/prior_art/mutable_corpus_runtime.py"
    ).read_text(encoding="utf-8")
    combined = enterprise_source + runtime_source
    assert "review_order" not in combined
    assert "exact_filename_number" not in combined
    assert "configured_review_record_count" not in combined
    assert "range(1, 33)" not in combined
