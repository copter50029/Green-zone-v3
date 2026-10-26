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

`registry/parks15.geojson` is the 2026-10-23 snapshot: 528 valid-coordinate entries from 530 rows. Rows 59 and 93 had unusable coordinates. Source details and the original marker SHA256 are inside the file. Row IDs should not be assumed stable across refreshes.

Do not replace human references with assistant labels or policy masks. Keep attribution and snapshot dates. No matching points does not prove that an image has no parks.

Raw TIFFs belong in `Images/`. Generated files belong in `Output/`.
