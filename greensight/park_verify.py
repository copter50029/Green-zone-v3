"""Prepare evidence for park verification; vegetation proximity is not proof."""
from copy import deepcopy
from datetime import date
import hashlib
import json
import math
from numbers import Real
from urllib.parse import urlencode, urlsplit

import numpy as np
from rasterio.crs import CRS
from rasterio.transform import Affine, rowcol
from rasterio.warp import transform as reproject


def _coordinates(value):
    try:
        lon, lat = map(float, value)
        if math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90:
            return [lon, lat]
    except (ValueError, TypeError):
        pass
    raise ValueError("Expected finite WGS84 longitude,latitude")


def _date(value):
    if value is not None:
        date.fromisoformat(value)
    return value


def prepare_park_review(
    registry, mask, transform, crs, *, scene_id,
    search_radius_m=50, imagery_date=None,
):
    """Return GeoJSON review tasks for registry points on valid image pixels.

    registry is WGS84 point GeoJSON. mask uses 0/1/2/255; class 1 is candidate
    vegetation, 255 marks NoData AND everything outside the study frame.
    Distances refer to candidate cell centres inside a bounded search circle.
    No result is automatically a verified park, entrance or public-access claim.
    """
    if registry.get("type") != "FeatureCollection" or not isinstance(registry.get("features"), list):
        raise ValueError("registry must be a GeoJSON FeatureCollection")
    if not isinstance(scene_id, str) or not scene_id.strip():
        raise ValueError("scene_id is required")
    if registry.get("sceneId", scene_id) != scene_id:
        raise ValueError("Registry and mask scene IDs must match")
    values = np.asarray(mask)
    if values.ndim != 2 or not all(values.shape) or not np.isin(values, [0, 1, 2, 255]).all():
        raise ValueError("mask must be non-empty, 2-D and use only 0,1,2,255")
    values = values.astype("uint8", copy=False)
    grid = transform if isinstance(transform, Affine) else Affine(*transform[:6])
    projection = CRS.from_user_input(crs)
    if not projection.is_projected or not math.isclose(projection.linear_units_factor[1], 1):
        raise ValueError("A projected CRS with metre units is required")
    if not all(math.isfinite(v) for v in list(grid)[:6]) or grid.b != 0 or grid.d != 0 or grid.a <= 0 or grid.e >= 0:
        raise ValueError("Expected a north-up metric raster grid")
    if isinstance(search_radius_m, bool) or not isinstance(search_radius_m, Real) or not math.isfinite(search_radius_m) or not 0 < search_radius_m <= 500:
        raise ValueError("search_radius_m must be finite and in (0,500]")
    _date(imagery_date)
    source = registry.get("source") or {}
    snapshot_date = _date(source.get("snapshotDate"))
    provenance = {
        "scene_id": scene_id,
        "mask_sha256": hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest(),
        "mask_shape": list(values.shape),
        "registry_sha256": hashlib.sha256(json.dumps(registry, sort_keys=True).encode()).hexdigest(),
        "transform": list(grid)[:6], "crs": projection.to_string(),
        "search_radius_m": float(search_radius_m), "imagery_date": imagery_date,
        "registry_snapshot_date": snapshot_date,
    }
    analysis_id = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()[:24]
    height, width = values.shape
    pixel_area = abs(grid.a * grid.e)
    tasks, excluded, seen = [], [], set()
    for index, feature in enumerate(registry["features"], start=1):
        props = feature.get("properties") or {}
        identity = str(feature.get("id") or props.get("id") or f"reference-{index}")
        if identity in seen:
            raise ValueError("Registry IDs must be unique for traceable reviews")
        seen.add(identity)
        geometry = feature.get("geometry") or {}
        try:
            if geometry.get("type") != "Point":
                raise ValueError("Point references required")
            lon, lat = _coordinates(geometry.get("coordinates"))
            xs, ys = reproject("EPSG:4326", projection, [lon], [lat])
            x, y = xs[0], ys[0]
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("Projection failed")
            row, col = rowcol(grid, x, y)
        except (ValueError, TypeError):
            excluded.append({"id": identity, "reason": "invalid_reference_geometry"})
            continue
        if not (0 <= row < height and 0 <= col < width):
            excluded.append({"id": identity, "reason": "outside_mask_grid"})
            continue
        if values[row, col] == 255:
            excluded.append({"id": identity, "reason": "nodata_or_outside_study_frame"})
            continue

        half_rows = math.ceil(search_radius_m / abs(grid.e)) + 1
        half_cols = math.ceil(search_radius_m / grid.a) + 1
        r0, r1 = row - half_rows, row + half_rows + 1
        c0, c1 = col - half_cols, col + half_cols + 1
        if (r1 - r0) * (c1 - c0) > 4_100_000:
            raise ValueError("Search window exceeds the pixel budget; use a smaller radius")
        # Padding remains NoData so missing/outside coverage is not hidden.
        window = np.full((r1 - r0, c1 - c0), 255, dtype="uint8")
        top, bottom, left, right = max(0, r0), min(height, r1), max(0, c0), min(width, c1)
        window[top - r0:bottom - r0, left - c0:right - c0] = values[top:bottom, left:right]
        rr, cc = np.ogrid[r0:r1, c0:c1]
        squared = (grid.c + (cc + 0.5) * grid.a - x) ** 2 + (grid.f + (rr + 0.5) * grid.e - y) ** 2
        circle = squared <= search_radius_m ** 2
        valid = circle & (window != 255)
        candidates = valid & (window == 1)
        candidate_count = int(candidates.sum())
        valid_count = int(valid.sum())
        circle_count = int(circle.sum())
        coordinate = f"{lat:.7f},{lon:.7f}"
        tasks.append({
            "type": "Feature", "id": identity,
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "registry_id": identity, "scene_id": scene_id, "analysis_id": analysis_id,
                "name": str(props.get("name", "")),
                "registry_properties": deepcopy(props),
                "review_status": "needs_review", "verified_park": False,
                "position_confirmed": False, "public_access_confirmed": False,
                "evidence": [], "review_history": [],
                "imagery_date": imagery_date, "registry_snapshot_date": snapshot_date,
                "different_years_need_review": bool(imagery_date and snapshot_date and imagery_date[:4] != snapshot_date[:4]),
                "nearest_candidate_cell_m": float(np.sqrt(squared[candidates].min())) if candidate_count else None,
                "candidate_area_m2_in_search": candidate_count * pixel_area,
                "valid_area_m2_in_search": valid_count * pixel_area,
                "valid_search_fraction": valid_count / circle_count if circle_count else None,
                "candidate_fraction_of_valid": candidate_count / valid_count if valid_count else None,
                "candidate_within_search": bool(candidate_count),
                "search_radius_m": float(search_radius_m),
                "google_maps": "https://www.google.com/maps/search/?" + urlencode({"api": 1, "query": coordinate}),
                "street_view": "https://www.google.com/maps/@?" + urlencode({"api": 1, "map_action": "pano", "viewpoint": coordinate}),
                "source_url": props.get("sourceUrl") or source.get("url"),
            },
        })
    return {
        "type": "FeatureCollection", "sceneId": scene_id, "analysis_id": analysis_id,
        "features": tasks, "excluded_references": excluded, "provenance": provenance,
        "limitations": [
            "Vegetation near a registry point does not establish a matching public park or entrance.",
            "Nearest distance is bounded by the search circle and measured to cell centres, not globally to park boundaries.",
            "Areas use pixel-centre membership; missing coverage and image/registry dates require review.",
            "Snapshot date is not a park opening date. No candidate is not proof of no park.",
        ],
    }


