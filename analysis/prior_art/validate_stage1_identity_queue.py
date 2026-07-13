from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


ROOT = Path("analysis/prior_art")


def sha256(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(value, dict):
        raise TypeError(path)

    return value


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--schema",
        type=Path,
        default=(
            ROOT
            / "schemas/"
            "identity_verification.schema.json"
        ),
    )

    parser.add_argument(
        "--queue-dir",
        type=Path,
        default=(
            ROOT
            / "corpus/"
            "identity_verifications"
        ),
    )

    parser.add_argument(
        "--manifest",
        type=Path,
        default=(
            ROOT
            / "evidence/verification/"
            "stage1_identity_queue_manifest.json"
        ),
    )

    args = parser.parse_args()

    schema = json.loads(
        args.schema.read_text(
            encoding="utf-8"
        )
    )

    manifest = json.loads(
        args.manifest.read_text(
            encoding="utf-8"
        )
    )

    validator = Draft202012Validator(
        schema
    )

    records = sorted(
        args.queue_dir.glob("*.yaml")
    )

    assert len(records) == 1303
    assert manifest["candidate_count"] == 1303
    assert manifest["record_count"] == 1303

    candidate_keys = set()
    global_ranks = set()

    for path in records:
        record = load_yaml(path)

        errors = list(
            validator.iter_errors(record)
        )

        if errors:
            raise AssertionError({
                "path": str(path),
                "errors": [
                    {
                        "path": list(
                            error.path
                        ),
                        "message": (
                            error.message
                        ),
                    }
                    for error in errors
                ],
            })

        assert record[
            "verification_state"
        ] == "UNVERIFIED"

        candidate_keys.add(
            record["candidate_key"]
        )

        global_ranks.add(
            record["global_rank"]
        )

    assert len(candidate_keys) == 1303
    assert global_ranks == set(
        range(1, 1304)
    )

    manifest_paths = {
        row["path"]: row
        for row in manifest["records"]
    }

    assert len(manifest_paths) == 1303

    for path in records:
        key = str(path)

        assert key in manifest_paths

        expected = manifest_paths[key]

        assert path.stat().st_size == (
            expected["bytes"]
        )

        assert sha256(path) == (
            expected["sha256"]
        )

    print(
        "STAGE1_IDENTITY_QUEUE_VALIDATION=PASS"
    )
    print("IDENTITY_RECORDS=1303")
    print("UNIQUE_CANDIDATE_KEYS=1303")
    print("GLOBAL_RANKS=1_TO_1303")
    print(
        "VERIFICATION_STATE="
        "UNVERIFIED"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
