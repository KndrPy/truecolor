from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

STAGE1 = Path("artifacts/stage_01")

CLAIM_ID_PATTERN = re.compile(
    r"^TC-NOV-[0-9]{3}$"
)

SOURCE_ID_PATTERN = re.compile(
    r"^PA-[0-9]{4}$"
)


def load_json(name: str) -> object:
    return json.loads(
        (STAGE1 / name).read_text(
            encoding="utf-8"
        )
    )


def test_semantic_source_and_evidence_counts() -> None:
    sources = load_json(
        "source_register.json"
    )

    evidence = load_json(
        "evidence_register.json"
    )

    assert sources["record_count"] == 16
    assert len(sources["records"]) == 16

    assert evidence["record_count"] == 16
    assert len(evidence["records"]) == 16


def test_source_ids_are_unique_and_canonical() -> None:
    sources = load_json(
        "source_register.json"
    )

    source_ids = [
        record["source_id"]
        for record in sources["records"]
    ]

    assert len(source_ids) == len(
        set(source_ids)
    )

    assert all(
        SOURCE_ID_PATTERN.fullmatch(
            source_id
        )
        for source_id in source_ids
    )


def test_six_claims_have_six_matrices() -> None:
    claims = load_json(
        "claim_register.json"
    )

    matrices = load_json(
        "claim_matrix_register.json"
    )

    claim_ids = {
        claim["claim_id"]
        for claim in claims["claims"]
    }

    matrix_claim_ids = {
        matrix["claim_id"]
        for matrix in matrices[
            "matrices"
        ]
    }

    assert len(claim_ids) == 6
    assert len(matrix_claim_ids) == 6
    assert claim_ids == matrix_claim_ids

    assert all(
        CLAIM_ID_PATTERN.fullmatch(
            claim_id
        )
        for claim_id in claim_ids
    )


def test_matrix_rows_are_evidence_hash_bound() -> None:
    matrices = load_json(
        "claim_matrix_register.json"
    )

    for matrix_record in matrices[
        "matrices"
    ]:
        matrix_path = Path(
            matrix_record["matrix_path"]
        )

        assert matrix_path.is_file()

        matrix_hash = hashlib.sha256(
            matrix_path.read_bytes()
        ).hexdigest()

        assert matrix_hash == matrix_record[
            "matrix_sha256"
        ]

        matrix = json.loads(
            matrix_path.read_text(
                encoding="utf-8"
            )
        )

        for row in matrix["rows"]:
            evidence_path = Path(
                row["evidence_record_path"]
            )

            assert evidence_path.is_file()

            evidence_hash = hashlib.sha256(
                evidence_path.read_bytes()
            ).hexdigest()

            assert evidence_hash == row[
                "evidence_record_sha256"
            ]


def test_second_review_cohort_is_exact() -> None:
    register = load_json(
        "second_review_register.json"
    )

    assert (
        register["expected_record_count"]
        == 5
    )

    assert register["record_count"] == 5

    review_ids = [
        record["review_id"]
        for record in register["records"]
    ]

    assert len(review_ids) == len(
        set(review_ids)
    )


def test_kill_register_matches_claim_registry() -> None:
    claims = load_json(
        "claim_register.json"
    )

    kills = load_json(
        "novelty_kill_register.json"
    )

    claim_ids = {
        claim["claim_id"]
        for claim in claims["claims"]
    }

    kill_claim_ids = {
        decision["claim_id"]
        for decision in kills[
            "decisions"
        ]
    }

    assert len(kill_claim_ids) == 6
    assert claim_ids == kill_claim_ids


def test_unsupported_fields_are_explicit() -> None:
    register = load_json(
        "unsupported_field_register.json"
    )

    assert register["record_count"] == len(
        register["records"]
    )

    for record in register["records"]:
        assert (
            record["state"]
            == (
                "NOT_ESTABLISHED_FROM_"
                "AVAILABLE_SOURCE"
            )
        )

        assert record["field_name"]
        assert record["source_id"]
        assert record[
            "evidence_record_path"
        ]


def test_stage1_remains_open_before_adjudication() -> None:
    report = load_json(
        "stage1_gap_report.json"
    )

    assert report["stage_id"] == 1
    assert report["stage_key"] == "prior_art"
    assert report["status"] == "OPEN"

    assert report[
        "closure_marker_emitted"
    ] is False

    assert not (
        STAGE1 / "STAGE_01_CLOSED.json"
    ).exists()

    assert (
        "claim_overlap_adjudication"
        in report["remaining_blockers"]
    )

    assert (
        "novelty_kill_decisions"
        in report["remaining_blockers"]
    )


def test_stage1_artifact_hashes_are_valid() -> None:
    hashes = load_json(
        "artifact_hashes.json"
    )

    assert (
        "artifacts/stage_01/"
        "artifact_hashes.json"
        not in hashes
    )

    for relative_path, expected in (
        hashes.items()
    ):
        path = Path(relative_path)

        assert path.is_file()

        actual = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

        assert actual == expected


def test_pending_review_fields_are_explicit() -> None:
    evidence = load_json(
        "evidence_register.json"
    )

    paper_five = next(
        record
        for record in evidence["records"]
        if record["acquisition_order"] == 5
    )

    assert (
        paper_five["review_eligibility"]
        == "BOUNDED"
    )

    assert (
        paper_five["primary_review_completed"]
        is False
    )

    assert paper_five["pending_field_count"] == 24


def test_semantic_run_has_no_contract_errors() -> None:
    run = load_json(
        "stage1_semantic_ledger_run.json"
    )

    gap = load_json(
        "stage1_gap_report.json"
    )

    assert run["status"] == "PASS"
    assert gap["semantic_contract_errors"] == []


def test_primary_review_blocker_is_record_derived() -> None:
    evidence = load_json(
        "evidence_register.json"
    )

    gap = load_json(
        "stage1_gap_report.json"
    )

    pending_reviewable = [
        record
        for record in evidence["records"]
        if (
            not record[
                "primary_review_completed"
            ]
            and record[
                "review_eligibility"
            ]
            in {
                "COMPLETE",
                "BOUNDED",
            }
        )
    ]

    assert pending_reviewable

    assert (
        "primary_scientific_reviews"
        in gap["remaining_blockers"]
    )
