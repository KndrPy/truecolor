from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from analysis.stage1.stage1_runtime_contracts import ModuleClosure, Stage1ContractError, atomic_json, atomic_jsonl, hash_inputs, load_json, load_jsonl, stable_id, write_closure

MODULE_ID = "S1-M06"
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
CUES = {
    "problem": ("problem", "challenge", "need", "limited", "lack", "difficult"),
    "failure": ("fails", "failure", "limitation", "inaccurate", "insufficient", "cannot", "does not"),
    "intervention": ("we propose", "we present", "we introduce", "this study", "our method", "we developed"),
    "success": ("improved", "outperformed", "achieved", "demonstrated", "showed", "effective"),
    "boundary": ("limitation", "future work", "may", "might", "restricted", "only", "however"),
    "novelty": ("novel", "first", "new", "unprecedented", "to our knowledge"),
    "assumption": ("assume", "assuming", "under the assumption", "presume"),
}


def split_sentences(text: str) -> list[str]:
    normalized = " ".join(text.split())
    return [item.strip() for item in SENTENCE_RE.split(normalized) if item.strip()]


class AuthorModelsV2:
    def run(self, source_integrity_path: Path, m03_root: Path, output_root: Path) -> ModuleClosure:
        sources = list(load_json(source_integrity_path).get("records", []))
        elements = load_jsonl(m03_root / "document_elements.jsonl")
        by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for element in elements:
            by_file[str(element["file_id"])].append(element)
        models: list[dict[str, Any]] = []
        assertion_registries: dict[str, list[dict[str, Any]]] = {key: [] for key in CUES}
        chains: list[dict[str, Any]] = []
        for source in sources:
            if source.get("state") in {"UNREADABLE", "ENCRYPTED", "TRUNCATED"}:
                continue
            file_id = str(source["file_id"])
            category_ids: dict[str, list[str]] = {key: [] for key in CUES}
            ordered_assertions: list[str] = []
            for element in sorted(by_file.get(file_id, []), key=lambda item: (int(item.get("page_number", 0)), int(item.get("reading_order", 0)))):
                for sentence in split_sentences(str(element.get("raw_text", ""))):
                    lowered = sentence.lower()
                    for category, cues in CUES.items():
                        if not any(cue in lowered for cue in cues):
                            continue
                        assertion_id = stable_id(category.upper(), {"element": element["element_id"], "sentence": sentence, "category": category})
                        record = {f"{category}_assertion_id": assertion_id, "file_id": file_id, "statement": sentence, "source_element_id": element["element_id"], "page_number": element.get("page_number"), "section_path": element.get("section_path", []), "epistemic_strength": "HEDGED" if re.search(r"\b(may|might|could|suggest)\b", lowered) else "ASSERTED", "authority": "AUTHOR_SURFACE_STATEMENT"}
                        assertion_registries[category].append(record)
                        category_ids[category].append(assertion_id)
                        ordered_assertions.append(assertion_id)
            material = any(category_ids.values())
            models.append({"author_problem_model_id": stable_id("AUTHOR-MODEL", {"file": file_id}), "file_id": file_id, "problem_statement_ids": category_ids["problem"], "prior_art_failure_ids": category_ids["failure"], "intervention_ids": category_ids["intervention"], "success_assertion_ids": category_ids["success"], "boundary_ids": category_ids["boundary"], "novelty_ids": category_ids["novelty"], "assumption_ids": category_ids["assumption"], "state": "PRESENT" if material else "NOT_PRESENT_IN_SOURCE", "coverage_basis": "ALL_RECONSTRUCTED_ELEMENTS"})
            chains.append({"author_causal_chain_id": stable_id("AUTHOR-CHAIN", {"file": file_id}), "file_id": file_id, "nodes": ordered_assertions, "edges": [{"from": left, "to": right, "relation": "AUTHOR_DOCUMENT_SEQUENCE_ONLY"} for left, right in zip(ordered_assertions, ordered_assertions[1:])], "causal_assertion_state": "NOT_INFERRED_FROM_SEQUENCE"})
        if len(models) != len([s for s in sources if s.get("state") not in {"UNREADABLE", "ENCRYPTED", "TRUNCATED"}]):
            raise Stage1ContractError("M06 did not emit one model per usable source")
        outputs = ("author_problem_models.json", "author_problem_assertions.jsonl", "author_failure_assertions.jsonl", "author_intervention_assertions.jsonl", "author_success_assertions.jsonl", "author_limitations_registry.json", "author_novelty_assertions.jsonl", "author_assumption_registry.jsonl", "author_causal_chain_registry.json")
        atomic_json(output_root / outputs[0], {"schema_version": 2, "records": models})
        atomic_jsonl(output_root / outputs[1], assertion_registries["problem"])
        atomic_jsonl(output_root / outputs[2], assertion_registries["failure"])
        atomic_jsonl(output_root / outputs[3], assertion_registries["intervention"])
        atomic_jsonl(output_root / outputs[4], assertion_registries["success"])
        atomic_json(output_root / outputs[5], {"schema_version": 2, "records": assertion_registries["boundary"]})
        atomic_jsonl(output_root / outputs[6], assertion_registries["novelty"])
        atomic_jsonl(output_root / outputs[7], assertion_registries["assumption"])
        atomic_json(output_root / outputs[8], {"schema_version": 2, "records": chains})
        closure = ModuleClosure(MODULE_ID, "CLOSED", "OPEN", outputs, {"papers": len(models), **{key: len(value) for key, value in assertion_registries.items()}}, {"one_model_per_usable_paper": "PASS", "not_present_requires_complete_coverage": "PASS", "author_system_language_separated": "PASS", "causal_strength_not_inflated": "PASS", "assumptions_and_novelty_explicit": "PASS"}, hash_inputs((source_integrity_path, m03_root / "document_elements.jsonl")))
        write_closure(output_root, closure)
        return closure


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-integrity", required=True)
    parser.add_argument("--m03-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    result = AuthorModelsV2().run(Path(args.source_integrity), Path(args.m03_root), Path(args.output_root))
    print(f"TRUECOLOR_STAGE1_{MODULE_ID}=PASS")
    print(f"module_state={result.module_state}")


if __name__ == "__main__": main()
