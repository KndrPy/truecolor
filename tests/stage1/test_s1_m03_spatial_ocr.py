from __future__ import annotations

from pathlib import Path

import pytest

from analysis.stage1.m03_spatial_ocr import (
    SpatialOcrPolicy,
    SpatialOcrReconstructor,
    Toolchain,
    _tsv_rows,
)


def test_tsv_requires_complete_schema() -> None:
    with pytest.raises(Exception, match="TSV schema is incomplete"):
        _tsv_rows("level\ttext\n5\tword\n")


def test_tsv_preserves_surface_confidence_and_coordinates() -> None:
    payload = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t2\t3\t4\t5\t10\t20\t30\t40\t91.25\t±0.04*\n"
    )
    rows = _tsv_rows(payload)
    assert rows == [{
        "block_num": 2,
        "paragraph_num": 3,
        "line_num": 4,
        "word_num": 5,
        "left": 10,
        "top": 20,
        "width": 30,
        "height": 40,
        "confidence": 91.25,
        "text": "±0.04*",
    }]


def test_materialization_binds_every_word_to_rendered_evidence_plane() -> None:
    parser = SpatialOcrReconstructor(
        policy=SpatialOcrPolicy(),
        toolchain=Toolchain("pdftoppm", "pdfinfo", "tesseract"),
    )
    render = {
        "width_px": 1200,
        "height_px": 1600,
        "sha256": "a" * 64,
    }
    rows = [
        {
            "block_num": 1,
            "paragraph_num": 1,
            "line_num": 1,
            "word_num": 1,
            "left": 120,
            "top": 160,
            "width": 240,
            "height": 80,
            "confidence": 88.0,
            "text": "Ground",
        },
        {
            "block_num": 1,
            "paragraph_num": 1,
            "line_num": 1,
            "word_num": 2,
            "left": 380,
            "top": 160,
            "width": 160,
            "height": 80,
            "confidence": 92.0,
            "text": "truth",
        },
    ]
    words, lines, blocks = parser._materialize_page(
        "b" * 64,
        "FILE-1",
        1,
        612.0,
        792.0,
        render,
        rows,
        "OCR_200_DPI_PSM_3_TSV",
    )
    assert len(words) == 2
    assert len(lines) == 1
    assert len(blocks) == 1
    assert lines[0]["raw_text"] == "Ground truth"
    assert blocks[0]["raw_text"] == "Ground truth"
    for word in words:
        assert word["evidence_anchor"]["plane"] == "RENDERED_SOURCE_PAGE"
        assert word["page_image_sha256"] == "a" * 64
        assert word["source_pdf_sha256"] == "b" * 64
        assert len(word["raster_bbox_px"]) == 4
        assert len(word["normalized_bbox"]) == 4
        assert len(word["pdf_bbox_points"]) == 4


def test_spatial_model_does_not_claim_hidden_pdf_reconstruction() -> None:
    source = Path("analysis/stage1/m03_spatial_ocr.py").read_text(encoding="utf-8")
    assert "IMMUTABLE_RENDER_EVIDENCE_PLANE_WITH_OCR_OVERLAY" in source
    assert "SOURCE_PDF -> DETERMINISTIC_PAGE_RENDER" in source
    assert "source_mutated\": False" in source
