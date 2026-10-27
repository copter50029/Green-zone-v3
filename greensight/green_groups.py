"""
greensight/green_groups.py  (new file - nothing existing is modified)

Group the green patches that are NOT parks by nearest neighbour, and circle each group.

Input : <scan_dir>/round1/patches.csv written by slide_window.scan_green
        (one row per green patch: area_m2, lon, lat = patch centroid)
        + the registered parks (data/registry/suanluang-parks.geojson).

Steps
  1. Drop every patch that lies on a registered park (inside the park's search disc:
     radius of a circle with the park's area + `park_buffer_m`) - those are parks.
  2. Nearest-neighbour grouping (single linkage): two patches whose centroids are
     within `link_m` of each other belong to the same group; chains of neighbours join.
  3. A group whose circle would be wider than `max_radius_m` is split again with a
     shorter link distance (x0.7 each time, down to `min_link_m`), so a city-wide chain
     of green does not become one giant circle.
  4. Groups with fewer than `min_patches` patches are "isolated": by default they are
     still circled (kind = "isolated", drawn dashed) so that NO non-park green patch is
     left outside a circle. `isolated_circles=False` leaves them out instead.
  5. Each circle is the smallest circle that holds all its patch centroids, widened by
     the largest patch reach. A patch's reach is sqrt(area x elongation / pi): the long
     half-axis of an ellipse with the patch's area and elongation, so a long thin strip
     is not cut off by its own circle (needs the `elongation` column of patches.csv;
     without it the reach is the equal-area radius).

Output (new folder): green_groups.png (picture, only if matplotlib is installed),
  green_groups.geojson (circles + centre points), green_groups.csv
  (cluster_id, center_lon, center_lat, radius_m, patches_in_group, patches_in_circle,
   green_m2_in_group, green_m2_in_circle), green_groups_map.html (Leaflet / OSM)

HONEST LIMITS
  * A patch is represented by its centroid and equal-area radius, not its true outline.
  * patches_in_circle counts ALL non-park patches whose centroid falls in the circle,
    including ones that belong to a neighbouring group; patches_in_group counts only
    the group's own members.
  * Small patches are included in nearest-neighbour grouping. Isolated groups with
    a total area of 2,000 m2 or less are treated as noise and not drawn by default.
  * patches.csv only lists patches of at least `min_report_m2` (300 m2 in slide_window);
    smaller green is not part of any group.
  * Green here is vegetation (NDVI), not "free land"; roofs, roads and private gardens
    are not separated. It is a grouping of detected green, nothing more.
"""
import csv
import json
import math
from pathlib import Path

import numpy as np
from rasterio.warp import transform as warp_transform
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from .park_mark import circle_lonlat, load_parks


def utm_crs_for(lon):
    """UTM (north) CRS for a longitude - metres, so distances and circles are true."""
    return f"EPSG:{32600 + int((lon + 180) // 6) + 1}"


