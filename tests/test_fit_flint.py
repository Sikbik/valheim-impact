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
SCRIPT = ROOT / 'tools/fit_flint.py'
PARENT = 'flint-surface-source-v1.png'
OUTPUTS = ('flint-hd-v1.png', 'flint-balanced-v1.png')


class FlintFitTests(unittest.TestCase):
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
            cwd=self.directory, capture_output=True, text=True, timeout=60)

    def assert_rejected(self, result, reason):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(reason, result.stderr)

    def test_cli_reproduces_both_reviewed_pngs_and_decoded_pixels(self):
        expected = (
            (1024, '87bb36cb4fd07085d5dad411d2371a02366452631da52caaebe4325f82e94dc3',
             '81279f252e904a3e098453af86df0bc437cf43378fa43ba41a9a8a51908c0867'),
            (512, 'ba062c317bfd97e5a4d32a18bf3518fb8cc78692bdbf300087dfb016075f7a47',
             '0c182c96ed300198ddf85795ba0a929fec03e6bec4590bf82c38a16fc30e6aac'),
        )
        before = (self.parents / PARENT).read_bytes()
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(sorted(path.name for path in self.output.iterdir()), sorted(OUTPUTS))
        self.assertEqual(json.loads(result.stdout), [
            {'name': name, 'sha256': record[1]} for name, record in zip(OUTPUTS, expected)])
        for name, (size, png_hash, rgb_hash) in zip(OUTPUTS, expected):
            data = (self.output / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), png_hash)
            with Image.open(self.output / name) as image:
                self.assertEqual(image.mode, 'RGB')
                self.assertEqual(image.size, (size, size))
                self.assertEqual(hashlib.sha256(image.tobytes()).hexdigest(), rgb_hash)
                self.assertEqual(image.convert('RGBA').getextrema()[3], (255, 255))
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
            offset = 8
            while offset < len(data):
                length = int.from_bytes(data[offset:offset + 4], 'big')
                self.assertIn(data[offset + 4:offset + 8], (b'IHDR', b'IDAT', b'IEND'))
                offset += length + 12
            self.assertEqual(offset, len(data))
        self.assertEqual((self.parents / PARENT).read_bytes(), before)

    def test_changed_parent_container_is_rejected_before_output_creation(self):
        path = self.parents / PARENT
        data = path.read_bytes() + b'changed'
        path.write_bytes(data)
        self.assert_rejected(self.run_cli(), 'Owned parent hash mismatch')
        self.assertFalse(self.output.exists())
        self.assertEqual(path.read_bytes(), data)

    def test_exact_input_leaf_and_ancestor_links_are_rejected(self):
        path = self.parents / PARENT
        target = self.directory / PARENT
        path.rename(target)
        path.symlink_to(target)
        self.assert_rejected(self.run_cli(), 'Linked input paths')
        self.assertFalse(self.output.exists())
        path.unlink()
        target.rename(path)
        linked = self.directory / 'linked-repository'
        linked.symlink_to(self.root, target_is_directory=True)
        self.assert_rejected(self.run_cli(root=linked), 'Linked input paths')
        self.assertFalse(self.output.exists())

    def test_each_existing_output_blocks_the_pair_without_overwriting(self):
        self.output.mkdir(parents=True)
        for name in OUTPUTS:
            with self.subTest(output=name):
                path = self.output / name
                path.write_bytes(b'previous candidate')
                self.assert_rejected(self.run_cli(), 'Output already exists or is linked')
                self.assertEqual(path.read_bytes(), b'previous candidate')
                self.assertEqual(list(self.output.iterdir()), [path])
                path.unlink()

    def test_dangling_output_leaf_links_block_the_pair(self):
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
