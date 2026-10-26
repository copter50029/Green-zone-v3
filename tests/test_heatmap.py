import unittest

import numpy as np

from greensight import make_heatmap


class HeatmapTests(unittest.TestCase):
    def test_inclusive_300m2_threshold_on_half_metre_grid(self):
        mask = np.zeros((45, 75), dtype="uint8")
        mask[:40, :30] = 1
        mask[:40, 40:70] = 1
        mask[39, 69] = 0
        original = mask.copy()
        result = make_heatmap(mask, pixel_m=0.5)
        self.assertEqual(result["stats"]["retainedCandidateAreaM2"], 300)
        self.assertEqual(result["stats"]["removedCandidateAreaM2"], 299.75)
        self.assertEqual(result["mask"].dtype, np.dtype("uint8"))
        np.testing.assert_array_equal(mask, original)

    def test_diagonal_contact_and_unknown_pixels_do_not_join_patches(self):
        mask = np.array([[1, 1, 2, 255], [1, 1, 2, 255], [0, 0, 1, 1], [0, 0, 1, 1]], dtype="uint8")
        result = make_heatmap(mask, pixel_m=1, min_area_m2=5)
        self.assertEqual(result["stats"]["retainedPatchCount"], 0)
        self.assertFalse((result["mask"] == 1).any())

    def test_green_core_red_fade_and_transparent_nodata(self):
        mask = np.zeros((20, 75), dtype="uint8")
        mask[:, :15] = 1
        mask[:, 74] = 255
        rgba = make_heatmap(mask, pixel_m=1)["rgba"]
        self.assertEqual(rgba.shape, (20, 75, 4))
        np.testing.assert_array_equal(rgba[0, 0], [0, 180, 65, 235])
        self.assertGreater(rgba[0, 15, 3], rgba[0, 25, 3])
        self.assertEqual(rgba[0, 65, 3], 0)
        self.assertTrue(np.all(rgba[:, 74] == 0))

    def test_radius_uses_metres_at_different_pixel_sizes(self):
        mask = np.zeros((3, 15), dtype="uint8")
        mask[:, 0] = 1
        rgba = make_heatmap(mask, pixel_m=5, min_area_m2=1, radius_m=10)["rgba"]
        self.assertGreater(rgba[1, 1, 3], 0)
        self.assertEqual(rgba[1, 2, 3], 0)

    def test_no_retained_seeds_never_create_fake_halos(self):
        for mask in (np.zeros((10, 10), dtype="uint8"), np.full((10, 10), 255, dtype="uint8")):
            result = make_heatmap(mask, pixel_m=1)
            self.assertTrue(np.all(result["rgba"] == 0))
            self.assertEqual(result["stats"]["retainedCandidateAreaM2"], 0)

    def test_all_styles_keep_the_same_mask_area_and_nodata(self):
        mask = np.zeros((10, 20), dtype="uint8")
        mask[:, :5] = 1
        mask[:, 19] = 255
        results = [make_heatmap(mask, 1, min_area_m2=5, style=style) for style in ("red", "spectrum", "grid")]
        for result in results:
            np.testing.assert_array_equal(result["mask"], results[0]["mask"])
            self.assertEqual(result["stats"], results[0]["stats"])
            self.assertTrue(np.all(result["rgba"][:, 19] == 0))

    def test_invalid_inputs_are_rejected(self):
        for pixel in (0, -1, float("nan"), float("inf"), True, "0.5", 1e200):
            with self.subTest(pixel=pixel), self.assertRaises(ValueError):
                make_heatmap([[1]], pixel)
        for mask in ([[256]], [[float("nan")]], np.zeros((0, 2)), np.zeros((2, 2, 2))):
            with self.assertRaises(ValueError):
                make_heatmap(mask, 1)
        for options in ({"min_area_m2": 0}, {"radius_m": 1}, {"radius_m": 10.5}, {"style": "temperature"}):
            with self.assertRaises(ValueError):
                make_heatmap([[1]], 1, **options)

    def test_cleanup_breaks_thin_bridges_before_size_filter(self):
        mask=np.zeros((65,110),dtype='uint8')
        mask[10:40,5:35]=1
        mask[20:30,70:80]=1
        mask[25,35:70]=1
        mask[:,100:]=255
        mask[50,50]=2
        original=mask.copy()
        result=make_heatmap(mask,1,clean_radius_m=2)
        self.assertGreater(result['stats']['morphologyRemovedPixels'],0)
        self.assertTrue((result['mask'][20:30,70:80]==0).all())
        self.assertTrue((result['mask'][25,40:70]==0).all())
        self.assertEqual(result['mask'][50,50],2)
        self.assertFalse(((result['mask']==1)&(mask!=1)).any())
        self.assertTrue((result['rgba'][:,100:]==0).all())
        np.testing.assert_array_equal(mask,original)

    def test_cleanup_rejects_invalid_or_excessive_kernels(self):
        for radius in (-1,True,float('nan'),11):
            with self.assertRaises(ValueError): make_heatmap([[1]],.5,clean_radius_m=radius)
        with self.assertRaises(ValueError): make_heatmap([[1]],.01,clean_radius_m=2)


if __name__ == "__main__":
    unittest.main()
