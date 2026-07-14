from __future__ import annotations

import hashlib
import json
from pathlib import Path

STAGE1 = Path("artifacts/stage_01")

INSTANCE = (
    STAGE1
    / "truecolor_stage1_instance.json"
)


def load_json(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def test_compiled_instance_is_authoritative() -> None:
    instance = load_json(INSTANCE)

    assert (
        instance["schema_id"]
        == "qudipi.stage1.compiled-instance"
    )

    assert instance["research_pack_id"]
    assert instance["study_id"]
    assert instance["corpus"]["members"]
    assert instance["claims"]
    assert instance["evidence_records"]


def test_runtime_counts_derive_from_manifest() -> None:
    instance = load_json(INSTANCE)

    sources = load_json(
        STAGE1 / "source_register.json"
    )

    evidence = load_json(
        STAGE1 / "evidence_register.json"
    )

    matrices = load_json(
        STAGE1
        / "claim_matrix_register.json"
    )

    kills = load_json(
        STAGE1
        / "novelty_kill_register.json"
    )

    assert (
        sources["configured_source_count"]
        == len(
            instance["corpus"]["members"]
        )
    )

    assert (
        evidence["configured_record_count"]
        == len(
            instance["evidence_records"]
        )
    )

    assert (
        matrices["configured_claim_count"]
        == len(instance["claims"])
    )

    assert (
        matrices["matrix_count"]
        == len(instance["claims"])
    )

    assert (
        kills["configured_decision_count"]
        == len(instance["claims"])
    )


def test_one_matrix_exists_per_configured_claim() -> None:
    instance = load_json(INSTANCE)

    matrices = load_json(
        STAGE1
        / "claim_matrix_register.json"
    )

    configured_claim_ids = {
        claim["claim_id"]
        for claim in instance["claims"]
    }

    matrix_claim_ids = {
        matrix["claim_id"]
        for matrix in matrices[
            "matrices"
        ]
    }

    assert (
        matrix_claim_ids
        == configured_claim_ids
    )


def test_review_queue_is_record_derived() -> None:
    instance = load_json(INSTANCE)

    review_register = load_json(
        STAGE1
        / "review_register.json"
    )

    evidence_by_id = {
        record["evidence_record_id"]:
            record
        for record
        in instance["evidence_records"]
    }

    for task_record in review_register[
        "tasks"
    ]:
        task = load_json(
            Path(task_record["task_path"])
        )

        assert (
            task["evidence_record_id"]
            in evidence_by_id
        )

        assert (
            task["task_state"]
            == "PENDING_REVIEW"
        )

        assert (
            task["review_output"][
                "reviewer"
            ]
            is None
        )


def test_evidence_records_are_hash_bound() -> None:
    instance = load_json(INSTANCE)

    for record in instance[
        "evidence_records"
    ]:
        path = Path(
            record["record_path"]
        )

        assert path.is_file()

        actual = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

        assert (
            actual
            == record["record_sha256"]
        )


def test_generic_code_has_no_instance_counts() -> None:
    generic_paths = [
        Path(
            "analysis/prior_art/"
            "stage1_closure/"
            "build_stage1_generic.py"
        ),
        Path(
            "analysis/prior_art/"
            "stage1_closure/"
            "validate_stage1_generic.py"
        ),
    ]

    prohibited = [
        "EXPECTED_PAPER_COUNT",
        "EXPECTED_CLAIM_COUNT",
        "EXPECTED_SECOND_REVIEW_COUNT",
        "paper-05",
        "paper_five",
        "test_primary_task_is_paper_five",
    ]

    for path in generic_paths:
        text = path.read_text(
            encoding="utf-8"
        )

        for token in prohibited:
            assert token not in text


def test_stage1_remains_open() -> None:
    report = load_json(
        STAGE1
        / "stage1_gap_report.json"
    )

    assert report["stage_id"] == 1
    assert report["stage_state"] == "OPEN"

    assert (
        report[
            "closure_marker_emitted"
        ]
        is False
    )

    assert not (
        STAGE1
        / "STAGE_01_CLOSED.json"
    ).exists()

    assert report[
        "remaining_blockers"
    ]


def test_stage1_artifact_hashes_validate() -> None:
    hashes = load_json(
        STAGE1
        / "artifact_hashes.json"
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


def _manifest_records(value: object) -> list[dict[str, object]]:
    if isinstance(value, list):
        return [
            record
            for record in value
            if isinstance(record, dict)
        ]

    if not isinstance(value, dict):
        return []

    for key in (
        "records",
        "papers",
        "sources",
        "cohort",
        "review_cohort",
        "claim_review_cohort",
        "items",
    ):
        child = value.get(key)

        if isinstance(child, list):
            records = [
                record
                for record in child
                if isinstance(record, dict)
            ]

            if records:
                return records

    candidate_lists = [
        child
        for child in value.values()
        if isinstance(child, list)
        and child
        and all(
            isinstance(record, dict)
            for record in child
        )
    ]

    if len(candidate_lists) == 1:
        return candidate_lists[0]

    return []


def test_governed_corpus_uses_configured_review_cohort() -> None:
    instance = load_json(INSTANCE)

    authority = instance[
        "source_authorities"
    ]["governed_corpus"]

    authority_path = Path(
        authority["path"]
    )

    assert authority_path.is_file()

    authority_document = load_json(
        authority_path
    )

    authority_records = _manifest_records(
        authority_document
    )

    assert authority_records

    governed_identities = {
        member["canonical_identity"]
        for member
        in instance["corpus"]["members"]
        if (
            "GOVERNED_CORPUS"
            in member["membership_roles"]
        )
    }

    evidence_identities = {
        record["canonical_identity"]
        for record
        in instance["evidence_records"]
    }

    assert governed_identities
    assert evidence_identities <= governed_identities


def test_candidate_pool_is_not_corpus_authority() -> None:
    instance = load_json(INSTANCE)

    configured_path = instance[
        "source_authorities"
    ]["governed_corpus"]["path"]

    assert not configured_path.endswith(
        "stage1_canonical_adjudication_cohort.csv"
    )

    assert configured_path.endswith(
        "stage1_claim_review_cohort_final.json"
    )
