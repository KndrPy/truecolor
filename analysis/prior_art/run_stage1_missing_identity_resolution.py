from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


NORMALIZED_ROOT = Path(
    "analysis/prior_art/evidence/"
    "identity_resolution/normalized"
)

REPORT_ROOT = Path(
    "analysis/prior_art/evidence/"
    "identity_resolution/reports"
)


def resolved_ranks() -> set[int]:
    ranks: set[int] = set()

    for path in NORMALIZED_ROOT.glob(
        "global-*.json"
    ):
        parts = path.stem.split("-")

        if len(parts) != 2:
            raise ValueError(
                f"Invalid normalized filename: {path}"
            )

        ranks.add(int(parts[1]))

    return ranks


def contiguous_ranges(
    ranks: list[int],
    maximum_batch_size: int,
) -> list[tuple[int, int]]:
    if maximum_batch_size < 1:
        raise ValueError(
            "maximum_batch_size must be >= 1"
        )

    if not ranks:
        return []

    ranges: list[tuple[int, int]] = []

    start = ranks[0]
    previous = ranks[0]

    for rank in ranks[1:]:
        is_contiguous = (
            rank == previous + 1
        )

        within_batch = (
            rank - start + 1
            <= maximum_batch_size
        )

        if is_contiguous and within_batch:
            previous = rank
            continue

        ranges.append((start, previous))
        start = rank
        previous = rank

    ranges.append((start, previous))

    return ranges


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
        default=0.35,
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
    )

    parser.add_argument(
        "--max-batches",
        type=int,
        default=None,
    )

    args = parser.parse_args()

    if args.timeout < 1:
        raise ValueError(
            "timeout must be >= 1"
        )

    if args.delay < 0:
        raise ValueError(
            "delay must be >= 0"
        )

    if args.batch_size < 1:
        raise ValueError(
            "batch-size must be >= 1"
        )

    if (
        args.max_batches is not None
        and args.max_batches < 1
    ):
        raise ValueError(
            "max-batches must be >= 1"
        )

    expected = set(range(1, 1304))

    present_before = resolved_ranks()

    unexpected_present = sorted(
        present_before - expected
    )

    if unexpected_present:
        raise ValueError(
            "Normalized ranks outside 1-1303: "
            f"{unexpected_present}"
        )

    missing_before = sorted(
        expected - present_before
    )

    ranges = contiguous_ranges(
        missing_before,
        args.batch_size,
    )

    if args.max_batches is not None:
        ranges = ranges[
            :args.max_batches
        ]

    selected_ranks = [
        rank
        for start, end in ranges
        for rank in range(start, end + 1)
    ]

    print(
        "STAGE1_MODE="
        + (
            "EXECUTE"
            if args.execute
            else "DRY_RUN"
        )
    )
    print(
        f"PRESENT_BEFORE="
        f"{len(present_before)}"
    )
    print(
        f"MISSING_BEFORE="
        f"{len(missing_before)}"
    )
    print(
        f"SELECTED_RANKS="
        f"{len(selected_ranks)}"
    )
    print(
        f"SELECTED_BATCHES="
        f"{len(ranges)}"
    )

    for start, end in ranges:
        print(
            f"SELECTED_RANGE="
            f"{start:04d}-{end:04d}"
        )

    if not args.execute:
        print(
            "STAGE1_MISSING_RUNNER_DRY_RUN=PASS"
        )
        return 0

    REPORT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    completed_batches = []
    failed_batches = []

    for index, (start, end) in enumerate(
        ranges,
        start=1,
    ):
        print(
            f"EXECUTING_BATCH={index}/"
            f"{len(ranges)} "
            f"RANGE={start:04d}-{end:04d}",
            flush=True,
        )

        command = [
            sys.executable,
            "-m",
            (
                "analysis.prior_art."
                "resolve_stage1_identities"
            ),
            "--start-rank",
            str(start),
            "--end-rank",
            str(end),
            "--timeout",
            str(args.timeout),
            "--delay",
            str(args.delay),
        ]

        completed = subprocess.run(
            command,
            check=False,
        )

        record = {
            "batch_index": index,
            "start_rank": start,
            "end_rank": end,
            "returncode": completed.returncode,
        }

        if completed.returncode == 0:
            completed_batches.append(record)
        else:
            failed_batches.append(record)

    present_after = resolved_ranks()

    newly_present = sorted(
        present_after - present_before
    )

    missing_after = sorted(
        expected - present_after
    )

    selected_not_created = sorted(
        set(selected_ranks) - present_after
    )

    report = {
        "expected_rank_count": 1303,
        "present_before": len(
            present_before
        ),
        "missing_before": len(
            missing_before
        ),
        "selected_rank_count": len(
            selected_ranks
        ),
        "selected_batch_count": len(
            ranges
        ),
        "completed_batches": (
            completed_batches
        ),
        "failed_batches": failed_batches,
        "newly_present_count": len(
            newly_present
        ),
        "selected_not_created": (
            selected_not_created
        ),
        "present_after": len(
            present_after
        ),
        "missing_after": len(
            missing_after
        ),
    }

    report_path = (
        REPORT_ROOT
        / "stage1-missing-production-run.json"
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"NEWLY_PRESENT="
        f"{len(newly_present)}"
    )
    print(
        f"SELECTED_NOT_CREATED="
        f"{len(selected_not_created)}"
    )
    print(
        f"PRESENT_AFTER="
        f"{len(present_after)}"
    )
    print(
        f"MISSING_AFTER="
        f"{len(missing_after)}"
    )
    print(
        f"FAILED_BATCHES="
        f"{len(failed_batches)}"
    )
    print(
        f"RUN_REPORT={report_path}"
    )

    if failed_batches:
        print(
            "STAGE1_MISSING_PRODUCTION_RUN=FAIL"
        )
        return 1

    if selected_not_created:
        print(
            "STAGE1_SELECTED_RANKS_INCOMPLETE=FAIL"
        )
        return 1

    print(
        "STAGE1_MISSING_PRODUCTION_RUN=PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
