"""Reviewed, resumable migration of legacy installer payload filenames.

No game content is changed. The caller must keep Valheim closed. Moving each
verified payload uses an exclusive hard-link followed by source removal, so a
collision cannot overwrite anything and a crash retains at least one valid name.
"""
import hashlib
import os
from pathlib import Path
import re

from . import core
from .package import PackageError, no_links, sha256

JOURNAL = 'storage-migration.json'
MAX_BACKUPS = 256
MAX_PAYLOADS = 32768


def _digest(value):
    return hashlib.sha256(core.encoded(value)).hexdigest()


def _snapshot_after(item):
    return dict(item['snapshot'], storageVersion=2)


def _context(game):
    game, _ = core.target_game(game)
    root = game / core.OWNED
    core.inspect_tree(root)
    state = root / '.installer'
    if any((state / name).exists() for name in ('pending.json', 'preparing.json')):
        raise core.InstallError('Recover the interrupted installer transaction before migrating state; keep Valheim closed until both finish')
    return game, root, state


def _validate_plan(plan, game):
    if not isinstance(plan, dict) or set(plan) != {'schemaVersion', 'game', 'receiptSha256', 'backups'} or plan['schemaVersion'] != 1 or plan['game'] != str(game):
        raise core.InstallError('Invalid state migration plan')
    if plan['receiptSha256'] is not None and not re.fullmatch('[a-f0-9]{64}', str(plan['receiptSha256'])):
        raise core.InstallError('Invalid migration receipt digest')
    if not isinstance(plan['backups'], list) or len(plan['backups']) > MAX_BACKUPS:
        raise core.InstallError('Migration backup count exceeds limit')
    seen, count = set(), 0
    for item in plan['backups']:
        if not isinstance(item, dict) or set(item) != {'id', 'snapshotSha256', 'snapshot'} or not re.fullmatch('[a-f0-9]{32}', str(item['id'])) or item['id'] in seen:
            raise core.InstallError('Invalid or duplicate migration backup')
        if not re.fullmatch('[a-f0-9]{64}', str(item['snapshotSha256'])):
            raise core.InstallError('Invalid migration snapshot digest')
        core.validate_snapshot(item['snapshot'])
        seen.add(item['id'])
        count += sum(change['before'] is not None for change in item['snapshot']['changes'])
    if count > MAX_PAYLOADS or len(core.encoded(plan)) > core.MAX_STATE_BYTES:
        raise core.InstallError('Migration state exceeds supported capacity')


def _checked(path, expected):
    no_links(path)
    if not path.is_file() or path.stat().st_size != expected['size'] or sha256(path) != expected['sha256']:
        raise core.InstallError('Migration payload is missing or modified: ' + str(path))


def _metadata_prefix(temporary, desired):
    no_links(temporary)
    if not temporary.is_file() or temporary.stat().st_size > len(desired):
        raise core.InstallError('Migration metadata temporary file changed')
    with temporary.open('rb') as reader:
        prefix = reader.read(len(desired) + 1)
    if not desired.startswith(prefix):
        raise core.InstallError('Migration metadata temporary file changed')
    return len(prefix)


