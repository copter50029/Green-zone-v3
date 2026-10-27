import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from ga_parks import run_ga_after_scan


class GAParksScanIntegrationTests(unittest.TestCase):
    def test_runs_selection_from_cleaned_scan_mask(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scan_dir = Path(temp_dir)
            mask = np.zeros((30, 30), dtype="uint8")
            mask[2:12, 2:12] = 1
            mask[18:23, 18:23] = 1
            with rasterio.open(
                scan_dir / "green_mask_round1.tif",
                "w",
                driver="GTiff",
                height=mask.shape[0],
                width=mask.shape[1],
                count=1,
                dtype=mask.dtype,
                crs="EPSG:32647",
                transform=from_origin(500000, 1500000, 1, 1),
            ) as dst:
                dst.write(mask, 1)

            rows = run_ga_after_scan(
                scan_dir,
                cell_px=30,
                min_patch_m2=10,
                area_per_park_m2=50,
                k_cap=2,
                pop=8,
                generations=4,
                tournament=2,
                elite=2,
                patience=2,
            )

            output = scan_dir / "ga_parks"
            self.assertTrue((output / "ga_parks.csv").is_file())
            geojson = json.loads((output / "ga_parks.geojson").read_text(encoding="utf-8"))
            self.assertEqual(len(rows), len(geojson["features"]))
            self.assertTrue(geojson["note"].endswith("not verified public land."))

    def test_missing_scan_mask_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(FileNotFoundError):
                run_ga_after_scan(temp_dir)


if __name__ == "__main__":
    unittest.main()
