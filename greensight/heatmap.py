"""Render vegetation candidates and a fading proximity halo on their input grid."""
from numbers import Real
from typing import Literal, TypedDict

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.ndimage import distance_transform_edt, label, binary_opening, gaussian_filter


# Shared by the detection preview and heatmap: identical RGB and opacity.
CANDIDATE_RGBA = (0, 180, 65, 235)


class HeatmapResult(TypedDict):
    mask: NDArray[np.uint8]
    rgba: NDArray[np.uint8]
    stats: dict[str, int | float]


def _positive_number(value, name):
    if isinstance(value, bool) or not isinstance(value, Real) or not np.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return float(value)


def _filter_patches(mask, pixel_area, minimum_area):
    # Four edge-connected neighbours; diagonal contact cannot join two patches.
    components, count = label(mask == 1, structure=[[0, 1, 0], [1, 1, 1], [0, 1, 0]])
    sizes = np.bincount(components.ravel(), minlength=count + 1)
    sizes[0] = 0
    keep = sizes >= np.ceil(minimum_area / pixel_area)
    keep[0] = False
    filtered = mask.astype("uint8", copy=True)
    filtered[(mask == 1) & ~keep[components]] = 0
    original = int(sizes.sum())
    retained = int(sizes[keep].sum())
    stats = {
        "originalPatchCount": int(count),
        "retainedPatchCount": int(keep.sum()),
        "removedPatchCount": int(count - keep.sum()),
        "originalCandidatePixels": original,
        "retainedCandidatePixels": retained,
        "removedCandidatePixels": original - retained,
        "originalCandidateAreaM2": original * pixel_area,
        "retainedCandidateAreaM2": retained * pixel_area,
        "removedCandidateAreaM2": (original - retained) * pixel_area,
        "largestRetainedPatchM2": float(sizes[keep].max() * pixel_area) if keep.any() else 0.0,
    }
    return filtered, stats


