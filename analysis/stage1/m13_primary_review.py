from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from analysis.stage1.stage1_runtime_contracts import (
    ModuleClosure,
    Stage1ContractError,
    atomic_json,
    hash_inputs,
    load_json,
    load_jsonl,
    stable_id,
    write_closure,
)

MODULE_ID = "S1-M13"
IDENTITY_FIELDS = {
    "work_id",
    "file_id",
    "file_ids",
    "source_file_id",
    "source_file_ids",
    "physical_file_id",
    "physical_file_ids",
    "canonical_file_id",
    "canonical_file_ids",
    "document_id",
    "document_ids",
    "version_id",
    "version_ids",
    "content_sha256",
    "source_sha256",
    "file_sha256",
    "source_path",
    "source_paths",
    "file_path",
    "file_paths",
    "canonical_path",
    "canonical_paths",
    "relative_path",
    "relative_paths",
    "path",
    "paths",
    "filename",
    "filenames",
    "file_name",
    "file_names",
    "source_name",
    "source_names",
}
PATH_FIELDS = {
    "source_path",
    "source_paths",
    "file_path",
    "file_paths",
    "canonical_path",
    "canonical_paths",
    "relative_path",
    "relative_paths",
    "path",
    "paths",
    "filename",
    "filenames",
    "file_name",
    "file_names",
    "source_name",
    "source_names",
}


def _normalized_identity_values(key: str, value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, Mapping):
        values: set[str] = set()
        for child_key, child in value.items():
            values.update(_normalized_identity_values(str(child_key).strip().lower(), child))
        return values
    if isinstance(value, (list, tuple, set)):
        values: set[str] = set()
        for child in value:
            values.update(_normalized_identity_values(key, child))
        return values
    text = str(value).strip()
    if not text:
        return set()
    values = {text}
    if key in PATH_FIELDS:
        normalized = text.replace("\\", "/")
        path = PurePosixPath(normalized)
        values.add(normalized)
        values.add(path.name)
        if path.suffix:
            values.add(path.stem)
    return {item for item in values if item}


def _identity_values(record: Mapping[str, Any]) -> set[str]:
    """Collect canonical identity aliases from top-level or nested provenance objects.

    Stage artifacts do not use one uniform provenance shape. M01 commonly stores source
    aliases in plural arrays such as ``file_ids`` and ``version_ids`` while downstream
    claim artifacts usually carry a scalar ``file_id``. Every explicitly identity-bearing
    key is normalized recursively; claim and element identifiers remain excluded.
    """
    values: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for raw_key, child in value.items():
                key = str(raw_key).strip().lower()
                if key in IDENTITY_FIELDS:
                    values.update(_normalized_identity_values(key, child))
                if isinstance(child, (Mapping, list, tuple, set)):
                    visit(child)
        elif isinstance(value, (list, tuple, set)):
            for child in value:
                if isinstance(child, (Mapping, list, tuple, set)):
                    visit(child)

    visit(record)
    return values


def _claims_by_work(
    works: list[Mapping[str, Any]], claims: list[Mapping[str, Any]]
) -> dict[str, list[str]]:
    identifier_to_work: dict[str, str] = {}
    result: dict[str, list[str]] = {}
    for work in works:
        work_id = str(work.get("work_id", "")).strip()
        if not work_id:
            raise Stage1ContractError("M13 work record missing work_id")
        result[work_id] = []
        identities = _identity_values(work)
        if not identities:
            raise Stage1ContractError(f"M13 work has no resolvable identity aliases: {work_id}")
        for identifier in identities:
            previous = identifier_to_work.get(identifier)
            if previous and previous != work_id:
                raise Stage1ContractError(
                    f"M13 ambiguous work identity {identifier}: {previous}, {work_id}"
                )
            identifier_to_work[identifier] = work_id

    unmatched: list[str] = []
    ambiguous: list[str] = []
    for claim in claims:
        claim_id = str(claim.get("claim_id", "")).strip()
        if not claim_id:
            raise Stage1ContractError("M13 grounded claim missing claim_id")
        candidates = {
            identifier_to_work[value]
            for value in _identity_values(claim)
            if value in identifier_to_work
        }
        if len(candidates) == 0:
            unmatched.append(claim_id)
            continue
        if len(candidates) > 1:
            ambiguous.append(claim_id)
            continue
        result[next(iter(candidates))].append(claim_id)

    if unmatched or ambiguous:
        unmatched_preview = ", ".join(unmatched[:10])
        ambiguous_preview = ", ".join(ambiguous[:10])
        raise Stage1ContractError(
            "M13 could not resolve grounded claims to exactly one work: "
            f"unmatched={len(unmatched)} [{unmatched_preview}], "
            f"ambiguous={len(ambiguous)} [{ambiguous_preview}]"
        )
    return result


class PrimaryReviewQueue:
    def run(self, m01_root: Path, m12_root: Path, output_root: Path) -> ModuleClosure:
        work_path = m01_root / "work_identity_state_registry.json"
        claim_path = m12_root / "grounded_claim_assessment_registry.jsonl"
        works = list(load_json(work_path).get("records", []))
        claims = load_jsonl(claim_path)
        if not works:
            raise Stage1ContractError("M13 requires current scientific works")
        claims_by_work = _claims_by_work(works, claims)
        tasks = []
        for work in works:
            work_id = str(work.get("work_id", ""))
            tasks.append(
                {
                    "primary_review_task_id": stable_id("PRIMARY-REVIEW", {"work": work_id}),
                    "work_id": work_id,
                    "identity_state": work.get("identity_state"),
                    "claim_ids": claims_by_work[work_id],
                    "review_requirements": [
                        "source_integrity",
                        "extraction_coverage",
                        "author_model",
                        "method_decomposition",
                        "claim_grounding",
                        "gap_assessment",
                    ],
                    "reviewer_plane": "HUMAN_OR_AUTHORIZED_AI",
                    "review_state": "PENDING",
                    "disposition": None,
                }
            )
        output = "primary_review_registry.json"
        atomic_json(output_root / output, {"schema_version": 4, "records": tasks})
        closure = ModuleClosure(
            MODULE_ID,
            "READY_FOR_REVIEW",
            "OPEN",
            (output,),
            {
                "works": len(works),
                "tasks": len(tasks),
                "pending": len(tasks),
                "claims": len(claims),
                "claims_linked": sum(len(value) for value in claims_by_work.values()),
            },
            {
                "every_current_work_has_task": "PASS",
                "review_requirements_total": "PASS",
                "disposition_not_fabricated": "PASS",
                "every_grounded_claim_resolves_to_one_work": "PASS",
            },
            hash_inputs((work_path, claim_path)),
        )
        write_closure(output_root, closure)
        return closure


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m01-root", required=True)
    parser.add_argument("--m12-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    result = PrimaryReviewQueue().run(
        Path(args.m01_root), Path(args.m12_root), Path(args.output_root)
    )
    print(f"TRUECOLOR_STAGE1_{MODULE_ID}=PASS")
    print(f"module_state={result.module_state}")


if __name__ == "__main__":
    main()
