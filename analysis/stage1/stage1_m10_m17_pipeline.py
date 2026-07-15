from __future__ import annotations

import argparse
from pathlib import Path

from analysis.stage1.m01_closure_adapter import materialize_m01_closure
from analysis.stage1.m10_corpus_ontology_alignment import CorpusOntologyAlignment
from analysis.stage1.m11_evidence_grounding import EvidenceGrounding
from analysis.stage1.m12_gap_and_competing_explanations import GapAndCompetingExplanationAnalysis
from analysis.stage1.m13_primary_review import PrimaryReviewQueue
from analysis.stage1.m14_independent_review import IndependentReviewQueue
from analysis.stage1.m15_review_conflict_resolution import ReviewConflictResolution
from analysis.stage1.m16_novelty_adjudication import NoveltyAdjudicationQueue
from analysis.stage1.m17_stage1_closure import Stage1ClosureAuthority


def run(args: argparse.Namespace) -> None:
    root = Path(args.stage_root)
    m01_root = Path(args.m01_root)
    m02_root = Path(args.m02_root)
    materialize_m01_closure(m01_root)
    CorpusOntologyAlignment().run(root / "m05", root / "m09", root / "m10")
    EvidenceGrounding().run(root / "m03", root / "m08", root / "m11")
    GapAndCompetingExplanationAnalysis().run(root / "m11", root / "m12")
    PrimaryReviewQueue().run(m01_root, root / "m12", root / "m13")
    IndependentReviewQueue().run(root / "m13", root / "m14")
    ReviewConflictResolution().run(root / "m13", root / "m14", root / "m15")
    NoveltyAdjudicationQueue().run(root / "m08", root / "m10", root / "m12", root / "m16")
    Stage1ClosureAuthority().run(
        root,
        root / "m17",
        {"m01": m01_root, "m02": m02_root},
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Stage 1 M10 through M17 sequentially without bypassing module contracts."
    )
    parser.add_argument("--stage-root", required=True)
    parser.add_argument("--m01-root", required=True)
    parser.add_argument("--m02-root", required=True)
    args = parser.parse_args()
    run(args)
    print("TRUECOLOR_STAGE1_M10_M17=PASS")


if __name__ == "__main__":
    main()