def load_patches(path):
    """[{'lon','lat','area_m2','elongation'}] from patches.csv (elongation optional, default 1)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = [{"lon": float(r["lon"]), "lat": float(r["lat"]), "area_m2": float(r["area_m2"]),
                 "elongation": float(r.get("elongation") or 1.0)}
                for r in csv.DictReader(f)]
    return rows


def min_enclosing_circle(pts):
    """Smallest circle (cx, cy, r) holding all 2-D points (Welzl, iterative)."""
    P = np.asarray(pts, dtype="float64")
    if len(P) == 1:
        return float(P[0, 0]), float(P[0, 1]), 0.0
    P = P[np.random.default_rng(0).permutation(len(P))]
    c, r = P[0].copy(), 0.0

    def far(p):
        return math.hypot(p[0] - c[0], p[1] - c[1]) > r * (1 + 1e-12) + 1e-9

    for i in range(1, len(P)):
        if far(P[i]):
            c, r = P[i].copy(), 0.0
            for j in range(i):
                if far(P[j]):
                    c, r = (P[i] + P[j]) / 2, math.hypot(*(P[i] - P[j])) / 2
                    for k in range(j):
                        if far(P[k]):
                            c, r = _circumcircle(P[i], P[j], P[k])
    r = float(np.hypot(P[:, 0] - c[0], P[:, 1] - c[1]).max())      # guarantee: all points inside
    return float(c[0]), float(c[1]), r


def _circumcircle(a, b, c):
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-12:                      # collinear: circle on the farthest pair
        pairs = [(a, b), (a, c), (b, c)]
        p, q = max(pairs, key=lambda t: math.hypot(*(t[0] - t[1])))
        return (p + q) / 2, math.hypot(*(p - q)) / 2
    ux = ((a @ a) * (b[1] - c[1]) + (b @ b) * (c[1] - a[1]) + (c @ c) * (a[1] - b[1])) / d
    uy = ((a @ a) * (c[0] - b[0]) + (b @ b) * (a[0] - c[0]) + (c @ c) * (b[0] - a[0])) / d
    cen = np.array([ux, uy])
    return cen, math.hypot(*(a - cen))


def nn_groups(xy, link_m, max_radius_m, min_link_m):
    """
    Single-linkage nearest-neighbour groups of the points xy (n,2 metres).
    Returns a list of index arrays. Over-wide groups are re-split with a shorter link.
    """
    out = []

    def split(idx, link):
        if len(idx) == 1:
            out.append(idx)
            return
        tree = cKDTree(xy[idx])
        pairs = tree.query_pairs(link, output_type="ndarray")
        n_comp, lab = connected_components(
            coo_matrix((np.ones(len(pairs), dtype=np.int8), (pairs[:, 0], pairs[:, 1])),
                       shape=(len(idx), len(idx))) if len(pairs) else coo_matrix((len(idx), len(idx))),
            directed=False)
        for g in range(n_comp):
            members = idx[lab == g]
            if len(members) > 1 and link * 0.7 >= min_link_m:
                _, _, r = min_enclosing_circle(xy[members])
                if r > max_radius_m:
                    split(members, link * 0.7)
                    continue
            out.append(members)

    split(np.arange(len(xy)), link_m)
    return out


def group_green_patches(patches, parks, out_dir, link_m=100.0, max_radius_m=300.0, min_link_m=15.0,
                        min_patches=3, park_buffer_m=30.0, crs=None, mask_path=None,
                        isolated_circles=True, isolated_noise_area_m2=2000.0):
    """Group non-park green patches and circle every group. Returns the list of group rows.
    mask_path: optional green mask (same projected CRS) drawn as the picture's background."""
    out = Path(out_dir)
    if out.exists():
        raise FileExistsError(f"{out} exists; choose a new output folder")
    if isinstance(patches, (str, Path)):
        patches = load_patches(patches)
    if isinstance(parks, (str, Path)):
        parks = load_parks(parks)
    if not patches:
        raise ValueError("No patches to group")
    if not math.isfinite(isolated_noise_area_m2) or isolated_noise_area_m2 < 0:
        raise ValueError("isolated_noise_area_m2 must be a finite non-negative number")
    crs = crs or utm_crs_for(float(np.mean([p["lon"] for p in patches])))
    xs, ys = warp_transform("EPSG:4326", crs, [p["lon"] for p in patches], [p["lat"] for p in patches])
    xy = np.column_stack([xs, ys])
    area = np.array([p["area_m2"] for p in patches])
    elong = np.array([max(float(p.get("elongation", 1.0)), 1.0) for p in patches])
    reach_all = np.sqrt(area * elong / math.pi)          # long half-axis of the patch's equal-area ellipse

    # 1. remove patches that sit on a registered park
    on_park = np.zeros(len(patches), dtype=bool)
    park_xy, park_m = [], []
    if parks:
        px, py = warp_transform("EPSG:4326", crs, [p["lon"] for p in parks], [p["lat"] for p in parks])
        for x, y, p in zip(px, py, parks):
            r = math.sqrt(p["area_m2"] / math.pi) + park_buffer_m
            on_park |= np.hypot(xy[:, 0] - x, xy[:, 1] - y) <= r
            park_xy.append((p["lon"], p["lat"], p["name"]))
            park_m.append((x, y, p["area_m2"]))
    keep = np.where(~on_park)[0]
    kxy, karea, kreach = xy[keep], area[keep], reach_all[keep]

    # 2-3. nearest-neighbour groups, re-split when too wide
    groups = nn_groups(kxy, link_m, max_radius_m, min_link_m) if len(keep) else []

    rows, feats, plot_items = [], [], []
    cid = 0
    noise_patches = 0
    noise_area = 0.0
    ktree = cKDTree(kxy) if len(keep) else None
    for g in sorted(groups, key=lambda m: (len(m) < min_patches, -karea[m].sum())):
        kind = "group" if len(g) >= min_patches else "isolated"
        if kind == "isolated" and not isolated_circles:
            continue
        cid += 1
        group_area = float(karea[g].sum())
        noise_suppressed = kind == "isolated" and group_area <= isolated_noise_area_m2
        if noise_suppressed:
            noise_patches += len(g)
            noise_area += group_area
        cx, cy, r = min_enclosing_circle(kxy[g])
        r += float(kreach[g].max())                                   # patches fit inside the circle
        inside = ktree.query_ball_point([cx, cy], r)
        lon, lat = warp_transform(crs, "EPSG:4326", [cx], [cy])
        row = {"cluster_id": cid, "kind": kind, "center_lon": round(lon[0], 7), "center_lat": round(lat[0], 7),
               "radius_m": round(r, 1), "patches_in_group": int(len(g)), "patches_in_circle": int(len(inside)),
               "green_m2_in_group": round(group_area, 1),
               "green_m2_in_circle": round(float(karea[inside].sum()), 1),
               "noise_suppressed": noise_suppressed}
        rows.append(row)
        if not noise_suppressed:
            plot_items.append((cx, cy, r, row))
            props = dict(row)
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon[0], lat[0]]},
                          "properties": {**props, "role": "center"}})
            feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [circle_lonlat(cx, cy, r, crs)]},
                          "properties": {**props, "role": "group_circle"}})

    out.mkdir(parents=True)
    (out / "green_groups.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False) + "\n", encoding="utf-8")
    with (out / "green_groups.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["cluster_id", "kind", "center_lon", "center_lat", "radius_m", "patches_in_group",
                                          "patches_in_circle", "green_m2_in_group", "green_m2_in_circle",
                                          "noise_suppressed"])
        w.writeheader()
        w.writerows(rows)
    n_in = int(sum(r["patches_in_group"] for r in rows))
    non_park_area = float(karea.sum())
    grouped_area = float(sum(r["green_m2_in_group"] for r in rows if not r["noise_suppressed"]))
    summary = {"patches_total": len(patches), "patches_on_parks_removed": int(on_park.sum()),
               "patches_grouped": int(sum(r["patches_in_group"] for r in rows if r["kind"] == "group")),
               "patches_isolated": int(sum(r["patches_in_group"] for r in rows if r["kind"] == "isolated")),
               "isolated_noise_groups": int(sum(r["noise_suppressed"] for r in rows)),
               "isolated_noise_patches": noise_patches,
               "patches_not_in_any_circle": int(len(keep) - n_in + noise_patches),
               "green_m2_total": round(float(area.sum()), 1),
               "green_m2_on_parks_removed": round(float(area[on_park].sum()), 1),
               "green_m2_non_park_total": round(non_park_area, 1),
               "isolated_noise_area_m2": isolated_noise_area_m2,
               "green_m2_isolated_noise": round(noise_area, 1),
               "green_m2_eligible_for_grouping": round(float(karea.sum()), 1),
               "green_m2_in_groups": round(grouped_area, 1),
               "green_m2_not_in_any_circle": round(max(non_park_area - grouped_area, 0.0), 1),
               "groups": sum(r["kind"] == "group" for r in rows),
               "isolated_circles": sum(r["kind"] == "isolated" and not r["noise_suppressed"] for r in rows),
               "link_m": link_m, "max_radius_m": max_radius_m, "min_patches": min_patches}
    if mask_path:
        cov = _mask_coverage(mask_path, plot_items, park_m, park_buffer_m, crs)
        if cov is not None:
            summary["green_px_outside_circles_pct"] = round(100 - cov, 2)
            summary["green_px_inside_circles_pct"] = round(cov, 2)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _write_html(out / "green_groups_map.html", feats, park_xy, [(p["lon"], p["lat"]) for p in patches])
    _write_png(out / "green_groups.png", plot_items, park_m, crs, mask_path)
    return rows


