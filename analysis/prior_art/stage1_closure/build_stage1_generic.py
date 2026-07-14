from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

TERMINAL_OVERLAP_STATES = {
    "NO_MATERIAL_OVERLAP",
    "BACKGROUND_ONLY",
    "COMPONENT_OVERLAP",
    "SUBSTANTIAL_OVERLAP",
    "ANTICIPATED_BY_PRIOR_ART",
    "POTENTIALLY_NOVEL_COMBINATION",
    "POTENTIALLY_NOVEL_ESTIMAND",
    "POTENTIALLY_NOVEL_VALIDATION",
}

UNRESOLVED_OVERLAP_STATES = {
    "",
    "NOT_ADJUDICATED",
    "UNRESOLVED",
    None,
}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build generic QuDiPi Stage 1 "
            "control artifacts from a compiled "
            "research-pack instance."
        )
    )

    parser.add_argument(
        "--manifest",
        required=True,
    )

    parser.add_argument(
        "--output",
        required=True,
    )

    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def write_json(
    path: Path,
    value: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def stable_id(
    prefix: str,
    *values: str,
) -> str:
    material = "\x1f".join(values)

    suffix = hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()[:16]

    return f"{prefix}-{suffix}"


def normalize_overlap_state(
    observation: dict[str, Any],
) -> str:
    candidates = (
        observation.get(
            "overlap_state"
        ),
        observation.get(
            "overlap_classification"
        ),
        observation.get("state"),
    )

    for candidate in candidates:
        if candidate in TERMINAL_OVERLAP_STATES:
            return str(candidate)

    return "UNRESOLVED"


def primary_review_required(
    record: dict[str, Any],
    manifest: dict[str, Any],
) -> bool:
    rule = (
        manifest[
            "review_policy"
        ][
            "primary_review"
        ][
            "required_when"
        ]
    )

    allowed_eligibility = set(
        rule.get(
            "review_eligibility",
            [],
        )
    )

    review_state = record[
        "review_state"
    ]

    return (
        record.get(
            "review_eligibility"
        )
        in allowed_eligibility
        and not review_state.get(
            "primary_review_completed"
        )
    )


def second_review_required(
    record: dict[str, Any],
    manifest: dict[str, Any],
) -> bool:
    required_source_ids = set(
        manifest[
            "review_policy"
        ][
            "independent_second_review"
        ].get(
            "required_source_ids",
            [],
        )
    )

    return (
        record["source_id"]
        in required_source_ids
        and not record[
            "review_state"
        ].get(
            "second_review_completed"
        )
    )


def build_review_task(
    *,
    record: dict[str, Any],
    task_type: str,
    review_policy_id: str,
    independence_required: bool,
) -> dict[str, Any]:
    task_id = stable_id(
        "REVIEW",
        task_type,
        record["evidence_record_id"],
    )

    return {
        "task_id": task_id,
        "task_type": task_type,
        "task_state": "PENDING_REVIEW",
        "evidence_record_id":
            record["evidence_record_id"],
        "source_id":
            record["source_id"],
        "canonical_identity":
            record["canonical_identity"],
        "claim_ids":
            record["claim_ids"],
        "review_policy_id":
            review_policy_id,
        "required_independence":
            independence_required,
        "source_bindings":
            record["source_bindings"],
        "review_output": {
            "reviewer": None,
            "field_dispositions": [],
            "claim_observations": [],
            "discrepancies": [],
            "review_started_at": None,
            "review_completed_at": None,
            "final_review_state": None,
            "attestation": None,
        },
    }


def main() -> None:
    arguments = parse_arguments()

    manifest_path = Path(
        arguments.manifest
    ).resolve()

    output_directory = Path(
        arguments.output
    ).resolve()

    matrix_directory = (
        output_directory
        / "claim_matrices"
    )

    task_directory = (
        output_directory
        / "review_tasks"
    )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    matrix_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    task_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    for path in matrix_directory.glob(
        "*.json"
    ):
        path.unlink()

    for path in task_directory.glob(
        "*.json"
    ):
        path.unlink()

    manifest = read_json(
        manifest_path
    )

    if (
        manifest.get("schema_id")
        != "qudipi.stage1.compiled-instance"
    ):
        raise RuntimeError(
            "invalid compiled Stage 1 instance"
        )

    claims = manifest.get(
        "claims",
        [],
    )

    evidence_records = manifest.get(
        "evidence_records",
        [],
    )

    corpus_members = (
        manifest.get(
            "corpus",
            {},
        ).get(
            "members",
            [],
        )
    )

    claim_ids = [
        claim["claim_id"]
        for claim in claims
    ]

    if len(claim_ids) != len(
        set(claim_ids)
    ):
        raise RuntimeError(
            "duplicate configured claim IDs"
        )

    source_ids = [
        record["source_id"]
        for record in evidence_records
    ]

    if len(source_ids) != len(
        set(source_ids)
    ):
        raise RuntimeError(
            "duplicate configured source IDs"
        )

    evidence_ids = [
        record["evidence_record_id"]
        for record in evidence_records
    ]

    if len(evidence_ids) != len(
        set(evidence_ids)
    ):
        raise RuntimeError(
            "duplicate evidence-record IDs"
        )

    allowed_field_states = set(
        manifest[
            "evidence_schema"
        ][
            "allowed_field_states"
        ]
    )

    unknown_field_states = []

    for record in evidence_records:
        for observation in record[
            "field_observations"
        ]:
            if (
                observation.get("state")
                not in allowed_field_states
            ):
                unknown_field_states.append(
                    {
                        "evidence_record_id":
                            record[
                                "evidence_record_id"
                            ],
                        "field_id":
                            observation[
                                "field_id"
                            ],
                        "state":
                            observation.get(
                                "state"
                            ),
                    }
                )

    if unknown_field_states:
        raise RuntimeError(
            "configured evidence records contain "
            "unregistered field states: "
            + json.dumps(
                unknown_field_states,
                sort_keys=True,
            )
        )

    evidence_identity_set = {
        record[
            "canonical_identity"
        ]
        for record in evidence_records
    }

    governed_identity_set = {
        member[
            "canonical_identity"
        ]
        for member in corpus_members
        if (
            "GOVERNED_CORPUS"
            in member.get(
                "membership_roles",
                [],
            )
        )
    }

    uncovered_governed_sources = sorted(
        governed_identity_set
        - evidence_identity_set
    )

    source_register = {
        "register_schema":
            "qudipi.stage1.source-register",
        "register_version": 1,
        "research_pack_id":
            manifest["research_pack_id"],
        "study_id":
            manifest["study_id"],
        "configured_source_count":
            len(corpus_members),
        "evidence_covered_source_count":
            len(
                governed_identity_set
                & evidence_identity_set
            ),
        "uncovered_governed_source_count":
            len(
                uncovered_governed_sources
            ),
        "uncovered_governed_sources":
            uncovered_governed_sources,
        "records": corpus_members,
    }

    write_json(
        output_directory
        / "source_register.json",
        source_register,
    )

    evidence_register_records = []

    unsupported_fields = []
    pending_fields = []

    for record in evidence_records:
        supported_count = 0
        unsupported_count = 0
        pending_count = 0

        for observation in record[
            "field_observations"
        ]:
            state = observation[
                "state"
            ]

            if state == (
                "ESTABLISHED_FROM_SOURCE"
            ):
                supported_count += 1

            if state == (
                "NOT_ESTABLISHED_FROM_"
                "AVAILABLE_SOURCE"
            ):
                unsupported_count += 1

                unsupported_fields.append(
                    {
                        "unsupported_field_id":
                            stable_id(
                                "UNSUPPORTED",
                                record[
                                    "evidence_record_id"
                                ],
                                observation[
                                    "field_id"
                                ],
                            ),
                        "evidence_record_id":
                            record[
                                "evidence_record_id"
                            ],
                        "source_id":
                            record[
                                "source_id"
                            ],
                        "field_id":
                            observation[
                                "field_id"
                            ],
                        "review_notes":
                            observation.get(
                                "review_notes"
                            ),
                    }
                )

            if state in {
                "PENDING_SOURCE_REVIEW",
                "UNRESOLVED",
            }:
                pending_count += 1

                pending_fields.append(
                    {
                        "pending_field_id":
                            stable_id(
                                "PENDING",
                                record[
                                    "evidence_record_id"
                                ],
                                observation[
                                    "field_id"
                                ],
                            ),
                        "evidence_record_id":
                            record[
                                "evidence_record_id"
                            ],
                        "source_id":
                            record[
                                "source_id"
                            ],
                        "field_id":
                            observation[
                                "field_id"
                            ],
                        "state": state,
                    }
                )

        evidence_register_records.append(
            {
                **record,
                "supported_field_count":
                    supported_count,
                "unsupported_field_count":
                    unsupported_count,
                "pending_field_count":
                    pending_count,
            }
        )

    write_json(
        output_directory
        / "evidence_register.json",
        {
            "register_schema":
                "qudipi.stage1.evidence-register",
            "register_version": 1,
            "configured_record_count":
                len(evidence_records),
            "records":
                evidence_register_records,
        },
    )

    write_json(
        output_directory
        / "unsupported_field_register.json",
        {
            "register_schema":
                "qudipi.stage1.unsupported-field-register",
            "register_version": 1,
            "record_count":
                len(unsupported_fields),
            "records":
                unsupported_fields,
        },
    )

    write_json(
        output_directory
        / "pending_field_register.json",
        {
            "register_schema":
                "qudipi.stage1.pending-field-register",
            "register_version": 1,
            "record_count":
                len(pending_fields),
            "records":
                pending_fields,
        },
    )

    review_tasks = []

    review_policy_id = (
        manifest[
            "review_policy"
        ][
            "policy_id"
        ]
    )

    independence_required = bool(
        manifest[
            "review_policy"
        ][
            "independent_second_review"
        ].get(
            "independence_required"
        )
    )

    for record in evidence_records:
        if primary_review_required(
            record,
            manifest,
        ):
            review_tasks.append(
                build_review_task(
                    record=record,
                    task_type=(
                        "PRIMARY_SCIENTIFIC_REVIEW"
                    ),
                    review_policy_id=
                        review_policy_id,
                    independence_required=False,
                )
            )

        if second_review_required(
            record,
            manifest,
        ):
            review_tasks.append(
                build_review_task(
                    record=record,
                    task_type=(
                        "INDEPENDENT_SECOND_REVIEW"
                    ),
                    review_policy_id=
                        review_policy_id,
                    independence_required=
                        independence_required,
                )
            )

    review_task_records = []

    for task in review_tasks:
        task_path = (
            task_directory
            / (
                task["task_id"]
                .lower()
                .replace("-", "_")
                + ".json"
            )
        )

        write_json(
            task_path,
            task,
        )

        review_task_records.append(
            {
                "task_id":
                    task["task_id"],
                "task_type":
                    task["task_type"],
                "task_state":
                    task["task_state"],
                "source_id":
                    task["source_id"],
                "evidence_record_id":
                    task[
                        "evidence_record_id"
                    ],
                "task_path":
                    task_path.relative_to(
                        ROOT
                    ).as_posix(),
                "task_sha256":
                    sha256_file(task_path),
            }
        )

    write_json(
        output_directory
        / "review_register.json",
        {
            "register_schema":
                "qudipi.stage1.review-register",
            "register_version": 1,
            "configured_review_policy_id":
                review_policy_id,
            "pending_task_count":
                len(review_task_records),
            "completed_task_count": 0,
            "tasks":
                review_task_records,
        },
    )

    evidence_by_claim: dict[
        str,
        list[dict[str, Any]],
    ] = {
        claim_id: []
        for claim_id in claim_ids
    }

    for record in evidence_records:
        observations_by_claim = {
            observation.get(
                "claim_id"
            ): observation
            for observation
            in record.get(
                "claim_observations",
                [],
            )
            if isinstance(
                observation,
                dict,
            )
        }

        for claim_id in record[
            "claim_ids"
        ]:
            if claim_id not in (
                evidence_by_claim
            ):
                continue

            raw_observation = (
                observations_by_claim.get(
                    claim_id,
                    {},
                )
            )

            overlap_state = (
                normalize_overlap_state(
                    raw_observation
                )
            )

            evidence_by_claim[
                claim_id
            ].append(
                {
                    "matrix_row_id":
                        stable_id(
                            "MATRIXROW",
                            claim_id,
                            record[
                                "source_id"
                            ],
                        ),
                    "claim_id":
                        claim_id,
                    "source_id":
                        record[
                            "source_id"
                        ],
                    "evidence_record_id":
                        record[
                            "evidence_record_id"
                        ],
                    "canonical_identity":
                        record[
                            "canonical_identity"
                        ],
                    "overlap_state":
                        overlap_state,
                    "overlapping_elements":
                        raw_observation.get(
                            "overlapping_elements",
                            [],
                        ),
                    "non_overlapping_elements":
                        raw_observation.get(
                            "non_overlapping_elements",
                            [],
                        ),
                    "evidence_spans":
                        raw_observation.get(
                            "evidence",
                            [],
                        ),
                    "source_limitation":
                        raw_observation.get(
                            "source_limitation"
                        ),
                    "confidence":
                        raw_observation.get(
                            "confidence"
                        ),
                    "adjudicator":
                        raw_observation.get(
                            "adjudicator"
                        ),
                    "review_status": (
                        "COMPLETE"
                        if overlap_state
                        in TERMINAL_OVERLAP_STATES
                        else "PENDING"
                    ),
                }
            )

    matrix_register_records = []

    for claim in claims:
        claim_id = claim[
            "claim_id"
        ]

        rows = sorted(
            evidence_by_claim[
                claim_id
            ],
            key=lambda row: (
                row["source_id"]
            ),
        )

        pending_rows = [
            row
            for row in rows
            if row[
                "review_status"
            ] != "COMPLETE"
        ]

        matrix = {
            "matrix_schema":
                "qudipi.stage1.claim-evidence-matrix",
            "matrix_version": 1,
            "matrix_id":
                stable_id(
                    "MATRIX",
                    claim_id,
                ),
            "claim": claim,
            "row_count": len(rows),
            "completed_row_count":
                len(rows) - len(pending_rows),
            "pending_row_count":
                len(pending_rows),
            "matrix_state": (
                "COMPLETE"
                if rows
                and not pending_rows
                else "OPEN"
            ),
            "rows": rows,
        }

        matrix_path = (
            matrix_directory
            / (
                stable_id(
                    "claim",
                    claim_id,
                ).lower()
                + ".json"
            )
        )

        write_json(
            matrix_path,
            matrix,
        )

        matrix_register_records.append(
            {
                "matrix_id":
                    matrix["matrix_id"],
                "claim_id": claim_id,
                "matrix_state":
                    matrix[
                        "matrix_state"
                    ],
                "row_count":
                    matrix["row_count"],
                "completed_row_count":
                    matrix[
                        "completed_row_count"
                    ],
                "pending_row_count":
                    matrix[
                        "pending_row_count"
                    ],
                "matrix_path":
                    matrix_path.relative_to(
                        ROOT
                    ).as_posix(),
                "matrix_sha256":
                    sha256_file(
                        matrix_path
                    ),
            }
        )

    write_json(
        output_directory
        / "claim_matrix_register.json",
        {
            "register_schema":
                "qudipi.stage1.claim-matrix-register",
            "register_version": 1,
            "configured_claim_count":
                len(claims),
            "matrix_count":
                len(
                    matrix_register_records
                ),
            "completed_matrix_count":
                sum(
                    1
                    for record
                    in matrix_register_records
                    if record[
                        "matrix_state"
                    ]
                    == "COMPLETE"
                ),
            "matrices":
                matrix_register_records,
        },
    )

    kill_decisions = [
        {
            "kill_decision_id":
                stable_id(
                    "KILL",
                    claim["claim_id"],
                ),
            "claim_id":
                claim["claim_id"],
            "kill_condition":
                claim.get(
                    "kill_condition"
                ),
            "decision_state":
                "PENDING",
            "decision": None,
            "decision_basis": [],
            "adjudicator": None,
            "confidence": None,
        }
        for claim in claims
    ]

    write_json(
        output_directory
        / "novelty_kill_register.json",
        {
            "register_schema":
                "qudipi.stage1.novelty-kill-register",
            "register_version": 1,
            "configured_decision_count":
                len(kill_decisions),
            "completed_decision_count": 0,
            "decisions":
                kill_decisions,
        },
    )

    synthesis_register = {
        "register_schema":
            "qudipi.stage1.synthesis-register",
        "register_version": 1,
        "required_syntheses": [
            {
                "synthesis_id":
                    "SOURCE_AND_METHOD",
                "state": "PENDING"
            },
            {
                "synthesis_id":
                    "ASSUMPTION",
                "state": "PENDING"
            },
            {
                "synthesis_id":
                    "FRAMING",
                "state": "PENDING"
            },
            {
                "synthesis_id":
                    "REGIME",
                "state": "PENDING"
            },
            {
                "synthesis_id":
                    "MATERIAL_LINEAGE",
                "state": "PENDING"
            },
            {
                "synthesis_id":
                    "CONTRADICTION_AND_QUALIFICATION",
                "state": "PENDING"
            },
            {
                "synthesis_id":
                    "NOVELTY_FRONTIER",
                "state": "PENDING"
            },
            {
                "synthesis_id":
                    "GAP_REGISTER",
                "state": "PENDING"
            }
        ],
    }

    write_json(
        output_directory
        / "synthesis_register.json",
        synthesis_register,
    )

    blockers = []

    if uncovered_governed_sources:
        blockers.append(
            "governed_corpus_evidence_coverage"
        )

    if any(
        task["task_type"]
        == "PRIMARY_SCIENTIFIC_REVIEW"
        for task in review_tasks
    ):
        blockers.append(
            "primary_scientific_reviews"
        )

    if any(
        task["task_type"]
        == "INDEPENDENT_SECOND_REVIEW"
        for task in review_tasks
    ):
        blockers.append(
            "independent_second_reviews"
        )

    if any(
        record["matrix_state"]
        != "COMPLETE"
        for record
        in matrix_register_records
    ):
        blockers.append(
            "claim_overlap_adjudication"
        )

    if kill_decisions:
        blockers.append(
            "novelty_kill_decisions"
        )

    blockers.append(
        "full_corpus_synthesis"
    )

    blockers = list(
        dict.fromkeys(blockers)
    )

    gap_report = {
        "report_schema":
            "qudipi.stage1.gap-report",
        "report_version": 1,
        "research_pack_id":
            manifest["research_pack_id"],
        "study_id":
            manifest["study_id"],
        "stage_id": 1,
        "stage_key": "prior_art",
        "stage_state": "OPEN",
        "closure_marker_emitted": False,
        "configured_governed_source_count":
            len(governed_identity_set),
        "evidence_covered_source_count":
            len(
                governed_identity_set
                & evidence_identity_set
            ),
        "configured_evidence_record_count":
            len(evidence_records),
        "configured_claim_count":
            len(claims),
        "pending_review_task_count":
            len(review_tasks),
        "configured_matrix_count":
            len(
                matrix_register_records
            ),
        "completed_matrix_count":
            sum(
                1
                for record
                in matrix_register_records
                if record[
                    "matrix_state"
                ]
                == "COMPLETE"
            ),
        "completed_kill_decision_count":
            0,
        "remaining_blockers":
            blockers,
        "prohibited_actions": [
            "hard-code corpus size",
            "hard-code paper identity",
            "hard-code claim count",
            "hard-code review count",
            "infer scientific facts from title or metadata",
            "infer novelty from corpus absence",
            "autonomously adjudicate novelty",
            "emit Stage 1 closure before configured obligations pass",
        ],
    }

    write_json(
        output_directory
        / "stage1_gap_report.json",
        gap_report,
    )

    run_manifest = {
        "run_schema":
            "qudipi.stage1.generic-build-run",
        "run_version": 1,
        "status": "PASS",
        "compiled_instance_path":
            manifest_path.relative_to(
                ROOT
            ).as_posix(),
        "compiled_instance_sha256":
            sha256_file(
                manifest_path
            ),
        "output_directory":
            output_directory.relative_to(
                ROOT
            ).as_posix(),
        "configured_counts": {
            "governed_sources":
                len(
                    governed_identity_set
                ),
            "evidence_records":
                len(evidence_records),
            "claims":
                len(claims),
            "review_tasks":
                len(review_tasks),
            "matrices":
                len(
                    matrix_register_records
                ),
            "kill_decisions":
                len(kill_decisions),
        },
    }

    write_json(
        output_directory
        / "stage1_generic_build_run.json",
        run_manifest,
    )

    hash_manifest_path = (
        output_directory
        / "artifact_hashes.json"
    )

    hashes = {}

    for path in sorted(
        output_directory.rglob(
            "*.json"
        )
    ):
        if path == hash_manifest_path:
            continue

        hashes[
            path.relative_to(
                ROOT
            ).as_posix()
        ] = sha256_file(path)

    write_json(
        hash_manifest_path,
        hashes,
    )

    print(
        "QUDIPI_STAGE1_GENERIC_BUILD=PASS"
    )

    print(
        "configured_governed_source_count="
        f"{len(governed_identity_set)}"
    )

    print(
        "configured_evidence_record_count="
        f"{len(evidence_records)}"
    )

    print(
        "configured_claim_count="
        f"{len(claims)}"
    )

    print(
        "pending_review_task_count="
        f"{len(review_tasks)}"
    )

    print(
        "configured_matrix_count="
        f"{len(matrix_register_records)}"
    )

    print(
        "remaining_blockers="
        + ",".join(blockers)
    )

    print("stage1_state=OPEN")


if __name__ == "__main__":
    main()
