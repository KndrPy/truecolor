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


def test_compiled_manifest_loads() -> None:
    manifest = load_truecolor_phase1_manifest(
        MANIFEST_PATH,
        HASH_PATH,
    )

    assert manifest.manifest_schema == (
        "qudipi.compiled-config"
    )
    assert manifest.manifest_version == 1
    assert manifest.product_version == "2.0.0"


def test_manifest_has_complete_stage_range() -> None:
    manifest = load_truecolor_phase1_manifest(
        MANIFEST_PATH,
        HASH_PATH,
    )

    assert manifest.stage_count == 34
    assert tuple(
        stage.stage_id
        for stage in manifest.stages
    ) == tuple(range(34))


def test_new_external_benchmark_stages_are_canonical() -> None:
    manifest = load_truecolor_phase1_manifest(
        MANIFEST_PATH,
        HASH_PATH,
    )

    assert manifest.stage_by_id(19).key == (
        "arad_1k_reconstruction"
    )
    assert manifest.stage_by_id(20).key == (
        "ntire_16_demosaicing"
    )
    assert manifest.stage_by_id(21).key == (
        "uci_skin_segmentation"
    )
    assert manifest.stage_by_id(22).key == (
        "mskcc_colorimeter"
    )
    assert manifest.stage_by_id(33).key == (
        "consumer_productization"
    )


def test_python_counts_match_compiled_json() -> None:
    raw = load_raw_manifest()

    manifest = load_truecolor_phase1_manifest(
        MANIFEST_PATH,
        HASH_PATH,
    )

    assert len(manifest.stages) == len(
        raw["config"]["stages"]
    )
    assert len(manifest.assets) == len(
        raw["config"]["assets"]
    )
    assert len(manifest.operators) == len(
        raw["config"]["operators"]
    )


def test_unknown_dependency_is_rejected(
    tmp_path: Path,
) -> None:
    raw = load_raw_manifest()
    raw["config"]["stages"][0]["dependencies"] = [99]

    manifest_path, hash_path = write_manifest(
        tmp_path,
        raw,
    )

    with pytest.raises(
        ManifestValidationError,
        match="unknown dependencies",
    ):
        load_truecolor_phase1_manifest(
            manifest_path,
            hash_path,
        )


def test_unknown_asset_is_rejected(
    tmp_path: Path,
) -> None:
    raw = load_raw_manifest()
    raw["config"]["stages"][0][
        "required_assets"
    ].append("unknown_asset")

    manifest_path, hash_path = write_manifest(
        tmp_path,
        raw,
    )

    with pytest.raises(
        ManifestValidationError,
        match="unknown assets",
    ):
        load_truecolor_phase1_manifest(
            manifest_path,
            hash_path,
        )


def test_unknown_operator_is_rejected(
    tmp_path: Path,
) -> None:
    raw = load_raw_manifest()
    raw["config"]["stages"][0][
        "required_operators"
    ] = ["unknown_operator"]

    manifest_path, hash_path = write_manifest(
        tmp_path,
        raw,
    )

    with pytest.raises(
        ManifestValidationError,
        match="unknown operators",
    ):
        load_truecolor_phase1_manifest(
            manifest_path,
            hash_path,
        )


def test_hash_mismatch_is_rejected(
    tmp_path: Path,
) -> None:
    raw = load_raw_manifest()

    manifest_path, hash_path = write_manifest(
        tmp_path,
        raw,
    )

    hash_path.write_text(
        "0" * 64 + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ManifestValidationError,
        match="does not match",
    ):
        load_truecolor_phase1_manifest(
            manifest_path,
            hash_path,
        )


def test_unsupported_schema_is_rejected(
    tmp_path: Path,
) -> None:
    raw = load_raw_manifest()
    raw["manifest_schema"] = "unknown.schema"

    manifest_path, hash_path = write_manifest(
        tmp_path,
        raw,
    )

    with pytest.raises(
        ManifestValidationError,
        match="unsupported manifest schema",
    ):
        load_truecolor_phase1_manifest(
            manifest_path,
            hash_path,
        )


def test_unsupported_version_is_rejected(
    tmp_path: Path,
) -> None:
    raw = load_raw_manifest()
    raw["manifest_version"] = 999

    manifest_path, hash_path = write_manifest(
        tmp_path,
        raw,
    )

    with pytest.raises(
        ManifestValidationError,
        match="unsupported manifest version",
    ):
        load_truecolor_phase1_manifest(
            manifest_path,
            hash_path,
        )


def test_missing_manifest_is_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ManifestValidationError,
        match="does not exist",
    ):
        load_truecolor_phase1_manifest(
            tmp_path / "missing.json",
            tmp_path / "missing.sha256",
        )
