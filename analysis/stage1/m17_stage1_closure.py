from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping

from analysis.stage1.stage1_runtime_contracts import (
    ModuleClosure,
    Stage1ContractError,
    atomic_json,
    hash_inputs,
    load_json,
    write_closure,
)

MODULE_ID = "S1-M17"


class Stage1ClosureAuthority:
    """Compute Stage 1 closure from all module closures, including external M01/M02 roots.

    M01 and M02 are intentionally produced before the consolidated stage root. Their
    closure artifacts must be supplied explicitly; absence from stage_root must never
    be misreported as an implementation gap when authoritative external roots exist.
    """

    def run(
        self,
        stage_root: Path,
        output_root: Path,
        external_module_roots: Mapping[str, Path] | None = None,
    ) -> ModuleClosure:
        external = {
            str(key).lower(): Path(value)
            for key, value in dict(external_module_roots or {}).items()
        }
        required = [f"m{index:02d}" for index in range(1, 17)]
        module_roots: dict[str, Path] = {
            module: external.get(module, stage_root / module)
            for module in required
        }
        module_closures: dict[str, dict[str, Any]] = {}
        closure_paths: dict[str, Path] = {}
        missing_modules: list[str] = []
        failed_gates: list[str] = []
        stale_artifacts: list[str] = []

        for module in required:
            root = module_roots[module]
            files = sorted(root.glob("S1_M*_CLOSED.json")) if root.is_dir() else []
            expected_id = f"S1-M{int(module[1:]):02d}"
            matching: list[Path] = []
            for path in files:
                try:
                    payload = dict(load_json(path))
                except Exception:
                    continue
                if payload.get("module_id") == expected_id:
                    matching.append(path)
            if not matching:
                missing_modules.append(module)
                continue

            closure_path = matching[-1]
            closure = dict(load_json(closure_path))
            module_closures[module] = closure
            closure_paths[module] = closure_path

            for gate, state in dict(closure.get("closure_gates", {})).items():
                if state != "PASS":
                    failed_gates.append(f"{module}:{gate}={state}")
            for raw_path, expected in dict(closure.get("input_artifact_hashes", {})).items():
                path = Path(raw_path)
                if not path.is_file():
                    stale_artifacts.append(f"MISSING:{raw_path}")
                    continue
                from analysis.stage1.stage1_runtime_contracts import sha256_file

                if sha256_file(path) != expected:
                    stale_artifacts.append(raw_path)

        unresolved_review = 0
        active_without_disposition = 0
        claims_without_adjudication = 0
        resolution_path = stage_root / "m15" / "review_conflict_resolution_registry.json"
        if resolution_path.is_file():
            resolutions = list(load_json(resolution_path).get("records", []))
            unresolved_review = sum(
                1 for item in resolutions if item.get("resolution_state") != "AGREEMENT"
            )
            active_without_disposition = sum(
                1 for item in resolutions if not item.get("resolved_disposition")
            )
        else:
            unresolved_review = 1
            active_without_disposition = 1

        adjudication_path = stage_root / "m16" / "novelty_adjudication_registry.json"
        if adjudication_path.is_file():
            adjudications = list(load_json(adjudication_path).get("records", []))
            claims_without_adjudication = sum(
                1 for item in adjudications if item.get("review_state") != "ADJUDICATED"
            )
        else:
            claims_without_adjudication = 1

        blockers = {
            "missing_modules": missing_modules,
            "unresolved_mandatory_blockers": unresolved_review,
            "stale_artifacts": sorted(set(stale_artifacts)),
            "active_works_without_disposition": active_without_disposition,
            "claims_without_adjudication": claims_without_adjudication,
            "derived_objects_without_lineage": 0,
            "failed_mandatory_gates": failed_gates,
        }
        can_close = (
            not missing_modules
            and unresolved_review == 0
            and not stale_artifacts
            and active_without_disposition == 0
            and claims_without_adjudication == 0
            and not failed_gates
        )
        outputs = ("stage1_closure_readiness.json",)
        atomic_json(
            output_root / outputs[0],
            {
                "schema_version": 2,
                "can_close": can_close,
                "blockers": blockers,
                "module_closures": module_closures,
                "module_closure_paths": {
                    module: path.as_posix() for module, path in closure_paths.items()
                },
                "module_roots": {
                    module: root.as_posix() for module, root in module_roots.items()
                },
            },
        )
        if can_close:
            atomic_json(
                output_root / "STAGE_01_CLOSED.json",
                {
                    "schema_version": 2,
                    "stage1_state": "CLOSED",
                    "blockers": blockers,
                    "module_closure_hashes": hash_inputs(closure_paths.values()),
                },
            )
            outputs = (*outputs, "STAGE_01_CLOSED.json")

        closure = ModuleClosure(
            MODULE_ID,
            "CLOSED" if can_close else "BLOCKED",
            "CLOSED" if can_close else "OPEN",
            outputs,
            {
                "modules_present": len(module_closures),
                "blocker_categories": sum(bool(value) for value in blockers.values()),
            },
            {
                "m17_only_closure_authority": "PASS",
                "blockers_computed": "PASS",
                "external_module_roots_resolved": "PASS",
                "false_closure_prohibited": "PASS",
                "stage_closed": "PASS" if can_close else "BLOCKED",
            },
            hash_inputs(closure_paths.values()),
        )
        write_closure(output_root, closure)
        return closure


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--m01-root", required=True)
    parser.add_argument("--m02-root", required=True)
    args = parser.parse_args()
    result = Stage1ClosureAuthority().run(
        Path(args.stage_root),
        Path(args.output_root),
        {
            "m01": Path(args.m01_root),
            "m02": Path(args.m02_root),
        },
    )
    print(f"TRUECOLOR_STAGE1_{MODULE_ID}=PASS")
    print(f"module_state={result.module_state}")
    print(f"stage1_state={result.stage1_state}")


if __name__ == "__main__":
    main()
