from __future__ import annotations

import argparse
from pathlib import Path

from analysis.stage1.stage1_runtime_contracts import ModuleClosure, Stage1ContractError, atomic_json, hash_inputs, load_json, load_jsonl, stable_id, write_closure

MODULE_ID = "S1-M13"


class PrimaryReviewQueue:
    def run(self, m01_root: Path, m12_root: Path, output_root: Path) -> ModuleClosure:
        work_path = m01_root / "work_identity_state_registry.json"
        claim_path = m12_root / "grounded_claim_assessment_registry.jsonl"
        works = list(load_json(work_path).get("records", []))
        claims = load_jsonl(claim_path)
        if not works:
            raise Stage1ContractError("M13 requires current scientific works")
        claims_by_work: dict[str, list[str]] = {}
        for claim in claims:
            claims_by_work.setdefault(str(claim.get("file_id", "")), []).append(str(claim.get("claim_id", "")))
        tasks = []
        for work in works:
            work_id = str(work.get("work_id", ""))
            tasks.append(
                {
                    "primary_review_task_id": stable_id("PRIMARY-REVIEW", {"work": work_id}),
                    "work_id": work_id,
                    "identity_state": work.get("identity_state"),
                    "claim_ids": claims_by_work.get(work_id, []),
                    "review_requirements": ["source_integrity", "extraction_coverage", "author_model", "method_decomposition", "claim_grounding", "gap_assessment"],
                    "reviewer_plane": "HUMAN_OR_AUTHORIZED_AI",
                    "review_state": "PENDING",
                    "disposition": None,
                }
            )
        output = "primary_review_registry.json"
        atomic_json(output_root / output, {"schema_version": 1, "records": tasks})
        closure = ModuleClosure(MODULE_ID, "READY_FOR_REVIEW", "OPEN", (output,), {"works": len(works), "tasks": len(tasks), "pending": len(tasks)}, {"every_current_work_has_task": "PASS", "review_requirements_total": "PASS", "disposition_not_fabricated": "PASS"}, hash_inputs((work_path, claim_path)))
        write_closure(output_root, closure)
        return closure


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m01-root", required=True)
    parser.add_argument("--m12-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    result = PrimaryReviewQueue().run(Path(args.m01_root), Path(args.m12_root), Path(args.output_root))
    print(f"TRUECOLOR_STAGE1_{MODULE_ID}=PASS")
    print(f"module_state={result.module_state}")


if __name__ == "__main__":
    main()
