"""Exercise the local profile tool against disposable game and pack fixtures."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/mod_profile.py'


class ModProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.game = self.base / 'Valheim'
        self.plugins = self.game / 'BepInEx/plugins'
        self.plugins.mkdir(parents=True)
        (self.game / 'valheim_Data').mkdir()
        (self.game / 'valheim_Data/globalgamemanagers').write_bytes(b'game marker')
        (self.game / 'valheim.x86_64').write_bytes(b'game executable')
        (self.game / 'BepInEx/core').mkdir()
        (self.game / 'BepInEx/core/BepInEx.dll').write_bytes(b'core preserved')
        (self.game / 'BepInEx/config').mkdir()
        (self.game / 'BepInEx/config/legacy.cfg').write_bytes(b'config preserved')
        (self.game / 'BepInEx/patchers').mkdir()
        (self.plugins / 'Legacy.dll').write_bytes(b'legacy executable')
        (self.plugins / 'pack').mkdir()
        (self.plugins / 'pack/small.txt').write_text('a small support file')
        self.large_pack = self.plugins / 'pack/original.pack'
        with self.large_pack.open('wb') as stream:
            stream.truncate(28 * 1024**3)
        self.external = self.base / 'external.resS'
        self.external.write_bytes(b'original external data')
        (self.plugins / 'relative.resS').symlink_to('pack/original.pack')
        (self.plugins / 'absolute.resS').symlink_to(self.external)
        (self.plugins / 'linked-directory').symlink_to(self.base, target_is_directory=True)
        self.vault = self.base / 'profiles'
        self.profile = self.vault / 'legacy'
        self.backup = self.profile / 'plugins'
        self.journal = self.profile / 'journal.json'

    def tearDown(self):
        self.temp.cleanup()

    def command(self, operation, *, prelude=None, vault=None, profile='legacy', ok=True):
        args = [operation, '--game', str(self.game), '--vault', str(vault or self.vault), '--profile', profile]
        if prelude:
            code = 'from tools import mod_profile as m\n' + prelude + '\nraise SystemExit(m.main())\n'
            cmd = [sys.executable, '-c', code, *args]
        else:
            cmd = [sys.executable, str(SCRIPT), *args]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        return result

    def preserved_metadata(self, path):
        info = path.lstat()
        return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns

    def assert_refused(self, result, reason):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(reason, result.stderr)

    def test_new_vault_ancestors_are_synced_before_legacy_rename(self):
        from tools import mod_profile as m
        from unittest.mock import patch
        vault = self.base / 'nested' / 'profiles'
        events = []
        real_sync, real_rename = m.sync_directory, m.rename_no_replace
        def sync(path):
            events.append(('sync', path))
            real_sync(path)
        def rename(source, destination):
            events.append(('rename', source))
            real_rename(source, destination)
        with patch.object(m, 'sync_directory', side_effect=sync), \
             patch.object(m, 'rename_no_replace', side_effect=rename), \
             patch.object(m.discovery, 'running_valheim', return_value=[]):
            m.operate('isolate', self.game, vault, 'legacy')
        first_rename = next(i for i, e in enumerate(events) if e[0] == 'rename')
        self.assertIn(('sync', self.base), events[:first_rename])
        self.assertIn(('sync', self.base / 'nested'), events[:first_rename])
        self.assertIn(('sync', vault), events[:first_rename])

    def test_inspect_is_read_only_and_never_hashes_pack_or_follows_links(self):
        before = self.preserved_metadata(self.plugins)
        report = self.command('inspect')
        self.assertEqual(report['phase'], 'unmanaged')
        inventory = {entry['path']: entry for entry in report['activeInventory']}
        self.assertEqual(inventory['Legacy.dll']['sha256'], hashlib.sha256(b'legacy executable').hexdigest())
        self.assertNotIn('sha256', inventory['pack/original.pack'])
        self.assertEqual(inventory['pack/original.pack']['size'], 28 * 1024**3)
        self.assertEqual(inventory['relative.resS']['target'], 'pack/original.pack')
        self.assertEqual(inventory['absolute.resS']['target'], str(self.external))
        self.assertFalse(any(name.startswith('linked-directory/') for name in inventory))
        self.assertFalse(self.vault.exists())
        self.assertEqual(self.preserved_metadata(self.plugins), before)

    def test_isolate_restore_roundtrip_preserves_inodes_metadata_links_core_and_config(self):
        paths = ['.', 'Legacy.dll', 'pack', 'pack/original.pack', 'relative.resS', 'absolute.resS', 'linked-directory']
        before = {name: self.preserved_metadata(self.plugins / name) for name in paths}
        result = self.command('isolate')
        self.assertEqual(result['phase'], 'isolated')
        self.assertEqual(list(self.plugins.iterdir()), [])
        for name in paths:
            self.assertEqual(self.preserved_metadata(self.backup / name), before[name], name)
        self.assertEqual(os.readlink(self.backup / 'relative.resS'), 'pack/original.pack')
        self.assertEqual(os.readlink(self.backup / 'absolute.resS'), str(self.external))
        self.assertEqual(self.command('inspect')['phase'], 'isolated')
        result = self.command('restore')
        self.assertEqual(result['phase'], 'restored')
        self.assertFalse(self.backup.exists())
        for name in paths:
            self.assertEqual(self.preserved_metadata(self.plugins / name), before[name], name)
        self.assertEqual((self.game / 'BepInEx/core/BepInEx.dll').read_bytes(), b'core preserved')
        self.assertEqual((self.game / 'BepInEx/config/legacy.cfg').read_bytes(), b'config preserved')
        self.assertEqual(self.external.read_bytes(), b'original external data')
        self.assertEqual(json.loads(self.journal.read_text())['phase'], 'restored')

    def test_restore_refuses_new_plugins_without_deleting_them(self):
        self.command('isolate')
        new_mod = self.plugins / 'ValheimImpact.dll'
        new_mod.write_bytes(b'new authored runtime')
        self.assert_refused(self.command('restore', ok=False), 'not empty')
        self.assertEqual(new_mod.read_bytes(), b'new authored runtime')
        self.assertTrue((self.backup / 'Legacy.dll').exists())
        self.assertEqual(json.loads(self.journal.read_text())['phase'], 'isolated')

    def test_running_game_and_detection_failure_refuse_all_mutations(self):
        running = "m.discovery.running_valheim = lambda: ['valheim.x86_64 (PID 123)']"
        self.assert_refused(self.command('isolate', prelude=running, ok=False), 'running')
        self.assertFalse(self.vault.exists())
        self.command('isolate')
        for operation in ['restore', 'recover']:
            self.assert_refused(self.command(operation, prelude=running, ok=False), 'running')
        failure = "def unavailable():\n    raise m.discovery.DetectionError('cannot inspect processes')\nm.discovery.running_valheim = unavailable"
        self.assert_refused(self.command('restore', prelude=failure, ok=False), 'cannot inspect processes')
        self.assertTrue(self.backup.exists())
        self.assertEqual(list(self.plugins.iterdir()), [])

    def test_profile_collision_and_unsafe_profile_name_refuse_without_moving_plugins(self):
        self.profile.mkdir(parents=True)
        marker = self.profile / 'personal.txt'
        marker.write_text('preserve')
        self.assert_refused(self.command('isolate', ok=False), 'already exists')
        self.assert_refused(self.command('isolate', profile='../escaped', ok=False), 'profile name')
        self.assertEqual(marker.read_text(), 'preserve')
        self.assertTrue((self.plugins / 'Legacy.dll').exists())

    def test_last_moment_destination_collision_does_not_overwrite_empty_directory(self):
        prelude = ('rename = m.rename_no_replace\n'
                   'def collide(source, destination):\n'
                   '    destination.mkdir()\n'
                   '    rename(source, destination)\n'
                   'm.rename_no_replace = collide')
        self.assert_refused(self.command('isolate', prelude=prelude, ok=False), 'already exists')
        self.assertTrue((self.plugins / 'Legacy.dll').exists())
        self.assertEqual(list(self.backup.iterdir()), [])

    def test_inventory_hash_and_metadata_limits_refuse_before_creating_vault(self):
        for prelude, message in [('m.MAX_HASH_BYTES = 1', 'hash byte limit'),
                                 ('m.MAX_INVENTORY_BYTES = 1', 'metadata byte limit')]:
            with self.subTest(limit=message):
                self.assert_refused(self.command('isolate', prelude=prelude, ok=False), message)
                self.assertFalse(self.vault.exists())
                self.assertTrue(self.large_pack.exists())

    def test_symlink_swapped_during_inventory_never_redirects_nested_reads(self):
        trap = self.base / 'trap'
        trap.mkdir()
        (trap / 'original.pack').write_bytes(b'outside content must not be read')
        (trap / 'small.txt').write_bytes(b'outside supporting content')
        prelude = ('read_metadata = m.metadata\n'
                   'def swap(path, relative, **kwargs):\n'
                   "    if relative == 'pack/original.pack' and not getattr(swap, 'done', False):\n"
                   '        swap.done = True\n'
                   "        folder = m.Path(m.sys.argv[m.sys.argv.index('--game') + 1]) / 'BepInEx/plugins/pack'\n"
                   "        folder.rename(folder.with_name('preserved-pack'))\n"
                   "        folder.symlink_to(folder.parents[3] / 'trap', target_is_directory=True)\n"
                   '    return read_metadata(path, relative, **kwargs)\n'
                   'm.metadata = swap')
        report = self.command('inspect', prelude=prelude)
        entries = {entry['path']: entry for entry in report['activeInventory']}
        self.assertEqual(entries['pack/original.pack']['size'], 28 * 1024**3)
        self.assertNotIn('sha256', entries['pack/original.pack'])

    def test_vault_inside_game_or_through_symlink_is_rejected(self):
        self.assert_refused(self.command('isolate', vault=self.game / 'BepInEx/disabled', ok=False), 'outside the game')
        destination = self.base / 'destination'
        destination.mkdir()
        self.vault.symlink_to(destination, target_is_directory=True)
        self.assert_refused(self.command('isolate', ok=False), 'symlink')
        self.assertEqual(list(destination.iterdir()), [])

    def test_plugin_root_symlink_is_rejected(self):
        elsewhere = self.base / 'elsewhere'
        self.plugins.rename(elsewhere)
        self.plugins.symlink_to(elsewhere, target_is_directory=True)
        self.assert_refused(self.command('isolate', ok=False), 'symlink')
        self.assertTrue((elsewhere / 'Legacy.dll').exists())

    def test_nonempty_patchers_block_isolation(self):
        patcher = self.game / 'BepInEx/patchers/LegacyPatcher.dll'
        patcher.write_bytes(b'patcher untouched')
        self.assert_refused(self.command('isolate', ok=False), 'patchers')
        self.assertFalse(self.vault.exists())
        self.assertEqual(patcher.read_bytes(), b'patcher untouched')

    def test_cross_filesystem_vault_is_rejected_without_copying(self):
        shared = Path('/dev/shm')
        if not shared.is_dir() or shared.stat().st_dev == self.plugins.stat().st_dev:
            self.skipTest('requires a second local filesystem')
        with tempfile.TemporaryDirectory(dir=shared) as other:
            vault = Path(other) / 'profiles'
            self.assert_refused(self.command('isolate', vault=vault, ok=False), 'same filesystem')
            self.assertFalse(vault.exists())
        self.assertTrue(self.large_pack.exists())

    def test_recover_completes_isolation_interrupted_before_initial_rename(self):
        prelude = 'import os\ndef interrupted(source, destination):\n    os._exit(73)\nm.rename_no_replace = interrupted'
        result = self.command('isolate', prelude=prelude, ok=False)
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertEqual(json.loads(self.journal.read_text())['phase'], 'isolating')
        self.assertTrue((self.plugins / 'Legacy.dll').exists())
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.command('recover')['phase'], 'isolated')
        self.assertEqual(list(self.plugins.iterdir()), [])
        self.command('restore')

    def test_recover_completes_isolation_interrupted_after_initial_rename(self):
        prelude = 'import os\nrename = m.rename_no_replace\ndef interrupted(source, destination):\n    rename(source, destination)\n    os._exit(73)\nm.rename_no_replace = interrupted'
        result = self.command('isolate', prelude=prelude, ok=False)
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertFalse(self.plugins.exists())
        self.assertTrue(self.backup.exists())
        self.assertEqual(self.command('recover')['phase'], 'isolated')
        self.assertEqual(list(self.plugins.iterdir()), [])
        self.command('restore')

    def test_recover_completes_restore_interrupted_after_empty_directory_removal(self):
        self.command('isolate')
        prelude = 'import os\nrmdir = os.rmdir\ndef interrupted(path, *args, **kwargs):\n    rmdir(path, *args, **kwargs)\n    os._exit(73)\nm.os.rmdir = interrupted'
        result = self.command('restore', prelude=prelude, ok=False)
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertFalse(self.plugins.exists())
        self.assertTrue(self.backup.exists())
        self.assertEqual(self.command('recover')['phase'], 'restored')
        self.assertEqual((self.plugins / 'Legacy.dll').read_bytes(), b'legacy executable')

    def test_recover_completes_restore_interrupted_after_rename(self):
        self.command('isolate')
        prelude = 'import os\nrename = m.rename_no_replace\ndef interrupted(source, destination):\n    rename(source, destination)\n    os._exit(73)\nm.rename_no_replace = interrupted'
        result = self.command('restore', prelude=prelude, ok=False)
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertTrue((self.plugins / 'Legacy.dll').exists())
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.command('recover')['phase'], 'restored')

    def test_restore_refuses_modified_dll_even_with_original_size_and_mtime(self):
        self.command('isolate')
        binary = self.backup / 'Legacy.dll'
        info = binary.stat()
        binary.write_bytes(b'tamper executable')
        os.utime(binary, ns=(info.st_atime_ns, info.st_mtime_ns))
        self.assert_refused(self.command('restore', ok=False), 'inventory changed')
        self.assertEqual(binary.read_bytes(), b'tamper executable')
        self.assertTrue(self.backup.exists())

    def test_recover_refuses_ambiguous_foreign_plugin_directory(self):
        prelude = 'import os\nrename = m.rename_no_replace\ndef interrupted(source, destination):\n    rename(source, destination)\n    os._exit(73)\nm.rename_no_replace = interrupted'
        self.assertEqual(self.command('isolate', prelude=prelude, ok=False).returncode, 73)
        self.plugins.mkdir()
        foreign = self.plugins / 'Foreign.dll'
        foreign.write_bytes(b'preserve foreign plugin')
        self.assert_refused(self.command('recover', ok=False), 'not empty')
        self.assertEqual(foreign.read_bytes(), b'preserve foreign plugin')
        self.assertTrue(self.backup.exists())

    def test_restore_refuses_replaced_empty_active_directory(self):
        self.command('isolate')
        original_empty = self.base / 'original-empty'
        self.plugins.rename(original_empty)
        self.plugins.mkdir()
        self.assert_refused(self.command('restore', ok=False), 'identity')
        self.assertTrue(original_empty.exists())
        self.assertTrue(self.backup.exists())

    def test_journal_cannot_redirect_restore_paths(self):
        self.command('isolate')
        journal = json.loads(self.journal.read_text())
        journal['game'] = str(self.base)
        self.journal.write_text(json.dumps(journal))
        self.assert_refused(self.command('restore', ok=False), 'journal')
        self.assertTrue(self.backup.exists())

    def test_simultaneous_operation_on_same_game_is_refused_even_with_different_vault(self):
        import fcntl
        descriptor = os.open(self.game, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assert_refused(self.command('isolate', ok=False), 'another profile operation')
            self.assertFalse(self.vault.exists())
        finally:
            os.close(descriptor)


if __name__ == '__main__':
    unittest.main()