def record_park_review(
    task, *, reviewer, reviewed_on, decision, evidence,
    position_confirmed=False, public_access_confirmed=False, notes="",
):
    """Record a person's decision; check completeness, not truth of their evidence.

    No registry coordinate is moved and no image/model metric becomes evidence
    of public access automatically. Verified decisions require explicit checks
    and evidence covering both position and public_access.
    """
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("A named reviewer is required")
    if reviewed_on is None:
        raise ValueError("reviewed_on is required")
    _date(reviewed_on)
    if decision not in ("needs_review", "verified_park", "rejected"):
        raise ValueError("Unknown review decision")
    if type(position_confirmed) is not bool or type(public_access_confirmed) is not bool:
        raise ValueError("Confirmation flags must be booleans")
    scopes = set()
    if not isinstance(evidence, list):
        raise ValueError("Evidence must be a list")
    for item in evidence:
        url = urlsplit(item.get("url", ""))
        if url.scheme != "https" or not url.netloc or url.username or url.password:
            raise ValueError("Evidence requires an HTTPS URL without credentials")
        _date(item.get("observed_on"))
        if not item.get("observed_on"):
            raise ValueError("Evidence observation date is required")
        item_scopes = item.get("scopes", [])
        if not isinstance(item_scopes, list) or not item_scopes or not set(item_scopes) <= {"position", "public_access"}:
            raise ValueError("Evidence scopes must identify position and/or public_access")
        scopes.update(item_scopes)
    if decision == "verified_park" and not (
        position_confirmed and public_access_confirmed and scopes >= {"position", "public_access"}
    ):
        raise ValueError("Verified park requires explicit position/access checks and supporting evidence")
    if decision == "rejected" and (not evidence or not str(notes).strip()):
        raise ValueError("Rejection requires evidence and an explanation")
    result = deepcopy(task)
    props = result["properties"]
    entry = {
        "reviewer": reviewer.strip(), "reviewed_on": reviewed_on, "decision": decision,
        "position_confirmed": position_confirmed, "public_access_confirmed": public_access_confirmed,
        "evidence": deepcopy(evidence), "notes": str(notes),
    }
    props.setdefault("review_history", []).append(entry)
    props.update(entry)
    props["review_status"] = decision
    props["verified_park"] = decision == "verified_park"
    return result


def write_park_preview(folder, tasks, transform, crs, mask_shape):
    """Write registry badges on source imagery, separate from detect and heatmap."""
    import rasterio
    with rasterio.open(folder / 'source.png') as src:
        image = np.moveaxis(src.read(), 0, -1).copy()
    height, width = image.shape[:2]
    glyphs = {'1': ['010','110','010','010','111'],
              '5': ['111','100','111','001','111']}
    for feature in tasks['features']:
        lon, lat = feature['geometry']['coordinates']
        xs, ys = reproject('EPSG:4326', crs, [lon], [lat])
        row, col = rowcol(transform, xs[0], ys[0])
        cx = int((col + 0.5) * width / mask_shape[1])
        cy = int((row + 0.5) * height / mask_shape[0])
        yy, xx = np.ogrid[:height, :width]
        distance = (xx - cx) ** 2 + (yy - cy) ** 2
        image[distance <= 100] = [255, 255, 255]
        image[distance <= 64] = [35, 110, 35]
        for digit, offset in (('1', -3), ('5', 1)):
            for r, line in enumerate(glyphs[digit]):
                for c, value in enumerate(line):
                    x, y = cx + offset + c, cy - 2 + r
                    if value == '1' and 0 <= x < width and 0 <= y < height:
                        image[y, x] = [255, 255, 255]
    with rasterio.open(folder / 'parks-map.png', 'w', driver='PNG', count=3,
                       width=width, height=height, dtype='uint8') as dst:
        dst.write(np.moveaxis(image, -1, 0))
