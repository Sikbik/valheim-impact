import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from tools import asset_pipeline

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_unity', ROOT / 'tools/prepare_unity.py')
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def copy_template(destination):
    for name in pipeline.TEMPLATE_FILES:
        source_name = 'Packages/manifest.public.json' if name == 'Packages/manifest.json' else name
        target = destination / source_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'unity' / source_name, target)


class SafetyTests(unittest.TestCase):
    def test_live_authoring_stages_inputs_without_replacing_project_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / 'build/staging/meadows', root / 'build/staging/meadows')
            project = root / 'unity'
            (project / 'ProjectSettings').mkdir(parents=True)
            (project / 'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.0.75f1\n')
            (project / 'Packages').mkdir()
            (project / 'Packages/manifest.json').write_text('keep the users installed packages')
            dest, count = pipeline.prepare(root, authoring=True)
            self.assertEqual(dest, project)
            self.assertGreater(count, 0)
            self.assertTrue((project / 'OwnedInputs/manifest.json').is_file())
            self.assertEqual((project / 'Packages/manifest.json').read_text(), 'keep the users installed packages')
            self.assertFalse((project / 'Assets/Editor').exists())

    def test_live_authoring_rejects_wrong_editor_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / 'build/staging/meadows', root / 'build/staging/meadows')
            project = root / 'unity'
            (project / 'ProjectSettings').mkdir(parents=True)
            (project / 'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.2.0f1\n')
            with self.assertRaisesRegex(ValueError, '6000.0.75f1'):
                pipeline.prepare(root, authoring=True)
            self.assertFalse((project / 'OwnedInputs').exists())

    def test_rejects_escape_absolute_resource_and_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('../outside', '/tmp/outside', 'pack.resS', 'x/../../outside'):
                with self.assertRaises(ValueError):
                    pipeline.safe_path(root, name)
            (root / 'link').symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                pipeline.safe_path(root, 'link/payload')

    def test_real_inputs_and_tamper_detection(self):
        manifest, files = pipeline.validate_inputs(ROOT / 'build/staging/meadows')
        assets = json.loads((ROOT / 'assets/meadows/prototype.json').read_text())['assets']
        self.assertEqual(len(files), sum(2 if a.get('generate_normal', True) else 1 for a in assets))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in files:
                (root / name).write_bytes(data)
            (root / 'manifest.json').write_text(json.dumps(manifest))
            first = root / files[0][0]
            first.write_bytes(first.read_bytes()[:-1] + b'x')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                pipeline.validate_inputs(root)

    def test_staging_preflights_output_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_template(root / 'unity')
            shutil.copytree(ROOT / 'build/staging/meadows', root / 'build/staging/meadows')
            dest = root / 'build/unity-project'
            dest.mkdir()
            outside = root / 'outside'
            outside.mkdir()
            (dest / 'OwnedInputs').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                pipeline.prepare(root)
            self.assertFalse((dest / 'Assets').exists())
            self.assertEqual(list(outside.iterdir()), [])

    def test_copy_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_template(root / 'unity')
            shutil.copytree(ROOT / 'build/staging/meadows', root / 'build/staging/meadows')
            (root / 'build/staging/meadows/unowned.resS').write_text('must stay out')
            dest, count = pipeline.prepare(root)
            assets = json.loads((ROOT / 'assets/meadows/prototype.json').read_text())['assets']
            self.assertEqual(count, sum(2 if a.get('generate_normal', True) else 1 for a in assets))
            actual = {str(p.relative_to(dest)) for p in dest.rglob('*') if p.is_file()}
            expected = set(pipeline.TEMPLATE_FILES) | {'OwnedInputs/manifest.json'}
            expected |= {'OwnedInputs/' + r['unity_dds'] for r in json.loads((dest / 'OwnedInputs/manifest.json').read_text())['assets']}
            self.assertEqual(actual, expected)

    def test_mixed_roles_stage_only_manifest_payloads_and_ignore_stale_normal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_template(root / 'unity')
            Image.new('RGB', (8, 8), 'green').save(root / 'source.png')
            manifest = root / 'spec.json'
            manifest.write_text(json.dumps({'assets': [
                dict(id='stone', source='source.png', size=[8, 8], periodic=False,
                     alpha_policy='opaque', normal_strength=0),
                dict(id='reed', source='source.png', size=[8, 8], periodic=False,
                     alpha_policy='opaque', normal_strength=0, generate_normal=False)]}))
            with patch.object(asset_pipeline, 'ROOT', root):
                asset_pipeline.build(manifest)
            stage = root / 'build/staging/meadows'
            self.assertFalse((stage / 'reed_normal-unity.dds').exists())
            (stage / 'reed_normal-unity.dds').write_bytes(b'stale normal must stay out')
            destination, count = pipeline.prepare(root)
            self.assertEqual(count, 3)
            inputs = destination / 'OwnedInputs'
            self.assertEqual({p.name for p in inputs.iterdir()}, {
                'manifest.json', 'stone_albedo-unity.dds', 'stone_normal-unity.dds',
                'reed_albedo-unity.dds'})
            staged = json.loads((inputs / 'manifest.json').read_text())
            self.assertEqual([record['id'] for record in staged['assets']],
                             ['stone_albedo', 'stone_normal', 'reed_albedo'])
            for record in staged['assets']:
                name = record['unity_dds']
                self.assertEqual((inputs / name).read_bytes(), (stage / name).read_bytes())


if __name__ == '__main__':
    unittest.main()
