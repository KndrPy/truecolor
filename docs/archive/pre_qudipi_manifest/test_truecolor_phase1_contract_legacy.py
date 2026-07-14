from qudipi.truecolor_phase1 import TRUECOLOR_PHASE1
from qudipi.validation import validate_study_contract


def test_truecolor_phase1_contract_is_valid() -> None:
    validate_study_contract(TRUECOLOR_PHASE1)


def test_truecolor_has_complete_stage_range() -> None:
    assert [
        stage.stage_id
        for stage in TRUECOLOR_PHASE1.stages
    ] == list(range(29))


def test_all_stage_references_resolve() -> None:
    asset_ids = {
        asset.asset_id
        for asset in TRUECOLOR_PHASE1.assets
    }
    operator_ids = {
        operator.operator_id
        for operator in TRUECOLOR_PHASE1.operators
    }

    for stage in TRUECOLOR_PHASE1.stages:
        assert set(stage.required_assets) <= asset_ids
        assert set(stage.required_operators) <= operator_ids


def test_scientific_claim_boundaries_are_registered() -> None:
    assert (
        "prediction_is_not_identifiability"
        in TRUECOLOR_PHASE1.research_pack.validity_rules
    )
    assert (
        "universal_RGB_to_spectrum_inversion"
        in TRUECOLOR_PHASE1.prohibited_claims
    )


def test_external_dataset_roles_are_bounded() -> None:
    assets = {
        asset.asset_id: asset
        for asset in TRUECOLOR_PHASE1.assets
    }

    assert "spectral_ground_truth" in assets["scin"].prohibited_roles
    assert (
        "instrument_measured_pigmentation"
        in assets["ddi"].prohibited_roles
    )
    assert (
        "post_result_endpoint_redefinition"
        in assets["ddi2"].prohibited_roles
    )
