# User Upload Inbox

This directory is the single user-driven document ingress endpoint for files received from the consumer application, direct upload, synchronized folder assignment, or an approved external document provider.

## Authority boundary

Files in this directory are **untrusted ingress objects**. They are not part of the scientific corpus and no internal service may treat them as ground truth until they pass promotion controls.

## Required ingress metadata

Each received object must be accompanied by an ingest record containing:

- immutable ingest event ID;
- original filename;
- source channel and external object identifier, when present;
- received timestamp;
- uploader or integration principal;
- byte length and SHA-256;
- detected media type;
- malware and malformed-file scan state;
- policy evaluation state;
- intended corpus or workspace;
- promotion state and promoted ground-truth object ID, when accepted.

## Allowed states

`RECEIVED`, `QUARANTINED`, `VALIDATED`, `REJECTED`, `PROMOTION_PENDING`, `PROMOTED`, `SUPERSEDED`.

## Promotion rule

Promotion must copy bytes atomically into `document_repository/ground_truth/`, verify the copied SHA-256, create the canonical ground-truth record, and append the promotion event before any Stage 1 service can consume the document.

This directory is ignored by Git except for this contract and its placeholder. User uploads must not be committed directly from the ingress area.
