from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
STAGE1 = ROOT / "artifacts" / "stage_01"

CLAIM_ID_PATTERN = re.compile(
    r"^TC-NOV-[0-9]{3}$"
)

SOURCE_ID_PATTERN = re.compile(
    r"^PA-[0-9]{4}$"
)

EXPECTED_SOURCE_COUNT = 16
EXPECTED_EVIDENCE_COUNT = 16
EXPECTED_SECOND_REVIEW_COUNT = 5
EXPECTED_CLAIM_COUNT = 6
EXPECTED_MATRIX_COUNT = 6
EXPECTED_KILL_COUNT = 6


def load_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def require_file(
    path: Path,
    errors: list[str],
) -> bool:
    if not path.is_file():
        errors.append(
            f"missing artifact: "
            f"{path.relative_to(ROOT)}"
        )
        return False

    return True


def main() -> int:
    errors: list[str] = []

    source_path = (
        STAGE1 / "source_register.json"
    )

    evidence_path = (
        STAGE1 / "evidence_register.json"
    )

    review_path = (
        STAGE1 / "second_review_register.json"
    )

    claim_path = (
        STAGE1 / "claim_register.json"
    )

    matrix_path = (
        STAGE1 / "claim_matrix_register.json"
    )

    kill_path = (
        STAGE1 / "novelty_kill_register.json"
    )

    unsupported_path = (
        STAGE1 / "unsupported_field_register.json"
    )

    gap_path = (
        STAGE1 / "stage1_gap_report.json"
    )

    run_path = (
        STAGE1
        / "stage1_semantic_ledger_run.json"
    )

    hash_path = (
        STAGE1 / "artifact_hashes.json"
    )

    required_paths = [
        source_path,
        evidence_path,
        review_path,
        claim_path,
        matrix_path,
        kill_path,
        unsupported_path,
        gap_path,
        run_path,
        hash_path,
    ]

    if not all(
        require_file(path, errors)
        for path in required_paths
    ):
        for error in errors:
            print(f"ERROR  {error}")

        print(
            "QUDIPI_STAGE1_SEMANTIC_VALIDATION=FAIL"
        )
        return 1

    source_register = load_json(
        source_path
    )

    evidence_register = load_json(
        evidence_path
    )

    review_register = load_json(
        review_path
    )

    claim_register = load_json(
        claim_path
    )

    matrix_register = load_json(
        matrix_path
    )

    kill_register = load_json(
        kill_path
    )

    unsupported_register = load_json(
        unsupported_path
    )

    gap_report = load_json(
        gap_path
    )

    run_manifest = load_json(
        run_path
    )

    if run_manifest.get("status") != "PASS":
        errors.append(
            "semantic ledger run manifest is not PASS"
        )

    semantic_errors = gap_report.get(
        "semantic_contract_errors",
        [],
    )

    if not isinstance(
        semantic_errors,
        list,
    ):
        errors.append(
            "semantic_contract_errors must be a list"
        )
    elif semantic_errors:
        errors.append(
            "semantic gap report contains contract errors"
        )

    if (
        source_register.get(
            "record_count"
        )
        != EXPECTED_SOURCE_COUNT
    ):
        errors.append(
            "source register must contain "
            f"{EXPECTED_SOURCE_COUNT} records"
        )

    source_ids = [
        record.get("source_id")
        for record in source_register.get(
            "records",
            [],
        )
    ]

    if len(source_ids) != len(
        set(source_ids)
    ):
        errors.append(
            "source register contains duplicate IDs"
        )

    for source_id in source_ids:
        if not isinstance(
            source_id,
            str,
        ) or not SOURCE_ID_PATTERN.fullmatch(
            source_id
        ):
            errors.append(
                f"invalid source ID: {source_id!r}"
            )

    if (
        evidence_register.get(
            "record_count"
        )
        != EXPECTED_EVIDENCE_COUNT
    ):
        errors.append(
            "evidence register must contain "
            f"{EXPECTED_EVIDENCE_COUNT} records"
        )

    evidence_ids = [
        record.get("evidence_id")
        for record in evidence_register.get(
            "records",
            [],
        )
    ]

    if len(evidence_ids) != len(
        set(evidence_ids)
    ):
        errors.append(
            "evidence register contains duplicate IDs"
        )

    if (
        review_register.get(
            "record_count"
        )
        != EXPECTED_SECOND_REVIEW_COUNT
    ):
        errors.append(
            "second-review register must contain "
            f"{EXPECTED_SECOND_REVIEW_COUNT} records"
        )

    review_ids = [
        record.get("review_id")
        for record in review_register.get(
            "records",
            [],
        )
    ]

    if len(review_ids) != len(
        set(review_ids)
    ):
        errors.append(
            "second-review register contains "
            "duplicate IDs"
        )

    claims = claim_register.get(
        "claims",
        [],
    )

    if len(claims) != EXPECTED_CLAIM_COUNT:
        errors.append(
            "claim register must contain "
            f"{EXPECTED_CLAIM_COUNT} claims"
        )

    claim_ids = [
        claim.get("claim_id")
        for claim in claims
    ]

    if len(claim_ids) != len(
        set(claim_ids)
    ):
        errors.append(
            "claim register contains duplicate IDs"
        )

    for claim_id in claim_ids:
        if not isinstance(
            claim_id,
            str,
        ) or not CLAIM_ID_PATTERN.fullmatch(
            claim_id
        ):
            errors.append(
                f"invalid claim ID: {claim_id!r}"
            )

    matrices = matrix_register.get(
        "matrices",
        [],
    )

    if len(matrices) != EXPECTED_MATRIX_COUNT:
        errors.append(
            "matrix register must contain "
            f"{EXPECTED_MATRIX_COUNT} matrices"
        )

    matrix_claim_ids = {
        matrix.get("claim_id")
        for matrix in matrices
    }

    if matrix_claim_ids != set(
        claim_ids
    ):
        errors.append(
            "matrix claim set differs from "
            "claim register"
        )

    for matrix_record in matrices:
        path = ROOT / matrix_record[
            "matrix_path"
        ]

        if not path.is_file():
            errors.append(
                "matrix file missing: "
                f"{matrix_record['matrix_path']}"
            )
            continue

        if (
            sha256_file(path)
            != matrix_record["matrix_sha256"]
        ):
            errors.append(
                "matrix hash mismatch: "
                f"{matrix_record['matrix_path']}"
            )

        matrix = load_json(path)

        if (
            matrix.get("claim_id")
            != matrix_record.get("claim_id")
        ):
            errors.append(
                "matrix claim identity mismatch: "
                f"{matrix_record['matrix_path']}"
            )

        rows = matrix.get("rows", [])

        if (
            len(rows)
            != matrix.get(
                "source_row_count"
            )
        ):
            errors.append(
                "matrix row count mismatch: "
                f"{matrix_record['matrix_path']}"
            )

        row_source_ids = [
            row.get("source_id")
            for row in rows
        ]

        if len(row_source_ids) != len(
            set(row_source_ids)
        ):
            errors.append(
                "matrix contains duplicate source rows: "
                f"{matrix_record['matrix_path']}"
            )

        for row in rows:
            evidence_record = (
                ROOT
                / row[
                    "evidence_record_path"
                ]
            )

            if not evidence_record.is_file():
                errors.append(
                    "matrix references missing evidence: "
                    f"{row['evidence_record_path']}"
                )
                continue

            if (
                sha256_file(evidence_record)
                != row[
                    "evidence_record_sha256"
                ]
            ):
                errors.append(
                    "matrix evidence hash mismatch: "
                    f"{row['evidence_record_path']}"
                )

            if row.get(
                "adjudication_complete"
            ):
                if (
                    row.get("overlap_state")
                    == "UNRESOLVED"
                ):
                    errors.append(
                        "completed matrix row remains unresolved"
                    )

                if not str(
                    row.get(
                        "adjudicator",
                        "",
                    )
                ).strip():
                    errors.append(
                        "completed matrix row lacks adjudicator"
                    )

                confidence = row.get(
                    "confidence"
                )

                if not isinstance(
                    confidence,
                    (int, float),
                ) or not (
                    0.0 <= confidence <= 1.0
                ):
                    errors.append(
                        "completed matrix row has invalid "
                        "confidence"
                    )

    decisions = kill_register.get(
        "decisions",
        [],
    )

    if len(decisions) != EXPECTED_KILL_COUNT:
        errors.append(
            "kill register must contain "
            f"{EXPECTED_KILL_COUNT} decisions"
        )

    kill_claim_ids = {
        decision.get("claim_id")
        for decision in decisions
    }

    if kill_claim_ids != set(
        claim_ids
    ):
        errors.append(
            "kill-decision claim set differs from "
            "claim register"
        )

    if (
        unsupported_register.get(
            "record_count"
        )
        != len(
            unsupported_register.get(
                "records",
                [],
            )
        )
    ):
        errors.append(
            "unsupported field count mismatch"
        )

    if gap_report.get("status") != "OPEN":
        errors.append(
            "Stage 1 must remain OPEN before "
            "scientific adjudication"
        )

    if gap_report.get(
        "closure_marker_emitted"
    ) is not False:
        errors.append(
            "Stage 1 closure marker state "
            "must be false"
        )

    if (
        STAGE1 / "STAGE_01_CLOSED.json"
    ).exists():
        errors.append(
            "Stage 1 closure marker was "
            "emitted prematurely"
        )

    hashes = load_json(hash_path)

    if (
        "artifacts/stage_01/artifact_hashes.json"
        in hashes
    ):
        errors.append(
            "hash manifest contains self-hash"
        )

    for relative_path, expected in hashes.items():
        artifact = ROOT / relative_path

        if not artifact.is_file():
            errors.append(
                "hashed artifact missing: "
                f"{relative_path}"
            )
            continue

        actual = sha256_file(artifact)

        if actual != expected:
            errors.append(
                "artifact hash mismatch: "
                f"{relative_path}"
            )

    if errors:
        print(
            "QUDIPI_STAGE1_SEMANTIC_VALIDATION=FAIL"
        )

        for error in errors:
            print(f"ERROR  {error}")

        return 1

    print(
        "QUDIPI_STAGE1_SEMANTIC_VALIDATION=PASS"
    )

    print(
        f"source_record_count={EXPECTED_SOURCE_COUNT}"
    )

    print(
        f"evidence_record_count={EXPECTED_EVIDENCE_COUNT}"
    )

    print(
        "second_review_record_count="
        f"{EXPECTED_SECOND_REVIEW_COUNT}"
    )

    print(
        f"claim_count={EXPECTED_CLAIM_COUNT}"
    )

    print(
        f"matrix_count={EXPECTED_MATRIX_COUNT}"
    )

    print(
        f"kill_condition_count={EXPECTED_KILL_COUNT}"
    )

    print(
        "stage1_status="
        f"{gap_report['status']}"
    )

    print(
        "remaining_blockers="
        + (
            ",".join(
                gap_report[
                    "remaining_blockers"
                ]
            )
            if gap_report[
                "remaining_blockers"
            ]
            else "none"
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
