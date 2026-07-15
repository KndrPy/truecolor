from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DECISION_FIELDS = (
    "selected_terminal_role",
    "decision_reason",
    "evidence_basis",
    "reviewer",
    "reviewed_at",
    "reviewer_attestation",
)
EVIDENCE_TYPES = {
    "SOURCE_DOCUMENT",
    "NORMALIZED_TEXT",
    "REVIEW_PACKET",
    "SCIENTIFIC_EVIDENCE_RECORD",
    "ACQUISITION_RECORD",
    "ADJUDICATION_RECORD",
    "CITATION_LINEAGE_RECORD",
    "EXCLUSION_RECORD",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rebuild_hashes(output: Path) -> None:
    hash_path = output / "artifact_hashes.json"
    hashes = {}
    for path in sorted(output.rglob("*.json")):
        if path == hash_path:
            continue
        hashes[path.relative_to(ROOT).as_posix()] = sha256_file(path)
    write_json(hash_path, hashes)


def semantic_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict, tuple, set)):
        return not value
    return False


def load_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build(args: argparse.Namespace) -> None:
    queue_path = Path(args.queue).resolve()
    review_dir = Path(args.review_dir).resolve()
    review_dir.mkdir(parents=True, exist_ok=True)

    queue = read_json(queue_path)
    decision_path = review_dir / "corpus_disposition_decisions.csv"
    previous = {
        row["task_id"]: row
        for row in load_rows(decision_path)
        if row.get("task_id")
    }

    review_rows = []
    decision_rows = []
    packet_rows = []
    errors = []
    preserved = 0

    for order, task_ref in enumerate(queue["tasks"], start=1):
        task_path = ROOT / task_ref["task_path"]
        if not task_path.is_file():
            errors.append(f"missing task {task_ref['task_path']}")
            continue

        task_hash = sha256_file(task_path)
        if task_hash != task_ref["task_sha256"]:
            errors.append(f"task hash mismatch {task_ref['task_path']}")
            continue

        task = read_json(task_path)
        metadata = task.get("source_metadata", {})
        observations = task.get("existing_disposition_observations", [])

        review_rows.append(
            {
                "review_order": order,
                "task_id": task["task_id"],
                "task_sha256": task_hash,
                "canonical_identity": task["canonical_identity"],
                "corpus_member_id": task["corpus_member_id"],
                "title": metadata.get("title", ""),
                "doi": metadata.get("doi", ""),
                "pmid": metadata.get("pmid", ""),
                "year": metadata.get("year", ""),
                "allowed_terminal_roles": "|".join(
                    task["allowed_terminal_roles"]
                ),
                "source_metadata_json": json.dumps(
                    metadata, sort_keys=True, separators=(",", ":")
                ),
                "existing_observations_json": json.dumps(
                    observations, sort_keys=True, separators=(",", ":")
                ),
            }
        )

        row = {
            "review_order": str(order),
            "task_id": task["task_id"],
            "task_sha256": task_hash,
            "canonical_identity": task["canonical_identity"],
            **{field: "" for field in DECISION_FIELDS},
        }

        prior = previous.get(task["task_id"])
        if (
            prior
            and prior.get("task_sha256") == task_hash
            and prior.get("canonical_identity") == task["canonical_identity"]
        ):
            for field in DECISION_FIELDS:
                row[field] = prior.get(field, "")
            if any(not semantic_empty(row[field]) for field in DECISION_FIELDS):
                preserved += 1

        decision_rows.append(row)
        packet_rows.append(
            {
                "review_order": order,
                "task_id": task["task_id"],
                "task_path": task_ref["task_path"],
                "task_sha256": task_hash,
                "canonical_identity": task["canonical_identity"],
                "source_metadata": metadata,
                "existing_disposition_observations": observations,
                "allowed_terminal_roles": task["allowed_terminal_roles"],
                "decision_contract": task["decision_contract"],
            }
        )

    review_fields = list(review_rows[0].keys()) if review_rows else []
    with (
        review_dir / "corpus_disposition_review.csv"
    ).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=review_fields)
        writer.writeheader()
        writer.writerows(review_rows)

    decision_fields = [
        "review_order",
        "task_id",
        "task_sha256",
        "canonical_identity",
        *DECISION_FIELDS,
    ]
    with decision_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=decision_fields)
        writer.writeheader()
        writer.writerows(decision_rows)

    write_json(
        review_dir / "corpus_disposition_review_packet.json",
        {
            "packet_schema":
                "qudipi.stage1.corpus-disposition-review-packet",
            "packet_version": 1,
            "queue_path": queue_path.relative_to(ROOT).as_posix(),
            "queue_sha256": sha256_file(queue_path),
            "task_count": len(packet_rows),
            "preserved_decision_count": preserved,
            "records": packet_rows,
            "construction_errors": errors,
        },
    )

    instructions = review_dir / "corpus_disposition_review_instructions.md"
    instructions.write_text(
        "# Stage 1 Corpus Disposition Review\n\n"
        "Enter decisions in `corpus_disposition_decisions.csv`.\n\n"
        "Allowed roles: FULL_SCIENTIFIC_EXTRACTION, "
        "BOUNDED_SCIENTIFIC_REVIEW, MATERIAL_LINEAGE_REFERENCE, "
        "EXCLUDED_WITH_REASON, TERMINAL_SOURCE_UNAVAILABLE.\n\n"
        "Every completed row requires all six decision fields. "
        "`evidence_basis` must be a JSON array of objects with "
        "`source`, `basis`, and `evidence_type`.\n",
        encoding="utf-8",
    )

    review_hashes = {}
    for path in (
        review_dir / "corpus_disposition_review.csv",
        decision_path,
        review_dir / "corpus_disposition_review_packet.json",
        instructions,
    ):
        review_hashes[path.relative_to(ROOT).as_posix()] = sha256_file(path)
    write_json(
        review_dir / "corpus_disposition_review_hashes.json",
        review_hashes,
    )

    print("QUDIPI_STAGE1_DISPOSITION_REVIEW_BUILD=PASS")
    print(f"review_row_count={len(review_rows)}")
    print(f"decision_row_count={len(decision_rows)}")
    print(f"preserved_decision_count={preserved}")

    if errors:
        for error in errors:
            print(f"ERROR  {error}")
        raise RuntimeError("review surface build failed")


