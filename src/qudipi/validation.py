from __future__ import annotations

from collections import deque
from string import hexdigits

from .contracts import (
    CompiledAsset,
    CompiledRole,
    CompiledStudyManifest,
    ManifestValidationError,
)

EXPECTED_MANIFEST_SCHEMA = "qudipi.compiled-config"
SUPPORTED_MANIFEST_VERSION = 1

ROLE_DISPOSITIONS = {
    "allowed",
    "prohibited",
    "unresolved",
}

DERIVATION_MODES = {
    "rule_based",
    "declared_only",
    "hybrid",
}


def validate_compiled_manifest(
    manifest: CompiledStudyManifest,
) -> None:
    _validate_manifest_identity(manifest)
    _validate_corpus_characterization(manifest)
    _validate_role_registry(manifest)
    _validate_stage_registry(manifest)
    _validate_asset_registry(manifest)
    _validate_schema_registry(manifest)
    _validate_operator_registry(manifest)
    _validate_stage_references(manifest)
    _validate_asset_stage_symmetry(manifest)
    _validate_stage_requirements(manifest)
    _validate_stage_graph(manifest)


def _validate_manifest_identity(
    manifest: CompiledStudyManifest,
) -> None:
    if manifest.manifest_schema != EXPECTED_MANIFEST_SCHEMA:
        raise ManifestValidationError(
            "unsupported manifest schema: "
            f"{manifest.manifest_schema}"
        )

    if manifest.manifest_version != SUPPORTED_MANIFEST_VERSION:
        raise ManifestValidationError(
            "unsupported manifest version: "
            f"{manifest.manifest_version}"
        )

    if manifest.phase != 1:
        raise ManifestValidationError(
            f"expected Phase 1 manifest, found phase {manifest.phase}"
        )

    if not manifest.single_config_authority:
        raise ManifestValidationError(
            "single_config_authority must be true"
        )

    if len(manifest.config_sha256) != 64:
        raise ManifestValidationError(
            "config_sha256 must contain 64 hexadecimal characters"
        )

    if any(
        character not in hexdigits
        for character in manifest.config_sha256
    ):
        raise ManifestValidationError(
            "config_sha256 contains non-hexadecimal characters"
        )


def _validate_corpus_characterization(
    manifest: CompiledStudyManifest,
) -> None:
    policy = manifest.corpus_characterization

    if not policy.required_details:
        raise ManifestValidationError(
            "corpus characterization required_details "
            "must not be empty"
        )

    if len(policy.required_details) != len(
        set(policy.required_details)
    ):
        raise ManifestValidationError(
            "corpus characterization contains "
            "duplicate required details"
        )

    if not policy.reject_unknown_roles:
        raise ManifestValidationError(
            "corpus characterization must reject unknown roles"
        )

    if not policy.preserve_unknown_details:
        raise ManifestValidationError(
            "corpus characterization must preserve "
            "unknown details"
        )


def _validate_role_registry(
    manifest: CompiledStudyManifest,
) -> None:
    role_ids = [
        role.role_id
        for role in manifest.roles
    ]

    if not role_ids:
        raise ManifestValidationError(
            "role registry must not be empty"
        )

    if len(role_ids) != len(set(role_ids)):
        raise ManifestValidationError(
            "duplicate role IDs detected"
        )

    for role in manifest.roles:
        _validate_role(role)


def _validate_role(role: CompiledRole) -> None:
    if not role.description.strip():
        raise ManifestValidationError(
            f"role {role.role_id} has an empty description"
        )

    if not role.role_class.strip():
        raise ManifestValidationError(
            f"role {role.role_id} has an empty role_class"
        )

    if not role.risk_class.strip():
        raise ManifestValidationError(
            f"role {role.role_id} has an empty risk_class"
        )

    if role.derivation_mode not in DERIVATION_MODES:
        raise ManifestValidationError(
            f"role {role.role_id} has unsupported "
            f"derivation mode {role.derivation_mode}"
        )

    for field_name, values in (
        ("requires_all", role.requires_all),
        ("requires_any", role.requires_any),
        ("forbids_any", role.forbids_any),
    ):
        if len(values) != len(set(values)):
            raise ManifestValidationError(
                f"role {role.role_id} contains duplicate "
                f"{field_name} characteristics"
            )

        if any(not value.strip() for value in values):
            raise ManifestValidationError(
                f"role {role.role_id} contains a blank "
                f"{field_name} characteristic"
            )

    required = set(role.requires_all) | set(
        role.requires_any
    )
    forbidden = set(role.forbids_any)

    overlap = required & forbidden

    if overlap:
        raise ManifestValidationError(
            f"role {role.role_id} both requires and "
            f"forbids characteristics: {sorted(overlap)}"
        )


