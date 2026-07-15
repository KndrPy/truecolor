from __future__ import annotations

import argparse
from pathlib import Path

from analysis.stage1.canonical_stage1_contracts import ModuleResult, atomic_write_json
from analysis.stage1.m03_hybrid_reconstruction import HybridSpatialReconstructor
from analysis.stage1.m03_m09_evidence_pipeline import (
    AuthorModels,
    Claims,
    DJI,
    LocalOntology,
    NonBodyEvidence,
    Terminology,
)
from analysis.stage1.m03_section_path_projection import project_section_paths


def run_all(args: argparse.Namespace) -> list[ModuleResult]:
    output_root = Path(args.output_root)
    m02_root = Path(args.m02_root)
    source_integrity = m02_root / "source_integrity_registry.json"
    results: list[ModuleResult] = []

    m03_root = output_root / "m03"
    results.append(
        HybridSpatialReconstructor().reconstruct(
            Path(args.corpus_root),
            source_integrity,
            m03_root,
        )
    )
    if results[-1].module_state not in {"CLOSED", "PARTIALLY_CLOSED"}:
        raise RuntimeError(
            f"S1-M03 did not reach an executable terminal state: {results[-1].module_state}"
        )
    project_section_paths(m03_root / "document_elements.jsonl")

    m04_root = output_root / "m04"
    results.append(
        NonBodyEvidence().run(
            Path(args.corpus_root),
            source_integrity,
            m03_root,
            m04_root,
        )
    )
    m05_root = output_root / "m05"
    results.append(Terminology().run(m03_root, m05_root))
    m06_root = output_root / "m06"
    results.append(AuthorModels().run(m03_root, m06_root))
    m07_root = output_root / "m07"
    results.append(DJI().run(m03_root, m07_root))
    m08_root = output_root / "m08"
    results.append(Claims().run(m03_root, m08_root))
    m09_root = output_root / "m09"
    results.append(LocalOntology().run(m05_root, m06_root, m07_root, m09_root))

    atomic_write_json(
        output_root / "stage1_m03_m09_run_manifest.json",
        {
            "schema_version": 2,
            "m03_implementation": "HYBRID_NATIVE_AND_SELECTIVE_SPATIAL_OCR",
            "m03_fusion_policy": "PRESERVE_LAYERS_NO_SEMANTIC_OVERWRITE",
            "section_path_projection": "EXACT_HEADING_MATCH_WITH_FORWARD_INHERITANCE",
            "module_states": {
                result.module_id: result.module_state for result in results
            },
            "stage1_state": "OPEN",
        },
    )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run canonical Stage 1 modules S1-M03 through S1-M09 with hybrid reconstruction."
    )
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--m02-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    results = run_all(args)
    print("TRUECOLOR_STAGE1_M03_M09_V2=PASS")
    for result in results:
        print(f"{result.module_id}.state={result.module_state}")
    print("stage1_state=OPEN")


if __name__ == "__main__":
    main()
