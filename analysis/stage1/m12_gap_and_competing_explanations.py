from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from analysis.stage1.stage1_runtime_contracts import (
    ModuleClosure,
    Stage1ContractError,
    atomic_json,
    atomic_jsonl,
    hash_inputs,
    load_jsonl,
    stable_id,
    write_closure,
)

MODULE_ID = "S1-M12"
HEDGE_RE = re.compile(r"\b(may|might|could|suggest|appears|possibly|potentially)\b", re.I)
GENERALIZE_RE = re.compile(r"\b(all|always|universal|generaliz|across populations|real world)\b", re.I)
CAUSAL_RE = re.compile(r"\b(cause|causes|caused|leads to|results in|drives)\b", re.I)


class GapAndCompetingExplanationAnalysis:
    def run(self, m11_root: Path, output_root: Path) -> ModuleClosure:
        grounding_path = m11_root / "claim_grounding_registry.jsonl"
        groundings = load_jsonl(grounding_path)
        if not groundings:
            raise Stage1ContractError("M12 requires grounded claims")
        gaps: list[dict[str, Any]] = []
        alternatives: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []
        for grounding in groundings:
            item = dict(grounding)
            statement = str(item.get("author_position", ""))
            detected: list[dict[str, Any]] = []
            if HEDGE_RE.search(statement):
                detected.append({"gap_type": "EPISTEMIC_UNCERTAINTY", "basis": "AUTHOR_HEDGE", "state": "PRESENT"})
            if GENERALIZE_RE.search(statement):
                detected.append({"gap_type": "GENERALIZATION_BOUNDARY", "basis": "BROAD_SCOPE_LANGUAGE", "state": "REVIEW_REQUIRED"})
            if CAUSAL_RE.search(statement):
                detected.append({"gap_type": "CAUSAL_IDENTIFICATION", "basis": "CAUSAL_LANGUAGE_REQUIRES_DESIGN_REVIEW", "state": "REVIEW_REQUIRED"})
                alternatives.append(
                    {
                        "alternative_explanation_id": stable_id("ALT-EXPLANATION", {"claim": item.get("claim_id"), "type": "CONFOUNDING"}),
                        "claim_id": item.get("claim_id"),
                        "candidate": "Observed association may reflect confounding, measurement coupling, selection, or model specification.",
                        "authority": "SYSTEM_DERIVED_CANDIDATE",
                        "review_state": "PENDING_REVIEW",
                    }
                )
            if not detected:
                detected.append({"gap_type": "NO_AUTOMATIC_GAP_SIGNAL", "basis": "RULE_SCREEN_ONLY", "state": "REVIEW_REQUIRED"})
            for gap in detected:
                gaps.append({"gap_id": stable_id("GAP", {"claim": item.get("claim_id"), **gap}), "claim_id": item.get("claim_id"), **gap})
            item["logical_gap"] = [gap["gap_type"] for gap in detected if gap["gap_type"] in {"CAUSAL_IDENTIFICATION"}]
            item["generalization_boundary"] = [gap["gap_type"] for gap in detected if gap["gap_type"] == "GENERALIZATION_BOUNDARY"]
            item["alternative_explanations"] = [alt["alternative_explanation_id"] for alt in alternatives if alt["claim_id"] == item.get("claim_id")]
            item["review_state"] = "PENDING_PRIMARY_REVIEW"
            updated.append(item)

        outputs = ("grounded_claim_assessment_registry.jsonl", "scientific_gap_registry.json", "alternative_explanation_registry.json")
        atomic_jsonl(output_root / outputs[0], updated)
        atomic_json(output_root / outputs[1], {"schema_version": 1, "records": gaps})
        atomic_json(output_root / outputs[2], {"schema_version": 1, "records": alternatives})
        closure = ModuleClosure(
            MODULE_ID,
            "CLOSED",
            "OPEN",
            outputs,
            {"claims": len(updated), "gaps": len(gaps), "alternative_explanations": len(alternatives)},
            {"all_claims_screened": "PASS", "system_inference_labeled": "PASS", "author_language_preserved": "PASS", "review_required_not_auto_resolved": "PASS"},
            hash_inputs((grounding_path,)),
        )
        write_closure(output_root, closure)
        return closure


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m11-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    result = GapAndCompetingExplanationAnalysis().run(Path(args.m11_root), Path(args.output_root))
    print(f"TRUECOLOR_STAGE1_{MODULE_ID}=PASS")
    print(f"module_state={result.module_state}")


if __name__ == "__main__":
    main()
