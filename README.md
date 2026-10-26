# GreenSight — Nike Backend

Python functions for **green-area detection, heatmaps and park verification**. There is no frontend. The team's `grid.py` stays separate.

For a file-by-file explanation of every library module, its functions, inputs, outputs and callers, read the [Library guide](docs/LIBRARY-GUIDE.md).

## Quick start: run the whole backend once

After installing dependencies and placing the three TIFFs in `Images/`, run:

```powershell
.\run_backend.cmd
```

Or call Python directly (also works without activating the environment):

```powershell
.\.venv\Scripts\python.exe run_backend.py
```

This single entry point runs the existing functions in order:

1. Preflight: check all configured image, registry and context paths.
2. Detect green areas, remove configured noise/exclusions and create heatmaps for every scene.
3. Find Don Mueang registry points on valid image pixels for every scene.
4. Audit every source window, output grid, retained patch, area and artifact hash.
5. Write combined results and a completion status.

Output goes to a new timestamped folder under `Output/runs/`. No previous run is overwritten. Paths are resolved against this project folder, so the new entry point also works when launched from another working directory. The full audit rereads large TIFFs and can take time.

```text
Output/runs/<timestamp>/
  config.json              Resolved input settings used by this run
  status.json              running / complete / failed, with stage
  summary.json             Combined analysis, registry lookup and audits
  analysis/<scene>/        Masks, source.png, heatmap.png, park-review.geojson, audit.json
  parks/<scene>-parks.geojson
  parks/summary.json
```

Open `source.png` and `heatmap.png` to inspect the images. In QGIS, overlay the original TIFF, `heatmap.tif` and the matching `parks/<scene>-parks.geojson` to inspect park positions. PNG previews do not contain park markers.

Optional arguments:

```powershell
.\run_backend.cmd --output Output/runs/team-review-01
.\run_backend.cmd --all-districts
.\run_backend.cmd --config data/scenes.json
```

For another backend developer:

```python
from run_backend import run_backend
result = run_backend()  # Returns summaries; saves all outputs.
```

The existing functions and commands below remain available. `.tmp-nike/` contains local experiment helpers, not required pipeline steps. Do not run every Python file: label creation/review, historical cleanup and `grid.py` are separate tools. Human park confirmation is never automated. Tests are a separate development check, not rerun on every large analysis.

## 1. Install

Run from the repository root. Use Python 3.10 or newer; the backend is tested with Python 3.12.14.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If an old environment points to a missing Python installation, create a new environment with an installed Python version.

## 2. Prepare the inputs

Place `Theos00.tif`, `Theos01.tif` and `Theos02.tif` in `Images/`. Check their paths and settings in **`data/scenes.json`**.

The images cover different places. Theos00 covers the Don Mueang airport area. Theos01 is outside Bangkok. Theos02 is another footprint. Do not treat all three as the whole Don Mueang district.

## 3. Run detection and heatmaps

```powershell
.\.venv\Scripts\python.exe run_nike.py --all --output Output/runs/my-analysis
```

Choose a new output folder each time. Existing results are not overwritten.

```python
from run_nike import run_all

results = run_all(out_dir='Output/runs/my-analysis')
print(results[0]['stats']['retainedCandidateAreaM2'])
```

The pipeline:

1. Read 512 × 512 windows, including edges, and check every band for valid data.
2. Build an experimental vegetation mask and merge windows.
3. Remove mapped buildings, residential/private areas and visual housing-policy exclusions.
4. Remove narrow fragments with a 3 m opening filter; keep connected patches of at least **300 m²**.
5. Separate the identified airport/rail area into a pending layer, excluded from the main total.
6. Save heatmaps, areas, source hashes and park-review tasks.

Current buffers are 8 m around buildings, 20 m around mapped houses and 10 m around residential polygons. They are screening settings, not property boundaries, and can also remove shared greenery near homes.

Change `min_area_m2` in the configuration to focus on larger patches. Green means **candidate vegetation**. The halo shows straight-line proximity, not temperature or walking distance. Amber marks pending review.

## 4. Find registered parks

