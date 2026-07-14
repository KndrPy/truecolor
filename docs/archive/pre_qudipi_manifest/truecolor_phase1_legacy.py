from __future__ import annotations

from .contracts import (
    AnalysisOperator,
    AssetClass,
    DataAsset,
    OperatorClass,
    ResearchPack,
    ScientificStage,
    StageState,
    StudyContract,
)


TERMINAL_STATES = (
    StageState.CLOSED,
    StageState.CLOSED_WITH_SCOPE_RESTRICTION,
    StageState.FALSIFIED,
    StageState.NOT_TESTABLE_WITH_CURRENT_ASSETS,
)


def asset(
    asset_id: str,
    name: str,
    asset_class: AssetClass,
    roles: tuple[str, ...],
    *,
    prohibited: tuple[str, ...] = (),
    constraints: tuple[str, ...] = (),
    stages: tuple[int, ...] = (),
    status: str = "REGISTERED",
) -> DataAsset:
    return DataAsset(
        asset_id=asset_id,
        display_name=name,
        asset_class=asset_class,
        primary_roles=roles,
        prohibited_roles=prohibited,
        required_constraints=constraints,
        canonical_stages=stages,
        status=status,
    )


ASSETS = (
    asset(
        "prior_art_corpus",
        "Governed prior-art corpus and review artifacts",
        AssetClass.LITERATURE_CORPUS,
        (
            "scientific_grounding",
            "method_lineage",
            "framing_analysis",
            "novelty_boundary",
        ),
        prohibited=(
            "automatic_truth_promotion",
            "bibliography_only_lineage",
        ),
        stages=(1, 2, 15, 17, 25, 27),
    ),
    asset(
        "issa",
        "ISSA skin reflectance corpus",
        AssetClass.SPECTRAL_DATASET,
        (
            "primary_reflectance_analysis",
            "metrology",
            "spectral_geometry",
            "observability",
            "physics_fitting",
            "information_bounds",
        ),
        prohibited=(
            "direct_melanin_ground_truth",
            "global_subject_skin_tone_scalar",
        ),
        stages=tuple(range(3, 19)),
        status="COMPLETE_VALIDATED",
    ),
    asset(
        "nist_skin_reflectance",
        "NIST human skin reflectance reference",
        AssetClass.SPECTRAL_DATASET,
        (
            "external_reflectance_reference",
            "range_validation",
            "colorimetric_integration_validation",
        ),
        stages=(3, 6, 7, 8, 10, 13, 14, 18),
    ),
    asset(
        "hyper_skin",
        "Hyper-Skin VIS/NIR facial hyperspectral dataset",
        AssetClass.SPECTRAL_DATASET,
        (
            "external_spectral_reconstruction",
            "facial_spatial_spectral_analysis",
            "camera_simulation",
        ),
        prohibited=(
            "uncontrolled_smartphone_validation",
            "universal_population_inference",
        ),
        stages=(6, 7, 8, 9, 10, 11, 12, 18),
    ),
    asset(
        "chroma_fit",
        "CHROMA-FIT image and physical color dataset",
        AssetClass.MULTIMODAL_DATASET,
        (
            "instrument_grounded_color_validation",
            "indoor_outdoor_capture_analysis",
            "forehead_forearm_site_analysis",
            "AST_MST_mapping",
        ),
        prohibited=("full_reflectance_ground_truth",),
        stages=(5, 13, 18, 19, 25),
    ),
    asset(
        "skin_tone_wild",
        "Skin Tone in the Wild",
        AssetClass.IMAGE_DATASET,
        (
            "MST_annotation_analysis",
            "identity_disjoint_classification",
            "out_of_domain_generalization",
        ),
        prohibited=(
            "physical_pigmentation_truth",
            "spectral_identifiability",
        ),
        stages=(1, 18, 20, 25),
    ),
    asset(
        "mst_e",
        "Monk Skin Tone Examples",
        AssetClass.MULTIMODAL_DATASET,
        (
            "within_subject_capture_robustness",
            "still_video_analysis",
            "capture_control_curve",
        ),
        prohibited=(
            "instrument_measured_melanin",
            "clinical_replication",
        ),
        stages=(19, 25),
        status="COMPLETE_GOVERNED",
    ),
    asset(
        "scin",
        "SCIN",
        AssetClass.IMAGE_DATASET,
        (
            "acquisition_heterogeneity",
            "representation_robustness",
            "domain_shift",
            "condition_diversity",
        ),
        prohibited=(
            "spectral_ground_truth",
            "calibrated_colorimetric_truth",
            "melanin_ground_truth",
            "RGB_to_spectrum_validation",
            "pathology_confirmed_replication",
        ),
        stages=(20, 25),
        status="COMPLETE",
    ),
    asset(
        "fitzpatrick17k",
        "Fitzpatrick17k",
        AssetClass.IMAGE_DATASET,
        (
            "dermatology_benchmark",
            "label_quality_decomposition",
            "subgroup_analysis",
        ),
        prohibited=("physical_pigmentation_truth",),
        stages=(21, 25),
        status="COMPLETE",
    ),
    asset(
        "cleanpatrick",
        "CleanPatrick",
        AssetClass.REVIEW_ARTIFACT,
        (
            "duplicate_correction",
            "off_topic_correction",
            "label_error_correction",
        ),
        prohibited=("biological_ground_truth",),
        stages=(21, 25),
    ),
    asset(
        "ddi",
        "Diverse Dermatology Images",
        AssetClass.IMAGE_DATASET,
        (
            "pathology_confirmed_external_evaluation",
            "clinical_translation",
            "contrast_physics_horse_race",
        ),
        prohibited=("instrument_measured_pigmentation",),
        stages=(22, 25),
        status="COMPLETE_VALIDATED",
    ),
    asset(
        "ddi2",
        "DDI-2",
        AssetClass.IMAGE_DATASET,
        (
            "fixed_external_replication",
            "patient_disjoint_evaluation",
            "heterogeneity_analysis",
        ),
        prohibited=("post_result_endpoint_redefinition",),
        stages=(23, 25),
        status="COMPLETE_VALIDATED",
    ),
    asset(
        "mra_midas",
        "MRA-MIDAS",
        AssetClass.MULTIMODAL_DATASET,
        (
            "identity_matched_modality_analysis",
            "distance_analysis",
            "domain_shift_inventory",
        ),
        prohibited=(
            "paired_inference_without_verified_linkage",
            "filename_inferred_identity",
        ),
        stages=(24, 25),
        status="READY_WITH_DOCUMENTED_MISSING_IMAGES",
    ),
    asset(
        "camera_sensitivities",
        "Measured camera spectral sensitivities",
        AssetClass.CAMERA_SENSITIVITY,
        (
            "camera_observation_operator",
            "camera_family_robustness",
            "sensor_perturbation",
        ),
        prohibited=("single_camera_universalization",),
        stages=(11, 12, 15, 17, 18),
    ),
    asset(
        "illuminant_library",
        "Measured and reference illuminant spectra",
        AssetClass.ILLUMINANT_SPECTRA,
        (
            "camera_illuminant_operator",
            "illumination_sensitivity",
            "photon_preserving_model",
        ),
        prohibited=("nominal_label_as_measured_SPD",),
        stages=(11, 12, 13, 15, 17, 18),
    ),
    asset(
        "cie_standards",
        "CIE observers, white points, and color standards",
        AssetClass.COLOR_STANDARD,
        (
            "XYZ_integration",
            "Lab_conversion",
            "DeltaE_validation",
        ),
        prohibited=("colorimetric_identity_as_spectral_identity",),
        stages=(13, 18),
    ),
    asset(
        "chromophore_basis",
        "Chromophore extinction spectra and scattering priors",
        AssetClass.OPTICAL_BASIS,
        (
            "forward_skin_physics",
            "inverse_parameter_estimation",
            "Fisher_information",
        ),
        prohibited=("fixed_universal_parameter_truth",),
        stages=(14, 15, 16, 17, 18),
    ),
)


