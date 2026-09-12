"""Inspect, isolate, restore, or recover a local Linux Valheim plugin profile.

Legacy packs move by same-filesystem directory rename. Symlinks are inventoried
with lstat/readlink and never traversed. This is separate from the public installer.
"""
import argparse
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from installer import discovery


MAX_ENTRIES = 100_000
MAX_JOURNAL_BYTES = 64 * 1024**2
MAX_INVENTORY_BYTES = 32 * 1024**2
MAX_DEPTH = 128
SMALL_FILE_BYTES = 1024**2
MAX_EXECUTABLE_BYTES = 64 * 1024**2
MAX_HASH_BYTES = 512 * 1024**2


class ProfileError(ValueError):
    pass


def no_links(path):
    path = Path(os.path.abspath(Path(path).expanduser()))
    for component in reversed([path, *path.parents]):
        try:
            if stat.S_ISLNK(component.lstat().st_mode):
                raise ProfileError('Refusing symlink in operation path: ' + str(component))
        except FileNotFoundError:
            pass
    return path


def exists(path):
    return os.path.lexists(path)


def directory(path):
    no_links(path)
    if not path.is_dir():
        raise ProfileError('Expected a real directory: ' + str(path))


def identity(path):
    directory(path)
    info = path.lstat()
    return {'device': info.st_dev, 'inode': info.st_ino}


@dataclass(frozen=True)
class Paths:
    game: Path
    vault: Path
    name: str

    @property
    def active(self):
        return self.game / 'BepInEx/plugins'

    @property
    def profile(self):
        return self.vault / self.name

    @property
    def saved(self):
        return self.profile / 'plugins'

    @property
    def journal(self):
        return self.profile / 'journal.json'


def paths_for(game, vault, name):
    if not sys.platform.startswith('linux'):
        raise ProfileError('This local profile utility currently supports Linux only')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', name):
        raise ProfileError('Invalid profile name. Use 1 to 64 letters, digits, dots, underscores or hyphens')
    paths = Paths(no_links(game), no_links(vault), name)
    directory(paths.game)
    if paths.vault.is_relative_to(paths.game):
        raise ProfileError('Profile vault must be outside the game directory')
    for marker in ['valheim.x86_64', 'valheim_Data/globalgamemanagers', 'BepInEx/core/BepInEx.dll']:
        path = no_links(paths.game / marker)
        if not path.is_file():
            raise ProfileError('Valheim or BepInEx marker missing: ' + str(path))
    for path in [paths.active, paths.profile, paths.saved, paths.journal]:
        no_links(path)
    ancestor = paths.vault
    while not ancestor.exists():
        ancestor = ancestor.parent
    directory(ancestor)
    if ancestor.stat().st_dev != (paths.game / 'BepInEx').stat().st_dev:
        raise ProfileError('Profile vault must be on the same filesystem as BepInEx/plugins')
    return paths


def closed_game():
    try:
        processes = discovery.running_valheim()
    except discovery.DetectionError as error:
        raise ProfileError(str(error)) from error
    if processes:
        raise ProfileError('Valheim is running. Close it normally before making changes: ' + ', '.join(processes))


