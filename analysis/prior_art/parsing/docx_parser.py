from __future__ import annotations

import hashlib
import zipfile
import xml.etree.ElementTree as ET

from pathlib import Path
from typing import Any


WORD_NS = (
    "http://schemas.openxmlformats.org/"
    "wordprocessingml/2006/main"
)

W = f"{{{WORD_NS}}}"


class DOCXParseError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


def canonical_hash(
    *values: object,
) -> str:
    payload = "\n".join(
        str(value)
        for value in values
    ).encode("utf-8")

    return hashlib.sha256(
        payload
    ).hexdigest()


def source_record(
    *,
    paragraph_index: int | None = None,
    table_index: int | None = None,
    row_index: int | None = None,
    column_index: int | None = None,
    cell_reference: str | None = None,
) -> dict[str, Any]:
    return {
        "page_number": None,
        "source_start": None,
        "source_end": None,
        "bbox": None,
        "xml_path": None,
        "document_part": (
            "word/document.xml"
        ),
        "paragraph_index": (
            paragraph_index
        ),
        "table_index": table_index,
        "sheet_name": None,
        "row_index": row_index,
        "column_index": (
            column_index
        ),
        "cell_reference": (
            cell_reference
        ),
    }


def element_text(
    element: ET.Element,
) -> str:
    pieces = []

    for node in element.iter():
        if node.tag == f"{W}t":
            pieces.append(
                node.text or ""
            )
        elif node.tag == f"{W}tab":
            pieces.append("\t")
        elif node.tag == f"{W}br":
            pieces.append("\n")

    return "".join(pieces).strip()


def append_segment(
    *,
    pieces: list[str],
    segments: list[dict[str, Any]],
    artifact_id: str,
    kind: str,
    text: str,
    source: dict[str, Any],
) -> None:
    if not text:
        return

    if pieces:
        pieces.append("\n\n")

    start = sum(
        len(piece)
        for piece in pieces
    )

    pieces.append(text)
    end = start + len(text)

    segment_hash = canonical_hash(
        artifact_id,
        kind,
        start,
        end,
        text,
        source,
    )

    segments.append(
        {
            "segment_id": (
                f"segment:{segment_hash}"
            ),
            "kind": kind,
            "text": text,
            "canonical_start": start,
            "canonical_end": end,
            "source": source,
        }
    )


def parse_docx(
    path: Path,
    *,
    artifact_id: str,
) -> tuple[
    str,
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    try:
        with zipfile.ZipFile(
            path,
            "r",
        ) as archive:
            names = set(
                archive.namelist()
            )

            if (
                "word/document.xml"
                not in names
            ):
                raise DOCXParseError(
                    "DOCX_DOCUMENT_PART_MISSING",
                    "word/document.xml",
                )

            payload = archive.read(
                "word/document.xml"
            )

    except zipfile.BadZipFile as exc:
        raise DOCXParseError(
            "DOCX_CONTAINER_INVALID",
            str(path),
        ) from exc

    try:
        root = ET.fromstring(
            payload
        )
    except ET.ParseError as exc:
        raise DOCXParseError(
            "DOCX_XML_INVALID",
            "word/document.xml",
        ) from exc

    body = root.find(
        f".//{W}body"
    )

    if body is None:
        raise DOCXParseError(
            "DOCX_BODY_MISSING",
            "word/document.xml",
        )

    pieces: list[str] = []
    segments: list[
        dict[str, Any]
    ] = []
    tables: list[
        dict[str, Any]
    ] = []

    paragraph_index = 0
    table_index = 0

    for child in list(body):
        if child.tag == f"{W}p":
            text = element_text(
                child
            )

            append_segment(
                pieces=pieces,
                segments=segments,
                artifact_id=(
                    artifact_id
                ),
                kind="PARAGRAPH",
                text=text,
                source=source_record(
                    paragraph_index=(
                        paragraph_index
                    ),
                ),
            )

            paragraph_index += 1

        elif child.tag == f"{W}tbl":
            table_rows = []
            maximum_columns = 0

            for row_offset, row in enumerate(
                child.findall(
                    f"./{W}tr"
                ),
                start=1,
            ):
                cells = []

                for column_offset, cell in enumerate(
                    row.findall(
                        f"./{W}tc"
                    ),
                    start=1,
                ):
                    value = element_text(
                        cell
                    )

                    cell_reference = (
                        f"R{row_offset}"
                        f"C{column_offset}"
                    )

                    cells.append(
                        {
                            "column_index": (
                                column_offset
                            ),
                            "cell_reference": (
                                cell_reference
                            ),
                            "value": value,
                            "value_type": (
                                "STRING"
                                if value
                                else "EMPTY"
                            ),
                        }
                    )

                    append_segment(
                        pieces=pieces,
                        segments=segments,
                        artifact_id=(
                            artifact_id
                        ),
                        kind="TABLE_CELL",
                        text=value,
                        source=source_record(
                            table_index=(
                                table_index
                            ),
                            row_index=(
                                row_offset
                            ),
                            column_index=(
                                column_offset
                            ),
                            cell_reference=(
                                cell_reference
                            ),
                        ),
                    )

                maximum_columns = max(
                    maximum_columns,
                    len(cells),
                )

                table_rows.append(
                    {
                        "row_index": (
                            row_offset
                        ),
                        "cells": cells,
                    }
                )

            table_hash = canonical_hash(
                artifact_id,
                "DOCX",
                table_index,
                table_rows,
            )

            tables.append(
                {
                    "table_id": (
                        f"table:{table_hash}"
                    ),
                    "source_kind": "DOCX",
                    "name": None,
                    "table_index": (
                        table_index
                    ),
                    "row_count": len(
                        table_rows
                    ),
                    "column_count": (
                        maximum_columns
                    ),
                    "rows": table_rows,
                }
            )

            table_index += 1

    return (
        "".join(pieces),
        segments,
        tables,
    )
