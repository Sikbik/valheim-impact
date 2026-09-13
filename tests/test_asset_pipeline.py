import importlib.util
import hashlib
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

    def test_build_albedo_only_preserves_cutout_payload_without_normal_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pixels = np.zeros((8, 8, 4), dtype=np.uint8)
            pixels[:4] = (48, 144, 64, 255)
            Image.fromarray(pixels).save(root / 'source.png')
            manifest = root / 'spec.json'
            manifest.write_text(json.dumps({'assets': [dict(id='sample', source='source.png',
                size=[8, 8], periodic=False, alpha_policy='cutout', alpha_cutoff=0.5,
                generate_normal=False)]}))
            original_convert = Image.Image.convert

            def reject_height_conversion(image, mode=None, *args, **kwargs):
                self.assertNotEqual(mode, 'L', 'Albedo-only output must skip height conversion')
                return original_convert(image, mode, *args, **kwargs)

            with patch.object(pipeline, 'ROOT', root), \
                    patch.object(Image.Image, 'convert', reject_height_conversion), \
                    patch.object(pipeline, 'normal_from_height', side_effect=AssertionError('Unexpected normal work')):
                pipeline.build(manifest)
            output = root / 'build/staging/meadows'
            self.assertEqual({path.name for path in output.iterdir()}, {
                'manifest.json', 'contact-sheet.png', 'sample_albedo.png',
                'sample_albedo.dds', 'sample_albedo-unity.dds'})
            report = json.loads((output / 'manifest.json').read_text())
            self.assertEqual(len(report['assets']), 1)
            record = report['assets'][0]
            self.assertEqual(record['id'], 'sample_albedo')
            self.assertEqual(record['role'], 'albedo')
            self.assertIs(record['srgb'], True)
            self.assertIsNone(record['normal_encoding'])
            self.assertEqual(record['alpha_policy'], 'cutout')
            self.assertEqual(record['alpha_range'], [0, 255])
            self.assertEqual(record['alpha_cutoff'], 0.5)
            self.assertEqual(len(record['cutout_mips']), 4)
            self.assertEqual(record['compressed_payload_bytes'], 112)
            self.assertEqual(report['compressed_payload_bytes'], 112)
            self.assertEqual(record['source_sha256'], hashlib.sha256((root / 'source.png').read_bytes()).hexdigest())
            np.testing.assert_array_equal(np.asarray(Image.open(output / record['png'])), pixels)
            for kind in ('png', 'dds', 'unity_dds'):
                data = (output / record[kind]).read_bytes()
                self.assertEqual(record[kind + '_sha256'], hashlib.sha256(data).hexdigest())
                if kind != 'png':
                    self.assertEqual(len(data), 240)
                    self.assertEqual(data[84:88], b'DXT5')
                    self.assertEqual(struct.unpack_from('<I', data, 28)[0], 4)
                    decoded = np.asarray(Image.open(io.BytesIO(data)).convert('RGBA'))
                    expected_alpha = pixels[:, :, 3] if kind == 'dds' else pixels[::-1, :, 3]
                    np.testing.assert_array_equal(decoded[:, :, 3], expected_alpha)

    def test_build_default_and_explicit_true_emit_identical_albedo_normal_pairs(self):
        reports, payloads = [], []
        for options in ({}, {'generate_normal': True}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                Image.new('RGB', (8, 8), 'green').save(root / 'source.png')
                manifest = root / 'spec.json'
                manifest.write_text(json.dumps({'assets': [dict(id='sample', source='source.png',
                    size=[8, 8], periodic=False, alpha_policy='opaque', normal_strength=0,
                    **options)]}))
                with patch.object(pipeline, 'ROOT', root):
                    pipeline.build(manifest)
                output = root / 'build/staging/meadows'
                report = json.loads((output / 'manifest.json').read_text())
                self.assertEqual([(r['id'], r['role']) for r in report['assets']],
                                 [('sample_albedo', 'albedo'), ('sample_normal', 'normal')])
                self.assertEqual(report['compressed_payload_bytes'], 224)
                self.assertEqual({p.name for p in output.iterdir()}, {'manifest.json', 'contact-sheet.png',
                    'sample_albedo.png', 'sample_albedo.dds', 'sample_albedo-unity.dds',
                    'sample_normal.png', 'sample_normal.dds', 'sample_normal-unity.dds'})
                reports.append(report)
                payloads.append({p.name: p.read_bytes() for p in output.iterdir()})
        self.assertEqual(reports[0], reports[1])
        self.assertEqual(payloads[0], payloads[1])

    def test_build_rejects_non_boolean_normal_flag_before_any_output_mutation(self):
        for flag in (None, 0, 1, 0.0, 'false', 'true', [], {}):
            for existing_output in (False, True):
                with self.subTest(flag=flag, existing_output=existing_output), \
                        tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    Image.new('RGB', (8, 8), 'green').save(root / 'source.png')
                    asset = dict(id='first', source='source.png', size=[8, 8], periodic=False,
                                 alpha_policy='opaque', normal_strength=0)
                    manifest = root / 'spec.json'
                    manifest.write_text(json.dumps({'assets': [asset, dict(asset, id='last', generate_normal=flag)]}))
                    output = root / 'build/staging/meadows'
                    prior = {'first_albedo.png': b'previous texture', 'manifest.json': b'previous manifest'}
                    if existing_output:
                        output.mkdir(parents=True)
                        for name, data in prior.items():
                            (output / name).write_bytes(data)
                    with patch.object(pipeline, 'ROOT', root), self.assertRaisesRegex(ValueError, 'generate_normal'):
                        pipeline.build(manifest)
                    if existing_output:
                        self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, prior)
                    else:
                        self.assertFalse(output.exists())

    def test_explicit_wrap_metadata_reaches_every_role_without_changing_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new('RGB', (8, 8), 'green').save(root / 'source.png')
            common = dict(source='source.png', size=[8, 8], periodic=False,
                          alpha_policy='opaque', normal_strength=0)
            manifest = root / 'spec.json'
            manifest.write_text(json.dumps({'assets': [dict(common, id='default'),
                dict(common, id='clamped', wrap_mode='clamp'),
                dict(common, id='repeated', wrap_mode='repeat')]}))
            with patch.object(pipeline, 'ROOT', root):
                pipeline.build(manifest)
            data = json.loads((root / 'build/staging/meadows/manifest.json').read_text())
            self.assertEqual([r['wrap_mode'] for r in data['assets']],
                             ['repeat', 'repeat', 'clamp', 'clamp', 'repeat', 'repeat'])
            for role in ('albedo', 'normal'):
                rows = [r for r in data['assets'] if r['role'] == role]
                self.assertEqual(len({r['dds_sha256'] for r in rows}), 1)

    def test_invalid_late_wrap_metadata_preserves_existing_outputs(self):
        for value in (None, True, 1, 'mirror', 'Clamp', [], {}):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                Image.new('RGB', (8, 8), 'green').save(root / 'source.png')
                asset = dict(id='first', source='source.png', size=[8, 8], periodic=False,
                             alpha_policy='opaque', generate_normal=False)
                manifest = root / 'spec.json'
                manifest.write_text(json.dumps({'assets': [asset, dict(asset, id='last', wrap_mode=value)]}))
                output = root / 'build/staging/meadows'
                output.mkdir(parents=True)
                marker = output / 'manifest.json'
                marker.write_bytes(b'prior valid output')
                with patch.object(pipeline, 'ROOT', root), self.assertRaisesRegex(ValueError, 'wrap_mode'):
                    pipeline.build(manifest)
                self.assertEqual(marker.read_bytes(), b'prior valid output')
                self.assertEqual({p.name for p in output.iterdir()}, {'manifest.json'})

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
