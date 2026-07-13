# ISSA Stage 3 Metrology and Provenance Report

Status: **CLOSED**

## Canonical source
- Path: `/mnt/d/truecolor-data/derived/issa/issa_analysis_table.parquet`
- Rows: 15256
- Columns: 47

## Hard gates
- source_hash_present: **PASS**
- canonical_row_count_match: **PASS**
- wavelength_grid_exact: **PASS**
- subject_key_present: **PASS**
- subject_count_reconciled: **PASS**
- split_leakage_zero: **PASS**
- reflectance_scale_resolved: **PASS**
- nonzero_admissible_rows: **PASS**
- all_rows_not_rejected: **PASS**
- admissible_fraction_nontrivial: **PASS**

## Key findings
- Wavelength exact match: True
- Reflectance source scale: percent
- Normalization factor: 0.01
- Admissible rows: 15256
- Admissible fraction: 1.0
- Unique subject keys: 2107
- Expected subject/composite IDs: 2107
- Split leakage subject keys: 0
- Basic inadmissible rows: 0
- Exact duplicate rows: 138
- Near-duplicate pairs: 594

## Interpretation discipline
- Pooling across instruments, origins, body sites, or SCI/SCE conventions is not permitted unless the emitted distributions and variance analyses support it.
- The empirical repeatability floor is descriptive unless genuinely repeated comparable measurements exist.
- Composite identities remain provisional unless their provenance is resolved from source documentation.
- A closed Stage 3 certifies data admissibility and provenance rules; it does not certify the later physics claims.
