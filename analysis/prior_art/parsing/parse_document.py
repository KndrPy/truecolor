from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile

from pathlib import Path
from typing import Any

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)

from .parser_router import (
    ParserRoutingError,
    route_parser,
)

from .pdf_parser import (
    PDFParseError,
    parse_pdf,
)

from .text_parser import (
    parse_text,
)

from .xml_parser import (
    parse_html,
    parse_xml,
)

from .docx_parser import (
    DOCXParseError,
    parse_docx,
)

from .tabular_parser import (
    TabularParseError,
    parse_delimited,
    parse_xlsx,
)

from .parse_attempt import (
    ParseAttemptFailure,
    execute_parse_attempt,
)


VERSION = "1.0.0"

ROOT = Path(
    "analysis/prior_art/parsing"
)

SCHEMA_PATH = (
    ROOT
    / "schemas"
    / "canonical_document.schema.json"
)


class DocumentParseError(
    RuntimeError
):
    def __init__(
        self,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


def load_json(
    path: Path,
) -> dict[str, Any]:
    value = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(value, dict):
        raise DocumentParseError(
            "INVALID_JSON_OBJECT",
            str(path),
        )

    return value


def canonical_bytes(
    value: Any,
) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def atomic_write_json(
    path: Path,
    value: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    descriptor, temporary_name = (
        tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
    )

    temporary_path = Path(
        temporary_name
    )

    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                value,
                handle,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )

            handle.write("\n")
            handle.flush()
            os.fsync(
                handle.fileno()
            )

        os.replace(
            temporary_path,
            path,
        )
    finally:
        temporary_path.unlink(
            missing_ok=True
        )


def parse_intake_manifest(
    manifest_path: Path,
    *,
    output_root: Path,
) -> tuple[
    dict[str, Any],
    Path,
]:
    manifest = load_json(
        manifest_path
    )

    object_path = Path(
        manifest[
            "storage"
        ][
            "object_path"
        ]
    )

    if not object_path.is_file():
        raise DocumentParseError(
            "SOURCE_OBJECT_MISSING",
            str(object_path),
        )

    media_type = manifest[
        "detected_media_type"
    ]

    route = route_parser(
        media_type
    )

    artifact_id = manifest[
        "artifact_id"
    ]

    content_sha256 = manifest[
        "content_sha256"
    ]

    pages: list[
        dict[str, Any]
    ] = []

    tables: list[
        dict[str, Any]
    ] = []

    ocr_assessment: list[
        dict[str, Any]
    ] = []

    if route.route == "PDF":
        (
            text,
            segments,
            pages,
            ocr_assessment,
        ) = parse_pdf(
            object_path,
            artifact_id=artifact_id,
        )

    elif route.route == "XML":
        text, segments = parse_xml(
            object_path,
            artifact_id=artifact_id,
        )

    elif route.route == "HTML":
        text, segments = parse_html(
            object_path,
            artifact_id=artifact_id,
        )

    elif route.route in {
        "TEXT",
        "MARKDOWN",
    }:
        text, segments = parse_text(
            object_path,
            artifact_id=artifact_id,
            markdown=(
                route.route
                == "MARKDOWN"
            ),
        )

    elif route.route == "DOCX":
        (
            text,
            segments,
            tables,
        ) = parse_docx(
            object_path,
            artifact_id=artifact_id,
        )

    elif route.route == "CSV":
        (
            text,
            segments,
            tables,
        ) = parse_delimited(
            object_path,
            artifact_id=artifact_id,
            delimiter=",",
            source_kind="CSV",
        )

    elif route.route == "TSV":
        (
            text,
            segments,
            tables,
        ) = parse_delimited(
            object_path,
            artifact_id=artifact_id,
            delimiter="\t",
            source_kind="TSV",
        )

    elif route.route == "XLSX":
        (
            text,
            segments,
            tables,
        ) = parse_xlsx(
            object_path,
            artifact_id=artifact_id,
        )

    else:
        raise DocumentParseError(
            "ROUTE_NOT_IMPLEMENTED",
            route.route,
        )

    basis = {
        "artifact_id": artifact_id,
        "content_sha256": (
            content_sha256
        ),
        "source_media_type": (
            media_type
        ),
        "parser_route": (
            route.route
        ),
        "text": text,
        "segments": segments,
        "pages": pages,
        "tables": tables,
        "ocr_assessment": (
            ocr_assessment
        ),
    }

    document_hash = hashlib.sha256(
        canonical_bytes(
            basis
        )
    ).hexdigest()

    document = {
        "schema_version": "1.0.0",
        "document_id": (
            "document:sha256:"
            f"{document_hash}"
        ),
        "artifact_id": artifact_id,
        "content_sha256": (
            content_sha256
        ),
        "source_media_type": (
            media_type
        ),
        "parser": {
            "name": (
                route.parser_name
            ),
            "version": VERSION,
            "route": route.route,
        },
        "text": text,
        "segments": segments,
        "pages": pages,
        "tables": tables,
        "ocr_assessment": (
            ocr_assessment
        ),
        "status": "PARSED",
    }

    schema = load_json(
        SCHEMA_PATH
    )

    validator = Draft202012Validator(
        schema,
        format_checker=(
            FormatChecker()
        ),
    )

    errors = list(
        validator.iter_errors(
            document
        )
    )

    if errors:
        raise DocumentParseError(
            "CANONICAL_DOCUMENT_INVALID",
            "; ".join(
                error.message
                for error in errors
            ),
        )

    output = (
        output_root.resolve()
        / content_sha256[:2]
        / content_sha256
        / (
            document_hash
            + ".canonical.json"
        )
    )

    atomic_write_json(
        output,
        document,
    )

    return document, output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--attempt-root",
        type=Path,
        default=None,
    )

    parser.add_argument(
        "--prior-parse-attempt-id",
        default=None,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    attempt_root = (
        args.attempt_root
        if args.attempt_root
        is not None
        else (
            args.output_root
            / "_parse_attempts"
        )
    )

    try:
        result = execute_parse_attempt(
            manifest_path=args.manifest,
            output_root=args.output_root,
            attempt_root=attempt_root,
            parser_version=VERSION,
            prior_parse_attempt_id=(
                args.prior_parse_attempt_id
            ),
            parse_function=(
                lambda manifest_path:
                parse_intake_manifest(
                    manifest_path,
                    output_root=(
                        args.output_root
                    ),
                )
            ),
        )
    except ParseAttemptFailure as exc:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "parse_attempt_id": (
                        exc.result.record[
                            "parse_attempt_id"
                        ]
                    ),
                    "attempt_record": str(
                        exc.result.record_path
                    ),
                    "failure": (
                        exc.result.record[
                            "error"
                        ]
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )

        return 1
    except (
        OSError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "failure": {
                        "code": getattr(
                            exc,
                            "code",
                            type(exc).__name__,
                        ),
                        "message": str(exc),
                    },
                },
                indent=2,
                sort_keys=True,
            )
        )

        return 1

    document = result.document

    if document is None:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "parse_attempt_id": (
                        result.record[
                            "parse_attempt_id"
                        ]
                    ),
                    "attempt_record": str(
                        result.record_path
                    ),
                    "failure": {
                        "code": (
                            "IDEMPOTENT_OUTPUT_MISSING"
                        ),
                        "message": (
                            "Succeeded parse attempt "
                            "references a missing or "
                            "invalid canonical output"
                        ),
                    },
                },
                indent=2,
                sort_keys=True,
            )
        )

        return 1

    print(
        json.dumps(
            {
                "status": "PARSED",
                "parse_attempt_id": (
                    result.record[
                        "parse_attempt_id"
                    ]
                ),
                "attempt_record": str(
                    result.record_path
                ),
                "document_id": (
                    document[
                        "document_id"
                    ]
                ),
                "route": (
                    document[
                        "parser"
                    ][
                        "route"
                    ]
                ),
                "segment_count": len(
                    document[
                        "segments"
                    ]
                ),
                "page_count": len(
                    document[
                        "pages"
                    ]
                ),
                "output": str(
                    result.output_path
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
