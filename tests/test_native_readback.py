import unittest
from types import SimpleNamespace
import numpy as np
from tools import validate_native
from tools.validate_native import compare_readback


class ReadbackTests(unittest.TestCase):
    def test_serialized_sampler_must_match_recipe_and_catalog_on_every_axis(self):
        for mode, number in (('repeat', 0), ('clamp', 1)):
            settings = SimpleNamespace(m_WrapU=number, m_WrapV=number, m_WrapW=number,
                                       m_FilterMode=2, m_Aniso=4, m_MipBias=0.0)
            texture = SimpleNamespace(m_TextureSettings=settings)
            record = {'id': 'fixture', 'wrapMode': mode}
            self.assertEqual(validate_native.validate_sampler(texture, record, mode), mode)
            for field in ('m_WrapU', 'm_WrapV', 'm_WrapW', 'm_FilterMode', 'm_Aniso'):
                original = getattr(settings, field)
                setattr(settings, field, original + 1)
                with self.subTest(mode=mode, field=field), self.assertRaisesRegex(ValueError, 'sampler'):
                    validate_native.validate_sampler(texture, record, mode)
                setattr(settings, field, original)
            for bias in (0.5, -0.5, float('nan'), float('inf'), -float('inf')):
                settings.m_MipBias = bias
                with self.subTest(mode=mode, bias=bias), self.assertRaisesRegex(ValueError, 'sampler'):
                    validate_native.validate_sampler(texture, record, mode)
            settings.m_MipBias = 0.0
            for invalid in (None, True, 'mirror', 'Clamp'):
                with self.assertRaisesRegex(ValueError, 'wrap_mode'):
                    validate_native.validate_sampler(texture, record, invalid)
            record['wrapMode'] = 'clamp' if mode == 'repeat' else 'repeat'
            with self.assertRaisesRegex(ValueError, 'sampler'):
                validate_native.validate_sampler(texture, record, mode)

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
