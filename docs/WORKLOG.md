# Work log — 2026-10-25

## Scope reviewed

Read the repository's source/configuration/docs (grid.py, README.md, .gitignore and license header), current Git diff/history, grid_index.csv header/sample and source metadata for Images/Theos00.tif, Theos01.tif and Theos02.tif. Dependencies in .venv and binary imagery were inspected as metadata, not counted as project source. This is the working clone at Documents/Codex/Green-zone-v2; the older clone under 2026-10-15/evi-ndvi is a separate checkout.

## Changes

- New branch nike/green-zone-functions from the existing main checkout.
- Preserved the user's uncommitted grid.py change (Theos2.tif -> Theos00.tif). No Nike edit to grid.py; local SHA256 before/after: c3601bb25c081cb92de6512d730c646139ec563d147cde858af44e9f975e20e4. Excluded grid.py from Nike commit.
- Reused previously tested standalone heatmap/park-review functions from the older Nike checkout; added a compact detector and run_nike.py integration example. No old HTTP server, ML models or frontend copied.
- Added cached public registry with snapshot date and source hash. No real review decision was created.
- Added Thai README/NIKE manual and ignores for environments, generated outputs and local config.
- Installed scipy in this clone's existing .venv; environments are ignored.

## Validation

20 synthetic unit/integration tests passed: detector classes and uint16 handling, NoData, exclusions, minimum patch area, fading colours, park evidence requirements, image-edge coverage, CRS/shape validation, GeoTIFF grid/alpha roundtrip and output overwrite protection. These are software tests, not semantic accuracy.

Ran the example on existing Theos00 tile_r7_c9.tif with experimental bands 3/4: 26,478.75 m2 candidate after filtering, 30 retained groups, 1 registry review task, 0 verified parks. Outputs remain local under Output/nike-preview-r7c9 and are not Git content.

## Limitations / next work

Band mapping/calibration still unverified; ratio detection alone cannot guarantee roof/private-garden rejection. No real labels/accuracy or automatic public-access verification. run_nike.py is a bounded raster example; complete-scene tiled inference and core merging remain the integration task before final patch filtering and whole-scene statistics. grid.py's partial-tile skipping and sampled valid fraction are documented, not changed.

Frontend should consume georeferenced outputs; this package does not add HTTP/XYZ serving. Human park checks and confirmed entrances are still required before scoring public access.

## Publication status

Local Git push could not invoke credential manager (MSYS directory object access error), so no authenticated push occurred. The connected GitHub account reported push permission, but the subsequent create-tree tool call was rejected with "user rejected MCP tool call". No remote branch or PR was created by this work. docs/PULL_REQUEST.md contains the prepared description and manual publish command. No alternate publication was attempted after the rejection.

## 2026-10-25 — Full-scene completion pass (local only)

Added analyse_scene/windows/exclude_context/evaluate_mask and a --all entry point. Processed all three source TIFFs, keeping partial edges and merging before global 300m2 filtering. Cached OSM buildings/residential/private polygons are now applied automatically, with disjoint removal areas and incomplete-context coverage reported. Native grid, valid counts and artifact hashes checked from real outputs. 27 synthetic tests passed. Prepared 51 draft inspection points; real reviewed labels remain zero.

Results: Theos00 473661.50 m2; Theos01 2796586.50 m2; Theos02 621733.25 m2 candidate vegetation after mapped exclusions and patch filtering. These cover all valid source pixels, unlike earlier polygon-AOI figures. Results remain unvalidated.

Park desk checks: row-476 has registry photograph and Dec 2025 street-view context from prior desk check; row-35 source Maps short link resolves to the same coordinate, but direct Street View query returns no imagery. Neither has independently confirmed current access/entrance. Original reference positions preserved. See FULL-SCENE-METHODS-th.md and Output/nike-scenes-20261025/checks.json.

No GitHub push, remote branch creation, PR or merge attempted. Existing local grid.py edit remains untouched and outside Nike commits.

OSM context snapshots were formatted to one GeoJSON feature per line to keep code reviews manageable; parsed JSON content was checked unchanged. Exact pre-format input bytes used for the actual runs remain recoverable in local commit 1817988, matching per-scene context_sha256. Formatting changed file hashes, not geometry or results; no duplicate full-scene run was performed for formatting alone. Exact module bytes matching every code_sha256 (8/8 modules per scene) were archived under each result's code-used/ folder.

### 2026-10-25 — Frontend contract and human review handoff
- Added export_frontend(): verifies completed input artifacts, writes EPSG:3857 RGBA previews with explicit WGS84 bounds, retains native-grid measurements and pending park status, and hashes exports.
- Exported all three scenes to Output/frontend-ready-20261025 plus zip; checked all hashes and unchanged area values. No external API or frontend framework added.
- Added prepare_label_review()/apply_label_review(): 42 blank decisions; explicit reviewer/date/notes required; uncertain withheld, original annotations preserved, splits retained.
- Added five tests; full suite 39 passed. Frontend integration contract tested locally; teammate frontend not available for end-to-end verification.
- grid.py hash unchanged; no GitHub push or PR.

### 2026-10-25 — Remove small noise before heatmap
- Added opt-in metric disk opening (2m in project config), then repeated global 300m2 area filtering and rebuilt all halos; no filling or added candidates.
- Cleaned all three saved full-scene masks with parent hashes, preserved old outputs. Areas: Theos00 473661.50 -> 439651.25 m2; Theos01 2796586.50 -> 2667583.00; Theos02 621733.25 -> 560430.00.
- Regenerated frontend-clean-20261025 package/zip, new final-clean-review page and before/after images. Full suite: 42 passed.
- Narrow real vegetation may also be removed. No semantic-accuracy or park-access claim; no GitHub publication.