def _validate_stage_registry(
    manifest: CompiledStudyManifest,
) -> None:
    stage_ids = [
        stage.stage_id
        for stage in manifest.stages
    ]

    stage_keys = [
        stage.key
        for stage in manifest.stages
    ]

    if manifest.stage_count != len(manifest.stages):
        raise ManifestValidationError(
            "stage_count does not match the stage registry"
        )

    if manifest.stage_count != 34:
        raise ManifestValidationError(
            f"expected 34 stages, found {manifest.stage_count}"
        )

    if sorted(stage_ids) != list(range(34)):
        raise ManifestValidationError(
            "stage IDs must be exactly 0 through 33"
        )

    if manifest.stage_id_min != 0:
        raise ManifestValidationError(
            "stage_id_min must equal 0"
        )

    if manifest.stage_id_max != 33:
        raise ManifestValidationError(
            "stage_id_max must equal 33"
        )

    if len(stage_ids) != len(set(stage_ids)):
        raise ManifestValidationError(
            "duplicate stage IDs detected"
        )

    if len(stage_keys) != len(set(stage_keys)):
        raise ManifestValidationError(
            "duplicate stage keys detected"
        )


def _validate_asset_registry(
    manifest: CompiledStudyManifest,
) -> None:
    asset_ids = [
        asset.asset_id
        for asset in manifest.assets
    ]

    if len(asset_ids) != len(set(asset_ids)):
        raise ManifestValidationError(
            "duplicate asset IDs detected"
        )

    role_ids = {
        role.role_id
        for role in manifest.roles
    }

    required_details = set(
        manifest.corpus_characterization.required_details
    )

    for asset in manifest.assets:
        _validate_asset(
            asset,
            role_ids,
            required_details,
        )


def _validate_asset(
    asset: CompiledAsset,
    role_ids: set[str],
    required_details: set[str],
) -> None:
    if len(asset.characteristics) != len(
        set(asset.characteristics)
    ):
        raise ManifestValidationError(
            f"asset {asset.asset_id} contains "
            "duplicate characteristics"
        )

    if len(asset.unknown_details) != len(
        set(asset.unknown_details)
    ):
        raise ManifestValidationError(
            f"asset {asset.asset_id} contains "
            "duplicate unknown details"
        )

    known = set(asset.known_details)
    unknown = set(asset.unknown_details)

    overlap = known & unknown

    if overlap:
        raise ManifestValidationError(
            f"asset {asset.asset_id} classifies details "
            f"as both known and unknown: {sorted(overlap)}"
        )

    missing = required_details - known - unknown

    if missing:
        raise ManifestValidationError(
            f"asset {asset.asset_id} does not classify "
            f"required details: {sorted(missing)}"
        )

    unknown_allowed_roles = (
        set(asset.declared_allowed_roles) - role_ids
    )

    if unknown_allowed_roles:
        raise ManifestValidationError(
            f"asset {asset.asset_id} references unknown "
            "declared allowed roles: "
            f"{sorted(unknown_allowed_roles)}"
        )

    unknown_prohibited_roles = (
        set(asset.declared_prohibited_roles) - role_ids
    )

    if unknown_prohibited_roles:
        raise ManifestValidationError(
            f"asset {asset.asset_id} references unknown "
            "declared prohibited roles: "
            f"{sorted(unknown_prohibited_roles)}"
        )

    role_overlap = set(
        asset.declared_allowed_roles
    ) & set(asset.declared_prohibited_roles)

    if role_overlap:
        raise ManifestValidationError(
            f"asset {asset.asset_id} declares roles as "
            "both allowed and prohibited: "
            f"{sorted(role_overlap)}"
        )

    if len(asset.applicable_stages) != len(
        set(asset.applicable_stages)
    ):
        raise ManifestValidationError(
            f"asset {asset.asset_id} contains duplicate "
            "applicable stage IDs"
        )


