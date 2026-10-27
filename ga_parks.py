"""
Pick the best set of new parks in every grid zone with a genetic algorithm (GA).

Flow
  1. Grid cutting : the green mask is cut into square zones (cell_px x cell_px, default
                    2000 px = 1 km at 0.5 m/px, the same size as grid.py's tiles).
  2. Candidates   : every 4-connected green patch >= min_patch_m2 in a zone is a candidate
                    park (area, centroid). Patches cut by a zone border belong to the
                    zone that holds the pixels, because zones are separated on purpose.
  3. GA per zone  : each individual is a yes/no choice per candidate, so it can hold
                    1, 2, 3 ... parks. The most parks allowed grows with the green area
                    of the zone: k_max = clip(floor(green_area / area_per_park_m2), 1, k_cap).
  4. Fitness      : bigger parks, parks far from each other, and a penalty when a chosen park
                    is too close to another chosen park or to an official park.

Fitness (maximise)
  F =  w_size   * size_score        sum(area chosen) / sum(k_max largest areas)      [0..1]
     + w_spread * spread_score      mean of min(nearest chosen neighbour, d_target)/d_target
                                    (a lone park scores 1: it has no neighbour to crowd it)
     - w_pair   * pair_penalty      sum over chosen pairs closer than min_pair_m of
                                    (min_pair_m - d) / min_pair_m
     - w_official * official_penalty  sum over chosen parks closer than min_official_m to an
                                    official park of (min_official_m - d) / min_official_m
     - w_count  * k / k_max         small cost per park so extra parks must earn their place

Run:  python ga_parks.py --mask <mask.tif> [--registry data/registry/parks15.geojson]
Needs numpy + scipy; reading the mask / registry also needs rasterio.
"""
import argparse
import csv
import json
import os

import numpy as np
from scipy import ndimage


# =================================================================
# GA CORE (pure numpy, no raster I/O) - testable on its own
# =================================================================
DEFAULTS = dict(
    area_per_park_m2=20000.0,   # one more park allowed per 2 ha of green in the zone
    k_cap=6,                    # never more than this many parks per zone
    min_pair_m=300.0,           # chosen parks closer than this are penalised
    d_target_m=600.0,           # spacing at which the spread reward is full
    min_official_m=300.0,       # chosen parks closer than this to an official park are penalised
    w_size=1.0, w_spread=0.5, w_pair=2.0, w_official=2.0, w_count=0.05,
    pop=120, generations=200, tournament=3, elite=2, patience=40,
)


def max_parks_for_area(green_area_m2, area_per_park_m2, k_cap, n_candidates):
    k = int(np.floor(green_area_m2 / area_per_park_m2))
    return int(max(1, min(k, k_cap, n_candidates)))


def _prepare(areas, xy, official_xy, p, k_max):
    d = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1))
    np.fill_diagonal(d, np.inf)
    pair_pen = np.where(np.isfinite(d), np.clip((p["min_pair_m"] - d) / p["min_pair_m"], 0, None), 0.0)
    if len(official_xy):
        d_off = np.sqrt(((xy[:, None, :] - official_xy[None, :, :]) ** 2).sum(-1)).min(1)
    else:
        d_off = np.full(len(xy), np.inf)
    off_pen = np.clip((p["min_official_m"] - d_off) / p["min_official_m"], 0, None)
    best_total = np.sort(areas)[::-1][:k_max].sum()
    return d, pair_pen, d_off, off_pen, best_total


def fitness(pop, areas, ctx, p, k_max):
    """Vectorised fitness for a (P, n) boolean population. Returns (F, parts dict)."""
    d, pair_pen, _, off_pen, best_total = ctx
    P = pop.astype(float)
    k = P.sum(1)
    size = (P @ areas) / best_total
    both = pop[:, :, None] & pop[:, None, :]
    nn = np.where(both, d[None], np.inf).min(2)                      # nearest chosen neighbour of i
    sel_nn = np.where(pop, np.minimum(nn, p["d_target_m"]) / p["d_target_m"], np.nan)
    # mean over the chosen parks (each has a neighbour when k > 1); a lone park scores 1
    spread = np.where(k > 1, np.nansum(np.where(pop, sel_nn, 0.0), axis=1) / np.maximum(k, 1), 1.0)
    pair = 0.5 * np.einsum("pi,ij,pj->p", P, pair_pen, P)
    off = P @ off_pen
    F = (p["w_size"] * size + p["w_spread"] * spread - p["w_pair"] * pair
         - p["w_official"] * off - p["w_count"] * k / k_max)
    F = np.where(k == 0, -1e9, F)
    return F, dict(size=size, spread=spread, pair_pen=pair, official_pen=off, k=k)


