from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

STAGE1 = Path("artifacts/stage_01")
REVIEW = STAGE1 / "disposition_review"


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_review_and_decision_rows_match_queue() -> None:
    queue = load_json(STAGE1 / "corpus_disposition_queue.json")

    with (REVIEW / "corpus_disposition_review.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        review_rows = list(csv.DictReader(handle))

    with (REVIEW / "corpus_disposition_decisions.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        decision_rows = list(csv.DictReader(handle))

    assert len(review_rows) == queue["task_count"]
    assert len(decision_rows) == queue["task_count"]


def test_decision_rows_are_task_hash_bound() -> None:
    queue = load_json(STAGE1 / "corpus_disposition_queue.json")
    task_by_id = {item["task_id"]: item for item in queue["tasks"]}

    with (REVIEW / "corpus_disposition_decisions.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle))

    for row in rows:
        task = task_by_id[row["task_id"]]
        assert row["task_sha256"] == task["task_sha256"]
        assert row["canonical_identity"] == task["canonical_identity"]


def test_review_hashes_validate() -> None:
    hashes = load_json(REVIEW / "corpus_disposition_review_hashes.json")
    for relative_path, expected in hashes.items():
        path = Path(relative_path)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_stage1_remains_open() -> None:
    gap = load_json(STAGE1 / "stage1_gap_report.json")
    assert gap["stage_state"] == "OPEN"
    assert not (STAGE1 / "STAGE_01_CLOSED.json").exists()
