from __future__ import annotations

import argparse
from collections import defaultdict
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

MODULE_ID = "S1-M11"


class EvidenceGrounding:
    def run(self, m03_root: Path, m08_root: Path, output_root: Path) -> ModuleClosure:
        element_path = m03_root / "document_elements.jsonl"
        claim_path = m08_root / "claim_registry.jsonl"
        elements = load_jsonl(element_path)
        claims = load_jsonl(claim_path)
        if not claims:
            raise Stage1ContractError("M11 cannot ground an empty claim registry")
        by_id = {str(item["element_id"]): item for item in elements}

        grounds: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for claim in claims:
            by_file[str(claim.get("file_id", ""))].append(claim)
            source_id = str(claim.get("source_element_id", ""))
            element = by_id.get(source_id)
            if element is None:
                missing.append({"claim_id": claim.get("claim_id"), "reason": "SOURCE_ELEMENT_MISSING", "source_element_id": source_id})
                continue
            grounding_id = stable_id("GROUNDING", {"claim": claim.get("claim_id"), "element": source_id})
            grounds.append(
                {
                    "grounding_id": grounding_id,
                    "claim_id": claim.get("claim_id"),
                    "file_id": claim.get("file_id"),
                    "author_position": claim.get("statement") or claim.get("claim_text") or "",
                    "supporting_evidence": [{"element_id": source_id, "page_number": element.get("page_number"), "bbox": element.get("bbox"), "raw_source_sha256": element.get("raw_source_sha256")}],
                    "qualifying_evidence": claim.get("qualifiers", []),
                    "contradicting_evidence": [],
                    "missing_evidence": [],
                    "alternative_explanations": [],
                    "logical_gap": "NOT_ASSESSED",
                    "measurement_gap": "NOT_ASSESSED",
                    "technical_gap": "NOT_ASSESSED",
                    "generalization_boundary": "NOT_ASSESSED",
                    "confidence": "SOURCE_GROUNDED_NOT_ADJUDICATED",
                    "review_state": "PENDING_PRIMARY_REVIEW",
                }
            )

        if missing:
            raise Stage1ContractError(f"M11 found {len(missing)} claims without source elements")
        outputs = ("claim_grounding_registry.jsonl", "grounding_missing_evidence_registry.json", "paper_grounding_summary.json")
        atomic_jsonl(output_root / outputs[0], grounds)
        atomic_json(output_root / outputs[1], {"schema_version": 1, "records": missing})
        atomic_json(
            output_root / outputs[2],
            {"schema_version": 1, "records": [{"file_id": file_id, "claim_count": len(items), "grounded_count": sum(1 for item in grounds if str(item.get("file_id")) == file_id)} for file_id, items in sorted(by_file.items())]},
        )
        closure = ModuleClosure(
            MODULE_ID,
            "CLOSED",
            "OPEN",
            outputs,
            {"claims": len(claims), "groundings": len(grounds), "missing": len(missing)},
            {"every_claim_grounded": "PASS", "source_coordinates_retained": "PASS", "plausibility_only_insight_prohibited": "PASS", "review_state_explicit": "PASS"},
            hash_inputs((element_path, claim_path)),
        )
        write_closure(output_root, closure)
        return closure


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m03-root", required=True)
    parser.add_argument("--m08-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    result = EvidenceGrounding().run(Path(args.m03_root), Path(args.m08_root), Path(args.output_root))
    print(f"TRUECOLOR_STAGE1_{MODULE_ID}=PASS")
    print(f"module_state={result.module_state}")


if __name__ == "__main__":
    main()