def parse_basis(raw: str) -> list[dict[str, Any]]:
    value = json.loads(raw)
    if not isinstance(value, list) or not value:
        raise ValueError("evidence_basis must be a nonempty JSON array")

    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each evidence_basis entry must be an object")
        if not str(item.get("source", "")).strip():
            raise ValueError("evidence source missing")
        if not str(item.get("basis", "")).strip():
            raise ValueError("evidence basis missing")
        if str(item.get("evidence_type", "")).strip() not in EVIDENCE_TYPES:
            raise ValueError("invalid evidence_type")
    return value


def validate_or_apply(args: argparse.Namespace) -> None:
    queue_path = Path(args.queue).resolve()
    coverage_path = Path(args.coverage).resolve()
    coverage_gap_path = Path(args.coverage_gap).resolve()
    stage_gap_path = Path(args.stage_gap).resolve()
    decisions_path = Path(args.decisions).resolve()
    policy_path = Path(args.policy).resolve()
    output = Path(args.output).resolve()

    queue = read_json(queue_path)
    coverage = read_json(coverage_path)
    coverage_gap = read_json(coverage_gap_path)
    stage_gap = read_json(stage_gap_path)
    policy = read_json(policy_path)

    allowed_roles = set(policy["terminal_roles"])
    task_refs = {item["task_id"]: item for item in queue["tasks"]}
    coverage_by_identity = {
        item["canonical_identity"]: item
        for item in coverage["records"]
    }

    rows = load_rows(decisions_path)
    errors = []
    decisions = []
    blanks = 0
    seen = set()

    for row_number, row in enumerate(rows, start=2):
        values = [str(row.get(field, "")).strip() for field in DECISION_FIELDS]
        if all(not value for value in values):
            blanks += 1
            continue

        task_id = str(row.get("task_id", "")).strip()
        if task_id in seen:
            errors.append(f"row {row_number}: duplicate task_id")
            continue
        seen.add(task_id)

        task_ref = task_refs.get(task_id)
        if task_ref is None:
            errors.append(f"row {row_number}: unknown task_id")
            continue

        task_path = ROOT / task_ref["task_path"]
        identity = str(row.get("canonical_identity", "")).strip()
        role = str(row.get("selected_terminal_role", "")).strip()
        reason = str(row.get("decision_reason", "")).strip()
        reviewer = str(row.get("reviewer", "")).strip()
        reviewed_at = str(row.get("reviewed_at", "")).strip()
        attestation = str(row.get("reviewer_attestation", "")).strip()

        if str(row.get("task_sha256", "")).strip() != sha256_file(task_path):
            errors.append(f"row {row_number}: task hash mismatch")
        if identity != task_ref["canonical_identity"]:
            errors.append(f"row {row_number}: identity mismatch")
        if role not in allowed_roles:
            errors.append(f"row {row_number}: invalid role")
        if not reason:
            errors.append(f"row {row_number}: decision reason missing")
        if not reviewer:
            errors.append(f"row {row_number}: reviewer missing")
        if not attestation:
            errors.append(f"row {row_number}: attestation missing")

        try:
            datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"row {row_number}: invalid reviewed_at")

        try:
            basis = parse_basis(str(row.get("evidence_basis", "")))
        except (json.JSONDecodeError, ValueError) as error:
            errors.append(f"row {row_number}: {error}")
            basis = []

        if identity not in coverage_by_identity:
            errors.append(f"row {row_number}: coverage identity missing")
        elif coverage_by_identity[identity]["coverage_state"] != "PENDING":
            errors.append(f"row {row_number}: coverage is not pending")

        decisions.append(
            {
                "task_id": task_id,
                "task_path": task_ref["task_path"],
                "canonical_identity": identity,
                "selected_terminal_role": role,
                "decision_reason": reason,
                "evidence_basis": basis,
                "reviewer": reviewer,
                "reviewed_at": reviewed_at,
                "reviewer_attestation": attestation,
            }
        )

    applied = []

    if args.apply and not errors:
        for decision in decisions:
            task_path = ROOT / decision["task_path"]
            task = read_json(task_path)
            task["task_state"] = "COMPLETED"
            task["decision"] = {
                key: decision[key]
                for key in DECISION_FIELDS
            }
            write_json(task_path, task)

            record = coverage_by_identity[decision["canonical_identity"]]
            record["coverage_state"] = "TERMINAL"
            record["coverage_role"] = decision["selected_terminal_role"]
            record["coverage_reason"] = decision["decision_reason"]
            record["derivation"] = {
                "method": "explicit_human_disposition_decision",
                "task_id": decision["task_id"],
                "reviewer": decision["reviewer"],
                "reviewed_at": decision["reviewed_at"],
                "evidence_basis": decision["evidence_basis"],
            }
            applied.append(decision["task_id"])

        completed = 0
        for task_ref in queue["tasks"]:
            task_path = ROOT / task_ref["task_path"]
            task_ref["task_sha256"] = sha256_file(task_path)
            task_ref["task_state"] = read_json(task_path)["task_state"]
            if task_ref["task_state"] == "COMPLETED":
                completed += 1

        queue["completed_task_count"] = completed
        queue["queue_state"] = (
            "COMPLETE" if completed == queue["task_count"] else "IN_PROGRESS"
        )

        terminal = sum(
            1 for item in coverage["records"]
            if item["coverage_state"] == "TERMINAL"
        )
        pending = sum(
            1 for item in coverage["records"]
            if item["coverage_state"] == "PENDING"
        )

        coverage["terminal_coverage_count"] = terminal
        coverage["pending_disposition_count"] = pending

        coverage_gap["terminal_coverage_count"] = terminal
        coverage_gap["pending_disposition_count"] = pending
        coverage_gap["stage_state"] = "COMPLETE" if pending == 0 else "OPEN"
        coverage_gap["pending_corpus_members"] = [
            {
                "coverage_record_id": item["coverage_record_id"],
                "corpus_member_id": item["corpus_member_id"],
                "canonical_identity": item["canonical_identity"],
                "coverage_role": item["coverage_role"],
            }
            for item in coverage["records"]
            if item["coverage_state"] == "PENDING"
        ]

        blockers = [
            item for item in stage_gap["remaining_blockers"]
            if item != "governed_corpus_terminal_disposition"
        ]
        if pending:
            blockers.append("governed_corpus_terminal_disposition")

        stage_gap["remaining_blockers"] = list(dict.fromkeys(blockers))
        stage_gap["terminal_coverage_count"] = terminal
        stage_gap["pending_corpus_disposition_count"] = pending
        stage_gap["pending_corpus_disposition_task_count"] = (
            queue["task_count"] - completed
        )

        write_json(queue_path, queue)
        write_json(coverage_path, coverage)
        write_json(coverage_gap_path, coverage_gap)
        write_json(stage_gap_path, stage_gap)

    report = {
        "report_schema":
            "qudipi.stage1.corpus-disposition-decision-import",
        "report_version": 1,
        "mode": "APPLY" if args.apply else "VALIDATE_ONLY",
        "input_row_count": len(rows),
        "blank_row_count": blanks,
        "valid_decision_count": len(decisions),
        "error_count": len(errors),
        "errors": errors,
        "applied_task_ids": applied,
    }
    write_json(
        output / "corpus_disposition_decision_import_report.json",
        report,
    )
    rebuild_hashes(output)

    print(
        "QUDIPI_STAGE1_DISPOSITION_DECISION_IMPORT="
        + ("PASS" if not errors else "FAIL")
    )
    print(f"input_row_count={len(rows)}")
    print(f"blank_row_count={blanks}")
    print(f"valid_decision_count={len(decisions)}")
    print(f"applied_decision_count={len(applied)}")
    print(f"error_count={len(errors)}")

    if errors:
        for error in errors:
            print(f"ERROR  {error}")
        raise RuntimeError("decision validation failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--queue", required=True)
    build_parser.add_argument("--review-dir", required=True)

    for command in ("validate", "apply"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--queue", required=True)
        command_parser.add_argument("--coverage", required=True)
        command_parser.add_argument("--coverage-gap", required=True)
        command_parser.add_argument("--stage-gap", required=True)
        command_parser.add_argument("--decisions", required=True)
        command_parser.add_argument("--policy", required=True)
        command_parser.add_argument("--output", required=True)
        command_parser.set_defaults(apply=(command == "apply"))

    args = parser.parse_args()

    if args.command == "build":
        build(args)
    else:
        validate_or_apply(args)


if __name__ == "__main__":
    main()
