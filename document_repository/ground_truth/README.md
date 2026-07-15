# Internal Ground-Truth Document Repository

This directory is the single canonical document repository consumed by Stage 1 and by internal services that parse, reconstruct, classify, reconcile, or ground scientific documents.

## Canonical authority

Only documents promoted through the controlled ingress workflow may enter this repository. Services must not parse directly from `document_ingress/user_upload_inbox/`, ad hoc downloads, temporary folders, or user desktop paths.

## Required object invariants

Every canonical document must have:

- stable ground-truth document ID independent of filename;
- original and current relative paths;
- SHA-256 of physical bytes;
- byte length and media type;
- promotion event ID;
- source-ingress event ID;
- first-seen and last-seen timestamps;
- current lifecycle state;
- immutable byte-history and path-history records;
- corpus membership controlled by the active Stage 1 corpus policy.

## Mutation policy

A replacement is a new physical-byte version. Existing bytes and history are not overwritten. Rename, removal, replacement, and restoration are explicit lifecycle events.

## Service contract

Stage 1 services receive a repository root and policy. They enumerate current accepted files from this repository, produce content-derived identities, and never infer identity from ordering or filename numbering.

The current 38-paper prior-art corpus will be promoted here after real-file validation from `preprocessed_intake/corpus_prior_art_paper-pdf/`.
