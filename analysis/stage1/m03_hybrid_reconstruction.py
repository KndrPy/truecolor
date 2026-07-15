from __future__ import annotations

import argparse
import csv
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
    ensure_fitz,
    load_json,
    normalized_text,
    sha256_bytes,
    sha256_file,
    stable_id,
    write_closure,
)

MODULE_ID = "S1-M03"
POLICY_VERSION = 1


@dataclass(frozen=True)
class HybridReconstructionPolicy:
    native_min_non_whitespace_chars: int = 80
    native_min_text_blocks: int = 1
    initial_ocr_dpi: int = 200
    retry_ocr_dpi: int = 300
    initial_ocr_psm: int = 3
    retry_ocr_psm: int = 6
    minimum_ocr_words: int = 8
    minimum_word_confidence: float = 35.0
    language: str = "eng"
    command_timeout_seconds: int = 180
    retain_page_renders: bool = False


@dataclass(frozen=True)
class Toolchain:
    pdftoppm: str
    tesseract: str

    @classmethod
    def detect(cls) -> "Toolchain":
        values = {name: shutil.which(name) for name in ("pdftoppm", "tesseract")}
        missing = sorted(name for name, value in values.items() if not value)
        if missing:
            raise Stage1EvidenceError("required hybrid reconstruction tools absent: " + ", ".join(missing))
        return cls(**{name: str(value) for name, value in values.items()})


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


def _bbox_union(boxes: Iterable[Sequence[float]]) -> list[float]:
    materialized = [tuple(float(value) for value in box) for box in boxes]
    if not materialized:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        min(box[0] for box in materialized),
        min(box[1] for box in materialized),
        max(box[2] for box in materialized),
        max(box[3] for box in materialized),
    ]


def _png_dimensions(path: Path) -> tuple[int, int]:
    payload = path.read_bytes()
    if payload[:8] != b"\x89PNG\r\n\x1a\n" or len(payload) < 24:
        raise Stage1EvidenceError(f"invalid page render: {path}")
    return int.from_bytes(payload[16:20], "big"), int.from_bytes(payload[20:24], "big")


def _tsv_words(payload: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(payload), delimiter="\t")
    required = {
        "level", "block_num", "par_num", "line_num", "word_num",
        "left", "top", "width", "height", "conf", "text",
    }
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        raise Stage1EvidenceError("Tesseract TSV schema is incomplete")
    records: list[dict[str, Any]] = []
    for row in reader:
        if row.get("level") != "5" or not str(row.get("text", "")).strip():
            continue
        try:
            confidence = float(row.get("conf", "-1"))
        except ValueError:
            confidence = -1.0
        records.append(
            {
                "block": int(row["block_num"]),
                "paragraph": int(row["par_num"]),
                "line": int(row["line_num"]),
                "word": int(row["word_num"]),
                "left": int(row["left"]),
                "top": int(row["top"]),
                "width": int(row["width"]),
                "height": int(row["height"]),
                "confidence": confidence,
                "text": str(row["text"]),
            }
        )
    return records


def classify_page(native_chars: int, native_blocks: int, policy: HybridReconstructionPolicy) -> str:
    if native_chars >= policy.native_min_non_whitespace_chars and native_blocks >= policy.native_min_text_blocks:
        return "NATIVE_LAYOUT"
    if native_chars > 0 or native_blocks > 0:
        return "NATIVE_PLUS_OCR_EVIDENCE_LAYERS"
    return "SPATIAL_OCR"


