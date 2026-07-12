# TrueColor Stage 2 — Estimand and Claim Preregistration

## Purpose

Stage 2 fixes the scientific quantities, claim hierarchy, admissibility rules, falsification conditions, multiplicity families, and ISSA lockbox policy before new confirmatory analysis.

## Registered primary question

What information about measured human-skin spectral reflectance is observable through realistic three-channel camera operators, how does that observability vary across declared conditions, which mechanisms account for uncertainty, and what minimum additional measurement contracts that uncertainty?

## Registered clinical question

Does a physics-derived recoverability score explain patient-level dermatology model error after lesion contrast, diagnosis, prevalence, acquisition shift, duplicate leakage, and label quality are controlled, and does the effect replicate in DDI-2?

## Primary measurands

1. Instrument-measured spectral reflectance R(lambda).
2. CIE L*, a*, b* under declared measurement conditions.
3. ITA as a derived continuous colorimetric descriptor.

ITA is not registered as direct melanin concentration.

## Primary estimands

E01 effective spectral dimension.
E02 camera-manifold alignment.
E03 real-skin metamer rate.
E04 held-out recoverability error.
E05 information bound.
E06 interaction-aware mechanism attribution.
E07 minimum sufficient added measurement.
E08 clinical incremental explanatory value.

## Claim boundary

Direct measurements and deterministic transformations may be described as measured, observed, computed, or derived. Forward-physics and sensor-noise results must be labeled modeled or bounded under assumptions. Image-domain results are associations or replications. Current assets cannot establish a validated universal consumer RGB-to-spectrum corrector.

## Inference unit

ISSA: subject or resolved composite component.
MST-E: subject.
DDI/DDI-2: patient.
MRA-MIDAS: highest verified identity.

## Confirmatory families

PF1 contains the five physics claims. Holm family-wise error control is applied where inferential tests are used.
PF2 contains the clinical incremental-value and replication tests.
Discovery families use Benjamini-Hochberg FDR.

## Lockbox

The 2,314-row ISSA test split remains sealed until metrology, measurand, simulation, preprocessing, model-selection, code, and environment gates are frozen. Opening is one-time. No retuning follows.

## Falsification

Each primary estimand has a predeclared result that rejects, narrows, or suspends the associated claim. Null results remain part of the final adjudication.

## Deviations

Any change after this closure requires a timestamped deviation record stating:
- affected registry field;
- reason;
- whether data had been observed;
- expected bias direction;
- approver;
- replacement analysis;
- effect on confirmatory status.
