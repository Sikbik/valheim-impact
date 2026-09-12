import unittest
import numpy as np

from tools.validate_cutout_sampling import compare_mask


class CutoutSamplingTests(unittest.TestCase):
    def test_native_mask_matches_exact_cutoff(self):
        alpha = np.array([[0, 128, 175, 176, 230, 255]], dtype=np.uint8)
        mask = np.repeat(np.where(alpha[:, :, None] >= 176, 255, 0), 4, axis=2).astype(np.uint8)
        self.assertEqual(compare_mask(alpha, mask, .69)['disagreements'], 0)

    def test_reversed_orientation_is_rejected(self):
        alpha = np.array([[0, 40], [220, 255]], dtype=np.uint8)
        mask = np.repeat(np.where(alpha[::-1, :, None] >= 176, 255, 0), 4, axis=2).astype(np.uint8)
        with self.assertRaisesRegex(ValueError, 'away from cutoff'):
            compare_mask(alpha, mask, .69)

    def test_bad_mask_channels_are_rejected(self):
        alpha = np.array([[0, 255]], dtype=np.uint8)
        mask = np.zeros((1, 2, 4), dtype=np.uint8)
        mask[0, 1] = [255, 255, 255, 0]
        with self.assertRaisesRegex(ValueError, 'binary RGBA'):
            compare_mask(alpha, mask, .69)

    def test_one_boundary_texel_is_reported(self):
        alpha = np.full((20, 20), 255, dtype=np.uint8)
        alpha[0, 0] = 176
        mask = np.full((20, 20, 4), 255, dtype=np.uint8)
        mask[0, 0] = 0
        result = compare_mask(alpha, mask, .69)
        self.assertEqual(result['disagreements'], 1)
        self.assertEqual(result['native_passing_pixels'], 399)

    def test_large_threshold_disagreement_is_rejected(self):
        alpha = np.full((20, 20), 176, dtype=np.uint8)
        mask = np.zeros((20, 20, 4), dtype=np.uint8)
        with self.assertRaisesRegex(ValueError, 'too many'):
            compare_mask(alpha, mask, .69)

    def test_fractional_readback_reports_lost_sub_byte_alpha_precision(self):
        alpha = np.full((20, 20), 176, dtype=np.uint8)
        mask = np.zeros((20, 20, 4), dtype=np.uint8)
        self.assertEqual(compare_mask(alpha, mask, .69, quantized_native_alpha=True)['disagreements'], 400)

    def test_point_mask_uses_independent_native_color_only_for_cutoff_uncertainty(self):
        decoded = np.array([[126]], dtype=np.uint8)
        mask = np.full((1, 1, 4), 255, dtype=np.uint8)
        sampled = np.array([[128]], dtype=np.uint8)
        result = compare_mask(decoded, mask, .5, sampled_alpha=sampled)
        self.assertEqual(result['disagreements'], 1)
        self.assertEqual(compare_mask(decoded, mask, .5,
                                      sampled_alpha=np.array([[130]], dtype=np.uint8))['disagreements'], 1)
        rejected_mask = np.zeros((1, 1, 4), dtype=np.uint8)
        with self.assertRaisesRegex(ValueError, 'away from cutoff'):
            compare_mask(decoded, rejected_mask, .5, sampled_alpha=np.array([[130]], dtype=np.uint8))

    def test_invalid_shape_and_cutoff_are_rejected(self):
        for cutoff in [0, 1, float('nan'), True, '0.69']:
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                compare_mask(np.zeros((1, 1), dtype=np.uint8), np.zeros((1, 1, 4), dtype=np.uint8), cutoff)
        with self.assertRaises(ValueError):
            compare_mask(np.zeros((1, 1), dtype=np.uint8), np.zeros((2, 1, 4), dtype=np.uint8), .69)


if __name__ == '__main__':
    unittest.main()
