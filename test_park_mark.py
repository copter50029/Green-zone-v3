import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform

from greensight.park_mark import load_parks, mark_parks, size_class

CRS = "EPSG:32647"
PX = 2.0
X0, Y0, N = 665000.0, 1520000.0, 1500          # 3 km x 3 km mask, 2 m pixels


def lonlat(x, y):
    lo, la = warp_transform(CRS, "EPSG:4326", [x], [y])
    return lo[0], la[0]


def build_mask(path, green_discs, nodata_box=None):
    t = from_origin(X0, Y0, PX, PX)
    m = np.zeros((N, N), dtype="uint8")
    rr, cc = np.mgrid[0:N, 0:N]
    cx, cy = t * (cc + 0.5, rr + 0.5)
    for x, y, r in green_discs:
        m[(cx - x) ** 2 + (cy - y) ** 2 <= r * r] = 1
    if nodata_box:
        m[:, nodata_box:] = 255
    with rasterio.open(path, "w", driver="GTiff", height=N, width=N, count=1, dtype="uint8", crs=CRS,
                       transform=t, nodata=255) as d:
        d.write(m, 1)


class ParkMarkTests(unittest.TestCase):
    def test_size_classes(self):
        self.assertEqual(size_class(99.9), ("below_S", 0.0))
        self.assertEqual(size_class(100), ("S", 500.0))
        self.assertEqual(size_class(7308), ("S", 500.0))
        self.assertEqual(size_class(16000), ("S", 500.0))
        self.assertEqual(size_class(16001), ("M", 1000.0))
        self.assertEqual(size_class(160001), ("XL", 5000.0))

    def test_marks_green_missing_and_outside_with_correct_circles(self):
        with tempfile.TemporaryDirectory() as d:
            real = (X0 + 600, Y0 - 600)           # park with green
            empty = (X0 + 1200, Y0 - 600)         # registered but only bare ground
            outside = (X0 + 2700, Y0 - 600)       # on NoData
            area = 3600.0
            r = math.sqrt(area / math.pi)
            build_mask(Path(d) / "mask.tif", [(real[0], real[1], r)], nodata_box=1200)
            geo = {"type": "FeatureCollection", "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": list(lonlat(*p))},
                 "properties": {"name": n, "area_m2": area}}
                for n, p in (("real", real), ("empty", empty), ("outside", outside))]}
            (Path(d) / "parks.geojson").write_text(json.dumps(geo), encoding="utf-8")
            rows = mark_parks(Path(d) / "mask.tif", Path(d) / "parks.geojson", Path(d) / "out")
            st = {r_["name"]: r_ for r_ in rows}
            self.assertEqual(st["real"]["status"], "green_detected")
            self.assertGreater(st["real"]["green_ratio"], 0.9)
            self.assertEqual(st["empty"]["status"], "no_green_detected")
            self.assertEqual(st["outside"]["status"], "outside_image")
            self.assertTrue(all(r_["access_radius_m"] == 500.0 for r_ in rows))

            out = json.loads((Path(d) / "out" / "parks_marked.geojson").read_text(encoding="utf-8"))
            circle = next(f for f in out["features"] if f["properties"]["role"] == "access_radius"
                          and f["properties"]["name"] == "real")
            lons, lats = zip(*circle["geometry"]["coordinates"][0])
            xs, ys = warp_transform("EPSG:4326", CRS, list(lons), list(lats))
            dist = np.hypot(np.array(xs) - real[0], np.array(ys) - real[1])
            self.assertTrue(np.allclose(dist, 500.0, atol=0.5))     # circle really is 500 m
            self.assertTrue((Path(d) / "out" / "parks_map.html").exists())

    def test_park_under_100_m2_is_checked_but_gets_no_circle(self):
        with tempfile.TemporaryDirectory() as d:
            build_mask(Path(d) / "mask.tif", [])
            lo, la = lonlat(X0 + 500, Y0 - 500)
            rows = mark_parks(Path(d) / "mask.tif", [{"name": "tiny", "lon": lo, "lat": la, "area_m2": 50.0}],
                              Path(d) / "o")
            self.assertEqual(rows[0]["size_class"], "below_S")
            self.assertEqual(rows[0]["access_radius_m"], 0.0)
            gj = json.loads((Path(d) / "o" / "parks_marked.geojson").read_text(encoding="utf-8"))
            self.assertEqual([f["properties"]["role"] for f in gj["features"]], ["park"])

    def test_fixed_radius_override_and_existing_folder_protected(self):
        with tempfile.TemporaryDirectory() as d:
            build_mask(Path(d) / "mask.tif", [])
            p = [{"name": "x", "lon": lonlat(X0 + 500, Y0 - 500)[0], "lat": lonlat(X0 + 500, Y0 - 500)[1],
                  "area_m2": 100000.0}]
            rows = mark_parks(Path(d) / "mask.tif", p, Path(d) / "o1", fixed_radius_m=500)
            self.assertEqual(rows[0]["access_radius_m"], 500.0)
            self.assertEqual(rows[0]["size_class"], "L")
            with self.assertRaises(FileExistsError):
                mark_parks(Path(d) / "mask.tif", p, Path(d) / "o1")

    def test_shipped_suanluang_registry_is_valid(self):
        parks = load_parks(Path(__file__).resolve().parent / "data" / "registry" / "suanluang-parks.geojson")
        self.assertGreaterEqual(len(parks), 11)
        self.assertEqual(len({p["id"] for p in parks}), len(parks))
        big = next(p for p in parks if p["area_m2"] > 160000)          # the Si Nakarin / Rama 9 park
        self.assertEqual(size_class(big["area_m2"]), ("XL", 5000.0))
        self.assertTrue(all(13.70 < p["lat"] < 13.75 and 100.61 < p["lon"] < 100.66 for p in parks))


if __name__ == "__main__":
    unittest.main()