def _repair(pop, areas, k_max, rng):
    """Force 1 <= parks <= k_max: drop the smallest extras, or add the largest if empty."""
    for i in range(len(pop)):
        idx = np.flatnonzero(pop[i])
        if len(idx) > k_max:
            drop = idx[np.argsort(areas[idx])[: len(idx) - k_max]]
            pop[i, drop] = False
        elif len(idx) == 0:
            pop[i, rng.integers(len(areas))] = True
    return pop


def run_ga(areas, xy, official_xy=None, k_max=None, seed=0, **overrides):
    """
    Optimise one zone.
    areas (n,) m2; xy (n,2) metres; official_xy (m,2) metres.
    Returns dict(selected=[indices], fitness, parts, history, k_max).
    """
    p = {**DEFAULTS, **overrides}
    areas = np.asarray(areas, float)
    xy = np.asarray(xy, float).reshape(-1, 2)
    official_xy = np.zeros((0, 2)) if official_xy is None else np.asarray(official_xy, float).reshape(-1, 2)
    n = len(areas)
    if n == 0:
        return dict(selected=[], fitness=float("nan"), parts={}, history=[], k_max=0)
    if k_max is None:
        k_max = max_parks_for_area(areas.sum(), p["area_per_park_m2"], p["k_cap"], n)
    k_max = int(min(k_max, n))
    rng = np.random.default_rng(seed)
    ctx = _prepare(areas, xy, official_xy, p, k_max)

    # start: random sets of 1..k_max parks, biased to big patches, plus the k largest
    prob = areas / areas.sum()
    pop = np.zeros((p["pop"], n), bool)
    for i in range(p["pop"]):
        kk = rng.integers(1, k_max + 1)
        pop[i, rng.choice(n, size=kk, replace=False, p=prob)] = True
    pop[0] = False
    pop[0, np.argsort(areas)[::-1][:k_max]] = True

    mut = min(0.5, 2.0 / n)
    best_f, best_i, stall, history = -np.inf, None, 0, []
    for gen in range(p["generations"]):
        F, parts = fitness(pop, areas, ctx, p, k_max)
        order = np.argsort(F)[::-1]
        if F[order[0]] > best_f + 1e-12:
            best_f, best_i, best_parts = F[order[0]], pop[order[0]].copy(), {k: float(v[order[0]]) for k, v in parts.items()}
            stall = 0
        else:
            stall += 1
        history.append(float(best_f))
        if stall >= p["patience"]:
            break
        new = [pop[j].copy() for j in order[: p["elite"]]]
        while len(new) < p["pop"]:
            a = max(rng.integers(0, p["pop"], p["tournament"]), key=lambda j: F[j])
            b = max(rng.integers(0, p["pop"], p["tournament"]), key=lambda j: F[j])
            cut = rng.random(n) < 0.5                              # uniform crossover
            child = np.where(cut, pop[a], pop[b])
            flip = rng.random(n) < mut                              # bit-flip mutation
            child = child ^ flip
            if rng.random() < 0.3:                                  # swap move: nudge one park to another patch
                on, off = np.flatnonzero(child), np.flatnonzero(~child)
                if len(on) and len(off):
                    child[rng.choice(on)] = False
                    child[rng.choice(off)] = True
            new.append(child)
        pop = _repair(np.array(new), areas, k_max, rng)
    return dict(selected=[int(i) for i in np.flatnonzero(best_i)], fitness=float(best_f),
                parts=best_parts, history=history, k_max=k_max)


# =================================================================
# GRID CUTTING + CANDIDATES
# =================================================================
def patches_in_block(block, row0, col0, pixel_m, x0, y0, min_patch_m2):
    """4-connected green patches of one zone -> (areas m2, centroids in metres, pixel rows/cols)."""
    lab, n = ndimage.label(block == 1)                              # 4-neighbour, like greensight
    if n == 0:
        return np.zeros(0), np.zeros((0, 2)), np.zeros((0, 2))
    idx = np.arange(1, n + 1)
    cnt = ndimage.sum(np.ones_like(lab, dtype=np.float32), lab, idx)
    keep = cnt * pixel_m ** 2 >= min_patch_m2
    cy = np.array(ndimage.center_of_mass(np.ones_like(lab, dtype=np.float32), lab, idx))
    cy, cnt = cy[keep], cnt[keep]
    rows, cols = cy[:, 0] + row0 + 0.5, cy[:, 1] + col0 + 0.5
    xy = np.stack([x0 + cols * pixel_m, y0 - rows * pixel_m], axis=1)   # north-up raster
    return cnt * pixel_m ** 2, xy, np.stack([rows, cols], axis=1)


