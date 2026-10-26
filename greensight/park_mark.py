"""
greensight/park_mark.py  (new file - nothing existing is modified)

After the sliding-window scan: mark the registered parks that have green on the
ground and draw each park's access radius.

For every park (point + registered area):
  * search disc  = radius of a circle with the park's registered area + `search_buffer_m`
    (GPS/registry points are rarely exactly at the park centre)
  * green_m2     = detected green area inside the search disc (from the scan mask)
  * status       = "green_detected"    green_m2 >= min_green_ratio x registered area
                   "no_green_detected" point is on valid pixels but too little green
                   "outside_image"     the point is on NoData / outside the raster
  * access circle (by registered size):
        S   100 - 16,000 m2   500 m      M   16,001 - 80,000 m2   1,000 m
        L   80,001 - 160,000  3,000 m    XL  160,001 m2 and up    5,000 m
    A park under 100 m2 is below class S: it is still checked for green but gets NO
    circle (size_class "below_S"). One radius for all parks: `fixed_radius_m=500`.

HONEST LIMITS
  * "green_detected" means vegetation was found where the registry says a park is. It
    is NOT verification that the park exists, is public, or is open - tiny parks
    (tens of m2) can be satisfied by a neighbouring tree. Review the flagged parks.
  * Circles are straight-line distance, not walking distance, and are not clipped.
  * Needs the mask to be in a projected CRS in metres (as the scan writes it).

Inputs : mask GeoTIFF (0/1/255, e.g. green_mask_round1.tif) + parks GeoJSON (Point
         features with properties name and area_m2) or CSV (name, lat, lon, area_m2).
Outputs: parks_marked.geojson (points + circles), parks_marked.csv, parks_map.html
         (Leaflet over OpenStreetMap; needs internet to show the base map),
         parks_marked.png (only if matplotlib is installed).
"""
import csv
import html
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform as warp_transform
from rasterio.windows import Window

NODATA_OUT = 255
MIN_PARK_M2 = 100.0
SIZE_CLASSES = (("S", 16000.0, 500.0), ("M", 80000.0, 1000.0), ("L", 160000.0, 3000.0), ("XL", math.inf, 5000.0))


def size_class(area_m2, min_area_m2=MIN_PARK_M2):
    """(class name, access radius m). Below min_area_m2 -> ("below_S", 0.0): no circle."""
    if area_m2 < min_area_m2:
        return "below_S", 0.0
    for name, upper, radius in SIZE_CLASSES:
        if area_m2 <= upper:
            return name, radius
    raise ValueError("unreachable")


def load_parks(path):
    """Return [{'name','lon','lat','area_m2', ...}] from GeoJSON (Point) or CSV."""
    path = Path(path)
    parks = []
    if path.suffix.lower() in (".geojson", ".json"):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        for f in data["features"]:
            if f["geometry"]["type"] != "Point":
                continue
            lon, lat = f["geometry"]["coordinates"][:2]
            p = dict(f.get("properties") or {})
            p.update(lon=float(lon), lat=float(lat))
            parks.append(p)
    else:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                r["lon"], r["lat"] = float(r["lon"]), float(r["lat"])
                parks.append(r)
    for i, p in enumerate(parks, 1):
        p.setdefault("name", f"park-{i}")
        p["area_m2"] = float(p.get("area_m2") or 0)
        if not (-180 <= p["lon"] <= 180 and -90 <= p["lat"] <= 90) or p["area_m2"] <= 0:
            raise ValueError(f"Park '{p['name']}' needs lon/lat in range and area_m2 > 0")
    return parks


def circle_lonlat(x, y, radius_m, crs, n=72):
    """Polygon ring (lon, lat) of a circle of radius_m around projected (x, y)."""
    ang = np.linspace(0, 2 * math.pi, n, endpoint=False)
    lons, lats = warp_transform(crs, "EPSG:4326", list(x + radius_m * np.cos(ang)), list(y + radius_m * np.sin(ang)))
    ring = [[float(a), float(b)] for a, b in zip(lons, lats)]
    return ring + [ring[0]]


def green_in_disc(mask, x, y, radius_m):
    """(green_m2, valid_m2, point_is_valid) inside a disc around projected (x, y)."""
    t = mask.transform
    px = abs(t.a)
    col, row = ~t * (x, y)
    half = int(math.ceil(radius_m / px)) + 1
    r0, c0 = int(math.floor(row)) - half, int(math.floor(col)) - half
    win = Window(c0, r0, 2 * half + 1, 2 * half + 1)
    data = mask.read(1, window=win, boundless=True, fill_value=NODATA_OUT)
    rr, cc = np.mgrid[r0:r0 + data.shape[0], c0:c0 + data.shape[1]]
    cx, cy = t * (cc + 0.5, rr + 0.5)
    inside = (cx - x) ** 2 + (cy - y) ** 2 <= radius_m ** 2
    area = abs(t.a * t.e - t.b * t.d)
    green = int(((data == 1) & inside).sum())
    valid = int(((data != NODATA_OUT) & inside).sum())
    here = mask.read(1, window=Window(int(math.floor(col)), int(math.floor(row)), 1, 1),
                     boundless=True, fill_value=NODATA_OUT)[0, 0]
    return green * area, valid * area, bool(here != NODATA_OUT)


