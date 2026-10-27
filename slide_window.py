"""
GreenSight - GeoHackathon 2026 (Patched to align with main pipeline)

Multi-round sliding-window green-zone scan over the tiles made by grid.py.

  STEP A  Arrange the grid tiles back together (virtual mosaic - nothing is merged
          on disk). Reads grid_index.csv + the tiles/ folder written by grid.py.
  STEP B  ROUND 1: slide a 1200 x 1200 px window (1000 px core + 100 px margin each
          side, stride 1000) over the mosaic in scan order. For every window the
          green area is measured. Green patches that touch across ANY window seam
          are joined, so a garden cut by a seam is counted once, at its true size.
  STEP C  ROUNDS 2-4: the same scan again with LARGER windows
          (2400, 3600, 4800 px by default - core and margin grow together).

  Scan order (start_corner): UL = upper-left, sweep left->right, rows downward
  (default, "left to right, then next row"); UR = upper-right, sweep right->left,
  ends lower-left; LL / LR start at the bottom. The order changes only the order
  in which windows are visited and listed - never the result.

  detector="team" (default): the team's detect_green() NDVI ratio (threshold 0.35).
  detector="hybrid": NDVI + EVI per pixel (see make_hybrid_predictor).

Install:
    pip install rasterio numpy scipy pillow matplotlib
"""

import os
import csv
import json
import time
import ntpath
import tempfile
from datetime import datetime
from collections import OrderedDict
import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.transform import Affine
from rasterio.warp import transform as warp_transform, Resampling
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from PIL import Image

try:
    from greensight.detect import detect_green as greensight_detect_green
    from greensight.cleanup import clean_saved_results as clean_saved_results
except ImportError:  # pragma: no cover - fallback when run outside the repo root
    greensight_detect_green = None
    clean_saved_results = None

BLUE, GREEN, RED, NIR = 1, 2, 3, 4
NODATA_OUT = 255


def detect_green(bands, *, red_band, nir_band, nodata=None, valid_mask=None,
                 exclude_mask=None, threshold=0.35, uncertain_threshold=0.15):
    """Return uint8: 0=other, 1=candidate, 2=uncertain, 255=NoData."""
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
    mask = np.full(valid.shape, NODATA_OUT, dtype="uint8")
    mask[valid] = 2
    mask[valid & (ratio < uncertain_threshold)] = 0
    mask[valid & (ratio >= threshold)] = 1
    if exclude_mask is not None:
        mask[valid & exclude_mask] = 0
    return mask


# =================================================================
# Per-pixel indices
# =================================================================
def compute_ndvi_evi(nir, red, blue, scale_max, nodata=None):
    valid = np.ones(nir.shape, dtype=bool)
    if nodata is not None:
        valid = (nir != nodata) & (red != nodata) & (blue != nodata)

    denom = nir + red
    denom[denom == 0] = 1e-6
    ndvi = (nir - red) / denom

    n, r, b = nir / scale_max, red / scale_max, blue / scale_max
    evi_denom = n + 6.0 * r - 7.5 * b + 1.0
    evi_denom[np.abs(evi_denom) < 1e-6] = 1e-6
    evi = np.clip(2.5 * (n - r) / evi_denom, -1.0, 1.0)

    ndvi[~valid] = -1.0
    evi[~valid] = -1.0
    return ndvi, evi, valid


def combine_vegetation(ndvi, evi, valid, mode="and", ndvi_thr=0.3, evi_thr=0.2, w_ndvi=0.5):
    a, b = ndvi >= ndvi_thr, evi >= evi_thr
    if mode == "and":
        veg = a & b
    elif mode == "or":
        veg = a | b
    elif mode == "weighted":
        sa = np.clip(ndvi / ndvi_thr, 0, 1)
        sb = np.clip(evi / evi_thr, 0, 1)
        veg = (w_ndvi * sa + (1 - w_ndvi) * sb) >= 0.5
    else:
        raise ValueError("mode must be 'and', 'or' or 'weighted'")
    return veg & valid, a & valid, b & valid


def get_pixel_area_m2(src):
    if src.crs is not None and src.crs.is_geographic:
        raise ValueError("CRS is geographic (degrees). Reproject to a metric CRS.")
    t = src.transform
    return abs(t.a * t.e - t.b * t.d)