def _mask_coverage(mask_path, items, park_m, park_buffer_m, crs):
    """% of the mask's green pixels (outside parks) that lie inside some circle (sampled <=1500 px)."""
    import rasterio
    with rasterio.open(mask_path) as m:
        if m.crs is None or m.crs != rasterio.crs.CRS.from_string(crs):
            return None
        sc = max(max(m.width, m.height) / 1500, 1.0)
        small = m.read(1, out_shape=(int(m.height / sc), int(m.width / sc)))
        t = m.transform
        rr, cc = np.nonzero(small == 1)
        x = t.c + (cc + 0.5) * sc * t.a
        y = t.f + (rr + 0.5) * sc * t.e
    on_park = np.zeros(len(x), dtype=bool)
    for px, py, a in park_m:
        on_park |= np.hypot(x - px, y - py) <= math.sqrt(a / math.pi) + park_buffer_m
    x, y = x[~on_park], y[~on_park]
    if not len(x):
        return None
    inside = np.zeros(len(x), dtype=bool)
    for cx, cy, r, _ in items:
        inside |= np.hypot(x - cx, y - cy) <= r
    return 100.0 * float(inside.mean())


def _write_png(path, items, park_m, crs, mask_path=None):
    """Picture: one circle per group (colour = green area in the group), group centres, parks.
    Axes are projected metres (easting / northing) so a circle is a true circle."""
    if not items:
        return
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.cm import ScalarMappable
        from matplotlib.colors import Normalize
        from matplotlib.patches import Circle
    except ImportError:                     # optional: only the picture needs matplotlib
        return
    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.set_facecolor("#2b2b2b")
    if mask_path:
        import rasterio
        with rasterio.open(mask_path) as m:
            if m.crs is not None and m.crs == rasterio.crs.CRS.from_string(crs):
                sc = max(max(m.width, m.height) / 1500, 1.0)
                small = m.read(1, out_shape=(int(m.height / sc), int(m.width / sc)))
                img = np.zeros(small.shape + (3,), dtype="uint8")
                img[small == 0] = (70, 70, 70)
                img[small == 1] = (60, 220, 90)
                t = m.transform
                ax.imshow(img, extent=(t.c, t.c + t.a * m.width, t.f + t.e * m.height, t.f), zorder=0)
    green = np.array([row["green_m2_in_group"] for *_, row in items])
    norm = Normalize(0, float(np.percentile(green, 95)) or 1.0)
    cmap = plt.get_cmap("YlOrRd")
    for cx, cy, r, row in items:
        col = cmap(norm(row["green_m2_in_group"]))
        ax.add_patch(Circle((cx, cy), r, facecolor=col, edgecolor=col, alpha=0.35, lw=0, zorder=2))
        ax.add_patch(Circle((cx, cy), r, fill=False, edgecolor=col, lw=1.2, zorder=3,
                            ls="--" if row["kind"] == "isolated" else "-"))
    for i in [j for j in np.argsort(-green) if items[j][3]["kind"] == "group"][:10]:
        cx, cy, _, row = items[i]
        ax.annotate(str(row["cluster_id"]), (cx, cy), color="white", fontsize=8, ha="center",
                    va="bottom", xytext=(0, 4), textcoords="offset points", zorder=6)
    for x, y, a in park_m:
        ax.plot(x, y, "o", color="#1a9641", mec="white", ms=9 if a > 160000 else 6, zorder=5)
    ax.set_aspect("equal")
    ax.autoscale()
    ax.set_title(f"Non-park green groups: {len(items)} circles (colour = green area in the group; "
                 f"numbers = 10 largest)\ndashed = isolated patches (<3), green dot = registered park", fontsize=10)
    ax.set_xlabel(f"easting (m, {crs}) - metres east")
    ax.set_ylabel("northing (m) - metres north")
    fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=ax, shrink=0.8, label="green area in group (m2)")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def _write_html(path, feats, park_points, _unused=None):
    data = json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False).replace("</", "<\\/")
    parks = json.dumps(park_points, ensure_ascii=False).replace("</", "<\\/")
    path.write_text(f"""<!doctype html><meta charset="utf-8"><title>Green groups</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>html,body,#m{{height:100%;margin:0}}</style><div id="m"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const data={data}, parks={parks};
const map=L.map('m');
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'&copy; OpenStreetMap'}}).addTo(map);
const layer=L.geoJSON(data,{{
 style:()=>({{color:'#e08a00',weight:2,fillOpacity:0.10}}),
 pointToLayer:(f,ll)=>L.circleMarker(ll,{{radius:4,color:'#000',weight:1,fillColor:'#e08a00',fillOpacity:1}}),
 onEachFeature:(f,l)=>{{const p=f.properties;
  l.bindPopup('<b>Group '+p.cluster_id+'</b><br>centre '+p.center_lat+', '+p.center_lon+'<br>radius '+p.radius_m+
   ' m<br>patches in group '+p.patches_in_group+', in circle '+p.patches_in_circle+'<br>green '+p.green_m2_in_group+' m2')}}
}}).addTo(map);
parks.forEach(p=>L.circleMarker([p[1],p[0]],{{radius:6,color:'#000',weight:1,fillColor:'#1a9641',fillOpacity:1}}).bindPopup(p[2]).addTo(map));
if(layer.getLayers().length) map.fitBounds(layer.getBounds()); else map.setView([13.73,100.63],13);
</script>""", encoding="utf-8")