def _validate_schema_registry(
    manifest: CompiledStudyManifest,
) -> None:
    schema_ids = [
        schema.schema_id
        for schema in manifest.schemas
    ]

    if not schema_ids:
        raise ManifestValidationError(
            "schema registry must not be empty"
        )

    if len(schema_ids) != len(set(schema_ids)):
        raise ManifestValidationError(
            "duplicate schema IDs detected"
        )

    for schema in manifest.schemas:
        if not schema.description.strip():
            raise ManifestValidationError(
                f"schema {schema.schema_id} "
                "has an empty description"
            )

        if schema.version <= 0:
            raise ManifestValidationError(
                f"schema {schema.schema_id} "
                "has an invalid version"
            )


def _validate_operator_registry(
    manifest: CompiledStudyManifest,
) -> None:
    operator_ids = [
        operator.operator_id
        for operator in manifest.operators
    ]

    if not operator_ids:
        raise ManifestValidationError(
            "operator registry must not be empty"
        )

    if len(operator_ids) != len(set(operator_ids)):
        raise ManifestValidationError(
            "duplicate operator IDs detected"
        )

    schema_ids = {
        schema.schema_id
        for schema in manifest.schemas
    }

    for operator in manifest.operators:
        if operator.input_schema not in schema_ids:
            raise ManifestValidationError(
                f"operator {operator.operator_id} references "
                f"unknown input schema {operator.input_schema}"
            )

        if operator.output_schema not in schema_ids:
            raise ManifestValidationError(
                f"operator {operator.operator_id} references "
                f"unknown output schema {operator.output_schema}"
            )


def _validate_stage_references(
    manifest: CompiledStudyManifest,
) -> None:
    stage_ids = {
        stage.stage_id
        for stage in manifest.stages
    }

    asset_ids = {
        asset.asset_id
        for asset in manifest.assets
    }

    operator_ids = {
        operator.operator_id
        for operator in manifest.operators
    }

    role_ids = {
        role.role_id
        for role in manifest.roles
    }

    for stage in manifest.stages:
        unknown_dependencies = (
            set(stage.dependencies) - stage_ids
        )

        if unknown_dependencies:
            raise ManifestValidationError(
                f"stage {stage.stage_id} references unknown "
                f"dependencies: {sorted(unknown_dependencies)}"
            )

        if stage.stage_id in stage.dependencies:
            raise ManifestValidationError(
                f"stage {stage.stage_id} depends on itself"
            )

        unknown_assets = (
            set(stage.required_assets) - asset_ids
        )

        if unknown_assets:
            raise ManifestValidationError(
                f"stage {stage.stage_id} references unknown "
                f"assets: {sorted(unknown_assets)}"
            )

        unknown_operators = (
            set(stage.required_operators)
            - operator_ids
        )

        if unknown_operators:
            raise ManifestValidationError(
                f"stage {stage.stage_id} references unknown "
                f"operators: {sorted(unknown_operators)}"
            )

        requirement_ids = [
            requirement.requirement_id
            for requirement in stage.asset_requirements
        ]

        if len(requirement_ids) != len(
            set(requirement_ids)
        ):
            raise ManifestValidationError(
                f"stage {stage.stage_id} contains "
                "duplicate asset requirement IDs"
            )

        for requirement in stage.asset_requirements:
            if requirement.minimum_assets <= 0:
                raise ManifestValidationError(
                    f"stage {stage.stage_id} requirement "
                    f"{requirement.requirement_id} "
                    "minimum_assets must be greater than zero"
                )

            unknown_roles = (
                set(requirement.accepted_roles)
                - role_ids
            )

            if unknown_roles:
                raise ManifestValidationError(
                    f"stage {stage.stage_id} requirement "
                    f"{requirement.requirement_id} "
                    "references unknown roles: "
                    f"{sorted(unknown_roles)}"
                )


