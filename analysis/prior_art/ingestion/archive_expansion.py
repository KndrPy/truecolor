from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import stat
import tarfile
import tempfile
import uuid
import zipfile

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterable

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)

from .artifact_intake import (
    IntakeError,
    ingest_file,
)

from .intake_metadata import (
    record_metadata,
)


IMPLEMENTATION_VERSION = "1.0.0"

DEFAULT_MAX_MEMBERS = 10000
DEFAULT_MAX_MEMBER_BYTES = (
    512 * 1024 * 1024
)
DEFAULT_MAX_TOTAL_BYTES = (
    2 * 1024 * 1024 * 1024
)
DEFAULT_MAX_COMPRESSION_RATIO = 200.0

ROOT = Path(
    "analysis/prior_art/ingestion"
)

SCHEMA_PATH = (
    ROOT
    / "schemas"
    / "archive_expansion.schema.json"
)


class ArchiveExpansionError(
    RuntimeError
):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class MemberPlan:
    index: int
    member_path: str
    uncompressed_bytes: int
    compressed_bytes: int | None
    source: Any


def load_json(
    path: Path,
) -> dict[str, Any]:
    value = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(value, dict):
        raise ArchiveExpansionError(
            "INVALID_MANIFEST",
            f"Expected object: {path}",
        )

    return value


def safe_member_path(
    raw_name: str,
) -> str:
    if "\x00" in raw_name:
        raise ArchiveExpansionError(
            "UNSAFE_MEMBER_PATH",
            "NUL byte in member path",
        )

    normalized = raw_name.replace(
        "\\",
        "/",
    )

    path = PurePosixPath(
        normalized
    )

    if path.is_absolute():
        raise ArchiveExpansionError(
            "UNSAFE_MEMBER_PATH",
            f"Absolute path: {raw_name}",
        )

    if any(
        part in {"", ".", ".."}
        for part in path.parts
    ):
        raise ArchiveExpansionError(
            "UNSAFE_MEMBER_PATH",
            f"Unsafe path component: {raw_name}",
        )

    if (
        len(path.parts) > 256
        or len(normalized) > 4096
    ):
        raise ArchiveExpansionError(
            "UNSAFE_MEMBER_PATH",
            f"Member path too deep or long: {raw_name}",
        )

    return path.as_posix()


def validate_limits(
    plans: list[MemberPlan],
    *,
    max_members: int,
    max_member_bytes: int,
    max_total_bytes: int,
    max_compression_ratio: float,
) -> None:
    if max_members < 1:
        raise ArchiveExpansionError(
            "INVALID_LIMIT",
            "max_members must be >= 1",
        )

    if max_member_bytes < 1:
        raise ArchiveExpansionError(
            "INVALID_LIMIT",
            "max_member_bytes must be >= 1",
        )

    if max_total_bytes < 1:
        raise ArchiveExpansionError(
            "INVALID_LIMIT",
            "max_total_bytes must be >= 1",
        )

    if max_compression_ratio <= 0:
        raise ArchiveExpansionError(
            "INVALID_LIMIT",
            (
                "max_compression_ratio "
                "must be > 0"
            ),
        )

    if not plans:
        raise ArchiveExpansionError(
            "EMPTY_ARCHIVE",
            "Container has no regular files",
        )

    if len(plans) > max_members:
        raise ArchiveExpansionError(
            "MEMBER_LIMIT_EXCEEDED",
            (
                f"{len(plans)} members exceed "
                f"limit {max_members}"
            ),
        )

    total = 0

    for plan in plans:
        if (
            plan.uncompressed_bytes
            > max_member_bytes
        ):
            raise ArchiveExpansionError(
                "MEMBER_SIZE_LIMIT_EXCEEDED",
                (
                    f"{plan.member_path}: "
                    f"{plan.uncompressed_bytes}"
                ),
            )

        total += (
            plan.uncompressed_bytes
        )

        if total > max_total_bytes:
            raise ArchiveExpansionError(
                "TOTAL_SIZE_LIMIT_EXCEEDED",
                (
                    f"Declared total {total} "
                    f"exceeds {max_total_bytes}"
                ),
            )

        compressed = (
            plan.compressed_bytes
        )

        if (
            compressed is not None
            and plan.uncompressed_bytes > 0
        ):
            ratio = (
                plan.uncompressed_bytes
                / max(1, compressed)
            )

            if (
                ratio
                > max_compression_ratio
            ):
                raise ArchiveExpansionError(
                    (
                        "COMPRESSION_RATIO_"
                        "EXCEEDED"
                    ),
                    (
                        f"{plan.member_path}: "
                        f"{ratio:.2f}"
                    ),
                )


