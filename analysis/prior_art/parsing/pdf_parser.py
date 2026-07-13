from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from pathlib import Path
from typing import Any

from .ocr_engine import (
    OCRExecutionError,
    execute_page_ocr,
    ocr_result_record,
    pdf_bbox_from_ocr_word,
)


class PDFParseError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


def require_binary(
    name: str,
) -> str:
    path = shutil.which(name)

    if path is None:
        raise PDFParseError(
            "REQUIRED_BINARY_MISSING",
            name,
        )

    return path


def run_checked(
    command: list[str],
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        raise PDFParseError(
            "PDF_TOOL_FAILED",
            (
                "command="
                + " ".join(command)
                + "\nstderr="
                + completed.stderr
            ),
        )

    return completed


def page_count(
    path: Path,
) -> int:
    pdfinfo = require_binary(
        "pdfinfo"
    )

    result = run_checked(
        [
            pdfinfo,
            str(path),
        ]
    )

    match = re.search(
        r"^Pages:\s+(\d+)\s*$",
        result.stdout,
        re.MULTILINE,
    )

    if match is None:
        raise PDFParseError(
            "PDF_PAGE_COUNT_MISSING",
            str(path),
        )

    count = int(
        match.group(1)
    )

    if count < 1:
        raise PDFParseError(
            "PDF_HAS_NO_PAGES",
            str(path),
        )

    return count


def extract_page_text(
    path: Path,
    page_number: int,
) -> str:
    pdftotext = require_binary(
        "pdftotext"
    )

    completed = run_checked(
        [
            pdftotext,
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-layout",
            "-enc",
            "UTF-8",
            str(path),
            "-",
        ]
    )

    return (
        completed.stdout
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .rstrip("\f\n")
    )


def extract_bbox_xml(
    path: Path,
) -> ET.Element:
    pdftotext = require_binary(
        "pdftotext"
    )

    with tempfile.TemporaryDirectory(
        prefix="truecolor-pdf-"
    ) as temporary:
        output = (
            Path(temporary)
            / "bbox.xhtml"
        )

        run_checked(
            [
                pdftotext,
                "-bbox-layout",
                "-enc",
                "UTF-8",
                str(path),
                str(output),
            ]
        )

        try:
            return ET.parse(
                output
            ).getroot()
        except ET.ParseError as exc:
            raise PDFParseError(
                "PDF_BBOX_XML_INVALID",
                str(path),
            ) from exc


def local_name(
    tag: str,
) -> str:
    return tag.rsplit(
        "}",
        1,
    )[-1]


def segment_id(
    *,
    artifact_id: str,
    page_number: int,
    word_index: int,
    text: str,
    bbox: dict[str, float],
) -> str:
    basis = (
        f"{artifact_id}\n"
        f"{page_number}\n"
        f"{word_index}\n"
        f"{text}\n"
        f"{bbox['x0']}\n"
        f"{bbox['y0']}\n"
        f"{bbox['x1']}\n"
        f"{bbox['y1']}"
    ).encode("utf-8")

    return (
        "segment:"
        + hashlib.sha256(
            basis
        ).hexdigest()
    )


def classify_ocr(
    *,
    page_number: int,
    text: str,
) -> dict[str, Any]:
    character_count = len(
        text.strip()
    )

    word_count = len(
        re.findall(
            r"\S+",
            text,
        )
    )

    reasons: list[str] = []

    if character_count == 0:
        classification = (
            "OCR_REQUIRED"
        )

        reasons.append(
            "NO_EMBEDDED_TEXT"
        )

    elif (
        character_count < 40
        or word_count < 8
    ):
        classification = (
            "OCR_RECOMMENDED"
        )

        reasons.append(
            "LOW_TEXT_DENSITY"
        )

    else:
        classification = (
            "OCR_NOT_REQUIRED"
        )

        reasons.append(
            "SUFFICIENT_EMBEDDED_TEXT"
        )

    return {
        "page_number": (
            page_number
        ),
        "classification": (
            classification
        ),
        "reason_codes": reasons,
        "character_count": (
            character_count
        ),
        "word_count": word_count,
    }


def parse_pdf(
    path: Path,
    *,
    artifact_id: str,
) -> tuple[
    str,
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    count = page_count(path)

    page_texts = {
        number: extract_page_text(
            path,
            number,
        )
        for number in range(
            1,
            count + 1,
        )
    }

    root = extract_bbox_xml(
        path
    )

    page_elements = [
        element
        for element in root.iter()
        if local_name(
            element.tag
        )
        == "page"
    ]

    pages: list[
        dict[str, Any]
    ] = []

    segments: list[
        dict[str, Any]
    ] = []

    ocr_assessment: list[
        dict[str, Any]
    ] = []

    canonical_pieces: list[
        str
    ] = []

    def append_separator(
        separator: str,
    ) -> None:
        if canonical_pieces:
            canonical_pieces.append(
                separator
            )

    for page_index in range(
        count
    ):
        page_number = (
            page_index + 1
        )

        page_element = (
            page_elements[
                page_index
            ]
            if page_index
            < len(page_elements)
            else None
        )

        width = None
        height = None

        if page_element is not None:
            width = float(
                page_element.attrib.get(
                    "width",
                    "0",
                )
            )

            height = float(
                page_element.attrib.get(
                    "height",
                    "0",
                )
            )

        embedded_page_text = (
            page_texts[
                page_number
            ]
        )

        assessment = classify_ocr(
            page_number=page_number,
            text=embedded_page_text,
        )

        page_output_text = (
            embedded_page_text
        )

        text_source = "EMBEDDED"

        ocr_mean_confidence = None

        if (
            assessment[
                "classification"
            ]
            == "OCR_REQUIRED"
        ):
            if (
                width is None
                or height is None
                or width <= 0
                or height <= 0
            ):
                raise PDFParseError(
                    "OCR_PAGE_DIMENSIONS_MISSING",
                    (
                        f"page_number="
                        f"{page_number}"
                    ),
                )

            try:
                ocr_result = (
                    execute_page_ocr(
                        path,
                        page_number=(
                            page_number
                        ),
                    )
                )
            except OCRExecutionError as exc:
                raise PDFParseError(
                    exc.code,
                    str(exc),
                ) from exc

            page_output_text = (
                ocr_result.text
            )

            text_source = "OCR"

            ocr_mean_confidence = (
                ocr_result.mean_confidence
            )

            previous_group = None

            for (
                word_index,
                word,
            ) in enumerate(
                ocr_result.words
            ):
                group = (
                    word.block_number,
                    word.paragraph_number,
                    word.line_number,
                )

                if previous_group is not None:
                    append_separator(
                        "\n"
                        if group
                        != previous_group
                        else " "
                    )

                start = sum(
                    len(piece)
                    for piece
                    in canonical_pieces
                )

                canonical_pieces.append(
                    word.text
                )

                end = (
                    start
                    + len(word.text)
                )

                bbox = (
                    pdf_bbox_from_ocr_word(
                        word,
                        page_width=width,
                        page_height=height,
                        image_width=(
                            ocr_result
                            .image_width
                        ),
                        image_height=(
                            ocr_result
                            .image_height
                        ),
                    )
                )

                segments.append(
                    {
                        "segment_id": (
                            segment_id(
                                artifact_id=(
                                    artifact_id
                                ),
                                page_number=(
                                    page_number
                                ),
                                word_index=(
                                    word_index
                                ),
                                text=word.text,
                                bbox=bbox,
                            )
                        ),
                        "kind": "PAGE",
                        "text": word.text,
                        "canonical_start": (
                            start
                        ),
                        "canonical_end": end,
                        "source": {
                            "page_number": (
                                page_number
                            ),
                            "source_start": (
                                None
                            ),
                            "source_end": None,
                            "bbox": bbox,
                            "xml_path": None,
                            "extraction_method": (
                                "OCR"
                            ),
                            "ocr_confidence": (
                                word.confidence
                            ),
                            "ocr_engine": (
                                ocr_result.engine
                            ),
                            "ocr_language": (
                                ocr_result.language
                            ),
                            "render_dpi": (
                                ocr_result.dpi
                            ),
                        },
                    }
                )

                previous_group = group

            assessment.update(
                ocr_result_record(
                    ocr_result
                )
            )

        else:
            words = (
                [
                    element
                    for element
                    in page_element.iter()
                    if local_name(
                        element.tag
                    )
                    == "word"
                ]
                if page_element
                is not None
                else []
            )

            for (
                word_index,
                word,
            ) in enumerate(words):
                word_text = (
                    word.text or ""
                ).strip()

                if not word_text:
                    continue

                append_separator(" ")

                start = sum(
                    len(piece)
                    for piece
                    in canonical_pieces
                )

                canonical_pieces.append(
                    word_text
                )

                end = (
                    start
                    + len(word_text)
                )

                bbox = {
                    "x0": float(
                        word.attrib[
                            "xMin"
                        ]
                    ),
                    "y0": float(
                        word.attrib[
                            "yMin"
                        ]
                    ),
                    "x1": float(
                        word.attrib[
                            "xMax"
                        ]
                    ),
                    "y1": float(
                        word.attrib[
                            "yMax"
                        ]
                    ),
                }

                segments.append(
                    {
                        "segment_id": (
                            segment_id(
                                artifact_id=(
                                    artifact_id
                                ),
                                page_number=(
                                    page_number
                                ),
                                word_index=(
                                    word_index
                                ),
                                text=word_text,
                                bbox=bbox,
                            )
                        ),
                        "kind": "PAGE",
                        "text": word_text,
                        "canonical_start": (
                            start
                        ),
                        "canonical_end": end,
                        "source": {
                            "page_number": (
                                page_number
                            ),
                            "source_start": (
                                None
                            ),
                            "source_end": None,
                            "bbox": bbox,
                            "xml_path": None,
                            "extraction_method": (
                                "EMBEDDED"
                            ),
                            "ocr_confidence": (
                                None
                            ),
                            "ocr_engine": None,
                            "ocr_language": None,
                            "render_dpi": None,
                        },
                    }
                )

            assessment.update(
                {
                    "execution_status": (
                        "NOT_RUN"
                    ),
                    "engine": None,
                    "engine_version": (
                        None
                    ),
                    "render_engine": None,
                    "render_engine_version": (
                        None
                    ),
                    "language": None,
                    "dpi": None,
                    "render_width_px": (
                        None
                    ),
                    "render_height_px": (
                        None
                    ),
                    "recognized_word_count": (
                        0
                    ),
                    "recognized_character_count": (
                        0
                    ),
                    "mean_confidence": None,
                }
            )

        pages.append(
            {
                "page_number": (
                    page_number
                ),
                "width": width,
                "height": height,
                "text": page_output_text,
                "text_source": text_source,
                "word_count": len(
                    re.findall(
                        r"\S+",
                        page_output_text,
                    )
                ),
                "character_count": len(
                    page_output_text.strip()
                ),
                "ocr_mean_confidence": (
                    ocr_mean_confidence
                ),
            }
        )

        ocr_assessment.append(
            assessment
        )

        if page_number < count:
            canonical_pieces.append(
                "\n\f\n"
            )

    return (
        "".join(
            canonical_pieces
        ),
        segments,
        pages,
        ocr_assessment,
    )
