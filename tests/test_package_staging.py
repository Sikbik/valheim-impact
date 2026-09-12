from pathlib import Path
import hashlib
import json
import tempfile
import unittest

try:
    from tools import package_staging
except ImportError:
    package_staging = None


class PackageTests(unittest.TestCase):
    def test_only_verified_manifest_entries_are_collected(self):
        self.assertIsNotNone(package_staging, 'allowlisted staging packager is required')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = b'authored'
            (root / 'owned.png').write_bytes(data)
            (root / 'original.resS').symlink_to('/nonexistent/third-party-pack')
            (root / 'unlisted.png').write_bytes(b'not in manifest')
            manifest = {'assets': [{'png': 'owned.png', 'png_sha256': hashlib.sha256(data).hexdigest()}]}
            files = package_staging.collect(root, manifest)
            self.assertEqual([p.name for p in files], ['owned.png'])
            (root / 'owned.png').write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                package_staging.collect(root, manifest)

    def test_listed_symlink_is_rejected(self):
        self.assertIsNotNone(package_staging, 'allowlisted staging packager is required')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'owned.png').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):
                package_staging.collect(root, {'assets': [{'png':'owned.png', 'png_sha256':'0'*64}]})
