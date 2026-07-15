from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from analysis.stage1.canonical_stage1_contracts import (
    ModuleResult,
    Stage1EvidenceError,
    atomic_write_json,
    atomic_write_jsonl,
    canonical_json,
    sha256_bytes,
    sha256_file,
    stable_id,
    write_closure,
)

MODULE_ID = "S1-M03-OCR"
POLICY_VERSION = 1


@dataclass(frozen=True)
class SpatialOcrPolicy:
    initial_dpi: int = 200
    retry_dpi: int = 300
    initial_psm: int = 3
    retry_psm: int = 6
    language: str = "eng"
    minimum_word_confidence: float = 35.0
    minimum_page_word_count: int = 8
    maximum_workers: int = 1
    command_timeout_seconds: int = 180
    retain_page_renders: bool = False
    retain_word_crops: bool = False


@dataclass(frozen=True)
class Toolchain:
    pdftoppm: str
    pdfinfo: str
    tesseract: str

    @classmethod
    def detect(cls) -> "Toolchain":
        tools = {name: shutil.which(name) for name in ("pdftoppm", "pdfinfo", "tesseract")}
        missing = sorted(name for name, value in tools.items() if not value)
        if missing:
            raise Stage1EvidenceError("required spatial OCR tools absent: " + ", ".join(missing))
        return cls(**{name: str(value) for name, value in tools.items()})


class CommandRunner:
    def run(self, command: Sequence[str], timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={
                **os.environ,
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
            },
        )


