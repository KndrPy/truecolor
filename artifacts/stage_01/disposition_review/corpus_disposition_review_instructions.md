# Stage 1 Corpus Disposition Review

Enter decisions in `corpus_disposition_decisions.csv`.

Allowed roles: FULL_SCIENTIFIC_EXTRACTION, BOUNDED_SCIENTIFIC_REVIEW, MATERIAL_LINEAGE_REFERENCE, EXCLUDED_WITH_REASON, TERMINAL_SOURCE_UNAVAILABLE.

Every completed row requires all six decision fields. `evidence_basis` must be a JSON array of objects with `source`, `basis`, and `evidence_type`.