@contextmanager
def game_lock(game):
    # An advisory lock on the existing directory needs no game-side lock file.
    # The same game remains locked even if another invocation selects another vault.
    import fcntl
    descriptor = os.open(game, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ProfileError('There is another profile operation on this game') from error
        yield
    finally:
        os.close(descriptor)


def metadata(path, relative, *, dir_fd=None):
    info = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
    kind = ('symlink' if stat.S_ISLNK(info.st_mode) else 'directory' if stat.S_ISDIR(info.st_mode)
            else 'file' if stat.S_ISREG(info.st_mode) else None)
    if kind is None:
        raise ProfileError('Unsupported special file in plugin tree: ' + str(path))
    return dict(path=relative, kind=kind, device=info.st_dev, inode=info.st_ino,
                mode=info.st_mode, uid=info.st_uid, gid=info.st_gid,
                size=info.st_size, mtimeNs=info.st_mtime_ns)


def file_digest(path, before, *, dir_fd=None):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_dev != before['device'] or info.st_ino != before['inode']:
            raise ProfileError('File changed during inventory: ' + str(path))
        digest = hashlib.sha256()
        remaining = before['size']
        while remaining:
            block = stream.read(min(1024**2, remaining))
            if not block:
                raise ProfileError('File changed during inventory: ' + str(path))
            digest.update(block)
            remaining -= len(block)
        if stream.read(1) or metadata(path, before['path'], dir_fd=dir_fd) != before:
            raise ProfileError('File changed during inventory: ' + str(path))
        return digest.hexdigest()


def inventory(root):
    """Record every entry without following links or reading large resource data."""
    directory(root)
    root_device = root.lstat().st_dev
    records = []
    hash_bytes = 0
    metadata_bytes = 0

    def visit(path, relative, parent_fd=None, depth=0):
        nonlocal hash_bytes, metadata_bytes
        if depth > MAX_DEPTH:
            raise ProfileError('Plugin inventory exceeds directory depth limit')
        if len(records) >= MAX_ENTRIES:
            raise ProfileError('Plugin inventory exceeds entry limit')
        record = metadata(path, relative, dir_fd=parent_fd)
        if record['device'] != root_device:
            raise ProfileError('Plugin tree crosses filesystem boundaries: ' + relative)
        if record['kind'] == 'symlink':
            record['target'] = os.readlink(path, dir_fd=parent_fd)
        elif record['kind'] == 'file':
            name = Path(path)
            executable = name.suffix.lower() in ('.dll', '.exe', '.so', '.dylib') or '.so.' in name.name.lower()
            if executable and record['size'] > MAX_EXECUTABLE_BYTES:
                raise ProfileError('Executable exceeds bounded hash limit: ' + relative)
            if executable or record['size'] <= SMALL_FILE_BYTES:
                hash_bytes += record['size']
                if hash_bytes > MAX_HASH_BYTES:
                    raise ProfileError('Plugin inventory exceeds total hash byte limit')
                record['sha256'] = file_digest(path, record, dir_fd=parent_fd)
        metadata_bytes += len(json.dumps(record, indent=2).encode())
        if metadata_bytes > MAX_INVENTORY_BYTES:
            raise ProfileError('Plugin inventory exceeds metadata byte limit')
        records.append(record)
        if record['kind'] == 'directory':
            # Keep parent descriptors open and address children relative to them.
            # Swapping a parent directory for a symlink cannot redirect nested reads.
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
            try:
                info = os.fstat(descriptor)
                if (info.st_dev, info.st_ino) != (record['device'], record['inode']):
                    raise ProfileError('Directory changed during inventory: ' + relative)
                with os.scandir(descriptor) as entries:
                    children = []
                    for entry in entries:
                        children.append(entry.name)
                        if len(records) + len(children) > MAX_ENTRIES:
                            raise ProfileError('Plugin inventory exceeds entry limit')
                for name in sorted(children):
                    visit(name, name if relative == '.' else relative + '/' + name, descriptor, depth + 1)
            finally:
                os.close(descriptor)
    visit(root, '.')
    return sorted(records, key=lambda entry: entry['path'])


def verify_inventory(root, expected):
    current = inventory(root)
    if current != expected:
        before = {entry['path']: entry for entry in expected}
        after = {entry['path']: entry for entry in current}
        changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
        raise ProfileError('Legacy plugin inventory changed: ' + ', '.join(changed[:10]))


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_directories(path):
    """Persist each new ancestor's directory entry before moving legacy content."""
    missing = []
    current = path
    while not exists(current):
        missing.append(current)
        current = current.parent
    directory(current)
    for child in reversed(missing):
        child.mkdir()
        sync_directory(child.parent)


def rename_no_replace(source, destination):
    """Use Linux's atomic no-replace rename, including when the destination is empty."""
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError as error:
        raise ProfileError('This system lacks renameat2; refusing an overwrite-capable fallback') from error
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise ProfileError('Rename destination already exists: ' + str(destination))
        raise OSError(code, os.strerror(code), str(destination))


def write_journal(paths, journal):
    data = (json.dumps(journal, indent=2, sort_keys=True) + '\n').encode()
    if len(data) > MAX_JOURNAL_BYTES:
        raise ProfileError('Profile journal exceeds size limit')
    no_links(paths.journal)
    temporary = paths.profile / ('.journal-' + uuid.uuid4().hex + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, paths.journal)
        sync_directory(paths.profile)
    finally:
        if exists(temporary):
            temporary.unlink()


def read_journal(paths):
    path = no_links(paths.journal)
    if not path.is_file() or path.stat().st_size > MAX_JOURNAL_BYTES:
        raise ProfileError('Missing or oversized profile journal. Preserve the profile for manual inspection')
    journal = json.loads(path.read_bytes())
    keys = {'schemaVersion', 'game', 'vault', 'profile', 'phase', 'createdAt', 'legacyIdentity', 'freshIdentity', 'inventory'}
    if (not isinstance(journal, dict) or set(journal) != keys or journal['schemaVersion'] != 1
            or journal['game'] != str(paths.game) or journal['vault'] != str(paths.vault)
            or journal['profile'] != paths.name
            or journal['phase'] not in ('isolating', 'isolated', 'restoring', 'restored')
            or not isinstance(journal['inventory'], list) or not journal['inventory']
            or len(journal['inventory']) > MAX_ENTRIES):
        raise ProfileError('Invalid or mismatched profile journal')
    for key in ['legacyIdentity', 'freshIdentity']:
        value = journal[key]
        if value is None and key == 'freshIdentity':
            continue
        if not isinstance(value, dict) or set(value) != {'device', 'inode'} or any(type(n) is not int or n < 0 for n in value.values()):
            raise ProfileError('Invalid directory identity in profile journal')
    if journal['phase'] in ('isolated', 'restoring', 'restored') and journal['freshIdentity'] is None:
        raise ProfileError('Missing active directory identity in profile journal')
    seen = set()
    for entry in journal['inventory']:
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str) or entry['path'] in seen:
            raise ProfileError('Invalid inventory in profile journal')
        seen.add(entry['path'])
    return journal


