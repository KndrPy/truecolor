from __future__ import annotations

import argparse
import json
import os
import resource
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

MODULE_ID = "S1-M01"
MODULE_SCHEMA = "qudipi.stage1.m01-corpus-reconciliation"
MODULE_SCHEMA_VERSION = 1


class M01ClosureError(EnterpriseCorpusError):
    """Raised when S1-M01 cannot prove its own bounded closure."""


@dataclass(frozen=True)
class M01ResourceBudget:
    maximum_wall_seconds: float = 900.0
    maximum_peak_rss_bytes: int = 4 * 1024 * 1024 * 1024
    maximum_output_bytes: int = 2 * 1024 * 1024 * 1024

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "M01ResourceBudget":
        if not value:
            return cls()
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown M01 resource budget fields: {', '.join(unknown)}")
        budget = cls(**value)
        if budget.maximum_wall_seconds <= 0:
            raise ValueError("maximum_wall_seconds must be positive")
        if budget.maximum_peak_rss_bytes <= 0 or budget.maximum_output_bytes <= 0:
            raise ValueError("byte budgets must be positive")
        return budget


@dataclass(frozen=True)
class M01ExecutionMetrics:
    wall_seconds: float
    peak_rss_bytes: int
    output_bytes: int
    source_file_count: int
    artifact_count: int


def _directory_size(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            total += path.stat().st_size
    return total


def _source_file_count(root: Path, policy: EnterpriseCorpusPolicy) -> int:
    count = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        included = any(path.match(pattern) for pattern in policy.include_globs)
        excluded = any(path.match(pattern) for pattern in policy.exclude_globs)
        if included and not excluded:
            count += 1
    return count


def _atomic_write_jsonl(path: Path, records: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _validate_bounded_closure(output_root: Path, result: Mapping[str, Any]) -> Mapping[str, str]:
    closure_path = output_root / "MUTABLE_CORPUS_RECONCILIATION_CLOSED.json"
    if not closure_path.is_file():
        raise M01ClosureError("mutable-corpus closure evidence is absent")
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    if closure.get("capability_state") != "CLOSED":
        raise M01ClosureError("mutable-corpus capability is not CLOSED")
    if closure.get("run_id") != result.get("run_id"):
        raise M01ClosureError("closure run_id does not match execution result")
    if closure.get("snapshot_id") != result.get("snapshot_id"):
        raise M01ClosureError("closure snapshot_id does not match execution result")
    gates = closure.get("semantic_gates")
    if not isinstance(gates, dict) or not gates:
        raise M01ClosureError("closure semantic gates are absent")
    failed = sorted(name for name, state in gates.items() if state != "PASS")
    if failed:
        raise M01ClosureError(f"mutable-corpus gates failed: {', '.join(failed)}")
    required = {
        "corpus_snapshot.json",
        "physical_file_registry.json",
        "document_version_registry.json",
        "scientific_work_registry.json",
        "physical_file_lifecycle_registry.json",
        "exact_duplicate_report.json",
        "version_family_report.json",
        "ambiguous_identity_queue.json",
        "missing_reference_candidates.json",
        "stage1_review_queue_projection.json",
        "artifact_hashes.json",
    }
    missing = sorted(name for name in required if not (output_root / name).is_file())
    if missing:
        raise M01ClosureError(f"required M01 artifacts absent: {', '.join(missing)}")
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
    if metrics.output_bytes > budget.maximum_output_bytes:
        failures.append(
            f"output_bytes={metrics.output_bytes}>{budget.maximum_output_bytes}"
        )
    if failures:
        raise M01ClosureError("M01 resource budget exceeded: " + "; ".join(failures))


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
) -> Mapping[str, Any]:
    """Execute and independently close S1-M01 against one corpus snapshot.

    This function closes only S1-M01. It never writes or claims Stage 1 closure.
    """
    policy = policy or EnterpriseCorpusPolicy()
    budget = resource_budget or M01ResourceBudget()
    corpus_root = corpus_root.resolve()
    output_root = output_root.resolve()
    module_root = output_root / "stage1" / "m01"
    module_root.mkdir(parents=True, exist_ok=True)
    module_closure = module_root / "S1_M01_CLOSED.json"
    if module_closure.exists():
        module_closure.unlink()

    source_count = _source_file_count(corpus_root, policy)
    started = time.perf_counter()
    before_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
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
    after_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB; macOS reports bytes. TrueColor production runtime is Linux/WSL.
    peak_rss_bytes = int(max(before_rss, after_rss) * 1024)
    semantic_gates = _validate_bounded_closure(output_root, result)
    artifact_paths = [path for path in output_root.glob("*.json") if path.is_file()]
    metrics = M01ExecutionMetrics(
        wall_seconds=wall_seconds,
        peak_rss_bytes=peak_rss_bytes,
        output_bytes=_directory_size(output_root),
        source_file_count=source_count,
        artifact_count=len(artifact_paths),
    )
    _enforce_budget(metrics, budget)

    trace_record = {
        "schema": "qudipi.stage1.construction-trace-event",
        "schema_version": 1,
        "module_id": MODULE_ID,
        "operation": "RECONCILE_MUTABLE_CORPUS",
        "run_id": result["run_id"],
        "snapshot_id": result["snapshot_id"],
        "input": {
            "corpus_root": corpus_root.as_posix(),
            "source_file_count": source_count,
            "policy": asdict(policy),
        },
        "output_artifacts": {
            path.name: sha256_file(path) for path in sorted(artifact_paths)
        },
        "metrics": asdict(metrics),
    }
    _atomic_write_jsonl(module_root / "construction_trace.jsonl", [trace_record])

    report = {
        "schema": MODULE_SCHEMA,
        "schema_version": MODULE_SCHEMA_VERSION,
        "module_id": MODULE_ID,
        "module_state": "CLOSED",
        "run_id": result["run_id"],
        "snapshot_id": result["snapshot_id"],
        "semantic_gates": semantic_gates,
        "resource_budget": asdict(budget),
        "metrics": asdict(metrics),
        "stage1_state": "OPEN",
        "stage1_closure_authority": "S1-M17_ONLY",
    }
    atomic_write_json(module_root / "m01_execution_report.json", report)
    atomic_write_json(module_closure, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute canonical Stage 1 module S1-M01.")
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--policy")
    parser.add_argument("--expected-sources")
    parser.add_argument("--prior-review-csv")
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
        load_optional(Path(args.dependency_manifest))
        if args.dependency_manifest
        else None
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
    )
    print("QUDIPI_STAGE1_S1_M01=PASS")
    print(f"run_id={report['run_id']}")
    print(f"snapshot_id={report['snapshot_id']}")
    print(f"module_state={report['module_state']}")
    print(f"stage1_state={report['stage1_state']}")


if __name__ == "__main__":
    main()
