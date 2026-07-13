from __future__ import annotations

import csv
import re
import shutil
import struct
import subprocess
import tempfile

from dataclasses import dataclass
from pathlib import Path
from typing import Any


OCR_RENDER_DPI = 300
OCR_LANGUAGE = "eng"


class OCRExecutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OCRWord:
    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int
    block_number: int
    paragraph_number: int
    line_number: int
    word_number: int


@dataclass(frozen=True)
class OCRPageResult:
    page_number: int
    dpi: int
    language: str
    engine: str
    engine_version: str
    render_engine: str
    render_engine_version: str
    image_width: int
    image_height: int
    words: tuple[OCRWord, ...]
    mean_confidence: float | None
    text: str


def require_binary(
    name: str,
) -> str:
    path = shutil.which(name)

    if path is None:
        raise OCRExecutionError(
            "OCR_REQUIRED_BINARY_MISSING",
            name,
        )

    return path


def run_command(
    command: list[str],
    *,
    code: str,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        raise OCRExecutionError(
            code,
            (
                "command="
                + " ".join(command)
                + "\nstdout="
                + completed.stdout
                + "\nstderr="
                + completed.stderr
            ),
        )

    return completed


def binary_version(
    executable: str,
    *,
    tesseract: bool = False,
) -> str:
    arguments = (
        [executable, "--version"]
        if tesseract
        else [executable, "-v"]
    )

    completed = subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        check=False,
    )

    lines = (
        completed.stdout
        + completed.stderr
    ).strip().splitlines()

    return (
        lines[0]
        if lines
        else "UNKNOWN"
    )


def png_dimensions(
    path: Path,
) -> tuple[int, int]:
    payload = path.read_bytes()

    if len(payload) < 24:
        raise OCRExecutionError(
            "OCR_RENDERED_IMAGE_TRUNCATED",
            str(path),
        )

    if payload[:8] != (
        b"\x89PNG\r\n\x1a\n"
    ):
        raise OCRExecutionError(
            "OCR_RENDERED_IMAGE_NOT_PNG",
            str(path),
        )

    if payload[12:16] != b"IHDR":
        raise OCRExecutionError(
            "OCR_RENDERED_IMAGE_IHDR_MISSING",
            str(path),
        )

    width, height = struct.unpack(
        ">II",
        payload[16:24],
    )

    if width < 1 or height < 1:
        raise OCRExecutionError(
            "OCR_RENDERED_IMAGE_DIMENSIONS_INVALID",
            f"{width}x{height}",
        )

    return width, height


def render_pdf_page(
    pdf_path: Path,
    *,
    page_number: int,
    output_directory: Path,
    dpi: int,
) -> tuple[
    Path,
    str,
]:
    pdftoppm = require_binary(
        "pdftoppm"
    )

    output_prefix = (
        output_directory
        / f"page-{page_number:06d}"
    )

    run_command(
        [
            pdftoppm,
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-r",
            str(dpi),
            "-png",
            "-singlefile",
            str(pdf_path),
            str(output_prefix),
        ],
        code="OCR_PAGE_RENDER_FAILED",
    )

    output_path = output_prefix.with_suffix(
        ".png"
    )

    if not output_path.is_file():
        raise OCRExecutionError(
            "OCR_RENDERED_IMAGE_MISSING",
            str(output_path),
        )

    return (
        output_path,
        binary_version(
            pdftoppm
        ),
    )


def parse_confidence(
    value: str,
) -> float | None:
    try:
        confidence = float(
            value
        )
    except ValueError:
        return None

    if confidence < 0:
        return None

    return confidence


def parse_tesseract_tsv(
    payload: str,
) -> tuple[OCRWord, ...]:
    reader = csv.DictReader(
        payload.splitlines(),
        delimiter="\t",
    )

    required_fields = {
        "level",
        "block_num",
        "par_num",
        "line_num",
        "word_num",
        "left",
        "top",
        "width",
        "height",
        "conf",
        "text",
    }

    fieldnames = set(
        reader.fieldnames or []
    )

    if not required_fields.issubset(
        fieldnames
    ):
        missing = sorted(
            required_fields
            - fieldnames
        )

        raise OCRExecutionError(
            "OCR_TSV_FIELDS_MISSING",
            ",".join(missing),
        )

    words: list[OCRWord] = []

    for row in reader:
        if row.get("level") != "5":
            continue

        text = (
            row.get(
                "text",
                "",
            )
            or ""
        ).strip()

        if not text:
            continue

        confidence = parse_confidence(
            row.get(
                "conf",
                "",
            )
            or ""
        )

        if confidence is None:
            continue

        try:
            word = OCRWord(
                text=text,
                confidence=confidence,
                left=int(
                    row["left"]
                ),
                top=int(
                    row["top"]
                ),
                width=int(
                    row["width"]
                ),
                height=int(
                    row["height"]
                ),
                block_number=int(
                    row["block_num"]
                ),
                paragraph_number=int(
                    row["par_num"]
                ),
                line_number=int(
                    row["line_num"]
                ),
                word_number=int(
                    row["word_num"]
                ),
            )
        except (
            TypeError,
            ValueError,
            KeyError,
        ) as exc:
            raise OCRExecutionError(
                "OCR_TSV_ROW_INVALID",
                repr(row),
            ) from exc

        if (
            word.width < 1
            or word.height < 1
            or word.left < 0
            or word.top < 0
        ):
            raise OCRExecutionError(
                "OCR_TSV_GEOMETRY_INVALID",
                repr(row),
            )

        words.append(word)

    return tuple(words)


