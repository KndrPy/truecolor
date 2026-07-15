from __future__ import annotations

import argparse
from pathlib import Path

from analysis.stage1.stage1_runtime_contracts import ModuleClosure, Stage1ContractError, atomic_json, hash_inputs, load_json, stable_id, write_closure

MODULE_ID = "S1-M14"


class IndependentReviewQueue:
    def run(self, m13_root: Path, output_root: Path) -> ModuleClosure:
        primary_path = m13_root / "primary_review_registry.json"
        primary = list(load_json(primary_path).get("records", []))
        if not primary:
            raise Stage1ContractError("M14 requires primary-review tasks")
        tasks = [
            {
                "independent_review_task_id": stable_id("SECOND-REVIEW", {"primary": item["primary_review_task_id"]}),
                "primary_review_task_id": item["primary_review_task_id"],
                "work_id": item["work_id"],
                "independence_constraints": ["different_reviewer_identity", "no_visibility_of_primary_disposition_before_submission", "same_source_snapshot"],
                "review_state": "PENDING",
                "disposition": None,
            }
            for item in primary
        ]
        output = "independent_review_registry.json"
        atomic_json(output_root / output, {"schema_version": 1, "records": tasks})
        closure = ModuleClosure(MODULE_ID, "READY_FOR_REVIEW", "OPEN", (output,), {"tasks": len(tasks), "pending": len(tasks)}, {"every_primary_task_has_second_review": "PASS", "independence_constraints_explicit": "PASS", "disposition_not_fabricated": "PASS"}, hash_inputs((primary_path,)))
        write_closure(output_root, closure)
        return closure


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m13-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    result = IndependentReviewQueue().run(Path(args.m13_root), Path(args.output_root))
    print(f"TRUECOLOR_STAGE1_{MODULE_ID}=PASS")
    print(f"module_state={result.module_state}")


if __name__ == "__main__":
    main()