# =================================================================
# PASS 1 - sliding windows with overlap
# =================================================================
def read_window_padded(src, row0, col0, rows, cols, bands, fill):
    out = np.full((len(bands), rows, cols), fill, dtype="float32")
    r0, c0 = max(row0, 0), max(col0, 0)
    r1, c1 = min(row0 + rows, src.height), min(col0 + cols, src.width)
    if r1 > r0 and c1 > c0:
        data = src.read(bands, window=Window(c0, r0, c1 - c0, r1 - r0)).astype("float32")
        out[:, r0 - row0:r1 - row0, c0 - col0:c1 - col0] = data
    return out


def make_hybrid_predictor(nodata, scale_max=4095, ndvi_thr=0.3, evi_thr=0.2, mode="and"):
    def predict(win, exclude_mask=None):
        blue, red, nir = win[0], win[1], win[2]
        ndvi, evi, valid = compute_ndvi_evi(nir, red, blue, scale_max, nodata)
        green, _, _ = combine_vegetation(ndvi, evi, valid, mode, ndvi_thr, evi_thr)
        if exclude_mask is not None:
            green = green & ~exclude_mask
        return green, valid
    return predict


def make_team_predictor(nodata, threshold=0.35, uncertain_threshold=0.15, include_uncertain=False):
    def predict(win, exclude_mask=None):
        m = detect_green(win, red_band=2, nir_band=3, nodata=nodata,
                         exclude_mask=exclude_mask,
                         threshold=threshold, uncertain_threshold=uncertain_threshold)
        valid = m != NODATA_OUT
        green = (m == 1) | ((m == 2) if include_uncertain else False)
        return green, valid
    return predict


def _mask_profile(src):
    return dict(driver="GTiff", height=src.height, width=src.width, count=1, dtype="uint8",
                crs=src.crs, transform=src.transform, nodata=NODATA_OUT,
                compress="deflate", tiled=False, blockysize=8, BIGTIFF="YES")


def pass1_detect(src, raw_path, core, margin, predictor, smooth_iterations=6, log_every=10,
                 row_order=None, col_order=None, exclude_mask=None):
    H, W = src.height, src.width
    fill = src.nodata if src.nodata is not None else 0
    row_order = list(range(0, H, core)) if row_order is None else list(row_order)
    col_order = list(range(0, W, core)) if col_order is None else list(col_order)
    n_rows = len(row_order)
    t0 = time.time()
    with rasterio.open(raw_path, "w", **_mask_profile(src)) as dst:
        for k, r0 in enumerate(row_order, start=1):
            ch = min(core, H - r0)
            stripe = np.full((ch, W), NODATA_OUT, dtype="uint8")
            for c0 in col_order:
                cw = min(core, W - c0)
                win_r0, win_c0 = r0 - margin, c0 - margin
                win_h, win_w = ch + 2 * margin, cw + 2 * margin
                win = read_window_padded(src, win_r0, win_c0, win_h, win_w, [BLUE, RED, NIR], fill)
                
                win_exclude = None
                if exclude_mask is not None:
                    win_exclude = np.full((win_h, win_w), False, dtype=bool)
                    ex_r0, ex_c0 = max(win_r0, 0), max(win_c0, 0)
                    ex_r1, ex_c1 = min(win_r0 + win_h, H), min(win_c0 + win_w, W)
                    if ex_r1 > ex_r0 and ex_c1 > ex_c0:
                        win_exclude[ex_r0 - win_r0:ex_r1 - win_r0, ex_c0 - win_c0:ex_c1 - win_c0] = \
                            exclude_mask[ex_r0:ex_r1, ex_c0:ex_c1]

                green, valid = predictor(win, exclude_mask=win_exclude)
                if smooth_iterations:
                    green = ndimage.binary_opening(green, iterations=smooth_iterations) & valid
                g = green[margin:margin + ch, margin:margin + cw]
                v = valid[margin:margin + ch, margin:margin + cw]
                stripe[:, c0:c0 + cw] = np.where(v, np.where(g, 1, 0), NODATA_OUT)
            dst.write(stripe, 1, window=Window(0, r0, W, ch))
            if k % log_every == 0 or k == n_rows:
                el = time.time() - t0
                print(f"  pass 1: window row {k}/{n_rows}  ({el / 60:.1f} min, "
                      f"ETA {(el / k) * (n_rows - k) / 60:.1f} min)")