def operator(
    operator_id: str,
    name: str,
    operator_class: OperatorClass,
    purpose: str,
    *,
    validations: tuple[str, ...] = (),
    prohibited: tuple[str, ...] = (),
) -> AnalysisOperator:
    return AnalysisOperator(
        operator_id=operator_id,
        display_name=name,
        operator_class=operator_class,
        scientific_purpose=purpose,
        required_validations=validations,
        prohibited_interpretations=prohibited,
    )


OPERATORS = (
    operator(
        "governance",
        "Program governance and reproducibility",
        OperatorClass.GOVERNANCE,
        "Register environments, assets, seeds, hashes, stages, and deviations.",
    ),
    operator(
        "prior_art_grounding",
        "Source-grounded prior-art compiler",
        OperatorClass.GROUNDING,
        "Capture claims, methods, regimes, framing, material lineage, and review interpretations.",
        prohibited=("published_claim_as_truth",),
    ),
    operator(
        "canonical_build",
        "Canonical dataset builder",
        OperatorClass.DATA_PIPELINE,
        "Normalize schemas, units, identifiers, wavelengths, and analytical tables.",
    ),
    operator(
        "metrology",
        "Identity, duplication, leakage, and effective-N analysis",
        OperatorClass.METROLOGY,
        "Establish observational units and measurement integrity.",
    ),
    operator(
        "measurand_admissibility",
        "Measurand and proxy admissibility",
        OperatorClass.QUANTITATIVE,
        "Test whether colorimetric and spectral proxies support the intended scientific interpretation.",
    ),
    operator(
        "representation_admissibility",
        "Spectral representation admission",
        OperatorClass.FUNCTIONAL,
        "Evaluate physical and functional transformations for stability, reconstruction, and noise.",
    ),
    operator(
        "linear_geometry",
        "Linear spectral geometry",
        OperatorClass.QUANTITATIVE,
        "Estimate covariance, rank, conditioning, redundancy, and site-conditioned structure.",
    ),
    operator(
        "functional_geometry",
        "Functional, nonlinear, and local geometry",
        OperatorClass.FUNCTIONAL,
        "Estimate FPCA structure, local dimension, diffusion geometry, and stability.",
    ),
    operator(
        "compact_representation",
        "Subject-disjoint compact representation validation",
        OperatorClass.QUANTITATIVE,
        "Validate compact global and site-specific bases without subject leakage.",
    ),
    operator(
        "wavelength_information",
        "Wavelength redundancy and innovation",
        OperatorClass.QUANTITATIVE,
        "Quantify conditional redundancy, residual innovation, loading stability, and stable subsets.",
    ),
    operator(
        "observation_operator",
        "Camera and illuminant observation operator",
        OperatorClass.OBSERVABILITY,
        "Construct measured camera-illuminant operators and quantify conditioning.",
    ),
    operator(
        "direct_observability",
        "Direct observability and real-spectrum metamer search",
        OperatorClass.OBSERVABILITY,
        "Measure row-space alignment, null-space energy, and realistic metamer collapse.",
    ),
    operator(
        "colorimetry",
        "External colorimetric anchoring",
        OperatorClass.COLORIMETRY,
        "Validate CIE integration, Lab reconstruction, DeltaE, observers, illuminants, and white points.",
    ),
    operator(
        "skin_physics",
        "Forward skin physics and inverse fitting",
        OperatorClass.OPTICAL_PHYSICS,
        "Fit multi-chromophore and scattering models using multiple physical solvers.",
    ),
    operator(
        "information_bound",
        "Fisher information and mechanism attribution",
        OperatorClass.INFORMATION_BOUND,
        "Compute CRBs and decompose photon, derivative, collinearity, and projection effects.",
    ),
    operator(
        "simulation",
        "Matched simulation and falsification",
        OperatorClass.SIMULATION,
        "Verify recovery, calibration, false positives, rank, localization, and attribution under known truth.",
    ),
    operator(
        "measurement_design",
        "Optimal measurement and band design",
        OperatorClass.OPTIMIZATION,
        "Compare candidate measurement systems using information, parity, and robustness objectives.",
    ),
    operator(
        "predictive_benchmarks",
        "Statistical, tensor, and neural recovery benchmarks",
        OperatorClass.APPLIED_AI,
        "Benchmark simple, statistical, tensor, and neural models under disjoint validation.",
        prohibited=("prediction_as_identifiability_proof",),
    ),
    operator(
        "mst_capture",
        "MST-E capture robustness",
        OperatorClass.QUANTITATIVE,
        "Estimate within-subject effects of capture conditions using mixed models.",
    ),
    operator(
        "scin_audit",
        "SCIN acquisition and representation audit",
        OperatorClass.APPLIED_AI,
        "Audit acquisition heterogeneity, labels, contrast, perturbations, and domain shift.",
    ),
    operator(
        "data_quality_decomposition",
        "Fitzpatrick17k and CleanPatrick quality decomposition",
        OperatorClass.CLINICAL_TRANSLATION,
        "Measure the effects of duplicates, off-topic records, and label correction.",
    ),
    operator(
        "ddi_translation",
        "DDI clinical translation",
        OperatorClass.CLINICAL_TRANSLATION,
        "Separate disease mix, contrast, acquisition, and physics contributions.",
    ),
    operator(
        "ddi2_replication",
        "DDI-2 fixed external replication",
        OperatorClass.CLINICAL_TRANSLATION,
        "Replicate the frozen DDI analysis without endpoint or threshold redefinition.",
    ),
    operator(
        "mra_midas_audit",
        "MRA-MIDAS identity and modality audit",
        OperatorClass.METROLOGY,
        "Establish linkage and admissibility before paired modality or distance inference.",
    ),
    operator(
        "integrated_decomposition",
        "Integrated physics, contrast, and data-quality decomposition",
        OperatorClass.QUANTITATIVE,
        "Estimate dataset-specific and cross-dataset mechanism contributions and interactions.",
    ),
    operator(
        "statistical_closure",
        "Statistical closure and lockbox",
        OperatorClass.QUANTITATIVE,
        "Apply multiplicity, clustered inference, permutation, controls, specification curves, and lockbox rules.",
    ),
    operator(
        "claim_adjudication",
        "Final claim adjudication",
        OperatorClass.PUBLICATION,
        "Assign terminal claim states with evidence, uncertainty, scope, and replication.",
    ),
    operator(
        "reproducibility_release",
        "Clean-room reproduction and release",
        OperatorClass.PUBLICATION,
        "Reproduce data products, models, figures, tables, reports, and hashes independently.",
    ),
)