def _validate_state(plan, root, *, resuming, own_lock=False):
    state = root / '.installer'
    core.inspect_tree(root)
    allowed = set()
    receipt = state / 'receipt.json'
    actual_receipt = sha256(receipt) if receipt.is_file() else None
    if actual_receipt != plan['receiptSha256']:
        raise core.InstallError('Ownership receipt changed after migration review')
    if receipt.is_file():
        core.validate_receipt(core.read_json(receipt))
        allowed.add(receipt)
    if (state / 'lock').exists():
        if not own_lock:
            raise core.InstallError('Another installer may be active; remove only a known stale lock after all installers exit')
        allowed.add(state / 'lock')
    if resuming:
        allowed.add(state / JOURNAL)
    backup_root = state / 'backups'
    actual_ids = {path.name for path in backup_root.iterdir()} if backup_root.exists() else set()
    if actual_ids != {item['id'] for item in plan['backups']}:
        raise core.InstallError('Backup inventory changed after migration review')
    for item in plan['backups']:
        folder = backup_root / item['id']
        snapshot = folder / 'snapshot.json'
        old = item['snapshot'].get('storageVersion', 1) == 1
        after_hash = _digest(_snapshot_after(item)) if old else item['snapshotSha256']
        current_hash = sha256(snapshot)
        if current_hash not in ({item['snapshotSha256'], after_hash} if resuming else {item['snapshotSha256']}):
            raise core.InstallError('Snapshot changed after migration review: ' + item['id'])
        allowed.add(snapshot)
        temporary = folder / '.snapshot-migration.payload'
        if temporary.exists():
            if not resuming or not old:
                raise core.InstallError('Unrecognized migration metadata temporary file')
            desired = core.encoded(_snapshot_after(item))
            prefix_length = _metadata_prefix(temporary, desired)
            if prefix_length != len(desired) and current_hash != item['snapshotSha256']:
                raise core.InstallError('Partial migration metadata temporary file has no original snapshot')
            allowed.add(temporary)
        for change in item['snapshot']['changes']:
            expected = change['before']
            if expected is None:
                continue
            source = core.payload_path(folder / 'files', change['path'], 1 if old else 2)
            destination = core.payload_path(folder / 'files', change['path'])
            if not old:
                _checked(destination, expected); allowed.add(destination); continue
            old_exists, new_exists = source.exists(), destination.exists()
            if not resuming and new_exists:
                raise core.InstallError('Migration destination collision: ' + str(destination))
            if not old_exists and not new_exists:
                raise core.InstallError('Legacy backup payload is missing: ' + change['path'])
            if not resuming and not old_exists:
                raise core.InstallError('Legacy source is missing before migration')
            if old_exists:
                _checked(source, expected); allowed.add(source)
            if new_exists:
                _checked(destination, expected); allowed.add(destination)
            if old_exists and new_exists and not os.path.samefile(source, destination):
                raise core.InstallError('Ambiguous migration collision is not the acknowledged exclusive link')
            if current_hash == after_hash and after_hash != item['snapshotSha256'] and (old_exists or not new_exists):
                raise core.InstallError('Encoded snapshot has inconsistent payload storage')
    actual = {path for path in state.rglob('*') if path.is_file()} if state.exists() else set()
    if actual != allowed:
        raise core.InstallError('Unrecognized installer-state files; preserve and review them before migration: ' + ', '.join(str(path.relative_to(state)) for path in sorted(actual - allowed)[:8]))


def preview(game):
    try:
        game, root, state = _context(game)
        journal = state / JOURNAL
        resuming = journal.exists()
        if resuming:
            saved = core.read_json(journal)
            if not isinstance(saved, dict) or set(saved) != {'schemaVersion', 'plan', 'reviewToken'} or saved['schemaVersion'] != 1:
                raise core.InstallError('Invalid storage migration journal')
            plan = saved['plan']
            _validate_plan(plan, game)
            if saved['reviewToken'] != _digest(plan):
                raise core.InstallError('Storage migration journal review token mismatch')
        else:
            core.receipt_at(root)
            receipt = state / 'receipt.json'
            plan = dict(schemaVersion=1, game=str(game), receiptSha256=sha256(receipt) if receipt.is_file() else None, backups=[])
            directory = state / 'backups'
            if directory.exists():
                folders = sorted(directory.iterdir())
                if len(folders) > MAX_BACKUPS:
                    raise core.InstallError('Migration backup count exceeds limit')
                for folder in folders:
                    if not folder.is_dir() or not re.fullmatch('[a-f0-9]{32}', folder.name):
                        raise core.InstallError('Unrecognized backup directory')
                    snapshot = core.snapshot_at(root, folder.name)
                    plan['backups'].append(dict(id=folder.name, snapshotSha256=sha256(folder / 'snapshot.json'), snapshot=snapshot))
                    # Reject the cumulative plan before reading another backup.
                    _validate_plan(plan, game)
            _validate_plan(plan, game)
        _validate_state(plan, root, resuming=resuming)
        return dict(plan=plan, reviewToken=_digest(plan), resuming=resuming,
                    legacyBackups=sum(item['snapshot'].get('storageVersion', 1) == 1 for item in plan['backups']),
                    scope='Rename verified private backup payloads and update snapshot storage metadata only. No active game file or save changes.')
    except (PackageError, OSError, KeyError, TypeError) as error:
        raise core.InstallError(str(error)) from error


