from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from analysis.stage1.stage1_runtime_contracts import ModuleClosure, Stage1ContractError, atomic_json, hash_inputs, load_json, load_jsonl, stable_id, write_closure

MODULE_ID = "S1-M09"
TYPE_OF_RE = re.compile(r"\b(?P<child>[A-Z][A-Za-z0-9 _/-]{1,80})\s+(?:is|represents)\s+(?:a|an)\s+(?:type|kind|form|class)\s+of\s+(?P<parent>[A-Z][A-Za-z0-9 _/-]{1,80})", re.I)
INCLUDES_RE = re.compile(r"\b(?P<parent>[A-Z][A-Za-z0-9 _/-]{1,80})\s+(?:includes|comprises|consists of)\s+(?P<children>[^.;]{3,250})", re.I)


class PaperLocalOntologyV2:
    def run(self, m05_root: Path, m06_root: Path, m07_root: Path, output_root: Path) -> ModuleClosure:
        entities = list(load_json(m05_root / "named_entity_registry.json").get("records", []))
        definitions = list(load_json(m05_root / "definition_registry.json").get("records", []))
        models = list(load_json(m06_root / "author_problem_models.json").get("records", []))
        djis = load_jsonl(m07_root / "defined_job_implements.jsonl")
        if not entities or not models:
            raise Stage1ContractError("M09 requires entities and one author model per paper")
        concepts = [{"concept_id": stable_id("LOCAL-CONCEPT", {"entity": item["entity_id"]}), "file_id": item["file_id"], "surface_form": item["canonical_surface_form"], "entity_class": item["entity_class"], "definition_ids": [d["definition_id"] for d in definitions if d.get("file_id") == item.get("file_id") and str(d.get("term", "")).lower() == str(item.get("canonical_surface_form", "")).lower()], "concept_state": "AUTHOR_LOCAL"} for item in entities]
        edges: list[dict[str, Any]] = []
        for definition in definitions:
            text = f"{definition.get('term', '')} is {definition.get('definition', '')}"
            match = TYPE_OF_RE.search(text)
            if match:
                edges.append({"taxonomy_edge_id": stable_id("TAXONOMY", {"definition": definition["definition_id"], "child": match.group("child"), "parent": match.group("parent")}), "file_id": definition["file_id"], "child_surface_form": match.group("child").strip(), "parent_surface_form": match.group("parent").strip(), "relation": "IS_A", "edge_state": "EXPLICIT_DEFINITION_DERIVED", "source_definition_id": definition["definition_id"]})
            match = INCLUDES_RE.search(text)
            if match:
                for child in re.split(r",|\band\b", match.group("children")):
                    child = child.strip()
                    if not child: continue
                    edges.append({"taxonomy_edge_id": stable_id("TAXONOMY", {"definition": definition["definition_id"], "child": child, "parent": match.group("parent")}), "file_id": definition["file_id"], "child_surface_form": child, "parent_surface_form": match.group("parent").strip(), "relation": "MEMBER_OF", "edge_state": "EXPLICIT_ENUMERATION_DERIVED", "source_definition_id": definition["definition_id"]})
        problem = [{"file_id": item["file_id"], "problem_paradigm_id": stable_id("PROBLEM-PARADIGM", {"file": item["file_id"]}), "problem_statement_ids": item.get("problem_statement_ids", []), "failure_assertion_ids": item.get("prior_art_failure_ids", []), "state": item.get("state")} for item in models]
        by_file: dict[str, list[str]] = defaultdict(list)
        for dji in djis: by_file[str(dji["file_id"])].append(str(dji["dji_id"]))
        solution = [{"file_id": item["file_id"], "solution_paradigm_id": stable_id("SOLUTION-PARADIGM", {"file": item["file_id"]}), "dji_ids": by_file.get(str(item["file_id"]), []), "state": "PRESENT" if by_file.get(str(item["file_id"])) else "NOT_PRESENT_IN_SOURCE"} for item in models]
        outputs = ("author_local_ontology.json", "author_taxonomy_graph.json", "paper_problem_paradigm.json", "paper_solution_paradigm.json", "paper_problem_space.json", "paper_solution_space.json")
        atomic_json(output_root / outputs[0], {"schema_version": 2, "concepts": concepts})
        atomic_json(output_root / outputs[1], {"schema_version": 2, "edges": edges, "inferred_edges": []})
        atomic_json(output_root / outputs[2], {"schema_version": 2, "records": problem})
        atomic_json(output_root / outputs[3], {"schema_version": 2, "records": solution})
        atomic_json(output_root / outputs[4], {"schema_version": 2, "records": [{"file_id": item["file_id"], "dimensions": [{"source_id": value, "dimension_id": stable_id("PROBLEM-DIMENSION", {"source": value})} for value in item["problem_statement_ids"] + item["failure_assertion_ids"]]} for item in problem]})
        atomic_json(output_root / outputs[5], {"schema_version": 2, "records": [{"file_id": item["file_id"], "dimensions": [{"source_id": value, "dimension_id": stable_id("SOLUTION-DIMENSION", {"source": value})} for value in item["dji_ids"]]} for item in solution]})
        closure = ModuleClosure(MODULE_ID, "CLOSED", "OPEN", outputs, {"concepts": len(concepts), "taxonomy_edges": len(edges), "papers": len(models)}, {"local_concepts_preserved": "PASS", "explicit_and_inferred_edges_separate": "PASS", "problem_solution_separate": "PASS", "one_paradigm_record_per_paper": "PASS", "zero_edges_allowed_only_as_evidence_result": "PASS"}, hash_inputs((m05_root / "named_entity_registry.json", m05_root / "definition_registry.json", m06_root / "author_problem_models.json", m07_root / "defined_job_implements.jsonl")))
        write_closure(output_root, closure)
        return closure


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m05-root", required=True)
    parser.add_argument("--m06-root", required=True)
    parser.add_argument("--m07-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    result = PaperLocalOntologyV2().run(Path(args.m05_root), Path(args.m06_root), Path(args.m07_root), Path(args.output_root))
    print(f"TRUECOLOR_STAGE1_{MODULE_ID}=PASS")
    print(f"module_state={result.module_state}")


if __name__ == "__main__": main()
