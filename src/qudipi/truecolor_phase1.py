from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import (
    CompiledApplication,
    CompiledAsset,
    CompiledCorpusCharacterization,
    CompiledOperator,
    CompiledRole,
    CompiledSchema,
    CompiledStage,
    CompiledStageAssetRequirement,
    CompiledStudyManifest,
    ManifestValidationError,
)
from .validation import validate_compiled_manifest

DEFAULT_MANIFEST_PATH = Path(
    "artifacts/stage_00/compiled_config_manifest.json"
)

DEFAULT_HASH_PATH = Path(
    "artifacts/stage_00/config_sha256.txt"
)


def load_truecolor_phase1_manifest(
    manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
    expected_hash_path: Path | str | None = DEFAULT_HASH_PATH,
) -> CompiledStudyManifest:
    resolved_manifest_path = Path(manifest_path)

    if not resolved_manifest_path.is_file():
        raise ManifestValidationError(
            "compiled manifest does not exist: "
            f"{resolved_manifest_path}"
        )

    try:
        raw = json.loads(
            resolved_manifest_path.read_text(
                encoding="utf-8"
            )
        )
    except json.JSONDecodeError as error:
        raise ManifestValidationError(
            "compiled manifest is not valid JSON"
        ) from error

    manifest = _project_manifest(raw)
    validate_compiled_manifest(manifest)

    if expected_hash_path is not None:
        _validate_expected_hash(
            manifest,
            Path(expected_hash_path),
        )

    return manifest


def truecolor_phase1() -> CompiledStudyManifest:
    return load_truecolor_phase1_manifest()


def _project_manifest(
    raw: dict[str, Any],
) -> CompiledStudyManifest:
    try:
        config = raw["config"]
        application = config["application"]
        corpus = config["corpus_characterization"]

        roles = tuple(
            CompiledRole(
                role_id=role_id,
                description=role["description"],
                role_class=role["role_class"],
                derivation_mode=role["derivation_mode"],
                requires_all=tuple(
                    role.get("requires_all", ())
                ),
                requires_any=tuple(
                    role.get("requires_any", ())
                ),
                forbids_any=tuple(
                    role.get("forbids_any", ())
                ),
                risk_class=role["risk_class"],
            )
            for role_id, role in sorted(
                config["roles"].items()
            )
        )

        stages = tuple(
            CompiledStage(
                stage_id=stage["id"],
                key=stage["key"],
                name=stage["name"],
                purpose=stage["purpose"],
                dependencies=tuple(stage["dependencies"]),
                required_assets=tuple(
                    stage["required_assets"]
                ),
                required_operators=tuple(
                    stage["required_operators"]
                ),
                current_disposition=stage[
                    "current_disposition"
                ],
                asset_requirements=tuple(
                    CompiledStageAssetRequirement(
                        requirement_id=requirement[
                            "requirement_id"
                        ],
                        minimum_assets=requirement[
                            "minimum_assets"
                        ],
                        required_characteristics=tuple(
                            requirement.get(
                                "required_characteristics",
                                (),
                            )
                        ),
                        accepted_roles=tuple(
                            requirement.get(
                                "accepted_roles",
                                (),
                            )
                        ),
                    )
                    for requirement in stage.get(
                        "asset_requirements",
                        (),
                    )
                ),
            )
            for stage in config["stages"]
        )

        assets = tuple(
            CompiledAsset(
                asset_id=asset["id"],
                display_name=asset["display_name"],
                asset_class=asset["asset_class"],
                acquisition_status=asset[
                    "acquisition_status"
                ],
                license_status=asset["license_status"],
                governance_class=asset[
                    "governance_class"
                ],
                identity_unit=asset["identity_unit"],
                measurement_unit=asset[
                    "measurement_unit"
                ],
                characteristics=tuple(
                    asset.get("characteristics", ())
                ),
                known_details=dict(
                    asset.get("known_details", {})
                ),
                unknown_details=tuple(
                    asset.get("unknown_details", ())
                ),
                declared_allowed_roles=tuple(
                    asset.get(
                        "declared_allowed_roles",
                        (),
                    )
                ),
                declared_prohibited_roles=tuple(
                    asset.get(
                        "declared_prohibited_roles",
                        (),
                    )
                ),
                applicable_stages=tuple(
                    asset["applicable_stages"]
                ),
            )
            for asset in config["assets"]
        )

        schemas = tuple(
            CompiledSchema(
                schema_id=schema_id,
                description=schema["description"],
                schema_class=schema["schema_class"],
                serialization=schema["serialization"],
                version=schema["version"],
            )
            for schema_id, schema in sorted(
                config["schemas"].items()
            )
        )

        operators = tuple(
            CompiledOperator(
                operator_id=operator_id,
                engine=operator["engine"],
                entrypoint=operator["entrypoint"],
                input_schema=operator["input_schema"],
                output_schema=operator["output_schema"],
                resource_profile=operator[
                    "resource_profile"
                ],
            )
            for operator_id, operator in sorted(
                config["operators"].items()
            )
        )

        return CompiledStudyManifest(
            manifest_schema=raw["manifest_schema"],
            manifest_version=raw["manifest_version"],
            product_version=raw["product_version"],
            config_sha256=raw["config_sha256"],
            phase=raw["phase"],
            stage_count=raw["stage_count"],
            stage_id_min=raw["stage_id_min"],
            stage_id_max=raw["stage_id_max"],
            single_config_authority=raw[
                "single_config_authority"
            ],
            application=CompiledApplication(
                project_id=application["id"],
                phase=application["phase"],
                study_id=application["study"],
                research_pack_id=application[
                    "research_pack"
                ],
                single_config_authority=application[
                    "single_config_authority"
                ],
            ),
            corpus_characterization=(
                CompiledCorpusCharacterization(
                    required_details=tuple(
                        corpus["required_details"]
                    ),
                    controlled_characteristics=corpus[
                        "controlled_characteristics"
                    ],
                    reject_unknown_roles=corpus[
                        "reject_unknown_roles"
                    ],
                    preserve_unknown_details=corpus[
                        "preserve_unknown_details"
                    ],
                )
            ),
            roles=roles,
            stages=stages,
            assets=assets,
            schemas=schemas,
            operators=operators,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ManifestValidationError(
            "compiled manifest does not match the required schema"
        ) from error


def _validate_expected_hash(
    manifest: CompiledStudyManifest,
    expected_hash_path: Path,
) -> None:
    if not expected_hash_path.is_file():
        raise ManifestValidationError(
            "expected configuration hash file does not exist: "
            f"{expected_hash_path}"
        )

    expected_hash = expected_hash_path.read_text(
        encoding="utf-8"
    ).strip()

    if manifest.config_sha256 != expected_hash:
        raise ManifestValidationError(
            "compiled manifest hash does not match "
            "the Rust-emitted configuration hash"
        )
