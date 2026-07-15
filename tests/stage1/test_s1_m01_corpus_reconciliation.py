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
from analysis.stage1.m01_validator import M01ValidationError, validate_m01_artifacts


class FakeBackend:
    def __init__(self, documents: dict[str, ExtractedDocument | Exception]) -> None:
        self.documents = documents

    def extract(self, path: Path) -> ExtractedDocument:
        value = self.documents[path.name]
        if isinstance(value, Exception):
            raise value
        return value


def write_pdf(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\n" + payload)


def document(
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


def test_resource_budget_contract_rejects_unknown_and_nonpositive_values() -> None:
    with pytest.raises(ValueError, match="unknown M01 resource budget fields"):
        M01ResourceBudget.from_mapping({"fake_success": True})
    with pytest.raises(ValueError, match="maximum_wall_seconds must be positive"):
        M01ResourceBudget.from_mapping({"maximum_wall_seconds": 0})
    with pytest.raises(ValueError, match="byte budgets must be positive"):
        M01ResourceBudget.from_mapping({"maximum_run_output_bytes": 0})


def test_functional_closure_is_real_and_stage1_remains_open(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "arbitrary-source-name.pdf", b"source")
    report = run_m01(
        corpus,
        output,
        backend=FakeBackend(
            {"arbitrary-source-name.pdf": document("A Lossless Scientific Corpus", doi="10.1000/m01.1")}
        ),
        observed_at="2026-07-15T00:00:00Z",
    )
    assert report["module_state"] == "CLOSED"
    assert report["stage1_state"] == "OPEN"
    assert report["stage1_closure_authority"] == "S1-M17_ONLY"
    assert report["metrics"]["accepted_source_file_count"] == 1
    assert all(value == "PASS" for value in report["semantic_gates"].values())
    assert (output / "stage1" / "m01" / "m01_artifact_hashes.json").is_file()
    assert not (output / "STAGE_01_CLOSED.json").exists()


def test_exact_duplicate_bytes_keep_distinct_physical_identities(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "alpha.pdf", b"same")
    write_pdf(corpus / "beta.pdf", b"same")
    shared = document("Duplicate Scientific Work", doi="10.1000/duplicate")
    run_m01(
        corpus,
        output,
        backend=FakeBackend({"alpha.pdf": shared, "beta.pdf": shared}),
        observed_at="2026-07-15T00:00:00Z",
    )
    physical = load(output / "physical_file_registry.json")["records"]
    assert len(physical) == 2
    assert len({item["file_id"] for item in physical}) == 2
    duplicates = load(output / "exact_duplicate_report.json")["records"]
    assert len(duplicates) == 1


def test_conflicting_doi_is_explicit_and_never_silently_merged(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "left.pdf", b"left")
    write_pdf(corpus / "right.pdf", b"right")
    run_m01(
        corpus,
        output,
        backend=FakeBackend(
            {
                "left.pdf": document("Convergent Scientific Title", doi="10.1000/left", body_seed="same evidence"),
                "right.pdf": document("Convergent Scientific Title", doi="10.1000/right", body_seed="same evidence"),
            }
        ),
        observed_at="2026-07-15T00:00:00Z",
    )
    issues = load(output / "ambiguous_identity_queue.json")["records"]
    assert issues
    assert any("CONFLICTING_PRIMARY_DOI" in reason for item in issues for reason in item["reasons"])


def test_explicit_prior_snapshot_drives_history_without_overriding_live_directory(
    tmp_path: Path,
) -> None:
    first_corpus = tmp_path / "first"
    first_output = tmp_path / "first-output"
    write_pdf(first_corpus / "old.pdf", b"old")
    run_m01(
        first_corpus,
        first_output,
        backend=FakeBackend({"old.pdf": document("Old Work", doi="10.1000/old")}),
        observed_at="2026-07-15T00:00:00Z",
    )
    prior = first_output / "corpus_snapshot.json"

    current_corpus = tmp_path / "current"
    current_output = tmp_path / "current-output"
    write_pdf(current_corpus / "new.pdf", b"new")
    report = run_m01(
        current_corpus,
        current_output,
        backend=FakeBackend({"new.pdf": document("New Work", doi="10.1000/new")}),
        prior_snapshot_path=prior,
        observed_at="2026-07-15T01:00:00Z",
    )
    physical = load(current_output / "physical_file_registry.json")["records"]
    assert [item["relative_path"] for item in physical] == ["new.pdf"]
    events = load(current_output / "corpus_change_set.json")["events"]
    assert {item["event_type"] for item in events} >= {"FILE_ADDED", "FILE_REMOVED"}
    assert report["prior_snapshot"]["snapshot_id"]


def test_invalid_prior_snapshot_fails_before_reconciliation(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    prior = tmp_path / "prior.json"
    write_pdf(corpus / "source.pdf", b"source")
    prior.write_text('{"schema":"wrong","snapshot_id":"x","files":[],"works":[]}', encoding="utf-8")
    with pytest.raises(M01ValidationError, match="unsupported schema"):
        run_m01(
            corpus,
            output,
            backend=FakeBackend({"source.pdf": document("Source")}),
            prior_snapshot_path=prior,
        )
    assert not (output / "stage1" / "m01" / "S1_M01_CLOSED.json").exists()


def test_invalid_pdf_signature_fails_closed(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    corpus.mkdir()
    (corpus / "hostile.pdf").write_bytes(b"not-a-pdf")
    with pytest.raises(EnterpriseCorpusError, match="preflight rejected"):
        run_m01(corpus, output, backend=FakeBackend({}))
    assert not (output / "stage1" / "m01" / "S1_M01_CLOSED.json").exists()


def test_symlink_is_rejected_by_default(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    target = tmp_path / "outside.pdf"
    write_pdf(target, b"outside")
    corpus.mkdir()
    (corpus / "linked.pdf").symlink_to(target)
    with pytest.raises(EnterpriseCorpusError, match="preflight rejected"):
        run_m01(corpus, output, backend=FakeBackend({}))
    reasons = load(output / "corpus_preflight_report.json")["records"][0]["reasons"]
    assert "SYMBOLIC_LINK_NOT_ALLOWED" in reasons
    assert "PATH_ESCAPES_CORPUS_ROOT" in reasons


def test_file_count_limit_fails_without_closure(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "one.pdf", b"1")
    write_pdf(corpus / "two.pdf", b"2")
    with pytest.raises(EnterpriseCorpusError, match="maximum_files_per_run"):
        run_m01(
            corpus,
            output,
            policy=EnterpriseCorpusPolicy(maximum_files_per_run=1),
            backend=FakeBackend({}),
        )
    assert not (output / "stage1" / "m01" / "S1_M01_CLOSED.json").exists()


def test_budget_excess_removes_module_closure(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "source.pdf", b"source")
    with pytest.raises(M01ClosureError, match="resource budget exceeded"):
        run_m01(
            corpus,
            output,
            backend=FakeBackend({"source.pdf": document("Budget Source")}),
            resource_budget=M01ResourceBudget(maximum_run_output_bytes=1),
        )
    assert not (output / "stage1" / "m01" / "S1_M01_CLOSED.json").exists()


def test_tampered_projection_is_detected(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "source.pdf", b"source")
    run_m01(
        corpus,
        output,
        backend=FakeBackend({"source.pdf": document("Tamper Source")}),
    )
    path = output / "physical_file_registry.json"
    value = load(path)
    value["records"] = []
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(M01ValidationError):
        validate_m01_artifacts(output)


def test_history_trace_appends_and_unchanged_snapshot_is_idempotent(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "stable.pdf", b"stable")
    backend = FakeBackend({"stable.pdf": document("Stable Work", doi="10.1000/stable")})
    first = run_m01(corpus, output, backend=backend, observed_at="2026-07-15T00:00:00Z")
    second = run_m01(corpus, output, backend=backend, observed_at="2026-07-15T00:00:00Z")
    assert first["snapshot_id"] == second["snapshot_id"]
    lines = (output / "stage1" / "m01" / "construction_trace.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines) == 2


def test_performance_bounded_multi_document_execution(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    docs: dict[str, ExtractedDocument | Exception] = {}
    for index in range(40):
        name = f"source-{index:03d}.pdf"
        write_pdf(corpus / name, f"payload-{index}".encode())
        docs[name] = document(f"Scientific Work {index}", doi=f"10.1000/perf.{index}")
    report = run_m01(
        corpus,
        output,
        backend=FakeBackend(docs),
        resource_budget=M01ResourceBudget(
            maximum_wall_seconds=30.0,
            maximum_peak_rss_bytes=2 * 1024 * 1024 * 1024,
            maximum_run_output_bytes=256 * 1024 * 1024,
        ),
    )
    assert report["metrics"]["accepted_source_file_count"] == 40
    assert report["metrics"]["wall_seconds"] <= 30.0
    assert report["metrics"]["run_output_bytes"] <= 256 * 1024 * 1024
