use qudipi_config::{Config, ConfigError, load, validate};
use std::path::PathBuf;

fn canonical_config() -> Config {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../qudipi.toml");

    load(path).expect("canonical configuration must load")
}

fn validation_message(error: ConfigError) -> String {
    error.to_string()
}

fn find_unmapped_pair(config: &Config) -> (usize, usize) {
    for (stage_index, stage) in config.stages.iter().enumerate() {
        for (asset_index, asset) in config.assets.iter().enumerate() {
            let stage_requires_asset = stage.required_assets.contains(&asset.id);

            let asset_applies_to_stage = asset.applicable_stages.contains(&stage.id);

            if !stage_requires_asset && !asset_applies_to_stage {
                return (stage_index, asset_index);
            }
        }
    }

    panic!("canonical configuration has no unmapped stage-asset pair");
}

fn find_mapped_pair(config: &Config) -> (usize, usize) {
    for (stage_index, stage) in config.stages.iter().enumerate() {
        for asset_id in &stage.required_assets {
            if let Some(asset_index) = config.assets.iter().position(|asset| &asset.id == asset_id)
            {
                return (stage_index, asset_index);
            }
        }
    }

    panic!("canonical configuration has no mapped stage-asset pair");
}

#[test]
fn canonical_asset_stage_mapping_is_valid() {
    let config = canonical_config();

    validate(&config).expect("canonical asset-stage mapping must validate");
}

#[test]
fn unknown_asset_applicable_stage_is_rejected() {
    let mut config = canonical_config();

    config.assets[0].applicable_stages.push(34);

    let message = validation_message(
        validate(&config).expect_err("unknown applicable stage must be rejected"),
    );

    assert!(
        message.contains("unknown applicable stage 34"),
        "unexpected validation message: {message}"
    );
}

#[test]
fn duplicate_asset_applicable_stage_is_rejected() {
    let mut config = canonical_config();

    let (_, asset_index) = find_mapped_pair(&config);
    let existing_stage = config.assets[asset_index]
        .applicable_stages
        .first()
        .copied()
        .expect("mapped asset must contain an applicable stage");

    config.assets[asset_index]
        .applicable_stages
        .push(existing_stage);

    let message = validation_message(
        validate(&config).expect_err("duplicate applicable stages must be rejected"),
    );

    assert!(
        message.contains("duplicate applicable stage IDs"),
        "unexpected validation message: {message}"
    );
}

#[test]
fn stage_to_asset_asymmetry_is_rejected() {
    let mut config = canonical_config();

    let (stage_index, asset_index) = find_unmapped_pair(&config);
    let stage_id = config.stages[stage_index].id;
    let asset_id = config.assets[asset_index].id.clone();

    config.stages[stage_index]
        .required_assets
        .push(asset_id.clone());

    let message = validation_message(
        validate(&config).expect_err("stage-to-asset asymmetry must be rejected"),
    );

    assert!(
        message.contains("asset-stage mapping is asymmetric"),
        "unexpected validation message: {message}"
    );

    assert!(
        message.contains(&format!("stage {stage_id} requires asset {asset_id}")),
        "unexpected validation message: {message}"
    );
}

#[test]
fn asset_to_stage_asymmetry_is_rejected() {
    let mut config = canonical_config();

    let (stage_index, asset_index) = find_unmapped_pair(&config);
    let stage_id = config.stages[stage_index].id;
    let asset_id = config.assets[asset_index].id.clone();

    config.assets[asset_index].applicable_stages.push(stage_id);

    let message = validation_message(
        validate(&config).expect_err("asset-to-stage asymmetry must be rejected"),
    );

    assert!(
        message.contains("asset-stage mapping is asymmetric"),
        "unexpected validation message: {message}"
    );

    assert!(
        message.contains(&format!("asset {asset_id} applies to stage {stage_id}")),
        "unexpected validation message: {message}"
    );
}

#[test]
fn duplicate_stage_required_asset_is_rejected() {
    let mut config = canonical_config();

    let (stage_index, asset_index) = find_mapped_pair(&config);
    let asset_id = config.assets[asset_index].id.clone();

    config.stages[stage_index].required_assets.push(asset_id);

    let message =
        validation_message(validate(&config).expect_err("duplicate stage assets must be rejected"));

    assert!(
        message.contains("duplicate required assets"),
        "unexpected validation message: {message}"
    );
}
