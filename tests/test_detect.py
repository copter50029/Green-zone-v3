import unittest
import numpy as np
from greensight import detect_green


class DetectTests(unittest.TestCase):
    def test_uint16_subtraction_thresholds_and_missing_data(self):
        image = np.array([[[100, 100, 100, 0, 65535]],
                          [[50, 150, 300, 0, 65535]]], dtype="uint16")
        mask = detect_green(image, red_band=1, nir_band=2, nodata=65535)
        np.testing.assert_array_equal(mask, [[0, 2, 1, 2, 255]])
        self.assertEqual(image[0, 0, 0], 100)

    def test_exclusions_remove_candidates_without_filling_nodata(self):
        image = np.array([[[100, 100, 100]], [[300, 300, 300]]])
        mask = detect_green(image, red_band=1, nir_band=2,
                            valid_mask=np.array([[True, True, False]]),
                            exclude_mask=np.array([[True, False, True]]))
        np.testing.assert_array_equal(mask, [[0, 1, 255]])

    def test_requires_distinct_bands_and_aligned_boolean_masks(self):
        image = np.ones((4, 2, 2))
        for options in ({"red_band": 3, "nir_band": 3},
                        {"red_band": 0, "nir_band": 4},
                        {"red_band": 3, "nir_band": 4, "threshold": np.nan},
                        {"red_band": 3, "nir_band": 4, "exclude_mask": np.zeros((2, 2))}):
            with self.assertRaises(ValueError):
                detect_green(image, **options)


if __name__ == "__main__":
    unittest.main()
