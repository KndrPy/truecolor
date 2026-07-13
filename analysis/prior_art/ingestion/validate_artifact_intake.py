from __future__ import annotations

import argparse
import json

from pathlib import Path
from typing import Any

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)

from .artifact_intake import (
    sha256_path,
)


ROOT = Path(
    "analysis/prior_art/ingestion"
)

SCHEMA_PATH = (
    ROOT
    / "schemas"
    / "artifact_intake.schema.json"
)


def load_json(
    path: Path,
) -> dict[str, Any]:
    value = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            f"Expected object: {path}"
        )

    return value


def validate_manifest(
    manifest_path: Path,
) -> list[dict[str, Any]]:
    schema = load_json(
        SCHEMA_PATH
    )

    manifest = load_json(
        manifest_path
    )

    validator = (
        Draft202012Validator(
            schema,
            format_checker=(
                FormatChecker()
            ),
        )
    )

    errors: list[
        dict[str, Any]
    ] = []

    for error in sorted(
        validator.iter_errors(
            manifest
        ),
        key=lambda item: list(
            item.absolute_path
        ),
    ):
        errors.append(
            {
                "kind": (
                    "SCHEMA_ERROR"
                ),
                "path": list(
                    error.absolute_path
                ),
                "message": (
                    error.message
                ),
            }
        )

    storage = manifest.get(
        "storage",
        {},
    )

    object_path_value = (
        storage.get(
            "object_path"
        )
    )

    if not isinstance(
        object_path_value,
        str,
    ):
        errors.append(
            {
                "kind": (
                    "OBJECT_PATH_MISSING"
                ),
                "message": (
                    "storage.object_path "
                    "is absent"
                ),
            }
        )

        return errors

    object_path = Path(
        object_path_value
    )

    if not object_path.is_file():
        errors.append(
            {
                "kind": (
                    "OBJECT_MISSING"
                ),
                "path": str(
                    object_path
                ),
            }
        )

        return errors

    observed_size = (
        object_path.stat().st_size
    )

    expected_size = manifest.get(
        "byte_length"
    )

    if observed_size != expected_size:
        errors.append(
            {
                "kind": (
                    "OBJECT_SIZE_MISMATCH"
                ),
                "expected": (
                    expected_size
                ),
                "observed": (
                    observed_size
                ),
            }
        )

    observed_sha256 = sha256_path(
        object_path
    )

    expected_sha256 = manifest.get(
        "content_sha256"
    )

    if (
        observed_sha256
        != expected_sha256
    ):
        errors.append(
            {
                "kind": (
                    "OBJECT_SHA256_MISMATCH"
                ),
                "expected": (
                    expected_sha256
                ),
                "observed": (
                    observed_sha256
                ),
            }
        )

    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "manifest",
        type=Path,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    errors = validate_manifest(
        args.manifest
    )

    result = {
        "manifest": str(
            args.manifest
        ),
        "errors": errors,
        "error_count": len(
            errors
        ),
        "status": (
            "PASS"
            if not errors
            else "FAIL"
        ),
    }

    print(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
        )
    )

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
