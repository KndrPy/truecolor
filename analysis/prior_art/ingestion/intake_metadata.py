from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)


IMPLEMENTATION_VERSION = "1.0.0"

ACCESS_STATUSES = {
    "AVAILABLE",
    "AUTH_REQUIRED",
    "MISSING",
    "BLOCKED",
    "EXPIRED",
    "UNKNOWN",
}

LICENSE_STATUSES = {
    "PUBLIC_DOMAIN",
    "OPEN_LICENSE",
    "RESTRICTED",
    "USER_PROVIDED",
    "PROHIBITED",
    "UNKNOWN",
}

ROOT = Path(
    "analysis/prior_art/ingestion"
)

SCHEMA_PATH = (
    ROOT
    / "schemas"
    / "intake_metadata.schema.json"
)


class MetadataError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_json(
    path: Path,
) -> dict[str, Any]:
    value = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(value, dict):
        raise MetadataError(
            "INVALID_JSON_OBJECT",
            f"Expected JSON object: {path}",
        )

    return value


def canonical_json_bytes(
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

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
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
            os.fsync(handle.fileno())

        os.replace(
            temporary_path,
            path,
        )
    finally:
        temporary_path.unlink(
            missing_ok=True
        )


def record_metadata(
    intake_manifest_path: Path,
    *,
    metadata_root: Path,
    access_status: str,
    license_status: str,
    provider: str | None = None,
    retrieved_at: str | None = None,
    parent_artifact_id: str | None = None,
    root_artifact_id: str | None = None,
    archive_member_path: str | None = None,
    archive_depth: int = 0,
    expansion_id: str | None = None,
    policy_note: str | None = None,
) -> tuple[dict[str, Any], Path]:
    manifest = load_json(
        intake_manifest_path
    )

    if access_status not in ACCESS_STATUSES:
        raise MetadataError(
            "INVALID_ACCESS_STATUS",
            access_status,
        )

    if license_status not in LICENSE_STATUSES:
        raise MetadataError(
            "INVALID_LICENSE_STATUS",
            license_status,
        )

    if archive_depth < 0:
        raise MetadataError(
            "INVALID_ARCHIVE_DEPTH",
            str(archive_depth),
        )

    artifact_id = manifest[
        "artifact_id"
    ]

    intake_attempt_id = manifest[
        "intake_attempt_id"
    ]

    source_uri = manifest.get(
        "source_uri"
    )

    processing_allowed = (
        access_status == "AVAILABLE"
        and license_status
        != "PROHIBITED"
    )

    basis = {
        "artifact_id": artifact_id,
        "intake_attempt_id": (
            intake_attempt_id
        ),
        "access_status": access_status,
        "license_status": license_status,
        "source": {
            "source_uri": source_uri,
            "provider": provider,
            "retrieved_at": retrieved_at,
        },
        "lineage": {
            "parent_artifact_id": (
                parent_artifact_id
            ),
            "root_artifact_id": (
                root_artifact_id
            ),
            "archive_member_path": (
                archive_member_path
            ),
            "archive_depth": (
                archive_depth
            ),
            "expansion_id": expansion_id,
        },
        "policy_note": policy_note,
    }

    metadata_hash = hashlib.sha256(
        canonical_json_bytes(
            basis
        )
    ).hexdigest()

    record = {
        "schema_version": "1.0.0",
        "metadata_id": (
            f"metadata:{metadata_hash}"
        ),
        **basis,
        "processing_allowed": (
            processing_allowed
        ),
        "recorded_at": utc_now(),
        "implementation": {
            "module": (
                "analysis.prior_art."
                "ingestion."
                "intake_metadata"
            ),
            "version": (
                IMPLEMENTATION_VERSION
            ),
        },
    }

    schema = load_json(
        SCHEMA_PATH
    )

    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )

    errors = list(
        validator.iter_errors(
            record
        )
    )

    if errors:
        raise MetadataError(
            "METADATA_SCHEMA_INVALID",
            "; ".join(
                error.message
                for error in errors
            ),
        )

    content_sha256 = manifest[
        "content_sha256"
    ]

    output = (
        metadata_root.resolve()
        / content_sha256[:2]
        / content_sha256
        / (
            intake_attempt_id
            .replace(":", "_")
            + ".metadata.json"
        )
    )

    atomic_write_json(
        output,
        record,
    )

    return record, output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--metadata-root",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--access-status",
        choices=sorted(
            ACCESS_STATUSES
        ),
        required=True,
    )

    parser.add_argument(
        "--license-status",
        choices=sorted(
            LICENSE_STATUSES
        ),
        required=True,
    )

    parser.add_argument(
        "--provider",
    )

    parser.add_argument(
        "--retrieved-at",
    )

    parser.add_argument(
        "--parent-artifact-id",
    )

    parser.add_argument(
        "--root-artifact-id",
    )

    parser.add_argument(
        "--archive-member-path",
    )

    parser.add_argument(
        "--archive-depth",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--expansion-id",
    )

    parser.add_argument(
        "--policy-note",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        record, path = record_metadata(
            args.manifest,
            metadata_root=(
                args.metadata_root
            ),
            access_status=(
                args.access_status
            ),
            license_status=(
                args.license_status
            ),
            provider=args.provider,
            retrieved_at=(
                args.retrieved_at
            ),
            parent_artifact_id=(
                args.parent_artifact_id
            ),
            root_artifact_id=(
                args.root_artifact_id
            ),
            archive_member_path=(
                args.archive_member_path
            ),
            archive_depth=(
                args.archive_depth
            ),
            expansion_id=(
                args.expansion_id
            ),
            policy_note=(
                args.policy_note
            ),
        )
    except MetadataError as exc:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "failure": {
                        "code": exc.code,
                        "message": str(exc),
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
                "status": "RECORDED",
                "metadata_id": record[
                    "metadata_id"
                ],
                "processing_allowed": (
                    record[
                        "processing_allowed"
                    ]
                ),
                "metadata_path": str(
                    path
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
