import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import sys
import shutil

import numpy as np
from PIL import Image
import texture2ddecoder

from tools import asset_pipeline
from tools.cutout_mips import preserve_cutout_coverage, report_chain
from tools.validate_staging import cutout_coverage_measurement


class CutoutMipTests(unittest.TestCase):
    cutoff = 0.69
    cutoff_byte = 176

    @staticmethod
    def image(alpha):
        pixels = np.full((*alpha.shape, 4), 255, dtype=np.uint8)
        pixels[:, :, 3] = alpha
        return Image.fromarray(pixels)

    def test_opt_in_restores_tail_that_ordinary_mips_lose(self):
        alpha = np.zeros((4, 4), dtype=np.uint8)
        alpha[:3, :3] = 255
        source = self.image(alpha)
        ordinary = asset_pipeline.mip_chain(source, 'albedo')
        corrected = asset_pipeline.mip_chain(source, 'albedo', alpha_cutoff=self.cutoff)
        self.assertEqual(int((np.asarray(ordinary[-1])[:, :, 3] >= self.cutoff_byte).sum()), 0)
        self.assertEqual(int((np.asarray(corrected[-1])[:, :, 3] >= self.cutoff_byte).sum()), 1)
        np.testing.assert_array_equal(np.asarray(corrected[0]), np.asarray(source))

    def test_zero_alpha_is_preserved(self):
        alpha = np.array([[0, 40], [160, 255]], dtype=np.uint8)
        adjusted, _ = preserve_cutout_coverage(alpha, self.cutoff, 0.75)
        self.assertEqual(int(adjusted[0, 0]), 0)

    def test_tied_values_are_not_split_to_force_target_count(self):
        alpha = np.full((2, 2), 100, dtype=np.uint8)
        adjusted, metrics = preserve_cutout_coverage(alpha, self.cutoff, 0.5)
        passing = int((adjusted >= self.cutoff_byte).sum())
        self.assertEqual(passing, 0)
        self.assertEqual(len(np.unique(adjusted)), 1)
        self.assertTrue(metrics['target_unattainable'])
        self.assertEqual(metrics['coverage_quantum'], 0.25)

    def test_unattainable_one_pixel_tail_reports_actual_precision(self):
        adjusted, metrics = preserve_cutout_coverage(np.array([[120]], dtype=np.uint8), self.cutoff, 0.4)
        self.assertEqual(float((adjusted >= self.cutoff_byte).mean()), 0.0)
        self.assertEqual(metrics['achieved_coverage'], 0.0)
        self.assertEqual(metrics['coverage_error'], -0.4)
        self.assertEqual(metrics['coverage_quantum'], 1.0)
        self.assertTrue(metrics['target_unattainable'])

    def test_corrected_alpha_is_not_recursively_filtered(self):
        alpha = np.zeros((8, 8), dtype=np.uint8)
        alpha[:5, :5] = 255
        source = self.image(alpha)
        ordinary = asset_pipeline.mip_chain(source, 'albedo')
        corrected = asset_pipeline.mip_chain(source, 'albedo', alpha_cutoff=self.cutoff)
        expected, _ = preserve_cutout_coverage(
            np.asarray(ordinary[2])[:, :, 3], self.cutoff,
            float((alpha >= self.cutoff_byte).mean()))
        np.testing.assert_array_equal(np.asarray(corrected[2])[:, :, 3], expected)

    def test_option_rejects_bad_type_range_and_non_albedo_role(self):
        image = Image.new('RGBA', (2, 2), (255, 255, 255, 255))
        for value in (True, '0.69', 0, 1, -0.1, 1.1, float('nan')):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                asset_pipeline.mip_chain(image, 'albedo', alpha_cutoff=value)
        with self.assertRaises(ValueError):
            asset_pipeline.mip_chain(image, 'normal', alpha_cutoff=self.cutoff)

    def test_build_rejects_alpha_cutoff_for_opaque_asset_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new('RGBA', (4, 4), (255, 255, 255, 255)).save(root / 'source.png')
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'assets': [{'id': 'opaque', 'source': 'source.png',
                'size': [4, 4], 'periodic': False, 'alpha_policy': 'opaque',
                'alpha_cutoff': self.cutoff, 'normal_strength': 0}]}))
            with patch.object(asset_pipeline, 'ROOT', root), self.assertRaises(ValueError):
                asset_pipeline.build(manifest)
            self.assertFalse((root / 'build').exists())

    def test_explicit_cutoff_accepts_real_alpha_without_255_and_rejects_no_passing_texels(self):
        for maximum, succeeds in ((253, True), (175, False)):
            with self.subTest(maximum=maximum), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pixels = np.zeros((4, 4, 4), dtype=np.uint8)
                pixels[:, :, :3] = 120
                pixels[:2, :, 3] = maximum
                Image.fromarray(pixels).save(root / 'source.png')
                manifest = root / 'manifest.json'
                manifest.write_text(json.dumps({'assets': [{'id': 'corner', 'source': 'source.png',
                    'size': [4, 4], 'periodic': False, 'alpha_policy': 'cutout',
                    'alpha_cutoff': self.cutoff, 'normal_strength': 0}]}))
                with patch.object(asset_pipeline, 'ROOT', root):
                    if succeeds:
                        asset_pipeline.build(manifest)
                        record = json.loads((root / 'build/staging/meadows/manifest.json').read_text())
                        self.assertEqual(record['assets'][0]['alpha_range'], [0, maximum])
                    else:
                        with self.assertRaises(ValueError):
                            asset_pipeline.build(manifest)

    def test_direct_asset_pipeline_cli_supports_cutout_imports(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'tools').mkdir()
            shutil.copy2(project / 'tools/asset_pipeline.py', root / 'tools/asset_pipeline.py')
            shutil.copy2(project / 'tools/cutout_mips.py', root / 'tools/cutout_mips.py')
            pixels = np.zeros((4, 4, 4), dtype=np.uint8)
            pixels[:, :, :3] = 100
            pixels[:2, :, 3] = 253
            Image.fromarray(pixels).save(root / 'source.png')
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'assets': [{'id': 'corner', 'source': 'source.png',
                'size': [4, 4], 'periodic': False, 'alpha_policy': 'cutout',
                'alpha_cutoff': self.cutoff, 'normal_strength': 0}]}))
            completed = subprocess.run([sys.executable, str(root / 'tools/asset_pipeline.py'), str(manifest)],
                cwd=root, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((root / 'build/staging/meadows/manifest.json').is_file())

    def test_default_opaque_and_normal_chains_are_unchanged(self):
        pixels = np.random.default_rng(4).integers(0, 256, (8, 8, 4), dtype=np.uint8)
        pixels[:, :, 3] = 255
        image = Image.fromarray(pixels)
        for role in ('albedo', 'normal'):
            before = asset_pipeline.mip_chain(image, role)
            after = asset_pipeline.mip_chain(image, role, alpha_cutoff=None)
            self.assertEqual([m.tobytes() for m in before], [m.tobytes() for m in after])

    def test_bc3_coverage_is_measured_at_the_actual_cutoff_for_every_mip(self):
        alpha = np.zeros((8, 8), dtype=np.uint8)
        alpha[:6, :6] = 255
        mips = asset_pipeline.mip_chain(self.image(alpha), 'albedo', alpha_cutoff=self.cutoff)
        blob = asset_pipeline.encode_dds(mips)
        offset = 128
        for mip in mips:
            size = max(1, (mip.width + 3) // 4) * max(1, (mip.height + 3) // 4) * 16
            raw = texture2ddecoder.decode_bc3(blob[offset:offset + size], mip.width, mip.height)
            decoded = np.asarray(Image.frombytes('RGBA', mip.size, raw, 'raw', 'BGRA'))
            expected = float((np.asarray(mip)[:, :, 3] >= self.cutoff_byte).mean())
            actual = float((decoded[:, :, 3] >= self.cutoff_byte).mean())
            self.assertLessEqual(abs(actual - expected), 1 / (mip.width * mip.height))
            offset += size

    def test_real_straw_tail_remains_visible_after_bc3(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('straw-fringe-standard-v1.png', 'straw-fringe-corner-v1.png'):
            with self.subTest(name=name):
                source = Image.open(root / 'assets/meadows' / name).convert('RGBA')
                mips = asset_pipeline.mip_chain(source, 'albedo', alpha_cutoff=self.cutoff)
                blob = asset_pipeline.encode_dds(mips)
                offset = 128
                decoded_coverages = []
                for mip in mips:
                    size = max(1, (mip.width + 3) // 4) * max(1, (mip.height + 3) // 4) * 16
                    raw = texture2ddecoder.decode_bc3(blob[offset:offset + size], mip.width, mip.height)
                    decoded = np.asarray(Image.frombytes('RGBA', mip.size, raw, 'raw', 'BGRA'))
                    decoded_coverages.append(float((decoded[:, :, 3] >= self.cutoff_byte).mean()))
                    offset += size
                self.assertGreater(decoded_coverages[-2], 0, '2x2 BC3 tail disappeared')
                self.assertGreater(decoded_coverages[-1], 0, '1x1 BC3 tail disappeared')

    def test_real_one_pixel_tail_uses_confident_alpha_without_changing_rgb(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('straw-fringe-standard-v1.png', 'straw-fringe-corner-v1.png'):
            with self.subTest(name=name):
                source = Image.open(root / 'assets/meadows' / name).convert('RGBA')
                ordinary = asset_pipeline.mip_chain(source, 'albedo')[-1]
                corrected = asset_pipeline.mip_chain(source, 'albedo', alpha_cutoff=self.cutoff)[-1]
                self.assertEqual(int(np.asarray(corrected)[0, 0, 3]), 255)
                np.testing.assert_array_equal(np.asarray(corrected)[0, 0, :3],
                                              np.asarray(ordinary)[0, 0, :3])

    def test_tall_grass_coarse_mips_survive_bc3_with_truthful_uniform_scale_report(self):
        root = Path(__file__).resolve().parents[1]
        source = Image.open(root / 'assets/meadows/grass-tall-rgba-v1.png').convert('RGBA')
        cutoff, threshold = 0.46000000834465027, 118
        for size in (512, 256):
            with self.subTest(size=size):
                base = asset_pipeline.fit_albedo(source, (size, size))
                ordinary = asset_pipeline.mip_chain(base, 'albedo')
                corrected = asset_pipeline.mip_chain(base, 'albedo', alpha_cutoff=cutoff)
                report = report_chain(corrected, cutoff, ordinary_mips=ordinary)
                blob = asset_pipeline.encode_dds(corrected)
                offset = 128
                for level, mip in enumerate(corrected):
                    length = max(1, (mip.width + 3) // 4) * max(1, (mip.height + 3) // 4) * 16
                    raw = texture2ddecoder.decode_bc3(blob[offset:offset + length], mip.width, mip.height)
                    decoded = np.asarray(Image.frombytes('RGBA', mip.size, raw, 'raw', 'BGRA'))[:, :, 3]
                    pixels = np.asarray(mip)
                    measurement = cutout_coverage_measurement(pixels[:, :, 3], decoded, cutoff)
                    self.assertLessEqual(abs(measurement['coverage_delta']),
                                         measurement['allowed_coverage_delta'], (size, mip.size))
                    self.assertEqual(report['mips'][level]['coverage'], measurement['coverage'])
                    if mip.size == (32, 32):
                        original_pixels = np.asarray(ordinary[level])
                        original_alpha = original_pixels[:, :, 3]
                        np.testing.assert_array_equal(pixels[:, :, :3], original_pixels[:, :, :3])
                        self.assertTrue(np.all(pixels[:, :, 3][original_alpha == 0] == 0))
                        for value in np.unique(original_alpha):
                            self.assertEqual(len(np.unique(pixels[:, :, 3][original_alpha == value])), 1)
                        scale = report['mips'][level]['alpha_scale']
                        expected_alpha = np.rint(np.clip(original_alpha.astype(float) * scale, 0, 255)).astype(np.uint8)
                        np.testing.assert_array_equal(pixels[:, :, 3], expected_alpha)
                        self.assertLessEqual(abs(float((decoded >= threshold).mean()) - report['authored_base_coverage']),
                                             measurement['allowed_coverage_delta'])
                    offset += length

    def test_coarse_mip_with_matching_bc3_coverage_keeps_existing_alpha_adjustment(self):
        alpha = np.zeros((64, 64), dtype=np.uint8)
        alpha[:32] = 255
        source = self.image(alpha)
        ordinary = asset_pipeline.mip_chain(source, 'albedo')
        corrected = asset_pipeline.mip_chain(source, 'albedo', alpha_cutoff=self.cutoff)
        for level in (1, 2, 3):
            expected, _ = preserve_cutout_coverage(np.asarray(ordinary[level])[:, :, 3], self.cutoff, 0.5)
            np.testing.assert_array_equal(np.asarray(corrected[level])[:, :, 3], expected)

    def test_validator_uses_actual_cutoff_and_discrete_tail_tolerance(self):
        source = np.array([[170, 180]], dtype=np.uint8)
        decoded = np.array([[175, 180]], dtype=np.uint8)
        measured = cutout_coverage_measurement(source, decoded, self.cutoff)
        self.assertEqual(measured['coverage'], 0.5)
        self.assertEqual(measured['decoded_coverage'], 0.5)
        self.assertEqual(measured['coverage_quantum'], 0.5)
        self.assertEqual(measured['allowed_coverage_delta'], 1.01)

    def test_validator_rejects_complete_compressed_cutout_loss_despite_tail_tolerance(self):
        source = np.array([[176, 0], [0, 0]], dtype=np.uint8)
        decoded = np.zeros((2, 2), dtype=np.uint8)
        with self.assertRaises(ValueError):
            cutout_coverage_measurement(source, decoded, self.cutoff)


if __name__ == '__main__':
    unittest.main()