def stage(
    stage_id: int,
    name: str,
    purpose: str,
    dependencies: tuple[int, ...],
    assets: tuple[str, ...],
    operators: tuple[str, ...],
    *,
    state: StageState = StageState.OPEN,
) -> ScientificStage:
    return ScientificStage(
        stage_id=stage_id,
        name=name,
        purpose=purpose,
        dependencies=dependencies,
        required_assets=assets,
        required_operators=operators,
        closure_requirements=(
            "entry_conditions_verified",
            "scientific_question_fixed",
            "estimands_registered",
            "primary_method_executed",
            "independent_validation_executed",
            "falsification_conditions_adjudicated",
            "scope_restrictions_recorded",
            "immutable_artifacts_hashed",
            "reproduction_instruction_recorded",
        ),
        falsification_conditions=(
            "registered_stage_specific_kill_condition",
        ),
        allowed_terminal_states=TERMINAL_STATES,
        current_state=state,
    )


STAGES = (
    stage(0, "Governance and reproducibility", "Create the governed research control plane.", (), ("prior_art_corpus",), ("governance",), state=StageState.VERIFY),
    stage(1, "Prior-art and novelty boundary", "Determine occupied, contested, and untested scientific space.", (0,), ("prior_art_corpus", "skin_tone_wild", "chroma_fit"), ("prior_art_grounding",), state=StageState.OPEN),
    stage(2, "Scientific charter and lockbox", "Freeze claims, estimands, admissibility, falsification, and multiplicity.", (1,), ("prior_art_corpus",), ("governance",), state=StageState.VERIFY),
    stage(3, "Asset registry and canonicalization", "Establish deterministic datasets and lineage.", (0, 2), ("issa", "nist_skin_reflectance", "hyper_skin", "chroma_fit"), ("canonical_build",), state=StageState.VERIFY),
    stage(4, "ISSA metrology and effective N", "Establish independent units and measurement integrity.", (3,), ("issa",), ("metrology",)),
    stage(5, "Measurand admissibility", "Adjudicate ITA, nuisance effects, sites, and proxy validity.", (4,), ("issa", "chroma_fit"), ("measurand_admissibility",), state=StageState.CLOSED_WITH_SCOPE_RESTRICTION),
    stage(6, "Representation admissibility", "Admit or reject physical and functional spectral representations.", (4, 5), ("issa", "nist_skin_reflectance", "hyper_skin"), ("representation_admissibility",)),
    stage(7, "Linear spectral geometry", "Characterize global and conditioned linear structure.", (6,), ("issa", "nist_skin_reflectance", "hyper_skin"), ("linear_geometry",), state=StageState.VERIFY),
    stage(8, "Functional and local geometry", "Test functional, nonlinear, and local intrinsic structure.", (6, 7), ("issa", "hyper_skin"), ("functional_geometry",)),
    stage(9, "Compact representation validation", "Validate subject-disjoint compact spectral representations.", (6, 7), ("issa",), ("compact_representation",), state=StageState.CLOSED_WITH_SCOPE_RESTRICTION),
    stage(10, "Wavelength redundancy and innovation", "Separate redundant and informative spectral structure.", (7, 8, 9), ("issa", "nist_skin_reflectance", "hyper_skin"), ("wavelength_information",), state=StageState.VERIFY),
    stage(11, "Camera and illuminant operator", "Construct measured observation operators.", (6, 10), ("camera_sensitivities", "illuminant_library", "issa"), ("observation_operator",)),
    stage(12, "Direct observability and metamers", "Quantify real-spectrum collapse under camera projection.", (11,), ("issa", "camera_sensitivities", "illuminant_library"), ("direct_observability",)),
    stage(13, "Colorimetric anchoring", "Validate spectral-to-color transformations and external agreement.", (3, 11), ("cie_standards", "issa", "nist_skin_reflectance", "chroma_fit"), ("colorimetry",)),
    stage(14, "Forward skin physics", "Fit and validate interpretable skin optical models.", (6, 12, 13), ("issa", "chromophore_basis"), ("skin_physics",)),
    stage(15, "Information bounds and four-mechanism attribution", "Quantify recoverability limits and mechanism contributions.", (11, 12, 14), ("issa", "camera_sensitivities", "illuminant_library", "chromophore_basis", "prior_art_corpus"), ("information_bound",)),
    stage(16, "Matched simulation and falsification", "Verify the entire analytical pipeline under known truth.", (6, 11, 14, 15), ("chromophore_basis", "camera_sensitivities", "illuminant_library"), ("simulation",)),
    stage(17, "Optimal measurement design", "Identify robust and parsimonious measurement systems.", (15, 16), ("camera_sensitivities", "illuminant_library", "chromophore_basis", "prior_art_corpus"), ("measurement_design",)),
    stage(18, "Predictive recovery benchmarks", "Compare simple, statistical, tensor, and neural recovery models.", (9, 12, 14, 15, 16), ("issa", "hyper_skin", "chroma_fit", "skin_tone_wild", "camera_sensitivities", "illuminant_library", "cie_standards", "chromophore_basis"), ("predictive_benchmarks",)),
    stage(19, "MST-E capture robustness", "Quantify within-subject capture-condition variation.", (5, 18), ("mst_e", "chroma_fit"), ("mst_capture",)),
    stage(20, "SCIN acquisition and representation audit", "Characterize heterogeneous image acquisition and domain shift.", (18, 19), ("scin", "skin_tone_wild"), ("scin_audit",)),
    stage(21, "Fitzpatrick17k and CleanPatrick decomposition", "Separate duplicate, off-topic, label, and subgroup effects.", (18,), ("fitzpatrick17k", "cleanpatrick"), ("data_quality_decomposition",)),
    stage(22, "DDI clinical translation", "Test physics, contrast, disease, and acquisition explanations.", (15, 18, 21), ("ddi",), ("ddi_translation",)),
    stage(23, "DDI-2 fixed replication", "Replicate the frozen DDI specification externally.", (22,), ("ddi2",), ("ddi2_replication",)),
    stage(24, "MRA-MIDAS linkage and admissibility", "Establish valid identity-matched modality and distance comparisons.", (4, 18), ("mra_midas",), ("mra_midas_audit",)),
    stage(25, "Integrated mechanism decomposition", "Integrate physics, contrast, data quality, domain, and disease mechanisms.", (19, 20, 21, 22, 23, 24), ("prior_art_corpus", "mst_e", "scin", "fitzpatrick17k", "cleanpatrick", "ddi", "ddi2", "mra_midas"), ("integrated_decomposition",)),
    stage(26, "Statistical closure and lockbox", "Freeze and execute final inferential controls.", (16, 25), ("issa", "mst_e", "ddi", "ddi2", "mra_midas"), ("statistical_closure",)),
    stage(27, "Final claim adjudication", "Assign terminal evidence states to all registered claims.", (26,), ("prior_art_corpus",), ("claim_adjudication",)),
    stage(28, "Clean-room reproduction and release", "Reproduce and release the complete evidence chain.", (27,), ("prior_art_corpus",), ("reproducibility_release",)),
)