def zip_plans(
    archive: zipfile.ZipFile,
) -> list[MemberPlan]:
    plans: list[MemberPlan] = []

    for index, info in enumerate(
        archive.infolist()
    ):
        member_path = safe_member_path(
            info.filename
        )

        if info.is_dir():
            continue

        unix_mode = (
            info.external_attr >> 16
        )

        if (
            unix_mode
            and stat.S_ISLNK(
                unix_mode
            )
        ):
            raise ArchiveExpansionError(
                "LINK_MEMBER_REJECTED",
                member_path,
            )

        plans.append(
            MemberPlan(
                index=index,
                member_path=member_path,
                uncompressed_bytes=(
                    info.file_size
                ),
                compressed_bytes=(
                    info.compress_size
                ),
                source=info,
            )
        )

    return plans


def tar_plans(
    archive: tarfile.TarFile,
) -> list[MemberPlan]:
    plans: list[MemberPlan] = []

    for index, info in enumerate(
        archive.getmembers()
    ):
        member_path = safe_member_path(
            info.name
        )

        if info.isdir():
            continue

        if (
            info.issym()
            or info.islnk()
        ):
            raise ArchiveExpansionError(
                "LINK_MEMBER_REJECTED",
                member_path,
            )

        if not info.isfile():
            raise ArchiveExpansionError(
                "SPECIAL_MEMBER_REJECTED",
                member_path,
            )

        plans.append(
            MemberPlan(
                index=index,
                member_path=member_path,
                uncompressed_bytes=(
                    info.size
                ),
                compressed_bytes=None,
                source=info,
            )
        )

    return plans


def copy_limited(
    source: BinaryIO,
    destination: Path,
    *,
    declared_bytes: int,
    max_member_bytes: int,
) -> int:
    observed = 0

    with destination.open(
        "xb"
    ) as output:
        while True:
            chunk = source.read(
                1024 * 1024
            )

            if not chunk:
                break

            observed += len(chunk)

            if observed > max_member_bytes:
                raise ArchiveExpansionError(
                    (
                        "OBSERVED_MEMBER_SIZE_"
                        "LIMIT_EXCEEDED"
                    ),
                    str(observed),
                )

            output.write(chunk)

        output.flush()
        os.fsync(output.fileno())

    if observed != declared_bytes:
        raise ArchiveExpansionError(
            "MEMBER_SIZE_MISMATCH",
            (
                f"Declared {declared_bytes}, "
                f"observed {observed}"
            ),
        )

    return observed