Reference: [Greener Bangkok park map](https://greener.bangkok.go.th/en/map-15-minute-garden/). The local registry is a snapshot from 23 October 2026, not a live list of entrances or opening conditions.

```powershell
# Don Mueang registry points, checked against all three images
.\.venv\Scripts\python.exe verify_parks.py --output Output/runs/my-park-check

# Optional: include all registry districts
.\.venv\Scripts\python.exe verify_parks.py --all-districts --output Output/runs/all-park-check
```

```python
from greensight import find_parks_in_image

parks = find_parks_in_image('Images/Theos00.tif', district='don-mueang')
print(len(parks['features']))
```

A point must fall on valid pixels in **every band**. Coordinates are not moved to match greenery.

The saved Don Mueang lookup found 2 points in Theos00 and 0 matching points in the other images. Zero matches does **not** mean no parks exist. District filtering uses registry metadata, not an official district-boundary polygon.

Finding a point is not verification. Use `prepare_park_review()` and `record_park_review()` to collect a real reviewer's position and public-access evidence. Found points start as `needs_review` and `verified_park=false`.

## 5. Read the results

| File | Meaning |
| --- | --- |
| `raw-mask.tif` | Experimental classes on the original grid |
| `candidate-mask.tif` | Main result after exclusions and cleanup |
| `heatmap.tif` | Georeferenced RGBA heatmap |
| `source.png`, `heatmap.png` | Visual previews; do not measure area from them |
| `pending-mask.tif`, `pending.tif` | Separate review layer, excluded from the main total |
| `park-review.geojson` | Registry points and review tasks |
| `summary.json`, `status.json` | Areas, settings, hashes and run status |

`summary-all.json` combines the scene summaries. Audits add `audit.json` and `patch-review-catalog.json`.

Mask values: `0=other`, `1=candidate`, `2=uncertain`, `255=NoData`. Area is measured on the native grid. Merge windows before filtering patches; do not filter separate tiles and add their areas.

## 6. Test and continue development

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The unified runner validation passed 48 backend tests, including a three-scene integration run. A real 2,000 x 2,000 TIFF also passed analysis, registry lookup and the full consistency audit through the new entry point. Full-size processing of all three original TIFFs was not repeated for this orchestration change. A real 2,000 ? 2,000 TIFF smoke test also passed its pixel, grid and area audit. Configuration paths, documentation links and saved artifact hashes were checked.

```text
greensight/             Backend functions
run_backend.py          Unified analysis + park lookup + audit entry point
run_backend.cmd         Windows launcher
run_nike.py             Existing analysis-only entry point
verify_parks.py         Park lookup entry point
requirements.txt        Python dependencies
data/scenes.json        Shared configuration
data/registry/          Cached park references
data/exclusions/        Cached building/residential context
data/labels/assistant/  Assistant interpretations, not human ground truth
data/labels/human/      Independent references; currently empty
data/labels/policies/   Housing exclusions and pending zones
data/labels/review/     Visual-context review decisions
tests/                  Software tests
docs/                   Guides, methods and history
Images/                 Local TIFFs
Output/latest/          Saved analysis, park lookup and smoke test
Output/evidence/        Label crops and review images
Output/logs/            Current and historical logs
Output/archive/         Earlier experiments and records
Output/runs/            New runs
Output/grid_2000/       Team grid output; original path preserved
```

`latest/` contains saved reference runs, not automatically updated aliases. New runs do not replace them. `Output/latest/index.json` lists them. `Output/layout-manifest.json` maps old paths to new locations; historical provenance is not rewritten.

For small arrays, import `detect_green` and `make_heatmap` from `greensight`. For full images, prefer `run_all()` so all configured policies are applied.

## Important limits

- Results are **candidates**, not confirmed public parks or land approved for planting.
- Incomplete context can miss private vegetation; conservative exclusions can also remove too much.
- Trees inside homes are still vegetation. Park eligibility stays separate from vegetation truth.
- Band identity/calibration is not fully verified. The detector uses an experimental raw-band ratio, not a trained ML model.
- There are no independently human-reviewed labels or real accuracy scores yet. Software tests do not measure detection accuracy.
- TIFFs and generated results are local and ignored by Git. Teammates need their own images. No API key is needed for the cached workflow.

Read the [documentation index](docs/README.md), [backend handoff](docs/BACKEND-HANDOFF-th.md), [data guide](data/README.md) and [work log](docs/WORKLOG.md). Old drafts are in `docs/archive/`.

Use a feature branch and request teammate review before merging changes. The unified runner does not change Git state or publish anything.
