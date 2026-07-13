from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile

from collections import defaultdict
from pathlib import Path
from typing import Any


def load_json(
    path: Path,
) -> dict[str, Any]:
    value = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(value, dict):
        raise TypeError(
            f"Expected object: {path}"
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


def build_index(
    manifest_root: Path,
    *,
    metadata_root: Path | None,
) -> dict[str, Any]:
    attempts: list[
        dict[str, Any]
    ] = []

    metadata_by_attempt: dict[
        str,
        dict[str, Any],
    ] = {}

    if (
        metadata_root is not None
        and metadata_root.exists()
    ):
        for path in sorted(
            metadata_root.rglob(
                "*.metadata.json"
            )
        ):
            record = load_json(
                path
            )

            attempt_id = record[
                "intake_attempt_id"
            ]

            if (
                attempt_id
                in metadata_by_attempt
            ):
                raise ValueError(
                    "DUPLICATE_METADATA_ATTEMPT:"
                    + attempt_id
                )

            metadata_by_attempt[
                attempt_id
            ] = record

    for path in sorted(
        manifest_root.rglob(
            "intake_*.json"
        )
    ):
        manifest = load_json(
            path
        )

        attempt_id = manifest[
            "intake_attempt_id"
        ]

        attempts.append(
            {
                "intake_attempt_id": (
                    attempt_id
                ),
                "artifact_id": (
                    manifest[
                        "artifact_id"
                    ]
                ),
                "content_sha256": (
                    manifest[
                        "content_sha256"
                    ]
                ),
                "byte_length": (
                    manifest[
                        "byte_length"
                    ]
                ),
                "original_name": (
                    manifest[
                        "original_name"
                    ]
                ),
                "detected_media_type": (
                    manifest[
                        "detected_media_type"
                    ]
                ),
                "object_path": (
                    manifest[
                        "storage"
                    ][
                        "object_path"
                    ]
                ),
                "manifest_path": str(
                    path.resolve()
                ),
                "metadata_id": (
                    metadata_by_attempt.get(
                        attempt_id,
                        {},
                    ).get(
                        "metadata_id"
                    )
                ),
                "processing_allowed": (
                    metadata_by_attempt.get(
                        attempt_id,
                        {},
                    ).get(
                        "processing_allowed"
                    )
                ),
            }
        )

    attempt_ids = [
        attempt[
            "intake_attempt_id"
        ]
        for attempt in attempts
    ]

    if (
        len(attempt_ids)
        != len(set(attempt_ids))
    ):
        raise ValueError(
            "DUPLICATE_INTAKE_ATTEMPT"
        )

    grouped: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for attempt in attempts:
        grouped[
            attempt["artifact_id"]
        ].append(attempt)

    artifacts: list[
        dict[str, Any]
    ] = []

    for artifact_id in sorted(
        grouped
    ):
        artifact_attempts = sorted(
            grouped[artifact_id],
            key=lambda item: (
                item[
                    "intake_attempt_id"
                ]
            ),
        )

        content_hashes = {
            attempt[
                "content_sha256"
            ]
            for attempt
            in artifact_attempts
        }

        object_paths = {
            attempt["object_path"]
            for attempt
            in artifact_attempts
        }

        byte_lengths = {
            attempt["byte_length"]
            for attempt
            in artifact_attempts
        }

        if len(content_hashes) != 1:
            raise ValueError(
                "ARTIFACT_HASH_CONFLICT:"
                + artifact_id
            )

        if len(object_paths) != 1:
            raise ValueError(
                "ARTIFACT_OBJECT_CONFLICT:"
                + artifact_id
            )

        if len(byte_lengths) != 1:
            raise ValueError(
                "ARTIFACT_SIZE_CONFLICT:"
                + artifact_id
            )

        artifacts.append(
            {
                "artifact_id": (
                    artifact_id
                ),
                "content_sha256": next(
                    iter(content_hashes)
                ),
                "byte_length": next(
                    iter(byte_lengths)
                ),
                "object_path": next(
                    iter(object_paths)
                ),
                "attempt_count": len(
                    artifact_attempts
                ),
                "intake_attempt_ids": [
                    attempt[
                        "intake_attempt_id"
                    ]
                    for attempt
                    in artifact_attempts
                ],
                "original_names": sorted(
                    {
                        attempt[
                            "original_name"
                        ]
                        for attempt
                        in artifact_attempts
                    }
                ),
                "detected_media_types": (
                    sorted(
                        {
                            attempt[
                                "detected_media_type"
                            ]
                            for attempt
                            in artifact_attempts
                        }
                    )
                ),
            }
        )

    basis = {
        "schema_version": "1.0.0",
        "artifact_count": len(
            artifacts
        ),
        "attempt_count": len(
            attempts
        ),
        "artifacts": artifacts,
        "attempts": sorted(
            attempts,
            key=lambda item: (
                item[
                    "intake_attempt_id"
                ]
            ),
        ),
    }

    index_hash = hashlib.sha256(
        canonical_bytes(
            basis
        )
    ).hexdigest()

    return {
        **basis,
        "index_sha256": (
            index_hash
        ),
    }


def atomic_write(
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
            )

            handle.write("\n")
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--manifest-root",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--metadata-root",
        type=Path,
    )

    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        index = build_index(
            args.manifest_root,
            metadata_root=(
                args.metadata_root
            ),
        )

        atomic_write(
            args.output,
            index,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "failure": {
                        "code": (
                            type(exc).__name__
                        ),
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
                "status": "PASS",
                "artifact_count": (
                    index[
                        "artifact_count"
                    ]
                ),
                "attempt_count": (
                    index[
                        "attempt_count"
                    ]
                ),
                "index_sha256": (
                    index[
                        "index_sha256"
                    ]
                ),
                "output": str(
                    args.output
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
