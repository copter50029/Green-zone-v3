# Data guide

`scenes.json` is the shared configuration. Paths are relative to the repository root.

| Folder | Contents | Verification status |
| --- | --- | --- |
| `registry/` | Cached Greener Bangkok points | Registry presence only |
| `exclusions/` | Cached buildings/residential/private context | Incomplete; not cadastral boundaries |
| `labels/assistant/` | Source-image interpretations | Human review pending |
| `labels/human/` | Independent reference files | Currently empty |
| `labels/policies/` | Housing exclusions and pending zones | Screening policy, not ownership proof |
| `labels/review/` | Visual review-cell decisions | Assistant context review only |

Reference: https://greener.bangkok.go.th/en/map-15-minute-garden/

`registry/suanluang-parks.geojson` contains the 11 supplied Suan Luang district park records used by the backend configuration. The records include parks with different owners; registry presence does not confirm public access or current status. Keep attribution and source details with the data.

Do not replace human references with assistant labels or policy masks. Keep attribution and snapshot dates. No matching points does not prove that an image has no parks.

Raw TIFFs belong in `Images/`. Generated files belong in `Output/`.
