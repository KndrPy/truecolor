from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mimetypes
import os
import stat
import tempfile
import uuid
import zipfile

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO


IMPLEMENTATION_VERSION = "1.0.0"
DETECTOR_VERSION = "1.0.0"
DEFAULT_MAX_BYTES = 1024 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024
TEXT_PROBE_BYTES = 256 * 1024


class IntakeError(RuntimeError):
    """Typed artifact-intake failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
        }


@dataclass(frozen=True)
class MediaDetection:
    media_type: str
    method: str
    confidence: float
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector_version": DETECTOR_VERSION,
            "method": self.method,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class IntakeResult:
    manifest: dict[str, Any]
    manifest_path: Path
    object_path: Path


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def canonical_json_bytes(
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
                READ_CHUNK_BYTES
            )

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def _looks_like_utf8_text(
    sample: bytes,
) -> bool:
    if b"\x00" in sample:
        return False

    try:
        text = sample.decode("utf-8")
    except UnicodeDecodeError:
        return False

    if not text:
        return True

    printable = sum(
        character.isprintable()
        or character in "\r\n\t"
        for character in text
    )

    return (
        printable / len(text)
    ) >= 0.95


def _detect_structured_text(
    sample: bytes,
    original_name: str,
) -> MediaDetection:
    text = sample.decode(
        "utf-8",
        errors="strict",
    )

    stripped = text.lstrip()
    lowered = stripped[:4096].lower()

    if (
        lowered.startswith("<!doctype html")
        or lowered.startswith("<html")
        or "<body" in lowered
        or "<head" in lowered
    ):
        return MediaDetection(
            media_type="text/html",
            method="STRUCTURAL_TEXT_PROBE",
            confidence=0.98,
            evidence=(
                "HTML root or document structure detected",
            ),
        )

    suffix = Path(
        original_name
    ).suffix.lower()

    xml_declaration_present = (
        stripped.startswith(
            "<?xml"
        )
    )

    xml_filename_present = (
        suffix in {
            ".xml",
            ".jats",
            ".tei",
            ".xhtml",
        }
    )

    if stripped.startswith("<"):
        try:
            import xml.etree.ElementTree as ET

            ET.fromstring(text)

            return MediaDetection(
                media_type="application/xml",
                method="STRUCTURAL_TEXT_PROBE",
                confidence=0.98,
                evidence=(
                    "Well-formed XML document detected",
                ),
            )
        except ET.ParseError:
            if (
                xml_declaration_present
                or xml_filename_present
            ):
                evidence = []

                if xml_declaration_present:
                    evidence.append(
                        "XML declaration detected"
                    )

                if xml_filename_present:
                    evidence.append(
                        "XML-family filename suffix detected"
                    )

                evidence.append(
                    "Document is not well-formed; "
                    "validation deferred to XML parser"
                )

                return MediaDetection(
                    media_type="application/xml",
                    method="STRUCTURAL_TEXT_PROBE",
                    confidence=0.75,
                    evidence=tuple(
                        evidence
                    ),
                )

    try:
        parsed = json.loads(text)

        if isinstance(parsed, (dict, list)):
            return MediaDetection(
                media_type="application/json",
                method="STRUCTURAL_TEXT_PROBE",
                confidence=0.99,
                evidence=(
                    "Complete JSON value parsed",
                ),
            )
    except json.JSONDecodeError:
        pass

    nonempty_lines = [
        line
        for line in text.splitlines()
        if line.strip()
    ]

    if len(nonempty_lines) >= 2:
        jsonl_valid = True

        for line in nonempty_lines[:100]:
            try:
                json.loads(line)
            except json.JSONDecodeError:
                jsonl_valid = False
                break

        if jsonl_valid:
            return MediaDetection(
                media_type=(
                    "application/x-ndjson"
                ),
                method=(
                    "STRUCTURAL_TEXT_PROBE"
                ),
                confidence=0.96,
                evidence=(
                    "Multiple JSON values parsed "
                    "one per non-empty line",
                ),
            )

    if suffix in {
        ".md",
        ".markdown",
    }:
        return MediaDetection(
            media_type="text/markdown",
            method="TEXT_HEURISTIC",
            confidence=0.90,
            evidence=(
                "UTF-8 text and Markdown suffix",
            ),
        )

    if (
        "\n" in text
        and any(
            delimiter in text
            for delimiter in (
                ",",
                "\t",
                ";",
                "|",
            )
        )
    ):
        try:
            dialect = csv.Sniffer().sniff(
                text[:8192],
                delimiters=",\t;|",
            )

            rows = list(
                csv.reader(
                    text[:8192].splitlines(),
                    dialect,
                )
            )

            if (
                len(rows) >= 2
                and len(rows[0]) >= 2
                and all(
                    len(row) == len(rows[0])
                    for row in rows[:20]
                )
            ):
                delimiter = dialect.delimiter

                if delimiter == "\t":
                    media_type = (
                        "text/tab-separated-values"
                    )

                    evidence = (
                        "Consistent tab-delimited "
                        "row structure detected",
                    )

                    confidence = (
                        0.90
                        if suffix == ".tsv"
                        else 0.86
                    )
                else:
                    media_type = "text/csv"

                    evidence = (
                        "Consistent comma-delimited "
                        "or CSV-compatible row "
                        "structure detected",
                    )

                    confidence = (
                        0.90
                        if suffix == ".csv"
                        else 0.82
                    )

                return MediaDetection(
                    media_type=media_type,
                    method="TEXT_HEURISTIC",
                    confidence=confidence,
                    evidence=evidence,
                )
        except csv.Error:
            pass

    return MediaDetection(
        media_type="text/plain",
        method="TEXT_HEURISTIC",
        confidence=0.80,
        evidence=(
            "Valid predominantly printable "
            "UTF-8 text",
        ),
    )


def detect_media_type(
    path: Path,
    *,
    original_name: str | None = None,
) -> MediaDetection:
    if not path.is_file():
        raise IntakeError(
            "SOURCE_NOT_FOUND",
            f"Artifact object does not exist: {path}",
            retryable=False,
        )

    byte_length = path.stat().st_size
    display_name = (
        original_name
        if original_name is not None
        else path.name
    )

    if byte_length == 0:
        return MediaDetection(
            media_type="application/x-empty",
            method="EMPTY",
            confidence=1.0,
            evidence=(
                "Artifact contains zero bytes",
            ),
        )

    with path.open("rb") as handle:
        sample = handle.read(
            TEXT_PROBE_BYTES
        )

    if sample.startswith(b"%PDF-"):
        return MediaDetection(
            media_type="application/pdf",
            method="BYTE_SIGNATURE",
            confidence=1.0,
            evidence=(
                "PDF signature %PDF- detected",
            ),
        )

    if sample.startswith(
        b"\x1f\x8b"
    ):
        return MediaDetection(
            media_type="application/gzip",
            method="BYTE_SIGNATURE",
            confidence=1.0,
            evidence=(
                "GZIP signature 1f8b detected",
            ),
        )

    if (
        len(sample) >= 262
        and sample[257:262] == b"ustar"
    ):
        return MediaDetection(
            media_type="application/x-tar",
            method="BYTE_SIGNATURE",
            confidence=1.0,
            evidence=(
                "TAR ustar signature detected",
            ),
        )

    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(
                path,
                "r",
            ) as archive:
                names = set(
                    archive.namelist()
                )

                is_docx = (
                    "[Content_Types].xml"
                    in names
                    and "word/document.xml"
                    in names
                    and any(
                        name.startswith(
                            "word/"
                        )
                        for name in names
                    )
                )

                is_xlsx = (
                    "[Content_Types].xml"
                    in names
                    and "xl/workbook.xml"
                    in names
                    and any(
                        name.startswith(
                            "xl/worksheets/"
                        )
                        for name in names
                    )
                )

                if is_docx:
                    return MediaDetection(
                        media_type=(
                            "application/"
                            "vnd.openxmlformats-"
                            "officedocument."
                            "wordprocessingml."
                            "document"
                        ),
                        method=(
                            "ARCHIVE_STRUCTURE"
                        ),
                        confidence=1.0,
                        evidence=(
                            "ZIP container contains "
                            "DOCX content types and "
                            "word/document.xml",
                        ),
                    )

                if is_xlsx:
                    return MediaDetection(
                        media_type=(
                            "application/"
                            "vnd.openxmlformats-"
                            "officedocument."
                            "spreadsheetml."
                            "sheet"
                        ),
                        method=(
                            "ARCHIVE_STRUCTURE"
                        ),
                        confidence=1.0,
                        evidence=(
                            "ZIP container contains "
                            "XLSX workbook and "
                            "worksheet members",
                        ),
                    )

        except (
            OSError,
            zipfile.BadZipFile,
        ):
            pass

        return MediaDetection(
            media_type="application/zip",
            method="BYTE_SIGNATURE",
            confidence=1.0,
            evidence=(
                "Valid ZIP container detected",
            ),
        )

    if _looks_like_utf8_text(
        sample
    ):
        return _detect_structured_text(
            sample,
            display_name,
        )

    guessed, _ = mimetypes.guess_type(
        display_name
    )

    if guessed is not None:
        return MediaDetection(
            media_type=guessed,
            method="UNKNOWN",
            confidence=0.25,
            evidence=(
                "No supported byte signature; "
                "low-confidence filename guess",
            ),
        )

    return MediaDetection(
        media_type=(
            "application/octet-stream"
        ),
        method="UNKNOWN",
        confidence=0.0,
        evidence=(
            "No supported signature or "
            "text structure detected",
        ),
    )


def _atomic_write_json(
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
            "wb",
        ) as handle:
            payload = (
                json.dumps(
                    value,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n"
            ).encode("utf-8")

            handle.write(payload)
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


def _copy_hash_to_temporary(
    source: Path,
    temporary_path: Path,
    *,
    max_bytes: int,
) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_length = 0

    with (
        source.open("rb") as source_handle,
        temporary_path.open(
            "xb"
        ) as destination_handle,
    ):
        while True:
            chunk = source_handle.read(
                READ_CHUNK_BYTES
            )

            if not chunk:
                break

            byte_length += len(chunk)

            if byte_length > max_bytes:
                raise IntakeError(
                    "SIZE_LIMIT_EXCEEDED",
                    (
                        "Artifact exceeded "
                        f"{max_bytes} bytes"
                    ),
                    retryable=False,
                )

            digest.update(chunk)
            destination_handle.write(
                chunk
            )

        destination_handle.flush()
        os.fsync(
            destination_handle.fileno()
        )

    return (
        digest.hexdigest(),
        byte_length,
    )


def ingest_file(
    source: Path,
    *,
    store_root: Path,
    manifest_root: Path,
    original_name: str | None = None,
    declared_media_type: str | None = None,
    source_uri: str | None = None,
    expected_sha256: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> IntakeResult:
    source = source.resolve()

    if not source.is_file():
        raise IntakeError(
            "SOURCE_NOT_FOUND",
            f"Source file does not exist: {source}",
            retryable=False,
        )

    if max_bytes < 0:
        raise IntakeError(
            "INVALID_MAX_BYTES",
            "max_bytes cannot be negative",
            retryable=False,
        )

    intake_attempt_id = (
        f"intake:{uuid.uuid4().hex}"
    )

    received_at = utc_now()

    store_root = store_root.resolve()
    manifest_root = (
        manifest_root.resolve()
    )

    temporary_root = (
        store_root / ".tmp"
    )

    temporary_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = (
        temporary_root
        / f"{uuid.uuid4().hex}.partial"
    )

    try:
        content_sha256, byte_length = (
            _copy_hash_to_temporary(
                source,
                temporary_path,
                max_bytes=max_bytes,
            )
        )

        if (
            expected_sha256 is not None
            and content_sha256
            != expected_sha256.lower()
        ):
            raise IntakeError(
                "CHECKSUM_MISMATCH",
                (
                    "Expected SHA-256 "
                    f"{expected_sha256.lower()} "
                    "but observed "
                    f"{content_sha256}"
                ),
                retryable=False,
            )

        object_relative_path = Path(
            "objects"
        ) / "sha256" / (
            content_sha256[:2]
        ) / (
            content_sha256[2:4]
        ) / (
            f"{content_sha256}.blob"
        )

        object_path = (
            store_root
            / object_relative_path
        )

        object_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        deduplicated = False

        try:
            os.link(
                temporary_path,
                object_path,
            )
        except FileExistsError:
            deduplicated = True

            observed_existing_hash = (
                sha256_path(
                    object_path
                )
            )

            if (
                observed_existing_hash
                != content_sha256
            ):
                raise IntakeError(
                    "OBJECT_INTEGRITY_FAILURE",
                    (
                        "Existing content-addressed "
                        "object does not match its "
                        "path hash"
                    ),
                    retryable=False,
                )
        finally:
            temporary_path.unlink(
                missing_ok=True
            )

        if not deduplicated:
            object_path.chmod(
                stat.S_IRUSR
                | stat.S_IRGRP
                | stat.S_IROTH
            )

        detection = detect_media_type(
            object_path,
            original_name=(
                original_name
                if original_name is not None
                else source.name
            ),
        )

        hashed_at = utc_now()
        detected_at = utc_now()
        stored_at = utc_now()

        normalized_declared = (
            declared_media_type.lower()
            if declared_media_type
            is not None
            else None
        )

        manifest = {
            "schema_version": "1.0.0",
            "artifact_id": (
                "artifact:sha256:"
                f"{content_sha256}"
            ),
            "intake_attempt_id": (
                intake_attempt_id
            ),
            "content_sha256": (
                content_sha256
            ),
            "byte_length": byte_length,
            "original_name": (
                original_name
                if original_name is not None
                else source.name
            ),
            "source_uri": source_uri,
            "declared_media_type": (
                normalized_declared
            ),
            "detected_media_type": (
                detection.media_type
            ),
            "media_type_mismatch": (
                normalized_declared
                is not None
                and normalized_declared
                != detection.media_type
            ),
            "media_detection": (
                detection.to_dict()
            ),
            "storage": {
                "object_path": str(
                    object_path
                ),
                "object_relative_path": (
                    object_relative_path.as_posix()
                ),
                "deduplicated": (
                    deduplicated
                ),
                "immutable": True,
            },
            "ingested_at": stored_at,
            "status": (
                "STORED_IMMUTABLY"
            ),
            "state_history": [
                {
                    "state": "RECEIVED",
                    "occurred_at": (
                        received_at
                    ),
                },
                {
                    "state": "HASHED",
                    "occurred_at": (
                        hashed_at
                    ),
                },
                {
                    "state": (
                        "MEDIA_TYPE_DETECTED"
                    ),
                    "occurred_at": (
                        detected_at
                    ),
                },
                {
                    "state": (
                        "STORED_IMMUTABLY"
                    ),
                    "occurred_at": (
                        stored_at
                    ),
                },
            ],
            "implementation": {
                "module": (
                    "analysis.prior_art."
                    "ingestion."
                    "artifact_intake"
                ),
                "version": (
                    IMPLEMENTATION_VERSION
                ),
            },
        }

        manifest_path = (
            manifest_root
            / content_sha256[:2]
            / content_sha256
            / (
                intake_attempt_id
                .replace(":", "_")
                + ".json"
            )
        )

        _atomic_write_json(
            manifest_path,
            manifest,
        )

        return IntakeResult(
            manifest=manifest,
            manifest_path=(
                manifest_path
            ),
            object_path=object_path,
        )

    finally:
        temporary_path.unlink(
            missing_ok=True
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Persist one prior-art artifact "
            "into the immutable local "
            "content-addressed store."
        )
    )

    parser.add_argument(
        "--source",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--store-root",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--manifest-root",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--original-name",
    )

    parser.add_argument(
        "--declared-media-type",
    )

    parser.add_argument(
        "--source-uri",
    )

    parser.add_argument(
        "--expected-sha256",
    )

    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        result = ingest_file(
            args.source,
            store_root=args.store_root,
            manifest_root=(
                args.manifest_root
            ),
            original_name=(
                args.original_name
            ),
            declared_media_type=(
                args.declared_media_type
            ),
            source_uri=(
                args.source_uri
            ),
            expected_sha256=(
                args.expected_sha256
            ),
            max_bytes=args.max_bytes,
        )
    except IntakeError as exc:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "failure": (
                        exc.to_dict()
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )

        return 1

    print(
        json.dumps(
            {
                "status": (
                    "STORED_IMMUTABLY"
                ),
                "artifact_id": (
                    result.manifest[
                        "artifact_id"
                    ]
                ),
                "content_sha256": (
                    result.manifest[
                        "content_sha256"
                    ]
                ),
                "byte_length": (
                    result.manifest[
                        "byte_length"
                    ]
                ),
                "detected_media_type": (
                    result.manifest[
                        "detected_media_type"
                    ]
                ),
                "deduplicated": (
                    result.manifest[
                        "storage"
                    ][
                        "deduplicated"
                    ]
                ),
                "object_path": str(
                    result.object_path
                ),
                "manifest_path": str(
                    result.manifest_path
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