SKIN_PHOTON_PACK = ResearchPack(
    pack_id="skin_photon",
    display_name="Skin Pigmentation and Photon Measurement",
    domain_dimensions=(
        "wavelength",
        "reflectance",
        "chromophore",
        "scattering",
        "anatomical_site",
        "pigmentation_regime",
        "camera_sensitivity",
        "illuminant_SPD",
        "capture_control",
        "colorimetric_proxy",
        "lesion_contrast",
        "label_quality",
    ),
    domain_relationships=(
        "CHROMOPHORE_CONTRIBUTES_TO",
        "ILLUMINATION_MODULATES",
        "SPECTRAL_RESPONSE_PROJECTED_BY",
        "PROXY_CONFLATES",
        "METAMERIC_WITH",
        "OPTICALLY_INDISTINGUISHABLE_UNDER",
    ),
    validity_rules=(
        "subject_count_is_not_pixel_count",
        "Fitzpatrick_is_not_physical_color_ground_truth",
        "MST_is_not_melanin_ground_truth",
        "prediction_is_not_identifiability",
        "colorimetric_similarity_is_not_spectral_identity",
        "camera_results_require_multiple_measured_sensitivities",
        "illumination_labels_do_not_replace_measured_SPD",
    ),
)


TRUECOLOR_PHASE1 = StudyContract(
    study_id="truecolor",
    display_name="TrueColor Skin Pigmentation and Photon Study",
    phase=1,
    research_pack=SKIN_PHOTON_PACK,
    assets=ASSETS,
    operators=OPERATORS,
    stages=STAGES,
    terminal_claim_states=(
        "SUPPORTED",
        "SUPPORTED_WITH_SCOPE_RESTRICTION",
        "INCONCLUSIVE",
        "FALSIFIED",
        "NOT_TESTABLE_WITH_CURRENT_ASSETS",
    ),
    prohibited_claims=(
        "universal_RGB_to_spectrum_inversion",
        "direct_melanin_concentration_from_ISSA_alone",
        "causal_biology_from_image_labels",
        "universal_camera_bound_from_one_CSS",
        "global_stable_skin_tone_scalar_across_sites_and_conditions",
    ),
)