def _validate_asset_stage_symmetry(
    manifest: CompiledStudyManifest,
) -> None:
    stages_by_id = {
        stage.stage_id: stage
        for stage in manifest.stages
    }

    assets_by_id = {
        asset.asset_id: asset
        for asset in manifest.assets
    }

    for stage in manifest.stages:
        for asset_id in stage.required_assets:
            asset = assets_by_id[asset_id]

            if stage.stage_id not in asset.applicable_stages:
                raise ManifestValidationError(
                    "asset-stage mapping is asymmetric: "
                    f"stage {stage.stage_id} requires "
                    f"asset {asset_id}"
                )

    for asset in manifest.assets:
        for stage_id in asset.applicable_stages:
            stage = stages_by_id.get(stage_id)

            if stage is None:
                raise ManifestValidationError(
                    f"asset {asset.asset_id} references "
                    f"unknown stage {stage_id}"
                )

            if asset.asset_id not in stage.required_assets:
                raise ManifestValidationError(
                    "asset-stage mapping is asymmetric: "
                    f"asset {asset.asset_id} applies "
                    f"to stage {stage_id}"
                )


def _validate_stage_requirements(
    manifest: CompiledStudyManifest,
) -> None:
    roles_by_id = {
        role.role_id: role
        for role in manifest.roles
    }

    for stage in manifest.stages:
        for requirement in stage.asset_requirements:
            matching_assets = 0

            for asset in manifest.assets:
                characteristics = set(
                    asset.characteristics
                )

                characteristics_match = set(
                    requirement.required_characteristics
                ) <= characteristics

                roles_match = (
                    not requirement.accepted_roles
                    or any(
                        _role_is_allowed(
                            asset,
                            roles_by_id[role_id],
                        )
                        for role_id in (
                            requirement.accepted_roles
                        )
                    )
                )

                if characteristics_match and roles_match:
                    matching_assets += 1

            if matching_assets < requirement.minimum_assets:
                raise ManifestValidationError(
                    f"stage {stage.stage_id} requirement "
                    f"{requirement.requirement_id} needs "
                    f"at least {requirement.minimum_assets} "
                    "matching assets but found "
                    f"{matching_assets}"
                )


def _role_is_allowed(
    asset: CompiledAsset,
    role: CompiledRole,
) -> bool:
    role_id = role.role_id

    if role_id in asset.declared_prohibited_roles:
        return False

    declared_allowed = (
        role_id in asset.declared_allowed_roles
    )

    characteristics = set(asset.characteristics)

    requires_all = set(role.requires_all)
    requires_any = set(role.requires_any)
    forbids_any = set(role.forbids_any)

    all_satisfied = requires_all <= characteristics
    any_satisfied = (
        not requires_any
        or bool(requires_any & characteristics)
    )
    forbidden_present = bool(
        forbids_any & characteristics
    )

    rule_satisfied = (
        all_satisfied
        and any_satisfied
        and not forbidden_present
    )

    if role.derivation_mode == "declared_only":
        return declared_allowed

    if role.derivation_mode == "rule_based":
        return rule_satisfied

    if role.derivation_mode == "hybrid":
        return declared_allowed or rule_satisfied

    return False


def _validate_stage_graph(
    manifest: CompiledStudyManifest,
) -> None:
    indegree = {
        stage.stage_id: 0
        for stage in manifest.stages
    }

    adjacency: dict[int, list[int]] = {
        stage.stage_id: []
        for stage in manifest.stages
    }

    for stage in manifest.stages:
        for dependency in stage.dependencies:
            adjacency[dependency].append(
                stage.stage_id
            )
            indegree[stage.stage_id] += 1

    queue = deque(
        stage_id
        for stage_id, degree in indegree.items()
        if degree == 0
    )

    visited = 0

    while queue:
        stage_id = queue.popleft()
        visited += 1

        for child in adjacency[stage_id]:
            indegree[child] -= 1

            if indegree[child] == 0:
                queue.append(child)

    if visited != len(manifest.stages):
        raise ManifestValidationError(
            "stage dependency graph contains a cycle"
        )
