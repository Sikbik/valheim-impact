"""Biome browsing includes untouched assets without changing review progress."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from tools import prepare_biome_inventory as biome


def encoded(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


class BiomeInventoryTests(unittest.TestCase):
    def setUp(self):
        self.one = 'CAB-11111111111111111111111111111111:1'
        self.two = 'CAB-11111111111111111111111111111111:2'
        self.mesh = 'CAB-11111111111111111111111111111111:3'
        self.catalog = {'schema_version': 1, 'inventory_sha256': 'a'*64, 'assets': [
            {'id': identity, 'kind': kind, 'source_name': 'Same name', 'object_name': 'Same name',
             'category': 'vegetation', 'dimensions': [64, 64] if kind == 'texture' else None,
             'container_paths': []}
            for identity, kind in [(self.one, 'texture'), (self.two, 'texture'), (self.mesh, 'mesh')]]}
        self.source = {'schema_version': 1, 'catalog_sha256': hashlib.sha256(encoded(self.catalog)).hexdigest(),
                       'inventory_sha256': 'a'*64, 'scope': 'Configured biome membership, independent of art progress.',
                       'sources': [{'id': 'vegetation:1', 'kind': 'vegetation', 'label': 'Configured tree',
                                    'biomes': ['meadows', 'black-forest'], 'asset_ids': [self.one, self.mesh]}]}

    def build(self):
        return biome.build(encoded(self.source), encoded(self.catalog))

    def test_untouched_assets_are_browsable_without_review_or_artwork_evidence(self):
        result = self.build()
        rows = {r['id']: r for r in result['biomes']}
        self.assertEqual(rows['meadows']['asset_ids'], [self.one, self.mesh])
        self.assertEqual(rows['black-forest']['asset_ids'], [self.one, self.mesh])
        self.assertEqual(result['summary'], {'assigned': 2, 'unassigned': 1, 'shared': 2})
        self.assertEqual(rows['meadows']['texture_count'], 1)
        self.assertNotIn('stages', json.dumps(result))
        self.assertNotIn(self.two, rows['meadows']['asset_ids'])

    def test_multiple_sources_do_not_duplicate_shared_assets(self):
        extra = copy.deepcopy(self.source['sources'][0]); extra['id'] = 'location:2'
        extra['kind'] = 'location'; self.source['sources'].append(extra)
        result = self.build()
        self.assertEqual(result['summary']['assigned'], 2)
        self.assertEqual(len(result['biomes'][0]['asset_ids']), 2)

    def test_unknown_assets_biomes_and_duplicate_sources_fail(self):
        original = copy.deepcopy(self.source)
        for change in ['unknown-asset', 'unknown-biome', 'duplicate-source', 'duplicate-asset', 'duplicate-biome']:
            with self.subTest(change=change):
                self.source = copy.deepcopy(original); row = self.source['sources'][0]
                if change == 'unknown-asset': row['asset_ids'].append('CAB-22222222222222222222222222222222:99')
                if change == 'unknown-biome': row['biomes'].append('not-a-biome')
                if change == 'duplicate-source': self.source['sources'].append(copy.deepcopy(row))
                if change == 'duplicate-asset': row['asset_ids'].append(self.one)
                if change == 'duplicate-biome': row['biomes'].append('meadows')
                with self.assertRaises(ValueError): self.build()

    def test_membership_cannot_inject_progress_or_unreviewed_payload_fields(self):
        for key, value in [('stages', ['approved']), ('vertices', [1, 2]), ('enabled', True)]:
            self.source['sources'][0][key] = value
            with self.assertRaises(ValueError): self.build()
            del self.source['sources'][0][key]

    def test_hash_and_source_identity_must_match_catalog(self):
        self.source['catalog_sha256'] = 'b'*64
        with self.assertRaises(ValueError): self.build()
        self.source['catalog_sha256'] = hashlib.sha256(encoded(self.catalog)).hexdigest()
        self.source['inventory_sha256'] = 'b'*64
        with self.assertRaises(ValueError): self.build()

    def test_prepare_is_reproducible_and_check_never_repairs_stale_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); status = root/'assets/status'; status.mkdir(parents=True)
            (status/'catalog.json').write_bytes(encoded(self.catalog))
            (status/'biome-membership.json').write_bytes(encoded(self.source))
            biome.prepare(root)
            output = root/'status-site/public/data/biomes.json'
            expected = output.read_bytes()
            biome.prepare(root, check=True)
            biome.prepare(root)
            self.assertEqual(output.read_bytes(), expected)
            output.write_bytes(b'{}')
            with self.assertRaises(ValueError): biome.prepare(root, check=True)
            self.assertEqual(output.read_bytes(), b'{}')
            self.assertFalse((status/'manifest.json').exists())
            self.assertFalse((status/'roadmap.json').exists())
