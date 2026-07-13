from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path("analysis/prior_art")

COHORT_PATH = (
    ROOT
    / "evidence/identity_resolution/"
    "adversarial_pilot_cohort.json"
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(value, dict):
        raise TypeError(
            f"Expected JSON object: {path}"
        )

    return value


def cohort_ranks() -> list[int]:
    artifact = load_json(COHORT_PATH)

    records = artifact.get("records")

    if not isinstance(records, list):
        raise TypeError(
            "Cohort records must be a list"
        )

    declared_count = int(
        artifact.get("record_count", -1)
    )

    if declared_count != 48:
        raise ValueError(
            "ADVERSARIAL_COHORT_DECLARED_COUNT_"
            f"INVALID={declared_count}"
        )

    ranks = [
        int(record["global_rank"])
        for record in records
    ]

    if len(ranks) != 48:
        raise ValueError(
            "ADVERSARIAL_COHORT_RECORD_COUNT_"
            f"INVALID={len(ranks)}"
        )

    if len(set(ranks)) != len(ranks):
        raise ValueError(
            "ADVERSARIAL_COHORT_DUPLICATE_RANK"
        )

    if min(ranks) < 1 or max(ranks) > 1303:
        raise ValueError(
            "ADVERSARIAL_COHORT_RANK_OUT_OF_RANGE"
        )

    return sorted(ranks)


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--execute",
        action="store_true",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
    )

    args = parser.parse_args()

    ranks = cohort_ranks()

    print(
        f"ADVERSARIAL_COHORT_SIZE={len(ranks)}"
    )
    print(
        "ADVERSARIAL_COHORT_RANKS="
        + ",".join(str(rank) for rank in ranks)
    )

    if not args.execute:
        print(
            "ADVERSARIAL_COHORT_MODE=DRY_RUN"
        )
        return 0

    print(
        "ADVERSARIAL_COHORT_MODE=EXECUTE"
    )

    succeeded = []
    failed = []

    for rank in ranks:
        command = [
            sys.executable,
            "-m",
            (
                "analysis.prior_art."
                "resolve_stage1_identities"
            ),
            "--start-rank",
            str(rank),
            "--end-rank",
            str(rank),
            "--timeout",
            str(args.timeout),
            "--delay",
            str(args.delay),
        ]

        if args.overwrite:
            command.append("--overwrite")

        print(
            f"EXECUTING_RANK={rank:04d}",
            flush=True,
        )

        completed = subprocess.run(
            command,
            check=False,
        )

        if completed.returncode == 0:
            succeeded.append(rank)
        else:
            failed.append({
                "global_rank": rank,
                "returncode": (
                    completed.returncode
                ),
            })

    print(
        f"ADVERSARIAL_SUCCEEDED="
        f"{len(succeeded)}"
    )
    print(
        f"ADVERSARIAL_FAILED="
        f"{len(failed)}"
    )

    if failed:
        print(
            json.dumps(
                failed,
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    print(
        "ADVERSARIAL_COHORT_EXECUTION=PASS"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
