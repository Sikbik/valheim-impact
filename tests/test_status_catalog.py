"""Public catalog integrity and evidence-driven contributor refresh."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import export_status, prepare_status_site


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(export_status, 'build_catalog_status'), 'public catalog adapter is required')
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.one = 'CAB-11111111111111111111111111111111:1'
        self.two = 'CAB-22222222222222222222222222222222:1'
        self.mesh = 'CAB-11111111111111111111111111111111:-2'
        self.catalog = {'schema_version': 1, 'inventory_sha256': 'a' * 64, 'assets': [
            {'id': self.one, 'kind': 'texture', 'source_name': 'shared', 'object_name': 'shared',
             'category': 'building', 'dimensions': [64, 128], 'container_paths': ['Assets/Pieces/shared.png']},
            {'id': self.two, 'kind': 'texture', 'source_name': 'shared', 'object_name': 'shared',
             'category': 'building', 'dimensions': [64, 128], 'container_paths': ['Assets/Pieces/shared.png']},
            {'id': self.mesh, 'kind': 'mesh', 'source_name': 'Roof', 'object_name': 'default',
             'category': 'building', 'dimensions': None, 'container_paths': ['Assets/Pieces/Roof.obj']},
        ]}
        self.manifest = {'schema_version': 1, 'snapshot_at': '2026-09-12T19:00:00Z',
                         'inventory_sha256': 'a' * 64, 'evidence': [], 'asset_notes': []}
        self.pin_catalog()

    def pin_catalog(self):
        self.catalog_bytes = encoded(self.catalog)
        self.manifest['catalog_sha256'] = hashlib.sha256(self.catalog_bytes).hexdigest()

    def build(self):
        return export_status.build_catalog_status(self.catalog_bytes, encoded(self.manifest), self.root)

    def proof(self, stage='authored'):
        path = self.root / 'docs/evidence/proof.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"passed":true}')
        self.manifest['evidence'] = [{'id': 'proof', 'path': 'docs/evidence/proof.json',
                                     'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                     'title': 'Scoped fixture', 'scope': 'One exact original texture.',
                                     'targets': [{'asset_id': self.one, 'stages': [stage]}]}]

    def test_no_raw_inventory_is_needed_and_no_stages_are_inherited(self):
        result = self.build()
        self.assertEqual(result['summary']['textures'], 2)
        self.assertEqual(result['summary']['meshes'], 1)
        self.assertEqual(result['inputs']['catalog_sha256'], self.manifest['catalog_sha256'])
        self.assertEqual(result['inputs']['inventory_sha256'], 'a' * 64)
        self.assertFalse((self.root / 'local').exists())
        self.assertEqual({a['id'] for a in result['assets']}, {self.one, self.two, self.mesh})
        for asset in result['assets']:
            self.assertEqual({stage for stage, value in asset['stages'].items() if value}, {'inventoried'})

    def test_reviewed_evidence_promotes_only_exact_target_and_check_sees_update(self):
        initial = self.build()
        self.proof('uv_reviewed')
        promoted = self.build()
        assets = {a['id']: a for a in promoted['assets']}
        self.assertTrue(assets[self.one]['stages']['uv_reviewed'])
        self.assertFalse(assets[self.one]['stages']['authored'])
        self.assertFalse(assets[self.two]['stages']['uv_reviewed'])
        self.assertFalse(assets[self.mesh]['stages']['authored'])
        self.assertEqual(assets[self.one]['evidence'], {'uv_reviewed': ['proof']})
        self.assertNotEqual(initial['inputs']['status_manifest_sha256'], promoted['inputs']['status_manifest_sha256'])

    def test_hash_pins_and_original_identity_provenance_must_match(self):
        self.catalog_bytes += b' '
        with self.assertRaisesRegex(ValueError, 'Catalog hash'):
            self.build()
        self.pin_catalog()
        self.manifest['inventory_sha256'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'Inventory hash'):
            self.build()
        self.manifest['inventory_sha256'] = 'a' * 64
        del self.manifest['catalog_sha256']
        with self.assertRaisesRegex(ValueError, 'catalog_sha256'):
            self.build()

    def test_unknown_or_missing_evidence_cannot_promote_an_asset(self):
        self.proof('finished')
        with self.assertRaisesRegex(ValueError, 'Unknown stage'):
            self.build()
        self.proof()
        self.manifest['evidence'][0]['targets'][0]['asset_id'] = 'CAB-33333333333333333333333333333333:1'
        with self.assertRaisesRegex(ValueError, 'Unknown asset'):
            self.build()
        self.proof()
        (self.root / 'docs/evidence/proof.json').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Evidence hash'):
            self.build()

    def test_unknown_catalog_keys_and_baked_progress_or_payload_are_rejected(self):
        for key, value in [('stages', {'approved': True}), ('pixels', [1, 2]),
                           ('vertices', [1, 2]), ('stream', {'offset': 0}), ('payload_bytes', 32)]:
            with self.subTest(key=key):
                bad = copy.deepcopy(self.catalog)
                bad['assets'][0][key] = value
                with self.assertRaisesRegex(ValueError, 'fields'):
                    export_status.catalog_to_inventory(bad)
        bad = copy.deepcopy(self.catalog)
        bad['local_inventory_path'] = '/private/game'
        with self.assertRaisesRegex(ValueError, 'fields'):
            export_status.catalog_to_inventory(bad)

    def test_invalid_types_names_categories_dimensions_and_paths_fail_closed(self):
        changes = [('id', True), ('id', 'CAB-short:1'), ('id', 'CAB-' + '1'*32 + ':9223372036854775808'),
                   ('kind', 'model'), ('category', 'unknown'), ('category', True),
                   ('dimensions', [True, 64]), ('dimensions', [1.5, 64]), ('dimensions', [64]),
                   ('source_name', '/home/private'), ('source_name', 'person@example.com'),
                   ('object_name', 'C:\\private'), ('source_name', 'mismatched'),
                   ('container_paths', ['local/extracted.png']), ('container_paths', ['Assets/../private.png']),
                   ('container_paths', ['Assets/C:\\private.png']),
                   ('container_paths', ['Assets/Pieces/person@example.com.png']),
                   ('container_paths', ['Assets/Pieces/shared.png'] * 2)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                bad = copy.deepcopy(self.catalog)
                bad['assets'][0][key] = value
                with self.assertRaises(ValueError):
                    export_status.catalog_to_inventory(bad)
        for field, value in [('schema_version', True), ('assets', {}), ('inventory_sha256', 'unknown')]:
            bad = copy.deepcopy(self.catalog)
            bad[field] = value
            with self.assertRaises(ValueError):
                export_status.catalog_to_inventory(bad)

    def test_duplicate_id_even_across_kinds_is_not_silently_merged(self):
        self.catalog['assets'].append(copy.deepcopy(self.catalog['assets'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            export_status.catalog_to_inventory(self.catalog)
        self.catalog['assets'].pop()
        self.catalog['assets'][2]['id'] = self.one
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            export_status.catalog_to_inventory(self.catalog)

    def test_duplicate_json_keys_and_boolean_manifest_schema_are_rejected(self):
        self.catalog_bytes = self.catalog_bytes.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
        self.manifest['catalog_sha256'] = hashlib.sha256(self.catalog_bytes).hexdigest()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.build()
        self.pin_catalog()
        self.manifest['schema_version'] = True
        with self.assertRaises(ValueError):
            self.build()

    def test_zero_size_texture_placeholder_is_preserved(self):
        self.catalog['assets'][0]['dimensions'] = [0, 0]
        self.pin_catalog()
        self.assertEqual(next(a for a in self.build()['assets'] if a['id'] == self.one)['dimensions'], [0, 0])

    def test_prepare_outputs_matching_snapshot_and_check_never_writes(self):
        catalog_path = self.root / 'assets/status/catalog.json'
        catalog_path.parent.mkdir(parents=True)
        catalog_path.write_bytes(self.catalog_bytes)
        manifest_path = catalog_path.with_name('manifest.json')
        manifest_path.write_bytes(encoded(self.manifest))
        with self.assertRaisesRegex(ValueError, 'stale'):
            prepare_status_site.prepare(self.root, check=True)
        self.assertFalse((self.root / 'status-site').exists())
        self.assertFalse((self.root / 'local').exists())
        prepare_status_site.prepare(self.root)
        inventory_path = self.root / 'status-site/public/data/inventory.json'
        summary_path = self.root / 'status-site/data/summary.json'
        inv, summary = json.loads(inventory_path.read_bytes()), json.loads(summary_path.read_bytes())
        self.assertEqual(summary, {key: value for key, value in inv.items() if key != 'assets'})
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        prepare_status_site.prepare(self.root, check=True)
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}, before)
        summary_path.write_bytes(before[summary_path][0] + b' ')
        with self.assertRaisesRegex(ValueError, 'stale'):
            prepare_status_site.prepare(self.root, check=True)
        self.assertEqual(inventory_path.read_bytes(), before[inventory_path][0])
        self.assertEqual(summary_path.read_bytes(), before[summary_path][0] + b' ')
        summary_path.write_bytes(before[summary_path][0])
        self.proof()
        manifest_path.write_bytes(encoded(self.manifest))
        with self.assertRaisesRegex(ValueError, 'stale'):
            prepare_status_site.prepare(self.root, check=True)
        self.assertEqual(inventory_path.read_bytes(), before[inventory_path][0])
        self.assertEqual(summary_path.read_bytes(), before[summary_path][0])

    def test_prepare_refuses_symlinks_before_any_output_change(self):
        status_dir = self.root / 'assets/status'
        status_dir.mkdir(parents=True)
        (status_dir / 'catalog.json').write_bytes(self.catalog_bytes)
        (status_dir / 'manifest.json').write_bytes(encoded(self.manifest))
        external = self.root / 'external'
        external.mkdir()
        (self.root / 'status-site').symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            prepare_status_site.prepare(self.root)
        self.assertEqual(list(external.iterdir()), [])

    def test_invalid_second_output_parent_cannot_partially_refresh_first_output(self):
        status_dir = self.root / 'assets/status'
        status_dir.mkdir(parents=True)
        (status_dir / 'catalog.json').write_bytes(self.catalog_bytes)
        (status_dir / 'manifest.json').write_bytes(encoded(self.manifest))
        blocked = self.root / 'status-site/data'
        blocked.parent.mkdir()
        blocked.write_bytes(b'existing unrelated file')
        with self.assertRaises(ValueError):
            prepare_status_site.prepare(self.root)
        self.assertFalse((self.root / 'status-site/public').exists())
        self.assertEqual(blocked.read_bytes(), b'existing unrelated file')


class RealCatalogIdentityTests(unittest.TestCase):
    def test_public_snapshot_roundtrip_retains_all_ids_and_metadata_without_payloads(self):
        self.assertTrue(hasattr(export_status, 'catalog_from_snapshot'), 'public catalog extraction is required')
        root = Path(__file__).resolve().parents[1]
        snapshot = json.loads((root / 'status-site/public/data/inventory.json').read_bytes())
        catalog = export_status.catalog_from_snapshot(snapshot)
        self.assertEqual(json.loads((root / 'assets/status/catalog.json').read_bytes()), catalog)
        records = export_status.asset_records(export_status.catalog_to_inventory(catalog))
        self.assertEqual(len(records), 13523)
        self.assertEqual(sum(a['kind'] == 'texture' for a in records.values()), 3187)
        self.assertEqual(sum(a['kind'] == 'mesh' for a in records.values()), 10336)
        for asset in snapshot['assets']:
            for key in ('id', 'kind', 'name', 'object_name', 'category', 'dimensions', 'container_paths'):
                self.assertEqual(records[asset['id']][key], asset[key])
        text = encoded(catalog).decode()
        for private in ('"stages"', '"evidence"', '"note"', '"vertices"', '"pixels"',
                        '"stream"', '"payload_bytes"', '/home/', 'local/'):
            self.assertNotIn(private, text)


if __name__ == '__main__':
    unittest.main()
