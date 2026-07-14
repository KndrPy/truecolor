from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
PRIOR_ART = ROOT / "analysis" / "prior_art"
STAGE1 = ROOT / "artifacts" / "stage_01"

INVENTORY_PATH = STAGE1 / "stage1_evidence_inventory.json"
SOURCE_STATE_PATH = STAGE1 / "source_state_register.json"
EVIDENCE_RECORD_PATH = STAGE1 / "evidence_record_register.json"
SECOND_REVIEW_PATH = STAGE1 / "second_review_register.json"
MATRIX_PATH = STAGE1 / "scientific_matrix_register.json"
KILL_PATH = STAGE1 / "kill_condition_register.json"
UNSUPPORTED_PATH = STAGE1 / "unsupported_field_register.json"
GAP_PATH = STAGE1 / "stage1_gap_report.json"
HASH_PATH = STAGE1 / "artifact_hashes.json"
RUN_PATH = STAGE1 / "stage1_ledger_run.json"

TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".csv",
    ".tsv",
    ".md",
    ".txt",
}

SOURCE_STATE_TERMS = (
    "terminal source state",
    "source_state",
    "source status",
    "acquisition status",
    "terminal_state",
)

EVIDENCE_RECORD_TERMS = (
    "evidence record",
    "evidence_record",
    "selected source lines",
    "evidence ranges",
    "claim evidence",
)

SECOND_REVIEW_TERMS = (
    "second review",
    "secondary review",
    "independent review",
    "reviewer 2",
    "adversarial review",
)

MATRIX_TERMS = (
    "claim matrix",
    "scientific matrix",
    "novelty matrix",
    "evidence matrix",
    "comparison matrix",
    "prior-art matrix",
)

KILL_TERMS = (
    "kill condition",
    "kill_condition",
    "novelty kill",
    "claim kill",
    "falsification decision",
)

UNSUPPORTED_TERMS = (
    "unsupported field",
    "unsupported_fields",
    "not reported",
    "not available",
    "unknown",
    "unresolved",
)

EXCLUDED_PATH_PARTS = {
    ".git",
    "target",
    ".venv",
    "__pycache__",
}


