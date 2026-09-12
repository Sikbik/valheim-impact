"""Biome approval requires exact scoped assets and a pinned explicit review."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

try:
    from tools import validate_roadmap as roadmap
except ImportError:
    roadmap = None

BIOMES = [('meadows', 'Meadows'), ('black-forest', 'Black Forest'), ('swamp', 'Swamp'),
          ('mountains', 'Mountains'), ('plains', 'Plains'), ('mistlands', 'Mistlands'),
          ('ashlands', 'Ashlands'), ('deep-north', 'Deep North'), ('ocean', 'Ocean')]
GATES = ['scope_complete', 'world_visual_review', 'weather_and_lod', 'performance_review', 'final_art_approval']
STAGES = ['inventoried', 'authored', 'uv_reviewed', 'native_validated', 'game_fixture_validated', 'approved']


class RoadmapTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(roadmap, 'roadmap validator is required')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.asset_id = 'CAB-11111111111111111111111111111111:1'
        self.other_id = 'CAB-22222222222222222222222222222222:1'
        self.roadmap = {'schema_version': 1, 'scope': 'Declared work scopes. Shared assets can occur in multiple biomes.',
                        'biomes': [dict(id=identity, name=name, state='planned', asset_ids=[], approval_evidence=[])
                                   for identity, name in BIOMES]}
        self.roadmap['biomes'][0].update(state='active', asset_ids=[self.asset_id])
        self.snapshot = {'assets': [dict(id=identity, kind='texture', stages={stage: stage == 'inventoried' for stage in STAGES})
                                    for identity in (self.asset_id, self.other_id)]}
        self.manifest = {'schema_version': 1, 'evidence': []}
        catalog = {'schema_version': 1, 'inventory_sha256': 'a'*64, 'assets': [
            dict(id=identity, kind='texture', source_name='roof', object_name='roof', category='building',
                 dimensions=[64, 64], container_paths=['Assets/Pieces/roof.png']) for identity in (self.asset_id, self.other_id)]}
        (self.root / 'assets/status').mkdir(parents=True)
        (self.root / 'assets/status/catalog.json').write_text(json.dumps(catalog))

    def approval(self):
        self.roadmap['biomes'][0].update(state='approved', approval_evidence=['meadows-review'])
        self.snapshot['assets'][0]['stages']['approved'] = True
        self.review = {'schema_version': 1, 'kind': 'biome-review', 'biome_id': 'meadows',
                       'gates': {gate: True for gate in GATES},
                       'targets': [{'asset_id': self.asset_id, 'stages': ['approved']}],
                       'checks': [{'name': 'World visual review completed', 'passed': True}], 'artifacts': []}
        self.record = {'id': 'meadows-review', 'path': 'docs/evidence/contributions/meadows-review.json',
                       'title': 'Meadows review', 'scope': 'Declared biome scope approved after review.',
                       'targets': copy.deepcopy(self.review['targets'])}
        self.manifest['evidence'] = [self.record]
        self.write_review()

    def write_review(self):
        content = json.dumps(self.review).encode()
        path = self.root / self.record['path']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        self.record['sha256'] = hashlib.sha256(content).hexdigest()

    def validate(self):
        return roadmap.validate_roadmap(self.roadmap, self.snapshot, self.manifest, self.root)

    def test_active_scope_has_separate_counts_and_no_automatic_biome_approval(self):
        self.snapshot['assets'][0]['stages']['authored'] = True
        result = self.validate()
        meadows = result['biomes'][0]
        self.assertEqual(meadows['state'], 'active')
        self.assertEqual(meadows['scoped_assets'], 1)
        self.assertEqual(meadows['stage_counts']['authored'], 1)
        self.assertEqual(meadows['stage_counts']['approved'], 0)
        self.assertEqual(len(result['biomes']), 9)
        self.assertNotIn('global_completion_percent', result)

    def test_shared_asset_is_allowed_across_biomes_but_not_duplicated_within_one(self):
        self.roadmap['biomes'][1].update(state='active', asset_ids=[self.asset_id])
        self.assertEqual(self.validate()['biomes'][1]['scoped_assets'], 1)
        self.roadmap['biomes'][0]['asset_ids'].append(self.asset_id)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.validate()

    def test_exact_nine_biomes_names_and_strict_fields_are_required(self):
        valid = copy.deepcopy(self.roadmap)
        cases = []
        missing = copy.deepcopy(valid); missing['biomes'].pop(); cases.append(missing)
        duplicate = copy.deepcopy(valid); duplicate['biomes'][-1] = copy.deepcopy(duplicate['biomes'][0]); cases.append(duplicate)
        renamed = copy.deepcopy(valid); renamed['biomes'][0]['name'] = 'Another biome'; cases.append(renamed)
        unknown = copy.deepcopy(valid); unknown['biomes'][0]['reviewer'] = 'private'; cases.append(unknown)
        boolean = copy.deepcopy(valid); boolean['schema_version'] = True; cases.append(boolean)
        for bad in cases:
            with self.subTest(bad=bad):
                self.roadmap = bad
                with self.assertRaises(ValueError):
                    self.validate()

    def test_unknown_ids_and_nonapproved_approval_claims_are_rejected(self):
        self.roadmap['biomes'][0]['asset_ids'] = ['CAB-33333333333333333333333333333333:1']
        with self.assertRaisesRegex(ValueError, 'Unknown asset'):
            self.validate()
        self.roadmap['biomes'][0]['asset_ids'] = [self.asset_id]
        self.roadmap['biomes'][0]['approval_evidence'] = ['unreviewed']
        with self.assertRaisesRegex(ValueError, 'Nonapproved'):
            self.validate()

    def test_approved_biome_requires_nonempty_scope_every_asset_and_explicit_review(self):
        self.roadmap['biomes'][0]['state'] = 'approved'
        with self.assertRaises(ValueError):
            self.validate()
        self.approval()
        self.assertEqual(self.validate()['biomes'][0]['state'], 'approved')
        self.roadmap['biomes'][0]['asset_ids'].append(self.other_id)
        with self.assertRaisesRegex(ValueError, 'approved'):
            self.validate()
        self.roadmap['biomes'][0]['asset_ids'] = []
        with self.assertRaises(ValueError):
            self.validate()

    def test_wrong_biome_incomplete_gates_and_false_boolean_lookalikes_cannot_approve(self):
        self.approval()
        self.review['biome_id'] = 'swamp'
        self.write_review()
        with self.assertRaisesRegex(ValueError, 'biome'):
            self.validate()
        self.review['biome_id'] = 'meadows'
        for value in (False, 1, 'true', None):
            with self.subTest(value=value):
                self.review['gates']['final_art_approval'] = value
                self.write_review()
                with self.assertRaises(ValueError):
                    self.validate()
        self.review['gates']['final_art_approval'] = True
        del self.review['gates']['scope_complete']
        self.write_review()
        with self.assertRaises(ValueError):
            self.validate()

    def test_review_scope_mismatch_unknown_evidence_and_source_hash_change_fail(self):
        self.approval()
        self.record['targets'].append({'asset_id': self.other_id, 'stages': ['approved']})
        self.review['targets'] = copy.deepcopy(self.record['targets'])
        self.write_review()
        with self.assertRaisesRegex(ValueError, 'scope'):
            self.validate()
        self.approval()
        (self.root / self.record['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.validate()
        self.write_review()
        self.roadmap['biomes'][0]['approval_evidence'] = ['unknown']
        with self.assertRaisesRegex(ValueError, 'evidence'):
            self.validate()

    def test_file_validation_uses_public_catalog_only_and_never_writes(self):
        status = self.root / 'assets/status'
        catalog_bytes = (status / 'catalog.json').read_bytes()
        self.manifest.update(snapshot_at='2026-09-12T19:00:00Z', inventory_sha256='a'*64,
                             catalog_sha256=hashlib.sha256(catalog_bytes).hexdigest(), asset_notes=[])
        (status / 'manifest.json').write_text(json.dumps(self.manifest))
        (status / 'roadmap.json').write_text(json.dumps(self.roadmap))
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.root.rglob('*') if path.is_file()}
        result = roadmap.validate_file(self.root)
        self.assertEqual(result['biomes'][0]['scoped_assets'], 1)
        self.assertEqual(result['biomes'][0]['stage_counts']['inventoried'], 1)
        self.assertFalse((self.root / 'local').exists())
        self.assertFalse((self.root / 'status-site').exists())
        self.assertEqual({path: (path.read_bytes(), path.stat().st_mtime_ns)
                          for path in self.root.rglob('*') if path.is_file()}, before)

    def test_approved_scope_can_cover_more_than_one_thousand_exact_assets(self):
        self.approval()
        identities = ['CAB-11111111111111111111111111111111:' + str(index) for index in range(1, 1002)]
        self.snapshot['assets'] = [dict(id=identity, kind='texture', stages={stage: True for stage in STAGES})
                                   for identity in identities]
        self.roadmap['biomes'][0]['asset_ids'] = identities
        self.review['targets'] = [{'asset_id': identity, 'stages': ['approved']} for identity in identities]
        self.record['targets'] = copy.deepcopy(self.review['targets'])
        self.write_review()
        result = self.validate()['biomes'][0]
        self.assertEqual(result['state'], 'approved')
        self.assertEqual(result['scoped_assets'], 1001)
        self.assertEqual(result['stage_counts']['approved'], 1001)

    def test_evidence_target_count_over_catalog_limit_is_rejected(self):
        from tools.export_tracker_evidence import targets
        records = [{'asset_id': 'CAB-11111111111111111111111111111111:' + str(index), 'stages': ['approved']}
                   for index in range(1, 100002)]
        with self.assertRaisesRegex(ValueError, 'targets'):
            targets({'targets': records})


if __name__ == '__main__':
    unittest.main()
