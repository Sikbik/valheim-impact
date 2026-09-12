import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from tools import check_comparisons


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ComparisonValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'assets/status').mkdir(parents=True)
        (self.root / 'assets').mkdir(exist_ok=True)
        self.comparisons = self.root / 'status-site/public/comparisons'
        self.comparisons.mkdir(parents=True)
        self.asset_id = 'CAB-a:1'
        self.catalog = {'schema_version': 1, 'inventory_sha256': 'a' * 64,
                        'assets': [{'id': self.asset_id, 'kind': 'texture'}]}
        self.write_json('assets/status/catalog.json', self.catalog)
        self.source = self.root / 'assets/source.png'
        Image.new('RGB', (8, 8), 'blue').save(self.source)
        self.provenance = {'schema_version': 1, 'assets': [{
            'dest': 'assets/source.png', 'sha256': digest(self.source),
            'original_game_pixels': False}]}
        self.write_json('assets/provenance.json', self.provenance)
        self.status = {'schema_version': 1, 'evidence': [{'targets': [
            {'asset_id': self.asset_id, 'stages': ['authored']}]}]}
        self.write_json('assets/status/manifest.json', self.status)
        sheet = self.comparisons / 'before-000.webp'
        Image.new('RGB', (1536, 1536), 'gray').save(sheet, 'WEBP', lossless=True)
        after = self.comparisons / 'after-source.webp'
        Image.new('RGB', (64, 64), 'blue').save(after, 'WEBP', lossless=True)
        self.index = {
            'schema_version': 1, 'tile_size': 192, 'columns': 8,
            'catalog_sha256': digest(self.root / 'assets/status/catalog.json'),
            'sheets': [{'file': sheet.name, 'sha256': digest(sheet), 'width': 1536,
                        'height': 1536, 'kind': 'reference-preview',
                        'original_game_pixels': True,
                        'license': 'Game reference, excluded from project artwork license'}],
            'assets': {self.asset_id: {
                'status': 'available',
                'before': {'sheet': sheet.name, 'x': 0, 'y': 0, 'width': 192,
                           'height': 192, 'kind': 'texture'},
                'after': [{'file': after.name, 'sha256': digest(after),
                           'source': 'assets/source.png', 'source_sha256': digest(self.source),
                           'label': 'Authored source albedo', 'scope': 'Fixture scope'}]}}}
        self.save_index()

    def tearDown(self):
        self.temp.cleanup()

    def write_json(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def save_index(self):
        self.write_json('status-site/public/comparisons/index.json', self.index)

    def validate(self):
        return check_comparisons.validate(self.root)

    def test_valid_manifest_reports_bounded_counts(self):
        report = self.validate()
        self.assertEqual(report, {'assets': 1, 'available': 1, 'unavailable': 0,
                                  'sheets': 1, 'after_files': 1, 'bytes': report['bytes']})

    def test_rejects_duplicate_json_keys_and_nonfinite_numbers(self):
        index = self.comparisons / 'index.json'
        index.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.validate()
        index.write_text('{"schema_version":NaN}')
        with self.assertRaisesRegex(ValueError, 'number'):
            self.validate()

    def test_rejects_wrong_identity_set_and_catalog_hash(self):
        del self.index['assets'][self.asset_id]
        self.index['assets']['CAB-extra:2'] = {'status': 'unavailable', 'before': None, 'reason': 'missing'}
        self.save_index()
        with self.assertRaisesRegex(ValueError, 'identity set'):
            self.validate()
        self.index['assets'] = {self.asset_id: {'status': 'unavailable', 'before': None, 'reason': 'missing'}}
        self.index['catalog_sha256'] = '0' * 64
        self.save_index()
        with self.assertRaisesRegex(ValueError, 'catalog hash'):
            self.validate()

    def test_rejects_unsafe_names_symlinks_and_orphan_webp(self):
        valid_name = self.index['sheets'][0]['file']
        self.index['sheets'][0]['file'] = '../before.webp'
        self.save_index()
        with self.assertRaisesRegex(ValueError, 'safe WebP basename'):
            self.validate()
        self.index['sheets'][0]['file'] = valid_name
        self.save_index()
        orphan = self.comparisons / 'orphan.webp'
        Image.new('RGB', (1, 1)).save(orphan, 'WEBP')
        with self.assertRaisesRegex(ValueError, 'indexed'):
            self.validate()
        orphan.unlink()
        target = self.comparisons / 'before-000.webp'
        target.unlink(); target.symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.validate()

    def test_rejects_out_of_bounds_or_wrong_kind_sprite(self):
        before = self.index['assets'][self.asset_id]['before']
        before['x'] = 1536
        self.save_index()
        with self.assertRaisesRegex(ValueError, 'bounds'):
            self.validate()
        before['x'] = 0; before['kind'] = 'mesh'
        self.save_index()
        with self.assertRaisesRegex(ValueError, 'kind'):
            self.validate()

    def test_requires_unavailable_reason_and_actual_authored_after(self):
        record = self.index['assets'][self.asset_id]
        valid_after = record['after']
        record.update(status='unavailable', before=None)
        record.pop('reason', None)
        record.pop('after')
        self.save_index()
        with self.assertRaisesRegex(ValueError, 'reason'):
            self.validate()
        self.index['assets'][self.asset_id] = self.set_available(valid_after)
        self.status['evidence'][0]['targets'][0]['stages'] = []
        self.write_json('assets/status/manifest.json', self.status)
        self.save_index()
        with self.assertRaisesRegex(ValueError, 'authored stage'):
            self.validate()

    def set_available(self, after):
        return {'status': 'available',
                'before': {'sheet': 'before-000.webp', 'x': 0, 'y': 0, 'width': 192,
                           'height': 192, 'kind': 'texture'},
                'after': after}

    def test_rejects_after_hash_source_provenance_size_and_metadata(self):
        after = self.index['assets'][self.asset_id]['after'][0]
        after['sha256'] = '0' * 64
        self.save_index()
        with self.assertRaisesRegex(ValueError, '[Aa]fter hash'):
            self.validate()
        after['sha256'] = digest(self.comparisons / after['file'])
        self.provenance['assets'][0]['original_game_pixels'] = True
        self.write_json('assets/provenance.json', self.provenance)
        self.save_index()
        with self.assertRaisesRegex(ValueError, 'provenance'):
            self.validate()

    def test_rejects_embedded_metadata_and_private_manifest_paths(self):
        after_path = self.comparisons / 'after-source.webp'
        Image.new('RGB', (16, 16)).save(after_path, 'WEBP', exif=b'private')
        after = self.index['assets'][self.asset_id]['after'][0]
        after['sha256'] = digest(after_path)
        self.save_index()
        with self.assertRaisesRegex(ValueError, 'metadata'):
            self.validate()
        Image.new('RGB', (16, 16)).save(after_path, 'WEBP', lossless=True)
        after['sha256'] = digest(after_path)
        after['scope'] = '/' + 'home/private/capture.webp'
        self.save_index()
        with self.assertRaisesRegex(ValueError, 'private path'):
            self.validate()


if __name__ == '__main__':
    unittest.main()
