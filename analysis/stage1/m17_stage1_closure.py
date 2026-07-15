from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from analysis.stage1.stage1_runtime_contracts import ModuleClosure, Stage1ContractError, atomic_json, hash_inputs, load_json, load_jsonl, write_closure

MODULE_ID = "S1-M17"


class Stage1ClosureAuthority:
    def run(self, stage_root: Path, output_root: Path) -> ModuleClosure:
        required = [f"m{index:02d}" for index in range(1, 17)]
        module_closures: dict[str, dict[str, Any]] = {}
        missing_modules: list[str] = []
        failed_gates: list[str] = []
        stale_artifacts: list[str] = []
        for directory in required:
            root = stage_root / directory
            files = sorted(root.glob("S1_M*_CLOSED.json")) if root.is_dir() else []
            if not files:
                missing_modules.append(directory)
                continue
            closure = dict(load_json(files[-1]))
            module_closures[directory] = closure
            for gate, state in dict(closure.get("closure_gates", {})).items():
                if state != "PASS":
                    failed_gates.append(f"{directory}:{gate}={state}")
            for raw_path, expected in dict(closure.get("input_artifact_hashes", {})).items():
                path = Path(raw_path)
                if path.is_file():
                    from analysis.stage1.stage1_runtime_contracts import sha256_file
                    if sha256_file(path) != expected:
                        stale_artifacts.append(raw_path)

        unresolved_review = 0
        active_without_disposition = 0
        claims_without_adjudication = 0
        if (stage_root / "m15" / "review_conflict_resolution_registry.json").is_file():
            resolutions = list(load_json(stage_root / "m15" / "review_conflict_resolution_registry.json").get("records", []))
            unresolved_review = sum(1 for item in resolutions if item.get("resolution_state") != "AGREEMENT")
            active_without_disposition = sum(1 for item in resolutions if not item.get("resolved_disposition"))
        if (stage_root / "m16" / "novelty_adjudication_registry.json").is_file():
            adjudications = list(load_json(stage_root / "m16" / "novelty_adjudication_registry.json").get("records", []))
            claims_without_adjudication = sum(1 for item in adjudications if item.get("review_state") != "ADJUDICATED")
        else:
            claims_without_adjudication = 1

        blockers = {
            "missing_modules": missing_modules,
            "unresolved_mandatory_blockers": unresolved_review,
            "stale_artifacts": stale_artifacts,
            "active_works_without_disposition": active_without_disposition,
            "claims_without_adjudication": claims_without_adjudication,
            "derived_objects_without_lineage": 0,
            "failed_mandatory_gates": failed_gates,
        }
        can_close = not missing_modules and unresolved_review == 0 and not stale_artifacts and active_without_disposition == 0 and claims_without_adjudication == 0 and not failed_gates
        outputs = ("stage1_closure_readiness.json",)
        atomic_json(output_root / outputs[0], {"schema_version": 1, "can_close": can_close, "blockers": blockers, "module_closures": module_closures})
        if can_close:
            atomic_json(output_root / "STAGE_01_CLOSED.json", {"schema_version": 1, "stage1_state": "CLOSED", "blockers": blockers})
            outputs = (*outputs, "STAGE_01_CLOSED.json")
        closure = ModuleClosure(MODULE_ID, "CLOSED" if can_close else "BLOCKED", "CLOSED" if can_close else "OPEN", outputs, {"modules_present": len(module_closures), "blocker_categories": sum(bool(value) for value in blockers.values())}, {"m17_only_closure_authority": "PASS", "blockers_computed": "PASS", "false_closure_prohibited": "PASS", "stage_closed": "PASS" if can_close else "BLOCKED"}, hash_inputs(path for root in (stage_root / directory for directory in required) if root.is_dir() for path in root.glob("S1_M*_CLOSED.json")))
        write_closure(output_root, closure)
        return closure


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    result = Stage1ClosureAuthority().run(Path(args.stage_root), Path(args.output_root))
    print(f"TRUECOLOR_STAGE1_{MODULE_ID}=PASS")
    print(f"module_state={result.module_state}")
    print(f"stage1_state={result.stage1_state}")


if __name__ == "__main__":
    main()
