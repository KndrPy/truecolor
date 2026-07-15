from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from analysis.prior_art.mutable_corpus import (
    CorpusPolicy,
    ExtractedDocument,
)
from analysis.prior_art.mutable_corpus_service import (
    compare_snapshot_states,
    reconcile_corpus,
    run_reconciliation,
)


class FakeExtractionBackend:
    def __init__(self, documents: dict[str, ExtractedDocument]) -> None:
        self.documents = documents

    def extract(self, path: Path) -> ExtractedDocument:
        return self.documents[path.name]


def document(
    title: str,
    doi: str,
    body: str,
    authors: str = "Ada Researcher and Bruno Scientist",
    year: int = 2025,
) -> ExtractedDocument:
    text = (
        f"{title}\n"
        f"{authors}\n"
        f"Journal of Reproducible Research {year}\n"
        f"https://doi.org/{doi}\n\n"
        "Abstract\n"
        f"{body}\n\n"
        "References\n"
    )
    return ExtractedDocument(
        text=text,
        metadata={"Title": title, "Subject": "Journal of Reproducible Research"},
        page_count=8,
        extraction_backend="fake",
    )


def write_pdf(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_researcher_order_and_filename_do_not_define_identity(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "99_unrelated_filename.pdf", b"paper-a")
    backend = FakeExtractionBackend(
        {
            "99_unrelated_filename.pdf": document(
                "Spectral Reconstruction of Human Skin",
                "10.1000/skin.2025.1",
                "A sufficiently long scientific body " * 20,
            )
        }
    )

    snapshot = reconcile_corpus(
        corpus,
        output,
        backend=backend,
        observed_at="2026-07-15T00:00:00Z",
    )

    assert snapshot.summary["physical_file_count"] == 1
    assert snapshot.summary["scientific_work_count"] == 1
    assert snapshot.works[0].canonical_title == "Spectral Reconstruction of Human Skin"
    assert snapshot.works[0].canonical_dois == ("10.1000/skin.2025.1",)
    assert snapshot.files[0].relative_path == "99_unrelated_filename.pdf"


def test_exact_duplicate_files_remain_distinct_physical_files_but_one_work(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    payload = b"same-publisher-pdf-bytes"
    write_pdf(corpus / "original.pdf", payload)
    write_pdf(corpus / "renamed-copy.pdf", payload)
    extracted = document(
        "A Canonical Scientific Work",
        "10.1000/canonical.1",
        "Substantial scientific content " * 20,
    )
    backend = FakeExtractionBackend(
        {
            "original.pdf": extracted,
            "renamed-copy.pdf": extracted,
        }
    )

    snapshot = reconcile_corpus(
        corpus,
        output,
        backend=backend,
        observed_at="2026-07-15T00:00:00Z",
    )

    assert snapshot.summary["physical_file_count"] == 2
    assert len({record.file_id for record in snapshot.files}) == 2
    assert snapshot.summary["exact_duplicate_count"] == 1
    assert snapshot.summary["scientific_work_count"] == 1
    assert len(snapshot.works[0].file_ids) == 2


def test_distinct_dois_prevent_title_similarity_from_collapsing_distinct_works(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "first.pdf", b"first")
    write_pdf(corpus / "second.pdf", b"second")
    backend = FakeExtractionBackend(
        {
            "first.pdf": document(
                "Skin Reflectance Reconstruction with RGB Cameras",
                "10.1000/first",
                "First method and validation cohort " * 20,
            ),
            "second.pdf": document(
                "Skin Reflectance Reconstruction with RGB Cameras",
                "10.1000/second",
                "Second independent method and validation cohort " * 20,
                year=2026,
            ),
        }
    )

    snapshot = reconcile_corpus(
        corpus,
        output,
        backend=backend,
        observed_at="2026-07-15T00:00:00Z",
    )

    assert snapshot.summary["scientific_work_count"] == 2
    assert all(
        relationship.relationship_type not in {
            "SAME_WORK_SAME_VERSION",
            "SAME_WORK_DIFFERENT_VERSION",
        }
        for relationship in snapshot.relationships
    )


def test_rename_is_reported_as_move_without_researcher_mapping(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"
    payload = b"stable-document-content"
    original = corpus / "paper-old-name.pdf"
    renamed = corpus / "arbitrary-new-name.pdf"
    write_pdf(original, payload)
    extracted = document(
        "Stable Identity Across Rename",
        "10.1000/rename",
        "Stable body text " * 30,
    )
    first_backend = FakeExtractionBackend({original.name: extracted})
    first = reconcile_corpus(
        corpus,
        first_output,
        backend=first_backend,
        observed_at="2026-07-15T00:00:00Z",
    )

    original.rename(renamed)
    second_backend = FakeExtractionBackend({renamed.name: extracted})
    second = reconcile_corpus(
        corpus,
        second_output,
        backend=second_backend,
        observed_at="2026-07-15T01:00:00Z",
    )
    events = compare_snapshot_states(asdict(first), second)

    assert len(events) == 1
    assert events[0]["event_type"] == "FILE_MOVED"
    assert events[0]["previous_path"] == "paper-old-name.pdf"
    assert events[0]["relative_path"] == "arbitrary-new-name.pdf"


def test_replacement_at_same_path_is_reported_as_replaced(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    path = corpus / "paper.pdf"
    write_pdf(path, b"version-one")
    first = reconcile_corpus(
        corpus,
        tmp_path / "first",
        backend=FakeExtractionBackend(
            {
                "paper.pdf": document(
                    "Version One",
                    "10.1000/version-one",
                    "First body " * 30,
                )
            }
        ),
        observed_at="2026-07-15T00:00:00Z",
    )

    write_pdf(path, b"version-two")
    second = reconcile_corpus(
        corpus,
        tmp_path / "second",
        backend=FakeExtractionBackend(
            {
                "paper.pdf": document(
                    "Version Two",
                    "10.1000/version-two",
                    "Second body " * 30,
                )
            }
        ),
        observed_at="2026-07-15T01:00:00Z",
    )
    events = compare_snapshot_states(asdict(first), second)

    assert [event["event_type"] for event in events] == ["FILE_REPLACED"]


def test_add_remove_and_include_exclude_are_runtime_policy_driven(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    write_pdf(corpus / "included.pdf", b"included")
    write_pdf(corpus / "drafts" / "excluded.pdf", b"excluded")
    policy = CorpusPolicy(exclude_globs=("drafts/*",))
    backend = FakeExtractionBackend(
        {
            "included.pdf": document(
                "Included Work",
                "10.1000/included",
                "Included content " * 30,
            )
        }
    )

    snapshot = reconcile_corpus(
        corpus,
        tmp_path / "output",
        policy=policy,
        backend=backend,
        observed_at="2026-07-15T00:00:00Z",
    )

    assert [record.relative_path for record in snapshot.files] == ["included.pdf"]


def test_cited_but_absent_doi_is_emitted_as_candidate_not_downloaded(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    write_pdf(corpus / "paper.pdf", b"paper")
    extracted = document(
        "Reference Discovery",
        "10.1000/present",
        "Primary evidence " * 20,
    )
    extracted = ExtractedDocument(
        text=extracted.text + "Missing Work https://doi.org/10.1000/missing\n",
        metadata=extracted.metadata,
        page_count=extracted.page_count,
        extraction_backend=extracted.extraction_backend,
    )

    snapshot = reconcile_corpus(
        corpus,
        tmp_path / "output",
        backend=FakeExtractionBackend({"paper.pdf": extracted}),
        observed_at="2026-07-15T00:00:00Z",
    )

    assert snapshot.missing_reference_candidates == (
        {
            "doi": "10.1000/missing",
            "state": "CITED_WORK_NOT_INGESTED",
            "citing_file_ids": [snapshot.files[0].file_id],
            "citation_count": 1,
        },
    )


def test_downstream_artifacts_are_invalidated_only_by_declared_dependencies(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    write_pdf(corpus / "paper.pdf", b"paper")
    backend = FakeExtractionBackend(
        {
            "paper.pdf": document(
                "Dependency Work",
                "10.1000/dependency",
                "Dependency content " * 30,
            )
        }
    )
    preliminary = reconcile_corpus(
        corpus,
        tmp_path / "preliminary",
        backend=backend,
        observed_at="2026-07-15T00:00:00Z",
    )
    file_id = preliminary.files[0].file_id
    dependencies = {
        "artifacts": [
            {
                "artifact_path": "artifacts/stage_01/evidence.json",
                "source_file_ids": [file_id],
            },
            {
                "artifact_path": "artifacts/stage_01/unrelated.json",
                "source_file_ids": ["FILE-unrelated"],
            },
        ]
    }

    run_reconciliation(
        corpus,
        tmp_path / "run",
        CorpusPolicy(),
        None,
        dependencies,
        "2026-07-15T00:00:00Z",
        backend=backend,
    )
    stale = json.loads(
        (tmp_path / "run" / "stale_downstream_artifact_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert stale["records"] == [
        {
            "artifact_path": "artifacts/stage_01/evidence.json",
            "state": "STALE",
            "changed_source_file_ids": [file_id],
        }
    ]


def test_snapshot_id_is_deterministic_and_excludes_observation_time(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    write_pdf(corpus / "paper.pdf", b"paper")
    backend = FakeExtractionBackend(
        {
            "paper.pdf": document(
                "Deterministic Work",
                "10.1000/deterministic",
                "Deterministic content " * 30,
            )
        }
    )

    first = reconcile_corpus(
        corpus,
        tmp_path / "first",
        backend=backend,
        observed_at="2026-07-15T00:00:00Z",
    )
    second = reconcile_corpus(
        corpus,
        tmp_path / "second",
        backend=backend,
        observed_at="2026-07-16T00:00:00Z",
    )

    assert first.snapshot_id == second.snapshot_id
    assert first.observed_at != second.observed_at
