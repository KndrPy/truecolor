from __future__ import annotations

from pathlib import Path

from analysis.stage1.m10_corpus_ontology_alignment import signature
from analysis.stage1.m17_stage1_closure import Stage1ClosureAuthority
from analysis.stage1.stage1_runtime_contracts import atomic_jsonl, load_jsonl, stable_id


def test_signature_preserves_material_tokens() -> None:
    assert signature("The Hyperspectral Imaging Method") == ("hyperspectral", "imaging")


def test_stable_id_is_deterministic() -> None:
    assert stable_id("X", {"b": 2, "a": 1}) == stable_id("X", {"a": 1, "b": 2})


def test_jsonl_round_trip_unicode_line_separator(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    atomic_jsonl(path, [{"id": "1", "text": "alpha\u2028beta"}])
    assert load_jsonl(path) == [{"id": "1", "text": "alpha\u2028beta"}]


def test_m17_is_only_stage_closed_writer() -> None:
    source = Path("analysis/stage1/m17_stage1_closure.py").read_text(encoding="utf-8")
    assert '"STAGE_01_CLOSED.json"' in source
    for path in Path("analysis/stage1").glob("m*.py"):
        if path.name == "m17_stage1_closure.py":
            continue
        assert "STAGE_01_CLOSED.json" not in path.read_text(encoding="utf-8")


def test_review_modules_do_not_fabricate_dispositions() -> None:
    for name in ("m13_primary_review.py", "m14_independent_review.py", "m15_review_conflict_resolution.py"):
        source = Path("analysis/stage1") / name
        text = source.read_text(encoding="utf-8")
        assert '"disposition": None' in text or '"resolved_disposition": left if state == "AGREEMENT" else None' in text
