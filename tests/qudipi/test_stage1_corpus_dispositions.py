from __future__ import annotations

import hashlib
import json
from pathlib import Path

STAGE1 = Path("artifacts/stage_01")

INSTANCE = (
    STAGE1
    / "truecolor_stage1_instance.json"
)

CONFIG = Path(
    "analysis/prior_art/"
    "stage1_closure/"
    "truecolor_stage1_disposition_sources.json"
)


def load_json(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def test_reconciliation_preserves_governed_corpus() -> None:
    instance = load_json(INSTANCE)

    coverage = load_json(
        STAGE1
        / "corpus_coverage_register.json"
    )

    governed = {
        member["canonical_identity"]
        for member
        in instance["corpus"]["members"]
    }

    covered = {
        record["canonical_identity"]
        for record in coverage["records"]
    }

    assert governed == covered


def test_explicit_artifact_dispositions_are_evidence_bound() -> None:
    coverage = load_json(
        STAGE1
        / "corpus_coverage_register.json"
    )

    evidence = load_json(
        STAGE1
        / "corpus_disposition_evidence_register.json"
    )

    observations = {
        item["observation_id"]:
            item
        for item in evidence[
            "observations"
        ]
    }

    for record in coverage["records"]:
        derivation = record.get(
            "derivation",
            {},
        )

        if (
            derivation.get("method")
            != (
                "explicit_existing_"
                "artifact_disposition"
            )
        ):
            continue

        observation = observations[
            derivation["observation_id"]
        ]

        assert (
            observation[
                "observation_state"
            ]
            == "MAPPED"
        )

        assert (
            record["coverage_role"]
            == observation[
                "mapped_role"
            ]
        )


def test_fuzzy_and_title_matching_are_prohibited() -> None:
    config = load_json(CONFIG)

    policy = config[
        "identity_policy"
    ]

    assert (
        policy[
            "exact_canonical_identity_only"
        ]
        is True
    )

    assert (
        policy[
            "title_matching_prohibited"
        ]
        is True
    )

    assert (
        policy[
            "fuzzy_matching_prohibited"
        ]
        is True
    )


def test_unmapped_values_remain_visible() -> None:
    unmapped = load_json(
        STAGE1
        / "corpus_disposition_unmapped_report.json"
    )

    gap = load_json(
        STAGE1
        / "stage1_gap_report.json"
    )

    if unmapped["identity_count"]:
        assert (
            "unmapped_explicit_corpus_dispositions"
            in gap["remaining_blockers"]
        )


def test_conflicts_do_not_resolve_automatically() -> None:
    conflicts = load_json(
        STAGE1
        / "corpus_disposition_conflict_report.json"
    )

    coverage = load_json(
        STAGE1
        / "corpus_coverage_register.json"
    )

    coverage_by_identity = {
        record["canonical_identity"]:
            record
        for record in coverage["records"]
    }

    for conflict in conflicts["conflicts"]:
        record = coverage_by_identity[
            conflict["canonical_identity"]
        ]

        assert (
            record["coverage_state"]
            == "PENDING"
        )

        assert (
            record["coverage_role"]
            == "REVIEW_DISPOSITION_REQUIRED"
        )


def test_disposition_artifacts_are_hash_bound() -> None:
    hashes = load_json(
        STAGE1
        / "artifact_hashes.json"
    )

    required = {
        "artifacts/stage_01/"
        "corpus_disposition_evidence_register.json",
        "artifacts/stage_01/"
        "corpus_disposition_reconciliation_report.json",
        "artifacts/stage_01/"
        "corpus_disposition_conflict_report.json",
        "artifacts/stage_01/"
        "corpus_disposition_unmapped_report.json",
    }

    assert required <= set(hashes)

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