@dataclass(frozen=True)
class InventoryRecord:
    path: str
    bytes: int
    sha256: str
    suffix: str
    categories: tuple[str, ...]
    structured_keys: tuple[str, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def repository_relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def eligible_files() -> Iterable[Path]:
    if not PRIOR_ART.is_dir():
        return ()

    paths: list[Path] = []

    for path in PRIOR_ART.rglob("*"):
        if not path.is_file():
            continue

        if any(part in EXCLUDED_PATH_PARTS for part in path.parts):
            continue

        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue

        paths.append(path)

    return sorted(paths, key=repository_relative)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(
            encoding="utf-8",
            errors="replace",
        )


def structured_keys(path: Path, text: str) -> tuple[str, ...]:
    suffix = path.suffix.lower()
    keys: set[str] = set()

    if suffix == ".json":
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return ()

        if isinstance(value, dict):
            keys.update(str(key) for key in value)

        elif isinstance(value, list):
            for item in value[:50]:
                if isinstance(item, dict):
                    keys.update(str(key) for key in item)

    elif suffix == ".jsonl":
        for line in text.splitlines()[:50]:
            if not line.strip():
                continue

            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(item, dict):
                keys.update(str(key) for key in item)

    elif suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","

        try:
            reader = csv.reader(text.splitlines(), delimiter=delimiter)
            header = next(reader, [])
        except csv.Error:
            return ()

        keys.update(cell.strip() for cell in header if cell.strip())

    else:
        for match in re.finditer(
            r"(?m)^[ \t]*([A-Za-z][A-Za-z0-9_.-]{1,80})[ \t]*:",
            text,
        ):
            keys.add(match.group(1))

    return tuple(sorted(keys))


def contains_term(
    normalized_text: str,
    normalized_path: str,
    terms: tuple[str, ...],
) -> bool:
    return any(
        term in normalized_text
        or term.replace(" ", "_") in normalized_path
        or term.replace(" ", "-") in normalized_path
        for term in terms
    )


def classify(
    path: Path,
    text: str,
    keys: tuple[str, ...],
) -> tuple[str, ...]:
    normalized_text = text.lower()
    normalized_path = repository_relative(path).lower()
    normalized_keys = {key.lower() for key in keys}

    categories: set[str] = set()

    if (
        contains_term(
            normalized_text,
            normalized_path,
            SOURCE_STATE_TERMS,
        )
        or {
            "terminal_state",
            "source_state",
            "acquisition_status",
        }
        & normalized_keys
    ):
        categories.add("source_state")

    if (
        contains_term(
            normalized_text,
            normalized_path,
            EVIDENCE_RECORD_TERMS,
        )
        or {
            "evidence_ranges",
            "selected_source_lines",
            "evidence_records",
            "claims",
        }
        & normalized_keys
    ):
        categories.add("evidence_record")

    if contains_term(
        normalized_text,
        normalized_path,
        SECOND_REVIEW_TERMS,
    ):
        categories.add("second_review")

    if contains_term(
        normalized_text,
        normalized_path,
        MATRIX_TERMS,
    ):
        categories.add("scientific_matrix")

    if (
        contains_term(
            normalized_text,
            normalized_path,
            KILL_TERMS,
        )
        or {
            "kill_condition",
            "kill_conditions",
            "falsification_decision",
        }
        & normalized_keys
    ):
        categories.add("kill_condition")

    if (
        contains_term(
            normalized_text,
            normalized_path,
            UNSUPPORTED_TERMS,
        )
        or {
            "unsupported_fields",
            "unknown_fields",
            "unresolved_fields",
        }
        & normalized_keys
    ):
        categories.add("unsupported_field")

    if (
        "identity_resolution" in normalized_path
        or "identity_verification" in normalized_path
        or "identity_verifications" in normalized_path
    ):
        categories.add("identity_provenance")

    if "adjudication" in normalized_path:
        categories.add("adjudication")

    if "ranking" in normalized_path:
        categories.add("ranking")

    if "scientific_extraction" in normalized_path:
        categories.add("scientific_extraction")

    if "graph_ir" in normalized_path:
        categories.add("graph_evidence")

    return tuple(sorted(categories))


def build_inventory() -> list[InventoryRecord]:
    records: list[InventoryRecord] = []

    for path in eligible_files():
        text = read_text(path)
        keys = structured_keys(path, text)

        records.append(
            InventoryRecord(
                path=repository_relative(path),
                bytes=path.stat().st_size,
                sha256=sha256_file(path),
                suffix=path.suffix.lower(),
                categories=classify(path, text, keys),
                structured_keys=keys,
            )
        )

    return records


def category_records(
    inventory: list[InventoryRecord],
    category: str,
) -> list[dict[str, Any]]:
    return [
        {
            "path": record.path,
            "bytes": record.bytes,
            "sha256": record.sha256,
            "structured_keys": list(
                record.structured_keys
            ),
        }
        for record in inventory
        if category in record.categories
    ]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def git_value(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return ""

    return result.stdout.strip()


def build_register(
    register_type: str,
    records: list[dict[str, Any]],
    required_minimum: int,
) -> dict[str, Any]:
    return {
        "register_schema": (
            f"qudipi.stage1.{register_type}"
        ),
        "register_version": 1,
        "required_minimum": required_minimum,
        "discovered_record_count": len(records),
        "status": (
            "SATISFIED"
            if len(records) >= required_minimum
            else "INCOMPLETE"
        ),
        "records": records,
    }


def artifact_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}

    for path in sorted(STAGE1.glob("*.json")):
        if path.name == HASH_PATH.name:
            continue

        hashes[path.name] = sha256_file(path)

    return hashes


def main() -> int:
    STAGE1.mkdir(parents=True, exist_ok=True)

    inventory = build_inventory()

    write_json(
        INVENTORY_PATH,
        {
            "inventory_schema":
                "qudipi.stage1.evidence-inventory",
            "inventory_version": 1,
            "repository_revision":
                git_value("rev-parse", "HEAD"),
            "source_root":
                repository_relative(PRIOR_ART),
            "record_count": len(inventory),
            "records": [
                asdict(record)
                for record in inventory
            ],
        },
    )

    contracts = {
        "source_state": (
            SOURCE_STATE_PATH,
            16,
        ),
        "evidence_record": (
            EVIDENCE_RECORD_PATH,
            16,
        ),
        "second_review": (
            SECOND_REVIEW_PATH,
            5,
        ),
        "scientific_matrix": (
            MATRIX_PATH,
            6,
        ),
        "kill_condition": (
            KILL_PATH,
            6,
        ),
        "unsupported_field": (
            UNSUPPORTED_PATH,
            1,
        ),
    }

    gap_entries: list[dict[str, Any]] = []

    for category, (
        destination,
        required_minimum,
    ) in contracts.items():
        records = category_records(
            inventory,
            category,
        )

        register = build_register(
            category,
            records,
            required_minimum,
        )

        write_json(destination, register)

        gap_entries.append(
            {
                "contract": category,
                "required_minimum":
                    required_minimum,
                "discovered_record_count":
                    len(records),
                "status": register["status"],
                "deficit": max(
                    required_minimum - len(records),
                    0,
                ),
                "register":
                    repository_relative(destination),
            }
        )

    blockers = [
        entry["contract"]
        for entry in gap_entries
        if entry["status"] != "SATISFIED"
    ]

    write_json(
        GAP_PATH,
        {
            "report_schema":
                "qudipi.stage1.gap-report",
            "report_version": 1,
            "stage_id": 1,
            "stage_key": "prior_art",
            "status": (
                "READY_FOR_ADJUDICATION"
                if not blockers
                else "OPEN"
            ),
            "closure_marker_emitted": False,
            "remaining_blockers": blockers,
            "contracts": gap_entries,
            "prohibited_actions": [
                "repeat corpus discovery",
                "repeat document ingestion",
                "repeat OCR",
                "repeat global ranking",
                "claim Stage 1 closure before adjudication",
            ],
        },
    )

    write_json(
        RUN_PATH,
        {
            "run_schema":
                "qudipi.stage1.ledger-run",
            "run_version": 1,
            "status": "PASS",
            "repository_revision":
                git_value("rev-parse", "HEAD"),
            "repository_tree":
                git_value("rev-parse", "HEAD^{tree}"),
            "inventory_record_count":
                len(inventory),
            "output_files": [
                repository_relative(path)
                for path in (
                    INVENTORY_PATH,
                    SOURCE_STATE_PATH,
                    EVIDENCE_RECORD_PATH,
                    SECOND_REVIEW_PATH,
                    MATRIX_PATH,
                    KILL_PATH,
                    UNSUPPORTED_PATH,
                    GAP_PATH,
                )
            ],
        },
    )

    write_json(HASH_PATH, artifact_hashes())

    print("QUDIPI_STAGE1_LEDGER_BUILD=PASS")
    print(f"inventory_record_count={len(inventory)}")

    for entry in gap_entries:
        print(
            f"{entry['contract']}_count="
            f"{entry['discovered_record_count']}"
        )
        print(
            f"{entry['contract']}_deficit="
            f"{entry['deficit']}"
        )

    print(
        "remaining_blockers="
        + (
            ",".join(blockers)
            if blockers
            else "none"
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