def canonical_ocr_text(
    words: tuple[OCRWord, ...],
) -> str:
    pieces: list[str] = []
    previous_group: tuple[
        int,
        int,
        int,
    ] | None = None

    for word in words:
        group = (
            word.block_number,
            word.paragraph_number,
            word.line_number,
        )

        if pieces:
            pieces.append(
                "\n"
                if group
                != previous_group
                else " "
            )

        pieces.append(
            word.text
        )

        previous_group = group

    return "".join(pieces)


def execute_page_ocr(
    pdf_path: Path,
    *,
    page_number: int,
    dpi: int = OCR_RENDER_DPI,
    language: str = OCR_LANGUAGE,
) -> OCRPageResult:
    if page_number < 1:
        raise OCRExecutionError(
            "OCR_PAGE_NUMBER_INVALID",
            str(page_number),
        )

    if dpi < 72 or dpi > 1200:
        raise OCRExecutionError(
            "OCR_DPI_INVALID",
            str(dpi),
        )

    tesseract = require_binary(
        "tesseract"
    )

    with tempfile.TemporaryDirectory(
        prefix=(
            "truecolor-ocr-"
            f"{page_number:06d}-"
        )
    ) as temporary:
        temporary_path = Path(
            temporary
        )

        (
            rendered_page,
            render_version,
        ) = render_pdf_page(
            pdf_path,
            page_number=page_number,
            output_directory=(
                temporary_path
            ),
            dpi=dpi,
        )

        (
            image_width,
            image_height,
        ) = png_dimensions(
            rendered_page
        )

        completed = run_command(
            [
                tesseract,
                str(rendered_page),
                "stdout",
                "-l",
                language,
                "--dpi",
                str(dpi),
                "tsv",
            ],
            code="OCR_TESSERACT_FAILED",
        )

        words = parse_tesseract_tsv(
            completed.stdout
        )

    confidences = [
        word.confidence
        for word in words
    ]

    mean_confidence = (
        sum(confidences)
        / len(confidences)
        if confidences
        else None
    )

    return OCRPageResult(
        page_number=page_number,
        dpi=dpi,
        language=language,
        engine="tesseract",
        engine_version=(
            binary_version(
                tesseract,
                tesseract=True,
            )
        ),
        render_engine="pdftoppm",
        render_engine_version=(
            render_version
        ),
        image_width=image_width,
        image_height=image_height,
        words=words,
        mean_confidence=(
            mean_confidence
        ),
        text=canonical_ocr_text(
            words
        ),
    )


def pdf_bbox_from_ocr_word(
    word: OCRWord,
    *,
    page_width: float,
    page_height: float,
    image_width: int,
    image_height: int,
) -> dict[str, float]:
    if (
        page_width <= 0
        or page_height <= 0
        or image_width <= 0
        or image_height <= 0
    ):
        raise OCRExecutionError(
            "OCR_COORDINATE_SCALE_INVALID",
            (
                f"page={page_width}x{page_height};"
                f"image={image_width}x{image_height}"
            ),
        )

    scale_x = (
        page_width
        / image_width
    )

    scale_y = (
        page_height
        / image_height
    )

    return {
        "x0": word.left * scale_x,
        "y0": word.top * scale_y,
        "x1": (
            word.left
            + word.width
        )
        * scale_x,
        "y1": (
            word.top
            + word.height
        )
        * scale_y,
    }


def ocr_result_record(
    result: OCRPageResult,
) -> dict[str, Any]:
    return {
        "execution_status": (
            "SUCCEEDED"
        ),
        "engine": result.engine,
        "engine_version": (
            result.engine_version
        ),
        "render_engine": (
            result.render_engine
        ),
        "render_engine_version": (
            result.render_engine_version
        ),
        "language": result.language,
        "dpi": result.dpi,
        "render_width_px": (
            result.image_width
        ),
        "render_height_px": (
            result.image_height
        ),
        "recognized_word_count": len(
            result.words
        ),
        "recognized_character_count": (
            len(
                re.sub(
                    r"\s+",
                    "",
                    result.text,
                )
            )
        ),
        "mean_confidence": (
            result.mean_confidence
        ),
    }
