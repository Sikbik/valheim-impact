import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

from tools import check_public_content as guard


def png_chunk(kind, payload):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)


def png(extra=b''):
    return (b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)) +
            extra + png_chunk(b'IDAT', zlib.compress(bytes([0, 200, 120, 40, 255]))) + png_chunk(b'IEND', b''))


def webp(extra=b''):
    chunk = b'VP8L' + struct.pack('<I', 2) + b'\x2f\x00'
    content = b'WEBP' + chunk + extra
    return b'RIFF' + struct.pack('<I', len(content)) + content


def icc_profile(description):
    value = b'text' + bytes(4) + description.encode() + b'\x00'
    header = bytearray(128)
    header[36:40] = b'acsp'
    result = header + struct.pack('>I', 1) + b'desc' + struct.pack('>II', 144, len(value)) + value
    struct.pack_into('>I', result, 0, len(result))
    return bytes(result)


class PublicContentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        return path

    def categories(self, paths, **kwargs):
        return {item['category'] for item in guard.scan(self.root, paths, **kwargs)['findings']}

    def artifact(self, name='assets/straw.png', data=None, **overrides):
        content = png() if data is None else data
        self.write(name, content)
        record = {'dest': name, 'sha256': hashlib.sha256(content).hexdigest(), 'original_game_pixels': False}
        record.update(overrides)
        self.write('assets/provenance.json', json.dumps({'schema_version': 1, 'assets': [record]}))
        return record

    def test_private_markers_rejected_without_disclosing_matched_values(self):
        home = '/' + 'home/real-contributor/private'
        address = 'private-person' + '@' + 'example.net'
        credential = 'ghp_' + 'a' * 40
        self.write('README.md', home + '\n' + address + '\n' + credential)
        report = guard.scan(self.root, ['README.md'])
        self.assertEqual(self.categories(['README.md']), {'private_home_path', 'email_address', 'credential_marker'})
        encoded = json.dumps(report)
        for private in (home, address, credential):
            self.assertNotIn(private, encoded)
        self.assertEqual({tuple(item) for item in report['findings']}, {('path', 'category')})

    def test_secret_files_local_build_and_game_payload_paths_are_rejected(self):
        names = ['.env', 'config/local.json', 'local/evidence.json', 'build/runtime.dll',
                 'assets/original.resS', 'assets/textures.dat', 'game/valheim_Data/a.bundle',
                 'backup/private.pem', 'unity/Library/cache.json', 'unity/Packages/manifest.json']
        for name in names:
            self.write(name, '{}')
            with self.subTest(name=name):
                self.assertIn('forbidden_path', self.categories([name]))
        self.write('config/local.example.json', '{"game_dir":"/absolute/path/to/game"}')
        self.assertEqual(self.categories(['config/local.example.json']), set())

    def test_symlink_file_parent_and_root_are_not_followed(self):
        secret = self.write('outside/secret.txt', 'private-person' + '@' + 'example.net')
        (self.root / 'alias.txt').symlink_to(secret)
        (self.root / 'linked').symlink_to(secret.parent, target_is_directory=True)
        self.assertEqual(self.categories(['alias.txt']), {'symlink'})
        self.assertEqual(self.categories(['linked/secret.txt']), {'symlink'})
        alias_root = self.root / 'root-link'
        alias_root.symlink_to(self.root, target_is_directory=True)
        self.assertIn('symlink', {x['category'] for x in guard.scan(alias_root, ['outside/secret.txt'])['findings']})

    def test_synthetic_exceptions_are_exact_and_confined_to_the_export_test(self):
        synthetic_home = '/' + 'home/private/person' + '@' + 'example.com'
        synthetic_address = 'person' + '@' + 'example.com'
        name = 'tests/test_tracker_evidence.py'
        self.write(name, repr(synthetic_home) + '\n' + repr(synthetic_address))
        self.assertEqual(self.categories([name]), set())
        self.write('README.md', synthetic_home)
        self.assertEqual(self.categories(['README.md']), {'private_home_path', 'email_address'})
        self.write(name, '/' + 'home/private-contributor/file')
        self.assertEqual(self.categories([name]), {'private_home_path'})
        self.write('tests/test_status_catalog.py', repr(synthetic_home) + '\n' + repr(synthetic_address))
        self.assertEqual(self.categories(['tests/test_status_catalog.py']), set())
        self.write('tests/test_status_catalog.py', repr('Assets/Pieces/' + synthetic_address + '.png'))
        self.assertEqual(self.categories(['tests/test_status_catalog.py']), set())
        self.write(name, repr('/' + 'home/private.png'))
        self.assertEqual(self.categories([name]), set())
        self.write('tests/test_tracker_evidence.py', "pattern = r'" + '/' + "home/|local/'")
        self.assertEqual(self.categories(['tests/test_tracker_evidence.py']), set())

    def test_animation_container_paths_are_not_email_addresses(self):
        paths = ['Assets/Models/Viking' + '@' + 'walk.fbx', 'assets/models/Player' + '@' + 'dance.FBX']
        self.write('assets/inventory.json', json.dumps({'paths': paths}))
        self.assertEqual(self.categories(['assets/inventory.json']), set())
        self.write('README.md', 'someone' + '@' + 'example.fbx')
        self.assertEqual(self.categories(['README.md']), {'email_address'})

    def test_documented_animation_syntax_is_allowed_only_in_the_exporter_comment(self):
        example = 'model' + '@' + 'animation.fbx'
        content = '# Unity uses ' + example + ' names. Remove only that file extension.'
        self.write('tools/export_status.py', content)
        self.assertEqual(self.categories(['tools/export_status.py']), set())
        self.write('README.md', example)
        self.assertEqual(self.categories(['README.md']), {'email_address'})
        self.write('tools/export_status.py', 'address = ' + repr(example))
        self.assertEqual(self.categories(['tools/export_status.py']), {'email_address'})

    def test_real_copyright_and_public_credit_exceptions_require_exact_scope(self):
        address = 'credit-alias' + '@' + 'example.net'
        self.write('CREDITS.md', 'Public alias <' + address + '>')
        self.assertEqual(self.categories(['CREDITS.md']), {'email_address'})
        self.assertEqual(self.categories(['CREDITS.md'], allowed_emails=[('CREDITS.md', address)]), set())
        self.write('LICENSE.txt', 'Copyright 2026 Public alias <' + address + '>\nPermission granted.')
        self.assertEqual(self.categories(['LICENSE.txt'], allowed_emails=[('LICENSE.txt', address)]), set())
        self.write('LICENSE.txt', 'Unrelated data: ' + address)
        self.assertEqual(self.categories(['LICENSE.txt'], allowed_emails=[('LICENSE.txt', address)]), {'email_address'})
        self.write('README.md', 'Contact: ' + address)
        self.assertIn('email_address', self.categories(['README.md'], allowed_emails=[('CREDITS.md', address)]))
        self.assertIn('invalid_email_policy', self.categories(['README.md'], allowed_emails=[('README.md', address)]))

    def test_artifact_hash_and_explicit_original_pixel_provenance_are_required(self):
        self.artifact()
        paths = ['assets/provenance.json', 'assets/straw.png']
        self.assertEqual(self.categories(paths), set())
        self.artifact(sha256='0' * 64)
        self.assertIn('artifact_hash', self.categories(paths))
        for flag in (True, None, 0, 'false'):
            self.artifact(original_game_pixels=flag)
            with self.subTest(flag=flag):
                self.assertIn('artifact_provenance', self.categories(paths))
        (self.root / 'assets/provenance.json').unlink()
        self.assertIn('artifact_provenance', self.categories(['assets/straw.png']))

    def test_duplicate_records_missing_files_and_source_links_are_rejected(self):
        record = self.artifact()
        self.write('assets/provenance.json', json.dumps({'assets': [record, record], 'schema_version': 1}))
        self.assertIn('artifact_provenance', self.categories(['assets/provenance.json', 'assets/straw.png']))
        self.write('assets/provenance.json', json.dumps({'assets': [dict(record, dest='assets/missing.png')], 'schema_version': 1}))
        self.assertIn('artifact_missing', self.categories(['assets/provenance.json']))
        target = self.write('outside.png', png())
        (self.root / 'assets/straw.png').unlink()
        (self.root / 'assets/straw.png').symlink_to(target)
        self.write('assets/provenance.json', json.dumps({'assets': [record], 'schema_version': 1}))
        self.assertIn('symlink', self.categories(['assets/provenance.json']))

    def test_authored_models_require_explicit_false_original_geometry(self):
        for flag in ('missing', True, 0, 'false', False):
            fields = {} if flag == 'missing' else {'original_geometry': flag}
            self.artifact('assets/models/straw.obj', b'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n', **fields)
            categories = self.categories(['assets/provenance.json', 'assets/models/straw.obj'])
            with self.subTest(flag=flag):
                self.assertEqual('original_geometry' in categories, flag is not False)
        self.write('docs/original.obj', 'v 1 2 3')
        self.assertIn('forbidden_path', self.categories(['docs/original.obj']))

    def test_png_text_exif_and_provenance_chunks_are_rejected_even_when_hash_matches(self):
        for kind in (b'tEXt', b'zTXt', b'iTXt', b'eXIf', b'caBX'):
            self.artifact(data=png(png_chunk(kind, b'private data')))
            with self.subTest(kind=kind):
                self.assertIn('embedded_image_metadata', self.categories(['assets/provenance.json', 'assets/straw.png']))
        self.artifact(data=png(png_chunk(b'sRGB', b'\x00')))
        self.assertEqual(self.categories(['assets/provenance.json', 'assets/straw.png']), set())

    def test_webp_exif_xmp_and_malformed_image_containers_are_rejected(self):
        for kind in (b'EXIF', b'XMP '):
            self.artifact('assets/straw.webp', webp(kind + struct.pack('<I', 2) + b'xx'))
            with self.subTest(kind=kind):
                self.assertIn('embedded_image_metadata', self.categories(['assets/provenance.json', 'assets/straw.webp']))
        for name, content in (('assets/straw.png', png()[:-3]), ('assets/straw.webp', webp() + b'junk')):
            self.artifact(name, content)
            self.assertIn('invalid_image', self.categories(['assets/provenance.json', name]))

    def test_image_pixel_payload_is_not_mistaken_for_private_text(self):
        # These bytes are pixel channel values in a valid uncompressed DEFLATE
        # block, not textual metadata. A whole-file text scan creates false hits.
        pixel_bytes = (('someone' + '@' + 'example.net') + '/' + 'home/someone/').encode().ljust(96, b'X')
        data = (b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', struct.pack('>IIBBBBB', 32, 1, 8, 2, 0, 0, 0)) +
                png_chunk(b'IDAT', zlib.compress(b'\x00' + pixel_bytes, level=0)) + png_chunk(b'IEND', b''))
        self.artifact(data=data)
        self.assertEqual(self.categories(['assets/provenance.json', 'assets/straw.png']), set())

    def test_tracker_art_registry_paths_are_relative_to_the_public_directory(self):
        name = 'status-site/public/art/banner.webp'
        content = webp()
        self.write(name, content)
        record = {'file': 'art/banner.webp', 'sha256': hashlib.sha256(content).hexdigest(),
                  'original_game_pixels': False}
        registry = 'status-site/public/art/provenance.json'
        self.write(registry, json.dumps({'schema_version': 1, 'assets': [record]}))
        self.assertEqual(self.categories([name, registry]), set())

    def test_color_profiles_are_preserved_but_private_text_in_profiles_is_rejected(self):
        for description, expected in (('Standard RGB color profile', set()),
                                      ('Source ' + '/' + 'home/private-person/profile', {'private_home_path'})):
            profile = icc_profile(description)
            png_data = png(png_chunk(b'iCCP', b'RGB\x00\x00' + zlib.compress(profile)))
            webp_chunk = b'ICCP' + struct.pack('<I', len(profile)) + profile + bytes(len(profile) & 1)
            for name, data in (('assets/straw.png', png_data), ('assets/straw.webp', webp(webp_chunk))):
                with self.subTest(name=name, private=bool(expected)):
                    self.artifact(name, data)
                    self.assertEqual(self.categories(['assets/provenance.json', name]), expected)

    def test_private_key_windows_home_and_secret_assignment_are_detected(self):
        cases = [(['-----BEGIN ', 'PRIVATE KEY-----'], 'credential_marker'),
                 (['C:', '\\Users\\', 'PrivatePerson\\document'], 'private_home_path'),
                 (['password=', 'a-long-secret-value'], 'credential_marker')]
        for fragments, expected in cases:
            self.write('README.md', ''.join(fragments))
            self.assertIn(expected, self.categories(['README.md']))

    def test_credential_function_call_is_code_but_literal_secret_values_are_rejected(self):
        self.write('installer/core.py', 'plan.token = hashlib.sha256(encoded(plan.summary())).hexdigest()')
        self.assertEqual(self.categories(['installer/core.py']), set())
        synthetic_secret = 'private-' + 'token-' + 'value-' + '123456789'
        self.write('config/example.json', json.dumps({'token': synthetic_secret}))
        self.assertIn('credential_marker', self.categories(['config/example.json']))
        self.write('installer/core.py', 'plan.token = ' + repr(synthetic_secret))
        self.assertIn('credential_marker', self.categories(['installer/core.py']))

    def test_explicit_file_list_limits_scan_and_reports_only_relative_categories(self):
        self.write('README.md', 'Public project description')
        self.write('excluded.txt', 'private-person' + '@' + 'example.net')
        self.assertEqual(self.categories(['README.md']), set())
        report = guard.scan(self.root, ['../outside.txt', str(self.root / 'README.md')])
        self.assertEqual({x['category'] for x in report['findings']}, {'invalid_path'})
        self.assertNotIn(str(self.root), json.dumps(report))

    @unittest.skipUnless(shutil.which('git'), 'Git is needed for the default tracked-file mode')
    def test_cli_default_git_files_and_explicit_file_list_exit_status(self):
        self.write('README.md', 'Public description')
        self.write('private.txt', 'private-person' + '@' + 'example.net')
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(['git', '-C', str(self.root), 'add', 'README.md'], check=True)
        script = Path(guard.__file__).absolute()
        command = [sys.executable, str(script), '--root', str(self.root)]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)['checked_files'], 1)
        file_list = self.write('public-files.txt', 'README.md\nprivate.txt\n')
        second = subprocess.run(command + ['--files-from', str(file_list)], capture_output=True, text=True)
        self.assertEqual(second.returncode, 1, second.stderr)
        self.assertEqual(json.loads(second.stdout)['findings'], [{'path': 'private.txt', 'category': 'email_address'}])


if __name__ == '__main__':
    unittest.main()
