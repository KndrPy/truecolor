from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1
SOURCE_STATES = (
    "READY", "PARTIALLY_READABLE", "UNREADABLE", "ENCRYPTED", "TRUNCATED",
    "NON_SCIENTIFIC", "VERSION_REVIEW_REQUIRED", "SOURCE_RECOVERY_REQUIRED",
)
SOURCE_FORMS = (
    "PUBLISHER_VERSION", "ACCEPTED_MANUSCRIPT", "PREPRINT", "SUPPLEMENT",
    "CORRECTION", "UNKNOWN",
)


class Stage1EvidenceError(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    # JSON permits U+0085/U+2028/U+2029 inside strings, but line-oriented
    # readers commonly treat them as record separators. Escape them so one
    # physical LF always equals one JSONL record boundary.
    return (
        payload
        .replace("\u0085", "\\u0085")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(prefix: str, payload: Any) -> str:
    return f"{prefix}-{sha256_bytes(canonical_json(payload).encode('utf-8'))[:24]}"


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def atomic_write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(canonical_json(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def load_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise Stage1EvidenceError(f"expected object in {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise Stage1EvidenceError(
                    f"invalid JSONL record at {path}:{line_no}: {error.msg}"
                ) from error
            if not isinstance(value, Mapping):
                raise Stage1EvidenceError(f"expected object at {path}:{line_no}")
            records.append(dict(value))
    return records


def normalized_text(text: str) -> str:
    return " ".join(text.split())


def ensure_fitz() -> Any:
    try:
        import fitz  # type: ignore
    except ImportError as error:
        raise Stage1EvidenceError("PyMuPDF is required for Stage 1 document processing") from error
    return fitz


def write_parquet(path: Path, records: list[Mapping[str, Any]]) -> None:
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as error:
        raise Stage1EvidenceError("pyarrow is required for real Parquet outputs") from error
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(
        pa.Table.from_pylist([dict(item) for item in records]),
        temp,
        compression="zstd",
    )
    os.replace(temp, path)


@dataclass(frozen=True)
class ModuleResult:
    module_id: str
    module_state: str
    stage1_state: str
    outputs: tuple[str, ...]
    counts: Mapping[str, int]
    closure_gates: Mapping[str, str]


def write_closure(output_root: Path, result: ModuleResult) -> None:
    atomic_write_json(
        output_root / f"{result.module_id.replace('-', '_')}_CLOSED.json",
        {
            "schema": "truecolor.stage1.module-closure",
            "schema_version": SCHEMA_VERSION,
            **asdict(result),
        },
    )
