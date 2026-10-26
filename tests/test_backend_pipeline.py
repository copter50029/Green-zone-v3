"""Exercise the complete entry point using small real raster files."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform

from run_backend import run_backend
from greensight.park_lookup import DON_MUEANG


class BackendPipelineTests(unittest.TestCase):
    def prepare(self, root):
        grid = from_origin(670000, 1540000, 1, 1)
        data = np.full((4, 40, 40), 100, dtype='uint16')
        data[3, 10:30, 10:30] = 300
        for name in ('one', 'two', 'three'):
            with rasterio.open(root / (name + '.tif'), 'w', driver='GTiff', width=40,
                               height=40, count=4, dtype='uint16', crs='EPSG:32647',
                               transform=grid, nodata=65535) as dst:
                dst.write(data)
        x, y = grid * (20.5, 20.5)
        lon, lat = transform('EPSG:32647', 'EPSG:4326', [x], [y])
        registry = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'id': 'park',
                    'geometry': {'type': 'Point', 'coordinates': [lon[0], lat[0]]},
                    'properties': {'districts': [DON_MUEANG]}}]}
        (root / 'parks.json').write_text(json.dumps(registry), encoding='utf-8')
        (root / 'empty.json').write_text(json.dumps({'type': 'FeatureCollection', 'features': []}))
        (root / 'policy.json').write_text(json.dumps({'target': 'eligible_green', 'purpose': 'area_exclusion', 'features': []}))
        (root / 'pending.json').write_text(json.dumps({'purpose': 'pending_review_areas', 'features': []}))
        config = {'registry': 'parks.json', 'policy_exclusions': 'policy.json',
                  'pending_areas': 'pending.json', 'scenes': [
                      {'id': name, 'path': name + '.tif', 'context': 'empty.json',
                       'red_band': 3, 'nir_band': 4} for name in ('one', 'two', 'three')]}
        (root / 'config.json').write_text(json.dumps(config))

    def test_three_scenes_lookup_and_audit_from_another_working_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.prepare(root)
            result = run_backend('config.json', 'results', project_root=root)
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(len(result['audits']), 3)
            for scene, park, audit in zip(result['scenes'], result['park_lookup'], result['audits']):
                self.assertEqual(scene['stats']['retainedCandidateAreaM2'], 400)
                self.assertEqual(park['registry_points_in_valid_image'], 1)
                self.assertEqual(park['verified_parks'], 0)
                self.assertEqual(audit['software_consistency'], 'passed')
                self.assertTrue((root / 'results/analysis' / scene['scene_id'] / 'heatmap.png').is_file())
            with self.assertRaises(FileExistsError):
                run_backend('config.json', 'results', project_root=root)
            (root / 'three.tif').unlink()
            with self.assertRaises(FileNotFoundError):
                run_backend('config.json', 'missing', project_root=root)
            self.assertFalse((root / 'missing').exists())

    def test_failed_stage_is_not_reported_as_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.prepare(root)
            with patch('run_backend.run_all', side_effect=ValueError('test failure')):
                with self.assertRaises(ValueError):
                    run_backend('config.json', 'results', project_root=root)
            status = json.loads((root / 'results/status.json').read_text())
            self.assertEqual(status['status'], 'failed')
            self.assertEqual(status['stage'], 'analysis')
            self.assertFalse((root / 'results/summary.json').exists())
