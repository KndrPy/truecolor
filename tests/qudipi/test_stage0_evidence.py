from __future__ import annotations

import hashlib
import json
from pathlib import Path

STAGE0 = Path("artifacts/stage_00")


def load_json(name: str) -> object:
    return json.loads(
        (STAGE0 / name).read_text(encoding="utf-8")
    )


def test_validation_report_passes() -> None:
    report = load_json("validation_report.json")

    assert report["status"] == "PASS"
    assert report["stage_count"] == 34
    assert report["asset_count"] >= 1
    assert report["schema_count"] >= 1
    assert report["operator_count"] >= 1


def test_characterization_report_covers_every_asset() -> None:
    assets = load_json("asset_registry.json")
    report = load_json(
        "asset_characterization_report.json"
    )

    assert report["asset_count"] == len(assets)
    assert len(report["assets"]) == len(assets)
    assert report["required_details"]


def test_every_required_detail_is_known_or_unknown() -> None:
    report = load_json(
        "asset_characterization_report.json"
    )

    required = set(report["required_details"])

    for asset in report["assets"]:
        known = set(asset["known_details"])
        unknown = set(asset["unknown_details"])

        assert known.isdisjoint(unknown)
        assert required <= known | unknown


def test_role_dispositions_are_explicit() -> None:
    report = load_json(
        "asset_characterization_report.json"
    )

    valid = {
        "allowed",
        "prohibited",
        "unresolved",
    }

    for asset in report["assets"]:
        for disposition in (
            asset["role_dispositions"].values()
        ):
            assert disposition["disposition"] in valid


def test_stage0_closure_lifecycle_is_consistent() -> None:
    report = load_json("closure_gate_report.json")
    status = report["status"]

    assert status in {"OPEN", "CLOSED"}

    if status == "OPEN":
        assert report["closure_marker_emitted"] is False
        assert report["remaining_blockers"]
        assert not (
            STAGE0 / "STAGE_00_CLOSED.json"
        ).exists()
    else:
        assert report["closure_marker_emitted"] is True
        assert report["remaining_blockers"] == []
        assert (
            STAGE0 / "STAGE_00_CLOSED.json"
        ).is_file()
        assert (
            STAGE0
            / report["reproducibility_capture"]
        ).is_file()

def test_recorded_artifact_hashes_are_correct() -> None:
    recorded = load_json("artifact_hashes.json")

    for file_name, expected_hash in recorded.items():
        path = STAGE0 / file_name
        assert path.is_file(), file_name

        actual_hash = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

        assert actual_hash == expected_hash
