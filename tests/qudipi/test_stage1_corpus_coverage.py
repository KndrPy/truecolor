from __future__ import annotations

import hashlib
import json
from pathlib import Path

STAGE1 = Path("artifacts/stage_01")

INSTANCE = (
    STAGE1
    / "truecolor_stage1_instance.json"
)

POLICY = Path(
    "analysis/prior_art/"
    "stage1_closure/"
    "truecolor_stage1_coverage_policy.json"
)


def load_json(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def test_every_governed_source_has_coverage_record() -> None:
    instance = load_json(INSTANCE)

    coverage = load_json(
        STAGE1
        / "corpus_coverage_register.json"
    )

    assert len(
        coverage["records"]
    ) == len(
        instance["corpus"]["members"]
    )


def test_evidence_records_receive_full_extraction_role() -> None:
    instance = load_json(INSTANCE)

    policy = load_json(POLICY)

    coverage = load_json(
        STAGE1
        / "corpus_coverage_register.json"
    )

    coverage_by_identity = {
        record["canonical_identity"]:
            record
        for record in coverage["records"]
    }

    for evidence in instance[
        "evidence_records"
    ]:
        record = coverage_by_identity[
            evidence["canonical_identity"]
        ]

        assert (
            record["coverage_role"]
            == policy[
                "evidence_record_role"
            ]
        )

        assert (
            record["coverage_state"]
            == "TERMINAL"
        )

        assert (
            record[
                "evidence_record_id"
            ]
            == evidence[
                "evidence_record_id"
            ]
        )


def test_non_evidence_sources_are_not_automatically_extraction_gaps() -> None:
    instance = load_json(INSTANCE)

    coverage = load_json(
        STAGE1
        / "corpus_coverage_register.json"
    )

    evidence_identities = {
        record["canonical_identity"]
        for record in instance[
            "evidence_records"
        ]
    }

    non_evidence_records = [
        record
        for record in coverage[
            "records"
        ]
        if record[
            "canonical_identity"
        ]
        not in evidence_identities
    ]

    assert non_evidence_records

    assert all(
        record["coverage_role"]
        != "FULL_SCIENTIFIC_EXTRACTION"
        for record in non_evidence_records
    )


def test_only_explicit_metadata_can_assign_terminal_non_evidence_role() -> None:
    coverage = load_json(
        STAGE1
        / "corpus_coverage_register.json"
    )

    for record in coverage["records"]:
        if (
            record["evidence_record_id"]
            is not None
        ):
            continue

        if (
            record["coverage_state"]
            == "TERMINAL"
        ):
            assert (
                record["derivation"].get(
                    "matched_field"
                )
            )

            assert (
                record["derivation"].get(
                    "matched_value"
                )
                not in {
                    None,
                    "",
                }
            )


def test_obsolete_full_evidence_blocker_is_removed() -> None:
    gap = load_json(
        STAGE1
        / "stage1_gap_report.json"
    )

    assert (
        "governed_corpus_evidence_coverage"
        not in gap[
            "remaining_blockers"
        ]
    )

    assert (
        gap[
            "full_extraction_is_not_required_for_all_governed_sources"
        ]
        is True
    )


def test_pending_dispositions_are_explicit() -> None:
    coverage = load_json(
        STAGE1
        / "corpus_coverage_register.json"
    )

    gap = load_json(
        STAGE1
        / "corpus_coverage_gap_report.json"
    )

    pending = [
        record
        for record in coverage["records"]
        if (
            record["coverage_state"]
            == "PENDING"
        )
    ]

    assert len(pending) == (
        gap[
            "pending_disposition_count"
        ]
    )

    for record in pending:
        assert (
            record["coverage_role"]
            == "REVIEW_DISPOSITION_REQUIRED"
        )


def test_coverage_artifacts_are_hash_bound() -> None:
    hashes = load_json(
        STAGE1
        / "artifact_hashes.json"
    )

    required = {
        "artifacts/stage_01/"
        "corpus_coverage_register.json",
        "artifacts/stage_01/"
        "corpus_coverage_gap_report.json",
    }

    assert required <= set(
        hashes
    )

    for relative_path in required:
        path = Path(relative_path)

        actual = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

        assert actual == hashes[
            relative_path
        ]


def test_stage1_remains_open() -> None:
    gap = load_json(
        STAGE1
        / "stage1_gap_report.json"
    )

    assert gap["stage_state"] == "OPEN"

    assert not (
        STAGE1
        / "STAGE_01_CLOSED.json"
    ).exists()
