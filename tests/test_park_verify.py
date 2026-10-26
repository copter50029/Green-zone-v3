import unittest

import numpy as np
from rasterio.transform import from_origin
from rasterio.warp import transform

from greensight import prepare_park_review, record_park_review


class ParkVerifyTests(unittest.TestCase):
    def setUp(self):
        self.coordinates = [100.5, 13.9]
        xs, ys = transform("EPSG:4326", "EPSG:32647", [100.5], [13.9])
        self.grid = from_origin(xs[0] - 5.5, ys[0] + 5.5, 1, 1)
        self.registry = {
            "type": "FeatureCollection", "sceneId": "scene_01",
            "source": {"snapshotDate": "2026-10-23"},
            "features": [{"type": "Feature", "id": "park-1", "properties": {"name": "Test park"},
                          "geometry": {"type": "Point", "coordinates": self.coordinates}}],
        }
        self.mask = np.zeros((15, 15), dtype="uint8")

    def prepare(self, **options):
        return prepare_park_review(self.registry, self.mask, self.grid, "EPSG:32647", scene_id="scene_01", **options)

    def test_nearby_vegetation_never_automatically_verifies_a_park(self):
        self.mask[5, 5] = 1
        task = self.prepare(imagery_date="2024-10-12")["features"][0]
        props = task["properties"]
        self.assertEqual(props["nearest_candidate_cell_m"], 0)
        self.assertEqual(props["candidate_area_m2_in_search"], 1)
        self.assertFalse(props["verified_park"])
        self.assertEqual(props["review_status"], "needs_review")
        self.assertTrue(props["different_years_need_review"])
        self.assertEqual(task["geometry"]["coordinates"], self.coordinates)

    def test_missing_search_coverage_is_not_hidden_at_image_edges(self):
        props = self.prepare(search_radius_m=20)["features"][0]["properties"]
        self.assertGreater(props["valid_search_fraction"], 0)
        self.assertLess(props["valid_search_fraction"], 1)

    def test_no_candidate_is_unknown_match_not_a_rejected_park(self):
        props = self.prepare()["features"][0]["properties"]
        self.assertIsNone(props["nearest_candidate_cell_m"])
        self.assertFalse(props["candidate_within_search"])
        self.assertEqual(props["review_status"], "needs_review")

    def test_nodata_reference_is_excluded_without_inventing_location(self):
        self.mask[5, 5] = 255
        result = self.prepare()
        self.assertEqual(result["features"], [])
        self.assertEqual(result["excluded_references"][0]["reason"], "nodata_or_outside_study_frame")

    def test_analysis_identity_includes_grid_shape_and_rejects_nonfinite_grid(self):
        original = self.prepare()["analysis_id"]
        self.mask = self.mask.reshape(9, 25)
        self.assertNotEqual(original, self.prepare()["analysis_id"])
        self.grid = from_origin(float("nan"), 100, 1, 1)
        with self.assertRaises(ValueError):
            self.prepare()

    def test_wrong_scene_crs_and_duplicate_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            prepare_park_review(self.registry, self.mask, self.grid, "EPSG:4326", scene_id="scene_01")
        with self.assertRaises(ValueError):
            prepare_park_review(self.registry, self.mask, self.grid, "EPSG:32647", scene_id="scene_02")
        self.registry["features"] *= 2
        with self.assertRaises(ValueError):
            self.prepare()

    def test_human_verification_requires_position_and_access_evidence(self):
        task = self.prepare()["features"][0]
        common = {"reviewer": "Unit-test reviewer", "reviewed_on": "2026-10-24", "decision": "verified_park"}
        with self.assertRaises(ValueError):
            record_park_review(task, evidence=[], **common)
        evidence = [{"url": "https://example.com/review-fixture", "observed_on": "2026-10-24", "scopes": ["position", "public_access"]}]
        reviewed = record_park_review(task, evidence=evidence, position_confirmed=True, public_access_confirmed=True, **common)
        self.assertTrue(reviewed["properties"]["verified_park"])
        self.assertFalse(task["properties"]["verified_park"])
        self.assertEqual(reviewed["geometry"], task["geometry"])

    def test_incomplete_or_unsafe_evidence_is_rejected(self):
        task = self.prepare()["features"][0]
        with self.assertRaises(ValueError):
            record_park_review(task, reviewer="", reviewed_on="2026-10-24", decision="needs_review", evidence=[])
        with self.assertRaises(ValueError):
            record_park_review(task, reviewer="Reviewer", reviewed_on="2026-10-24", decision="rejected", evidence=[], notes="")
        with self.assertRaises(ValueError):
            record_park_review(task, reviewer="Reviewer", reviewed_on="2026-10-24", decision="needs_review",
                               evidence=[{"url": "javascript:alert(1)", "observed_on": "2026-10-24", "scopes": ["position"]}])


if __name__ == "__main__":
    unittest.main()