def solve_scene(mask_path, registry_path=None, out_dir="ga_parks_out", cell_px=2000,
                min_patch_m2=300.0, max_candidates=60, seed=0, **ga_overrides):
    import rasterio
    from rasterio.warp import transform as warp_transform
    from rasterio.windows import Window

    os.makedirs(out_dir, exist_ok=True)
    with rasterio.open(mask_path) as src:
        H, W, crs, tf = src.height, src.width, src.crs, src.transform
        pixel_m = abs(tf.a)
        if tf.b or tf.d:
            raise ValueError("Rotated rasters are not supported; use the north-up mosaic mask.")
        x0, y0 = tf.c, tf.f
        official = np.zeros((0, 2))
        if registry_path and os.path.isfile(registry_path):
            with open(registry_path, encoding="utf-8") as f:
                reg = json.load(f)
            pts = [ft["geometry"]["coordinates"] for ft in reg["features"]
                   if (ft.get("geometry") or {}).get("type") == "Point"]
            if pts:
                xs, ys = warp_transform("EPSG:4326", crs, [q[0] for q in pts], [q[1] for q in pts])
                official = np.stack([xs, ys], axis=1)
        rows_out, features = [], []
        for r0 in range(0, H, cell_px):
            for c0 in range(0, W, cell_px):
                h, w = min(cell_px, H - r0), min(cell_px, W - c0)
                block = src.read(1, window=Window(c0, r0, w, h))
                areas, xy, rc = patches_in_block(block, r0, c0, pixel_m, x0, y0, min_patch_m2)
                zone = f"r{r0 // cell_px}_c{c0 // cell_px}"
                if len(areas) == 0:
                    print(f"{zone}: no candidates"); continue
                zone_green = float(areas.sum())
                top = np.argsort(areas)[::-1][:max_candidates]      # bound the GA size
                res = run_ga(areas[top], xy[top], official,
                             k_max=max_parks_for_area(zone_green, ga_overrides.get("area_per_park_m2", DEFAULTS["area_per_park_m2"]),
                                                      ga_overrides.get("k_cap", DEFAULTS["k_cap"]), len(top)),
                             seed=seed, **ga_overrides)
                sel = top[res["selected"]]
                print(f"{zone}: {len(areas)} candidates, zone green {zone_green:,.0f} m2, "
                      f"k_max {res['k_max']} -> {len(sel)} parks, fitness {res['fitness']:.3f}")
                if len(sel):
                    lon, lat = warp_transform(crs, "EPSG:4326", list(xy[sel, 0]), list(xy[sel, 1]))
                for j, s in enumerate(sel):
                    d_off = float(np.sqrt(((official - xy[s]) ** 2).sum(1)).min()) if len(official) else None
                    row = dict(zone=zone, rank=j + 1, area_m2=round(float(areas[s]), 1),
                               x_m=round(float(xy[s, 0]), 2), y_m=round(float(xy[s, 1]), 2),
                               lon=round(lon[j], 7), lat=round(lat[j], 7),
                               dist_nearest_official_m=None if d_off is None else round(d_off, 1),
                               zone_fitness=round(res["fitness"], 4), zone_k_max=res["k_max"])
                    rows_out.append(row)
                    features.append({"type": "Feature",
                                     "geometry": {"type": "Point", "coordinates": [lon[j], lat[j]]},
                                     "properties": {k: v for k, v in row.items() if k not in ("lon", "lat")}})
    with open(os.path.join(out_dir, "ga_parks.csv"), "w", newline="", encoding="utf-8") as f:
        if rows_out:
            wtr = csv.DictWriter(f, fieldnames=list(rows_out[0])); wtr.writeheader(); wtr.writerows(rows_out)
    with open(os.path.join(out_dir, "ga_parks.geojson"), "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features,
                   "note": "GA-ranked candidate parks; not verified public land."}, f)
    print(f"Wrote {len(rows_out)} parks in {out_dir}")
    return rows_out


def run_ga_after_scan(scan_dir, registry_path=None, out_name="ga_parks", **kwargs):
    """Run GA park selection on the cleaned round-1 mask produced by scan_green()."""
    mask_path = os.path.join(scan_dir, "green_mask_round1.tif")
    if not os.path.isfile(mask_path):
        raise FileNotFoundError(f"Cleaned scan mask not found: {mask_path}")
    return solve_scene(mask_path, registry_path, os.path.join(scan_dir, out_name), **kwargs)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mask", required=True, help="cleaned green mask GeoTIFF (1 = green)")
    ap.add_argument("--registry", default="data/registry/parks15.geojson")
    ap.add_argument("--out", default="ga_parks_out")
    ap.add_argument("--cell-px", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    for k, v in DEFAULTS.items():
        if k in ("pop", "generations", "tournament", "elite", "patience", "k_cap"):
            ap.add_argument("--" + k.replace("_", "-"), type=int, default=None)
        else:
            ap.add_argument("--" + k.replace("_", "-"), type=float, default=None)
    a = vars(ap.parse_args())
    over = {k: a[k] for k in DEFAULTS if a.get(k) is not None}
    solve_scene(a["mask"], a["registry"], a["out"], a["cell_px"], seed=a["seed"], **over)