def make_heatmap(
    mask: ArrayLike,
    pixel_m: float,
    min_area_m2: float = 300,
    radius_m: int = 50,
    *,
    style: Literal["red", "spectrum", "grid", "density", "proximity"] = "red",
    clean_radius_m: float = 0,
) -> HeatmapResult:
    """Return filtered mask, RGBA uint8 image and patch-area statistics.

    mask is a non-empty 2-D class array: 0=other, 1=candidate vegetation,
    2=uncertain, 255=NoData/outside frame. Pixels must be square and in metres.
    Merge sliding-window cores before calling. Inputs are never modified.
    Density style shows smoothed local vegetation occupancy (blue to red).
    Proximity style paints green/yellow/red across valid coverage. The
    class mask and measured areas do not change with style. This function does
    not classify imagery, reject roofs or verify public parks.
    """
    pixel_m = _positive_number(pixel_m, "pixel_m")
    minimum = _positive_number(min_area_m2, "min_area_m2")
    pixel_area = pixel_m * pixel_m
    if not np.isfinite(pixel_area) or pixel_area == 0:
        raise ValueError("pixel_m squared must be finite and positive")
    if isinstance(radius_m, bool) or not isinstance(radius_m, (int, np.integer)) or not 10 <= radius_m <= 500:
        raise ValueError("radius_m must be an integer from 10 to 500 metres")
    if style not in ("red", "spectrum", "grid", "density", "proximity"):
        raise ValueError("style must be red, spectrum, grid, density or proximity")
    source = np.asarray(mask)
    if source.ndim != 2 or not all(source.shape) or not np.isin(source, [0, 1, 2, 255]).all():
        raise ValueError("mask must be non-empty, 2-D and contain only 0, 1, 2, 255")

    if isinstance(clean_radius_m, bool) or not isinstance(clean_radius_m, Real) or not np.isfinite(clean_radius_m) or not 0 <= clean_radius_m <= 10:
        raise ValueError("clean_radius_m must be finite from 0 to 10 metres")
    cleaned = source.copy()
    if clean_radius_m:
        pixels = int(np.ceil(clean_radius_m / pixel_m))
        if pixels > 64:
            raise ValueError("Cleanup kernel exceeds 64-pixel radius")
        yy, xx = np.ogrid[-pixels:pixels+1, -pixels:pixels+1]
        disk = (xx*pixel_m)**2 + (yy*pixel_m)**2 <= clean_radius_m**2
        opened = binary_opening(source == 1, structure=disk) & (source == 1)
        cleaned[(source == 1) & ~opened] = 0
    filtered, stats = _filter_patches(cleaned, pixel_area, minimum)
    input_pixels = int((source == 1).sum())
    stats.update(cleanRadiusM=float(clean_radius_m), inputCandidatePixels=input_pixels,
                 morphologyRemovedPixels=int(((source == 1) & (cleaned != 1)).sum()),
                 totalRemovedFromInputM2=(input_pixels-stats["retainedCandidatePixels"])*pixel_area)
    rgba = np.zeros((*filtered.shape, 4), dtype="uint8")
    seeds = filtered == 1
    if style == "proximity":
        # Paint every valid cell: green at vegetation, yellow midway, red far.
        # Far means >= radius_m; this is straight-line distance, not walking time.
        if seeds.any():
            distance = distance_transform_edt(~seeds, sampling=(pixel_m, pixel_m))
            fraction = np.clip(distance / radius_m, 0, 1)
            valid = filtered != 255
            stops = [0, 0.16, 0.32, 0.5, 0.7, 0.86, 1]
            # Chartreuse/olive-yellow and warm orange bridge green to red.
            palette = np.array([CANDIDATE_RGBA[:3], [155,190,60], [185,185,65],
                                [255,225,40], [250,155,35], [245,95,28], [235,45,35]])
            for channel in range(3):
                rgba[valid, channel] = np.round(np.interp(fraction[valid], stops, palette[:, channel])).astype('uint8')
            rgba[valid, 3] = np.round(235 - 50 * fraction[valid]).astype('uint8')
            rgba[seeds] = CANDIDATE_RGBA
        return {"mask": filtered, "rgba": rgba, "stats": stats}
    if style == "density":
        # Fixed 0..1 local vegetation occupancy, not per-image maximum scaling.
        # Gaussian support is three sigma (= radius_m), measured in metres.
        density = gaussian_filter(seeds.astype('float32'), sigma=radius_m / (3 * pixel_m),
                                  mode='constant', cval=0, truncate=3)
        strength = np.sqrt(np.clip(density, 0, 1))
        visible = (filtered != 255) & (strength >= 0.02)
        stops = [0, 0.25, 0.5, 0.75, 1]
        palette = np.array([[45, 45, 190], [0, 185, 250], [0, 210, 110],
                            [255, 235, 45], [235, 35, 25]])
        for channel in range(3):
            rgba[visible, channel] = np.round(np.interp(strength[visible], stops, palette[:, channel])).astype('uint8')
        # Smoothly fade sparse vegetation to transparent; keep the source visible.
        fade = np.clip((strength[visible] - 0.02) / 0.25, 0, 1)
        rgba[visible, 3] = np.round(200 * fade * fade * (3 - 2 * fade)).astype('uint8')
        return {"mask": filtered, "rgba": rgba, "stats": stats}
    if seeds.any():
        distance = distance_transform_edt(~seeds, sampling=(pixel_m, pixel_m)).astype("float32")
        ring = (distance < radius_m) & (filtered != 255)
        fraction = distance[ring] / radius_m
        if style == "grid":
            fraction = (np.minimum((fraction * 5).astype("int16"), 4) + 0.5) / 5
        taper = 1 - fraction * fraction * (3 - 2 * fraction)
        if style == "red":
            rgba[ring, 0] = 255
            rgba[ring, 1] = (50 + 150 * fraction).astype("uint8")
            rgba[ring, 2] = (40 + 160 * fraction).astype("uint8")
            rgba[ring, 3] = np.round(170 * np.exp(-4.5 * fraction * fraction) * taper).astype("uint8")
        else:
            stops = [0, 0.25, 0.5, 0.75, 1]
            palette = np.array([[235, 67, 53], [253, 174, 70], [255, 235, 120], [110, 191, 114], [50, 136, 189]])
            for channel in range(3):
                rgba[ring, channel] = np.round(np.interp(fraction, stops, palette[:, channel])).astype("uint8")
            rgba[ring, 3] = np.round(190 * taper).astype("uint8")
    rgba[seeds] = CANDIDATE_RGBA
    return {"mask": filtered, "rgba": rgba, "stats": stats}
