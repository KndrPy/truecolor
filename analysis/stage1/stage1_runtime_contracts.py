from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class Stage1ContractError(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def stable_id(prefix: str, payload: Any) -> str:
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:24]}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def atomic_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                payload = canonical_json(dict(record)).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029").replace("\u0085", "\\u0085")
                handle.write(payload + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def load_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise Stage1ContractError(f"expected JSON object: {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, physical_line in enumerate(handle, 1):
            if not physical_line.strip():
                continue
            try:
                value = json.loads(physical_line)
            except json.JSONDecodeError as error:
                raise Stage1ContractError(f"invalid JSONL record at {path}:{line_number}: {error}") from error
            if not isinstance(value, Mapping):
                raise Stage1ContractError(f"expected JSON object at {path}:{line_number}")
            records.append(dict(value))
    return records


def require_files(root: Path, names: Sequence[str]) -> None:
    missing = [name for name in names if not (root / name).is_file()]
    if missing:
        raise Stage1ContractError("missing required artifacts: " + ", ".join(missing))


def require_unique(records: Sequence[Mapping[str, Any]], key: str, label: str) -> None:
    values = [str(item.get(key, "")) for item in records]
    if any(not value for value in values):
        raise Stage1ContractError(f"{label} contains an empty {key}")
    if len(values) != len(set(values)):
        raise Stage1ContractError(f"{label} contains duplicate {key} values")


def require_references(records: Sequence[Mapping[str, Any]], field: str, allowed: set[str], label: str) -> None:
    missing: list[str] = []
    for item in records:
        values = item.get(field, [])
        if isinstance(values, str):
            values = [values]
        for value in values or []:
            if str(value) not in allowed:
                missing.append(str(value))
    if missing:
        raise Stage1ContractError(f"{label} has unresolved {field}: {sorted(set(missing))[:20]}")


@dataclass(frozen=True)
class ModuleClosure:
    module_id: str
    module_state: str
    stage1_state: str
    outputs: tuple[str, ...]
    counts: Mapping[str, int]
    closure_gates: Mapping[str, str]
    input_artifact_hashes: Mapping[str, str]


def write_closure(root: Path, closure: ModuleClosure) -> None:
    atomic_json(
        root / f"{closure.module_id.replace('-', '_')}_CLOSED.json",
        {"schema": "truecolor.stage1.module-closure", "schema_version": 2, **asdict(closure)},
    )


def hash_inputs(paths: Iterable[Path]) -> dict[str, str]:
    return {path.as_posix(): sha256_file(path) for path in paths if path.is_file()}