def mark_parks(mask_path, parks, out_dir, fixed_radius_m=None, search_buffer_m=30.0,
               min_green_ratio=0.25):
    """Check each park against the green mask, draw access circles, write the outputs."""
    if isinstance(parks, (str, Path)):
        parks = load_parks(parks)
    out = Path(out_dir)
    if out.exists():
        raise FileExistsError(f"{out} exists; choose a new output folder")
    out.mkdir(parents=True)
    rows, features = [], []
    with rasterio.open(mask_path) as m:
        if m.crs is None or m.crs.is_geographic:
            raise ValueError("The mask must be in a projected CRS in metres")
        xs, ys = warp_transform("EPSG:4326", m.crs, [p["lon"] for p in parks], [p["lat"] for p in parks])
        for p, x, y in zip(parks, xs, ys):
            cls, class_radius = size_class(p["area_m2"])
            radius = float(fixed_radius_m or class_radius) if cls != "below_S" else 0.0
            search_r = math.sqrt(p["area_m2"] / math.pi) + search_buffer_m
            g_m2, v_m2, on_valid = green_in_disc(m, x, y, search_r)
            if not on_valid:
                status = "outside_image"
            elif g_m2 >= min_green_ratio * p["area_m2"]:
                status = "green_detected"
            else:
                status = "no_green_detected"
            row = {"name": p["name"], "lon": p["lon"], "lat": p["lat"], "area_m2": p["area_m2"],
                   "size_class": cls, "access_radius_m": radius, "search_radius_m": round(search_r, 1),
                   "green_m2_in_search_disc": round(g_m2, 1),
                   "green_ratio": round(g_m2 / p["area_m2"], 2), "status": status,
                   "owner": p.get("owner", "")}
            rows.append(row)
            props = {k: v for k, v in row.items() if k not in ("lon", "lat")}
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
                             "properties": {**props, "role": "park"}})
            if radius > 0:
                features.append({"type": "Feature",
                                 "geometry": {"type": "Polygon", "coordinates": [circle_lonlat(x, y, radius, m.crs)]},
                                 "properties": {**props, "role": "access_radius"}})
        mask_crs = m.crs
    (out / "parks_marked.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False) + "\n", encoding="utf-8")
    with (out / "parks_marked.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    _write_html(out / "parks_map.html", features)
    _write_png(out / "parks_marked.png", mask_path, rows, mask_crs)
    return rows


_COLORS = {"green_detected": "#1a9641", "no_green_detected": "#d7191c", "outside_image": "#777777"}


def _write_html(path, features):
    data = json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False).replace("</", "<\\/")
    path.write_text(f"""<!doctype html><meta charset="utf-8"><title>Parks</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>html,body,#m{{height:100%;margin:0}}</style><div id="m"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const C={json.dumps(_COLORS)};
const data={data};
const map=L.map('m');
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'&copy; OpenStreetMap'}}).addTo(map);
const layer=L.geoJSON(data,{{
 style:f=>f.properties.role==='access_radius'?{{color:C[f.properties.status],weight:1,fillOpacity:0.08}}:{{}},
 pointToLayer:(f,ll)=>L.circleMarker(ll,{{radius:7,color:'#000',weight:1,fillColor:C[f.properties.status],fillOpacity:1}}),
 onEachFeature:(f,l)=>{{if(f.properties.role==='park')l.bindPopup('<b>'+f.properties.name+'</b><br>'+f.properties.status+
  '<br>registered '+f.properties.area_m2+' m2, green found '+f.properties.green_m2_in_search_disc+' m2<br>radius '+f.properties.access_radius_m+' m')}}
}}).addTo(map);
map.fitBounds(layer.getBounds());
</script>""", encoding="utf-8")


def _write_png(path, mask_path, rows, crs):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    with rasterio.open(mask_path) as m:
        sc = max(max(m.width, m.height) / 1500, 1.0)
        small = m.read(1, out_shape=(int(m.height / sc), int(m.width / sc)))
        t = m.transform
        xs, ys = warp_transform("EPSG:4326", m.crs, [r["lon"] for r in rows], [r["lat"] for r in rows])
    img = np.zeros(small.shape + (3,), dtype="uint8")
    img[small == 0] = (70, 70, 70)
    img[small == 1] = (60, 220, 90)
    ext = (t.c, t.c + t.a * m.width, t.f + t.e * m.height, t.f)
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(img, extent=ext)
    for r, x, y in zip(rows, xs, ys):
        if r["access_radius_m"] > 0:
            ax.add_patch(plt.Circle((x, y), r["access_radius_m"], fill=False, color=_COLORS[r["status"]], lw=1))
        ax.plot(x, y, "o", color=_COLORS[r["status"]], mec="k", ms=6)
    ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); ax.set_aspect("equal")
    ax.set_title("Registered parks on the detected green (dot = park, circle = access radius)")
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)


def mark_parks_after_scan(scan_dir, parks_path, out_name="parks", **kwargs):
    """Run right after slide_window.scan_green: uses <scan_dir>/green_mask_round1.tif and
    writes <scan_dir>/<out_name>/ (parks_marked.geojson / .csv / parks_map.html / .png)."""
    scan_dir = Path(scan_dir)
    return mark_parks(scan_dir / "green_mask_round1.tif", parks_path, scan_dir / out_name, **kwargs)


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Mark registered parks on the green mask and draw access radii")
    p.add_argument("mask", help="green_mask_round1.tif from slide_scan")
    p.add_argument("parks", help="parks GeoJSON or CSV")
    p.add_argument("out_dir", help="new output folder")
    p.add_argument("--radius", type=float, default=None, help="one radius in metres for all parks (default: by size class)")
    a = p.parse_args(argv)
    for r in mark_parks(a.mask, a.parks, a.out_dir, fixed_radius_m=a.radius):
        print(f"{r['status']:<18} {r['name'][:40]:<40} green {r['green_m2_in_search_disc']:>8} m2 / "
              f"registered {r['area_m2']:.0f} m2, radius {r['access_radius_m']:.0f} m")


if __name__ == "__main__":
    main()
