import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image

from tests import test_comparisons as fixtures

digest = fixtures.digest
from tools import refresh_comparisons


class RefreshComparisonTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ComparisonValidatorTests('test_valid_manifest_reports_bounded_counts')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root
        self.base = self.fixture.comparisons
        self.recipe = {'schema_version': 1, 'previews': [dict(
            asset_id=self.fixture.asset_id,
            **{k: v for k, v in self.fixture.index['assets'][self.fixture.asset_id]['after'][0].items() if k != 'sha256'})]}
        self.save_recipe()

    def save_recipe(self):
        self.fixture.write_json('assets/status/comparisons.json', self.recipe)

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.base.iterdir()}

    def test_initial_refresh_preserves_before_and_is_repeatable(self):
        index = copy.deepcopy(self.fixture.index)
        index.pop('catalog_sha256')
        index['assets'][self.fixture.asset_id].pop('after')
        (self.base / 'after-source.webp').unlink()
        self.fixture.write_json('status-site/public/comparisons/index.json', index)
        before = (self.base / 'before-000.webp').read_bytes()
        refresh_comparisons.refresh(self.root)
        current = self.snapshot()
        refresh_comparisons.refresh(self.root, check=True)
        self.assertEqual(current, self.snapshot())
        refresh_comparisons.refresh(self.root)
        self.assertEqual(current, self.snapshot())
        generated = json.loads(current['index.json'])
        self.assertEqual(generated['sheets'], index['sheets'])
        self.assertEqual(generated['assets'][self.fixture.asset_id]['before'], index['assets'][self.fixture.asset_id]['before'])
        self.assertEqual(before, current['before-000.webp'])

    def test_check_rejects_stale_output_without_writes(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'differs'):
            refresh_comparisons.refresh(self.root, check=True)
        self.assertEqual(before, self.snapshot())

    def test_bad_last_recipe_does_not_partially_update_first(self):
        self.recipe['previews'].append(dict(self.recipe['previews'][0], file='after-second.webp', source_sha256='0' * 64))
        self.save_recipe()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'hash'):
            refresh_comparisons.refresh(self.root)
        self.assertEqual(before, self.snapshot())

    def test_unmapped_identity_and_unsafe_paths_rejected(self):
        valid = copy.deepcopy(self.recipe)
        for changes in ({'asset_id': 'CAB-unknown:1'}, {'file': '../after-other.webp'},
                        {'source': 'assets/../outside.png'}, {'source': 'local/source.png'}):
            with self.subTest(changes=changes):
                self.recipe = copy.deepcopy(valid)
                self.recipe['previews'][0].update(changes)
                self.save_recipe()
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    refresh_comparisons.refresh(self.root)
                self.assertEqual(before, self.snapshot())

    def test_linked_source_parent_rejected(self):
        (self.root / 'assets/linked').symlink_to(self.root / 'assets', target_is_directory=True)
        self.recipe['previews'][0]['source'] = 'assets/linked/source.png'
        self.save_recipe()
        with self.assertRaisesRegex(ValueError, 'symlink'):
            refresh_comparisons.refresh(self.root)

    def test_invalid_before_and_unowned_output_preserved(self):
        self.fixture.index['assets'][self.fixture.asset_id]['before']['x'] = 9999
        self.fixture.save_index()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'bounds'):
            refresh_comparisons.refresh(self.root)
        self.assertEqual(before, self.snapshot())
        self.recipe['previews'][0]['file'] = 'after-orphan.webp'
        self.save_recipe()
        (self.base / 'after-orphan.webp').write_bytes(b'do not overwrite')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'unowned'):
            refresh_comparisons.refresh(self.root)
        self.assertEqual(before, self.snapshot())

    def test_output_is_bounded_and_metadata_clean(self):
        Image.new('RGBA', (1024, 768), (20, 60, 120, 100)).save(self.fixture.source, exif=b'private')
        sha = digest(self.fixture.source)
        self.recipe['previews'][0]['source_sha256'] = sha
        self.fixture.provenance['assets'][0]['sha256'] = sha
        self.fixture.write_json('assets/provenance.json', self.fixture.provenance)
        self.save_recipe()
        refresh_comparisons.refresh(self.root)
        with Image.open(self.base / 'after-source.webp') as image:
            self.assertEqual(image.size, (512, 384))
            self.assertNotIn('exif', image.info)
            self.assertEqual(image.getpixel((0, 0))[3], 100)
        self.fixture.validate()

    def test_write_failure_rolls_back_all_owned_files(self):
        before = self.snapshot()
        real_replace = os.replace
        count = 0
        def fail_second(source, destination):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('injected publication failure')
            return real_replace(source, destination)
        with patch.object(refresh_comparisons.os, 'replace', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'injected'):
                refresh_comparisons.refresh(self.root)
        self.assertEqual(before, self.snapshot())


if __name__ == '__main__':
    unittest.main()
