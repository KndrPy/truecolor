from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from analysis.prior_art.mutable_corpus import ExtractionBackend, sha256_file
from analysis.prior_art.mutable_corpus_consumer import run_consumer_reconciliation
from analysis.prior_art.mutable_corpus_enterprise import (
    EnterpriseCorpusError,
    EnterpriseCorpusPolicy,
    atomic_write_json,
)
from analysis.prior_art.mutable_corpus_runtime import (
    expected_sources_from_review_csv,
    load_optional,
    merge_expected_sources,
)
from analysis.stage1.m01_validator import (
    M01ValidationError,
    load_json,
    validate_m01_artifacts,
    validate_prior_snapshot,
)

MODULE_ID = "S1-M01"
MODULE_SCHEMA = "qudipi.stage1.m01-corpus-reconciliation"
MODULE_SCHEMA_VERSION = 2


class M01ClosureError(EnterpriseCorpusError):
    """Raised when S1-M01 cannot prove its own bounded closure."""


@dataclass(frozen=True)
class M01ResourceBudget:
    maximum_wall_seconds: float = 900.0
    maximum_peak_rss_bytes: int = 4 * 1024 * 1024 * 1024
    maximum_run_output_bytes: int = 2 * 1024 * 1024 * 1024

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "M01ResourceBudget":
        if not value:
            return cls()
        normalized = dict(value)
        if "maximum_output_bytes" in normalized:
            if "maximum_run_output_bytes" in normalized:
                raise ValueError("specify only one output-byte budget field")
            normalized["maximum_run_output_bytes"] = normalized.pop("maximum_output_bytes")
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        unknown = sorted(set(normalized) - allowed)
        if unknown:
            raise ValueError(f"unknown M01 resource budget fields: {', '.join(unknown)}")
        budget = cls(**normalized)
        if budget.maximum_wall_seconds <= 0:
            raise ValueError("maximum_wall_seconds must be positive")
        if budget.maximum_peak_rss_bytes <= 0 or budget.maximum_run_output_bytes <= 0:
            raise ValueError("byte budgets must be positive")
        return budget


@dataclass(frozen=True)
class M01ExecutionMetrics:
    wall_seconds: float
    peak_rss_bytes: int
    run_output_bytes: int
    accepted_source_file_count: int
    scientific_work_count: int
    document_version_count: int
    artifact_count: int


def _atomic_append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if platform.system() == "Darwin" else value * 1024)


def _runtime_dependency_report(backend: ExtractionBackend | None) -> Mapping[str, Any]:
    if backend is not None:
        return {
            "mode": "INJECTED_BACKEND",
            "pdftotext": "NOT_REQUIRED",
            "pdfinfo": "NOT_REQUIRED",
        }
    dependencies = {
        "pdftotext": shutil.which("pdftotext"),
        "pdfinfo": shutil.which("pdfinfo"),
    }
    missing = sorted(name for name, path in dependencies.items() if not path)
    if missing:
        raise M01ClosureError("required PDF runtime dependencies absent: " + ", ".join(missing))
    return {"mode": "POPPLER", **dependencies}


def _install_prior_snapshot(prior_snapshot_path: Path, output_root: Path) -> Mapping[str, Any]:
    prior = load_json(prior_snapshot_path)
    validate_prior_snapshot(prior)
    target = output_root / "corpus_snapshot.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".corpus_snapshot.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(prior, handle, sort_keys=True, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "snapshot_id": prior["snapshot_id"],
        "sha256": sha256_file(target),
        "source_path": prior_snapshot_path.resolve().as_posix(),
    }


def _root_artifacts(output_root: Path) -> list[Path]:
    return sorted(
        path
        for path in output_root.iterdir()
        if path.is_file() and path.suffix in {".json", ".jsonl"}
    )


def _current_run_output_bytes(paths: list[Path], module_paths: list[Path]) -> int:
    unique = {path.resolve() for path in [*paths, *module_paths] if path.is_file()}
    return sum(path.stat().st_size for path in unique)


