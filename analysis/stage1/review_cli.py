from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from analysis.stage1.m15_review_conflict_resolution import ReviewConflictResolution
from analysis.stage1.m17_stage1_closure import Stage1ClosureAuthority
from analysis.stage1.review_execution import (
    REVIEW_DISPOSITIONS,
    NOVELTY_DECISIONS,
    adjudicate_claim,
    assign_review,
    progress,
    resolve_conflict,
    submit_review,
    validate_independence,
)
from analysis.stage1.stage1_runtime_contracts import (
    Stage1ContractError,
    atomic_json,
    load_json,
    sha256_file,
)

PRIMARY_FIELD = "primary_review_task_id"
INDEPENDENT_FIELD = "independent_review_task_id"


def _stage(args: argparse.Namespace) -> Path:
    root = Path(args.stage_root)
    if not root.is_dir():
        raise Stage1ContractError(f"stage root does not exist: {root}")
    return root


def _reject_placeholder(value: str, field: str) -> str:
    text = str(value).strip()
    lowered = text.lower()
    if not text:
        raise Stage1ContractError(f"{field} must not be empty")
    if (text.startswith("<") and text.endswith(">")) or lowered in {
        "task_id",
        "reviewer_id",
        "work_id",
        "claim_id",
        "primary_task_id",
        "independent_task_id",
        "your_reviewer_id",
    }:
        raise Stage1ContractError(
            f"{field} contains a placeholder value: {text}. "
            "Use 'list-pending' to obtain real task/work/claim identifiers."
        )
    return text


def _existing_manifest(value: str) -> Path:
    path = Path(value)
    if not path.is_file():
        raise Stage1ContractError(
            f"manifest file does not exist: {path}. "
            "Use 'generate-assignment-manifest' or create the JSON file before running a batch command."
        )
    return path


