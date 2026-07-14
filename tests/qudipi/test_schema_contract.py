from __future__ import annotations

import json
from pathlib import Path

import pytest

from qudipi.contracts import ManifestValidationError
from qudipi.truecolor_phase1 import (
    load_truecolor_phase1_manifest,
)

MANIFEST_PATH = Path(
    "artifacts/stage_00/compiled_config_manifest.json"
)

HASH_PATH = Path(
    "artifacts/stage_00/config_sha256.txt"
)


def load_raw_manifest() -> dict:
    return json.loads(
        MANIFEST_PATH.read_text(encoding="utf-8")
    )


def write_manifest(
    tmp_path: Path,
    raw: dict,
) -> tuple[Path, Path]:
    manifest_path = tmp_path / "manifest.json"
    hash_path = tmp_path / "config_sha256.txt"

    manifest_path.write_text(
        json.dumps(raw),
        encoding="utf-8",
    )

    hash_path.write_text(
        raw["config_sha256"] + "\n",
        encoding="utf-8",
    )

    return manifest_path, hash_path


def test_schema_registry_loads() -> None:
    manifest = load_truecolor_phase1_manifest(
        MANIFEST_PATH,
        HASH_PATH,
    )

    assert manifest.schemas
    assert manifest.schema_by_id(
        "spectral_dataset_v1"
    ).serialization == "arrow_ipc"


def test_all_operator_schema_references_resolve() -> None:
    manifest = load_truecolor_phase1_manifest(
        MANIFEST_PATH,
        HASH_PATH,
    )

    schema_ids = {
        schema.schema_id
        for schema in manifest.schemas
    }

    for operator in manifest.operators:
        assert operator.input_schema in schema_ids
        assert operator.output_schema in schema_ids


def test_unknown_input_schema_is_rejected(
    tmp_path: Path,
) -> None:
    raw = load_raw_manifest()

    first_operator = next(
        iter(raw["config"]["operators"].values())
    )
    first_operator["input_schema"] = "missing_schema_v1"

    manifest_path, hash_path = write_manifest(
        tmp_path,
        raw,
    )

    with pytest.raises(
        ManifestValidationError,
        match="unknown input schema",
    ):
        load_truecolor_phase1_manifest(
            manifest_path,
            hash_path,
        )


def test_unknown_output_schema_is_rejected(
    tmp_path: Path,
) -> None:
    raw = load_raw_manifest()

    first_operator = next(
        iter(raw["config"]["operators"].values())
    )
    first_operator["output_schema"] = "missing_schema_v1"

    manifest_path, hash_path = write_manifest(
        tmp_path,
        raw,
    )

    with pytest.raises(
        ManifestValidationError,
        match="unknown output schema",
    ):
        load_truecolor_phase1_manifest(
            manifest_path,
            hash_path,
        )


def test_empty_schema_registry_is_rejected(
    tmp_path: Path,
) -> None:
    raw = load_raw_manifest()
    raw["config"]["schemas"] = {}

    manifest_path, hash_path = write_manifest(
        tmp_path,
        raw,
    )

    with pytest.raises(
        ManifestValidationError,
        match="schema registry must not be empty",
    ):
        load_truecolor_phase1_manifest(
            manifest_path,
            hash_path,
        )
