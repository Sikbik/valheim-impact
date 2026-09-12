"""Installer mutations run only in disposable game fixtures."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import warnings

from installer import core
from installer.package import Package, PackageError


def digest(data):
    return hashlib.sha256(data).hexdigest()


def package(path, files=None, **overrides):
    files = files or {'ValheimImpact.Core.dll': b'original runtime'}
    manifest = dict(schemaVersion=1, product='ValheimImpact', version='0.1.0',
                    platform='linux-x86_64', experimental=True,
                    files=[dict(path=name, size=len(data), sha256=digest(data)) for name, data in files.items()])
    manifest.update(overrides)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
        for name, data in files.items():
            archive.writestr('payload/' + name, data)
    return path


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.game = self.base / 'Valheim'
        (self.game / 'valheim_Data').mkdir(parents=True)
        (self.game / 'valheim.x86_64').write_bytes(b'fixture executable')
        (self.game / 'valheim_Data/globalgamemanagers').write_bytes(b'fixture Unity marker')
        (self.game / 'BepInEx/core').mkdir(parents=True)
        (self.game / 'BepInEx/core/BepInEx.dll').write_bytes(b'fixture prerequisite')
        (self.game / 'BepInEx/plugins').mkdir()
        self.other = self.game / 'BepInEx/plugins/OtherMod.dll'
        self.other.write_bytes(b'untouched')
        self.root = self.game / 'BepInEx/plugins/ValheimImpact'
        self.zip = package(self.base / 'one.zip')
        self.process_patch = patch('installer.core.running_valheim', return_value=[])
        self.process_patch.start()
        self.warning_context = warnings.catch_warnings()
        self.warning_context.__enter__()
        warnings.filterwarnings('ignore', message='Duplicate name:', category=UserWarning)

    def tearDown(self):
        self.process_patch.stop()
        self.temp.cleanup()
        self.warning_context.__exit__(None, None, None)

    def install(self, path=None, profile='Balanced'):
        plan = core.preview(self.game, path or self.zip, profile=profile)
        return core.apply(plan, reviewed_token=plan.token)

    def test_explicit_replacement_is_reviewed_and_rollback_restores_it(self):
        payload = {'ValheimImpact.Core.dll': b'runtime', 'assets/bindings.json': b'{"schemaVersion":1,"bindings":[]}'}
        bundle = package(self.base / 'binding.zip', payload)
        disabled = core.preview(self.game, bundle)
        enabled = core.preview(self.game, bundle, enable_replacement=True)
        self.assertNotEqual(disabled.token, enabled.token)
        core.apply(enabled, reviewed_token=enabled.token)
        self.assertTrue(json.loads((self.root / 'profile.json').read_text())['enableGameReplacement'])
        change = core.preview(self.game, bundle, operation='update')
        core.apply(change, reviewed_token=change.token)
        self.assertFalse(json.loads((self.root / 'profile.json').read_text())['enableGameReplacement'])
        rollback = core.preview(self.game, operation='rollback')
        core.apply(rollback, reviewed_token=rollback.token)
        self.assertTrue(json.loads((self.root / 'profile.json').read_text())['enableGameReplacement'])
        self.assertTrue(core.verify(self.game)['ok'])

    def test_replacement_requires_a_binding_payload(self):
        with self.assertRaises(core.InstallError):
            core.preview(self.game, self.zip, enable_replacement=True)

    def test_install_preview_verify_and_uninstall_preserve_other_content(self):
        plan = core.preview(self.game, self.zip)
        self.assertFalse(self.root.exists())
        self.assertEqual({c.path for c in plan.changes}, {'ValheimImpact.Core.dll', 'profile.json'})
        core.apply(plan, reviewed_token=plan.token)
        self.assertEqual((self.root / 'ValheimImpact.Core.dll').read_bytes(), b'original runtime')
        self.assertEqual(json.loads((self.root / 'profile.json').read_text())['profile'], 'Balanced')
        self.assertTrue(core.verify(self.game)['ok'])
        (self.root / 'personal.txt').write_text('keep me')
        (self.root / 'ValheimImpact.Core.dll').write_bytes(b'user edit')
        plan = core.preview(self.game, operation='uninstall')
        self.assertIn('ValheimImpact.Core.dll', [c.path for c in plan.changes if c.action == 'preserve'])
        core.apply(plan, reviewed_token=plan.token)
        self.assertEqual((self.root / 'personal.txt').read_text(), 'keep me')
        self.assertEqual((self.root / 'ValheimImpact.Core.dll').read_bytes(), b'user edit')
        self.assertEqual(self.other.read_bytes(), b'untouched')
        self.assertFalse((self.root / 'profile.json').exists())

    def test_update_and_explicit_rollback_restore_previous_bytes_and_profile(self):
        self.install()
        two = package(self.base / 'two.zip', {'ValheimImpact.Core.dll': b'new runtime', 'assets/probe.bundle': b'probe'}, version='0.2.0')
        self.install(two, 'High')
        plan = core.preview(self.game, operation='rollback')
        core.apply(plan, reviewed_token=plan.token)
        self.assertEqual((self.root / 'ValheimImpact.Core.dll').read_bytes(), b'original runtime')
        self.assertFalse((self.root / 'assets/probe.bundle').exists())
        self.assertEqual(json.loads((self.root / 'profile.json').read_text())['profile'], 'Balanced')
        self.assertTrue(core.verify(self.game)['ok'])

    def test_unmanaged_and_modified_files_block_updates(self):
        self.root.mkdir()
        (self.root / 'ValheimImpact.Core.dll').write_bytes(b'personal DLL')
        with self.assertRaisesRegex(core.InstallError, 'unowned'):
            core.preview(self.game, self.zip)
        (self.root / 'ValheimImpact.Core.dll').unlink()
        self.install()
        (self.root / 'ValheimImpact.Core.dll').write_bytes(b'modified')
        with self.assertRaisesRegex(core.InstallError, 'modified'):
            core.preview(self.game, self.zip)
        self.assertFalse(core.verify(self.game)['ok'])

    def test_review_token_and_stale_preview_are_rejected(self):
        plan = core.preview(self.game, self.zip)
        with self.assertRaisesRegex(core.InstallError, 'review'):
            core.apply(plan, reviewed_token='wrong')
        self.root.mkdir()
        (self.root / 'ValheimImpact.Core.dll').write_bytes(b'new conflict')
        with self.assertRaises(core.InstallError):
            core.apply(plan, reviewed_token=plan.token)
        self.assertEqual((self.root / 'ValheimImpact.Core.dll').read_bytes(), b'new conflict')

    def test_running_game_prevents_all_mutations(self):
        plan = core.preview(self.game, self.zip)
        with patch('installer.core.running_valheim', return_value=['valheim.x86_64 (123)']):
            with self.assertRaisesRegex(core.InstallError, 'running'):
                core.apply(plan, reviewed_token=plan.token)
        self.assertFalse(self.root.exists())

    def test_failed_mid_commit_restores_old_installation(self):
        self.install()
        two = package(self.base / 'two.zip', {'ValheimImpact.Core.dll': b'new', 'assets/probe.bundle': b'probe'})
        plan = core.preview(self.game, two)
        replace = os.replace
        def fail_one(source, destination):
            if str(destination).endswith('probe.bundle') and '/staging/' in str(source):
                raise OSError('simulated disk failure')
            return replace(source, destination)
        with patch('installer.core.os.replace', side_effect=fail_one):
            with self.assertRaisesRegex(core.InstallError, 'rolled back'):
                core.apply(plan, reviewed_token=plan.token)
        self.assertEqual((self.root / 'ValheimImpact.Core.dll').read_bytes(), b'original runtime')
        self.assertTrue(core.verify(self.game)['ok'])
        self.assertFalse((self.root / '.installer/pending.json').exists())

    def test_symlink_ancestor_and_owned_file_are_rejected(self):
        outside = self.base / 'elsewhere'
        outside.mkdir()
        self.root.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(core.InstallError):
            core.preview(self.game, self.zip)
        self.root.unlink()
        self.install()
        (self.root / 'ValheimImpact.Core.dll').unlink()
        (self.root / 'ValheimImpact.Core.dll').symlink_to(self.other)
        with self.assertRaises(core.InstallError):
            core.preview(self.game, operation='uninstall')
        self.assertEqual(self.other.read_bytes(), b'untouched')

    def test_missing_game_or_bepinex_and_wrong_platform_fail(self):
        (self.game / 'BepInEx/core/BepInEx.dll').unlink()
        with self.assertRaisesRegex(core.InstallError, 'BepInEx'):
            core.preview(self.game, self.zip)

    def test_tamper_extra_entries_duplicates_and_links_fail(self):
        for kind in ['tamper', 'extra', 'duplicate', 'symlink']:
            with self.subTest(kind=kind):
                z = package(self.base / (kind + '.zip'))
                with zipfile.ZipFile(z, 'a') as archive:
                    if kind == 'tamper':
                        archive.writestr('payload/ValheimImpact.Core.dll', b'tampered')
                    elif kind == 'extra':
                        archive.writestr('surprise.txt', b'extra')
                    elif kind == 'duplicate':
                        archive.writestr('payload/valheimimpact.core.dll', b'case collision')
                    else:
                        link = zipfile.ZipInfo('payload/link.dll')
                        link.create_system = 3
                        link.external_attr = (stat.S_IFLNK | 0o777) << 16
                        archive.writestr(link, '../OtherMod.dll')
                with self.assertRaises(PackageError):
                    Package.read(z)

    def test_manifest_traversal_reserved_resources_and_case_collisions_fail(self):
        for name in ['../outside.dll', '/absolute.dll', 'a\\b.dll', 'C:/evil.dll', '.installer/receipt.json', 'profile.json', 'asset.resS', 'x/../../y.dll', 'a./evil.dll', 'CON.dll']:
            with self.subTest(name=name):
                with self.assertRaises(PackageError):
                    Package.read(package(self.base / 'bad.zip', {name: b'bad'}))
        with self.assertRaises(PackageError):
            Package.read(package(self.base / 'bad.zip', {'a.dll': b'one', 'A.dll': b'two'}))

    def test_package_hash_size_limits_and_platform_are_enforced(self):
        z = self.zip
        with patch('installer.package.MAX_TOTAL_BYTES', 3):
            with self.assertRaises(PackageError):
                Package.read(z)
        wrong = package(self.base / 'windows.zip', platform='windows-x86_64')
        with self.assertRaisesRegex(core.InstallError, 'platform'):
            core.preview(self.game, wrong)

    def test_package_corrupt_hash_without_duplicate_is_rejected(self):
        with zipfile.ZipFile(self.zip) as archive:
            manifest = json.loads(archive.read('manifest.json'))
        manifest['files'][0]['sha256'] = '0' * 64
        with zipfile.ZipFile(self.zip, 'w') as archive:
            archive.writestr('manifest.json', json.dumps(manifest))
            archive.writestr('payload/ValheimImpact.Core.dll', b'original runtime')
        with self.assertRaisesRegex(PackageError, 'integrity'):
            Package.read(self.zip)

    def test_case_alias_of_unowned_file_is_not_installed_beside_it(self):
        self.root.mkdir()
        (self.root / 'valheimimpact.core.dll').write_bytes(b'personal')
        with self.assertRaisesRegex(core.InstallError, '[Cc]ase'):
            core.preview(self.game, self.zip)

    def test_interrupted_transaction_recovers_and_can_install_again(self):
        plan = core.preview(self.game, self.zip)
        replace = os.replace
        def interrupt(source, destination):
            if str(destination).endswith('profile.json') and '/staging/' in str(source):
                raise KeyboardInterrupt('simulated process termination')
            return replace(source, destination)
        with patch('installer.core.os.replace', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                core.apply(plan, reviewed_token=plan.token)
        self.assertTrue((self.root / '.installer/pending.json').exists())
        with self.assertRaisesRegex(core.InstallError, 'Interrupted'):
            core.preview(self.game, self.zip)
        recovery = core.preview(self.game, operation='recover')
        core.apply(recovery, reviewed_token=recovery.token)
        self.assertFalse((self.root / 'ValheimImpact.Core.dll').exists())
        self.install()
        self.assertTrue(core.verify(self.game)['ok'])

    def test_package_changed_after_preview_is_rejected_without_writes(self):
        plan = core.preview(self.game, self.zip)
        package(self.zip, {'ValheimImpact.Core.dll': b'new'})
        with self.assertRaisesRegex(core.InstallError, 'changed after review'):
            core.apply(plan, reviewed_token=plan.token)
        self.assertFalse(self.root.exists())

    def test_cli_requires_exact_preview_token_and_verifies_installation(self):
        import subprocess
        import sys
        def cli(*args):
            return subprocess.run([sys.executable, '-m', 'installer', *map(str, args)], capture_output=True, text=True)
        preview = cli('preview', '--game', self.game, '--package', self.zip)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        token = json.loads(preview.stdout)['reviewToken']
        refused = cli('apply', '--game', self.game, '--package', self.zip, '--review-token', 'not-reviewed')
        self.assertEqual(refused.returncode, 2)
        self.assertFalse(self.root.exists())
        applied = cli('apply', '--game', self.game, '--package', self.zip, '--review-token', token)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        verified = cli('verify', '--game', self.game)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertTrue(json.loads(verified.stdout)['installed'])

    def test_steam_library_vdf_discovers_secondary_fixture_library(self):
        from installer.discovery import steam_games
        steam = self.base / 'steam'
        (steam / 'steamapps').mkdir(parents=True)
        library = self.base / 'Games Library'
        game = library / 'steamapps/common/Valheim'
        game.mkdir(parents=True)
        (steam / 'steamapps/libraryfolders.vdf').write_text('"libraryfolders" { "0" { "path" "' + str(library) + '" } }')
        self.assertEqual(steam_games(roots=[steam]), [str(game)])

    def test_linux_process_detector_identifies_fixture_without_stopping_it(self):
        import subprocess
        from installer.discovery import running_valheim
        process = subprocess.Popen(['valheim.x86_64', '30'], executable='/bin/sleep')
        try:
            detected = running_valheim()
            self.assertTrue(any('PID ' + str(process.pid) in item for item in detected))
            self.assertIsNone(process.poll())
        finally:
            # This is our disposable sleep fixture, never a real game process.
            process.terminate()
            process.wait(timeout=5)

    def test_failure_before_commit_does_not_poison_a_fresh_install(self):
        plan = core.preview(self.game, self.zip)
        original = core.atomic_json
        def fail_journal(path, value):
            if path.name == 'pending.json':
                raise OSError('simulated journal write failure')
            return original(path, value)
        with patch('installer.core.atomic_json', side_effect=fail_journal):
            with self.assertRaises(core.InstallError):
                core.apply(plan, reviewed_token=plan.token)
        self.assertFalse((self.root / 'ValheimImpact.Core.dll').exists())
        self.install()
        self.assertTrue(core.verify(self.game)['ok'])

    def test_real_process_exit_during_preparation_is_recoverable(self):
        import subprocess
        import sys
        code = "from installer import core; import os,sys; p=core.preview(sys.argv[1],sys.argv[2]); core.apply(p,reviewed_token=p.token,progress=lambda _:os._exit(42))"
        result = subprocess.run([sys.executable, '-c', code, str(self.game), str(self.zip)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertFalse((self.root / 'ValheimImpact.Core.dll').exists())
        # Documented recovery requires removing only the stale lock after the child exited.
        (self.root / '.installer/lock').unlink()
        recovered = core.preview(self.game, operation='recover')
        core.apply(recovered, reviewed_token=recovered.token)
        self.install()
        self.assertTrue(core.verify(self.game)['ok'])

    def test_archive_entry_limit_is_checked_before_zipfile_allocates_entries(self):
        excessive = self.base / 'many.zip'
        with zipfile.ZipFile(excessive, 'w') as archive:
            for index in range(20000):
                archive.writestr('entry' + str(index), b'')
        with patch('installer.package.zipfile.ZipFile', side_effect=AssertionError('archive parsed before bounds check')):
            with self.assertRaises(PackageError):
                Package.read(excessive)

    def test_update_rejects_file_directory_shape_changes_before_writing(self):
        one = package(self.base / 'shape-one.zip', {'assets/item': b'old'})
        self.install(one)
        two = package(self.base / 'shape-two.zip', {'assets/item/new.bundle': b'new'}, version='0.2.0')
        with self.assertRaisesRegex(core.InstallError, 'shape'):
            core.preview(self.game, two)
        self.assertEqual((self.root / 'assets/item').read_bytes(), b'old')

    def test_maximum_legal_package_has_readable_receipt_and_rollback_snapshot(self):
        entries = {('a' * 205 + f'{index:010}.dll'): b'x' for index in range(4096)}
        maximum = package(self.base / 'maximum.zip', entries)
        plan = core.preview(self.game, maximum)
        core.validate_receipt(plan.desired_receipt)
        self.assertEqual(len(plan.desired_receipt['files']), 4097)
        identifier = 'a' * 32
        backup = self.root / '.installer/backups' / identifier
        backup.mkdir(parents=True)
        snapshot = dict(schemaVersion=1, beforeReceipt=None, changes=[dict(path=c.path, before=c.before, after=c.after) for c in plan.changes])
        core.atomic_json(backup / 'snapshot.json', snapshot)
        self.assertGreater((backup / 'snapshot.json').stat().st_size, 2 * 1024**2)
        self.assertEqual(len(core.snapshot_at(self.root, identifier)['changes']), 4097)
