from __future__ import annotations

import json

from .truecolor_phase1 import truecolor_phase1


def main() -> None:
    manifest = truecolor_phase1()

    print(
        json.dumps(
            {
                "manifest_schema":
                    manifest.manifest_schema,
                "manifest_version":
                    manifest.manifest_version,
                "product_version":
                    manifest.product_version,
                "config_sha256":
                    manifest.config_sha256,
                "study_id":
                    manifest.application.study_id,
                "phase":
                    manifest.phase,
                "research_pack":
                    manifest.application.research_pack_id,
                "asset_count":
                    len(manifest.assets),
                "role_count":
                    len(manifest.roles),
                "required_detail_count":
                    len(
                        manifest
                        .corpus_characterization
                        .required_details
                    ),
                "schema_count":
                    len(manifest.schemas),
                "operator_count":
                    len(manifest.operators),
                "stage_count":
                    len(manifest.stages),
                "first_stage":
                    manifest.stage_id_min,
                "last_stage":
                    manifest.stage_id_max,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
