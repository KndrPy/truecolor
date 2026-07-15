from __future__ import annotations

import argparse
from pathlib import Path

from analysis.prior_art.mutable_corpus_closure_validator import validate_consumer_closure
from analysis.stage1.stage1_runtime_contracts import ModuleClosure, hash_inputs, write_closure

MODULE_ID = "S1-M01"


def materialize_m01_closure(m01_root: Path) -> ModuleClosure:
    """Validate the legacy M01 artifact set and emit the canonical Stage 1 closure record.

    This adapter does not reinterpret or weaken M01. It delegates to the existing
    closure validator, preserves its gates, hashes the validated evidence set, and
    creates the canonical S1_M01_CLOSED.json consumed by M17.
    """
    gates = dict(validate_consumer_closure(m01_root))
    required = [
        m01_root / "physical_file_registry.json",
        m01_root / "document_version_registry.json",
        m01_root / "work_identity_state_registry.json",
        m01_root / "mutable_corpus_contract.json",
        m01_root / "stage1_review_queue_projection.json",
        m01_root / "extraction_recovery_queue.json",
    ]
    missing = [path.as_posix() for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("M01 canonical evidence missing after closure validation: " + ", ".join(missing))
    closure = ModuleClosure(
        MODULE_ID,
        "CLOSED",
        "OPEN",
        tuple(path.name for path in required),
        {
            "validated_artifacts": len(required),
            "closure_gates": len(gates),
        },
        {**gates, "canonical_closure_adapter": "PASS"},
        hash_inputs(required),
    )
    write_closure(m01_root, closure)
    return closure


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize canonical S1-M01 closure from validated mutable-corpus artifacts.")
    parser.add_argument("--m01-root", required=True)
    args = parser.parse_args()
    result = materialize_m01_closure(Path(args.m01_root))
    print("TRUECOLOR_STAGE1_S1-M01=PASS")
    print(f"module_state={result.module_state}")
    print(f"stage1_state={result.stage1_state}")


if __name__ == "__main__":
    main()