def _sync_directory(directory):
    if os.name == 'posix':
        fd = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def apply(review, *, reviewed_token):
    if not isinstance(review, dict) or reviewed_token != review.get('reviewToken') or reviewed_token != _digest(review.get('plan')):
        raise core.InstallError('A matching state migration review token is required')
    core.closed_game()
    fresh = preview(review['plan']['game'])
    if fresh['reviewToken'] != reviewed_token:
        raise core.InstallError('Installer state changed after migration review')
    if fresh['legacyBackups'] == 0:
        return dict(ok=True, migratedBackups=0, discoverablePrivateDlls=0)
    plan = fresh['plan']; game, root, state = _context(plan['game'])
    lock = state / 'lock'
    try:
        with lock.open('x') as writer:
            writer.write(str(os.getpid())); writer.flush(); os.fsync(writer.fileno())
    except FileExistsError as error:
        raise core.InstallError('Another installer may be active') from error
    try:
        _validate_state(plan, root, resuming=fresh['resuming'], own_lock=True)
        core.closed_game()
        if not fresh['resuming']:
            core.atomic_json(state / JOURNAL, dict(schemaVersion=1, plan=plan, reviewToken=reviewed_token))
            _sync_directory(state)
        for item in plan['backups']:
            if item['snapshot'].get('storageVersion', 1) == 2:
                continue
            folder = state / 'backups' / item['id']
            for change in item['snapshot']['changes']:
                expected = change['before']
                if expected is None:
                    continue
                source = core.payload_path(folder / 'files', change['path'], 1)
                destination = core.payload_path(folder / 'files', change['path'])
                core.closed_game()
                if source.exists():
                    _checked(source, expected)
                    if not destination.exists():
                        # link() creates the destination atomically and refuses an
                        # existing name. Journal recovery accepts a double name only
                        # when both identify this same verified filesystem object.
                        os.link(source, destination)
                        _sync_directory(destination.parent)
                    if not os.path.samefile(source, destination):
                        raise core.InstallError('Migration destination collision')
                    _checked(destination, expected)
                    core.closed_game()
                    source.unlink(); _sync_directory(source.parent)
                else:
                    _checked(destination, expected)
            core.closed_game()
            desired = core.encoded(_snapshot_after(item))
            snapshot = folder / 'snapshot.json'
            current = sha256(snapshot)
            if current not in (item['snapshotSha256'], hashlib.sha256(desired).hexdigest()):
                raise core.InstallError('Snapshot changed during migration')
            temporary = folder / '.snapshot-migration.payload'
            if current == item['snapshotSha256']:
                exists = temporary.exists()
                prefix_length = _metadata_prefix(temporary, desired) if exists else 0
                # The durable journal reserves this previously absent name. An
                # interrupted write may contain only a verified prefix, including
                # zero bytes; append its missing suffix without truncating it.
                with temporary.open('ab' if exists else 'xb') as writer:
                    writer.write(desired[prefix_length:]); writer.flush(); os.fsync(writer.fileno())
                if _metadata_prefix(temporary, desired) != len(desired):
                    raise core.InstallError('Migration metadata temporary file is incomplete')
                os.replace(temporary, snapshot); _sync_directory(folder)
            elif temporary.exists():
                temporary.unlink(); _sync_directory(folder)
        _validate_state(plan, root, resuming=True, own_lock=True)
        if core.state_dlls(root):
            raise core.InstallError('Discoverable installer-state DLLs remain; migration cannot complete')
        core.closed_game()
        (state / JOURNAL).unlink(); _sync_directory(state)
        return dict(ok=True, migratedBackups=fresh['legacyBackups'], discoverablePrivateDlls=0)
    except (PackageError, OSError, KeyError, TypeError) as error:
        raise core.InstallError('State migration stopped; retain its journal and resume after review: ' + str(error)) from error
    finally:
        lock.unlink(missing_ok=True)