def require_identity(path, expected):
    if not exists(path) or identity(path) != expected:
        raise ProfileError('Directory identity does not match the profile journal: ' + str(path))


def require_empty(path):
    directory(path)
    with os.scandir(path) as entries:
        if next(entries, None) is not None:
            raise ProfileError('Active plugins directory is not empty. Preserve or move its contents explicitly before restore/recovery')


def patcher_entries(paths):
    patchers = no_links(paths.game / 'BepInEx/patchers')
    if not exists(patchers):
        return []
    directory(patchers)
    with os.scandir(patchers) as entries:
        names = []
        for entry in entries:
            names.append(entry.name)
            if len(names) > MAX_ENTRIES:
                raise ProfileError('Patcher inventory exceeds entry limit')
    return sorted(names)


def complete_isolation(paths, journal):
    if patcher_entries(paths):
        raise ProfileError('BepInEx/patchers is not empty. Plugin isolation alone cannot disable those patchers')
    if exists(paths.saved):
        require_identity(paths.saved, journal['legacyIdentity'])
        verify_inventory(paths.saved, journal['inventory'])
    else:
        require_identity(paths.active, journal['legacyIdentity'])
        verify_inventory(paths.active, journal['inventory'])
        closed_game()
        rename_no_replace(paths.active, paths.saved)
        sync_directory(paths.active.parent)
        sync_directory(paths.profile)
    if exists(paths.active):
        require_empty(paths.active)
        if journal['freshIdentity'] is not None:
            require_identity(paths.active, journal['freshIdentity'])
    else:
        closed_game()
        paths.active.mkdir(mode=0o755)
        sync_directory(paths.active.parent)
    journal['freshIdentity'] = identity(paths.active)
    journal['phase'] = 'isolated'
    write_journal(paths, journal)
    return summary(paths, journal)


def complete_restore(paths, journal):
    if not exists(paths.saved):
        require_identity(paths.active, journal['legacyIdentity'])
        verify_inventory(paths.active, journal['inventory'])
    else:
        require_identity(paths.saved, journal['legacyIdentity'])
        verify_inventory(paths.saved, journal['inventory'])
        if exists(paths.active):
            require_empty(paths.active)
            require_identity(paths.active, journal['freshIdentity'])
            closed_game()
            os.rmdir(paths.active)
            sync_directory(paths.active.parent)
        closed_game()
        if exists(paths.active):
            raise ProfileError('Restore destination already exists. Preserve it and inspect before recovery')
        rename_no_replace(paths.saved, paths.active)
        sync_directory(paths.profile)
        sync_directory(paths.active.parent)
        verify_inventory(paths.active, journal['inventory'])
    journal['phase'] = 'restored'
    write_journal(paths, journal)
    return summary(paths, journal)


