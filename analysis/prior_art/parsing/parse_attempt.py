from __future__ import annotations

import hashlib
import json
import os
import tempfile

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)

from .parser_router import (
    ParserRoutingError,
    route_parser,
)


ATTEMPT_SCHEMA_VERSION = "1.0.0"

ATTEMPT_SCHEMA_PATH = (
    Path(__file__).resolve().parent
    / "schemas"
    / "parse_attempt.schema.json"
)

MAX_DIAGNOSTIC_LENGTH = 1024


@dataclass(frozen=True)
class ParseAttemptResult:
    record: dict[str, Any]
    record_path: Path
    document: dict[str, Any] | None
    output_path: Path | None


class ParseAttemptFailure(
    RuntimeError
):
    def __init__(
        self,
        *,
        original: Exception,
        result: ParseAttemptResult,
    ) -> None:
        super().__init__(
            str(original)
        )

        self.original = original
        self.result = result
        self.code = getattr(
            original,
            "code",
            type(original).__name__,
        )


def canonical_bytes(
    value: Any,
) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_path(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while True:
            chunk = handle.read(
                1024 * 1024
            )

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


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


def bounded_message(
    value: object,
) -> str:
    message = str(value)

    if len(message) <= (
        MAX_DIAGNOSTIC_LENGTH
    ):
        return message

    return message[
        : MAX_DIAGNOSTIC_LENGTH - 3
    ] + "..."


def load_manifest_context(
    manifest_path: Path,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "intake_attempt_id": None,
        "artifact_id": None,
        "content_sha256": None,
        "parser": {
            "route": None,
            "name": None,
        },
    }

    try:
        value = json.loads(
            manifest_path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return context

    if not isinstance(
        value,
        dict,
    ):
        return context

    context[
        "intake_attempt_id"
    ] = value.get(
        "intake_attempt_id"
    )

    context[
        "artifact_id"
    ] = value.get(
        "artifact_id"
    )

    context[
        "content_sha256"
    ] = value.get(
        "content_sha256"
    )

    media_type = value.get(
        "detected_media_type"
    )

    if isinstance(
        media_type,
        str,
    ):
        try:
            route = route_parser(
                media_type
            )
        except ParserRoutingError:
            pass
        else:
            context["parser"] = {
                "route": route.route,
                "name": route.parser_name,
            }

    return context


def parse_attempt_id(
    *,
    manifest_sha256: str,
    output_root: Path,
    parser_version: str,
    prior_parse_attempt_id: (
        str | None
    ),
) -> str:
    basis = {
        "manifest_sha256": (
            manifest_sha256
        ),
        "output_root": str(
            output_root.resolve()
        ),
        "parser_version": (
            parser_version
        ),
        "prior_parse_attempt_id": (
            prior_parse_attempt_id
        ),
    }

    digest = hashlib.sha256(
        canonical_bytes(
            basis
        )
    ).hexdigest()

    return f"parse:{digest}"


def attempt_record_path(
    *,
    attempt_root: Path,
    parse_attempt_id_value: str,
) -> Path:
    digest = (
        parse_attempt_id_value
        .split(":", 1)[1]
    )

    return (
        attempt_root.resolve()
        / digest[:2]
        / digest
        / "parse-attempt.json"
    )


def validate_record(
    record: dict[str, Any],
) -> None:
    schema = json.loads(
        ATTEMPT_SCHEMA_PATH.read_text(
            encoding="utf-8"
        )
    )

    validator = Draft202012Validator(
        schema,
        format_checker=(
            FormatChecker()
        ),
    )

    errors = sorted(
        validator.iter_errors(
            record
        ),
        key=lambda error: list(
            error.absolute_path
        ),
    )

    if errors:
        raise ValueError(
            "PARSE_ATTEMPT_INVALID: "
            + "; ".join(
                error.message
                for error in errors
            )
        )


def execute_parse_attempt(
    *,
    manifest_path: Path,
    output_root: Path,
    attempt_root: Path,
    parser_version: str,
    parse_function: Callable[
        [Path],
        tuple[
            dict[str, Any],
            Path,
        ],
    ],
    prior_parse_attempt_id: (
        str | None
    ) = None,
) -> ParseAttemptResult:
    resolved_manifest = (
        manifest_path.resolve()
    )

    resolved_output_root = (
        output_root.resolve()
    )

    resolved_attempt_root = (
        attempt_root.resolve()
    )

    manifest_hash = sha256_path(
        resolved_manifest
    )

    context = load_manifest_context(
        resolved_manifest
    )

    attempt_id = parse_attempt_id(
        manifest_sha256=manifest_hash,
        output_root=(
            resolved_output_root
        ),
        parser_version=(
            parser_version
        ),
        prior_parse_attempt_id=(
            prior_parse_attempt_id
        ),
    )

    record_path = attempt_record_path(
        attempt_root=(
            resolved_attempt_root
        ),
        parse_attempt_id_value=(
            attempt_id
        ),
    )

    if record_path.is_file():
        existing = json.loads(
            record_path.read_text(
                encoding="utf-8"
            )
        )

        validate_record(
            existing
        )

        if (
            existing["status"]
            == "SUCCEEDED"
        ):
            output_value = existing.get(
                "output_path"
            )

            output_path = (
                Path(output_value)
                if isinstance(
                    output_value,
                    str,
                )
                else None
            )

            document = None

            if (
                output_path is not None
                and output_path.is_file()
            ):
                loaded = json.loads(
                    output_path.read_text(
                        encoding="utf-8"
                    )
                )

                if isinstance(
                    loaded,
                    dict,
                ):
                    document = loaded

            return ParseAttemptResult(
                record=existing,
                record_path=record_path,
                document=document,
                output_path=output_path,
            )

        if existing["status"] == "FAILED":
            result = ParseAttemptResult(
                record=existing,
                record_path=record_path,
                document=None,
                output_path=None,
            )

            recorded_error = (
                existing.get("error")
                or {}
            )

            replay_error = RuntimeError(
                str(
                    recorded_error.get(
                        "message",
                        "Persisted parse attempt failed",
                    )
                )
            )

            setattr(
                replay_error,
                "code",
                recorded_error.get(
                    "code",
                    "PARSE_ATTEMPT_FAILED",
                ),
            )

            setattr(
                replay_error,
                "retryable",
                bool(
                    recorded_error.get(
                        "retryable",
                        False,
                    )
                ),
            )

            raise ParseAttemptFailure(
                original=replay_error,
                result=result,
            )

    base_record = {
        "schema_version": (
            ATTEMPT_SCHEMA_VERSION
        ),
        "parse_attempt_id": attempt_id,
        "prior_parse_attempt_id": (
            prior_parse_attempt_id
        ),
        "manifest_path": str(
            resolved_manifest
        ),
        "manifest_sha256": (
            manifest_hash
        ),
        "intake_attempt_id": (
            context[
                "intake_attempt_id"
            ]
        ),
        "artifact_id": (
            context[
                "artifact_id"
            ]
        ),
        "content_sha256": (
            context[
                "content_sha256"
            ]
        ),
        "parser": {
            "route": context[
                "parser"
            ]["route"],
            "name": context[
                "parser"
            ]["name"],
            "version": parser_version,
        },
    }

    try:
        document, output_path = (
            parse_function(
                resolved_manifest
            )
        )
    except Exception as exc:
        record = {
            **base_record,
            "status": "FAILED",
            "state_history": [
                {
                    "state": "STARTED"
                },
                {
                    "state": "FAILED"
                },
            ],
            "output_path": None,
            "document_id": None,
            "error": {
                "code": getattr(
                    exc,
                    "code",
                    type(exc).__name__,
                ),
                "message": bounded_message(
                    exc
                ),
                "retryable": bool(
                    getattr(
                        exc,
                        "retryable",
                        False,
                    )
                ),
                "exception_type": (
                    type(exc).__name__
                ),
            },
        }

        validate_record(
            record
        )

        atomic_write_json(
            record_path,
            record,
        )

        result = ParseAttemptResult(
            record=record,
            record_path=record_path,
            document=None,
            output_path=None,
        )

        raise ParseAttemptFailure(
            original=exc,
            result=result,
        ) from exc

    record = {
        **base_record,
        "status": "SUCCEEDED",
        "state_history": [
            {
                "state": "STARTED"
            },
            {
                "state": "SUCCEEDED"
            },
        ],
        "output_path": str(
            output_path.resolve()
        ),
        "document_id": document[
            "document_id"
        ],
        "error": None,
    }

    validate_record(
        record
    )

    atomic_write_json(
        record_path,
        record,
    )

    return ParseAttemptResult(
        record=record,
        record_path=record_path,
        document=document,
        output_path=output_path,
    )
