from __future__ import annotations

import json
import tempfile

from pathlib import Path
from typing import Callable

from .artifact_intake import (
    IntakeError,
    ingest_file,
)


def expect_failure(
    name: str,
    expected_code: str,
    operation: Callable[[], None],
) -> dict[str, object]:
    try:
        operation()
    except IntakeError as exc:
        return {
            "test": name,
            "expected_code": (
                expected_code
            ),
            "observed_code": (
                exc.code
            ),
            "passed": (
                exc.code
                == expected_code
            ),
        }
    except Exception as exc:
        return {
            "test": name,
            "expected_code": (
                expected_code
            ),
            "observed_code": (
                type(exc).__name__
            ),
            "passed": False,
        }

    return {
        "test": name,
        "expected_code": (
            expected_code
        ),
        "observed_code": (
            "NO_FAILURE"
        ),
        "passed": False,
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source_root = root / "sources"
        store_root = root / "store"
        manifest_root = root / "manifests"

        source_root.mkdir()

        checksum_source = (
            source_root
            / "checksum.txt"
        )

        checksum_source.write_bytes(
            b"checksum"
        )

        oversized_source = (
            source_root
            / "oversized.bin"
        )

        oversized_source.write_bytes(
            b"x" * 1025
        )

        missing_source = (
            source_root
            / "missing.pdf"
        )

        tests = [
            expect_failure(
                (
                    "checksum_mismatch"
                ),
                (
                    "CHECKSUM_MISMATCH"
                ),
                lambda: ingest_file(
                    checksum_source,
                    store_root=(
                        store_root
                    ),
                    manifest_root=(
                        manifest_root
                    ),
                    expected_sha256=(
                        "0" * 64
                    ),
                ),
            ),
            expect_failure(
                "size_limit",
                (
                    "SIZE_LIMIT_EXCEEDED"
                ),
                lambda: ingest_file(
                    oversized_source,
                    store_root=(
                        store_root
                    ),
                    manifest_root=(
                        manifest_root
                    ),
                    max_bytes=1024,
                ),
            ),
            expect_failure(
                "missing_source",
                "SOURCE_NOT_FOUND",
                lambda: ingest_file(
                    missing_source,
                    store_root=(
                        store_root
                    ),
                    manifest_root=(
                        manifest_root
                    ),
                ),
            ),
            expect_failure(
                "invalid_max_bytes",
                "INVALID_MAX_BYTES",
                lambda: ingest_file(
                    checksum_source,
                    store_root=(
                        store_root
                    ),
                    manifest_root=(
                        manifest_root
                    ),
                    max_bytes=-1,
                ),
            ),
        ]

        passed = all(
            bool(
                result["passed"]
            )
            for result in tests
        )

        output = {
            "capabilities": [
                "CAP-INTAKE-001",
                "CAP-INTAKE-002",
                "CAP-INTAKE-003",
            ],
            "falsification_status": (
                "PASS"
                if passed
                else "FAIL"
            ),
            "tests": tests,
        }

        report_path = (
            Path(
                "analysis/prior_art/"
                "ingestion/reports/"
                "intake-falsification.json"
            )
        )

        report_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        report_path.write_text(
            json.dumps(
                output,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        print(
            json.dumps(
                output,
                indent=2,
                sort_keys=True,
            )
        )

        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