### 2026-10-25 — Conservative residential eligibility
- User explicitly chose exclusion of ambiguous housing-context vegetation, accepting loss of public roadside/nearby green.
- Added configurable building/house/residential buffers (8/20/10m in project settings), 3m opening, and clipped all halos to exclusion mask.
- Added separate 42-core eligibility interpretations, including six residential-context vegetation exclusions; retained original vegetation labels, no invented public-park positive references or human review.
- Recomputed three native masks: 372643.00 / 2379871.75 / 451337.00 m2; verified no added candidates, preserved NoData and native area counts; sampled mapped-building cores for mask exclusion and alpha zero.
- Restored original cached-context bytes from Git plus matching newline/BOM variants and verified parent SHA256; archived context-used.geojson alongside outputs.
- Generated frontend-public-20261025 and final-public-review-20261025; full suite 43 passed. Mapping remains incomplete; no claim all private gardens are eliminated, no new ML accuracy claim, no remote publication.

### 2026-10-25 — User-corrected housing block
- Accepted user correction: green cores below the Theos00 airport apron sit within visible housing context and should not count under conservative public-green policy.
- Added source-grid WGS84 area-exclusions.geojson (assistant interpretation, unknown ownership) and reusable scene-specific policy exclusion in full-scene and cached processing.
- Removed core/halo in the polygon, preserved parent alpha exclusions, original vegetation labels and previous runs. Theos00 372643 -> 363144.25m2; other two scene areas unchanged.
- Rebuilt three-scene frontend handoff; 44 software tests passed. Not a claim that automatic private-yard detection is complete.

### 2026-10-25 — Full three-scene audit and authoritative handoff
- Re-ran all three original TIFFs twice as policies evolved; audited raw mask against every source window, all native counts, every retained component, NoData, exclusion core/alpha and hashes.
- Reviewed 432 paired source/overlay cells (12 contact sheets); added 86 conservative housing-cell exclusions with assistant provenance and explicit non-cadastral limits.
- User kept institutional/shared/resort/sports candidates as unverified and requested airport/rail green in a separate pending layer excluded from the main total.
- Added pending masks/RGBA, pixel-conservation checks, source-audit/catalog helper and optional frontend pending contract. Final main areas: 160152.75 / 2161651.25 / 305740.00 m2; pending: 180615.50 / 0 / 0 m2; 921 main components.
- Last successful unittest run: 46 passed, including pending/native/audit/frontend export tests. A later repeat was blocked before test execution by Windows denying the Python runtime even after read permission was granted; preserved the blocked log and separate test-status JSON.
- Audits passed for 1668988808 source positions including NoData, 108000000 valid pixels. Archived exact bytes for all 14 recorded code modules per scene and frozen input/config/policy snapshots.
- Updated README around the authoritative results, function usage, teammate handoff, reproducibility and remaining semantic limitations; no claims of real accuracy, public ownership or complete private-yard rejection.
- PowerShell verified every export hash, recorded code hash, all 921 catalog entries, three full audits and 51 report assets. No remote publication; grid.py user edit preserved.

### 2026-10-25 — Backend-only scope requested by user
- Removed active web-export module, HTML report generator, projected web bundles/ZIPs, HTML outputs, dedicated web docs and web-only tests. Retained the three human label-review tests in test_label_review.py.
- Deleted web files by explicit verified literal paths after computed-path bulk deletion was rejected by the approval policy. Source TIFFs, grid.py and native analysis/evidence outputs were preserved.
- run_all/clean_saved_results now write summary-all.json directly; no UI or HTML generation.
- Added find_parks_in_image()/verify_parks.py: district-metadata filtering plus all-band valid-pixel lookup; coordinates unchanged, no automatic public-access confirmation. Official reference is https://greener.bangkok.go.th/en/map-15-minute-garden/; local registry snapshot date stays 2026-10-23.
- User explicitly retained all three images as separate geographic cases. Don Mueang-filtered lookup: Theos00=2; Theos01=0; Theos02=0. Theos01 is outside Bangkok; no-match is not proof of no parks.
- Backend-only tests: 46 passed on installed Python 3.12.14 fallback runtime. Real TIFF 2000x2000 smoke + exhaustive audit passed with 4000000 valid pixels / 6597.75m2 candidate / no HTML. Rasterio emitted the expected non-georeferenced PNG-preview warning; native GeoTIFF audit passed.
- Rewrote README and backend handoff docs around functions, policies, outputs and explicit verification limits. Prior work-log entries describe historical scope, not active web functionality. No GitHub publication.

### 2026-10-25 — Organized backend handoff and English README
- Reorganized 45 files/folders without changing image or saved analysis bytes. Data now separates registry, assistant/human labels, policy polygons and visual-review decisions.
- Current reference results are Output/latest/{analysis,parks,smoke}; evidence/logs/older runs are separate. Kept Output/grid_2000 and grid.py at their existing team paths.
- Moved detailed method documents into docs/methods, old drafts into docs/archive, and the duplicate root label work log into docs/archive. Added concise documentation/data/output indexes.
- Renamed requirements-nike.txt to requirements.txt; updated active Python defaults, CLI output defaults, config and document links. New runs default under Output/runs rather than the saved reference folders.
- Rewrote README in simple English with six steps: install, inputs, detection/heatmaps, park lookup, output interpretation, testing/handoff. Preserved verification limits and backend-only scope.
- Checks: 46 tests passed; actual three-image registry lookup remained 2/0/0; real 2000x2000 TIFF smoke/audit passed with 4000000 valid pixels and 6597.75m2 candidate; all 24 saved native artifact hashes and 14 active document links checked.
- Frozen historical provenance is not rewritten. Output/layout-manifest.json maps old paths; Output/latest/index.json identifies saved reference snapshots. No GitHub publication.
