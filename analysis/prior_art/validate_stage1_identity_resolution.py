from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)


ROOT = Path("analysis/prior_art")

SCHEMA_PATH = (
    ROOT
    / "schemas/"
    "identity_resolution_result.schema.json"
)

NORMALIZED_DIR = (
    ROOT
    / "evidence/"
    "identity_resolution/"
    "normalized"
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(value, dict):
        raise TypeError(path)

    return value


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--start-rank",
        type=int,
        default=1,
    )

    parser.add_argument(
        "--end-rank",
        type=int,
        default=1303,
    )

    parser.add_argument(
        "--require-complete",
        action="store_true",
    )

    args = parser.parse_args()

    schema = load_json(
        SCHEMA_PATH
    )

    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )

    expected = set(
        range(
            args.start_rank,
            args.end_rank + 1,
        )
    )

    observed = set()
    errors = []
    states = Counter()

    for path in sorted(
        NORMALIZED_DIR.glob(
            "global-*.json"
        )
    ):
        result = load_json(path)

        rank = int(
            result["global_rank"]
        )

        if rank not in expected:
            continue

        observed.add(rank)

        for error in validator.iter_errors(
            result
        ):
            errors.append({
                "path": str(path),
                "field_path": list(
                    error.path
                ),
                "message": error.message,
            })

        states[
            result["resolution_state"]
        ] += 1

        evidence = result[
            "retrieval_evidence"
        ]

        for item in evidence:
            raw_path = item.get(
                "raw_path"
            )

            raw_sha = item.get(
                "raw_sha256"
            )

            if raw_path is None:
                continue

            raw = Path(raw_path)

            if not raw.is_file():
                errors.append({
                    "path": str(path),
                    "field_path": [
                        "retrieval_evidence",
                        "raw_path",
                    ],
                    "message": (
                        f"raw evidence missing: "
                        f"{raw}"
                    ),
                })

            elif raw_sha:
                import hashlib

                observed_sha = (
                    hashlib.sha256(
                        raw.read_bytes()
                    ).hexdigest()
                )

                if observed_sha != raw_sha:
                    errors.append({
                        "path": str(path),
                        "field_path": [
                            "retrieval_evidence",
                            "raw_sha256",
                        ],
                        "message": (
                            "raw evidence hash "
                            "mismatch"
                        ),
                    })

    missing = sorted(
        expected - observed
    )

    if (
        args.require_complete
        and missing
    ):
        errors.append({
            "path": str(NORMALIZED_DIR),
            "field_path": [],
            "message": (
                "missing normalized ranks: "
                + ",".join(
                    str(value)
                    for value in missing
                )
            ),
        })

    print(
        f"EXPECTED_RESULTS="
        f"{len(expected)}"
    )
    print(
        f"OBSERVED_RESULTS="
        f"{len(observed)}"
    )
    print(
        f"MISSING_RESULTS="
        f"{len(missing)}"
    )

    for state, count in sorted(
        states.items()
    ):
        print(
            f"STATE_{state}={count}"
        )

    print(
        f"VALIDATION_ERRORS="
        f"{len(errors)}"
    )

    if errors:
        print(
            json.dumps(
                errors[:50],
                indent=2,
                sort_keys=True,
            )
        )

        return 1

    print(
        "STAGE1_IDENTITY_RESOLUTION_"
        "VALIDATION=PASS"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
