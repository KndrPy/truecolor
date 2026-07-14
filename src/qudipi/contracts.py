from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class ManifestValidationError(ValueError):
    """Raised when a compiled QuDiPi manifest is malformed or unsupported."""


@dataclass(frozen=True, slots=True)
class CompiledApplication:
    project_id: str
    phase: int
    study_id: str
    research_pack_id: str
    single_config_authority: bool


@dataclass(frozen=True, slots=True)
class CompiledCorpusCharacterization:
    required_details: tuple[str, ...]
    controlled_characteristics: bool
    reject_unknown_roles: bool
    preserve_unknown_details: bool


@dataclass(frozen=True, slots=True)
class CompiledRole:
    role_id: str
    description: str
    role_class: str
    derivation_mode: str
    requires_all: tuple[str, ...]
    requires_any: tuple[str, ...]
    forbids_any: tuple[str, ...]
    risk_class: str


@dataclass(frozen=True, slots=True)
class CompiledStageAssetRequirement:
    requirement_id: str
    minimum_assets: int
    required_characteristics: tuple[str, ...]
    accepted_roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompiledStage:
    stage_id: int
    key: str
    name: str
    purpose: str
    dependencies: tuple[int, ...]
    required_assets: tuple[str, ...]
    required_operators: tuple[str, ...]
    current_disposition: str
    asset_requirements: tuple[
        CompiledStageAssetRequirement,
        ...,
    ]


@dataclass(frozen=True, slots=True)
class CompiledAsset:
    asset_id: str
    display_name: str
    asset_class: str
    acquisition_status: str
    license_status: str
    governance_class: str
    identity_unit: str
    measurement_unit: str
    characteristics: tuple[str, ...]
    known_details: Mapping[str, str]
    unknown_details: tuple[str, ...]
    declared_allowed_roles: tuple[str, ...]
    declared_prohibited_roles: tuple[str, ...]
    applicable_stages: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CompiledSchema:
    schema_id: str
    description: str
    schema_class: str
    serialization: str
    version: int


@dataclass(frozen=True, slots=True)
class CompiledOperator:
    operator_id: str
    engine: str
    entrypoint: str
    input_schema: str
    output_schema: str
    resource_profile: str


@dataclass(frozen=True, slots=True)
class CompiledStudyManifest:
    manifest_schema: str
    manifest_version: int
    product_version: str
    config_sha256: str
    phase: int
    stage_count: int
    stage_id_min: int
    stage_id_max: int
    single_config_authority: bool
    application: CompiledApplication
    corpus_characterization: CompiledCorpusCharacterization
    roles: tuple[CompiledRole, ...]
    stages: tuple[CompiledStage, ...]
    assets: tuple[CompiledAsset, ...]
    schemas: tuple[CompiledSchema, ...]
    operators: tuple[CompiledOperator, ...]

    def stage_by_id(self, stage_id: int) -> CompiledStage:
        for stage in self.stages:
            if stage.stage_id == stage_id:
                return stage

        raise KeyError(f"unknown stage ID: {stage_id}")

    def asset_by_id(self, asset_id: str) -> CompiledAsset:
        for asset in self.assets:
            if asset.asset_id == asset_id:
                return asset

        raise KeyError(f"unknown asset ID: {asset_id}")

    def role_by_id(self, role_id: str) -> CompiledRole:
        for role in self.roles:
            if role.role_id == role_id:
                return role

        raise KeyError(f"unknown role ID: {role_id}")

    def schema_by_id(self, schema_id: str) -> CompiledSchema:
        for schema in self.schemas:
            if schema.schema_id == schema_id:
                return schema

        raise KeyError(f"unknown schema ID: {schema_id}")

    def operator_by_id(
        self,
        operator_id: str,
    ) -> CompiledOperator:
        for operator in self.operators:
            if operator.operator_id == operator_id:
                return operator

        raise KeyError(f"unknown operator ID: {operator_id}")
