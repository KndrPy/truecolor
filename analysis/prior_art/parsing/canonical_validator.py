from __future__ import annotations

import hashlib
import json

from pathlib import Path
from typing import Any

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)


ROOT = Path(__file__).resolve().parent

SCHEMA_PATH = (
    ROOT
    / "schemas"
    / "canonical_document.schema.json"
)

TABULAR_ROUTES = {
    "DOCX",
    "CSV",
    "TSV",
    "XLSX",
}


class CanonicalInvariantError(
    RuntimeError
):
    def __init__(
        self,
        errors: list[str],
    ) -> None:
        super().__init__(
            "; ".join(errors)
        )

        self.errors = errors


def canonical_bytes(
    value: Any,
) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def recompute_document_id(
    document: dict[str, Any],
) -> str:
    basis = {
        "artifact_id": document[
            "artifact_id"
        ],
        "content_sha256": document[
            "content_sha256"
        ],
        "source_media_type": document[
            "source_media_type"
        ],
        "parser_route": document[
            "parser"
        ]["route"],
        "text": document["text"],
        "segments": document[
            "segments"
        ],
        "pages": document["pages"],
        "tables": document["tables"],
        "ocr_assessment": document[
            "ocr_assessment"
        ],
    }

    digest = hashlib.sha256(
        canonical_bytes(
            basis
        )
    ).hexdigest()

    return (
        "document:sha256:"
        + digest
    )


def schema_errors(
    document: dict[str, Any],
) -> list[str]:
    schema = json.loads(
        SCHEMA_PATH.read_text(
            encoding="utf-8"
        )
    )

    validator = Draft202012Validator(
        schema,
        format_checker=(
            FormatChecker()
        ),
    )

    return [
        (
            "SCHEMA:"
            + "/".join(
                str(part)
                for part
                in error.absolute_path
            )
            + ":"
            + error.message
        )
        for error in sorted(
            validator.iter_errors(
                document
            ),
            key=lambda item: list(
                item.absolute_path
            ),
        )
    ]


def validate_segments(
    document: dict[str, Any],
    *,
    errors: list[str],
) -> None:
    text = document["text"]
    segments = document[
        "segments"
    ]

    segment_ids: set[str] = set()
    prior_end = 0

    for index, segment in enumerate(
        segments
    ):
        segment_id = segment[
            "segment_id"
        ]

        if segment_id in segment_ids:
            errors.append(
                f"SEGMENT_ID_DUPLICATE:{index}"
            )

        segment_ids.add(
            segment_id
        )

        start = segment[
            "canonical_start"
        ]

        end = segment[
            "canonical_end"
        ]

        if start > end:
            errors.append(
                f"SEGMENT_RANGE_REVERSED:{index}"
            )

        if (
            start < 0
            or end > len(text)
        ):
            errors.append(
                f"SEGMENT_RANGE_OUTSIDE_TEXT:{index}"
            )

        elif text[start:end] != segment[
            "text"
        ]:
            errors.append(
                f"SEGMENT_RANGE_TEXT_MISMATCH:{index}"
            )

        if index and start < prior_end:
            errors.append(
                f"SEGMENT_OVERLAP:{index}"
            )

        prior_end = max(
            prior_end,
            end,
        )


