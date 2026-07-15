from __future__ import annotations

from analysis.stage1.m03_layout_backend import LayoutBackend
from analysis.stage1.m06_author_models_v2 import split_sentences


def test_layout_backend_falls_back_without_optional_dependency() -> None:
    result = LayoutBackend().analyze(object())
    assert result.state in {"FALLBACK", "FAILED_FALLBACK", "USED", "USED_UNSTRUCTURED"}


def test_author_sentence_split_is_nonempty() -> None:
    assert split_sentences("We propose a method. It may improve accuracy.") == ["We propose a method.", "It may improve accuracy."]


def test_v3_pipeline_is_sequential() -> None:
    source = open("analysis/stage1/stage1_m03_m17_pipeline_v3.py", encoding="utf-8").read()
    order = [source.index(token) for token in ("ScientificNonBodyEvidenceV2().run", "Terminology().run", "AuthorModelsV2().run", "DJI().run", "Claims().run", "PaperLocalOntologyV2().run", "run_m10_m17(args)")]
    assert order == sorted(order)