def expand_archive(
    parent_manifest_path: Path,
    *,
    store_root: Path,
    manifest_root: Path,
    expansion_root: Path,
    metadata_root: Path,
    max_members: int = (
        DEFAULT_MAX_MEMBERS
    ),
    max_member_bytes: int = (
        DEFAULT_MAX_MEMBER_BYTES
    ),
    max_total_bytes: int = (
        DEFAULT_MAX_TOTAL_BYTES
    ),
    max_compression_ratio: float = (
        DEFAULT_MAX_COMPRESSION_RATIO
    ),
    archive_depth: int = 0,
) -> tuple[dict[str, Any], Path]:
    if archive_depth < 0:
        raise ArchiveExpansionError(
            "INVALID_ARCHIVE_DEPTH",
            str(archive_depth),
        )

    parent = load_json(
        parent_manifest_path
    )

    media_type = parent[
        "detected_media_type"
    ]

    if media_type not in {
        "application/zip",
        "application/x-tar",
        "application/gzip",
    }:
        raise ArchiveExpansionError(
            "UNSUPPORTED_CONTAINER_TYPE",
            media_type,
        )

    object_path = Path(
        parent["storage"][
            "object_path"
        ]
    )

    if not object_path.is_file():
        raise ArchiveExpansionError(
            "PARENT_OBJECT_MISSING",
            str(object_path),
        )

    expansion_id = (
        f"expansion:{uuid.uuid4().hex}"
    )

    parent_artifact_id = parent[
        "artifact_id"
    ]

    parent_attempt_id = parent[
        "intake_attempt_id"
    ]

    root_artifact_id = (
        parent_artifact_id
    )

    children: list[
        dict[str, Any]
    ] = []

    expanded_total = 0

    with tempfile.TemporaryDirectory(
        prefix="truecolor-expand-"
    ) as temporary:
        temporary_root = Path(
            temporary
        )

        if media_type == "application/zip":
            with zipfile.ZipFile(
                object_path,
                "r",
            ) as archive:
                plans = zip_plans(
                    archive
                )

                validate_limits(
                    plans,
                    max_members=max_members,
                    max_member_bytes=(
                        max_member_bytes
                    ),
                    max_total_bytes=(
                        max_total_bytes
                    ),
                    max_compression_ratio=(
                        max_compression_ratio
                    ),
                )

                for plan in plans:
                    extracted = (
                        temporary_root
                        / f"{plan.index}.member"
                    )

                    with archive.open(
                        plan.source,
                        "r",
                    ) as source:
                        observed = copy_limited(
                            source,
                            extracted,
                            declared_bytes=(
                                plan
                                .uncompressed_bytes
                            ),
                            max_member_bytes=(
                                max_member_bytes
                            ),
                        )

                    expanded_total += (
                        observed
                    )

                    result = ingest_file(
                        extracted,
                        store_root=store_root,
                        manifest_root=(
                            manifest_root
                        ),
                        original_name=(
                            Path(
                                plan.member_path
                            ).name
                        ),
                        source_uri=(
                            "archive://"
                            f"{parent_artifact_id}/"
                            f"{plan.member_path}"
                        ),
                        max_bytes=(
                            max_member_bytes
                        ),
                    )

                    record_metadata(
                        result.manifest_path,
                        metadata_root=(
                            metadata_root
                        ),
                        access_status=(
                            "AVAILABLE"
                        ),
                        license_status=(
                            "USER_PROVIDED"
                        ),
                        provider=(
                            "archive-expansion"
                        ),
                        parent_artifact_id=(
                            parent_artifact_id
                        ),
                        root_artifact_id=(
                            root_artifact_id
                        ),
                        archive_member_path=(
                            plan.member_path
                        ),
                        archive_depth=(
                            archive_depth + 1
                        ),
                        expansion_id=(
                            expansion_id
                        ),
                    )

                    children.append(
                        {
                            "member_path": (
                                plan.member_path
                            ),
                            "member_index": (
                                plan.index
                            ),
                            "declared_uncompressed_bytes": (
                                plan
                                .uncompressed_bytes
                            ),
                            "compressed_bytes": (
                                plan
                                .compressed_bytes
                            ),
                            "child_artifact_id": (
                                result.manifest[
                                    "artifact_id"
                                ]
                            ),
                            "child_intake_attempt_id": (
                                result.manifest[
                                    "intake_attempt_id"
                                ]
                            ),
                            "child_manifest_path": str(
                                result.manifest_path
                            ),
                            "child_object_path": str(
                                result.object_path
                            ),
                            "child_content_sha256": (
                                result.manifest[
                                    "content_sha256"
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
                        }
                    )

        elif media_type == "application/x-tar":
            with tarfile.open(
                object_path,
                "r:",
            ) as archive:
                plans = tar_plans(
                    archive
                )

                validate_limits(
                    plans,
                    max_members=max_members,
                    max_member_bytes=(
                        max_member_bytes
                    ),
                    max_total_bytes=(
                        max_total_bytes
                    ),
                    max_compression_ratio=(
                        max_compression_ratio
                    ),
                )

                for plan in plans:
                    extracted = (
                        temporary_root
                        / f"{plan.index}.member"
                    )

                    source = archive.extractfile(
                        plan.source
                    )

                    if source is None:
                        raise ArchiveExpansionError(
                            (
                                "MEMBER_STREAM_"
                                "UNAVAILABLE"
                            ),
                            plan.member_path,
                        )

                    with source:
                        observed = copy_limited(
                            source,
                            extracted,
                            declared_bytes=(
                                plan
                                .uncompressed_bytes
                            ),
                            max_member_bytes=(
                                max_member_bytes
                            ),
                        )

                    expanded_total += observed

                    result = ingest_file(
                        extracted,
                        store_root=store_root,
                        manifest_root=(
                            manifest_root
                        ),
                        original_name=(
                            Path(
                                plan.member_path
                            ).name
                        ),
                        source_uri=(
                            "archive://"
                            f"{parent_artifact_id}/"
                            f"{plan.member_path}"
                        ),
                        max_bytes=(
                            max_member_bytes
                        ),
                    )

                    record_metadata(
                        result.manifest_path,
                        metadata_root=(
                            metadata_root
                        ),
                        access_status=(
                            "AVAILABLE"
                        ),
                        license_status=(
                            "USER_PROVIDED"
                        ),
                        provider=(
                            "archive-expansion"
                        ),
                        parent_artifact_id=(
                            parent_artifact_id
                        ),
                        root_artifact_id=(
                            root_artifact_id
                        ),
                        archive_member_path=(
                            plan.member_path
                        ),
                        archive_depth=(
                            archive_depth + 1
                        ),
                        expansion_id=(
                            expansion_id
                        ),
                    )

                    children.append(
                        {
                            "member_path": (
                                plan.member_path
                            ),
                            "member_index": (
                                plan.index
                            ),
                            "declared_uncompressed_bytes": (
                                plan
                                .uncompressed_bytes
                            ),
                            "compressed_bytes": None,
                            "child_artifact_id": (
                                result.manifest[
                                    "artifact_id"
                                ]
                            ),
                            "child_intake_attempt_id": (
                                result.manifest[
                                    "intake_attempt_id"
                                ]
                            ),
                            "child_manifest_path": str(
                                result.manifest_path
                            ),
                            "child_object_path": str(
                                result.object_path
                            ),
                            "child_content_sha256": (
                                result.manifest[
                                    "content_sha256"
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
                        }
                    )

        else:
            original_name = parent[
                "original_name"
            ]

            child_name = (
                original_name[:-3]
                if original_name.lower()
                .endswith(".gz")
                else (
                    original_name
                    + ".expanded"
                )
            )

            extracted = (
                temporary_root
                / "0.member"
            )

            with gzip.open(
                object_path,
                "rb",
            ) as source:
                observed = 0

                with extracted.open(
                    "xb"
                ) as output:
                    while True:
                        chunk = source.read(
                            1024 * 1024
                        )

                        if not chunk:
                            break

                        observed += len(
                            chunk
                        )

                        if (
                            observed
                            > max_member_bytes
                        ):
                            raise ArchiveExpansionError(
                                (
                                    "OBSERVED_MEMBER_"
                                    "SIZE_LIMIT_EXCEEDED"
                                ),
                                str(observed),
                            )

                        if (
                            observed
                            > max_total_bytes
                        ):
                            raise ArchiveExpansionError(
                                (
                                    "TOTAL_SIZE_LIMIT_"
                                    "EXCEEDED"
                                ),
                                str(observed),
                            )

                        output.write(chunk)

                    output.flush()
                    os.fsync(
                        output.fileno()
                    )

            compressed_bytes = (
                object_path
                .stat()
                .st_size
            )

            ratio = (
                observed
                / max(
                    1,
                    compressed_bytes,
                )
            )

            if (
                ratio
                > max_compression_ratio
            ):
                raise ArchiveExpansionError(
                    (
                        "COMPRESSION_RATIO_"
                        "EXCEEDED"
                    ),
                    f"{ratio:.2f}",
                )

            expanded_total = observed

            result = ingest_file(
                extracted,
                store_root=store_root,
                manifest_root=(
                    manifest_root
                ),
                original_name=child_name,
                source_uri=(
                    "archive://"
                    f"{parent_artifact_id}/"
                    f"{child_name}"
                ),
                max_bytes=(
                    max_member_bytes
                ),
            )

            record_metadata(
                result.manifest_path,
                metadata_root=(
                    metadata_root
                ),
                access_status="AVAILABLE",
                license_status=(
                    "USER_PROVIDED"
                ),
                provider=(
                    "archive-expansion"
                ),
                parent_artifact_id=(
                    parent_artifact_id
                ),
                root_artifact_id=(
                    root_artifact_id
                ),
                archive_member_path=(
                    child_name
                ),
                archive_depth=(
                    archive_depth + 1
                ),
                expansion_id=(
                    expansion_id
                ),
            )

            children.append(
                {
                    "member_path": (
                        child_name
                    ),
                    "member_index": 0,
                    "declared_uncompressed_bytes": (
                        observed
                    ),
                    "compressed_bytes": (
                        compressed_bytes
                    ),
                    "child_artifact_id": (
                        result.manifest[
                            "artifact_id"
                        ]
                    ),
                    "child_intake_attempt_id": (
                        result.manifest[
                            "intake_attempt_id"
                        ]
                    ),
                    "child_manifest_path": str(
                        result.manifest_path
                    ),
                    "child_object_path": str(
                        result.object_path
                    ),
                    "child_content_sha256": (
                        result.manifest[
                            "content_sha256"
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
                }
            )

    expansion = {
        "schema_version": "1.0.0",
        "expansion_id": expansion_id,
        "parent_artifact_id": (
            parent_artifact_id
        ),
        "parent_intake_attempt_id": (
            parent_attempt_id
        ),
        "parent_content_sha256": (
            parent["content_sha256"]
        ),
        "container_media_type": (
            media_type
        ),
        "limits": {
            "max_members": max_members,
            "max_member_bytes": (
                max_member_bytes
            ),
            "max_total_bytes": (
                max_total_bytes
            ),
            "max_compression_ratio": (
                max_compression_ratio
            ),
            "archive_depth": (
                archive_depth
            ),
        },
        "children": sorted(
            children,
            key=lambda child: (
                child["member_index"],
                child["member_path"],
            ),
        ),
        "member_count": len(
            children
        ),
        "expanded_byte_count": (
            expanded_total
        ),
        "status": "EXPANDED",
        "implementation": {
            "module": (
                "analysis.prior_art."
                "ingestion."
                "archive_expansion"
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

    validation_errors = list(
        validator.iter_errors(
            expansion
        )
    )

    if validation_errors:
        raise ArchiveExpansionError(
            (
                "EXPANSION_MANIFEST_"
                "INVALID"
            ),
            "; ".join(
                error.message
                for error
                in validation_errors
            ),
        )

    output = (
        expansion_root.resolve()
        / parent["content_sha256"][
            :2
        ]
        / parent["content_sha256"]
        / (
            expansion_id
            .replace(":", "_")
            + ".json"
        )
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    descriptor, temporary_name = (
        tempfile.mkstemp(
            prefix=f".{output.name}.",
            suffix=".tmp",
            dir=output.parent,
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
                expansion,
                handle,
                indent=2,
                sort_keys=True,
            )

            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(
            temporary_path,
            output,
        )
    finally:
        temporary_path.unlink(
            missing_ok=True
        )

    return expansion, output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--parent-manifest",
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
        "--expansion-root",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--metadata-root",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--max-members",
        type=int,
        default=DEFAULT_MAX_MEMBERS,
    )

    parser.add_argument(
        "--max-member-bytes",
        type=int,
        default=DEFAULT_MAX_MEMBER_BYTES,
    )

    parser.add_argument(
        "--max-total-bytes",
        type=int,
        default=DEFAULT_MAX_TOTAL_BYTES,
    )

    parser.add_argument(
        "--max-compression-ratio",
        type=float,
        default=(
            DEFAULT_MAX_COMPRESSION_RATIO
        ),
    )

    parser.add_argument(
        "--archive-depth",
        type=int,
        default=0,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        expansion, path = expand_archive(
            args.parent_manifest,
            store_root=(
                args.store_root
            ),
            manifest_root=(
                args.manifest_root
            ),
            expansion_root=(
                args.expansion_root
            ),
            metadata_root=(
                args.metadata_root
            ),
            max_members=(
                args.max_members
            ),
            max_member_bytes=(
                args.max_member_bytes
            ),
            max_total_bytes=(
                args.max_total_bytes
            ),
            max_compression_ratio=(
                args.max_compression_ratio
            ),
            archive_depth=(
                args.archive_depth
            ),
        )
    except (
        ArchiveExpansionError,
        IntakeError,
        OSError,
        zipfile.BadZipFile,
        tarfile.TarError,
        gzip.BadGzipFile,
    ) as exc:
        code = getattr(
            exc,
            "code",
            type(exc).__name__,
        )

        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "failure": {
                        "code": code,
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
                "status": (
                    expansion["status"]
                ),
                "expansion_id": (
                    expansion[
                        "expansion_id"
                    ]
                ),
                "member_count": (
                    expansion[
                        "member_count"
                    ]
                ),
                "expanded_byte_count": (
                    expansion[
                        "expanded_byte_count"
                    ]
                ),
                "expansion_manifest_path": (
                    str(path)
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
