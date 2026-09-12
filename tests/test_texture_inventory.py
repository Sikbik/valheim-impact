"""Contract checks for inventory identity, categories and read-only output paths."""
import tempfile
from pathlib import Path
import unittest

try:
    from tools import texture_inventory as inventory
except ImportError:
    inventory = None


class TextureInventoryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(inventory, 'repeatable texture inventory is required')

    def test_equal_path_ids_in_different_serialized_files_do_not_collapse(self):
        first = inventory.object_key('archive:/CAB-a/CAB-a', 123)
        second = inventory.object_key('CAB-b', 123)
        self.assertNotEqual(first, second)
        self.assertEqual(first, 'CAB-a:123')
        self.assertEqual(first, inventory.object_key('CAB-a', 123))

    def test_dedup_uses_identity_and_preserves_same_name_different_objects(self):
        records = [dict(id='CAB-a:1', name='stone', sources=['bundle-a']),
                   dict(id='CAB-a:1', name='stone', sources=['bundle-b']),
                   dict(id='CAB-b:1', name='stone', sources=['bundle-c'])]
        result = inventory.deduplicate(records)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['sources'], ['bundle-a', 'bundle-b'])
        with self.assertRaises(ValueError):
            inventory.deduplicate(records + [dict(id='CAB-a:1', name='different', sources=[])])

    def test_support_maps_and_icons_are_not_counted_as_surface_albedo_candidates(self):
        fixtures = [('Assets/world/Props/Beech/beech_bark_n.png','support_map'),
                    ('Assets/GameElements/Pieces/icons/woodwall.png','ui'),
                    ('Assets/Characters/Troll/troll_d.png','character'),
                    ('Assets/world/Props/Beech/beech_bark.png','vegetation'),
                    ('Assets/GameElements/Pieces/_res/roof/wood_roof_d.png','building'),
                    ('Assets/world/Props/stone/rock_256.png','world_surface'),
                    ('Assets/fx/smoke.png','effect'),
                    ('Assets/Unknown/surprise.png','unclassified')]
        for path, expected in fixtures:
            with self.subTest(path=path):
                self.assertEqual(inventory.category_estimate(path), expected)

    def test_manifest_preserves_asset_identity_and_ignores_dependency_rows(self):
        sample = '\ufeffSoftRef manifest - Text\nversion: 2\nbundle dependencies:\n- bundle: abc\n  dependencies:\n  - def\nasset locations:\n- asset ID: 001\n  bundle: abc\n  path in bundle: Assets/stone.png\n- asset ID: 002\n  bundle: def\n  path in bundle: Assets/Wood.png\n'
        self.assertEqual(inventory.parse_manifest(sample), [dict(asset_id='001',bundle='abc',path='Assets/stone.png'),dict(asset_id='002',bundle='def',path='Assets/Wood.png')])
        with self.assertRaises(ValueError):
            inventory.parse_manifest(sample.replace('bundle: abc\n  path', 'bundle: ../outside\n  path'))

    def test_full_scope_includes_dependency_only_bundles(self):
        text = 'bundle dependencies:\n- bundle: abc\n  dependencies:\n  - def\nasset locations:\n'
        self.assertEqual(inventory.manifest_bundle_names([dict(bundle='abc',path='Assets/a.png')], text, 'all'), ['abc','def'])

    def test_outputs_refuse_game_tree_and_symlink_ancestors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = root / 'game'
            game.mkdir()
            (root/'linked').symlink_to(game, target_is_directory=True)
            for output in [game/'inspection',root/'linked'/'inspection']:
                with self.subTest(output=output), self.assertRaises(ValueError):
                    inventory.validate_output(output, game)
            self.assertEqual(inventory.validate_output(root/'local',game),root/'local')

    def test_uv_bounds_use_selected_submesh_and_preserve_negative_scale(self):
        points = [(0, 0), (1, 0), (0, 1), (4, 5)]
        result = inventory.uv_statistics(points, [(0, 1, 2)], (-0.5, 0.25), (0.1, 0.2))
        self.assertEqual(result['vertices_used'], 3)
        self.assertEqual(result['raw_bounds'], [[0, 0], [1, 1]])
        self.assertEqual(result['transformed_bounds'], [[-0.4, 0.2], [0.1, 0.45]])
        self.assertEqual(result['transformed_outside_unit_square'], 1)
        with self.assertRaises(ValueError):
            inventory.uv_statistics([(float('nan'), 0)], [(0, 0, 0)])

    def test_cross_bundle_mesh_plan_keeps_material_identity_and_caps_unique_meshes(self):
        materials = [dict(id='A:1',name='stone'),dict(id='B:1',name='stone')]
        renderers = [dict(id='R:1',material_ids=['A:1'],mesh_id='M:1'),
                     dict(id='R:2',material_ids=['A:1'],mesh_id='M:2'),
                     dict(id='R:3',material_ids=['A:1'],mesh_id='M:2'),
                     dict(id='R:4',material_ids=['B:1'],mesh_id='M:3')]
        meshes = [dict(id='M:1',sources=['main']),dict(id='M:2',sources=['main']),dict(id='M:3',sources=['other'])]
        existing = [dict(material_id='A:1',mesh=dict(id='M:1'))]
        plan = inventory.plan_mesh_references(materials,renderers,meshes,existing,{'stone'},2)
        self.assertEqual([(item['material_id'],item['mesh_id']) for item in plan], [('A:1','M:2'),('B:1','M:3')])
        self.assertEqual(inventory.plan_mesh_references(materials,renderers,meshes,existing,{'unrelated'},2), [])

    def test_summary_never_equates_candidate_counts_with_visible_replacements(self):
        result = inventory.summarize([dict(category_estimate='world_surface'),dict(category_estimate='ui')], [], [], [])
        self.assertEqual(result['textures'], 2)
        self.assertEqual(result['visible_replacements_validated'], 0)
        self.assertEqual(result['texture_category_estimates'], {'ui':1, 'world_surface':1})


if __name__ == '__main__':
    unittest.main()
