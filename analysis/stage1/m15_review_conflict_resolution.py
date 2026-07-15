from __future__ import annotations

import argparse
from pathlib import Path

from analysis.stage1.stage1_runtime_contracts import ModuleClosure, Stage1ContractError, atomic_json, hash_inputs, load_json, stable_id, write_closure

MODULE_ID = "S1-M15"


class ReviewConflictResolution:
    def run(self, m13_root: Path, m14_root: Path, output_root: Path) -> ModuleClosure:
        primary_path = m13_root / "primary_review_registry.json"
        second_path = m14_root / "independent_review_registry.json"
        primary = {str(item["work_id"]): item for item in load_json(primary_path).get("records", [])}
        second = {str(item["work_id"]): item for item in load_json(second_path).get("records", [])}
        if set(primary) != set(second):
            raise Stage1ContractError("M15 primary and independent review work sets differ")
        records = []
        for work_id in sorted(primary):
            left = primary[work_id].get("disposition")
            right = second[work_id].get("disposition")
            if left is None or right is None:
                state = "AWAITING_REVIEWS"
            elif left == right:
                state = "AGREEMENT"
            else:
                state = "CONFLICT_REQUIRES_RESOLUTION"
            records.append(
                {
                    "review_resolution_id": stable_id("REVIEW-RESOLUTION", {"work": work_id}),
                    "work_id": work_id,
                    "primary_disposition": left,
                    "independent_disposition": right,
                    "resolution_state": state,
                    "resolved_disposition": left if state == "AGREEMENT" else None,
                    "resolution_evidence": [],
                }
            )
        output = "review_conflict_resolution_registry.json"
        atomic_json(output_root / output, {"schema_version": 1, "records": records})
        unresolved = sum(1 for item in records if item["resolution_state"] != "AGREEMENT")
        closure = ModuleClosure(MODULE_ID, "READY_FOR_RESOLUTION", "OPEN", (output,), {"works": len(records), "unresolved": unresolved}, {"review_sets_total": "PASS", "conflicts_explicit": "PASS", "resolution_not_fabricated": "PASS"}, hash_inputs((primary_path, second_path)))
        write_closure(output_root, closure)
        return closure


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m13-root", required=True)
    parser.add_argument("--m14-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    result = ReviewConflictResolution().run(Path(args.m13_root), Path(args.m14_root), Path(args.output_root))
    print(f"TRUECOLOR_STAGE1_{MODULE_ID}=PASS")
    print(f"module_state={result.module_state}")


if __name__ == "__main__":
    main()
