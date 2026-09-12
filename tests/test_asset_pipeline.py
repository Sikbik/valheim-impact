import importlib.util
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import json

import numpy as np
from PIL import Image

try:
    from tools import asset_pipeline as pipeline
except ImportError:
    pipeline = None


class AssetPipelineTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(pipeline, 'project-owned asset pipeline is required')

    def test_alpha_is_exact_and_never_taken_from_generated_preview(self):
        rgb = Image.new('RGB', (8, 4), 'green')
        mask = Image.fromarray(np.arange(32, dtype=np.uint8).reshape(4, 8))
        result = pipeline.fit_albedo(rgb, (8, 4), alpha=mask)
        np.testing.assert_array_equal(np.asarray(result)[:, :, 3], np.asarray(mask))
        with self.assertRaises(ValueError):
            pipeline.fit_albedo(rgb, (16, 8), alpha=mask)

    def test_periodic_rgb_preserves_alpha(self):
        pixels = np.random.default_rng(1).integers(0, 256, (16, 16, 4), dtype=np.uint8)
        result = np.asarray(pipeline.fit_albedo(Image.fromarray(pixels), (16, 16), periodic=True))
        np.testing.assert_array_equal(result[0, :, :3], result[-1, :, :3])
        np.testing.assert_array_equal(result[:, 0, :3], result[:, -1, :3])
        np.testing.assert_array_equal(result[:, :, 3], pixels[:, :, 3])

    def test_mips_filter_albedo_in_linear_light(self):
        pixels = np.zeros((2, 2, 4), dtype=np.uint8)
        pixels[:, 1, :3] = 255
        pixels[:, :, 3] = 255
        final = np.asarray(pipeline.mip_chain(Image.fromarray(pixels), 'albedo')[-1])
        self.assertTrue(186 <= int(final[0, 0, 0]) <= 189)

    def test_transparent_rgb_does_not_bleed_into_visible_mips(self):
        pixels = np.zeros((2, 2, 4), dtype=np.uint8)
        pixels[:, 0] = (255, 0, 0, 255)
        pixels[:, 1] = (0, 0, 255, 0)
        final = np.asarray(pipeline.mip_chain(Image.fromarray(pixels), 'albedo')[-1])
        self.assertGreater(final[0, 0, 0], 250)
        self.assertLess(final[0, 0, 2], 3)

    def test_normal_encoding_has_correct_png_to_unity_slope(self):
        yy, xx = np.mgrid[0:8, 0:8]
        normal = np.asarray(pipeline.normal_from_height((xx + yy) / 16, strength=1, periodic=False))
        self.assertLess(normal[3, 3, 3], 128)  # tangent X in A
        self.assertGreater(normal[3, 3, 1], 128)  # PNG down becomes Unity up
        self.assertTrue(np.all(normal[:, :, (0, 2)] == 255))

    def test_dxt5_full_chain_decodes_upright(self):
        pixels = np.zeros((8, 16, 4), dtype=np.uint8)
        pixels[:4] = (255, 0, 0, 255)
        pixels[4:] = (0, 0, 255, 255)
        mips = pipeline.mip_chain(Image.fromarray(pixels), 'albedo')
        encoded = pipeline.encode_dds(mips)
        self.assertEqual([(im.width, im.height) for im in mips], [(16, 8), (8, 4), (4, 2), (2, 1), (1, 1)])
        self.assertEqual(len(encoded), 128 + pipeline.bc3_bytes(16, 8))
        self.assertEqual(struct.unpack_from('<I', encoded, 28)[0], 5)
        decoded = np.asarray(Image.open(io.BytesIO(encoded)).convert('RGBA'))
        self.assertGreater(decoded[0, 0, 0], 240)
        self.assertGreater(decoded[-1, 0, 2], 240)

    def test_release_input_rejects_symlinks_even_inside_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'owned.png').write_bytes(b'owned')
            (root / 'link.png').symlink_to(root / 'owned.png')
            with self.assertRaises(ValueError):
                pipeline.safe_file(root, 'link.png')
            (root / 'folder').mkdir()
            (root / 'dirlink').symlink_to(root / 'folder', target_is_directory=True)
            with self.assertRaises(ValueError):
                pipeline.safe_file(root, 'dirlink/a.png')

    def test_unity_payload_flips_storage_rows_without_changing_normal_sign(self):
        pixels = np.zeros((8, 8, 4), dtype=np.uint8)
        pixels[:4] = (255, 96, 255, 64)
        pixels[4:] = (255, 160, 255, 192)
        mips = pipeline.mip_chain(Image.fromarray(pixels), 'normal')
        decoded = np.asarray(Image.open(io.BytesIO(pipeline.encode_unity_dds(mips))).convert('RGBA'))
        self.assertGreater(decoded[0, 0, 3], 180)
        self.assertLess(decoded[-1, 0, 3], 75)

    def test_release_input_rejects_traversal_and_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in ['../outside.png', '/etc/passwd', 'original.resS', 'pack.dat']:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    pipeline.safe_file(Path(directory), path)

    def test_build_preflights_linked_outputs_before_writing_any_texture(self):
        for linked_directory in (True, False):
            with self.subTest(linked_directory=linked_directory), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / 'project'
                root.mkdir()
                outside = Path(directory) / 'outside'
                outside.mkdir()
                untouched = outside / 'untouched.png'
                untouched.write_bytes(b'preserve me')
                Image.new('RGB', (8, 8), 'green').save(root / 'source.png')
                manifest = root / 'spec.json'
                manifest.write_text(json.dumps({'assets':[dict(id='sample', source='source.png', size=[8,8],
                    periodic=False, alpha_policy='opaque', normal_strength=0)]}))
                (root / 'build/staging').mkdir(parents=True)
                output = root / 'build/staging/meadows'
                if linked_directory:
                    output.symlink_to(outside, target_is_directory=True)
                else:
                    output.mkdir()
                    (output / 'sample_normal.png').symlink_to(untouched)
                with patch.object(pipeline, 'ROOT', root), self.assertRaises(ValueError):
                    pipeline.build(manifest)
                self.assertEqual(untouched.read_bytes(), b'preserve me')
                self.assertFalse((output / 'sample_albedo.png').exists())


if __name__ == '__main__':
    unittest.main()