def _validate_underlying_closure(
    output_root: Path, result: Mapping[str, Any]
) -> Mapping[str, str]:
    closure_path = output_root / "MUTABLE_CORPUS_RECONCILIATION_CLOSED.json"
    if not closure_path.is_file():
        raise M01ClosureError("mutable-corpus closure evidence is absent")
    closure = load_json(closure_path)
    if closure.get("capability_state") != "CLOSED":
        raise M01ClosureError("mutable-corpus capability is not CLOSED")
    if closure.get("run_id") != result.get("run_id"):
        raise M01ClosureError("closure run_id does not match execution result")
    if closure.get("snapshot_id") != result.get("snapshot_id"):
        raise M01ClosureError("closure snapshot_id does not match execution result")
    gates = closure.get("semantic_gates")
    if not isinstance(gates, Mapping) or not gates:
        raise M01ClosureError("closure semantic gates are absent")
    failed = sorted(name for name, state in gates.items() if state != "PASS")
    if failed:
        raise M01ClosureError(f"mutable-corpus gates failed: {', '.join(failed)}")
    return {str(name): str(state) for name, state in gates.items()}


def _enforce_budget(metrics: M01ExecutionMetrics, budget: M01ResourceBudget) -> None:
    failures: list[str] = []
    if metrics.wall_seconds > budget.maximum_wall_seconds:
        failures.append(
            f"wall_seconds={metrics.wall_seconds:.6f}>{budget.maximum_wall_seconds:.6f}"
        )
    if metrics.peak_rss_bytes > budget.maximum_peak_rss_bytes:
        failures.append(
            f"peak_rss_bytes={metrics.peak_rss_bytes}>{budget.maximum_peak_rss_bytes}"
        )
    if metrics.run_output_bytes > budget.maximum_run_output_bytes:
        failures.append(
            f"run_output_bytes={metrics.run_output_bytes}>{budget.maximum_run_output_bytes}"
        )
    if failures:
        raise M01ClosureError("M01 resource budget exceeded: " + "; ".join(failures))


