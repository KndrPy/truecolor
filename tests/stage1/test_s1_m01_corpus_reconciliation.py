from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.prior_art.mutable_corpus import ExtractedDocument
from analysis.prior_art.mutable_corpus_enterprise import EnterpriseCorpusError, EnterpriseCorpusPolicy
from analysis.stage1.m01_corpus_reconciliation import (
    M01ClosureError,
    M01ResourceBudget,
    run_m01,
)


class FakeBackend:
    def __init__(self, documents: dict[str, ExtractedDocument]) -> None:
        self.documents = documents

    def extract(self, path: Path) -> ExtractedDocument:
        value = self.documents[path.name]
        if isinstance(value, Exception):
            raise value
        return value


def write_pdf(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\n" + payload)


def scientific_document(
    title: str,
    *,
    doi: str = "",
    arxiv: str = "",
    body_seed: str = "controlled scientific evidence",
) -> ExtractedDocument:
    identifiers = []
    if doi:
        identifiers.append(f"https://doi.org/{doi}")
    if arxiv:
        identifiers.append(f"arXiv:{arxiv}")
    body = (body_seed + " methods measurements validation results. ") * 40
    text = (
        f"{title}\n"
        "Ada Researcher and Bruno Scientist\n"
        "Journal of Reproducible Science 2026\n"
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
        metadata={"Title": title, "Subject": "Journal of Reproducible Science", "Pages": "8"},
        page_count=8,
        extraction_backend="fake",
        extraction_errors=(),
    )


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_unit_resource_budget_rejects_unknown_and_nonpositive_values() -> None:
    with pytest.raises(ValueError, match="unknown M01 resource budget fields"):
        M01ResourceBudget.from_mapping({"fake_success": True})
    with pytest.raises(ValueError, match="maximum_wall_seconds must be positive"):
        M01ResourceBudget.from_mapping({"maximum_wall_seconds": 0})
    with pytest.raises(ValueError, match="byte budgets must be positive"):
        M01ResourceBudget.from_mapping({"maximum_output_bytes": 0})


def test_functional_single_work_emits_real_module_closure(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "arbitrary-source-name.pdf", b"source")
    report = run_m01(
        corpus,
        output,
        backend=FakeBackend(
            {
                "arbitrary-source-name.pdf": scientific_document(
                    "A Lossless Scientific Corpus", doi="10.1000/m01.1"
                )
            }
        ),
        observed_at="2026-07-15T00:00:00Z",
    )
    assert report["module_id"] == "S1-M01"
    assert report["module_state"] == "CLOSED"
    assert report["stage1_state"] == "OPEN"
    assert report["stage1_closure_authority"] == "S1-M17_ONLY"
    closure = load(output / "stage1" / "m01" / "S1_M01_CLOSED.json")
    assert closure == report
    trace_lines = (output / "stage1" / "m01" / "construction_trace.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(trace_lines) == 1
    trace = json.loads(trace_lines[0])
    assert trace["input"]["source_file_count"] == 1
    assert trace["output_artifacts"]
    assert not (output / "STAGE_01_CLOSED.json").exists()


def test_integration_expected_source_and_dependency_inputs_propagate(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "present.pdf", b"present")
    report = run_m01(
        corpus,
        output,
        backend=FakeBackend(
            {"present.pdf": scientific_document("Present Work", doi="10.1000/present")}
        ),
        expected_sources={
            "records": [
                {
                    "source_id": "EXPECTED-1",
                    "title": "Missing Work",
                    "doi": "10.1000/missing",
                    "required": True,
                    "claims": ["TC-NOV-001"],
                }
            ]
        },
        dependency_manifest={
            "artifacts": [
                {
                    "artifact_id": "DOWNSTREAM-1",
                    "source_file_ids": ["FILE-does-not-exist"],
                }
            ]
        },
        observed_at="2026-07-15T00:00:00Z",
    )
    assert report["module_state"] == "CLOSED"
    missing = load(output / "missing_reference_candidates.json")["records"]
    assert any(record.get("doi") == "10.1000/missing" for record in missing)
    projection = load(output / "stage1_review_queue_projection.json")
    assert projection["task_count"] == 1


def test_chaos_invalid_pdf_signature_fails_without_module_closure(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    corpus.mkdir()
    (corpus / "hostile.pdf").write_bytes(b"not-a-pdf")
    with pytest.raises(EnterpriseCorpusError, match="preflight rejected"):
        run_m01(
            corpus,
            output,
            backend=FakeBackend({}),
            observed_at="2026-07-15T00:00:00Z",
        )
    assert not (output / "stage1" / "m01" / "S1_M01_CLOSED.json").exists()
    preflight = load(output / "corpus_preflight_report.json")
    assert "INVALID_PDF_SIGNATURE" in preflight["records"][0]["reasons"]


def test_chaos_resource_budget_excess_fails_closed(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "source.pdf", b"source")
    with pytest.raises(M01ClosureError, match="resource budget exceeded"):
        run_m01(
            corpus,
            output,
            backend=FakeBackend(
                {"source.pdf": scientific_document("Budget Source", doi="10.1000/budget")}
            ),
            observed_at="2026-07-15T00:00:00Z",
            resource_budget=M01ResourceBudget(maximum_output_bytes=1),
        )
    assert not (output / "stage1" / "m01" / "S1_M01_CLOSED.json").exists()


def test_performance_bounded_multi_document_execution(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    documents: dict[str, ExtractedDocument] = {}
    for index in range(40):
        name = f"research-source-{index:03d}.pdf"
        write_pdf(corpus / name, f"payload-{index}".encode("utf-8"))
        documents[name] = scientific_document(
            f"Scientific Work {index}",
            doi=f"10.1000/performance.{index}",
            body_seed=f"independent evidence family {index}",
        )
    report = run_m01(
        corpus,
        output,
        backend=FakeBackend(documents),
        observed_at="2026-07-15T00:00:00Z",
        resource_budget=M01ResourceBudget(
            maximum_wall_seconds=30.0,
            maximum_peak_rss_bytes=2 * 1024 * 1024 * 1024,
            maximum_output_bytes=256 * 1024 * 1024,
        ),
    )
    metrics = report["metrics"]
    assert metrics["source_file_count"] == 40
    assert metrics["wall_seconds"] <= 30.0
    assert metrics["output_bytes"] <= 256 * 1024 * 1024


def test_interaction_add_rename_replace_remove_preserves_history(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    first = corpus / "initial-name.pdf"
    write_pdf(first, b"v1")
    first_doc = scientific_document("Mutable Work", doi="10.1000/mutable")
    run_m01(
        corpus,
        output,
        backend=FakeBackend({"initial-name.pdf": first_doc}),
        observed_at="2026-07-15T00:00:00Z",
    )

    renamed = corpus / "renamed-by-researcher.pdf"
    first.rename(renamed)
    run_m01(
        corpus,
        output,
        backend=FakeBackend({"renamed-by-researcher.pdf": first_doc}),
        observed_at="2026-07-15T01:00:00Z",
    )

    write_pdf(renamed, b"v2")
    second_doc = scientific_document(
        "Mutable Work Revised", doi="10.1000/mutable", body_seed="revised methods"
    )
    run_m01(
        corpus,
        output,
        backend=FakeBackend({"renamed-by-researcher.pdf": second_doc}),
        observed_at="2026-07-15T02:00:00Z",
    )

    renamed.unlink()
    run_m01(
        corpus,
        output,
        backend=FakeBackend({}),
        observed_at="2026-07-15T03:00:00Z",
    )
    lifecycle = load(output / "physical_file_lifecycle_registry.json")["records"]
    assert any(record["current_state"] == "REMOVED" for record in lifecycle)
    event_lines = (output / "history" / "corpus_event_ledger.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    events = [json.loads(line)["event_type"] for line in event_lines]
    assert "FILE_ADDED" in events
    assert "FILE_REMOVED" in events


def test_end_to_end_repeated_execution_is_idempotent_for_unchanged_corpus(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "stable.pdf", b"stable")
    backend = FakeBackend(
        {"stable.pdf": scientific_document("Stable Scientific Work", doi="10.1000/stable")}
    )
    first = run_m01(
        corpus,
        output,
        backend=backend,
        observed_at="2026-07-15T00:00:00Z",
    )
    first_snapshot = load(output / "corpus_snapshot.json")
    second = run_m01(
        corpus,
        output,
        backend=backend,
        observed_at="2026-07-15T00:00:00Z",
    )
    second_snapshot = load(output / "corpus_snapshot.json")
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first_snapshot == second_snapshot
    assert second["module_state"] == "CLOSED"
    assert not (output / "STAGE_01_CLOSED.json").exists()
