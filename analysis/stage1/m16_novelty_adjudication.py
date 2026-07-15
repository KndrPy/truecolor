from __future__ import annotations

import argparse
from pathlib import Path

from analysis.stage1.stage1_runtime_contracts import ModuleClosure, Stage1ContractError, atomic_json, hash_inputs, load_jsonl, stable_id, write_closure

MODULE_ID = "S1-M16"
ALLOWED = {"KILLED", "SURVIVES", "NARROWED", "INDETERMINATE"}


class NoveltyAdjudicationQueue:
    def run(self, m08_root: Path, m10_root: Path, m12_root: Path, output_root: Path) -> ModuleClosure:
        claim_path = m08_root / "claim_registry.jsonl"
        grounding_path = m12_root / "grounded_claim_assessment_registry.jsonl"
        claims = load_jsonl(claim_path)
        grounds = {str(item["claim_id"]): item for item in load_jsonl(grounding_path)}
        if not claims:
            raise Stage1ContractError("M16 requires atomic claims")
        records = []
        for claim in claims:
            claim_id = str(claim.get("claim_id", ""))
            if claim_id not in grounds:
                raise Stage1ContractError(f"claim lacks M12 grounding: {claim_id}")
            records.append(
                {
                    "novelty_adjudication_id": stable_id("NOVELTY", {"claim": claim_id}),
                    "claim_id": claim_id,
                    "atomic_claim": claim.get("statement") or claim.get("claim_text") or "",
                    "relevant_source_ids": [],
                    "overlap_matrix": [],
                    "single_source_anticipation": "PENDING_REVIEW",
                    "multi_source_combination": "PENDING_REVIEW",
                    "temporal_priority": "PENDING_REVIEW",
                    "novelty_decision": "INDETERMINATE",
                    "decision_authority": "DEFAULT_PENDING_EVIDENCE_NOT_FINAL",
                    "review_state": "PENDING_NOVELTY_REVIEW",
                }
            )
        output = "novelty_adjudication_registry.json"
        atomic_json(output_root / output, {"schema_version": 1, "allowed_decisions": sorted(ALLOWED), "records": records})
        closure = ModuleClosure(MODULE_ID, "READY_FOR_ADJUDICATION", "OPEN", (output,), {"claims": len(records), "pending": len(records)}, {"every_claim_has_adjudication_record": "PASS", "allowed_decision_space_enforced": "PASS", "indeterminate_not_false_survival": "PASS", "source_comparison_pending_explicit": "PASS"}, hash_inputs((claim_path, grounding_path)))
        write_closure(output_root, closure)
        return closure


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m08-root", required=True)
    parser.add_argument("--m10-root", required=True)
    parser.add_argument("--m12-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    result = NoveltyAdjudicationQueue().run(Path(args.m08_root), Path(args.m10_root), Path(args.m12_root), Path(args.output_root))
    print(f"TRUECOLOR_STAGE1_{MODULE_ID}=PASS")
    print(f"module_state={result.module_state}")


if __name__ == "__main__":
    main()
