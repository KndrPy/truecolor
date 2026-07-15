from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.stage1.m03_hybrid_reconstruction import (
    HybridReconstructionPolicy,
    _bbox_union,
    _tsv_words,
    classify_page,
)


def test_native_page_routes_without_ocr() -> None:
    policy = HybridReconstructionPolicy(
        native_min_non_whitespace_chars=80,
        native_min_text_blocks=1,
    )
    assert classify_page(800, 4, policy) == "NATIVE_LAYOUT"


def test_empty_page_routes_to_spatial_ocr() -> None:
    policy = HybridReconstructionPolicy()
    assert classify_page(0, 0, policy) == "SPATIAL_OCR"


def test_partial_native_page_preserves_both_layers() -> None:
    policy = HybridReconstructionPolicy(
        native_min_non_whitespace_chars=80,
        native_min_text_blocks=1,
    )
    assert classify_page(12, 1, policy) == "NATIVE_PLUS_OCR_EVIDENCE_LAYERS"


def test_tsv_parser_rejects_missing_coordinate_contract() -> None:
    with pytest.raises(Exception, match="TSV schema is incomplete"):
        _tsv_words("level\ttext\n5\tword\n")


def test_tsv_parser_preserves_surface_coordinates_and_confidence() -> None:
    payload = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t2\t1\t3\t4\t10\t20\t30\t40\t91.5\tDOI\n"
    )
    words = _tsv_words(payload)
    assert words == [
        {
            "block": 2,
            "paragraph": 1,
            "line": 3,
            "word": 4,
            "left": 10,
            "top": 20,
            "width": 30,
            "height": 40,
            "confidence": 91.5,
            "text": "DOI",
        }
    ]


def test_bbox_union_is_total_and_non_destructive() -> None:
    assert _bbox_union([[10, 20, 30, 40], [5, 25, 50, 35]]) == [5.0, 20.0, 50.0, 40.0]
    assert _bbox_union([]) == [0.0, 0.0, 0.0, 0.0]


def test_hybrid_contract_forbids_semantic_overwrite() -> None:
    source = Path("analysis/stage1/m03_hybrid_reconstruction.py").read_text(encoding="utf-8")
    assert "PRESERVE_LAYERS_NO_SEMANTIC_OVERWRITE" in source
    assert "OCR never overwrites native content" in source
    assert '"evidence_layer": "NATIVE_PDF_OBJECT_MODEL"' in source
    assert '"evidence_layer": "RENDERED_SOURCE_PAGE_OCR_OVERLAY"' in source


def test_v2_pipeline_uses_hybrid_reconstructor() -> None:
    source = Path("analysis/stage1/m03_m09_evidence_pipeline_v2.py").read_text(encoding="utf-8")
    assert "HybridSpatialReconstructor().reconstruct" in source
    assert "SpatialReconstruction().run" not in source
    assert "HYBRID_NATIVE_AND_SELECTIVE_SPATIAL_OCR" in source


def test_mixed_page_falsification_gate_is_present() -> None:
    source = Path("analysis/stage1/m03_hybrid_reconstruction.py").read_text(encoding="utf-8")
    assert "mixed page did not preserve both evidence layers" in source
    assert "page representation is not total" in source
    assert "element coordinate or source lineage is incomplete" in source