def summary(paths, journal):
    return dict(game=str(paths.game), vault=str(paths.vault), profile=paths.name,
                phase=journal['phase'], activePlugins=str(paths.active),
                savedPlugins=str(paths.saved), journal=str(paths.journal),
                legacyEntries=len(journal['inventory']),
                hashedFiles=sum('sha256' in entry for entry in journal['inventory']),
                symlinks=sum(entry['kind'] == 'symlink' for entry in journal['inventory']))


def operate(operation, game, vault, profile):
    paths = paths_for(game, vault, profile)
    if operation == 'inspect':
        journal = read_journal(paths) if exists(paths.journal) else None
        report = summary(paths, journal) if journal else dict(game=str(paths.game), vault=str(paths.vault), profile=profile,
                                                               phase='unmanaged', activePlugins=str(paths.active),
                                                               savedPlugins=str(paths.saved), journal=str(paths.journal))
        report['activeInventory'] = inventory(paths.active) if exists(paths.active) else []
        report['savedInventory'] = inventory(paths.saved) if exists(paths.saved) else []
        report['patcherEntries'] = patcher_entries(paths)
        report['runningProcesses'] = discovery.running_valheim()
        if journal:
            legacy = paths.saved if exists(paths.saved) else paths.active
            report['legacyInventoryMatches'] = inventory(legacy) == journal['inventory'] if exists(legacy) else False
        return report
    if operation not in ('isolate', 'restore', 'recover'):
        raise ProfileError('Unknown profile operation')
    closed_game()
    with game_lock(paths.game):
        # Recheck under the lock before any preparation or game-side mutation.
        paths = paths_for(game, vault, profile)
        closed_game()
        if operation == 'isolate':
            if exists(paths.profile):
                raise ProfileError('Profile destination already exists. Use inspect/recover or a new profile name')
            if patcher_entries(paths):
                raise ProfileError('BepInEx/patchers is not empty. Plugin isolation alone cannot disable those patchers')
            original = inventory(paths.active)
            if identity(paths.active)['device'] != (paths.game / 'BepInEx').stat().st_dev:
                raise ProfileError('Plugin root must be on the same filesystem as BepInEx')
            journal = dict(schemaVersion=1, game=str(paths.game), vault=str(paths.vault), profile=profile,
                           phase='isolating', createdAt=datetime.now(timezone.utc).isoformat(),
                           legacyIdentity=identity(paths.active), freshIdentity=None, inventory=original)
            # Create the durable journal before the first game directory rename.
            durable_directories(paths.vault)
            paths.profile.mkdir(mode=0o700)
            sync_directory(paths.vault)
            write_journal(paths, journal)
            return complete_isolation(paths, journal)
        journal = read_journal(paths)
        if operation == 'restore':
            if journal['phase'] != 'isolated':
                raise ProfileError('Profile is not isolated. Inspect its journal and use recover for an interrupted operation')
            require_identity(paths.saved, journal['legacyIdentity'])
            verify_inventory(paths.saved, journal['inventory'])
            require_empty(paths.active)
            require_identity(paths.active, journal['freshIdentity'])
            journal['phase'] = 'restoring'
            write_journal(paths, journal)
            return complete_restore(paths, journal)
        if journal['phase'] == 'isolating':
            return complete_isolation(paths, journal)
        if journal['phase'] == 'restoring':
            return complete_restore(paths, journal)
        raise ProfileError('No interrupted profile operation to recover')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['inspect', 'isolate', 'restore', 'recover'])
    parser.add_argument('--game', required=True, type=Path)
    parser.add_argument('--vault', required=True, type=Path, help='Local directory outside the game on the same filesystem')
    parser.add_argument('--profile', required=True, help='Unique local profile name')
    args = parser.parse_args(argv)
    try:
        report = operate(args.operation, args.game, args.vault, args.profile)
    except (ProfileError, discovery.DetectionError, OSError, ValueError) as error:
        print('mod-profile: ' + str(error), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
