import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from tools import key_authored_straw as key


def checker_fixture():
    values = np.indices((8, 8)).sum(axis=0) % 2
    pixels = np.repeat(np.where(values, 190, 250)[:, :, None], 3, axis=2).astype(np.uint8)
    pixels[2:6, 2:6] = (230, 170, 70)
    pixels[1, 3] = (190, 180, 160)  # Warm color mixed with a neutral background.
    return Image.fromarray(pixels)


class StrawKeyTests(unittest.TestCase):
    def test_neutral_checkerboard_has_zero_alpha_and_warm_straw_stays_opaque(self):
        image, report = key.derive_alpha(checker_fixture())
        pixels = np.asarray(image)
        self.assertEqual(image.mode, 'RGBA')
        self.assertTrue(np.all(pixels[0, :, 3] == 0))
        self.assertTrue(np.all(pixels[2:6, 2:6, 3] == 255))
        self.assertTrue(np.all(pixels[2:6, 2:6, :3] == (230, 170, 70)))
        self.assertEqual(report['alpha_counts']['opaque'], 16)
        self.assertEqual(report['alpha_counts']['intermediate'], 1)
        self.assertEqual(report['alpha_counts']['zero'], 47)

    def test_partial_alpha_edges_are_decontaminated_with_authored_color(self):
        image, report = key.derive_alpha(checker_fixture())
        pixels = np.asarray(image)
        self.assertGreater(int(pixels[1, 3, 3]), 0)
        self.assertLess(int(pixels[1, 3, 3]), 255)
        self.assertEqual(tuple(pixels[1, 3, :3]), (230, 170, 70))
        self.assertEqual(tuple(pixels[0, 0, :3]), (230, 170, 70))
        # Compositing over black contains warm edge color, not source neutral RGB.
        composite = pixels[1, 3, :3].astype(float) * pixels[1, 3, 3] / 255
        self.assertGreater(composite[0], composite[2] * 3)
        self.assertEqual(report['edge_review']['partial_pixels_farther_than_two_pixels'], 0)

    def test_exact_thresholds_and_color_order_reject_non_straw_colors(self):
        image = checker_fixture()
        samples = [(108, 104, 100), (164, 132, 100), (100, 100, 250), (200, 100, 200)]
        for x, value in enumerate(samples):
            image.putpixel((x, 0), value)
        result, _ = key.derive_alpha(image)
        self.assertEqual([result.getpixel((x, 0))[3] for x in range(4)], [0, 255, 0, 0])

    def test_does_not_flip_crop_fill_gaps_or_copy_color_between_distant_regions(self):
        image = Image.new('RGB', (8, 8), (220, 220, 220))
        image.putpixel((1, 1), (240, 170, 40))
        image.putpixel((6, 6), (130, 95, 20))
        result, report = key.derive_alpha(image)
        self.assertEqual(result.size, image.size)
        self.assertEqual(result.getpixel((1, 1)), (240, 170, 40, 255))
        self.assertEqual(result.getpixel((6, 6)), (130, 95, 20, 255))
        self.assertEqual(result.getpixel((0, 1)), (240, 170, 40, 0))
        self.assertEqual(result.getpixel((7, 6)), (130, 95, 20, 0))
        self.assertEqual(report['alpha_counts']['zero'], 62)

    def test_enclosed_neutral_gap_is_reported_and_remains_transparent(self):
        image = checker_fixture()
        image.putpixel((3, 3), (200, 200, 200))
        result, report = key.derive_alpha(image)
        self.assertEqual(result.getpixel((3, 3))[3], 0)
        self.assertEqual(report['edge_review']['enclosed_fully_transparent_components'], 1)
        self.assertEqual(report['edge_review']['largest_enclosed_fully_transparent_component_pixels'], 1)

    def test_rejects_wrong_mode_unbounded_dimensions_bad_thresholds_and_missing_classes(self):
        for image in (checker_fixture().convert('RGBA'), Image.new('RGB', (8, 4)),
                      Image.new('RGB', (2049, 2049)),
                      Image.new('RGB', (8, 8), (220, 220, 220)),
                      Image.new('RGB', (8, 8), (220, 170, 70))):
            with self.subTest(mode=image.mode, size=image.size):
                with self.assertRaises(ValueError):
                    key.derive_alpha(image)
        for thresholds in ((8, 8), (-1, 64), (8, 256), (True, 64), (8, 64.0)):
            with self.subTest(thresholds=thresholds):
                with self.assertRaises(ValueError):
                    key.derive_alpha(checker_fixture(), *thresholds)

    def test_deterministic_output_and_honest_candidate_report(self):
        first, report = key.derive_alpha(checker_fixture())
        second, again = key.derive_alpha(checker_fixture())
        self.assertEqual(first.tobytes(), second.tobytes())
        self.assertEqual(report, again)
        self.assertEqual(report['cutoff'], 0.69)
        self.assertEqual(report['coverage_at_cutoff'], 16 / 64)
        self.assertEqual(report['alpha_extrema'], [0, 255])
        self.assertFalse(report['game_validated'])
        self.assertFalse(report['uv_approved'])
        self.assertEqual(report['status'], 'candidate for visual review')


class StrawKeyBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'authored-rgb.png'
        checker_fixture().save(self.source)
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.output = 'local/fringe.png'
        self.report = 'local/fringe.json'
        root_patch = patch.object(key, 'ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def build(self, **overrides):
        args = dict(input_path=self.source, expected_sha256=self.digest,
                    output=self.output, report=self.report)
        args.update(overrides)
        return key.build(**args)

    def test_build_records_rgb_hash_parameters_and_real_alpha_without_touching_source(self):
        before = self.source.read_bytes()
        report = self.build()
        png = (self.root / self.output).read_bytes()
        metadata = (self.root / self.report).read_bytes()
        self.assertEqual(json.loads(metadata), report)
        self.assertEqual(report['source']['sha256'], self.digest)
        self.assertEqual(report['source']['mode'], 'RGB')
        self.assertEqual(report['thresholds'], {'transparent_at_or_below': 8, 'opaque_at_or_above': 64})
        self.assertEqual(report['sha256'], hashlib.sha256(png).hexdigest())
        self.assertFalse(report['original_game_pixels'])
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(self.build(), report)
        self.assertEqual((self.root / self.output).read_bytes(), png)
        self.assertEqual((self.root / self.report).read_bytes(), metadata)

    def test_source_hash_mismatch_and_unbounded_file_are_rejected_before_outputs(self):
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.build(expected_sha256='0' * 64)
        with patch.object(key, 'MAX_SOURCE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'bounded file size'):
                self.build()
        self.assertFalse((self.root / 'local').exists())

    def test_output_source_and_report_aliases_refused_including_hardlinks(self):
        local = self.root / 'local'
        local.mkdir()
        for name in ('source-alias.png', 'source-alias.json'):
            os.link(self.source, local / name)
        for args in ({'output': 'local/source-alias.png'}, {'report': 'local/source-alias.json'},
                     {'output': 'local/fringe.png', 'report': 'local/fringe.png'}):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    self.build(**args)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.digest)
        (local / 'fringe.png').write_bytes(b'existing')
        os.link(local / 'fringe.png', local / 'fringe.json')
        with self.assertRaisesRegex(ValueError, 'alias'):
            self.build()
        self.assertEqual((local / 'fringe.json').read_bytes(), b'existing')

    def test_symlinks_and_paths_outside_local_output_area_are_rejected(self):
        link = self.root / 'linked.png'
        link.symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, 'Symlinks'):
            self.build(input_path=link)
        (self.root / 'local').symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlinks'):
            self.build()
        (self.root / 'local').unlink()
        for args in ({'output': 'assets/new.png'}, {'output': '../outside.png'},
                     {'report': '/tmp/report.json'}):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    self.build(**args)
        self.assertFalse((self.root / 'local').exists())

    def test_failed_publication_preserves_source_previous_output_and_foreign_temp(self):
        (self.root / 'local').mkdir()
        output = self.root / self.output
        output.write_bytes(b'previous candidate')
        sentinel = self.root / 'local' / '.unrelated.tmp'
        sentinel.write_bytes(b'foreign temporary')
        with patch.object(key.os, 'replace', side_effect=OSError('injected publish failure')):
            with self.assertRaisesRegex(OSError, 'injected publish failure'):
                self.build()
        self.assertEqual(output.read_bytes(), b'previous candidate')
        self.assertEqual(sentinel.read_bytes(), b'foreign temporary')
        self.assertEqual(list((self.root / 'local').glob('.*.tmp')), [sentinel])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.digest)


if __name__ == '__main__':
    unittest.main()
