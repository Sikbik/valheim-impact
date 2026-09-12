import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from tools import fit_straw_fringe as fringe


def authored_fixture(size=8):
    pixels = np.zeros((size, size, 4), dtype=np.uint8)
    pixels[:, :, :3] = (90, 50, 20)
    pixels[:size // 2, :, :] = (230, 170, 75, 255)
    return Image.fromarray(pixels)


class StrawFringeTests(unittest.TestCase):
    def test_fits_complete_image_without_flipping_cropping_or_forcing_edges(self):
        image = fringe.fit_fringe(authored_fixture(), 4)
        self.assertEqual(image.size, (4, 4))
        pixels = np.asarray(image)
        self.assertTrue(np.all(pixels[:2, :, :] == (230, 170, 75, 255)))
        self.assertTrue(np.all(pixels[2:, :, 3] == 0))
        self.assertFalse(np.array_equal(pixels[0], pixels[-1]))

    def test_same_size_preserves_every_authored_rgba_byte(self):
        image = authored_fixture()
        image.putpixel((2, 3), (200, 80, 20, 175))
        image.putpixel((5, 6), (20, 40, 220, 176))
        self.assertEqual(fringe.fit_fringe(image, 8).tobytes(), image.tobytes())

    def test_resampling_is_alpha_weighted_linear_rgb(self):
        pixels = np.zeros((4, 4, 4), dtype=np.uint8)
        pixels[:2, :2] = (255, 0, 0, 0)  # Unseen red must not tint the edge.
        pixels[0, 0] = (255, 255, 255, 255)
        pixels[0, 1] = (0, 0, 0, 255)
        pixels[2:, 2:] = (200, 100, 30, 255)
        result = np.asarray(fringe.fit_fringe(Image.fromarray(pixels), 2))
        self.assertTrue(np.all(np.abs(result[0, 0, :3].astype(int) - 188) <= 1))
        self.assertEqual(int(result[0, 0, 3]), 128)
        self.assertEqual(tuple(result[1, 1]), (200, 100, 30, 255))

    def test_rejects_non_rgba_flat_alpha_non_square_and_invalid_sizes(self):
        invalid = [Image.new('RGB', (8, 8)), Image.new('RGBA', (8, 8), (1, 2, 3, 255)),
                   Image.new('RGBA', (8, 8), (1, 2, 3, 0)),
                   Image.new('RGBA', (8, 8), (1, 2, 3, 170)),
                   Image.new('RGBA', (8, 8), (1, 2, 3, 200)),
                   Image.new('RGBA', (8, 4)), Image.new('RGBA', (4097, 1))]
        for image in invalid:
            with self.subTest(mode=image.mode, size=image.size, alpha=image.getpixel((0, 0))):
                with self.assertRaises(ValueError):
                    fringe.fit_fringe(image, 8)
        for size in (0, -1, 3, 1024, True, 4.0):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    fringe.fit_fringe(authored_fixture(), size)

    def test_rejects_cutout_lost_during_downsampling(self):
        image = Image.new('RGBA', (8, 8), (100, 50, 20, 255))
        image.putpixel((0, 0), (100, 50, 20, 0))
        with self.assertRaisesRegex(ValueError, 'fitted'):
            fringe.fit_fringe(image, 2)

    def test_metrics_use_saved_cutoff_and_report_mip_loss_without_claiming_validation(self):
        pixels = np.array([[(20, 30, 40, 175), (20, 30, 40, 176)],
                           [(20, 30, 40, 0), (20, 30, 40, 255)]], dtype=np.uint8)
        report = fringe.validate_fringe(Image.fromarray(pixels), 'standard')
        self.assertEqual(report['cutoff'], 0.69)
        self.assertEqual(report['cutoff_byte_minimum'], 176)
        self.assertEqual([m['dimensions'] for m in report['mips']], [[2, 2], [1, 1]])
        self.assertEqual(report['mips'][0]['passing_pixels'], 2)
        self.assertEqual(report['mips'][0]['coverage'], 0.5)
        self.assertEqual(report['mips'][0]['alpha_counts'], {'zero': 1, 'opaque': 1, 'intermediate': 2})
        self.assertEqual(report['mips'][1]['passing_pixels'], 0)
        self.assertIn(1, report['mips_without_cutout'])
        self.assertEqual(report['reference_comparison']['coverage'], 2446 / 4096)
        self.assertFalse(report['reference_comparison']['used_to_modify_alpha'])
        self.assertFalse(report['native_shader_validated'])
        self.assertFalse(report['compressed_mips_validated'])
        corner = fringe.validate_fringe(Image.fromarray(pixels), 'corner')
        self.assertEqual(corner['reference_comparison']['coverage'], 2427 / 4096)
        self.assertEqual(report['mips'], corner['mips'])


class StrawFringeBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.assets = self.root / 'assets'
        self.assets.mkdir()
        self.source = self.assets / 'authored.png'
        authored_fixture().save(self.source)
        self.source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.provenance_path = self.assets / 'provenance.json'
        self.provenance = {'schema_version': 1, 'assets': [
            {'dest': 'assets/authored.png', 'sha256': self.source_hash, 'original_game_pixels': False,
             'original_masks_used': False, 'tool': 'synthetic test fixture'}]}
        self.recipe_path = self.assets / 'recipe.json'
        self.recipe = {'schema_version': 1, 'variant': 'standard', 'size': 512,
                       'source': {'path': 'assets/authored.png', 'sha256': self.source_hash},
                       'output': 'assets/fitted.png', 'report': 'assets/validation.json'}
        self.write_inputs()
        root_patch = patch.object(fringe, 'ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def write_inputs(self):
        self.provenance_path.write_text(json.dumps(self.provenance))
        self.recipe_path.write_text(json.dumps(self.recipe))

    def test_build_is_deterministic_authored_only_and_preserves_inputs(self):
        originals = {p: p.read_bytes() for p in (self.source, self.recipe_path, self.provenance_path)}
        first = fringe.build(self.recipe_path)
        output = self.assets / 'fitted.png'
        report_path = self.assets / 'validation.json'
        initial = (output.read_bytes(), report_path.read_bytes())
        self.assertEqual(first, json.loads(initial[1]))
        self.assertIs(first['original_game_pixels'], False)
        self.assertIs(first['original_masks_used'], False)
        self.assertEqual(first['source']['sha256'], self.source_hash)
        self.assertEqual(first['sha256'], hashlib.sha256(initial[0]).hexdigest())
        self.assertEqual(first['dimensions'], [512, 512])
        self.assertEqual(len(first['mips']), 10)
        self.assertEqual(first['mips'][0]['coverage'], 0.5)  # No matching the original mask's coverage.
        with Image.open(output) as image:
            self.assertEqual(image.mode, 'RGBA')
            self.assertEqual(image.getchannel('A').getextrema(), (0, 255))
        self.assertEqual(fringe.build(self.recipe_path), first)
        self.assertEqual((output.read_bytes(), report_path.read_bytes()), initial)
        for path, data in originals.items():
            self.assertEqual(path.read_bytes(), data)

    def test_build_rejects_missing_ambiguous_or_unproven_provenance_before_outputs(self):
        record = self.provenance['assets'][0].copy()
        variants = [[], [record, record],
                    [dict(record, original_game_pixels=True)], [dict(record, original_game_pixels=0)],
                    [dict(record, sha256='0' * 64)], [dict(record, dest='local/original.png')],
                    [{key: value for key, value in record.items() if key != 'original_game_pixels'}]]
        for records in variants:
            with self.subTest(records=records):
                self.provenance['assets'] = records
                self.write_inputs()
                with self.assertRaisesRegex(ValueError, 'provenance'):
                    fringe.build(self.recipe_path)
                self.assertFalse((self.assets / 'fitted.png').exists())
                self.assertFalse((self.assets / 'validation.json').exists())

    def test_build_rejects_changed_source_and_rgb_even_with_matching_provenance(self):
        self.source.write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            fringe.build(self.recipe_path)
        Image.new('RGB', (8, 8), (160, 140, 120)).save(self.source)
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.recipe['source']['sha256'] = digest
        self.provenance['assets'][0]['sha256'] = digest
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, 'RGBA'):
            fringe.build(self.recipe_path)
        self.assertFalse((self.assets / 'fitted.png').exists())

    def test_build_requires_explicit_false_original_masks_provenance_before_writing(self):
        valid = self.provenance['assets'][0].copy()
        missing = object()
        for value in (True, missing, None, 'false', 'true', 0, 1, 0.0, [], {}):
            with self.subTest(original_masks_used='missing' if value is missing else value):
                record = valid.copy()
                if value is missing:
                    record.pop('original_masks_used')
                else:
                    record['original_masks_used'] = value
                self.provenance['assets'] = [record]
                self.write_inputs()
                # Existing derived files must survive an invalid provenance record.
                output = self.assets / 'fitted.png'
                report = self.assets / 'validation.json'
                output.write_bytes(b'previous PNG')
                report.write_bytes(b'previous JSON')
                originals = {p: p.read_bytes() for p in (self.source, self.recipe_path,
                                                        self.provenance_path, output, report)}
                with self.assertRaisesRegex(ValueError, 'provenance'):
                    fringe.build(self.recipe_path)
                for path, data in originals.items():
                    self.assertEqual(path.read_bytes(), data)

    def test_build_refuses_source_recipe_provenance_aliases_and_output_aliases(self):
        for key in ('output', 'report'):
            for protected in (self.source, self.recipe_path, self.provenance_path):
                for hardlink in (False, True):
                    with self.subTest(key=key, protected=protected.name, hardlink=hardlink):
                        self.recipe.update(output='assets/fitted.png', report='assets/validation.json')
                        alias = self.assets / ('alias.png' if key == 'output' else 'alias.json')
                        alias.unlink(missing_ok=True)
                        self.recipe[key] = str((alias if hardlink else protected).relative_to(self.root))
                        self.write_inputs()
                        if hardlink:
                            os.link(protected, alias)
                        before = protected.read_bytes()
                        with self.assertRaises(ValueError):
                            fringe.build(self.recipe_path)
                        self.assertEqual(protected.read_bytes(), before)
                        alias.unlink(missing_ok=True)
        self.recipe.update(output='assets/fitted.png', report='assets/validation.json')
        self.recipe['report'] = self.recipe['output']
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, 'alias'):
            fringe.build(self.recipe_path)
        self.recipe['report'] = 'assets/validation.json'
        self.write_inputs()
        output = self.assets / 'fitted.png'
        output.write_bytes(b'previous output')
        os.link(output, self.assets / 'validation.json')
        with self.assertRaisesRegex(ValueError, 'alias'):
            fringe.build(self.recipe_path)
        self.assertEqual(output.read_bytes(), b'previous output')
        self.assertEqual((self.assets / 'validation.json').read_bytes(), b'previous output')

    def test_build_refuses_symlink_inputs_outputs_and_parent_directories(self):
        for key, target in (('source', self.source), ('output', self.source), ('report', self.provenance_path)):
            with self.subTest(key=key):
                link = self.assets / ('link.json' if key == 'report' else 'link.png')
                link.symlink_to(target)
                old = self.recipe['source']['path'] if key == 'source' else self.recipe[key]
                if key == 'source':
                    self.recipe['source']['path'] = str(link.relative_to(self.root))
                else:
                    self.recipe[key] = str(link.relative_to(self.root))
                self.write_inputs()
                with self.assertRaisesRegex(ValueError, 'Symlinks'):
                    fringe.build(self.recipe_path)
                if key == 'source':
                    self.recipe['source']['path'] = old
                else:
                    self.recipe[key] = old
                link.unlink()
        linked_dir = self.root / 'linked'
        linked_dir.symlink_to(self.assets, target_is_directory=True)
        self.recipe['output'] = 'linked/fitted.png'
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, 'Symlinks'):
            fringe.build(self.recipe_path)
        self.recipe['output'] = 'assets/fitted.png'
        self.write_inputs()
        link = self.assets / 'recipe-link.json'
        link.symlink_to(self.recipe_path)
        with self.assertRaisesRegex(ValueError, 'Symlinks'):
            fringe.build(link)

    def test_failed_publication_preserves_previous_outputs_and_cleans_only_its_temporary(self):
        output = self.assets / 'fitted.png'
        report = self.assets / 'validation.json'
        output.write_bytes(b'previous PNG')
        report.write_bytes(b'previous JSON')
        sentinel = self.assets / '.other-file.tmp'
        sentinel.write_bytes(b'unrelated temporary file')
        with patch.object(fringe.os, 'replace', side_effect=OSError('injected publication failure')):
            with self.assertRaisesRegex(OSError, 'injected publication failure'):
                fringe.build(self.recipe_path)
        self.assertEqual(output.read_bytes(), b'previous PNG')
        self.assertEqual(report.read_bytes(), b'previous JSON')
        self.assertEqual(sentinel.read_bytes(), b'unrelated temporary file')
        self.assertEqual(list(self.assets.glob('.*.tmp')), [sentinel])

    def test_bounded_source_size_rejected_before_decode_or_output(self):
        with patch.object(fringe, 'MAX_SOURCE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'bounded file size'):
                fringe.build(self.recipe_path)
        self.assertFalse((self.assets / 'fitted.png').exists())
        self.assertFalse((self.assets / 'validation.json').exists())

    def test_build_rejects_bad_recipe_without_writing(self):
        for change in ({'size': 1024}, {'size': True}, {'variant': 'opaque'},
                       {'schema_version': 2}, {'reference_mask': 'local/original.png'},
                       {'output': '../outside.png'}, {'report': '/tmp/fringe-report.json'}):
            with self.subTest(change=change):
                saved = self.recipe.copy()
                self.recipe.update(change)
                self.write_inputs()
                with self.assertRaises(ValueError):
                    fringe.build(self.recipe_path)
                self.recipe = saved
                self.assertFalse((self.assets / 'fitted.png').exists())
                self.assertFalse((self.assets / 'validation.json').exists())


if __name__ == '__main__':
    unittest.main()