def _json_list(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise Stage1ContractError(f"manifest file does not exist: {path}")
    payload = load_json(path)
    records = payload.get("records")
    if not isinstance(records, list):
        raise Stage1ContractError(f"manifest requires records list: {path}")
    return [dict(item) for item in records]


def _required_text(item: Mapping[str, Any], key: str) -> str:
    value = str(item.get(key, "")).strip()
    if not value:
        raise Stage1ContractError(f"manifest record missing {key}")
    return _reject_placeholder(value, key)


def _required_list(item: Mapping[str, Any], key: str) -> list[Any]:
    value = item.get(key)
    if not isinstance(value, list) or not value:
        raise Stage1ContractError(f"manifest record requires non-empty {key}")
    return list(value)


def _reject_duplicate_ids(records: Iterable[Mapping[str, Any]], key: str) -> None:
    seen: set[str] = set()
    for item in records:
        value = _required_text(item, key)
        if value in seen:
            raise Stage1ContractError(f"duplicate {key} in manifest: {value}")
        seen.add(value)


def _transactional_files(paths: list[Path], operation: Callable[[dict[Path, Path]], None]) -> None:
    """Execute a multi-file mutation against private copies, then publish all outputs."""
    if not paths:
        raise Stage1ContractError("transaction requires at least one file")
    parents = {path.parent.resolve() for path in paths}
    common = Path(os.path.commonpath([str(parent) for parent in parents]))
    common.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".stage1-review-txn-", dir=common) as raw:
        temp_root = Path(raw)
        mapping: dict[Path, Path] = {}
        for index, target in enumerate(paths):
            temp = temp_root / f"{index:03d}-{target.name}"
            if target.is_file():
                shutil.copy2(target, temp)
            else:
                temp.parent.mkdir(parents=True, exist_ok=True)
            mapping[target] = temp
        operation(mapping)
        journal = temp_root / "commit_journal.json"
        journal.write_text(
            json.dumps(
                {
                    "state": "PREPARED",
                    "targets": [path.as_posix() for path in paths],
                    "prepared_hashes": {
                        target.as_posix(): sha256_file(mapping[target])
                        for target in paths
                        if mapping[target].is_file()
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        for target in paths:
            source = mapping[target]
            if not source.is_file():
                raise Stage1ContractError(f"transaction did not produce {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)


def _snapshot(value: str) -> str:
    value = _reject_placeholder(value, "source_snapshot")
    candidate = Path(value)
    return sha256_file(candidate) if candidate.is_file() else value


def _registry_for_plane(root: Path, plane: str) -> tuple[Path, str]:
    if plane == "primary":
        return root / "m13" / "primary_review_registry.json", PRIMARY_FIELD
    if plane == "independent":
        return root / "m14" / "independent_review_registry.json", INDEPENDENT_FIELD
    raise Stage1ContractError(f"unsupported review plane: {plane}")


def list_pending(args: argparse.Namespace) -> None:
    root = _stage(args)
    plane = args.plane
    if plane in {"primary", "independent"}:
        registry, task_field = _registry_for_plane(root, plane)
        records = [
            {
                "task_id": item.get(task_field),
                "work_id": item.get("work_id"),
                "review_state": item.get("review_state"),
                "reviewer_id": item.get("reviewer_id"),
            }
            for item in _json_list(registry)
            if item.get("review_state") in {"PENDING", "ASSIGNED"}
        ]
    elif plane == "resolution":
        registry = root / "m15" / "review_conflict_resolution_registry.json"
        records = [
            {
                "work_id": item.get("work_id"),
                "resolution_state": item.get("resolution_state"),
                "primary_disposition": item.get("primary_disposition"),
                "independent_disposition": item.get("independent_disposition"),
            }
            for item in _json_list(registry)
            if item.get("resolution_state") not in {"AGREEMENT", "RESOLVED"}
        ]
    else:
        registry = root / "m16" / "novelty_adjudication_registry.json"
        records = [
            {
                "claim_id": item.get("claim_id"),
                "review_state": item.get("review_state"),
                "atomic_claim": item.get("atomic_claim"),
            }
            for item in _json_list(registry)
            if item.get("review_state") != "ADJUDICATED"
        ]
    limit = max(0, int(args.limit))
    print(json.dumps({"plane": plane, "total_pending": len(records), "records": records[:limit]}, indent=2))


def generate_assignment_manifest(args: argparse.Namespace) -> None:
    root = _stage(args)
    reviewer_id = _reject_placeholder(args.reviewer_id, "reviewer_id")
    role = _reject_placeholder(args.role, "role")
    output = Path(args.output)
    if output.exists() and not args.overwrite:
        raise Stage1ContractError(f"refusing to overwrite existing manifest: {output}")
    registry, task_field = _registry_for_plane(root, args.plane)
    records = []
    for item in _json_list(registry):
        if item.get("review_state") != "PENDING":
            continue
        records.append(
            {
                "task_id": item.get(task_field),
                "work_id": item.get("work_id"),
                "reviewer_id": reviewer_id,
                "role": role,
            }
        )
    if not records:
        raise Stage1ContractError(f"no pending {args.plane} review tasks found")
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(output, {"schema_version": 1, "plane": args.plane, "records": records})
    print(json.dumps({"output": output.as_posix(), "records": len(records)}, indent=2))


def assign_primary(args: argparse.Namespace) -> None:
    root = _stage(args)
    assign_review(
        root / "m13" / "primary_review_registry.json",
        PRIMARY_FIELD,
        _reject_placeholder(args.task_id, "task_id"),
        _reject_placeholder(args.reviewer_id, "reviewer_id"),
        _reject_placeholder(args.role, "role"),
    )


def assign_independent(args: argparse.Namespace) -> None:
    root = _stage(args)
    primary = root / "m13" / "primary_review_registry.json"
    independent = root / "m14" / "independent_review_registry.json"
    assign_review(
        independent,
        INDEPENDENT_FIELD,
        _reject_placeholder(args.task_id, "task_id"),
        _reject_placeholder(args.reviewer_id, "reviewer_id"),
        _reject_placeholder(args.role, "role"),
    )
    validate_independence(primary, independent)


def _submit(args: argparse.Namespace, independent: bool) -> None:
    root = _stage(args)
    module = "m14" if independent else "m13"
    name = "independent_review_registry.json" if independent else "primary_review_registry.json"
    field = INDEPENDENT_FIELD if independent else PRIMARY_FIELD
    registry = root / module / name
    ledger = root / module / "review_submission_ledger.jsonl"
    evidence = [_reject_placeholder(value, "evidence_id") for value in args.evidence_id]
    snapshot = _snapshot(args.source_snapshot)
    task_id = _reject_placeholder(args.task_id, "task_id")
    reviewer_id = _reject_placeholder(args.reviewer_id, "reviewer_id")

    def apply(mapping: dict[Path, Path]) -> None:
        submit_review(
            mapping[registry],
            field,
            task_id,
            reviewer_id,
            args.disposition,
            evidence,
            args.rationale,
            snapshot,
            mapping[ledger],
        )

    _transactional_files([registry, ledger], apply)
    if independent:
        validate_independence(root / "m13" / "primary_review_registry.json", registry)


def validate_reviews(args: argparse.Namespace) -> None:
    root = _stage(args)
    validate_independence(
        root / "m13" / "primary_review_registry.json",
        root / "m14" / "independent_review_registry.json",
    )


def resolve_review(args: argparse.Namespace) -> None:
    root = _stage(args)
    resolution = root / "m15" / "review_conflict_resolution_registry.json"
    ledger = root / "m15" / "review_resolution_ledger.jsonl"
    work_id = _reject_placeholder(args.work_id, "work_id")
    resolver_id = _reject_placeholder(args.resolver_id, "resolver_id")

    def apply(mapping: dict[Path, Path]) -> None:
        resolve_conflict(
            mapping[resolution],
            work_id,
            resolver_id,
            args.disposition,
            [_reject_placeholder(value, "evidence_id") for value in args.evidence_id],
            args.rationale,
            mapping[ledger],
        )

    _transactional_files([resolution, ledger], apply)


def adjudicate_one(args: argparse.Namespace) -> None:
    root = _stage(args)
    registry = root / "m16" / "novelty_adjudication_registry.json"
    ledger = root / "m16" / "novelty_adjudication_ledger.jsonl"
    overlap_path = _existing_manifest(args.overlap_matrix)
    overlap = json.loads(overlap_path.read_text(encoding="utf-8"))
    if not isinstance(overlap, list):
        raise Stage1ContractError("overlap matrix file must contain a JSON list")

    def apply(mapping: dict[Path, Path]) -> None:
        adjudicate_claim(
            mapping[registry],
            _reject_placeholder(args.claim_id, "claim_id"),
            _reject_placeholder(args.adjudicator_id, "adjudicator_id"),
            args.decision,
            [_reject_placeholder(value, "relevant_source_id") for value in args.relevant_source_id],
            overlap,
            args.single_source_anticipation,
            args.multi_source_combination,
            args.temporal_priority,
            args.rationale,
            mapping[ledger],
        )

    _transactional_files([registry, ledger], apply)


def batch_adjudicate(args: argparse.Namespace) -> None:
    root = _stage(args)
    records = _json_list(_existing_manifest(args.manifest))
    _reject_duplicate_ids(records, "claim_id")
    registry = root / "m16" / "novelty_adjudication_registry.json"
    ledger = root / "m16" / "novelty_adjudication_ledger.jsonl"

    for item in records:
        decision = _required_text(item, "decision")
        if decision not in NOVELTY_DECISIONS:
            raise Stage1ContractError(f"invalid novelty decision: {decision}")
        _required_list(item, "relevant_source_ids")
        _required_list(item, "overlap_matrix")
        for key in (
            "claim_id",
            "adjudicator_id",
            "single_source_anticipation",
            "multi_source_combination",
            "temporal_priority",
            "rationale",
        ):
            _required_text(item, key)

    def apply(mapping: dict[Path, Path]) -> None:
        for item in records:
            adjudicate_claim(
                mapping[registry],
                _required_text(item, "claim_id"),
                _required_text(item, "adjudicator_id"),
                _required_text(item, "decision"),
                [str(value) for value in _required_list(item, "relevant_source_ids")],
                [dict(value) for value in _required_list(item, "overlap_matrix")],
                _required_text(item, "single_source_anticipation"),
                _required_text(item, "multi_source_combination"),
                _required_text(item, "temporal_priority"),
                _required_text(item, "rationale"),
                mapping[ledger],
            )

    _transactional_files([registry, ledger], apply)


def batch_assign(args: argparse.Namespace) -> None:
    root = _stage(args)
    records = _json_list(_existing_manifest(args.manifest))
    _reject_duplicate_ids(records, "task_id")
    independent = args.plane == "independent"
    registry, field = _registry_for_plane(root, args.plane)

    def apply(mapping: dict[Path, Path]) -> None:
        for item in records:
            assign_review(
                mapping[registry],
                field,
                _required_text(item, "task_id"),
                _required_text(item, "reviewer_id"),
                _required_text(item, "role"),
            )

    _transactional_files([registry], apply)
    if independent:
        validate_reviews(args)


def batch_submit(args: argparse.Namespace) -> None:
    root = _stage(args)
    records = _json_list(_existing_manifest(args.manifest))
    _reject_duplicate_ids(records, "task_id")
    independent = args.plane == "independent"
    module = "m14" if independent else "m13"
    name = "independent_review_registry.json" if independent else "primary_review_registry.json"
    field = INDEPENDENT_FIELD if independent else PRIMARY_FIELD
    registry = root / module / name
    ledger = root / module / "review_submission_ledger.jsonl"
    for item in records:
        disposition = _required_text(item, "disposition")
        if disposition not in REVIEW_DISPOSITIONS:
            raise Stage1ContractError(f"invalid review disposition: {disposition}")
        _required_list(item, "evidence_ids")
        for key in ("task_id", "reviewer_id", "rationale", "source_snapshot"):
            _required_text(item, key)

    def apply(mapping: dict[Path, Path]) -> None:
        for item in records:
            submit_review(
                mapping[registry],
                field,
                _required_text(item, "task_id"),
                _required_text(item, "reviewer_id"),
                _required_text(item, "disposition"),
                [str(value) for value in _required_list(item, "evidence_ids")],
                _required_text(item, "rationale"),
                _snapshot(_required_text(item, "source_snapshot")),
                mapping[ledger],
            )

    _transactional_files([registry, ledger], apply)
    if independent:
        validate_reviews(args)


def recompute_m15(args: argparse.Namespace) -> None:
    root = _stage(args)
    existing_path = root / "m15" / "review_conflict_resolution_registry.json"
    existing = (
        {str(item.get("work_id")): dict(item) for item in _json_list(existing_path)}
        if existing_path.is_file()
        else {}
    )
    ReviewConflictResolution().run(root / "m13", root / "m14", root / "m15")
    payload = load_json(existing_path)
    fresh = [dict(item) for item in payload.get("records", [])]
    for item in fresh:
        old = existing.get(str(item.get("work_id")))
        if old and old.get("resolution_state") == "RESOLVED":
            item.update(
                {
                    key: value
                    for key, value in old.items()
                    if key.startswith("resolution_")
                    or key in {"resolution_state", "resolved_disposition", "resolver_id"}
                }
            )
    atomic_json(existing_path, {**dict(payload), "records": fresh})


def recompute_m17(args: argparse.Namespace) -> None:
    root = _stage(args)
    Stage1ClosureAuthority().run(
        root,
        root / "m17",
        {"m01": Path(args.m01_root), "m02": Path(args.m02_root)},
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Complete durable Stage 1 review execution CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status")
    status.add_argument("--stage-root", required=True)
    status.set_defaults(handler=lambda args: print(json.dumps(progress(_stage(args)), indent=2)))

    pending = sub.add_parser("list-pending")
    pending.add_argument("--stage-root", required=True)
    pending.add_argument("--plane", choices=("primary", "independent", "resolution", "adjudication"), required=True)
    pending.add_argument("--limit", type=int, default=20)
    pending.set_defaults(handler=list_pending)

    generate = sub.add_parser("generate-assignment-manifest")
    generate.add_argument("--stage-root", required=True)
    generate.add_argument("--plane", choices=("primary", "independent"), required=True)
    generate.add_argument("--reviewer-id", required=True)
    generate.add_argument("--role", required=True)
    generate.add_argument("--output", required=True)
    generate.add_argument("--overwrite", action="store_true")
    generate.set_defaults(handler=generate_assignment_manifest)

    for name, handler in (("assign-primary", assign_primary), ("assign-independent", assign_independent)):
        cmd = sub.add_parser(name)
        cmd.add_argument("--stage-root", required=True)
        cmd.add_argument("--task-id", required=True)
        cmd.add_argument("--reviewer-id", required=True)
        cmd.add_argument("--role", required=True)
        cmd.set_defaults(handler=handler)

    for name, independent in (("submit-primary", False), ("submit-independent", True)):
        cmd = sub.add_parser(name)
        cmd.add_argument("--stage-root", required=True)
        cmd.add_argument("--task-id", required=True)
        cmd.add_argument("--reviewer-id", required=True)
        cmd.add_argument("--disposition", required=True, choices=sorted(REVIEW_DISPOSITIONS))
        cmd.add_argument("--evidence-id", action="append", required=True)
        cmd.add_argument("--rationale", required=True)
        cmd.add_argument("--source-snapshot", required=True)
        cmd.set_defaults(handler=lambda args, independent=independent: _submit(args, independent))

    validate = sub.add_parser("validate-independence")
    validate.add_argument("--stage-root", required=True)
    validate.set_defaults(handler=validate_reviews)

    resolve = sub.add_parser("resolve-review")
    resolve.add_argument("--stage-root", required=True)
    resolve.add_argument("--work-id", required=True)
    resolve.add_argument("--resolver-id", required=True)
    resolve.add_argument("--disposition", required=True, choices=sorted(REVIEW_DISPOSITIONS))
    resolve.add_argument("--evidence-id", action="append", required=True)
    resolve.add_argument("--rationale", required=True)
    resolve.set_defaults(handler=resolve_review)

    adjudicate = sub.add_parser("adjudicate-claim")
    adjudicate.add_argument("--stage-root", required=True)
    adjudicate.add_argument("--claim-id", required=True)
    adjudicate.add_argument("--adjudicator-id", required=True)
    adjudicate.add_argument("--decision", required=True, choices=sorted(NOVELTY_DECISIONS))
    adjudicate.add_argument("--relevant-source-id", action="append", required=True)
    adjudicate.add_argument("--overlap-matrix", required=True)
    adjudicate.add_argument("--single-source-anticipation", required=True)
    adjudicate.add_argument("--multi-source-combination", required=True)
    adjudicate.add_argument("--temporal-priority", required=True)
    adjudicate.add_argument("--rationale", required=True)
    adjudicate.set_defaults(handler=adjudicate_one)

    batch_adj = sub.add_parser("batch-adjudicate")
    batch_adj.add_argument("--stage-root", required=True)
    batch_adj.add_argument("--manifest", required=True)
    batch_adj.set_defaults(handler=batch_adjudicate)

    for name, handler in (("batch-assign", batch_assign), ("batch-submit", batch_submit)):
        cmd = sub.add_parser(name)
        cmd.add_argument("--stage-root", required=True)
        cmd.add_argument("--plane", choices=("primary", "independent"), required=True)
        cmd.add_argument("--manifest", required=True)
        cmd.set_defaults(handler=handler)

    m15 = sub.add_parser("recompute-m15")
    m15.add_argument("--stage-root", required=True)
    m15.set_defaults(handler=recompute_m15)

    m17 = sub.add_parser("recompute-m17")
    m17.add_argument("--stage-root", required=True)
    m17.add_argument("--m01-root", required=True)
    m17.add_argument("--m02-root", required=True)
    m17.set_defaults(handler=recompute_m17)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except (Stage1ContractError, FileNotFoundError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from None
    print(f"TRUECOLOR_STAGE1_REVIEW_CLI_{args.command.upper().replace('-', '_')}=PASS")


if __name__ == "__main__":
    main()
