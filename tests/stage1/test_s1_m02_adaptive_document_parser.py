from __future__ import annotations

import json
from pathlib import Path

from analysis.stage1.m02_adaptive_document_parser import (
    AdaptiveDocumentParser,
    CommandRunner,
    ParserPolicy,
    TextQuality,
    Toolchain,
    evaluate_text,
)


class FakeParser(AdaptiveDocumentParser):
    def __init__(self, scenarios: dict[int, tuple[str, str, str, str]]) -> None:
        super().__init__(
            policy=ParserPolicy(native_min_chars_per_page=20, lexical_token_minimum=4),
            toolchain=Toolchain("pdfinfo", "pdftotext", "pdftoppm", "tesseract", None),
            runner=CommandRunner(),
        )
        self.scenarios = scenarios

    def _page_count(self, source: Path) -> int:
        return len(self.scenarios)

    def _native_page(self, source: Path, page: int):
        return self.scenarios[page][0], {"strategy": "NATIVE_LAYOUT", "returncode": 0, "stderr": "", "elapsed_seconds": 0.0}

    def _alternate_page(self, source: Path, page: int):
        return self.scenarios[page][1], {"strategy": "ALTERNATE_NATIVE_PYMUPDF", "returncode": 0, "stderr": "", "elapsed_seconds": 0.0}

    def _ocr_page(self, source: Path, page: int, dpi: int, psm: int):
        index = 2 if dpi == self.policy.initial_ocr_dpi else 3
        return self.scenarios[page][index], {
            "strategy": f"OCR_{dpi}_DPI_PSM_{psm}",
            "returncode": 0,
            "stderr": "",
            "elapsed_seconds": 0.0,
        }


def _pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.7\nsynthetic")
    return path


def test_quality_rejects_empty_and_accepts_readable_text() -> None:
    policy = ParserPolicy(native_min_chars_per_page=20, lexical_token_minimum=4)
    assert not evaluate_text("\n\n", policy).usable
    result = evaluate_text("This page contains enough readable scientific text for parsing.", policy)
    assert result.usable
    assert result.printable_ratio == 1.0


def test_native_success_stops_fallback(tmp_path: Path) -> None:
    parser = FakeParser({1: ("Native scientific text with enough words for success.", "", "", "")})
    result = parser.parse(_pdf(tmp_path / "source.pdf"), tmp_path / "out")
    assert result["document_state"] == "RECOVERED_NATIVE"
    assert result["pages"][0]["strategy"] == "NATIVE_LAYOUT"
    assert len(result["pages"][0]["attempts"]) == 1


def test_alternate_parser_used_only_after_native_failure(tmp_path: Path) -> None:
    parser = FakeParser({1: ("", "Alternate parser recovers enough useful scientific text.", "", "")})
    result = parser.parse(_pdf(tmp_path / "source.pdf"), tmp_path / "out")
    assert result["document_state"] == "RECOVERED_ALTERNATE"
    assert result["pages"][0]["strategy"] == "ALTERNATE_NATIVE_PYMUPDF"
    assert len(result["pages"][0]["attempts"]) == 2


def test_ocr_used_only_after_both_native_paths_fail(tmp_path: Path) -> None:
    parser = FakeParser({1: ("", "", "OCR recovers enough readable scientific page content.", "")})
    result = parser.parse(_pdf(tmp_path / "source.pdf"), tmp_path / "out")
    assert result["document_state"] == "RECOVERED_OCR"
    assert result["pages"][0]["strategy"].startswith("OCR_200_DPI")
    assert len(result["pages"][0]["attempts"]) == 3


def test_enhanced_retry_is_bounded_and_unresolved_is_explicit(tmp_path: Path) -> None:
    parser = FakeParser({1: ("", "", "", "")})
    result = parser.parse(_pdf(tmp_path / "source.pdf"), tmp_path / "out")
    assert result["document_state"] == "UNRESOLVED"
    assert result["unresolved_pages"] == [1]
    assert len(result["pages"][0]["attempts"]) == 4


def test_mixed_document_uses_page_level_routing(tmp_path: Path) -> None:
    parser = FakeParser(
        {
            1: ("Native page has enough scientific text for direct use.", "", "", ""),
            2: ("", "", "OCR page has enough scientific text after rendering.", ""),
        }
    )
    result = parser.parse(_pdf(tmp_path / "source.pdf"), tmp_path / "out")
    assert result["document_state"] == "RECOVERED_HYBRID"
    assert [page["state"] for page in result["pages"]] == ["RECOVERED_NATIVE", "RECOVERED_OCR"]


def test_unchanged_source_uses_cache(tmp_path: Path) -> None:
    parser = FakeParser({1: ("Native scientific text with enough words for success.", "", "", "")})
    source = _pdf(tmp_path / "source.pdf")
    first = parser.parse(source, tmp_path / "out")
    second = parser.parse(source, tmp_path / "out")
    assert first["cache_state"] == "MISS"
    assert second["cache_state"] == "HIT"


def test_source_bytes_are_never_modified(tmp_path: Path) -> None:
    parser = FakeParser({1: ("", "", "OCR recovers enough readable scientific page content.", "")})
    source = _pdf(tmp_path / "source.pdf")
    before = source.read_bytes()
    parser.parse(source, tmp_path / "out")
    assert source.read_bytes() == before


def test_manifest_records_attempt_lineage(tmp_path: Path) -> None:
    parser = FakeParser({1: ("", "", "OCR recovers enough readable scientific page content.", "")})
    source = _pdf(tmp_path / "source.pdf")
    result = parser.parse(source, tmp_path / "out")
    manifest = json.loads(
        (tmp_path / "out" / result["source_sha256"] / "m02_parse_manifest.json").read_text()
    )
    assert manifest["source_sha256"] == result["source_sha256"]
    assert manifest["output_text_sha256"]
    assert [attempt["strategy"] for attempt in manifest["pages"][0]["attempts"]] == [
        "NATIVE_LAYOUT",
        "ALTERNATE_NATIVE_PYMUPDF",
        "OCR_200_DPI_PSM_3",
    ]
