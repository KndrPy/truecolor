use qudipi_config::{AssetConfig, Config, RoleConfig, RoleDerivationMode, load, validate};
use qudipi_domain::{AccessClass, AssetId, RoleId};
use std::{collections::BTreeMap, path::PathBuf};

fn canonical_config() -> Config {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../qudipi.toml");

    load(path).expect("canonical config must load")
}

fn synthetic_asset() -> AssetConfig {
    AssetConfig {
        id: AssetId::new("synthetic_asset").unwrap(),
        display_name: "Synthetic asset".to_string(),
        asset_class: "synthetic".to_string(),
        acquisition_status: "available".to_string(),
        license_status: "approved".to_string(),
        governance_class: AccessClass::ProjectPrivate,
        identity_unit: "sample".to_string(),
        measurement_unit: "value".to_string(),
        characteristics: vec!["measured".to_string(), "provenance_available".to_string()],
        known_details: BTreeMap::from([
            ("identity_structure".to_string(), "sample".to_string()),
            ("license_scope".to_string(), "research".to_string()),
            ("measurement_type".to_string(), "value".to_string()),
        ]),
        unknown_details: vec![
            "capture_device".to_string(),
            "consent_scope".to_string(),
            "illumination".to_string(),
            "label_provenance".to_string(),
            "measurement_provenance".to_string(),
            "modality".to_string(),
            "repeat_measure_structure".to_string(),
            "site".to_string(),
            "wavelength_axis".to_string(),
        ],
        declared_allowed_roles: Vec::new(),
        declared_prohibited_roles: Vec::new(),
        applicable_stages: Vec::new(),
    }
}

#[test]
fn canonical_generic_corpus_config_is_valid() {
    validate(&canonical_config()).unwrap();
}

#[test]
fn unknown_required_detail_is_preserved() {
    let mut config = canonical_config();
    let required = config.corpus_characterization.required_details[0].clone();

    config.assets[0].known_details.remove(&required);

    if !config.assets[0].unknown_details.contains(&required) {
        config.assets[0].unknown_details.push(required);
    }

    validate(&config).unwrap();
}

#[test]
fn detail_cannot_be_both_known_and_unknown() {
    let mut config = canonical_config();
    let required = config.corpus_characterization.required_details[0].clone();

    config.assets[0]
        .known_details
        .insert(required.clone(), "known".to_string());

    if !config.assets[0].unknown_details.contains(&required) {
        config.assets[0].unknown_details.push(required);
    }

    let error = validate(&config).unwrap_err().to_string();

    assert!(error.contains("exactly one of known or unknown"));
}

#[test]
fn unknown_declared_role_is_rejected() {
    let mut config = canonical_config();

    config.assets[0]
        .declared_allowed_roles
        .push(RoleId::new("role_not_in_registry").unwrap());

    let error = validate(&config).unwrap_err().to_string();

    assert!(error.contains("unknown declared allowed role"));
}

#[test]
fn rule_based_role_can_be_defined_without_corpus_names() {
    let mut config = canonical_config();

    config.roles.insert(
        "synthetic_measurement_role".to_string(),
        RoleConfig {
            description: "Synthetic rule-based test role".to_string(),
            role_class: "scientific_use".to_string(),
            derivation_mode: RoleDerivationMode::RuleBased,
            requires_all: vec!["measured".to_string()],
            requires_any: vec!["provenance_available".to_string()],
            forbids_any: vec!["synthetic_only".to_string()],
            risk_class: "standard".to_string(),
        },
    );

    let asset = synthetic_asset();

    assert!(asset.characteristics.contains(&"measured".to_string()));
}
