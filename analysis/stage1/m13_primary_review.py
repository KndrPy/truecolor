from __future__ import annotations

import argparse
from pathlib import Path
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
IDENTITY_FIELDS = (
    "work_id",
    "file_id",
    "source_file_id",
    "physical_file_id",
    "canonical_file_id",
    "document_id",
    "content_sha256",
)


def _identity_values(record: Mapping[str, Any]) -> set[str]:
    return {
        str(record.get(field)).strip()
        for field in IDENTITY_FIELDS
        if record.get(field) is not None and str(record.get(field)).strip()
    }


def _claims_by_work(works: list[Mapping[str, Any]], claims: list[Mapping[str, Any]]) -> dict[str, list[str]]:
    identifier_to_work: dict[str, str] = {}
    result: dict[str, list[str]] = {}
    for work in works:
        work_id = str(work.get("work_id", "")).strip()
        if not work_id:
            raise Stage1ContractError("M13 work record missing work_id")
        result[work_id] = []
        for identifier in _identity_values(work):
            previous = identifier_to_work.get(identifier)
            if previous and previous != work_id:
                raise Stage1ContractError(
                    f"M13 ambiguous work identity {identifier}: {previous}, {work_id}"
                )
            identifier_to_work[identifier] = work_id

    unmatched: list[str] = []
    for claim in claims:
        claim_id = str(claim.get("claim_id", "")).strip()
        if not claim_id:
            raise Stage1ContractError("M13 grounded claim missing claim_id")
        candidates = {
            identifier_to_work[value]
            for value in _identity_values(claim)
            if value in identifier_to_work
        }
        if len(candidates) != 1:
            unmatched.append(claim_id)
            continue
        result[next(iter(candidates))].append(claim_id)

    if unmatched:
        preview = ", ".join(unmatched[:10])
        raise Stage1ContractError(
            f"M13 could not resolve {len(unmatched)} grounded claims to exactly one work: {preview}"
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
        atomic_json(output_root / output, {"schema_version": 2, "records": tasks})
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
