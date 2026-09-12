"""Installer private payloads must stay outside BepInEx recursive DLL discovery."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from installer import core
from tests import test_installer as fixtures
package = fixtures.package


class InstallerStorageTests(unittest.TestCase):
    setUp = fixtures.InstallerTests.setUp
    tearDown = fixtures.InstallerTests.tearDown
    install = fixtures.InstallerTests.install

    def private_dlls(self):
        # Mirrors TypeLoader's *.dll / SearchOption.AllDirectories candidate scan.
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')
                      if p.is_file() and p.suffix.casefold() == '.dll' and '.installer' in p.parts)

    def test_update_rollback_uninstall_leave_no_discoverable_private_dlls(self):
        self.install()
        self.assertEqual(self.private_dlls(), [])
        self.install(package(self.base / 'two.zip', {'ValheimImpact.Core.dll': b'updated runtime'}, version='0.2.0'))
        self.assertEqual(self.private_dlls(), [])
        for operation in ('rollback', 'uninstall', 'rollback'):
            plan = core.preview(self.game, operation=operation)
            core.apply(plan, reviewed_token=plan.token)
            self.assertEqual(self.private_dlls(), [], operation)
        self.assertEqual((self.root / 'ValheimImpact.Core.dll').read_bytes(), b'original runtime')
        self.assertTrue(core.verify(self.game)['ok'])

    def test_staging_and_backup_bytes_are_undiscoverable_before_commit(self):
        self.install()
        newer = package(self.base / 'two.zip', {'ValheimImpact.Core.dll': b'updated runtime'}, version='0.2.0')
        plan = core.preview(self.game, newer)
        original = core.atomic_json
        observations = []
        def observe(path, value):
            if path.name == 'pending.json':
                staged = list((self.root / '.installer/staging').rglob('*'))
                observations.append((self.private_dlls(), any(p.is_file() and p.suffix == '.payload' for p in staged)))
            return original(path, value)
        with patch('installer.core.atomic_json', side_effect=observe):
            core.apply(plan, reviewed_token=plan.token)
        self.assertEqual(observations, [([], True)])

    def test_real_staging_crash_keeps_only_encoded_files_and_recovers(self):
        self.install()
        newer = package(self.base / 'two.zip', {'ValheimImpact.Core.dll': b'updated runtime'}, version='0.2.0')
        code = '''from installer import core
import os, sys, tempfile
from pathlib import Path
assert Path(sys.argv[1]).is_relative_to(tempfile.gettempdir())
core.running_valheim = lambda: []
original = os.fsync
def crash(fd):
    name = os.readlink('/proc/self/fd/' + str(fd))
    if '/.installer/staging/' in name:
        os._exit(43)
    return original(fd)
core.os.fsync = crash
plan = core.preview(sys.argv[1], sys.argv[2])
core.apply(plan, reviewed_token=plan.token)
'''
        result = subprocess.run([sys.executable, '-c', code, str(self.game), str(newer)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 43, result.stderr)
        self.assertEqual(self.private_dlls(), [])
        self.assertEqual((self.root / 'ValheimImpact.Core.dll').read_bytes(), b'original runtime')
        (self.root / '.installer/lock').unlink()
        plan = core.preview(self.game, operation='recover')
        core.apply(plan, reviewed_token=plan.token)
        self.assertTrue(core.verify(self.game)['ok'])
        self.assertEqual(self.private_dlls(), [])

    def legacy_backup(self):
        self.install()
        self.install(package(self.base / 'two.zip', {'ValheimImpact.Core.dll': b'updated runtime'}, version='0.2.0'))
        receipt = core.read_json(self.root / '.installer/receipt.json')
        folder = self.root / '.installer/backups' / receipt['lastBackup']
        snapshot = core.read_json(folder / 'snapshot.json')
        for item in snapshot['changes']:
            if item['before'] is not None:
                original = folder / 'files' / item['path']
                original.parent.mkdir(parents=True, exist_ok=True)
                core.payload_path(folder / 'files', item['path']).rename(original)
        snapshot.pop('storageVersion')
        core.atomic_json(folder / 'snapshot.json', snapshot)
        return folder, snapshot

    def test_legacy_migration_is_explicit_preserves_bytes_and_allows_rollback(self):
        from installer import state_migration
        folder, snapshot = self.legacy_backup()
        self.assertTrue(self.private_dlls())
        self.assertFalse(core.verify(self.game)['ok'])
        with self.assertRaisesRegex(core.InstallError, 'Legacy'):
            core.preview(self.game, operation='rollback')
        plan = state_migration.preview(self.game)
        self.assertTrue(self.private_dlls(), 'preview cannot rename legacy files')
        with self.assertRaises(core.InstallError):
            state_migration.apply(plan, reviewed_token='wrong')
        state_migration.apply(plan, reviewed_token=plan['reviewToken'])
        self.assertEqual(self.private_dlls(), [])
        self.assertEqual(core.read_json(folder / 'snapshot.json')['storageVersion'], 2)
        plan = core.preview(self.game, operation='rollback')
        core.apply(plan, reviewed_token=plan.token)
        self.assertEqual((self.root / 'ValheimImpact.Core.dll').read_bytes(), b'original runtime')
        self.assertTrue(core.verify(self.game)['ok'])
        self.assertEqual(self.private_dlls(), [])

    def test_legacy_migration_refuses_running_game_modified_or_unknown_state(self):
        from installer import state_migration
        folder, snapshot = self.legacy_backup()
        plan = state_migration.preview(self.game)
        with patch('installer.core.running_valheim', return_value=['Valheim running']):
            with self.assertRaises(core.InstallError):
                state_migration.apply(plan, reviewed_token=plan['reviewToken'])
        self.assertTrue(self.private_dlls())
        file = folder / 'files/ValheimImpact.Core.dll'
        file.write_bytes(b'foreign edit')
        with self.assertRaises(core.InstallError):
            state_migration.preview(self.game)
        file.write_bytes(b'original runtime')
        (folder / 'files/unowned.dll').write_bytes(b'unowned')
        with self.assertRaises(core.InstallError):
            state_migration.preview(self.game)
        self.assertEqual((folder / 'files/unowned.dll').read_bytes(), b'unowned')

    def test_legacy_migration_destination_collision_is_not_overwritten(self):
        from installer import state_migration
        folder, snapshot = self.legacy_backup()
        destination = core.payload_path(folder / 'files', 'ValheimImpact.Core.dll')
        destination.write_bytes(b'foreign collision')
        with self.assertRaises(core.InstallError):
            state_migration.preview(self.game)
        self.assertEqual(destination.read_bytes(), b'foreign collision')
        self.assertEqual((folder / 'files/ValheimImpact.Core.dll').read_bytes(), b'original runtime')

    def test_migration_resumes_after_atomic_destination_creation(self):
        from installer import state_migration
        folder, snapshot = self.legacy_backup()
        plan = state_migration.preview(self.game)
        unlink = Path.unlink
        def interrupt(path, *args, **kwargs):
            if path.name == 'ValheimImpact.Core.dll' and '/files/' in str(path):
                raise KeyboardInterrupt('after atomic link, before source removal')
            return unlink(path, *args, **kwargs)
        with patch('pathlib.Path.unlink', new=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                state_migration.apply(plan, reviewed_token=plan['reviewToken'])
        self.assertTrue((self.root / '.installer/storage-migration.json').exists())
        with self.assertRaisesRegex(core.InstallError, 'migration'):
            core.preview(self.game, operation='rollback')
        resumed = state_migration.preview(self.game)
        self.assertEqual(resumed['reviewToken'], plan['reviewToken'])
        state_migration.apply(resumed, reviewed_token=resumed['reviewToken'])
        self.assertEqual(self.private_dlls(), [])
        self.assertFalse((self.root / '.installer/storage-migration.json').exists())
        self.assertTrue(core.verify(self.game)['ok'])

    def test_legacy_interrupted_commit_recovers_staging_then_requires_migration(self):
        from installer import state_migration
        folder, snapshot = self.legacy_backup()
        identifier = folder.name
        staged = self.root / '.installer/staging' / identifier
        staged.mkdir(parents=True)
        (staged / 'ValheimImpact.Core.dll').write_bytes(b'updated runtime')
        core.atomic_json(self.root / '.installer/pending.json', dict(backup=identifier))
        with self.assertRaisesRegex(core.InstallError, 'Recover'):
            state_migration.preview(self.game)
        recovery = core.preview(self.game, operation='recover')
        result = core.apply(recovery, reviewed_token=recovery.token)
        self.assertTrue(result['migrationRequired'])
        self.assertFalse(staged.exists())
        self.assertEqual((self.root / 'ValheimImpact.Core.dll').read_bytes(), b'original runtime')
        self.assertFalse(core.verify(self.game)['ok'])
        review = state_migration.preview(self.game)
        state_migration.apply(review, reviewed_token=review['reviewToken'])
        self.assertEqual(self.private_dlls(), [])
        self.assertTrue(core.verify(self.game)['ok'])

    def test_recovery_refuses_unknown_staging_before_active_files_change(self):
        folder, snapshot = self.legacy_backup()
        staged = self.root / '.installer/staging' / folder.name
        staged.mkdir(parents=True)
        (staged / 'unowned.dll').write_bytes(b'preserve')
        core.atomic_json(self.root / '.installer/pending.json', dict(backup=folder.name))
        recovery = core.preview(self.game, operation='recover')
        with self.assertRaisesRegex(core.InstallError, 'staging'):
            core.apply(recovery, reviewed_token=recovery.token)
        self.assertEqual((self.root / 'ValheimImpact.Core.dll').read_bytes(), b'updated runtime')
        self.assertEqual((staged / 'unowned.dll').read_bytes(), b'preserve')

    def test_migration_resumes_metadata_replacement_interruption(self):
        from installer import state_migration
        folder, snapshot = self.legacy_backup()
        review = state_migration.preview(self.game)
        replace = os.replace
        def interrupt(source, destination):
            if Path(source).name == '.snapshot-migration.payload':
                raise KeyboardInterrupt('before snapshot rename')
            return replace(source, destination)
        with patch('installer.state_migration.os.replace', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                state_migration.apply(review, reviewed_token=review['reviewToken'])
        self.assertTrue((self.root / '.installer/storage-migration.json').exists())
        resumed = state_migration.preview(self.game)
        state_migration.apply(resumed, reviewed_token=resumed['reviewToken'])
        self.assertEqual(self.private_dlls(), [])
        self.assertTrue(core.verify(self.game)['ok'])

    def test_migration_resumes_empty_and_partial_metadata_writes(self):
        from installer import state_migration
        folder, snapshot = self.legacy_backup()
        review = state_migration.preview(self.game)
        temporary = folder / '.snapshot-migration.payload'
        desired = core.encoded(dict(snapshot, storageVersion=2))
        original_open = Path.open

        class InterruptedWriter:
            def __init__(self, writer, count):
                self.writer, self.count = writer, count

            def __enter__(self):
                self.writer.__enter__()
                return self

            def __exit__(self, *args):
                return self.writer.__exit__(*args)

            def write(self, data):
                self.writer.write(data[:self.count])
                self.writer.flush()
                os.fsync(self.writer.fileno())
                raise KeyboardInterrupt('during snapshot metadata write')

        for count in (0, 11):
            def interrupt(path, mode='r', *args, **kwargs):
                writer = original_open(path, mode, *args, **kwargs)
                return InterruptedWriter(writer, count) if path == temporary and mode in ('xb', 'ab') else writer
            with patch('pathlib.Path.open', new=interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    state_migration.apply(review, reviewed_token=review['reviewToken'])
            self.assertEqual(temporary.read_bytes(), desired[:count])
            self.assertEqual(core.read_json(folder / 'snapshot.json'), snapshot)
            self.assertEqual(self.private_dlls(), [])
            review = state_migration.preview(self.game)
            self.assertTrue(review['resuming'])

        # A foreign or damaged prefix is not a resumable write and is preserved.
        temporary.write_bytes(b'foreign')
        with self.assertRaisesRegex(core.InstallError, 'metadata temporary'):
            state_migration.preview(self.game)
        self.assertEqual(temporary.read_bytes(), b'foreign')
        temporary.write_bytes(desired[:11])
        state_migration.apply(review, reviewed_token=review['reviewToken'])
        self.assertFalse(temporary.exists())
        self.assertFalse((self.root / '.installer/storage-migration.json').exists())
        rollback = core.preview(self.game, operation='rollback')
        core.apply(rollback, reviewed_token=rollback.token)
        self.assertEqual((self.root / 'ValheimImpact.Core.dll').read_bytes(), b'original runtime')
        self.assertTrue(core.verify(self.game)['ok'])
        self.assertEqual(self.private_dlls(), [])

    def test_migration_stale_preview_and_symlinks_are_rejected(self):
        from installer import state_migration
        folder, snapshot = self.legacy_backup()
        review = state_migration.preview(self.game)
        source = folder / 'files/ValheimImpact.Core.dll'
        source.write_bytes(b'modified after review')
        with self.assertRaises(core.InstallError):
            state_migration.apply(review, reviewed_token=review['reviewToken'])
        source.unlink()
        source.symlink_to(self.other)
        with self.assertRaises(core.InstallError):
            state_migration.preview(self.game)
        self.assertEqual(self.other.read_bytes(), b'untouched')