# =================================================================
# PASS 2 - exact patches across ALL seams
# =================================================================
def pass2_patches(raw_path, stripe_rows, log_every=20):
    with rasterio.open(raw_path) as src:
        H, W = src.height, src.width
        cols = np.arange(W, dtype=np.float64)
        stats, offsets, edges = [], [], []
        total, prev_bottom, nodata_px = 0, None, 0
        t0 = time.time()
        n_stripes = -(-H // stripe_rows)
        for k, r0 in enumerate(range(0, H, stripe_rows), start=1):
            h = min(stripe_rows, H - r0)
            raw = src.read(1, window=Window(0, r0, W, h))
            nodata_px += int((raw == NODATA_OUT).sum())
            lab, n = ndimage.label(raw == 1)
            offsets.append(total)
            if n:
                cnt = np.zeros(n + 1); sr = np.zeros(n + 1); sc = np.zeros(n + 1)
                srr = np.zeros(n + 1); scc = np.zeros(n + 1); src_ = np.zeros(n + 1)
                for b0 in range(0, h, 32):
                    L = lab[b0:b0 + 32]
                    if not L.any():
                        continue
                    lf = L.ravel()
                    rr = np.broadcast_to((r0 + b0 + np.arange(L.shape[0], dtype=np.float64))[:, None],
                                         L.shape).ravel()
                    cc = np.broadcast_to(cols, L.shape).ravel()
                    cnt += np.bincount(lf, minlength=n + 1)
                    sr += np.bincount(lf, weights=rr, minlength=n + 1)
                    sc += np.bincount(lf, weights=cc, minlength=n + 1)
                    srr += np.bincount(lf, weights=rr * rr, minlength=n + 1)
                    scc += np.bincount(lf, weights=cc * cc, minlength=n + 1)
                    src_ += np.bincount(lf, weights=rr * cc, minlength=n + 1)
                stats.append(np.stack([cnt[1:], sr[1:], sc[1:], srr[1:], scc[1:], src_[1:]], axis=1))
                top = np.where(lab[0] > 0, lab[0] + total, 0)
                bottom = np.where(lab[-1] > 0, lab[-1] + total, 0)
            else:
                top = bottom = np.zeros(W, dtype=np.int64)
            if prev_bottom is not None:
                m = (prev_bottom > 0) & (top > 0)
                if m.any():
                    edges.append(np.unique(np.stack([prev_bottom[m], top[m]], axis=1), axis=0))
            prev_bottom = bottom
            total += n
            if k % log_every == 0 or k == n_stripes:
                el = time.time() - t0
                print(f"  pass 2: stripe {k}/{n_stripes}, {total:,} partial patches "
                      f"({el / 60:.1f} min)")

    S = np.concatenate(stats) if stats else np.zeros((0, 6))
    N = len(S)
    if edges:
        e = np.concatenate(edges) - 1
        graph = coo_matrix((np.ones(len(e), dtype=np.int8), (e[:, 0], e[:, 1])), shape=(N, N))
        n_roots, comp = connected_components(graph, directed=False)
    else:
        n_roots, comp = N, np.arange(N)
    return {"stats": S, "comp": comp, "n_roots": n_roots, "offsets": np.array(offsets),
            "nodata_px": nodata_px, "H": H, "W": W}


def decide_noise(res, noise_elongation_thresh, noise_max_size, noise_min_absolute_size):
    S, comp, R = res["stats"], res["comp"], res["n_roots"]
    tot = np.stack([np.bincount(comp, weights=S[:, i], minlength=R) for i in range(6)], axis=1)
    n = tot[:, 0]
    nn = np.maximum(n, 1)
    mr, mc = tot[:, 1] / nn, tot[:, 2] / nn
    vrr = tot[:, 3] / nn - mr * mr
    vcc = tot[:, 4] / nn - mc * mc
    vrc = tot[:, 5] / nn - mr * mc
    half_tr = (vrr + vcc) / 2
    root = np.sqrt(np.maximum(half_tr ** 2 - (vrr * vcc - vrc ** 2), 0))
    lam_max = np.maximum(half_tr + root, 1e-6)
    lam_min = np.maximum(half_tr - root, 1e-6)
    elong = np.sqrt(lam_max / lam_min)
    remove = (n < noise_min_absolute_size) | ((n < noise_max_size) & (elong > noise_elongation_thresh))
    return {"count": n, "mean_r": mr, "mean_c": mc, "elong": elong, "remove": remove}


# =================================================================
# PASS 3 - write final mask
# =================================================================
def pass3_write(raw_path, final_path, res, decision, stripe_rows, log_every=20):
    node_remove = decision["remove"][res["comp"]]
    offsets = res["offsets"]
    with rasterio.open(raw_path) as src:
        H, W = src.height, src.width
        prof = _mask_profile(src)
        t0 = time.time()
        n_stripes = -(-H // stripe_rows)
        with rasterio.open(final_path, "w", **prof) as dst:
            for k, r0 in enumerate(range(0, H, stripe_rows), start=1):
                h = min(stripe_rows, H - r0)
                raw = src.read(1, window=Window(0, r0, W, h))
                lab, n = ndimage.label(raw == 1)
                if n:
                    lookup = np.zeros(n + 1, dtype=bool)
                    off = offsets[k - 1]
                    lookup[1:] = node_remove[off:off + n]
                    raw = np.where((raw == 1) & lookup[lab], 0, raw).astype("uint8")
                dst.write(raw, 1, window=Window(0, r0, W, h))
                if k % log_every == 0 or k == n_stripes:
                    print(f"  pass 3: stripe {k}/{n_stripes} ({(time.time() - t0) / 60:.1f} min)")


# =================================================================
# OUTPUTS
# =================================================================
def write_outputs(src, out_dir, res, decision, pixel_area_m2, raw_green_px,
                  min_report_m2, max_patches_csv, final_path, preview_px=2000):
    keep = ~decision["remove"]
    n = decision["count"]
    green_px = float(n[keep].sum())
    valid_px = res["H"] * res["W"] - res["nodata_px"]
    summary = {
        "image_px": [res["W"], res["H"]], "pixel_size_m": pixel_area_m2 ** 0.5,
        "valid_area_km2": valid_px * pixel_area_m2 / 1e6,
        "green_area_m2": green_px * pixel_area_m2,
        "green_area_rai": green_px * pixel_area_m2 / 1600.0,
        "green_area_ha": green_px * pixel_area_m2 / 1e4,
        "green_pct_of_valid": green_px / valid_px * 100.0 if valid_px else 0.0,
        "patches_kept": int(keep.sum()),
        "patches_removed_as_noise": int((~keep).sum()),
        "area_removed_as_noise_m2": float(n[~keep].sum() * pixel_area_m2),
        "raw_green_area_before_filter_m2": float(raw_green_px * pixel_area_m2),
    }
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    idx = np.where(keep & (n * pixel_area_m2 >= min_report_m2))[0]
    idx = idx[np.argsort(-n[idx])][:max_patches_csv]
    xs, ys = [], []
    for i in idx:
        x, y = src.transform * (decision["mean_c"][i] + 0.5, decision["mean_r"][i] + 0.5)
        xs.append(x); ys.append(y)
    if len(idx) and src.crs is not None and not src.crs.is_geographic:
        lons, lats = warp_transform(src.crs, "EPSG:4326", xs, ys)
    else:
        lons, lats = xs, ys
    with open(os.path.join(out_dir, "patches.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "pixels", "area_m2", "area_rai", "lon", "lat", "elongation"])
        for rank, (i, lo, la) in enumerate(zip(idx, lons, lats), start=1):
            w.writerow([rank, int(n[i]), round(n[i] * pixel_area_m2, 1),
                        round(n[i] * pixel_area_m2 / 1600.0, 3), f"{lo:.7f}", f"{la:.7f}",
                        round(float(decision["elong"][i]), 2)])

    with rasterio.open(final_path) as m:
        sc = max(max(m.width, m.height) / preview_px, 1.0)
        pw, ph = int(m.width / sc), int(m.height / sc)
        small = m.read(1, out_shape=(ph, pw), resampling=Resampling.nearest)
    img = np.zeros((ph, pw, 3), dtype="uint8")
    img[small == 0] = (70, 70, 70)
    img[small == 1] = (60, 220, 90)
    Image.fromarray(img, mode="RGB").save(os.path.join(out_dir, "green_preview.png"))
    return summary


# =================================================================
# STEP A - TileMosaic
# =================================================================
class TileMosaic:
    def __init__(self, grid_index_csv, tiles_dir=None, cache_size=6):
        self.csv_path = os.path.abspath(grid_index_csv)
        self.base = os.path.dirname(self.csv_path)
        self.tiles_dir = tiles_dir or os.path.join(self.base, "tiles")
        with open(self.csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            raise ValueError(f"{grid_index_csv} has no tiles")

        self.tiles = {}
        for r in rows:
            t = {"gr": int(r["grid_row"]), "gc": int(r["grid_col"]),
                 "row_off": int(r["row_off"]), "col_off": int(r["col_off"]),
                 "h": int(r["height"]), "w": int(r["width"]),
                 "path": self._resolve(r["file"], int(r["grid_row"]), int(r["grid_col"]))}
            self.tiles[(t["row_off"], t["col_off"])] = t
        self._tile_h = max(t["h"] for t in self.tiles.values())
        self._tile_w = max(t["w"] for t in self.tiles.values())

        self.row0 = min(t["row_off"] for t in self.tiles.values())
        self.col0 = min(t["col_off"] for t in self.tiles.values())
        self.height = max(t["row_off"] + t["h"] for t in self.tiles.values()) - self.row0
        self.width = max(t["col_off"] + t["w"] for t in self.tiles.values()) - self.col0

        self._cache = OrderedDict()
        self._cache_size = cache_size

        ref = None
        for key, t in sorted(self.tiles.items()):
            with rasterio.open(t["path"]) as ds:
                tf = ds.transform * Affine.translation(self.col0 - t["col_off"], self.row0 - t["row_off"])
                if ref is None:
                    ref = tf
                    self.crs, self.nodata, self.count, self.dtype = ds.crs, ds.nodata, ds.count, ds.dtypes[0]
                else:
                    if not all(abs(a - b) < 1e-6 for a, b in zip(tuple(tf)[:6], tuple(ref)[:6])):
                        raise ValueError(f"Tile {t['path']} does not line up with the others.")
        self.transform = ref
        self.indexes = tuple(range(1, self.count + 1))

    def _resolve(self, recorded, gr, gc):
        cands = [recorded,
                 os.path.join(self.tiles_dir, ntpath.basename(recorded)),
                 os.path.join(self.tiles_dir, f"tile_r{gr}_c{gc}.tif")]
        for c in cands:
            if c and os.path.isfile(c):
                return c
        raise FileNotFoundError(f"Tile file for grid r{gr} c{gc} not found. Looked in: {cands}")

    def layout(self):
        grs = sorted({t["gr"] for t in self.tiles.values()})
        gcs = sorted({t["gc"] for t in self.tiles.values()})
        have = {(t["gr"], t["gc"]) for t in self.tiles.values()}
        lines = ["        " + " ".join(f"c{c:<3}" for c in range(gcs[0], gcs[-1] + 1))]
        for r in range(grs[0], grs[-1] + 1):
            lines.append(f"  r{r:<4} " + " ".join(("  # " if (r, c) in have else "  . ")
                                                  for c in range(gcs[0], gcs[-1] + 1)))
        return "\n".join(lines)

    def _open(self, path):
        if path in self._cache:
            self._cache.move_to_end(path)
            return self._cache[path]
        ds = rasterio.open(path)
        self._cache[path] = ds
        if len(self._cache) > self._cache_size:
            _, old = self._cache.popitem(last=False)
            old.close()
        return ds

    def read(self, indexes, window):
        single = isinstance(indexes, int)
        bands = [indexes] if single else list(indexes)
        r0, c0 = int(window.row_off), int(window.col_off)
        h, w = int(window.height), int(window.width)
        fill = self.nodata if self.nodata is not None else 0
        out = np.full((len(bands), h, w), fill, dtype=self.dtype)
        R0, C0 = r0 + self.row0, c0 + self.col0
        gr_lo, gr_hi = R0 // self._tile_h, (R0 + h - 1) // self._tile_h
        gc_lo, gc_hi = C0 // self._tile_w, (C0 + w - 1) // self._tile_w
        for gr in range(gr_lo, gr_hi + 1):
            for gc in range(gc_lo, gc_hi + 1):
                t = self.tiles.get((gr * self._tile_h, gc * self._tile_w))
                if t is None:
                    continue
                a0, b0 = max(R0, t["row_off"]), max(C0, t["col_off"])
                a1, b1 = min(R0 + h, t["row_off"] + t["h"]), min(C0 + w, t["col_off"] + t["w"])
                if a1 <= a0 or b1 <= b0:
                    continue
                ds = self._open(t["path"])
                data = ds.read(bands, window=Window(b0 - t["col_off"], a0 - t["row_off"],
                                                    b1 - b0, a1 - a0))
                out[:, a0 - R0:a1 - R0, b0 - C0:b1 - C0] = data
        return out[0] if single else out

    def close(self):
        for ds in self._cache.values():
            ds.close()
        self._cache.clear()


# =================================================================
# STEP B & C - Scan and Multiround Execution
# =================================================================
def scan_offsets(size, step, reverse=False):
    starts = list(range(0, size, step))
    return starts[::-1] if reverse else starts


def scan_orders(H, W, core, start_corner="UL"):
    if start_corner not in ("UL", "UR", "LL", "LR"):
        raise ValueError("start_corner must be UL, UR, LL or LR")
    rows = scan_offsets(H, core, reverse=start_corner in ("LL", "LR"))
    cols = scan_offsets(W, core, reverse=start_corner in ("UR", "LR"))
    return rows, cols


def window_stats(mask_path, mosaic, core, start_corner, round_no, pixel_area_m2):
    rows_order, cols_order = scan_orders(mosaic.height, mosaic.width, core, start_corner)
    out, idx = [], 0
    with rasterio.open(mask_path) as m:
        for gi, r0 in enumerate(rows_order):
            ch = min(core, mosaic.height - r0)
            strip = m.read(1, window=Window(0, r0, mosaic.width, ch))
            for c0 in cols_order:
                cw = min(core, mosaic.width - c0)
                cell = strip[:, c0:c0 + cw]
                g = int((cell == 1).sum())
                v = int((cell != NODATA_OUT).sum())
                px = {"UL": (c0, r0), "UR": (c0 + cw, r0), "LR": (c0 + cw, r0 + ch), "LL": (c0, r0 + ch)}
                xs, ys = zip(*[mosaic.transform * px[n] for n in ("UL", "UR", "LR", "LL")])
                lons, lats = warp_transform(mosaic.crs, "EPSG:4326", list(xs), list(ys))
                idx += 1
                out.append({
                    "round": round_no, "scan_index": idx,
                    "win_row": r0 // core, "win_col": c0 // core,
                    "row_off": r0, "col_off": c0, "height": ch, "width": cw,
                    "green_px": g, "valid_px": v,
                    "green_m2": g * pixel_area_m2, "green_rai": g * pixel_area_m2 / 1600.0,
                    "valid_m2": v * pixel_area_m2,
                    "green_pct": (g / v * 100.0) if v else 0.0,
                    "corners": {n: (lo, la) for n, lo, la in zip(("UL", "UR", "LR", "LL"), lons, lats)}})
    return out


def save_window_csv(stats, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["round", "scan_index", "win_row", "win_col", "row_off", "col_off", "height", "width",
                    "valid_m2", "green_m2", "green_rai", "green_pct"] +
                   [f"{n}_{k}" for n in ("UL", "UR", "LR", "LL") for k in ("lon", "lat")])
        for s in stats:
            w.writerow([s["round"], s["scan_index"], s["win_row"], s["win_col"], s["row_off"], s["col_off"],
                        s["height"], s["width"], round(s["valid_m2"], 1), round(s["green_m2"], 1),
                        round(s["green_rai"], 3), round(s["green_pct"], 2)] +
                       [f"{s['corners'][n][i]:.9f}" for n in ("UL", "UR", "LR", "LL") for i in (0, 1)])


def mask_agreement(path_a, path_b, stripe_rows=512):
    diff = total = 0
    with rasterio.open(path_a) as a, rasterio.open(path_b) as b:
        for r0 in range(0, a.height, stripe_rows):
            h = min(stripe_rows, a.height - r0)
            x = a.read(1, window=Window(0, r0, a.width, h))
            y = b.read(1, window=Window(0, r0, a.width, h))
            diff += int((x != y).sum())
            total += x.size
    return diff, total


def save_overview(rounds_info, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, len(rounds_info), figsize=(4.2 * len(rounds_info), 4.4), squeeze=False)
    for ax, ri in zip(axes[0], rounds_info):
        st = ri["stats"]
        nr = max(s["win_row"] for s in st) + 1
        nc = max(s["win_col"] for s in st) + 1
        grid = np.full((nr, nc), np.nan)
        for s in st:
            if s["valid_px"]:
                grid[s["win_row"], s["win_col"]] = s["green_pct"]
        im = ax.imshow(grid, cmap="Greens", vmin=0, vmax=max(40, np.nanmax(grid) if np.isfinite(grid).any() else 1))
        for s in st:
            if s["valid_px"]:
                ax.text(s["win_col"], s["win_row"], f"{s['green_pct']:.0f}", ha="center", va="center", fontsize=7)
        ax.set_title(f"Round {ri['round']}: window {ri['window_px']} px\n"
                     f"({ri['window_px'] * ri['pixel_size_m']:.0f} m), cell {ri['core_px']} px", fontsize=9)
        ax.set_xticks(range(nc)); ax.set_yticks(range(nr)); ax.tick_params(labelsize=6)
    fig.colorbar(im, ax=axes[0].tolist(), shrink=0.8, label="green % of window cell")
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)


def scan_green(grid_index_csv, out_dir, rounds=4, core=1000, margin=100, growth=None,
               start_corner="UL", redetect_each_round=False, stripe_rows=512,
               scale_max=4095, ndvi_threshold=0.3, evi_threshold=0.2, hybrid_mode="and",
               noise_elongation_thresh=4.0, noise_max_size=5000, noise_min_absolute_size=1200,
               smooth_iterations=6, predictor=None, detector="team",
               team_threshold=0.35, include_uncertain=False, min_report_m2=300.0,
               max_patches_csv=100000, tiles_dir=None, keep_raw=False, exclude_mask=None):
    os.makedirs(out_dir, exist_ok=True)
    growth = growth or list(range(1, rounds + 1))
    if len(growth) != rounds:
        raise ValueError("growth must have one factor per round")

    print("Arranging grid tiles into one mosaic...")
    mosaic = TileMosaic(grid_index_csv, tiles_dir=tiles_dir)
    pixel_area = get_pixel_area_m2(mosaic)
    px_m = pixel_area ** 0.5
    print(f"  {len(mosaic.tiles)} tiles -> mosaic {mosaic.width} x {mosaic.height} px "
          f"({mosaic.width * px_m / 1000:.2f} x {mosaic.height * px_m / 1000:.2f} km), "
          f"{mosaic.count} bands, CRS {mosaic.crs}")
    print(mosaic.layout())

    if predictor is None:
        if detector == "team":
            predictor = make_team_predictor(mosaic.nodata, team_threshold,
                                            include_uncertain=include_uncertain)
        elif detector == "hybrid":
            predictor = make_hybrid_predictor(mosaic.nodata, scale_max, ndvi_threshold,
                                              evi_threshold, hybrid_mode)
        else:
            raise ValueError("detector must be 'hybrid' or 'team'")
    print(f"Detector: {detector}")
    rounds_info, mask_paths = [], []
    for k, g in enumerate(growth, start=1):
        c_k, m_k = int(core * g), int(margin * g)
        win_k = c_k + 2 * m_k
        mask_path = os.path.join(out_dir, f"green_mask_round{k}.tif") if (k == 1 or redetect_each_round) \
            else mask_paths[0]
        print(f"\n===== ROUND {k}/{rounds}: window {win_k} x {win_k} px "
              f"(core {c_k} + margin {m_k} each side) =====")
        if k == 1 or redetect_each_round:
            raw_path = os.path.join(out_dir, f"green_raw_round{k}.tif")
            rows_o, cols_o = scan_orders(mosaic.height, mosaic.width, c_k, start_corner)
            print("PASS 1/3: sliding-window detection")
            pass1_detect(mosaic, raw_path, c_k, m_k, predictor, smooth_iterations,
                         row_order=rows_o, col_order=cols_o, exclude_mask=exclude_mask)
            print("PASS 2/3: joining patches across all window seams")
            res = pass2_patches(raw_path, stripe_rows)
            decision = decide_noise(res, noise_elongation_thresh, noise_max_size, noise_min_absolute_size)
            raw_green_px = float(decision["count"].sum())
            print(f"  {res['n_roots']:,} exact patches; {int(decision['remove'].sum()):,} flagged as noise")
            print("PASS 3/3: writing the final mask")
            pass3_write(raw_path, mask_path, res, decision, stripe_rows)
            sub = os.path.join(out_dir, f"round{k}")
            os.makedirs(sub, exist_ok=True)
            summary = write_outputs(mosaic, sub, res, decision, pixel_area, raw_green_px,
                                    min_report_m2, max_patches_csv, mask_path)
            if not keep_raw:
                os.remove(raw_path)
            mask_paths.append(mask_path)
        else:
            summary = rounds_info[0]["summary"]
            mask_paths.append(mask_path)
            print("Reusing the round-1 mask; re-measuring with larger windows.")

        stats = window_stats(mask_path, mosaic, c_k, start_corner, k, pixel_area)
        save_window_csv(stats, os.path.join(out_dir, f"round{k}_windows.csv"))
        tot_g = sum(s["green_m2"] for s in stats)
        print(f"Round {k}: {len(stats)} windows scanned; green area {tot_g:,.0f} m2 "
              f"({summary['green_pct_of_valid']:.1f}% of valid)")
        rounds_info.append({"round": k, "window_px": win_k, "core_px": c_k, "margin_px": m_k,
                            "pixel_size_m": px_m, "n_windows": len(stats), "stats": stats,
                            "summary": summary, "mask": mask_path, "window_green_m2_sum": tot_g})

    table = []
    for ri in rounds_info:
        row = {"round": ri["round"], "window_px": ri["window_px"],
               "window_m": ri["window_px"] * px_m, "n_windows": ri["n_windows"],
               "green_m2": ri["summary"]["green_area_m2"],
               "green_rai": ri["summary"]["green_area_rai"],
               "green_pct_of_valid": ri["summary"]["green_pct_of_valid"],
               "sum_of_window_green_m2": ri["window_green_m2_sum"]}
        if ri["mask"] != rounds_info[0]["mask"]:
            d, t = mask_agreement(rounds_info[0]["mask"], ri["mask"], stripe_rows)
            row["pixels_different_from_round1"] = d
            row["agreement_with_round1_pct"] = 100.0 * (1 - d / t)
        else:
            row["pixels_different_from_round1"] = 0
            row["agreement_with_round1_pct"] = 100.0
        table.append(row)
    with open(os.path.join(out_dir, "rounds_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"start_corner": start_corner, "redetect_each_round": redetect_each_round,
                   "tiles": len(mosaic.tiles), "mosaic_px": [mosaic.width, mosaic.height],
                   "rounds": table}, f, indent=2)
    save_overview(rounds_info, os.path.join(out_dir, "scan_overview.png"))

    print("\n================ SUMMARY ================")
    print(f"{'round':>5} {'window px':>9} {'windows':>8} {'green m2':>14} {'green %':>8} {'diff px vs R1':>14}")
    for r in table:
        print(f"{r['round']:>5} {r['window_px']:>9} {r['n_windows']:>8} {r['green_m2']:>14,.0f} "
              f"{r['green_pct_of_valid']:>8.2f} {r['pixels_different_from_round1']:>14,}")
    mosaic.close()
    return table


def _new_run_output_dir(results_dir, scene):
    scene_dir = os.path.join(results_dir, scene)
    os.makedirs(scene_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return tempfile.mkdtemp(prefix=f"run_{timestamp}_", dir=scene_dir)


if __name__ == "__main__":
    PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
    GRID_DIR = os.path.join(PROJECT_DIR, "Output", "grid_2000")
    OUT_DIR = os.path.join(PROJECT_DIR, "Final_Results")
    SCENES = ("Theosmain",)
    START_CORNER = "UL"
    ROUNDS = 4
    for scene in SCENES:
        grid_index = os.path.join(GRID_DIR, scene, "grid_index.csv")
        scene_out_dir = _new_run_output_dir(OUT_DIR, scene)
        print(f"Run outputs: {scene_out_dir}")
        scan_green(grid_index, scene_out_dir, rounds=ROUNDS, core=1000, margin=100,
                   start_corner=START_CORNER, redetect_each_round=False,
                   detector="team", team_threshold=0.40,
                   smooth_iterations=6, noise_min_absolute_size=1200,
                   min_report_m2=300.0)
        # After the scan: mark the registered parks that have green on the ground and
        # draw their access circles (S 500 m, M 1 km, L 3 km, XL 5 km).
        from greensight.park_mark import mark_parks_after_scan
        parks_file = os.path.join(PROJECT_DIR, "data", "registry", "suanluang-parks.geojson")
        mark_parks_after_scan(scene_out_dir, parks_file)
        # Then group the green that is NOT a park (nearest neighbour) and circle each group.
        from greensight.green_groups import group_green_after_scan
        group_green_after_scan(scene_out_dir, parks_file)
        # Finally select GA-ranked candidate park sites from the cleaned green mask.
        from ga_parks import run_ga_after_scan
        run_ga_after_scan(scene_out_dir, parks_file)