from __future__ import annotations

import json
from pathlib import Path

from analysis.prior_art.mutable_corpus import ExtractedDocument
from analysis.prior_art.mutable_corpus_consumer import run_consumer_reconciliation
from analysis.prior_art.mutable_corpus_enterprise import EnterpriseCorpusPolicy


class FakeBackend:
    def __init__(self, documents: dict[str, ExtractedDocument]) -> None:
        self.documents = documents

    def extract(self, path: Path) -> ExtractedDocument:
        return self.documents[path.name]


def write_pdf(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\n" + payload)


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_consumer_entrypoint_closes_only_after_all_semantic_gates_pass(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "researcher-name.pdf", b"consumer")
    text = (
        "Consumer Grade Corpus Identity\n"
        "Ada Researcher and Bruno Scientist\n"
        "Journal of Durable Science 2026, Volume 12(2), pp. 101-119\n"
        "https://doi.org/10.1000/consumer.1?utm_source=test\n\n"
        "Abstract\n"
        + "A durable study with repeatable methods and measurements. " * 30
        + "\n\nIntroduction\n"
        + "Scientific background and motivation. " * 20
        + "\n\nMethods\n"
        + "Controlled methods and validation. " * 20
        + "\n\nResults\n"
        + "Measured results and uncertainty. " * 20
        + "\n\nReferences\n"
    )
    backend = FakeBackend(
        {
            "researcher-name.pdf": ExtractedDocument(
                text=text,
                metadata={
                    "Title": "Consumer Grade Corpus Identity",
                    "Subject": "Journal of Durable Science",
                    "Pages": "19",
                },
                page_count=19,
                extraction_backend="fake",
            )
        }
    )
    result = run_consumer_reconciliation(
        corpus,
        output,
        EnterpriseCorpusPolicy(),
        {
            "records": [
                {
                    "source_id": "SOURCE-1",
                    "title": "Consumer Grade Corpus Identity",
                    "doi": "10.1000/consumer.1",
                    "required": True,
                    "claims": ["CLAIM-1"],
                }
            ]
        },
        None,
        "2026-07-15T00:00:00Z",
        backend=backend,
    )
    assert result["capability_state"] == "CLOSED"
    assert set(result["semantic_gates"].values()) == {"PASS"}
    closure = load(output / "MUTABLE_CORPUS_RECONCILIATION_CLOSED.json")
    assert closure["capability_state"] == "CLOSED"
    bindings = load(output / "physical_file_version_registry.json")["records"]
    assert bindings[0]["version_id"]
    assert bindings[0]["work_id"]
    locator = load(output / "bibliographic_locator_registry.json")["records"][0]
    assert locator["bibliographic_page_range"] == "101-119"
    assert "https://doi.org/10.1000/consumer.1" in locator["publisher_urls"]
    work_states = load(output / "work_identity_state_registry.json")["records"]
    assert work_states[0]["identity_state"] == "UNIQUE_WORK"
    coverage = load(output / "claim_source_coverage_report.json")["records"]
    assert coverage[0]["claim_id"] == "CLAIM-1"
    assert coverage[0]["coverage_state"] == "COMPLETE"
    authority = load(output / "scientific_authority_boundary.json")
    assert authority["rules"]["silent_download"] == "PROHIBITED"
    assert authority["records"][0]["scientifically_authoritative_file_id"] == ""


def test_closure_marker_is_removed_before_a_new_run(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "output"
    write_pdf(corpus / "paper.pdf", b"first")
    document = ExtractedDocument(
        text=(
            "Stable Consumer Paper\nAda Researcher and Bruno Scientist\n"
            "https://doi.org/10.1000/stable.1\n\nAbstract\n"
            + "Stable scientific evidence. " * 50
            + "\n\nMethods\n"
            + "Repeatable methods. " * 20
            + "\n\nResults\n"
            + "Repeatable results. " * 20
            + "\n\nReferences\n"
        ),
        metadata={"Title": "Stable Consumer Paper", "Pages": "8"},
        page_count=8,
        extraction_backend="fake",
    )
    backend = FakeBackend({"paper.pdf": document})
    run_consumer_reconciliation(
        corpus,
        output,
        EnterpriseCorpusPolicy(),
        None,
        None,
        "2026-07-15T00:00:00Z",
        backend=backend,
    )
    first = load(output / "MUTABLE_CORPUS_RECONCILIATION_CLOSED.json")
    run_consumer_reconciliation(
        corpus,
        output,
        EnterpriseCorpusPolicy(),
        None,
        None,
        "2026-07-15T01:00:00Z",
        backend=backend,
    )
    second = load(output / "MUTABLE_CORPUS_RECONCILIATION_CLOSED.json")
    assert first["run_id"] != second["run_id"]
    assert second["capability_state"] == "CLOSED"
