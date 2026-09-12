"""Status boundaries: exact identity, explicit evidence and a public allowlist."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

try:
    from tools import export_status
except ImportError:
    export_status = None


class StatusExportTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(export_status, 'metadata-only status exporter is required')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inventory = {
            'game_root': '/private/game',
            'textures': [dict(id='CAB-a:1', name='shared', dimensions=[64, 128],
                              category_estimate='building', container_paths=['Assets/Pieces/shared.png'])],
            'meshes': [dict(id='CAB-a:2', name='default', container_paths=['Assets/Pieces/Roof.obj'])],
        }
        self.manifest = dict(schema_version=1, snapshot_at='2026-09-12T19:00:00Z',
                             inventory_sha256='a'*64, evidence=[], asset_notes=[])

    def proof(self, stages, asset_id='CAB-a:1'):
        path = self.root / 'docs/evidence/proof.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"result":"passed","private":"/private/keep-local"}')
        record = dict(id='fixture', path='docs/evidence/proof.json',
                      sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      title='Menu fixture', scope='One material on a retained original mesh.',
                      targets=[dict(asset_id=asset_id, stages=stages)])
        self.manifest['evidence'].append(record)
        return record

    def build(self):
        return export_status.build_status(self.inventory, self.manifest, self.root,
                                          inventory_sha256='a'*64, manifest_sha256='b'*64)

    def test_absent_evidence_leaves_every_completion_false(self):
        result = self.build()
        self.assertEqual(result['summary']['textures'], 1)
        self.assertEqual(result['summary']['meshes'], 1)
        self.assertEqual(result['summary']['authored_models'], 0)
        for asset in result['assets']:
            self.assertEqual({key for key, value in asset['stages'].items() if value}, {'inventoried'})
            self.assertEqual(asset['evidence'], {})

    def test_same_names_and_path_ids_in_other_cabs_do_not_inherit_progress(self):
        self.inventory['textures'].append(dict(self.inventory['textures'][0], id='CAB-b:1'))
        self.proof(['game_fixture_validated'])
        assets = {asset['id']: asset for asset in self.build()['assets']}
        self.assertTrue(assets['CAB-a:1']['stages']['game_fixture_validated'])
        self.assertFalse(assets['CAB-b:1']['stages']['game_fixture_validated'])
        self.assertFalse(assets['CAB-a:1']['stages']['authored'])
        self.assertEqual(assets['CAB-a:1']['evidence'], {'game_fixture_validated': ['fixture']})

    def test_duplicate_identity_merges_paths_but_does_not_inflate_counts(self):
        duplicate = dict(self.inventory['textures'][0], container_paths=['Assets/Other/shared.png'])
        self.inventory['textures'].append(duplicate)
        result = self.build()
        self.assertEqual(result['summary']['textures'], 1)
        self.assertEqual(result['assets'][0]['container_paths'],
                         ['Assets/Other/shared.png', 'Assets/Pieces/shared.png'])

    def test_conflicting_duplicate_identity_fails_instead_of_hiding_conflict(self):
        self.inventory['textures'].append(dict(self.inventory['textures'][0], dimensions=[32, 32]))
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            self.build()

    def test_private_source_fields_and_evidence_contents_are_never_exported(self):
        self.inventory['textures'][0].update(stream={'path': '/private/payload.resS', 'size': 99},
                                            sources=['secret-bundle'], pixels=[1, 2, 3],
                                            local_png='local/original.png', status='approved')
        self.inventory['meshes'][0].update(vertices=[1, 2, 3], indices=[4, 5, 6],
                                          local_obj='/private/model.obj')
        self.inventory['textures'][0]['container_paths'] += ['/private/path.png', 'local/no.png',
                                                           'Assets/../private.png', 'C:\\secret.png']
        self.proof(['uv_reviewed'])
        result = self.build()
        encoded = json.dumps(result)
        for private in ['/private', 'secret-bundle', 'local/', 'vertices', 'pixels', 'indices', 'resS']:
            self.assertNotIn(private, encoded)
        texture = next(a for a in result['assets'] if a['kind'] == 'texture')
        self.assertEqual(texture['container_paths'], ['Assets/Pieces/shared.png'])
        self.assertFalse(texture['stages']['approved'])

    def test_unknown_stage_or_unknown_target_is_rejected(self):
        proof = self.proof(['finished'])
        with self.assertRaisesRegex(ValueError, 'Unknown stage'):
            self.build()
        proof['targets'] = [dict(asset_id='shared', stages=['authored'])]
        with self.assertRaisesRegex(ValueError, 'Unknown asset'):
            self.build()

    def test_missing_or_changed_evidence_cannot_support_a_claim(self):
        self.proof(['authored'])
        evidence_path = self.root / 'docs/evidence/proof.json'
        evidence_path.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Evidence hash'):
            self.build()
        evidence_path.unlink()
        with self.assertRaisesRegex(ValueError, 'Evidence file'):
            self.build()

    def test_evidence_paths_cannot_escape_or_follow_symlinks(self):
        record = self.proof(['authored'])
        record['path'] = '../proof.json'
        with self.assertRaisesRegex(ValueError, 'Evidence path'):
            self.build()
        record['path'] = 'docs/evidence/proof.json'
        path = self.root / record['path']
        original = path.read_bytes()
        path.unlink()
        external = self.root / 'private.json'
        external.write_bytes(original)
        path.symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'Evidence file'):
            self.build()

    def test_mesh_uv_review_keeps_original_geometry_and_native_status_separate(self):
        self.proof(['uv_reviewed'], 'CAB-a:2')
        result = self.build()
        mesh = next(a for a in result['assets'] if a['kind'] == 'mesh')
        self.assertEqual(mesh['name'], 'Roof')
        self.assertEqual(mesh['object_name'], 'default')
        self.assertIsNone(mesh['dimensions'])
        self.assertTrue(mesh['stages']['uv_reviewed'])
        self.assertFalse(mesh['stages']['native_validated'])
        self.assertFalse(mesh['stages']['authored'])

    def test_zero_size_serialized_font_placeholder_remains_in_inventory(self):
        self.inventory['textures'][0].update(name='Font Texture', dimensions=[0, 0])
        texture = next(a for a in self.build()['assets'] if a['kind'] == 'texture')
        self.assertEqual(texture['dimensions'], [0, 0])
        self.assertFalse(texture['stages']['native_validated'])

    def test_reference_only_evidence_adds_no_completion_stage(self):
        self.proof([])
        result = self.build()
        texture = next(a for a in result['assets'] if a['kind'] == 'texture')
        self.assertEqual(texture['evidence'], {'reference': ['fixture']})
        self.assertEqual(result['summary']['evidence_records'], 1)
        self.assertEqual(result['evidence'][0]['targets'], ['CAB-a:1'])
        self.assertFalse(texture['stages']['uv_reviewed'])

    def test_inventory_hash_mismatch_stops_stale_identity_mapping(self):
        self.manifest['inventory_sha256'] = 'c'*64
        with self.assertRaisesRegex(ValueError, 'Inventory hash'):
            self.build()

    def test_output_cannot_replace_inventory_or_follow_a_link(self):
        inventory_path, manifest_path = self.root/'inventory.json', self.root/'manifest.json'
        inventory_path.write_text(json.dumps(self.inventory))
        before = inventory_path.read_bytes()
        manifest_path.write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError, 'output'):
            export_status.export_file(inventory_path, manifest_path, inventory_path, self.root)
        output = self.root/'linked.json'
        output.symlink_to(inventory_path)
        with self.assertRaisesRegex(ValueError, 'output'):
            export_status.export_file(inventory_path, manifest_path, output, self.root)
        self.assertEqual(inventory_path.read_bytes(), before)

    def test_repeat_export_is_byte_identical_minified_and_preserves_last_good_on_failure(self):
        inventory_path, manifest_path = self.root/'inventory.json', self.root/'manifest.json'
        inventory_path.write_text(json.dumps(self.inventory))
        self.manifest['inventory_sha256'] = hashlib.sha256(inventory_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(self.manifest))
        output = self.root/'output.json'
        export_status.export_file(inventory_path, manifest_path, output, self.root)
        first = output.read_bytes()
        self.assertEqual(first.count(b'\n'), 1)
        export_status.export_file(inventory_path, manifest_path, output, self.root)
        self.assertEqual(output.read_bytes(), first)
        self.assertEqual(json.loads(first)['snapshot_at'], '2026-09-12T19:00:00Z')
        self.manifest['snapshot_at'] = 'unknown'
        manifest_path.write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError, 'timestamp'):
            export_status.export_file(inventory_path, manifest_path, output, self.root)
        self.assertEqual(output.read_bytes(), first)


if __name__ == '__main__':
    unittest.main()
