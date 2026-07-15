from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from analysis.stage1.m03_section_path_projection import project_section_paths
from analysis.stage1.m04_scientific_nonbody_v2 import ScientificNonBodyEvidenceV2
from analysis.stage1.m06_author_models_v2 import AuthorModelsV2
from analysis.stage1.m09_local_ontology_v2 import PaperLocalOntologyV2
from analysis.stage1.m03_m09_evidence_pipeline import Terminology, DJI, Claims
from analysis.stage1.stage1_m10_m17_pipeline import run as run_m10_m17


def run(args: argparse.Namespace) -> None:
    stage = Path(args.stage_root)
    m03_source = Path(args.m03_root)
    m03 = stage / "m03"
    if m03.resolve() != m03_source.resolve():
        if m03.exists(): shutil.rmtree(m03)
        shutil.copytree(m03_source, m03)
    project_section_paths(m03 / "document_elements.jsonl")
    m02 = Path(args.m02_root)
    ScientificNonBodyEvidenceV2().run(Path(args.corpus_root), m02 / "source_integrity_registry.json", m03, stage / "m04")
    Terminology().run(m03, stage / "m05")
    AuthorModelsV2().run(m02 / "source_integrity_registry.json", m03, stage / "m06")
    DJI().run(m03, stage / "m07")
    Claims().run(m03, stage / "m08")
    PaperLocalOntologyV2().run(stage / "m05", stage / "m06", stage / "m07", stage / "m09")
    args.stage_root = stage.as_posix()
    run_m10_m17(args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sequential Stage 1 M03-M17 consumer pipeline. Reuses validated M03 and never bypasses closure contracts.")
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--m01-root", required=True)
    parser.add_argument("--m02-root", required=True)
    parser.add_argument("--m03-root", required=True)
    parser.add_argument("--stage-root", required=True)
    args = parser.parse_args()
    run(args)
    print("TRUECOLOR_STAGE1_M03_M17_V3=PASS")


if __name__ == "__main__": main()