def validate_pdf(
    document: dict[str, Any],
    *,
    errors: list[str],
) -> None:
    pages = document["pages"]
    assessments = document[
        "ocr_assessment"
    ]

    expected_numbers = list(
        range(
            1,
            len(pages) + 1,
        )
    )

    observed_page_numbers = [
        page["page_number"]
        for page in pages
    ]

    if observed_page_numbers != (
        expected_numbers
    ):
        errors.append(
            "PDF_PAGE_NUMBERS_NOT_CONTIGUOUS"
        )

    if len(pages) != len(
        assessments
    ):
        errors.append(
            "PDF_ASSESSMENT_COUNT_MISMATCH"
        )

    assessment_by_page = {
        assessment["page_number"]:
        assessment
        for assessment in assessments
    }

    page_numbers = set(
        expected_numbers
    )

    for index, segment in enumerate(
        document["segments"]
    ):
        source = segment[
            "source"
        ]

        page_number = source.get(
            "page_number"
        )

        if page_number not in (
            page_numbers
        ):
            errors.append(
                f"PDF_SEGMENT_PAGE_INVALID:{index}"
            )

        if source.get(
            "bbox"
        ) is None:
            errors.append(
                f"PDF_SEGMENT_BBOX_MISSING:{index}"
            )

    for page in pages:
        number = page[
            "page_number"
        ]

        assessment = (
            assessment_by_page.get(
                number
            )
        )

        if assessment is None:
            continue

        text_source = page[
            "text_source"
        ]

        if text_source == "OCR":
            if (
                assessment[
                    "execution_status"
                ]
                != "SUCCEEDED"
            ):
                errors.append(
                    f"OCR_EXECUTION_NOT_SUCCEEDED:{number}"
                )

            if page[
                "ocr_mean_confidence"
            ] is None:
                errors.append(
                    f"OCR_PAGE_CONFIDENCE_MISSING:{number}"
                )

            if assessment[
                "mean_confidence"
            ] is None:
                errors.append(
                    f"OCR_ASSESSMENT_CONFIDENCE_MISSING:{number}"
                )

        elif text_source == "EMBEDDED":
            if page[
                "ocr_mean_confidence"
            ] is not None:
                errors.append(
                    f"EMBEDDED_PAGE_HAS_OCR_CONFIDENCE:{number}"
                )

            if assessment[
                "execution_status"
            ] != "NOT_RUN":
                errors.append(
                    f"EMBEDDED_PAGE_EXECUTED_OCR:{number}"
                )


def validate_tables(
    document: dict[str, Any],
    *,
    errors: list[str],
) -> None:
    route = document[
        "parser"
    ]["route"]

    tables = document[
        "tables"
    ]

    table_ids: set[str] = set()

    expected_indexes = list(
        range(
            len(tables)
        )
    )

    observed_indexes = [
        table["table_index"]
        for table in tables
    ]

    if observed_indexes != (
        expected_indexes
    ):
        errors.append(
            "TABLE_INDEXES_NOT_CONTIGUOUS"
        )

    table_cells: set[
        tuple[
            int,
            int,
            int,
            str,
        ]
    ] = set()

    for table_position, table in enumerate(
        tables
    ):
        table_id = table[
            "table_id"
        ]

        if table_id in table_ids:
            errors.append(
                f"TABLE_ID_DUPLICATE:{table_position}"
            )

        table_ids.add(
            table_id
        )

        if table[
            "source_kind"
        ] != route:
            errors.append(
                f"TABLE_SOURCE_ROUTE_MISMATCH:{table_position}"
            )

        rows = table[
            "rows"
        ]

        if table[
            "row_count"
        ] != len(rows):
            errors.append(
                f"TABLE_ROW_COUNT_MISMATCH:{table_position}"
            )

        expected_rows = list(
            range(
                1,
                len(rows) + 1,
            )
        )

        observed_rows = [
            row["row_index"]
            for row in rows
        ]

        if observed_rows != (
            expected_rows
        ):
            errors.append(
                f"TABLE_ROWS_NOT_CONTIGUOUS:{table_position}"
            )

        maximum_columns = max(
            (
                len(
                    row["cells"]
                )
                for row in rows
            ),
            default=0,
        )

        if table[
            "column_count"
        ] != maximum_columns:
            errors.append(
                f"TABLE_COLUMN_COUNT_MISMATCH:{table_position}"
            )

        references: set[str] = set()

        for row in rows:
            cells = row[
                "cells"
            ]

            observed_columns = [
                cell[
                    "column_index"
                ]
                for cell in cells
            ]

            expected_columns = list(
                range(
                    1,
                    len(cells) + 1,
                )
            )

            if observed_columns != (
                expected_columns
            ):
                errors.append(
                    (
                        "TABLE_COLUMNS_NOT_CONTIGUOUS:"
                        f"{table_position}:"
                        f"{row['row_index']}"
                    )
                )

            for cell in cells:
                reference = cell[
                    "cell_reference"
                ]

                if reference in references:
                    errors.append(
                        (
                            "TABLE_CELL_REFERENCE_DUPLICATE:"
                            f"{table_position}:"
                            f"{reference}"
                        )
                    )

                references.add(
                    reference
                )

                table_cells.add(
                    (
                        table[
                            "table_index"
                        ],
                        row[
                            "row_index"
                        ],
                        cell[
                            "column_index"
                        ],
                        reference,
                    )
                )

    for index, segment in enumerate(
        document["segments"]
    ):
        if segment[
            "kind"
        ] != "TABLE_CELL":
            continue

        source = segment[
            "source"
        ]

        identity = (
            source.get(
                "table_index"
            ),
            source.get(
                "row_index"
            ),
            source.get(
                "column_index"
            ),
            source.get(
                "cell_reference"
            ),
        )

        if identity not in (
            table_cells
        ):
            errors.append(
                f"TABLE_CELL_PROVENANCE_INVALID:{index}"
            )