class HybridSpatialReconstructor:
    """Preserve native structure where trustworthy and selectively add OCR evidence layers.

    OCR never overwrites native content. On mixed pages both layers are retained with
    independent coordinates, hashes, confidence and reading-order graphs. Semantic
    reconciliation is deferred to a later reviewed transformation.
    """

    def __init__(
        self,
        policy: HybridReconstructionPolicy | None = None,
        toolchain: Toolchain | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self.policy = policy or HybridReconstructionPolicy()
        self.toolchain = toolchain or Toolchain.detect()
        self.runner = runner or CommandRunner()

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return self.runner.run(command, self.policy.command_timeout_seconds)

    def _native_elements(self, fitz: Any, page: Any, file_id: str, source_hash: str, page_number: int) -> list[dict[str, Any]]:
        try:
            page_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES)
        except Exception as error:
            raise Stage1EvidenceError(f"native layout failed on page {page_number}: {type(error).__name__}: {error}") from error
        elements: list[dict[str, Any]] = []
        for block_index, block in enumerate(page_dict.get("blocks", [])):
            if int(block.get("type", -1)) != 0:
                continue
            lines: list[str] = []
            spans: list[dict[str, Any]] = []
            for line in block.get("lines", []):
                line_spans = list(line.get("spans", []))
                lines.append("".join(str(span.get("text", "")) for span in line_spans))
                spans.extend(
                    {
                        "text": str(span.get("text", "")),
                        "bbox": [float(value) for value in span.get("bbox", (0, 0, 0, 0))],
                        "font": str(span.get("font", "")),
                        "size": float(span.get("size", 0.0)),
                        "flags": int(span.get("flags", 0)),
                    }
                    for span in line_spans
                )
            raw = "\n".join(lines).strip()
            if not raw:
                continue
            bbox = [float(value) for value in block.get("bbox", (0, 0, 0, 0))]
            element_id = stable_id(
                "ELEMENT",
                {"file": file_id, "page": page_number, "native_block": block_index, "raw": sha256_bytes(raw.encode("utf-8"))},
            )
            elements.append(
                {
                    "element_id": element_id,
                    "file_id": file_id,
                    "page_number": page_number,
                    "element_type": "NATIVE_TEXT_BLOCK",
                    "evidence_layer": "NATIVE_PDF_OBJECT_MODEL",
                    "bbox": bbox,
                    "raw_text": raw,
                    "normalized_text": normalized_text(raw),
                    "raw_source_sha256": sha256_bytes(raw.encode("utf-8")),
                    "source_pdf_sha256": source_hash,
                    "confidence": 1.0,
                    "spans": spans,
                }
            )
        return elements

    def _spatial_ocr_page(
        self,
        source: Path,
        file_id: str,
        source_hash: str,
        page_number: int,
        width_points: float,
        height_points: float,
        temp_root: Path,
        retained_root: Path,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Mapping[str, Any], list[dict[str, Any]]]:
        attempts: list[dict[str, Any]] = []
        selected: tuple[Path, int, int, list[dict[str, Any]], str] | None = None
        for dpi, psm in (
            (self.policy.initial_ocr_dpi, self.policy.initial_ocr_psm),
            (self.policy.retry_ocr_dpi, self.policy.retry_ocr_psm),
        ):
            prefix = temp_root / f"page-{page_number:05d}-{dpi}"
            render_started = time.perf_counter()
            render = self._run(
                (
                    self.toolchain.pdftoppm, "-f", str(page_number), "-l", str(page_number),
                    "-singlefile", "-r", str(dpi), "-png", source.as_posix(), prefix.as_posix(),
                )
            )
            image = prefix.with_suffix(".png")
            if render.returncode != 0 or not image.is_file():
                attempts.append(
                    {
                        "page_number": page_number,
                        "strategy": f"OCR_{dpi}_DPI_PSM_{psm}_TSV",
                        "stage": "RENDER",
                        "returncode": render.returncode or 1,
                        "usable": False,
                        "stderr": render.stderr[-2000:],
                        "elapsed_seconds": round(time.perf_counter() - render_started, 6),
                    }
                )
                continue
            width_px, height_px = _png_dimensions(image)
            image_hash = sha256_file(image)
            ocr_started = time.perf_counter()
            ocr = self._run(
                (
                    self.toolchain.tesseract, image.as_posix(), "stdout", "--dpi", str(dpi),
                    "--psm", str(psm), "-l", self.policy.language, "tsv",
                )
            )
            words = _tsv_words(ocr.stdout) if ocr.returncode == 0 else []
            usable = len(words) >= self.policy.minimum_ocr_words
            strategy = f"OCR_{dpi}_DPI_PSM_{psm}_TSV"
            attempts.append(
                {
                    "page_number": page_number,
                    "strategy": strategy,
                    "stage": "OCR",
                    "returncode": ocr.returncode,
                    "usable": usable,
                    "word_count": len(words),
                    "page_image_sha256": image_hash,
                    "stderr": ocr.stderr[-2000:],
                    "elapsed_seconds": round(time.perf_counter() - ocr_started, 6),
                }
            )
            if usable:
                selected = (image, width_px, height_px, words, strategy)
                break
        if selected is None:
            return [], [], {"state": "UNRESOLVED", "page_number": page_number}, attempts

        image, width_px, height_px, words, strategy = selected
        page_image_hash = sha256_file(image)
        retained_path = ""
        if self.policy.retain_page_renders:
            retained_root.mkdir(parents=True, exist_ok=True)
            destination = retained_root / f"page-{page_number:05d}.png"
            shutil.copyfile(image, destination)
            retained_path = destination.as_posix()

        word_records: list[dict[str, Any]] = []
        groups: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
        for item in words:
            x0, y0 = item["left"], item["top"]
            x1, y1 = x0 + item["width"], y0 + item["height"]
            normalized_bbox = [x0 / width_px, y0 / height_px, x1 / width_px, y1 / height_px]
            pdf_bbox = [
                round(normalized_bbox[0] * width_points, 6),
                round(normalized_bbox[1] * height_points, 6),
                round(normalized_bbox[2] * width_points, 6),
                round(normalized_bbox[3] * height_points, 6),
            ]
            word_id = stable_id(
                "OCR-WORD",
                {"file": file_id, "page": page_number, "image": page_image_hash, "bbox": [x0, y0, x1, y1], "text": item["text"]},
            )
            record = {
                "word_id": word_id,
                "file_id": file_id,
                "page_number": page_number,
                "surface_form": item["text"],
                "confidence": item["confidence"],
                "low_confidence": item["confidence"] < self.policy.minimum_word_confidence,
                "raster_bbox_px": [x0, y0, x1, y1],
                "normalized_bbox": [round(value, 8) for value in normalized_bbox],
                "pdf_bbox_points": pdf_bbox,
                "source_pdf_sha256": source_hash,
                "page_image_sha256": page_image_hash,
                "strategy": strategy,
            }
            word_records.append(record)
            groups.setdefault((item["block"], item["paragraph"], item["line"]), []).append(record)

        elements: list[dict[str, Any]] = []
        for sequence, (key, members) in enumerate(sorted(groups.items(), key=lambda pair: min(word["raster_bbox_px"][1] for word in pair[1]))):
            ordered = sorted(members, key=lambda word: word["raster_bbox_px"][0])
            raw = " ".join(word["surface_form"] for word in ordered)
            element_id = stable_id(
                "ELEMENT",
                {"file": file_id, "page": page_number, "ocr_line": key, "image": page_image_hash, "raw": sha256_bytes(raw.encode("utf-8"))},
            )
            elements.append(
                {
                    "element_id": element_id,
                    "file_id": file_id,
                    "page_number": page_number,
                    "element_type": "OCR_TEXT_LINE",
                    "evidence_layer": "RENDERED_SOURCE_PAGE_OCR_OVERLAY",
                    "bbox": _bbox_union(word["pdf_bbox_points"] for word in ordered),
                    "raster_bbox_px": _bbox_union(word["raster_bbox_px"] for word in ordered),
                    "raw_text": raw,
                    "normalized_text": normalized_text(raw),
                    "raw_source_sha256": sha256_bytes(raw.encode("utf-8")),
                    "source_pdf_sha256": source_hash,
                    "page_image_sha256": page_image_hash,
                    "word_ids": [word["word_id"] for word in ordered],
                    "confidence": round(sum(float(word["confidence"]) for word in ordered) / len(ordered) / 100.0, 6),
                    "reading_order": sequence,
                    "strategy": strategy,
                }
            )

        page_record = {
            "file_id": file_id,
            "page_number": page_number,
            "state": "OCR_REPRESENTED",
            "page_image_sha256": page_image_hash,
            "render_dpi": int(strategy.split("_")[1]),
            "width_px": width_px,
            "height_px": height_px,
            "width_points": width_points,
            "height_points": height_points,
            "retained_render_path": retained_path,
            "word_ids": [word["word_id"] for word in word_records],
            "element_ids": [element["element_id"] for element in elements],
            "representation": "IMMUTABLE_RENDER_EVIDENCE_PLANE_WITH_OCR_OVERLAY",
            "strategy": strategy,
        }
        return word_records, elements, page_record, attempts

    def reconstruct(self, corpus_root: Path, source_integrity_path: Path, output_root: Path) -> ModuleResult:
        fitz = ensure_fitz()
        sources = list(load_json(source_integrity_path).get("records", []))
        output_root.mkdir(parents=True, exist_ok=True)
        page_records: list[dict[str, Any]] = []
        elements: list[dict[str, Any]] = []
        words: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        attempts: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        structures: list[dict[str, Any]] = []
        started = time.perf_counter()

        with tempfile.TemporaryDirectory(prefix="truecolor-m03-hybrid-") as temporary:
            temp_root = Path(temporary)
            for source_record in sources:
                file_id = str(source_record["file_id"])
                source_state = str(source_record.get("state", ""))
                if source_state in {"UNREADABLE", "ENCRYPTED", "TRUNCATED"}:
                    unresolved.append({"file_id": file_id, "scope": "DOCUMENT", "reason": source_state})
                    continue
                source = (corpus_root / str(source_record["relative_path"])).resolve()
                source_hash = sha256_file(source)
                document = fitz.open(source)
                document_element_ids: list[str] = []
                try:
                    for page_index in range(len(document)):
                        page_number = page_index + 1
                        page = document.load_page(page_index)
                        native = self._native_elements(fitz, page, file_id, source_hash, page_number)
                        native_chars = sum(len("".join(item["raw_text"].split())) for item in native)
                        route = classify_page(native_chars, len(native), self.policy)
                        selected = list(native)
                        ocr_page: Mapping[str, Any] | None = None
                        if route != "NATIVE_LAYOUT":
                            word_records, ocr_elements, ocr_page, page_attempts = self._spatial_ocr_page(
                                source,
                                file_id,
                                source_hash,
                                page_number,
                                float(page.rect.width),
                                float(page.rect.height),
                                temp_root,
                                output_root / "page_renders" / source_hash,
                            )
                            attempts.extend(page_attempts)
                            words.extend(word_records)
                            selected.extend(ocr_elements)
                            if ocr_page.get("state") == "UNRESOLVED":
                                unresolved.append({"file_id": file_id, "page_number": page_number, "scope": "PAGE", "reason": "SPATIAL_OCR_FAILED", "native_characters": native_chars})
                        selected.sort(key=lambda item: (float(item["bbox"][1]), float(item["bbox"][0]), item["evidence_layer"]))
                        for order, item in enumerate(selected):
                            item["reading_order"] = order
                        for left, right in zip(selected, selected[1:]):
                            edges.append(
                                {
                                    "edge_id": stable_id("ORDER", {"from": left["element_id"], "to": right["element_id"]}),
                                    "file_id": file_id,
                                    "page_number": page_number,
                                    "from_element_id": left["element_id"],
                                    "to_element_id": right["element_id"],
                                    "relation": "NEXT_IN_EVIDENCE_LAYER_VIEW",
                                }
                            )
                        elements.extend(selected)
                        document_element_ids.extend(item["element_id"] for item in selected)
                        page_records.append(
                            {
                                "page_layout_id": stable_id("PAGE-LAYOUT", {"file": file_id, "page": page_number}),
                                "file_id": file_id,
                                "page_number": page_number,
                                "width": float(page.rect.width),
                                "height": float(page.rect.height),
                                "rotation": int(page.rotation),
                                "route": route,
                                "native_element_ids": [item["element_id"] for item in native],
                                "ocr_element_ids": [item["element_id"] for item in selected if item["evidence_layer"] == "RENDERED_SOURCE_PAGE_OCR_OVERLAY"],
                                "element_ids": [item["element_id"] for item in selected],
                                "ocr_evidence": dict(ocr_page) if ocr_page and ocr_page.get("state") != "UNRESOLVED" else None,
                                "fusion_policy": "PRESERVE_LAYERS_NO_SEMANTIC_OVERWRITE",
                            }
                        )
                    structures.append(
                        {
                            "document_structure_id": stable_id("DOC-STRUCTURE", {"file": file_id, "source": source_hash}),
                            "file_id": file_id,
                            "source_pdf_sha256": source_hash,
                            "page_count": len(document),
                            "element_ids": document_element_ids,
                        }
                    )
                finally:
                    document.close()

        atomic_write_json(output_root / "document_structure.json", {"schema_version": 1, "records": structures})
        atomic_write_jsonl(output_root / "document_elements.jsonl", elements)
        atomic_write_jsonl(output_root / "page_layouts.jsonl", page_records)
        atomic_write_json(output_root / "reading_order_graph.json", {"schema_version": 1, "edges": edges})
        atomic_write_jsonl(output_root / "ocr_word_registry.jsonl", words)
        atomic_write_json(output_root / "ocr_attempt_ledger.json", {"schema_version": 1, "records": attempts})
        atomic_write_json(output_root / "unresolved_extraction_regions.json", {"schema_version": 1, "records": unresolved})

        expected_pages = sum(int(item.get("page_count", 0) or 0) for item in sources if item.get("state") not in {"UNREADABLE", "ENCRYPTED", "TRUNCATED"})
        if expected_pages and len(page_records) != expected_pages:
            raise Stage1EvidenceError(f"page representation is not total: expected {expected_pages}, emitted {len(page_records)}")
        if any(not item.get("bbox") or not item.get("raw_source_sha256") for item in elements):
            raise Stage1EvidenceError("element coordinate or source lineage is incomplete")
        mixed_pages = [item for item in page_records if item["route"] == "NATIVE_PLUS_OCR_EVIDENCE_LAYERS"]
        if any(not item["native_element_ids"] or not item["ocr_element_ids"] for item in mixed_pages):
            raise Stage1EvidenceError("mixed page did not preserve both evidence layers")

        result = ModuleResult(
            MODULE_ID,
            "CLOSED" if not unresolved else "PARTIALLY_CLOSED",
            "OPEN",
            (
                "document_structure.json",
                "document_elements.jsonl",
                "page_layouts.jsonl",
                "reading_order_graph.json",
                "ocr_word_registry.jsonl",
                "ocr_attempt_ledger.json",
                "unresolved_extraction_regions.json",
            ),
            {
                "documents": len(structures),
                "pages": len(page_records),
                "elements": len(elements),
                "ocr_words": len(words),
                "unresolved_regions": len(unresolved),
            },
            {
                "all_pages_represented": "PASS" if len(page_records) == expected_pages else "FAIL",
                "source_coordinates_total": "PASS",
                "raw_normalized_lineage": "PASS",
                "native_ocr_layer_separation": "PASS",
                "no_semantic_overwrite": "PASS",
            },
        )
        write_closure(output_root, result)
        atomic_write_json(
            output_root / "m03_hybrid_manifest.json",
            {
                "schema": "truecolor.stage1.hybrid-spatial-reconstruction",
                "schema_version": 1,
                "policy_version": POLICY_VERSION,
                "policy": asdict(self.policy),
                "evidence_model": "SOURCE_PDF -> NATIVE_OBJECT_LAYER OR HASHED_RENDER_EVIDENCE_PLANE -> COORDINATE OCR OVERLAY",
                "fusion_policy": "PRESERVE_LAYERS_NO_SEMANTIC_OVERWRITE",
                "elapsed_seconds": round(time.perf_counter() - started, 6),
                "module_state": result.module_state,
            },
        )
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run canonical hybrid native/spatial OCR reconstruction.")
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--source-integrity", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--retain-page-renders", action="store_true")
    args = parser.parse_args()
    policy = HybridReconstructionPolicy(retain_page_renders=args.retain_page_renders)
    result = HybridSpatialReconstructor(policy=policy).reconstruct(
        Path(args.corpus_root), Path(args.source_integrity), Path(args.output_root)
    )
    print("TRUECOLOR_STAGE1_S1_M03=PASS")
    print(f"module_state={result.module_state}")
    print(f"stage1_state={result.stage1_state}")
    for key, value in sorted(result.counts.items()):
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
