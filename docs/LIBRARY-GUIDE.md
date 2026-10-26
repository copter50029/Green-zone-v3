# GreenSight library guide

All 13 source files in `greensight/`. Run the workflow with `run_backend.cmd`; do not run each library file separately. For setup, see [README](../README.md).

## Files and functions

| File | Functions / contents | Purpose and inputs → outputs | Used by / when to edit |
| --- | --- | --- | --- |
| [__init__.py](../greensight/__init__.py) | Public imports and `__all__` | Exposes common functions through `from greensight import ...`; starts no processing | Other backend code. Edit when adding public exports |
| [detect.py](../greensight/detect.py) | `detect_green()` | Source band array + band numbers + validity/exclusion masks → experimental vegetation class mask | `scene`, `audit`. Edit pixel classification rules |
| [heatmap.py](../greensight/heatmap.py) | `make_heatmap()`; `HeatmapResult`; internal `_positive_number()`, `_filter_patches()` | Merged mask + pixel size + minimum area + radii/style → cleaned mask, RGBA colours and area/count statistics | `scene`, `pending`, `cleanup`. Edit fragment filtering or halo colours |
| [exclusions.py](../greensight/exclusions.py) | `exclude_context()`, `exclude_policy_areas()` | Mask + mapped building/residential/private polygons or scene-specific policy polygons + grid → filtered mask, blocked-area mask and context report | `scene`, `cleanup`, `audit`. Edit tag/buffer rules; change specific polygons in data |
| [pending.py](../greensight/pending.py) | `separate_pending()`, `write_pending()` | Heatmap result + pending-zone policy + grid → main result, pending mask, amber layer and area report; writes pending TIFFs | `scene`, `cleanup`. Edit restricted-area partition logic |
| [scene.py](../greensight/scene.py) | `analyse_scene()`; utilities `windows()`, `digest()`, `read_json()`, `write_json()` | TIFF + settings/reference paths → per-scene summary and saved masks, heatmap, PNG previews, review tasks, hashes/status. Utilities handle windows, SHA256 and JSON | `run_nike.run_all()` and shared helpers. Edit processing order or saved outputs |
| [park_lookup.py](../greensight/park_lookup.py) | `find_parks_in_image()`; constants `REFERENCE_PAGE`, `DON_MUEANG` | TIFF + local point registry + optional district → GeoJSON points on valid pixels in every band, exclusion counts and provenance | `verify_parks.py`. Edit district/point-in-image checks |
| [park_verify.py](../greensight/park_verify.py) | `prepare_park_review()`, `record_park_review()`; internal `_coordinates()`, `_date()` | Registry + candidate mask/grid → review tasks with nearby-green metrics and map links. Task + human decision/evidence → updated copy with review history. Caller saves results | `scene`, `cleanup`, human-review code. Edit evidence/review rules |
| [audit.py](../greensight/audit.py) | `audit_scene()` | Completed analysis folder + original TIFF + matching context/policies → consistency report; writes `audit.json` and patch catalog | `run_backend.py`. Edit checks for hashes, grids, pixels, exclusions and area conservation |
| [cleanup.py](../greensight/cleanup.py) | `clean_saved_results()` | Existing merged results + matching references + cleanup settings → new filtered outputs and summaries, preserving parent results | Optional cleanup experiments without rereading source radiometry. Edit saved-result reprocessing |
| [labels.py](../greensight/labels.py) | `validate_labels()` | Assistant vegetation annotations + original image directory + optional crop evidence → structural QA report: alignment, IDs, overlap, split spacing and hashes | Label preparation. Edit annotation/schema checks; not a human-truth validator |
| [label_review.py](../greensight/label_review.py) | `prepare_label_review()`, `apply_label_review()` | Assistant labels → blank review queue; labels + completed human decisions → separate train/validation/test collections. Caller saves results | Human annotation review. Edit review fields; blank/uncertain decisions stay withheld |
| [evaluate.py](../greensight/evaluate.py) | `evaluate_mask()` | Prediction mask + matching independent human-reviewed test polygons + grid → confusion counts, quality/coverage metrics, or not-ready status | Evaluation after references exist. Edit metrics; does not train models |

## Processing order

```text
run_backend.py
  → run_nike.run_all() → scene.analyse_scene()
      → detect → exclusions → heatmap → pending → park_verify.prepare_park_review()
  → verify_parks.py → park_lookup.find_parks_in_image()
  → audit.audit_scene()
```

`cleanup`, label tools, evaluation and human park decisions are separate tools, not automatic steps. `__pycache__/` and `.tmp-nike/` are not library source modules to run.

## Data rules and limits

- Arrays: bands `(B,H,W)`, mask `(H,W)`, returned RGBA `(H,W,4)`. Band numbers are **one-based**.
- Mask: `0=other`, `1=candidate`, `2=uncertain`, `255=NoData/outside frame`.
- GeoJSON: WGS84 `[longitude, latitude]`. Raster grid/CRS comes from the TIFF; areas use square metres. Heatmap pixels must be square and metric.
- Current full-run settings: minimum patch **300 m²**, opening radius **3 m**, building/house/residential buffers **8/20/10 m**. Change these in `data/scenes.json`; low-level defaults can differ.
- Merge windows before patch filtering. Halo distance is straight-line proximity, not temperature or 15-minute walking access.
- Registry lookup uses cached data and preserves coordinates. Nearby greenery does not prove a public park. Human verification needs position and access evidence; code checks record completeness, not evidence truth.
- Detection uses an experimental band ratio, not a trained ML model. Labels/audits passing does not establish real accuracy. Run audits without Python `-O`.

## Usage

```python
from run_backend import run_backend
result = run_backend()  # All automatic steps; new timestamped output folder.
```

Outputs: `Output/runs/<timestamp>/analysis/<scene>/`, `parks/`, combined `summary.json` and `status.json`. Open PNG previews or overlay TIFF/park GeoJSON in QGIS; PNGs do not contain park markers.

Keep reusable code in `greensight/`, settings/reference data in `data/`, entry points at the root and tests in `tests/`. Use `<run>/analysis` as the input to saved-result cleanup; it does not create a fresh raw mask for full-source audits.