def validate_route_collections(
    document: dict[str, Any],
    *,
    errors: list[str],
) -> None:
    route = document[
        "parser"
    ]["route"]

    if route != "PDF":
        if document["pages"]:
            errors.append(
                "NON_PDF_HAS_PAGES"
            )

        if document[
            "ocr_assessment"
        ]:
            errors.append(
                "NON_PDF_HAS_OCR_ASSESSMENT"
            )

    if route not in TABULAR_ROUTES:
        if document["tables"]:
            errors.append(
                "NON_TABULAR_HAS_TABLES"
            )


def prose_projection(
    document: dict[str, Any],
) -> tuple[str, ...]:
    route = document[
        "parser"
    ]["route"]

    if route == "TEXT":
        return tuple(
            block.strip()
            for block in document[
                "text"
            ].split("\n\n")
            if block.strip()
        )

    projected = tuple(
        str(
            segment["text"]
        ).strip()
        for segment in document[
            "segments"
        ]
        if str(
            segment["text"]
        ).strip()
    )

    if route == "MARKDOWN":
        normalized: list[str] = []

        for value in projected:
            heading = value.lstrip()

            while (
                heading.startswith("#")
            ):
                heading = heading[1:]

            normalized.append(
                heading.strip()
            )

        return tuple(
            value
            for value in normalized
            if value
        )

    return projected


def validate_canonical_document(
    document: dict[str, Any],
) -> None:
    errors = schema_errors(
        document
    )

    content_sha256 = document.get(
        "content_sha256"
    )

    if document.get(
        "artifact_id"
    ) != (
        "artifact:sha256:"
        + str(content_sha256)
    ):
        errors.append(
            "ARTIFACT_CONTENT_ID_MISMATCH"
        )

    try:
        expected_document_id = (
            recompute_document_id(
                document
            )
        )
    except (
        KeyError,
        TypeError,
    ):
        expected_document_id = None

    if (
        expected_document_id
        is not None
        and document.get(
            "document_id"
        )
        != expected_document_id
    ):
        errors.append(
            "DOCUMENT_ID_MISMATCH"
        )

    try:
        validate_segments(
            document,
            errors=errors,
        )

        validate_route_collections(
            document,
            errors=errors,
        )

        route = document[
            "parser"
        ]["route"]

        if route == "PDF":
            validate_pdf(
                document,
                errors=errors,
            )

        if route in TABULAR_ROUTES:
            validate_tables(
                document,
                errors=errors,
            )

    except (
        KeyError,
        TypeError,
    ) as exc:
        errors.append(
            "INVARIANT_STRUCTURE_ERROR:"
            + type(exc).__name__
        )

    if errors:
        raise CanonicalInvariantError(
            errors
        )
