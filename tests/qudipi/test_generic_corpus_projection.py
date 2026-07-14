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


def test_generic_manifest_projection_loads() -> None:
    manifest = load_truecolor_phase1_manifest(
        MANIFEST_PATH,
        HASH_PATH,
    )

    assert manifest.roles
    assert manifest.corpus_characterization.required_details
    assert manifest.assets


def test_asset_projection_preserves_known_and_unknown_details() -> None:
    manifest = load_truecolor_phase1_manifest(
        MANIFEST_PATH,
        HASH_PATH,
    )

    required = set(
        manifest.corpus_characterization.required_details
    )

    for asset in manifest.assets:
        known = set(asset.known_details)
        unknown = set(asset.unknown_details)

        assert known.isdisjoint(unknown)
        assert required <= known | unknown


def test_unknown_declared_allowed_role_is_rejected(
    tmp_path: Path,
) -> None:
    raw = load_raw_manifest()

    raw["config"]["assets"][0][
        "declared_allowed_roles"
    ].append("missing_role")

    manifest_path, hash_path = write_manifest(
        tmp_path,
        raw,
    )

    with pytest.raises(
        ManifestValidationError,
        match="unknown declared allowed roles",
    ):
        load_truecolor_phase1_manifest(
            manifest_path,
            hash_path,
        )


def test_unknown_stage_requirement_role_is_rejected(
    tmp_path: Path,
) -> None:
    raw = load_raw_manifest()

    stage = next(
        stage
        for stage in raw["config"]["stages"]
        if stage.get("asset_requirements")
    )

    stage["asset_requirements"][0][
        "accepted_roles"
    ].append("missing_role")

    manifest_path, hash_path = write_manifest(
        tmp_path,
        raw,
    )

    with pytest.raises(
        ManifestValidationError,
        match="references unknown roles",
    ):
        load_truecolor_phase1_manifest(
            manifest_path,
            hash_path,
        )


def test_missing_detail_classification_is_rejected(
    tmp_path: Path,
) -> None:
    raw = load_raw_manifest()

    required_detail = raw["config"][
        "corpus_characterization"
    ]["required_details"][0]

    asset = raw["config"]["assets"][0]
    asset["known_details"].pop(
        required_detail,
        None,
    )

    asset["unknown_details"] = [
        detail
        for detail in asset["unknown_details"]
        if detail != required_detail
    ]

    manifest_path, hash_path = write_manifest(
        tmp_path,
        raw,
    )

    with pytest.raises(
        ManifestValidationError,
        match="does not classify required details",
    ):
        load_truecolor_phase1_manifest(
            manifest_path,
            hash_path,
        )


def test_known_unknown_overlap_is_rejected(
    tmp_path: Path,
) -> None:
    raw = load_raw_manifest()

    asset = raw["config"]["assets"][0]
    known_detail = next(
        iter(asset["known_details"])
    )

    asset["unknown_details"].append(
        known_detail
    )

    manifest_path, hash_path = write_manifest(
        tmp_path,
        raw,
    )

    with pytest.raises(
        ManifestValidationError,
        match="both known and unknown",
    ):
        load_truecolor_phase1_manifest(
            manifest_path,
            hash_path,
        )
