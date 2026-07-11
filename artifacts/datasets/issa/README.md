# ISSA Dataset Integration

## Role

ISSA provides instrument-derived spectral reflectance and corresponding colorimetric values. It anchors the reflectance-to-CIELAB portion of the TrueColor research pipeline.

It does not independently validate smartphone RGB-to-CIELAB or smartphone RGB-to-ITA calibration.

## Validated Local State

- 15,256 measurements
- 2,107 subject or composite identifiers
- common spectral grid: 31 bands
- wavelength range: 400–700 nm
- wavelength interval: 10 nm
- subject/component-disjoint partitioning
- training measurements: 10,662
- validation measurements: 2,280
- test measurements: 2,314

## Public Repository Scope

Permitted public artifacts include:

- aggregate dataset validation;
- spectral-grid specification;
- split methodology without subject assignments;
- aggregate model evaluation;
- model coefficients;
- selected hyperparameters;
- bootstrap coefficient summaries without subject-resampling identities.

The source workbook, reflectance arrays, subject identifiers, measurement-level data, and subject split assignments remain outside Git.
