"""Experimental vegetation detection using explicitly selected source bands."""
import numpy as np


def detect_green(bands, *, red_band, nir_band, nodata=None, valid_mask=None,
                 exclude_mask=None, threshold=0.35, uncertain_threshold=0.15):
    """Return uint8: 0=other, 1=candidate, 2=uncertain, 255=NoData.

    bands shape is (bands,rows,columns); band numbers are one-based.
    Unverified bands/raw DN produce an experimental ratio, not calibrated NDVI.
    Roof/private-area exclusions require a bool mask on this same grid.
    """
    image = np.asarray(bands)
    if image.ndim != 3 or not all(image.shape) or image.dtype.kind not in "uif":
        raise ValueError("Expected a non-empty numeric (bands,rows,columns) array")
    if any(isinstance(b, (bool, np.bool_)) or not isinstance(b, (int, np.integer)) or not 1 <= b <= image.shape[0]
           for b in (red_band, nir_band)) or red_band == nir_band:
        raise ValueError("Use distinct one-based red_band and nir_band numbers")
    if not np.isfinite([threshold, uncertain_threshold]).all() or not -1 <= uncertain_threshold < threshold <= 1:
        raise ValueError("Require -1 <= uncertain_threshold < threshold <= 1")
    valid = np.isfinite(image).all(axis=0)
    if nodata is not None:
        valid &= (image != nodata).all(axis=0)
    for option, name in ((valid_mask, "valid_mask"), (exclude_mask, "exclude_mask")):
        if option is not None and (np.asarray(option).shape != valid.shape or np.asarray(option).dtype != bool):
            raise ValueError(f"{name} must be a boolean array matching the raster grid")
    if valid_mask is not None:
        valid &= valid_mask
    red, nir = image[[red_band - 1, nir_band - 1]].astype("float64")
    denominator = red + nir
    ratio = np.full(valid.shape, np.nan)
    np.divide(nir - red, denominator, out=ratio, where=valid & (denominator > 0))
    mask = np.full(valid.shape, 255, dtype="uint8")
    mask[valid] = 2
    mask[valid & (ratio < uncertain_threshold)] = 0
    mask[valid & (ratio >= threshold)] = 1
    if exclude_mask is not None:
        mask[valid & exclude_mask] = 0
    return mask
