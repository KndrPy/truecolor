from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

PRIOR_ART = ROOT / "analysis" / "prior_art"
STAGE1 = ROOT / "artifacts" / "stage_01"
TASK_DIRECTORY = STAGE1 / "review_tasks"

EVIDENCE_REGISTER_PATH = (
    STAGE1 / "evidence_register.json"
)

SECOND_REVIEW_REGISTER_PATH = (
    STAGE1 / "second_review_register.json"
)

QUEUE_PATH = (
    STAGE1 / "review_work_queue.json"
)

HASH_PATH = (
    STAGE1 / "review_task_hashes.json"
)

EXPECTED_PRIMARY_TASK_COUNT = 1
EXPECTED_SECOND_REVIEW_TASK_COUNT = 5
EXPECTED_TOTAL_TASK_COUNT = 6


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


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def git_value(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return ""

    return result.stdout.strip()


def resolve_optional_path(
    relative_path: str | None,
) -> dict[str, Any] | None:
    if not relative_path:
        return None

    path = ROOT / relative_path

    if not path.is_file():
        return {
            "path": relative_path,
            "exists": False,
            "sha256": None,
        }

    return {
        "path": relative_path,
        "exists": True,
        "sha256": sha256_file(path),
    }


def paper_record(
    evidence_path: str,
) -> dict[str, Any]:
    return read_json(ROOT / evidence_path)


def source_bindings(
    paper: dict[str, Any],
) -> dict[str, Any]:
    source = paper.get("source", {})

    bindings: dict[str, Any] = {
        "scientific_evidence_record": {
            "path": (
                "analysis/prior_art/"
                "scientific_extraction/p1/"
                f"paper-{int(paper['acquisition_order']):02d}"
                "-scientific-evidence.json"
            )
        }
    }

    evidence_path = ROOT / bindings[
        "scientific_evidence_record"
    ]["path"]

    bindings[
        "scientific_evidence_record"
    ]["exists"] = evidence_path.is_file()

    bindings[
        "scientific_evidence_record"
    ]["sha256"] = (
        sha256_file(evidence_path)
        if evidence_path.is_file()
        else None
    )

    bindings["source"] = resolve_optional_path(
        source.get("local_source_path")
    )

    bindings["normalized_text"] = (
        resolve_optional_path(
            source.get("local_text_path")
        )
    )

    bindings["review_packet"] = (
        resolve_optional_path(
            source.get("review_packet_path")
        )
    )

    bindings[
        "primary_evidence_selection"
    ] = resolve_optional_path(
        paper.get(
            "primary_extraction_evidence_selection"
        )
    )

    return bindings


def pending_field_names(
    paper: dict[str, Any],
) -> list[str]:
    fields = paper.get("fields", {})

    return sorted(
        field_name
        for field_name, field in fields.items()
        if isinstance(field, dict)
        and field.get("state")
        == "PENDING_SOURCE_REVIEW"
    )


def task_template(
    *,
    task_id: str,
    task_type: str,
    review_order: int,
    paper: dict[str, Any],
    evidence_record_path: str,
    required_independence: bool,
) -> dict[str, Any]:
    quality_control = paper.get(
        "quality_control",
        {},
    )

    return {
        "task_schema":
            "qudipi.stage1.scientific-review-task",
        "task_version": 1,
        "task_id": task_id,
        "task_type": task_type,
        "task_state": "PENDING_REVIEW",
        "review_order": review_order,
        "source_id": (
            f"PA-{int(paper['acquisition_order']):04d}"
        ),
        "evidence_id": (
            f"PA-EVID-"
            f"{int(paper['acquisition_order']):04d}"
        ),
        "canonical_key":
            paper["canonical_key"],
        "doi": paper.get("doi"),
        "title": paper["title"],
        "claim_ids": paper.get(
            "claim_ids",
            [],
        ),
        "review_eligibility":
            paper.get(
                "review_eligibility"
            ),
        "scientific_content_state":
            paper.get(
                "scientific_content_state"
            ),
        "extraction_scope":
            paper.get(
                "extraction_scope"
            ),
        "terminal_source_state":
            paper.get(
                "terminal_source_state"
            ),
        "required_independence":
            required_independence,
        "prior_primary_reviewer":
            quality_control.get(
                "primary_reviewer"
            ),
        "prior_second_reviewer":
            quality_control.get(
                "second_reviewer"
            ),
        "pending_field_names":
            pending_field_names(paper),
        "source_bindings":
            source_bindings(paper),
        "review_contract": {
            "title_or_metadata_inference_prohibited":
                True,
            "unsupported_fields_remain_explicit":
                True,
            "source_scope_must_not_be_exceeded":
                True,
            "evidence_line_ranges_required_for_supported_fields":
                True,
            "claim_overlap_requires_separate_adjudication":
                True,
            "novelty_decision_prohibited_in_review_task":
                True,
        },
        "review_output": {
            "reviewer": None,
            "review_method": None,
            "review_started_at": None,
            "review_completed_at": None,
            "field_dispositions": [],
            "claim_relevance_observations": [],
            "discrepancies": [],
            "final_review_state": None,
            "reviewer_attestation": None,
        },
        "evidence_record_path":
            evidence_record_path,
        "evidence_record_sha256":
            sha256_file(
                ROOT / evidence_record_path
            ),
    }


def main() -> int:
    errors: list[str] = []

    TASK_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    evidence_register = read_json(
        EVIDENCE_REGISTER_PATH
    )

    second_review_register = read_json(
        SECOND_REVIEW_REGISTER_PATH
    )

    evidence_records = (
        evidence_register.get(
            "records",
            [],
        )
    )

    pending_primary_records = [
        record
        for record in evidence_records
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

    if (
        len(pending_primary_records)
        != EXPECTED_PRIMARY_TASK_COUNT
    ):
        errors.append(
            "expected exactly one pending "
            "reviewable primary record"
        )

    review_records = (
        second_review_register.get(
            "records",
            [],
        )
    )

    if (
        len(review_records)
        != EXPECTED_SECOND_REVIEW_TASK_COUNT
    ):
        errors.append(
            "expected exactly five second-review "
            "cohort records"
        )

    tasks: list[dict[str, Any]] = []

    for index, record in enumerate(
        pending_primary_records,
        start=1,
    ):
        evidence_path = record[
            "evidence_record_path"
        ]

        paper = paper_record(
            evidence_path
        )

        task = task_template(
            task_id=(
                f"PA-TASK-PRIMARY-{index:02d}"
            ),
            task_type=(
                "PRIMARY_SCIENTIFIC_REVIEW"
            ),
            review_order=index,
            paper=paper,
            evidence_record_path=
                evidence_path,
            required_independence=False,
        )

        task_path = (
            TASK_DIRECTORY
            / (
                task["task_id"].lower()
                .replace("-", "_")
                + ".json"
            )
        )

        write_json(task_path, task)

        tasks.append(
            {
                "task_id":
                    task["task_id"],
                "task_type":
                    task["task_type"],
                "task_state":
                    task["task_state"],
                "review_order":
                    task["review_order"],
                "source_id":
                    task["source_id"],
                "canonical_key":
                    task["canonical_key"],
                "claim_ids":
                    task["claim_ids"],
                "task_path":
                    relative(task_path),
                "task_sha256":
                    sha256_file(task_path),
            }
        )

    for record in sorted(
        review_records,
        key=lambda value: value[
            "second_review_order"
        ],
    ):
        evidence_path = record[
            "evidence_record_path"
        ]

        paper = paper_record(
            evidence_path
        )

        review_order = int(
            record[
                "second_review_order"
            ]
        )

        task = task_template(
            task_id=(
                f"PA-TASK-SECOND-{review_order:02d}"
            ),
            task_type=(
                "INDEPENDENT_SECOND_REVIEW"
            ),
            review_order=review_order,
            paper=paper,
            evidence_record_path=
                evidence_path,
            required_independence=True,
        )

        task_path = (
            TASK_DIRECTORY
            / (
                task["task_id"].lower()
                .replace("-", "_")
                + ".json"
            )
        )

        write_json(task_path, task)

        tasks.append(
            {
                "task_id":
                    task["task_id"],
                "task_type":
                    task["task_type"],
                "task_state":
                    task["task_state"],
                "review_order":
                    task["review_order"],
                "source_id":
                    task["source_id"],
                "canonical_key":
                    task["canonical_key"],
                "claim_ids":
                    task["claim_ids"],
                "task_path":
                    relative(task_path),
                "task_sha256":
                    sha256_file(task_path),
            }
        )

    task_ids = [
        task["task_id"]
        for task in tasks
    ]

    if len(task_ids) != len(set(task_ids)):
        errors.append(
            "duplicate review task IDs"
        )

    if len(tasks) != EXPECTED_TOTAL_TASK_COUNT:
        errors.append(
            "review queue must contain exactly "
            f"{EXPECTED_TOTAL_TASK_COUNT} tasks"
        )

    write_json(
        QUEUE_PATH,
        {
            "queue_schema":
                "qudipi.stage1.review-work-queue",
            "queue_version": 1,
            "repository_revision":
                git_value(
                    "rev-parse",
                    "HEAD",
                ),
            "repository_tree":
                git_value(
                    "rev-parse",
                    "HEAD^{tree}",
                ),
            "expected_primary_task_count":
                EXPECTED_PRIMARY_TASK_COUNT,
            "expected_second_review_task_count":
                EXPECTED_SECOND_REVIEW_TASK_COUNT,
            "expected_total_task_count":
                EXPECTED_TOTAL_TASK_COUNT,
            "primary_task_count":
                sum(
                    1
                    for task in tasks
                    if task["task_type"]
                    == "PRIMARY_SCIENTIFIC_REVIEW"
                ),
            "second_review_task_count":
                sum(
                    1
                    for task in tasks
                    if task["task_type"]
                    == "INDEPENDENT_SECOND_REVIEW"
                ),
            "task_count": len(tasks),
            "completed_task_count": 0,
            "queue_state": (
                "READY"
                if not errors
                else "INVALID"
            ),
            "tasks": sorted(
                tasks,
                key=lambda task: (
                    task["task_type"],
                    task["review_order"],
                ),
            ),
            "construction_errors": errors,
        },
    )

    hashes = {
        task["task_path"]:
            task["task_sha256"]
        for task in tasks
    }

    hashes[relative(QUEUE_PATH)] = (
        sha256_file(QUEUE_PATH)
    )

    write_json(HASH_PATH, hashes)

    print(
        "QUDIPI_STAGE1_REVIEW_QUEUE_BUILD="
        + (
            "PASS"
            if not errors
            else "FAIL"
        )
    )

    print(
        "primary_task_count="
        f"{sum(1 for task in tasks if task['task_type'] == 'PRIMARY_SCIENTIFIC_REVIEW')}"
    )

    print(
        "second_review_task_count="
        f"{sum(1 for task in tasks if task['task_type'] == 'INDEPENDENT_SECOND_REVIEW')}"
    )

    print(
        f"task_count={len(tasks)}"
    )

    print("completed_task_count=0")

    for error in errors:
        print(f"ERROR  {error}")

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