def _pdf_page_sizes(pdfinfo_output: str) -> tuple[int, dict[int, tuple[float, float]]]:
    page_count = 0
    default_size: tuple[float, float] | None = None
    for line in pdfinfo_output.splitlines():
        if line.lower().startswith("pages:"):
            page_count = int(line.split(":", 1)[1].strip())
        elif line.lower().startswith("page size:"):
            parts = line.split(":", 1)[1].strip().split()
            if len(parts) >= 3 and parts[1].lower() == "x":
                default_size = (float(parts[0]), float(parts[2]))
    if page_count <= 0:
        raise Stage1EvidenceError("pdfinfo did not report a positive page count")
    if default_size is None:
        default_size = (612.0, 792.0)
    return page_count, {page: default_size for page in range(1, page_count + 1)}


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        raise Stage1EvidenceError(f"render is not a valid PNG: {path}")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _safe_float(value: str, default: float = -1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _tsv_rows(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    rows: list[dict[str, Any]] = []
    required = {"level", "page_num", "block_num", "par_num", "line_num", "word_num", "left", "top", "width", "height", "conf", "text"}
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        raise Stage1EvidenceError("Tesseract TSV schema is incomplete")
    for raw in reader:
        if raw.get("level") != "5":
            continue
        surface = str(raw.get("text", ""))
        if not surface.strip():
            continue
        rows.append(
            {
                "block_num": int(raw["block_num"]),
                "paragraph_num": int(raw["par_num"]),
                "line_num": int(raw["line_num"]),
                "word_num": int(raw["word_num"]),
                "left": int(raw["left"]),
                "top": int(raw["top"]),
                "width": int(raw["width"]),
                "height": int(raw["height"]),
                "confidence": _safe_float(raw["conf"]),
                "text": surface,
            }
        )
    return rows


def _bbox_union(boxes: Iterable[Sequence[float]]) -> list[float]:
    values = [tuple(float(value) for value in box) for box in boxes]
    if not values:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        min(box[0] for box in values),
        min(box[1] for box in values),
        max(box[2] for box in values),
        max(box[3] for box in values),
    ]


class SpatialOcrReconstructor:
    """Create an evidentiary text overlay on an immutable rendered page plane.

    The output never pretends to recreate the source PDF's hidden structure. Each
    OCR token is anchored to: source PDF hash, page number, rendered-page hash,
    raster coordinates, normalized coordinates, and PDF-point coordinates.
    """

    def __init__(
        self,
        policy: SpatialOcrPolicy | None = None,
        toolchain: Toolchain | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self.policy = policy or SpatialOcrPolicy()
        self.toolchain = toolchain or Toolchain.detect()
        self.runner = runner or CommandRunner()

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return self.runner.run(command, self.policy.command_timeout_seconds)

    def _render_page(self, source: Path, page: int, dpi: int, destination: Path) -> Mapping[str, Any]:
        prefix = destination.with_suffix("")
        started = time.perf_counter()
        result = self._run(
            (
                self.toolchain.pdftoppm,
                "-f", str(page), "-l", str(page), "-singlefile",
                "-r", str(dpi), "-png", source.as_posix(), prefix.as_posix(),
            )
        )
        png = prefix.with_suffix(".png")
        if result.returncode != 0 or not png.is_file():
            raise Stage1EvidenceError(
                f"page render failed for page {page}: {result.stderr[-2000:]}"
            )
        width, height = _png_dimensions(png)
        return {
            "path": png,
            "width_px": width,
            "height_px": height,
            "sha256": sha256_file(png),
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "stderr": result.stderr[-2000:],
        }

    def _ocr_tsv(self, image: Path, dpi: int, psm: int) -> tuple[list[dict[str, Any]], Mapping[str, Any]]:
        started = time.perf_counter()
        result = self._run(
            (
                self.toolchain.tesseract,
                image.as_posix(), "stdout", "--dpi", str(dpi),
                "--psm", str(psm), "-l", self.policy.language, "tsv",
            )
        )
        if result.returncode != 0:
            return [], {
                "returncode": result.returncode,
                "stderr": result.stderr[-2000:],
                "elapsed_seconds": round(time.perf_counter() - started, 6),
            }
        return _tsv_rows(result.stdout), {
            "returncode": result.returncode,
            "stderr": result.stderr[-2000:],
            "elapsed_seconds": round(time.perf_counter() - started, 6),
        }

    def _materialize_page(
        self,
        source_hash: str,
        file_id: str,
        page_number: int,
        page_width_pt: float,
        page_height_pt: float,
        render: Mapping[str, Any],
        words: list[dict[str, Any]],
        strategy: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        width_px = int(render["width_px"])
        height_px = int(render["height_px"])
        page_image_hash = str(render["sha256"])
        word_records: list[dict[str, Any]] = []
        line_groups: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
        block_groups: dict[int, list[dict[str, Any]]] = {}

        for row in words:
            x0 = row["left"]
            y0 = row["top"]
            x1 = x0 + row["width"]
            y1 = y0 + row["height"]
            raster_bbox = [x0, y0, x1, y1]
            normalized_bbox = [
                round(x0 / width_px, 8), round(y0 / height_px, 8),
                round(x1 / width_px, 8), round(y1 / height_px, 8),
            ]
            pdf_bbox = [
                round(normalized_bbox[0] * page_width_pt, 6),
                round(normalized_bbox[1] * page_height_pt, 6),
                round(normalized_bbox[2] * page_width_pt, 6),
                round(normalized_bbox[3] * page_height_pt, 6),
            ]
            payload = {
                "source_sha256": source_hash,
                "page": page_number,
                "page_image_sha256": page_image_hash,
                "raster_bbox": raster_bbox,
                "surface": row["text"],
            }
            record = {
                "word_id": stable_id("OCR-WORD", payload),
                "file_id": file_id,
                "page_number": page_number,
                "surface_form": row["text"],
                "confidence": row["confidence"],
                "low_confidence": row["confidence"] < self.policy.minimum_word_confidence,
                "block_number": row["block_num"],
                "paragraph_number": row["paragraph_num"],
                "line_number": row["line_num"],
                "word_number": row["word_num"],
                "raster_bbox_px": raster_bbox,
                "normalized_bbox": normalized_bbox,
                "pdf_bbox_points": pdf_bbox,
                "source_pdf_sha256": source_hash,
                "page_image_sha256": page_image_hash,
                "evidence_anchor": {
                    "plane": "RENDERED_SOURCE_PAGE",
                    "page_number": page_number,
                    "render_dpi": int(strategy.split("_")[1]),
                    "page_image_sha256": page_image_hash,
                },
                "strategy": strategy,
            }
            word_records.append(record)
            line_groups.setdefault((row["block_num"], row["paragraph_num"], row["line_num"]), []).append(record)
            block_groups.setdefault(row["block_num"], []).append(record)

        line_records: list[dict[str, Any]] = []
        for key, members in sorted(line_groups.items()):
            ordered = sorted(members, key=lambda item: (item["raster_bbox_px"][0], item["word_number"]))
            raw_text = " ".join(item["surface_form"] for item in ordered)
            line_records.append(
                {
                    "line_id": stable_id("OCR-LINE", {"file_id": file_id, "page": page_number, "key": key, "words": [item["word_id"] for item in ordered]}),
                    "file_id": file_id,
                    "page_number": page_number,
                    "raw_text": raw_text,
                    "normalized_text": " ".join(raw_text.split()),
                    "word_ids": [item["word_id"] for item in ordered],
                    "raster_bbox_px": _bbox_union(item["raster_bbox_px"] for item in ordered),
                    "pdf_bbox_points": _bbox_union(item["pdf_bbox_points"] for item in ordered),
                    "mean_confidence": round(sum(float(item["confidence"]) for item in ordered) / len(ordered), 4),
                    "raw_source_sha256": sha256_bytes(raw_text.encode("utf-8")),
                    "page_image_sha256": page_image_hash,
                    "strategy": strategy,
                }
            )

        block_records: list[dict[str, Any]] = []
        lines_by_block: dict[int, list[dict[str, Any]]] = {}
        for line in line_records:
            first_word = next(item for item in word_records if item["word_id"] == line["word_ids"][0])
            lines_by_block.setdefault(int(first_word["block_number"]), []).append(line)
        for block_number, member_lines in sorted(lines_by_block.items()):
            ordered_lines = sorted(member_lines, key=lambda item: (item["raster_bbox_px"][1], item["raster_bbox_px"][0]))
            raw_text = "\n".join(item["raw_text"] for item in ordered_lines)
            block_records.append(
                {
                    "element_id": stable_id("ELEMENT", {"file_id": file_id, "page": page_number, "block": block_number, "page_image": page_image_hash}),
                    "file_id": file_id,
                    "page_number": page_number,
                    "element_type": "OCR_TEXT_BLOCK",
                    "role": "UNCLASSIFIED_TEXT",
                    "raw_text": raw_text,
                    "normalized_text": " ".join(raw_text.split()),
                    "raw_source_sha256": sha256_bytes(raw_text.encode("utf-8")),
                    "line_ids": [item["line_id"] for item in ordered_lines],
                    "word_ids": [word_id for item in ordered_lines for word_id in item["word_ids"]],
                    "raster_bbox_px": _bbox_union(item["raster_bbox_px"] for item in ordered_lines),
                    "bbox": _bbox_union(item["pdf_bbox_points"] for item in ordered_lines),
                    "normalized_bbox": [
                        round(value, 8)
                        for value in _bbox_union(
                            next(word for word in word_records if word["word_id"] == word_id)["normalized_bbox"]
                            for item in ordered_lines for word_id in item["word_ids"]
                        )
                    ],
                    "confidence": round(sum(item["mean_confidence"] for item in ordered_lines) / len(ordered_lines) / 100.0, 6),
                    "page_image_sha256": page_image_hash,
                    "evidence_plane": "RENDERED_SOURCE_PAGE",
                    "strategy": strategy,
                }
            )
        return word_records, line_records, block_records

    def reconstruct(self, source: Path, output_root: Path, file_id: str = "") -> Mapping[str, Any]:
        source = source.resolve()
        output_root = output_root.resolve()
        if not source.is_file() or source.read_bytes()[:5] != b"%PDF-":
            raise Stage1EvidenceError(f"invalid source PDF: {source}")
        source_hash = sha256_file(source)
        file_id = file_id or f"FILE-{source_hash[:20]}"
        info = self._run((self.toolchain.pdfinfo, source.as_posix()))
        if info.returncode != 0:
            raise Stage1EvidenceError("pdfinfo failed: " + info.stderr[-2000:])
        page_count, page_sizes = _pdf_page_sizes(info.stdout)
        render_root = output_root / source_hash / "page_renders"
        render_root.mkdir(parents=True, exist_ok=True)

        page_records: list[dict[str, Any]] = []
        words_all: list[dict[str, Any]] = []
        lines_all: list[dict[str, Any]] = []
        blocks_all: list[dict[str, Any]] = []
        attempts: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        started = time.perf_counter()

        with tempfile.TemporaryDirectory(prefix="truecolor-spatial-ocr-") as temporary:
            temp_root = Path(temporary)
            for page_number in range(1, page_count + 1):
                selected: tuple[Mapping[str, Any], list[dict[str, Any]], str] | None = None
                for dpi, psm in ((self.policy.initial_dpi, self.policy.initial_psm), (self.policy.retry_dpi, self.policy.retry_psm)):
                    render = self._render_page(source, page_number, dpi, temp_root / f"page-{page_number}-{dpi}.png")
                    words, ocr_attempt = self._ocr_tsv(Path(render["path"]), dpi, psm)
                    usable = len(words) >= self.policy.minimum_page_word_count
                    attempt = {
                        "page_number": page_number,
                        "strategy": f"OCR_{dpi}_DPI_PSM_{psm}_TSV",
                        "render_sha256": render["sha256"],
                        "render_width_px": render["width_px"],
                        "render_height_px": render["height_px"],
                        "render_elapsed_seconds": render["elapsed_seconds"],
                        "ocr_elapsed_seconds": ocr_attempt["elapsed_seconds"],
                        "returncode": ocr_attempt["returncode"],
                        "word_count": len(words),
                        "usable": usable,
                        "stderr": ocr_attempt["stderr"],
                    }
                    attempts.append(attempt)
                    if usable:
                        selected = (render, words, attempt["strategy"])
                        break
                if selected is None:
                    unresolved.append({"file_id": file_id, "page_number": page_number, "reason": "OCR_SPATIAL_RECOVERY_FAILED"})
                    continue
                render, words, strategy = selected
                render_path = Path(render["path"])
                retained_path = ""
                if self.policy.retain_page_renders:
                    retained = render_root / f"page-{page_number:05d}.png"
                    shutil.copyfile(render_path, retained)
                    retained_path = retained.relative_to(output_root).as_posix()
                page_width_pt, page_height_pt = page_sizes[page_number]
                word_records, line_records, block_records = self._materialize_page(
                    source_hash, file_id, page_number, page_width_pt, page_height_pt,
                    render, words, strategy,
                )
                words_all.extend(word_records)
                lines_all.extend(line_records)
                blocks_all.extend(block_records)
                page_records.append(
                    {
                        "page_id": stable_id("OCR-PAGE", {"file_id": file_id, "page": page_number, "render": render["sha256"]}),
                        "file_id": file_id,
                        "page_number": page_number,
                        "source_pdf_sha256": source_hash,
                        "page_image_sha256": render["sha256"],
                        "render_dpi": int(strategy.split("_")[1]),
                        "width_px": render["width_px"],
                        "height_px": render["height_px"],
                        "width_points": page_width_pt,
                        "height_points": page_height_pt,
                        "retained_render_path": retained_path,
                        "word_ids": [item["word_id"] for item in word_records],
                        "line_ids": [item["line_id"] for item in line_records],
                        "element_ids": [item["element_id"] for item in block_records],
                        "representation": "IMMUTABLE_RENDER_EVIDENCE_PLANE_WITH_OCR_OVERLAY",
                        "strategy": strategy,
                    }
                )

        doc_root = output_root / source_hash
        atomic_write_json(doc_root / "ocr_page_image_registry.json", {"schema_version": 1, "records": page_records})
        atomic_write_jsonl(doc_root / "ocr_word_registry.jsonl", words_all)
        atomic_write_jsonl(doc_root / "ocr_line_registry.jsonl", lines_all)
        atomic_write_jsonl(doc_root / "ocr_document_elements.jsonl", blocks_all)
        atomic_write_json(doc_root / "ocr_attempt_ledger.json", {"schema_version": 1, "records": attempts})
        atomic_write_json(doc_root / "ocr_unresolved_regions.json", {"schema_version": 1, "records": unresolved})
        manifest = {
            "schema": "truecolor.stage1.spatial-ocr-evidence-overlay",
            "schema_version": 1,
            "module_id": MODULE_ID,
            "policy_version": POLICY_VERSION,
            "source_path": source.as_posix(),
            "source_sha256": source_hash,
            "file_id": file_id,
            "page_count": page_count,
            "represented_page_count": len(page_records),
            "unresolved_page_count": len(unresolved),
            "word_count": len(words_all),
            "line_count": len(lines_all),
            "element_count": len(blocks_all),
            "evidence_model": "SOURCE_PDF -> DETERMINISTIC_PAGE_RENDER -> HASHED_EVIDENCE_PLANE -> OCR_COORDINATE_OVERLAY",
            "source_mutated": False,
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "outputs": [
                "ocr_page_image_registry.json", "ocr_word_registry.jsonl",
                "ocr_line_registry.jsonl", "ocr_document_elements.jsonl",
                "ocr_attempt_ledger.json", "ocr_unresolved_regions.json",
            ],
        }
        atomic_write_json(doc_root / "spatial_ocr_manifest.json", manifest)
        if len(page_records) + len(unresolved) != page_count:
            raise Stage1EvidenceError("spatial OCR did not terminally represent every page")
        if any(not item["page_image_sha256"] or not item["pdf_bbox_points"] for item in words_all):
            raise Stage1EvidenceError("OCR word lacks evidence-plane or PDF-coordinate grounding")
        if any(not item["raw_source_sha256"] for item in blocks_all):
            raise Stage1EvidenceError("OCR block lacks raw-text lineage")
        result = ModuleResult(
            module_id=MODULE_ID,
            module_state="CLOSED" if not unresolved else "PARTIAL",
            stage1_state="OPEN",
            outputs=tuple(manifest["outputs"]),
            counts={"pages": len(page_records), "words": len(words_all), "lines": len(lines_all), "elements": len(blocks_all), "unresolved": len(unresolved)},
            closure_gates={
                "source_immutable": "PASS",
                "every_page_terminal": "PASS",
                "render_evidence_hashed": "PASS",
                "word_coordinates_total": "PASS",
                "raw_text_lineage": "PASS",
            },
        )
        write_closure(doc_root, result)
        return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Create coordinate-bearing OCR evidence overlays for rendered PDF pages.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--file-id", default="")
    parser.add_argument("--retain-page-renders", action="store_true")
    args = parser.parse_args()
    policy = SpatialOcrPolicy(retain_page_renders=args.retain_page_renders)
    result = SpatialOcrReconstructor(policy=policy).reconstruct(Path(args.input), Path(args.output_root), args.file_id)
    print("TRUECOLOR_STAGE1_S1_M03_SPATIAL_OCR=PASS")
    print(f"page_count={result['page_count']}")
    print(f"represented_page_count={result['represented_page_count']}")
    print(f"unresolved_page_count={result['unresolved_page_count']}")
    print(f"word_count={result['word_count']}")
    print(f"element_count={result['element_count']}")


if __name__ == "__main__":
    main()
