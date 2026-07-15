from __future__ import annotations

import json
from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")
pytest.importorskip("pyarrow")

from analysis.stage1.m02_source_preflight import SourcePreflight
from analysis.stage1.m03_m09_evidence_pipeline import (
    AuthorModels,
    Claims,
    DJI,
    LocalOntology,
    NonBodyEvidence,
    SpatialReconstruction,
    Terminology,
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def build_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Methods", fontsize=16)
    page.insert_text(
        (72, 110),
        "We measured 29 participants and computed reflectance from 400 to 720 nm.\n"
        "The proposed method may improve spectral reconstruction accuracy.",
        fontsize=10,
    )
    page.insert_text((72, 180), "Results and Discussion", fontsize=16)
    page.insert_text(
        (72, 215),
        "The method achieved 0.82 ± 0.04 accuracy under controlled lighting.",
        fontsize=10,
    )
    document.save(path)
    document.close()


def registries(root: Path, pdf: Path) -> tuple[Path, Path]:
    physical = root / "physical.json"
    versions = root / "versions.json"
    write_json(
        physical,
        {
            "records": [
                {
                    "file_id": "FILE-1",
                    "relative_path": pdf.name,
                    "binary_sha256": "",
                }
            ]
        },
    )
    write_json(
        versions,
        {
            "records": [
                {
                    "file_id": "FILE-1",
                    "version_id": "VERSION-1",
                    "work_id": "WORK-1",
                    "extracted_identifiers": {"dois": []},
                }
            ]
        },
    )
    return physical, versions


def test_m02_represents_every_file_and_page(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    pdf = corpus / "paper.pdf"
    build_pdf(pdf)
    physical, versions = registries(tmp_path, pdf)
    output = tmp_path / "m02"

    result = SourcePreflight().run(corpus, physical, versions, output)

    source = json.loads((output / "source_integrity_registry.json").read_text())
    pages = (output / "page_integrity_registry.jsonl").read_text().splitlines()
    assert result.module_state == "CLOSED"
    assert result.stage1_state == "OPEN"
    assert len(source["records"]) == 1
    assert source["records"][0]["page_count"] == 1
    assert len(pages) == 1


def test_m03_to_m09_emit_required_artifacts(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    pdf = corpus / "paper.pdf"
    build_pdf(pdf)
    physical, versions = registries(tmp_path, pdf)
    m02 = tmp_path / "m02"
    SourcePreflight().run(corpus, physical, versions, m02)

    m03 = tmp_path / "m03"
    SpatialReconstruction().run(
        corpus,
        m02 / "source_integrity_registry.json",
        m03,
    )
    assert (m03 / "document_elements.jsonl").is_file()
    assert (m03 / "reading_order_graph.json").is_file()

    m04 = tmp_path / "m04"
    NonBodyEvidence().run(
        corpus,
        m02 / "source_integrity_registry.json",
        m03,
        m04,
    )
    assert (m04 / "table_cells.parquet").is_file()

    m05 = tmp_path / "m05"
    Terminology().run(m03, m05)
    assert (m05 / "named_entity_registry.json").is_file()

    m06 = tmp_path / "m06"
    AuthorModels().run(m03, m06)
    assert (m06 / "author_problem_models.json").is_file()

    m07 = tmp_path / "m07"
    DJI().run(m03, m07)
    dag = json.loads((m07 / "dji_dependency_dag.json").read_text())
    assert isinstance(dag["edges"], list)

    m08 = tmp_path / "m08"
    Claims().run(m03, m08)
    assert (m08 / "quantitative_claim_registry.parquet").is_file()

    m09 = tmp_path / "m09"
    LocalOntology().run(m05, m06, m07, m09)
    assert (m09 / "author_local_ontology.json").is_file()
    assert (m09 / "paper_problem_paradigm.json").is_file()
    assert (m09 / "paper_solution_paradigm.json").is_file()


def test_m03_never_closes_unreadable_source_as_empty_valid(tmp_path: Path) -> None:
    source_integrity = tmp_path / "source_integrity_registry.json"
    write_json(
        source_integrity,
        {
            "records": [
                {
                    "file_id": "FILE-X",
                    "relative_path": "missing.pdf",
                    "state": "UNREADABLE",
                }
            ]
        },
    )
    output = tmp_path / "m03"
    SpatialReconstruction().run(tmp_path, source_integrity, output)
    unresolved = json.loads(
        (output / "unresolved_extraction_regions.json").read_text()
    )
    assert unresolved["records"][0]["reason"] == "UNREADABLE"
    assert unresolved["records"][0]["materiality"] == "FULL_DOCUMENT"
