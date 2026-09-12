import unittest
import numpy as np
from tools.validate_native import compare_readback


class ReadbackTests(unittest.TestCase):
    def test_srgb_decodes_rgb_without_changing_alpha(self):
        reference = np.array([[[128, 128, 128, 128]]], dtype=np.uint8)
        actual = np.array([[[55, 55, 55, 128]]], dtype=np.uint8)
        self.assertLess(compare_readback(reference, actual, True)['max_error'], 1)

    def test_inverted_storage_rows_fail_readback(self):
        reference = np.array([[[0, 0, 0, 255]], [[255, 128, 64, 255]]], dtype=np.uint8)
        with self.assertRaisesRegex(ValueError, 'GPU readback'):
            compare_readback(reference, reference[::-1], False)

    def test_normal_alpha_channel_is_validated(self):
        reference = np.array([[[255, 128, 255, 64]]], dtype=np.uint8)
        bad = reference.copy()
        bad[0, 0, 3] = 192
        with self.assertRaisesRegex(ValueError, 'GPU readback'):
            compare_readback(reference, bad, False)

    def test_size_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            compare_readback(np.zeros((2, 2, 4)), np.zeros((1, 1, 4)), False)