def _write_module_hash_manifest(module_root: Path, artifacts: list[Path]) -> Mapping[str, Any]:
    manifest_path = module_root / "m01_artifact_hashes.json"
    records = [
        {
            "path": path.resolve().relative_to(module_root.parent.parent.resolve()).as_posix()
            if path.resolve().is_relative_to(module_root.parent.parent.resolve())
            else path.resolve().as_posix(),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted({item.resolve() for item in artifacts if item.is_file()})
        if path != manifest_path.resolve()
    ]
    manifest = {
        "schema": "qudipi.stage1.m01-artifact-hashes",
        "schema_version": 1,
        "records": records,
    }
    atomic_write_json(manifest_path, manifest)
    return {**manifest, "manifest_sha256": sha256_file(manifest_path)}


def run_m01(
    corpus_root: Path,
    output_root: Path,
    *,
    policy: EnterpriseCorpusPolicy | None = None,
    expected_sources: Mapping[str, Any] | None = None,
    dependency_manifest: Mapping[str, Any] | None = None,
    observed_at: str | None = None,
    backend: ExtractionBackend | None = None,
    resource_budget: M01ResourceBudget | None = None,
    prior_snapshot_path: Path | None = None,
) -> Mapping[str, Any]:
    """Execute and independently close S1-M01 against one corpus snapshot."""
    policy = policy or EnterpriseCorpusPolicy()
    budget = resource_budget or M01ResourceBudget()
    corpus_root = corpus_root.resolve()
    output_root = output_root.resolve()
    module_root = output_root / "stage1" / "m01"
    module_root.mkdir(parents=True, exist_ok=True)
    module_closure = module_root / "S1_M01_CLOSED.json"
    module_report = module_root / "m01_execution_report.json"
    module_hashes = module_root / "m01_artifact_hashes.json"
    for stale in (module_closure, module_report, module_hashes):
        if stale.exists():
            stale.unlink()

    dependency_report = _runtime_dependency_report(backend)
    prior_lineage = (
        _install_prior_snapshot(prior_snapshot_path.resolve(), output_root)
        if prior_snapshot_path is not None
        else None
    )

    started = time.perf_counter()
    try:
        result = run_consumer_reconciliation(
            corpus_root,
            output_root,
            policy,
            expected_sources,
            dependency_manifest,
            observed_at,
            backend=backend,
        )
        wall_seconds = time.perf_counter() - started
        underlying_gates = _validate_underlying_closure(output_root, result)
        exhaustive_gates = validate_m01_artifacts(output_root)

        preflight_records = load_json(output_root / "corpus_preflight_report.json").get(
            "records", []
        )
        accepted_count = sum(
            isinstance(item, Mapping) and item.get("state") == "ACCEPTED"
            for item in preflight_records
        )
        works = load_json(output_root / "scientific_work_registry.json").get("records", [])
        versions = load_json(output_root / "document_version_registry.json").get("records", [])
        root_artifacts = _root_artifacts(output_root)
        metrics = M01ExecutionMetrics(
            wall_seconds=wall_seconds,
            peak_rss_bytes=_rss_bytes(),
            run_output_bytes=_current_run_output_bytes(root_artifacts, []),
            accepted_source_file_count=accepted_count,
            scientific_work_count=len(works) if isinstance(works, list) else 0,
            document_version_count=len(versions) if isinstance(versions, list) else 0,
            artifact_count=len(root_artifacts),
        )
        _enforce_budget(metrics, budget)

        trace_record = {
            "schema": "qudipi.stage1.construction-trace-event",
            "schema_version": 2,
            "module_id": MODULE_ID,
            "operation": "RECONCILE_MUTABLE_CORPUS",
            "run_id": result["run_id"],
            "snapshot_id": result["snapshot_id"],
            "input": {
                "corpus_root": corpus_root.as_posix(),
                "accepted_source_file_count": accepted_count,
                "policy": asdict(policy),
                "prior_snapshot": prior_lineage,
            },
            "runtime_dependencies": dependency_report,
            "metrics": asdict(metrics),
            "state": "VALIDATED",
        }
        trace_path = module_root / "construction_trace.jsonl"
        _atomic_append_jsonl(trace_path, trace_record)

        report = {
            "schema": MODULE_SCHEMA,
            "schema_version": MODULE_SCHEMA_VERSION,
            "module_id": MODULE_ID,
            "module_state": "CLOSED",
            "run_id": result["run_id"],
            "snapshot_id": result["snapshot_id"],
            "prior_snapshot": prior_lineage,
            "runtime_dependencies": dependency_report,
            "semantic_gates": {**underlying_gates, **exhaustive_gates},
            "resource_budget": asdict(budget),
            "metrics": asdict(metrics),
            "stage1_state": "OPEN",
            "stage1_closure_authority": "S1-M17_ONLY",
        }
        atomic_write_json(module_report, report)
        manifest = _write_module_hash_manifest(
            module_root, [*root_artifacts, trace_path, module_report]
        )
        closure = {**report, "artifact_manifest_sha256": manifest["manifest_sha256"]}
        atomic_write_json(module_closure, closure)
        return closure
    except (M01ValidationError, EnterpriseCorpusError, OSError, ValueError):
        for stale in (module_closure, module_report, module_hashes):
            if stale.exists():
                stale.unlink()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute canonical Stage 1 module S1-M01.")
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--policy")
    parser.add_argument("--expected-sources")
    parser.add_argument("--prior-review-csv")
    parser.add_argument("--prior-snapshot")
    parser.add_argument("--dependency-manifest")
    parser.add_argument("--resource-budget")
    parser.add_argument("--observed-at")
    args = parser.parse_args()

    policy = EnterpriseCorpusPolicy.from_mapping(
        load_optional(Path(args.policy)) if args.policy else None
    )
    explicit = load_optional(Path(args.expected_sources)) if args.expected_sources else None
    review = expected_sources_from_review_csv(
        Path(args.prior_review_csv) if args.prior_review_csv else None
    )
    expected = merge_expected_sources(explicit, review)
    dependencies = (
        load_optional(Path(args.dependency_manifest)) if args.dependency_manifest else None
    )
    budget = M01ResourceBudget.from_mapping(
        load_optional(Path(args.resource_budget)) if args.resource_budget else None
    )
    report = run_m01(
        Path(args.corpus_root),
        Path(args.output_root),
        policy=policy,
        expected_sources=expected,
        dependency_manifest=dependencies,
        observed_at=args.observed_at,
        resource_budget=budget,
        prior_snapshot_path=Path(args.prior_snapshot) if args.prior_snapshot else None,
    )
    print("QUDIPI_STAGE1_S1_M01=PASS")
    print(f"run_id={report['run_id']}")
    print(f"snapshot_id={report['snapshot_id']}")
    print(f"module_state={report['module_state']}")
    print(f"stage1_state={report['stage1_state']}")


if __name__ == "__main__":
    main()
