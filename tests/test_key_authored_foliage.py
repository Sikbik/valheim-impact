import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from tools import key_authored_foliage as key


def foliage_fixture():
    values = np.indices((8, 8)).sum(axis=0) % 2
    pixels = np.repeat(np.where(values, 190, 245)[:, :, None], 3, axis=2).astype(np.uint8)
    pixels[2:5, 2:5] = (95, 170, 55)
    pixels[5:7, 3:6] = (125, 85, 45)
    pixels[1, 3] = (180, 170, 160)
    return Image.fromarray(pixels)


class FoliageAlphaTests(unittest.TestCase):
    def test_neutral_background_is_removed_and_authored_foliage_is_retained(self):
        image, report = key.derive_alpha(foliage_fixture())
        pixels = np.asarray(image)
        self.assertTrue(np.all(pixels[0, :, 3] == 0))
        self.assertTrue(np.all(pixels[2:5, 2:5, 3] == 255))
        self.assertTrue(np.all(pixels[5:7, 3:6, 3] == 255))
        np.testing.assert_array_equal(pixels[2:5, 2:5, :3], np.full((3, 3, 3), (95, 170, 55)))
        np.testing.assert_array_equal(pixels[5:7, 3:6, :3], np.full((2, 3, 3), (125, 85, 45)))
        self.assertGreaterEqual(report['connected_foreground_components'], 1)

    def test_partial_alpha_and_transparency_use_nearest_confident_authored_rgb(self):
        image, _ = key.derive_alpha(foliage_fixture())
        pixels = np.asarray(image)
        self.assertTrue(0 < pixels[1, 3, 3] < 255)
        self.assertEqual(tuple(pixels[1, 3, :3]), (95, 170, 55))
        self.assertIn(tuple(pixels[0, 0, :3]), ((95, 170, 55), (125, 85, 45)))

    def test_score_thresholds_are_exact_and_threshold_values_are_integers(self):
        fixture = foliage_fixture()
        fixture.putpixel((0, 0), (110, 100, 100))
        fixture.putpixel((1, 0), (132, 100, 100))
        result, report = key.derive_alpha(fixture)
        self.assertEqual(result.getpixel((0, 0))[3], 0)
        self.assertEqual(result.getpixel((1, 0))[3], 255)
        self.assertEqual(report['thresholds'], {'transparent_at_or_below': 10, 'opaque_at_or_above': 32})
        for thresholds in ((10, 10), (-1, 32), (10, 256), (True, 32), (10, 32.0)):
            with self.subTest(thresholds=thresholds), self.assertRaises(ValueError):
                key.derive_alpha(foliage_fixture(), *thresholds)

    def test_invalid_modes_dimensions_and_missing_classes_are_rejected(self):
        invalid = (foliage_fixture().convert('RGBA'), Image.new('RGB', (8, 4)),
                   Image.new('RGB', (2049, 2049)), Image.new('RGB', (8, 8), (200, 200, 200)),
                   Image.new('RGB', (8, 8), (40, 180, 60)))
        for image in invalid:
            with self.subTest(mode=image.mode, size=image.size), self.assertRaises(ValueError):
                key.derive_alpha(image)


class FoliageBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'authored.png'
        foliage_fixture().save(self.source)
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.root_patch = patch.object(key, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def build(self, **overrides):
        values = dict(input_path=self.source, expected_sha256=self.digest,
                      output='local/foliage.png', report='local/foliage.json')
        values.update(overrides)
        return key.build(**values)

    def test_build_checks_hash_and_records_candidate_evidence(self):
        before = self.source.read_bytes()
        report = self.build()
        stored = json.loads((self.root / 'local/foliage.json').read_text())
        self.assertEqual(stored, report)
        self.assertEqual(report['source']['sha256'], self.digest)
        self.assertEqual(report['sha256'], hashlib.sha256((self.root / 'local/foliage.png').read_bytes()).hexdigest())
        self.assertFalse(report['native_validated'])
        self.assertFalse(report['game_validated'])
        self.assertFalse(report['original_game_pixels'])
        self.assertFalse(report['original_masks_used'])
        self.assertEqual(self.source.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.build(expected_sha256='0' * 64)

    def test_link_alias_protected_and_unbounded_inputs_are_rejected(self):
        link = self.root / 'link.png'
        link.symlink_to(self.source)
        with self.assertRaises(ValueError):
            self.build(input_path=link)
        (self.root / 'local').mkdir(exist_ok=True)
        os.link(self.source, self.root / 'local/source.png')
        with self.assertRaises(ValueError):
            self.build(output='local/source.png')
        for output in ('assets/foliage.png', '../foliage.png', '/tmp/foliage.png'):
            with self.subTest(output=output), self.assertRaises(ValueError):
                self.build(output=output)
        with patch.object(key, 'MAX_SOURCE_BYTES', 1), self.assertRaises(ValueError):
            self.build()


if __name__ == '__main__':
    unittest.main()
