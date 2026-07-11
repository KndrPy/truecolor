# SCIN

## Role

External teledermatology evaluation dataset containing consented,
user-contributed images, dermatologist condition labels, estimated
Fitzpatrick skin type, and estimated Monk Skin Tone.

## Source

Official Google Research SCIN release and the
`dx-scin-public-data` Google Cloud Storage bucket.

## License

SCIN Data Use License. See:

`datasets/licenses/SCIN_DATA_USE_LICENSE.txt`

## Mandatory restrictions

- Do not attempt re-identification or re-linking.
- Retain attribution, source, license, and modification notices.
- Treat images as potentially sensitive medical content.
- Do not place raw images in this Git repository.
- Record all exclusions, transformations, and deduplication operations.

## Known release issues

- 15 unique duplicate images appearing 42 times in total.
- 48 gradable cases without a skin-condition label.
- One referenced image is missing.
- Subject-level splitting and duplicate removal are required before evaluation.

## Intended use in TrueColor

SCIN is not instrument-measured pigmentation ground truth.

Use it for:

- telemedicine capture-quality evaluation;
- eMST and eFST ordinal evaluation;
- disease-versus-baseline pigmentation confounding;
- illumination and device robustness;
- uncertainty and abstention analysis.
