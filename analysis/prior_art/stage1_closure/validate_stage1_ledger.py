from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
STAGE1 = ROOT / "artifacts" / "stage_01"

REGISTER_REQUIREMENTS = {
    "source_state_register.json": 16,
    "evidence_record_register.json": 16,
    "second_review_register.json": 5,
    "scientific_matrix_register.json": 6,
    "kill_condition_register.json": 6,
    "unsupported_field_register.json": 1,
}


def load_json(name: str) -> Any:
    return json.loads(
        (STAGE1 / name).read_text(
            encoding="utf-8"
        )
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def main() -> int:
    errors: list[str] = []

    required_files = {
        "stage1_evidence_inventory.json",
        "source_state_register.json",
        "evidence_record_register.json",
        "second_review_register.json",
        "scientific_matrix_register.json",
        "kill_condition_register.json",
        "unsupported_field_register.json",
        "stage1_gap_report.json",
        "stage1_ledger_run.json",
        "artifact_hashes.json",
    }

    actual_files = {
        path.name
        for path in STAGE1.glob("*.json")
        if path.is_file()
    }

    for name in sorted(
        required_files - actual_files
    ):
        errors.append(
            f"missing Stage 1 artifact: {name}"
        )

    if (
        STAGE1 / "STAGE_01_CLOSED.json"
    ).exists():
        errors.append(
            "Stage 1 closure marker exists before "
            "scientific adjudication"
        )

    for name, required_minimum in (
        REGISTER_REQUIREMENTS.items()
    ):
        path = STAGE1 / name

        if not path.is_file():
            continue

        register = load_json(name)
        records = register.get("records", [])
        discovered = register.get(
            "discovered_record_count"
        )

        if discovered != len(records):
            errors.append(
                f"{name} count does not match records"
            )

        if register.get(
            "required_minimum"
        ) != required_minimum:
            errors.append(
                f"{name} has wrong required minimum"
            )

        paths = [
            record.get("path")
            for record in records
        ]

        if len(paths) != len(set(paths)):
            errors.append(
                f"{name} contains duplicate paths"
            )

        for record in records:
            source = ROOT / record["path"]

            if not source.is_file():
                errors.append(
                    f"{name} references missing file "
                    f"{record['path']}"
                )
                continue

            actual_hash = sha256_file(source)

            if actual_hash != record["sha256"]:
                errors.append(
                    f"{name} source hash mismatch "
                    f"{record['path']}"
                )

    hash_path = STAGE1 / "artifact_hashes.json"

    if hash_path.is_file():
        hashes = load_json(
            "artifact_hashes.json"
        )

        for name, expected in hashes.items():
            artifact = STAGE1 / name

            if not artifact.is_file():
                errors.append(
                    f"hashed Stage 1 artifact missing: "
                    f"{name}"
                )
                continue

            actual = sha256_file(artifact)

            if actual != expected:
                errors.append(
                    f"Stage 1 artifact hash mismatch: "
                    f"{name}"
                )

    if errors:
        print(
            "QUDIPI_STAGE1_LEDGER_VALIDATION=FAIL"
        )

        for error in errors:
            print(f"ERROR  {error}")

        return 1

    gap = load_json("stage1_gap_report.json")

    print("QUDIPI_STAGE1_LEDGER_VALIDATION=PASS")
    print(
        f"stage1_status={gap['status']}"
    )
    print(
        "remaining_blockers="
        + (
            ",".join(
                gap["remaining_blockers"]
            )
            if gap["remaining_blockers"]
            else "none"
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
