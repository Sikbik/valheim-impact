import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/fit_raspberry.py'
PARENTS = ('raspberry-surface-source-v1.png', 'dandelion-leaf-source-v1.png')
OUTPUTS = ('raspberry-atlas-hd-v1.png', 'raspberry-atlas-balanced-v1.png')


class RaspberryFitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / 'repository'
        self.parents = self.root / 'assets/meadows'
        self.parents.mkdir(parents=True)
        for name in PARENTS:
            shutil.copyfile(ROOT / 'assets/meadows' / name, self.parents / name)
        self.output = self.directory / 'new/nested/output'

    def run_cli(self, root=None, output=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), '--root', str(root or self.root),
             '--output-dir', str(output or self.output)],
            cwd=self.directory, capture_output=True, text=True, timeout=60)

    def assert_rejected(self, result, reason):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(reason, result.stderr)

    def test_cli_reproduces_both_reviewed_pngs_and_decoded_pixels(self):
        expected = (
            (512, 'd97655a5ff683f41c6b740343444b8abb92066f78d91495f451c4c680a9f4805',
             'c3d904991d12a84d4008b63fe02baaa1e85a2a6ceb728b3584ae85bd0488f8fc'),
            (256, '43cd1cb387fba4c0734afa276a5ce918f95e6f84b598a0c87a0eb8b0173b39cd',
             '9d57733eba20dae4dc9d3219c9ded6afbff64dea76369bf713aacfe94921465d'),
        )
        before = {name: (self.parents / name).read_bytes() for name in PARENTS}
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(sorted(path.name for path in self.output.iterdir()), sorted(OUTPUTS))
        self.assertEqual(json.loads(result.stdout), [
            {'name': name, 'sha256': record[1]} for name, record in zip(OUTPUTS, expected)])
        for name, (size, png_hash, rgba_hash) in zip(OUTPUTS, expected):
            path = self.output / name
            data = path.read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), png_hash)
            with Image.open(path) as image:
                self.assertEqual(image.mode, 'RGBA')
                self.assertEqual(image.size, (size, size))
                self.assertEqual(image.getchannel('A').getextrema(), (255, 255))
                self.assertEqual(hashlib.sha256(image.tobytes()).hexdigest(), rgba_hash)
            # Check the real container, including metadata Pillow may not expose.
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
            offset = 8
            while offset < len(data):
                length = int.from_bytes(data[offset:offset + 4], 'big')
                self.assertIn(data[offset + 4:offset + 8], (b'IHDR', b'IDAT', b'IEND'))
                offset += length + 12
            self.assertEqual(offset, len(data))
        for name in PARENTS:
            self.assertEqual((self.parents / name).read_bytes(), before[name])

    def test_changed_parent_container_is_rejected_before_output_creation(self):
        for name in PARENTS:
            with self.subTest(parent=name):
                path = self.parents / name
                original = path.read_bytes()
                # Decoded image can stay unchanged while container bytes differ.
                path.write_bytes(original + b'changed')
                self.assert_rejected(self.run_cli(), 'Owned parent hash mismatch')
                self.assertFalse(self.output.exists())
                self.assertEqual(path.read_bytes(), original + b'changed')
                path.write_bytes(original)

    def test_input_leaf_links_are_rejected_even_for_exact_owned_bytes(self):
        for name in PARENTS:
            with self.subTest(parent=name):
                path = self.parents / name
                target = self.directory / name
                path.rename(target)
                path.symlink_to(target)
                self.assert_rejected(self.run_cli(), 'Linked input paths')
                self.assertFalse(self.output.exists())
                self.assertTrue(path.is_symlink())
                path.unlink()
                target.rename(path)

    def test_linked_input_ancestor_is_rejected(self):
        linked = self.directory / 'linked-repository'
        linked.symlink_to(self.root, target_is_directory=True)
        self.assert_rejected(self.run_cli(root=linked), 'Linked input paths')
        self.assertFalse(self.output.exists())

    def test_each_existing_output_blocks_the_whole_pair_without_overwriting(self):
        self.output.mkdir(parents=True)
        for name in OUTPUTS:
            with self.subTest(output=name):
                path = self.output / name
                path.write_bytes(b'previous candidate')
                self.assert_rejected(self.run_cli(), 'Output already exists or is linked')
                self.assertEqual(path.read_bytes(), b'previous candidate')
                self.assertEqual(list(self.output.iterdir()), [path])
                path.unlink()

    def test_dangling_output_leaf_links_block_the_whole_pair(self):
        self.output.mkdir(parents=True)
        for name in OUTPUTS:
            with self.subTest(output=name):
                path = self.output / name
                target = self.directory / 'missing-target.png'
                path.symlink_to(target)
                self.assert_rejected(self.run_cli(), 'Output already exists or is linked')
                self.assertTrue(path.is_symlink())
                self.assertFalse(target.exists())
                self.assertEqual(list(self.output.iterdir()), [path])
                path.unlink()

    def test_linked_output_directory_or_ancestor_is_rejected_without_writes(self):
        target = self.directory / 'destination'
        target.mkdir()
        linked = self.directory / 'linked-output'
        linked.symlink_to(target, target_is_directory=True)
        for output in (linked, linked / 'nested'):
            with self.subTest(output=output):
                self.assert_rejected(self.run_cli(output=output), 'Linked output paths')
                self.assertEqual(list(target.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
