import os
import csv
import rasterio
from pathlib import Path
from rasterio.windows import Window, transform as window_transform
from rasterio.warp import transform as warp_transform, Resampling
 
CORNERS = ("UL", "UR", "LR", "LL")   # upper-left, upper-right, lower-right, lower-left
 
 
def valid_fraction(src, window, band=1, probe_px=100):
    """Share of real (non-NoData) pixels in a window, from a cheap decimated read."""
    h = max(1, min(probe_px, int(window.height)))
    w = max(1, min(probe_px, int(window.width)))
    probe = src.read(band, window=window, out_shape=(h, w), resampling=Resampling.nearest)
    if src.nodata is None:
        return 1.0
    return float((probe != src.nodata).mean())
 
 
def corner_lonlat(src, row_off, col_off, height, width):
    """lon/lat of the 4 OUTER corners (pixel edges, not centres) of a tile."""
    px = {"UL": (col_off, row_off), "UR": (col_off + width, row_off),
          "LR": (col_off + width, row_off + height), "LL": (col_off, row_off + height)}
    xs, ys = zip(*[src.transform * px[n] for n in CORNERS])
    if src.crs is not None and not src.crs.is_geographic:
        lons, lats = warp_transform(src.crs, "EPSG:4326", list(xs), list(ys))
    else:
        lons, lats = list(xs), list(ys)
    return {n: (float(lo), float(la)) for n, lo, la in zip(CORNERS, lons, lats)}
 
 
def grid_cut(tif_path, out_dir, tile_size=2000, save_tiles=True,
             min_valid_fraction=0.01, keep_partial=False, probe_band=1):
    """
    Cut tif_path into tile_size x tile_size tiles.
    Returns a list of dicts (one per kept tile) and writes grid_index.csv.
    """
    os.makedirs(out_dir, exist_ok=True)
    tiles_dir = os.path.join(out_dir, "tiles")
    if save_tiles:
        os.makedirs(tiles_dir, exist_ok=True)
 
    kept, skipped_empty, skipped_partial = [], 0, 0
    with rasterio.open(tif_path) as src:
        print(f"Opened {os.path.basename(tif_path)}: {src.width} x {src.height} px, "
              f"{src.count} bands, CRS {src.crs}")
        n_rows = -(-src.height // tile_size)
        n_cols = -(-src.width // tile_size)
        print(f"Grid {tile_size} x {tile_size}: {n_rows} rows x {n_cols} cols = {n_rows * n_cols} cells")
 
        for gr in range(n_rows):
            for gc in range(n_cols):
                row_off, col_off = gr * tile_size, gc * tile_size
                h = min(tile_size, src.height - row_off)
                w = min(tile_size, src.width - col_off)
                if (h < tile_size or w < tile_size) and not keep_partial:
                    skipped_partial += 1
                    continue
                win = Window(col_off, row_off, w, h)
 
                vf = valid_fraction(src, win, band=probe_band)
                if vf < min_valid_fraction:
                    skipped_empty += 1
                    continue
 
                info = {"grid_row": gr, "grid_col": gc, "row_off": row_off, "col_off": col_off,
                        "height": h, "width": w, "valid_pct": round(vf * 100, 1),
                        "corners": corner_lonlat(src, row_off, col_off, h, w), "path": ""}
 
                if save_tiles:
                    path = os.path.join(tiles_dir, f"tile_r{gr}_c{gc}.tif")
                    profile = src.profile.copy()
                    profile.update(height=h, width=w, transform=window_transform(win, src.transform),
                                   tiled=True, blockxsize=256, blockysize=256, compress="deflate")
                    with rasterio.open(path, "w", **profile) as dst:
                        dst.write(src.read(window=win))
                    info["path"] = path
                kept.append(info)
                print(f"  tile r{gr} c{gc}: offset (row {row_off}, col {col_off}), {vf * 100:.0f}% valid")
 
    csv_path = os.path.join(out_dir, "grid_index.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["grid_row", "grid_col", "row_off", "col_off", "height", "width", "valid_pct"] +
                    [f"{n}_{k}" for n in CORNERS for k in ("lon", "lat")] + ["file"])
        for t in kept:
            wr.writerow([t["grid_row"], t["grid_col"], t["row_off"], t["col_off"], t["height"],
                         t["width"], t["valid_pct"]] +
                        [f"{t['corners'][n][i]:.9f}" for n in CORNERS for i in (0, 1)] + [t["path"]])
 
    print(f"\nKept {len(kept)} tiles; skipped {skipped_empty} empty (NoData) and "
          f"{skipped_partial} partial edge cells.")
    print(f"Index: {csv_path}")
    return kept
 
 
if __name__ == "__main__":
    PROJECT_DIR = Path(__file__).resolve().parent
    INPUT_TIFS = [
        PROJECT_DIR / "Images" / "Theosmain.tif",
    ]
    OUT_DIR = PROJECT_DIR / "Output" / "grid_2000"
    TILE_SIZE = 2000
    SAVE_TILES = True        # False = only write grid_index.csv (no tile files)

    for input_tif in INPUT_TIFS:
        if not input_tif.is_file():
            raise FileNotFoundError(f"Input raster not found: {input_tif}")

    for input_tif in INPUT_TIFS:
        image_out_dir = OUT_DIR / input_tif.stem
        grid_cut(input_tif, image_out_dir, tile_size=TILE_SIZE, save_tiles=SAVE_TILES)