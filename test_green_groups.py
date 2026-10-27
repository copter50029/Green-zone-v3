import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
from rasterio.warp import transform as warp_transform

from greensight.green_groups import group_green_patches, min_enclosing_circle, nn_groups

CRS = "EPSG:32647"


def lonlat(x, y):
    lo, la = warp_transform(CRS, "EPSG:4326", [x], [y])
    return lo[0], la[0]


def patch(x, y, area=500.0):
    lo, la = lonlat(x, y)
    return {"lon": lo, "lat": la, "area_m2": area}


X0, Y0 = 665000.0, 1520000.0


class GreenGroupTests(unittest.TestCase):
    def test_min_enclosing_circle(self):
        cx, cy, r = min_enclosing_circle([(0, 0), (10, 0), (5, 8), (5, 1)])
        pts = np.array([(0, 0), (10, 0), (5, 8), (5, 1)], float)
        self.assertTrue((np.hypot(pts[:, 0] - cx, pts[:, 1] - cy) <= r + 1e-6).all())
        cx, cy, r = min_enclosing_circle([(0, 0), (10, 0)])
        self.assertAlmostEqual(r, 5.0)
        _, _, r = min_enclosing_circle([(0, 0), (5, 0), (10, 0)])          # collinear
        self.assertAlmostEqual(r, 5.0)

    def test_groups_exclude_parks_drop_singletons_and_report_centre_radius_count(self):
        near = [patch(X0 + 20 * i, Y0 - 500 + 15 * (i % 2)) for i in range(5)]       # tight group A
        far = [patch(X0 + 2000 + 25 * i, Y0 - 1500) for i in range(4)]                # tight group B
        lone = [patch(X0 + 1000, Y0 - 3000)]                                           # singleton
        on_park = [patch(X0 + 500, Y0 - 900), patch(X0 + 510, Y0 - 905), patch(X0 + 520, Y0 - 900)]
        lo, la = lonlat(X0 + 505, Y0 - 902)
        parks = [{"name": "park", "lon": lo, "lat": la, "area_m2": 3600.0}]
        with tempfile.TemporaryDirectory() as d:
            rows = group_green_patches(near + far + lone + on_park, parks, Path(d) / "o", isolated_circles=False)
            self.assertEqual(len(rows), 2)                                    # A and B only
            sizes = sorted(r["patches_in_group"] for r in rows)
            self.assertEqual(sizes, [4, 5])
            summ = json.loads((Path(d) / "o" / "summary.json").read_text())
            self.assertEqual(summ["patches_on_parks_removed"], 3)
            self.assertEqual(summ["patches_not_in_any_circle"], 1)           # the singleton
            a = next(r for r in rows if r["patches_in_group"] == 5)
            xc, yc = warp_transform("EPSG:4326", CRS, [a["center_lon"]], [a["center_lat"]])
            self.assertLess(math.hypot(xc[0] - (X0 + 40), yc[0] - (Y0 - 500)), 15)  # centre in the middle of the group
            self.assertTrue(40 <= a["radius_m"] <= 70)                        # ~40 m half-width + patch radius
            self.assertEqual(a["patches_in_circle"], 5)
            gj = json.loads((Path(d) / "o" / "green_groups.geojson").read_text())
            self.assertEqual(sorted(f["properties"]["role"] for f in gj["features"]),
                             ["center", "center", "group_circle", "group_circle"])
            self.assertTrue((Path(d) / "o" / "green_groups_map.html").exists())
            try:
                import matplotlib  # noqa: F401
                self.assertGreater((Path(d) / "o" / "green_groups.png").stat().st_size, 5000)
            except ImportError:
                pass

    def test_isolated_patches_get_their_own_circle_and_elongated_patch_is_covered(self):
        grp = [patch(X0 + 20 * i, Y0 - 500) for i in range(4)]
        lone = dict(patch(X0 + 3000, Y0 - 500, area=1000.0), elongation=9.0)   # long thin strip
        with tempfile.TemporaryDirectory() as d:
            rows = group_green_patches(grp + [lone], [], Path(d) / "o", isolated_noise_area_m2=0)
            kinds = sorted(r["kind"] for r in rows)
            self.assertEqual(kinds, ["group", "isolated"])
            iso = next(r for r in rows if r["kind"] == "isolated")
            self.assertAlmostEqual(iso["radius_m"], math.sqrt(1000.0 * 9.0 / math.pi), delta=0.2)   # ellipse reach, not 17.8 m
            summ = json.loads((Path(d) / "o" / "summary.json").read_text())
            self.assertEqual(summ["patches_not_in_any_circle"], 0)
            self.assertEqual(summ["isolated_circles"], 1)

    def test_long_chain_is_split_so_no_circle_exceeds_max_radius(self):
        pts = np.array([(i * 50.0, 0.0) for i in range(60)])                  # 3 km chain, 50 m apart
        groups = nn_groups(pts, link_m=100.0, max_radius_m=300.0, min_link_m=15.0)
        self.assertEqual(sorted(np.concatenate(groups).tolist()), list(range(60)))   # nobody lost or duplicated
        self.assertGreater(len(groups), 1)
        for g in groups:
            self.assertLessEqual(min_enclosing_circle(pts[g])[2], 300.0 + 1e-6)

    def test_small_patches_are_grouped_and_only_small_isolated_noise_is_suppressed(self):
        patches = [
            patch(X0, Y0, area=500.0),
            patch(X0 + 10, Y0, area=500.0),
            patch(X0 + 1000, Y0, area=1500.0),
        ]
        with tempfile.TemporaryDirectory() as d:
            rows = group_green_patches(patches, [], Path(d) / "o", min_patches=2)
            self.assertEqual(len(rows), 2)
            group = next(row for row in rows if row["kind"] == "group")
            isolated = next(row for row in rows if row["kind"] == "isolated")
            self.assertEqual(group["patches_in_group"], 2)
            self.assertEqual(group["green_m2_in_group"], 1000.0)
            self.assertFalse(group["noise_suppressed"])
            self.assertTrue(isolated["noise_suppressed"])
            summary = json.loads((Path(d) / "o" / "summary.json").read_text())
            self.assertEqual(summary["isolated_noise_groups"], 1)
            self.assertEqual(summary["isolated_noise_patches"], 1)
            self.assertEqual(summary["patches_not_in_any_circle"], 1)
            self.assertEqual(summary["green_m2_isolated_noise"], 1500.0)
            self.assertEqual(summary["green_m2_eligible_for_grouping"], 2500.0)
            self.assertEqual(summary["green_m2_in_groups"], 1000.0)
            self.assertEqual(summary["green_m2_not_in_any_circle"], 1500.0)
            features = json.loads((Path(d) / "o" / "green_groups.geojson").read_text())["features"]
            self.assertEqual(len(features), 2)

    def test_existing_output_folder_is_protected(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "o").mkdir()
            with self.assertRaises(FileExistsError):
                group_green_patches([patch(X0, Y0)], [], Path(d) / "o")


if __name__ == "__main__":
    unittest.main()
