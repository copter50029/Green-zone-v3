import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import rasterio
from rasterio.enums import ColorInterp
from rasterio.transform import from_origin
from rasterio.warp import transform

from run_nike import run_analysis


class RunnerTests(unittest.TestCase):
    def make_image(self, path):
        data = np.full((4, 40, 40), 100, dtype="uint16")
        data[3, 10:30, 10:30] = 300
        data[:, 0, :] = 65535
        data[:, 5, 5] = 65535
        grid = from_origin(670000, 1540000, 1, 1)
        with rasterio.open(path, "w", driver="GTiff", count=4, width=40, height=40,
                           dtype="uint16", crs="EPSG:32647", transform=grid, nodata=65535) as dst:
            dst.write(data)
        return grid

    def test_real_file_roundtrip_preserves_grid_alpha_and_pending_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            grid = self.make_image(root / "source.tif")
            x, y = grid * (20.5, 20.5)
            lons, lats = transform("EPSG:32647", "EPSG:4326", [x], [y])
            registry = {"type": "FeatureCollection", "features": [{"type": "Feature", "id": "test",
                        "geometry": {"type": "Point", "coordinates": [lons[0], lats[0]]}, "properties": {}}]}
            (root / "parks.json").write_text(json.dumps(registry), encoding="utf-8")
            options = dict(scene_id="test", red_band=3, nir_band=4, registry_path=root / "parks.json")
            result = run_analysis(root / "source.tif", root / "out", **options)
            self.assertEqual(result["stats"]["retainedCandidateAreaM2"], 400)
            self.assertEqual(result["review_tasks"], 1)
            self.assertEqual(result["verified_parks"], 0)
            with rasterio.open(root / "out/candidate-mask.tif") as src:
                self.assertEqual(src.transform, from_origin(670000,1539999,1,1))
                self.assertEqual(src.crs.to_epsg(), 32647)
                self.assertEqual(src.read(1)[4, 5], 255)
            with rasterio.open(root / "out/heatmap.tif") as src:
                self.assertEqual(src.colorinterp[-1], ColorInterp.alpha)
                self.assertEqual(src.read(4)[4, 5], 0)
            with self.assertRaises(FileExistsError):
                run_analysis(root / "source.tif", root / "out", **options)

    def test_wrong_exclusion_grid_rejected_before_writing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_image(root / "source.tif")
            with rasterio.open(root / "exclude.tif", "w", driver="GTiff", count=1, width=40, height=40,
                               dtype="uint8", crs="EPSG:32647", transform=from_origin(0, 0, 1, 1)) as dst:
                dst.write(np.ones((40, 40), dtype="uint8"), 1)
            with self.assertRaises(ValueError):
                run_analysis(root / "source.tif", root / "out", scene_id="test", red_band=3, nir_band=4,
                             exclude_path=root / "exclude.tif")
            self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main()
