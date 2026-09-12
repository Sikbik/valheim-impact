import unittest
import hashlib
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import numpy as np
from PIL import Image
from tools import fit_roof_atlas
from tools.fit_roof_atlas import compose_atlas


class RoofAtlasTests(unittest.TestCase):
    def layout(self):
        return {'reference_size': [8, 8], 'output_size': [32, 32], 'regions': [
            {'source': 'straw', 'box': [0, 0, 3, 8], 'quarter_turns': 0},
            {'source': 'wood', 'box': [3, 0, 8, 8], 'quarter_turns': 1}]}

    def sources(self):
        return {'straw': Image.new('RGBA', (40, 40), (220, 180, 80, 255)),
                'wood': Image.new('RGBA', (40, 40), (80, 45, 20, 255))}

    def test_exact_region_coverage_no_cross_material_blending(self):
        pixels = np.asarray(compose_atlas(self.sources(), self.layout()))
        self.assertEqual(pixels.shape, (32, 32, 4))
        self.assertTrue(np.all(pixels[:, :12] == (220, 180, 80, 255)))
        self.assertTrue(np.all(pixels[:, 12:] == (80, 45, 20, 255)))

    def test_rejects_gap_overlap_and_outside_region(self):
        for box in ([4, 0, 8, 8], [2, 0, 8, 8], [3, 0, 9, 8]):
            with self.subTest(box=box):
                layout = self.layout(); layout['regions'][1]['box'] = box
                with self.assertRaises(ValueError): compose_atlas(self.sources(), layout)

    def test_rejects_transparency_in_opaque_roof_inputs(self):
        sources = self.sources(); sources['wood'].putpixel((0, 0), (0, 0, 0, 0))
        with self.assertRaises(ValueError): compose_atlas(sources, self.layout())

    def test_grain_rotation_and_uniform_texel_scale(self):
        ramp = np.zeros((64, 64, 4), dtype=np.uint8); ramp[:, :, 3] = 255
        ramp[:, :, 0] = np.arange(64)[None, :] * 4
        layout = {'reference_size': [8, 8], 'output_size': [32, 32],
                  'regions': [{'source': 'wood', 'box': [0, 0, 8, 8], 'quarter_turns': 1}]}
        result = np.asarray(compose_atlas({'wood': Image.fromarray(ramp)}, layout))
        self.assertTrue(np.array_equal(result[:, 15], result[:, 16]))
        self.assertGreater(abs(int(result[12, 16, 0])-int(result[20, 16, 0])), 25)

    def test_deterministic_and_independently_periodic_regions(self):
        rng = np.random.default_rng(177)
        sources = {name: Image.fromarray(rng.integers(0, 256, (40, 40, 3), dtype=np.uint8))
                   for name in ('straw', 'wood')}
        first = np.asarray(compose_atlas(sources, self.layout()))
        second = np.asarray(compose_atlas(sources, self.layout()))
        self.assertTrue(np.array_equal(first, second))
        self.assertTrue(np.array_equal(first[0], first[-1]))
        self.assertTrue(np.array_equal(first[:, 0], first[:, 11]))
        self.assertTrue(np.array_equal(first[:, 12], first[:, -1]))

    def test_nonintegral_grid_and_unbounded_output_rejected(self):
        for size in ([31, 32], [32768, 32768]):
            layout = self.layout(); layout['output_size'] = size
            with self.assertRaises(ValueError): compose_atlas(self.sources(), layout)


class RoofAtlasBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.assets = self.root / 'assets'
        self.assets.mkdir()
        self.source = self.assets / 'authored.png'
        Image.new('RGB', (8, 8), (40, 80, 120)).save(self.source)
        self.source_bytes = self.source.read_bytes()
        self.source_hash = hashlib.sha256(self.source_bytes).hexdigest()
        self.provenance_path = self.assets / 'provenance.json'
        self.provenance = {'schema_version': 1, 'assets': [
            {'dest': 'assets/authored.png', 'sha256': self.source_hash, 'original_game_pixels': False}]}
        self.layout_path = self.assets / 'layout.json'
        self.layout = {'reference_size': [8, 8], 'output_size': [16, 16],
                       'output': 'assets/atlas.png',
                       'sources': {'wood': {'path': 'assets/authored.png', 'sha256': self.source_hash}},
                       'regions': [{'source': 'wood', 'box': [0, 0, 8, 8], 'quarter_turns': 0}]}
        self.write_inputs()
        self.root_patch = patch.object(fit_roof_atlas, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def write_inputs(self):
        self.provenance_path.write_text(json.dumps(self.provenance))
        self.layout_path.write_text(json.dumps(self.layout))

    def test_build_verifies_authored_provenance_and_preserves_inputs(self):
        before = {path: path.read_bytes() for path in (self.source, self.layout_path, self.provenance_path)}
        report = fit_roof_atlas.build(self.layout_path)
        self.assertEqual(report['dimensions'], [16, 16])
        self.assertEqual(report['alpha_extrema'], [255, 255])
        self.assertIs(report['original_game_pixels'], False)
        self.assertEqual(report['sha256'], hashlib.sha256((self.assets / 'atlas.png').read_bytes()).hexdigest())
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)

    def test_build_refuses_unproven_sources_before_creating_output(self):
        valid = dict(self.provenance['assets'][0])
        for alteration in ({'original_game_pixels': True}, {'original_game_pixels': 0},
                           {'original_game_pixels': None}, {'sha256': '0' * 64},
                           {'dest': 'local/reference.png'}, {}):
            with self.subTest(alteration=alteration):
                (self.assets / 'atlas.png').unlink(missing_ok=True)
                entry = dict(valid, **alteration)
                if not alteration:
                    entry.pop('original_game_pixels')
                self.provenance['assets'] = [entry]
                self.write_inputs()
                with self.assertRaisesRegex(ValueError, 'provenance'):
                    fit_roof_atlas.build(self.layout_path)
                self.assertFalse((self.assets / 'atlas.png').exists())
        self.provenance['assets'] = []
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, 'provenance'):
            fit_roof_atlas.build(self.layout_path)
        self.assertFalse((self.assets / 'atlas.png').exists())

    def test_build_refuses_source_and_metadata_output_aliases(self):
        for protected in (self.source, self.layout_path, self.provenance_path):
            for hardlink in (False, True):
                with self.subTest(protected=protected.name, hardlink=hardlink):
                    alias = self.assets / 'alias.png'
                    if alias.exists():
                        alias.unlink()
                    self.source.write_bytes(self.source_bytes)
                    self.layout['output'] = str((alias if hardlink else protected).relative_to(self.root))
                    self.write_inputs()
                    if hardlink:
                        os.link(protected, alias)
                    before = protected.read_bytes()
                    with self.assertRaisesRegex(ValueError, 'overwrite'):
                        fit_roof_atlas.build(self.layout_path)
                    self.assertEqual(protected.read_bytes(), before)
                    if hardlink:
                        self.assertEqual(alias.read_bytes(), before)
                        alias.unlink()

    def test_changed_source_bytes_are_rejected_despite_matching_declared_provenance(self):
        Image.new('RGB', (8, 8), (200, 20, 20)).save(self.source)
        changed = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            fit_roof_atlas.build(self.layout_path)
        self.assertEqual(self.source.read_bytes(), changed)
        self.assertFalse((self.assets / 'atlas.png').exists())


if __name__ == '__main__': unittest.main()
