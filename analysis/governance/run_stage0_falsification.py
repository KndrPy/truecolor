from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

import yaml


REPO = Path.cwd()
RUNNER = [
    sys.executable,
    "-m",
    "analysis.governance.run_stage0",
]


def execute(output_dir: Path) -> tuple[int, dict]:
    completed = subprocess.run(
        RUNNER
        + [
            "--output-dir",
            str(output_dir),
            "--allow-dirty",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    summary_path = output_dir / "stage0_summary.json"

    if not summary_path.exists():
        raise RuntimeError(
            "Stage 0 runner did not produce stage0_summary.json.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )

    summary = json.loads(
        summary_path.read_text(encoding="utf-8")
    )

    return completed.returncode, summary


def run_mutation_test(
    *,
    name: str,
    path: Path,
    mutate: Callable[[str], str],
    expected_failed_gates: set[str],
    root: Path,
) -> dict:
    original = path.read_text(encoding="utf-8")

    try:
        mutated = mutate(original)

        if mutated == original:
            raise RuntimeError(
                f"Mutation made no change for {name}"
            )

        path.write_text(
            mutated,
            encoding="utf-8",
        )

        output_dir = root / name
        returncode, summary = execute(output_dir)

        observed_failed = set(
            summary["failed_gates"]
        )

        passed = (
            returncode != 0
            and summary["status"]
            == "OPEN_FAILED_GATES"
            and expected_failed_gates
            <= observed_failed
        )

        return {
            "test": name,
            "passed": passed,
            "runner_returncode": returncode,
            "expected_failed_gates": sorted(
                expected_failed_gates
            ),
            "observed_failed_gates": sorted(
                observed_failed
            ),
            "status": summary["status"],
        }

    finally:
        path.write_text(
            original,
            encoding="utf-8",
        )


def remove_scin(text: str) -> str:
    data = yaml.safe_load(text)

    removed = data["assets"].pop(
        "scin",
        None,
    )

    if removed is None:
        raise RuntimeError(
            "SCIN asset was not present."
        )

    return yaml.safe_dump(
        data,
        sort_keys=False,
        width=100,
    )


def corrupt_stage_ids(text: str) -> str:
    data = yaml.safe_load(text)

    data["stages"][1]["stage"] = 99

    return yaml.safe_dump(
        data,
        sort_keys=False,
        width=100,
    )


def remove_work_ignore(text: str) -> str:
    lines = text.splitlines()

    filtered = [
        line
        for line in lines
        if line.strip() != "work/"
    ]

    return "\n".join(filtered).rstrip() + "\n"


def main() -> int:
    governance = (
        REPO / "analysis/governance"
    )

    with tempfile.TemporaryDirectory(
        prefix="truecolor-stage0-falsification-"
    ) as temp:
        root = Path(temp)

        results = [
            run_mutation_test(
                name="missing_scin_registration",
                path=(
                    governance
                    / "data_asset_registry.yaml"
                ),
                mutate=remove_scin,
                expected_failed_gates={
                    "required_assets_registered",
                    "scin_registered",
                },
                root=root,
            ),
            run_mutation_test(
                name="invalid_stage_numbering",
                path=(
                    governance
                    / "stage_registry.yaml"
                ),
                mutate=corrupt_stage_ids,
                expected_failed_gates={
                    "stage_ids_exact",
                },
                root=root,
            ),
            run_mutation_test(
                name="missing_work_ignore_rule",
                path=REPO / ".gitignore",
                mutate=remove_work_ignore,
                expected_failed_gates={
                    "gitignore_hygiene",
                },
                root=root,
            ),
        ]

    output = (
        governance
        / "results"
        / "stage0_falsification_results.json"
    )
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    all_passed = all(
        result["passed"]
        for result in results
    )

    payload = {
        "stage": 0,
        "falsification_status": (
            "PASS"
            if all_passed
            else "FAIL"
        ),
        "tests": results,
    }

    output.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
    )

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
