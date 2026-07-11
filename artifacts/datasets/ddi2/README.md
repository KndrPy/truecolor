# DDI-2 Dataset Integration

## Role

DDI-2 is used for patient-disjoint external dermatology evaluation and subgroup robustness analysis.

It is not treated as colorimeter-grounded pigmentation truth.

## Validated Local State

- 665 images
- 550 patients
- canonical package validated locally
- patient-disjoint folds prepared locally

## Split Invariant

All images associated with one patient must remain in one partition. Exact-byte or derived-image relationships must also remain within one partition.

## Public Repository Scope

Permitted artifacts include aggregate integrity summaries, schema descriptions, patient-disjoint split-generation methodology, and aggregate fold statistics.

Patient identifiers, image-level records, filename mappings, and actual patient-to-fold assignments remain outside Git.
