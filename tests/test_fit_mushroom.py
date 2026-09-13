import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/fit_mushroom.py'
PARENT = 'mushroom-atlas-source-v1.png'
OUTPUTS = ('mushroom-atlas-hd-v1.png', 'mushroom-atlas-balanced-v1.png')
EXPECTED = (
    (512, '94bc997a44d0a5de8fa7e38c37f8d7f87952c6d21c42d2c2b4fd2d64ac6ec58d',
     'b93c8512a0f6077e3ea9ed1a38b5d2f7e224977a5a8f5b5b57ebb78f92cb20c0'),
    (256, '9c40bc014fbeeda426b8fcc25dcdd06afdd63f58650bc31bcb2c2434b3c77a94',
     '3fd8df04a2e4b96252489ec6f63d4d72b852d884c94f7c479e4686004ecb9b37'),
)


class MushroomFitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / 'repository'
        self.parents = self.root / 'assets/meadows'
        self.parents.mkdir(parents=True)
        shutil.copyfile(ROOT / 'assets/meadows' / PARENT, self.parents / PARENT)
        self.output = self.directory / 'new/nested/output'

    def run_cli(self, root=None, output=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), '--root', str(root or self.root),
             '--output-dir', str(output or self.output)],
            cwd=self.directory, capture_output=True, text=True, timeout=30)

    def assert_rejected(self, result, reason):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(reason, result.stderr)

    def module(self):
        self.assertTrue(SCRIPT.is_file(), 'The portable fitting helper is missing')
        spec = importlib.util.spec_from_file_location('mushroom_fit_under_test', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_cli_reproduces_both_outputs_from_only_the_owned_master(self):
        before = (self.parents / PARENT).read_bytes()
        self.assertEqual(list(self.parents.iterdir()), [self.parents / PARENT])
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(json.loads(result.stdout), [
            {'name': name, 'sha256': record[1]}
            for name, record in zip(OUTPUTS, EXPECTED)])
        self.assertEqual(sorted(x.name for x in self.output.iterdir()), sorted(OUTPUTS))
        for name, (size, png_hash, rgba_hash) in zip(OUTPUTS, EXPECTED):
            path = self.output / name
            data = path.read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), png_hash)
            with Image.open(path) as image:
                self.assertEqual(image.mode, 'RGBA')
                self.assertEqual(image.size, (size, size))
                self.assertEqual(hashlib.sha256(image.tobytes()).hexdigest(), rgba_hash)
                self.assertEqual(image.getextrema()[3], (255, 255))
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
            offset = 8
            while offset < len(data):
                length = int.from_bytes(data[offset:offset + 4], 'big')
                self.assertIn(data[offset + 4:offset + 8], (b'IHDR', b'IDAT', b'IEND'))
                offset += length + 12
            self.assertEqual(offset, len(data))
        self.assertEqual((self.parents / PARENT).read_bytes(), before)

    def test_changed_parent_is_rejected_without_outputs_or_input_changes(self):
        parent = self.parents / PARENT
        changed = parent.read_bytes() + b'changed'
        parent.write_bytes(changed)
        self.assert_rejected(self.run_cli(), 'Owned atlas hash mismatch')
        self.assertFalse(self.output.exists())
        self.assertEqual(parent.read_bytes(), changed)

    def test_missing_parent_is_rejected_before_output_creation(self):
        (self.parents / PARENT).unlink()
        self.assert_rejected(self.run_cli(), 'Owned atlas hash mismatch')
        self.assertFalse(self.output.exists())

    def test_linked_input_leaf_and_ancestor_are_rejected(self):
        parent = self.parents / PARENT
        actual = self.directory / 'actual.png'
        parent.rename(actual)
        parent.symlink_to(actual)
        self.assert_rejected(self.run_cli(), 'Linked input paths')
        self.assertFalse(self.output.exists())
        parent.unlink()
        actual.rename(parent)
        link = self.directory / 'linked-repository'
        link.symlink_to(self.root, target_is_directory=True)
        self.assert_rejected(self.run_cli(root=link), 'Linked input paths')
        self.assertFalse(self.output.exists())

    def test_each_existing_output_blocks_the_pair_without_overwriting(self):
        self.output.mkdir(parents=True)
        for name in OUTPUTS:
            with self.subTest(output=name):
                path = self.output / name
                path.write_bytes(b'preserved candidate')
                self.assert_rejected(self.run_cli(), 'Output already exists or is linked')
                self.assertEqual(path.read_bytes(), b'preserved candidate')
                self.assertEqual(list(self.output.iterdir()), [path])
                path.unlink()

    def test_dangling_output_links_block_the_pair_without_following_links(self):
        self.output.mkdir(parents=True)
        for name in OUTPUTS:
            with self.subTest(output=name):
                path = self.output / name
                target = self.directory / 'absent.png'
                path.symlink_to(target)
                self.assert_rejected(self.run_cli(), 'Output already exists or is linked')
                self.assertTrue(path.is_symlink())
                self.assertFalse(target.exists())
                self.assertEqual(list(self.output.iterdir()), [path])
                path.unlink()

    def test_linked_output_directory_and_ancestor_are_rejected_without_writes(self):
        target = self.directory / 'target'
        target.mkdir()
        link = self.directory / 'linked-output'
        link.symlink_to(target, target_is_directory=True)
        for output in (link, link / 'nested'):
            with self.subTest(output=output):
                self.assert_rejected(self.run_cli(output=output), 'Linked output paths')
                self.assertEqual(list(target.iterdir()), [])

    def test_second_hash_failure_does_not_write_the_first_output(self):
        module = self.module()
        bad_outputs = (module.OUTPUTS[0], (module.OUTPUTS[1][0], '0' * 64))
        with patch.object(module, 'OUTPUTS', bad_outputs):
            with self.assertRaisesRegex(ValueError, 'PNG bytes differ'):
                module.reproduce(self.root, self.output)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