def group_green_after_scan(scan_dir, parks_path, out_name="green_groups", **kwargs):
    """Run after slide_window.scan_green: uses <scan_dir>/round1/patches.csv."""
    scan_dir = Path(scan_dir)
    mask = scan_dir / "green_mask_round1.tif"
    kwargs.setdefault("mask_path", mask if mask.exists() else None)   # green background if available
    return group_green_patches(scan_dir / "round1" / "patches.csv", parks_path, scan_dir / out_name, **kwargs)


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Group non-park green patches by nearest neighbour and circle them")
    p.add_argument("patches_csv", help="round1/patches.csv from slide_window")
    p.add_argument("parks", help="parks GeoJSON or CSV")
    p.add_argument("out_dir", help="new output folder")
    p.add_argument("--link", type=float, default=100.0, help="neighbour distance in metres")
    p.add_argument("--max-radius", type=float, default=300.0, help="split groups wider than this (metres)")
    p.add_argument("--min-patches", type=int, default=3)
    p.add_argument("--isolated-noise-area", type=float, default=2000.0,
                   help="suppress isolated groups at or below this green area (m2)")
    a = p.parse_args(argv)
    for r in group_green_patches(a.patches_csv, a.parks, a.out_dir, link_m=a.link, max_radius_m=a.max_radius,
                                 min_patches=a.min_patches, isolated_noise_area_m2=a.isolated_noise_area):
        print(f"group {r['cluster_id']:>3}: centre ({r['center_lat']}, {r['center_lon']}) radius {r['radius_m']:>7} m, "
              f"{r['patches_in_group']} patches ({r['green_m2_in_group']} m2), {r['patches_in_circle']} inside circle")


if __name__ == "__main__":
    main()
