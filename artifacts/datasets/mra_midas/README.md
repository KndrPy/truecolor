# MRA-MIDAS Dataset Integration

## Purpose

MRA-MIDAS is used as an external multimodal dermatology benchmark for:

- clinical versus dermoscopic modality analysis;
- capture-distance robustness;
- Fitzpatrick-stratified evaluation;
- pathology-grounded lesion evaluation;
- patient-disjoint multimodal modeling.

It is not used as instrument-grounded skin-color truth and does not provide paired colorimeter or spectrophotometer measurements for absolute CIELAB or ITA validation.

## Governed Local Package

The source package is retained outside the Git repository under the configured external data root.

No source images, source workbook, patient-level metadata, image-level metadata, filenames, source hashes, or restricted dataset content are redistributed through this repository.

## Validated Package State

| Measure | Count |
|---|---:|
| Workbook records | 3,416 |
| Physical image files | 3,416 |
| Strict workbook-to-file links | 3,403 |
| Deterministic filename-overlay links | 1 |
| Analysis-eligible linked records | 3,404 |
| Workbook records missing physical images | 12 |
| Notebook checkpoint artifacts | 7 |
| Unassigned extra physical variants | 5 |
| Physically valid JPEG images | 3,416 |

Canonical readiness status:

`READY_WITH_12_DOCUMENTED_MISSING_IMAGES`

## Linkage Policy

The canonical reconciliation uses, in order:

1. exact case-insensitive filename and extension matching;
2. unique filename-stem matching where only the extension differs;
3. unique recognized suffix normalization;
4. one deterministic `_cropped` correction retaining the workbook extension.

No speculative mapping was applied to the twelve workbook records without corresponding physical images.

## Analytical Constraints

- Splits must be patient-disjoint.
- Captures of the same lesion must remain in the same partition.
- Clinical and dermoscopic captures associated with the same record must not cross partitions.
- Missing physical records are retained in metadata but excluded from image loading.
- Exact-byte duplicates must be treated as a leakage constraint.
- MRA-MIDAS must not be presented as calibrated skin-pigmentation ground truth.
