"""Reviewed, journaled transactions limited to BepInEx/plugins/ValheimImpact."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid
import zipfile

from .discovery import DetectionError, running_valheim
from .package import CHUNK, MAX_FILES, Package, PackageError, no_links, records_valid, safe_path, sha256, strict_json

OWNED = Path('BepInEx/plugins/ValheimImpact')
MAX_STATE_BYTES = 16 * 1024**2
PROFILES = {
    'Compact': dict(residentMiB=384, inFlightMiB=32, concurrentRequests=1, startsPerFrame=1),
    'Balanced': dict(residentMiB=768, inFlightMiB=64, concurrentRequests=2, startsPerFrame=1),
    'High': dict(residentMiB=1536, inFlightMiB=128, concurrentRequests=2, startsPerFrame=1),
}


class InstallError(ValueError):
    pass


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def descriptor(path, data):
    return dict(path=path, size=len(data), sha256=hashlib.sha256(data).hexdigest())


def target_game(game):
    game = no_links(Path(game).expanduser())
    if not game.is_dir():
        raise InstallError('Select the Valheim game folder')
    platform = 'linux-x86_64' if (game / 'valheim.x86_64').is_file() else 'windows-x86_64' if (game / 'valheim.exe').is_file() else None
    if platform is None or not (game / 'valheim_Data/globalgamemanagers').is_file():
        raise InstallError('Folder lacks the Valheim executable and Unity game marker')
    for path in [game / ('valheim.x86_64' if platform == 'linux-x86_64' else 'valheim.exe'), game / 'valheim_Data/globalgamemanagers', game / 'BepInEx/core/BepInEx.dll', game / OWNED]:
        no_links(path)
    if not (game / 'BepInEx/core/BepInEx.dll').is_file():
        raise InstallError('BepInEx 5 is required. Install it separately before continuing')
    host = 'windows-x86_64' if sys.platform == 'win32' else 'linux-x86_64' if sys.platform.startswith('linux') else None
    if platform != host:
        raise InstallError('Game platform does not match this installer host')
    return game, platform


def closed_game():
    try:
        processes = running_valheim()
    except DetectionError as error:
        raise InstallError(str(error)) from error
    if processes:
        raise InstallError('Valheim is running. Close it normally before making changes: ' + ', '.join(processes))


def read_json(path):
    no_links(path)
    if path.stat().st_size > MAX_STATE_BYTES:
        raise InstallError('Installer state exceeds size limit')
    return strict_json(path.read_bytes())


def validate_receipt(receipt):
    if not isinstance(receipt, dict) or set(receipt) != {'schemaVersion', 'product', 'version', 'platform', 'profile', 'files', 'lastBackup'}:
        raise InstallError('Invalid ownership receipt')
    if receipt['schemaVersion'] != 1 or receipt['product'] != 'ValheimImpact' or receipt['profile'] not in PROFILES:
        raise InstallError('Invalid ownership receipt')
    records_valid(receipt['files'], internal=True)
    if receipt['lastBackup'] is not None and not re.fullmatch('[a-f0-9]{32}', str(receipt['lastBackup'])):
        raise InstallError('Invalid backup identifier')
    return receipt


def receipt_at(root):
    path = root / '.installer/receipt.json'
    if path.exists():
        return validate_receipt(read_json(path))
    state = root / '.installer'
    if state.exists() and any(state.iterdir()):
        # A pending initial install has no receipt yet, but has recoverable state.
        if not (state / 'pending.json').is_file() and not (state / 'preparing.json').is_file():
            raise InstallError('Unrecognized installer state. Preserve it and review manually')
    return None


def inspect_tree(root):
    """Reject link redirection and case aliases before touching any owned path."""
    no_links(root)
    if not root.exists():
        return
    if not root.is_dir():
        raise InstallError('Owned installation path is not a directory')
    spelling = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(folder) / name
            no_links(path)
            key = str(path.relative_to(root)).casefold()
            if key in spelling:
                raise InstallError('Case-colliding installed paths: ' + str(path))
            spelling[key] = str(path)
            if not path.is_dir() and not path.is_file():
                raise InstallError('Nonregular installed entry: ' + str(path))


def existing(root, name):
    safe_path(name, internal=True)
    path = no_links(root / name)
    parent = root
    for component in Path(name).parts:
        if parent.is_dir():
            for child in parent.iterdir():
                if child.name.casefold() == component.casefold() and child.name != component:
                    raise InstallError('Case alias of installed path: ' + str(child))
        parent = parent / component
    if not path.exists():
        return None
    if not path.is_file():
        raise InstallError('Expected file, found directory: ' + name)
    return dict(path=name, size=path.stat().st_size, sha256=sha256(path))


@dataclass(frozen=True)
class Change:
    action: str
    path: str
    before: dict | None
    after: dict | None


@dataclass
class Plan:
    game: Path
    operation: str
    profile: str
    package_path: Path | None
    package_digest: str | None
    version: str | None
    changes: list[Change]
    previous_receipt: dict | None
    desired_receipt: dict | None
    restore_id: str | None = None
    phase: str = 'commit'
    token: str = ''
    enable_replacement: bool = False
    sources: dict = field(default_factory=dict, repr=False)

    def summary(self):
        return dict(game=str(self.game), destination=str(self.game / OWNED), operation=self.operation,
                    profile=self.profile, version=self.version, experimental=True,
                    requestedGameReplacement=self.enable_replacement if self.operation in ('install', 'update') else None,
                    packageSha256=self.package_digest, restoreId=self.restore_id, phase=self.phase,
                    changes=[asdict(change) for change in self.changes],
                    receiptBefore=self.previous_receipt, receiptAfter=self.desired_receipt,
                    stateChanges=['Write ownership receipt and transaction journal', 'Keep a backup inside .installer/backups for local rollback'])


def payload_path(directory, logical, storage_version=2):
    safe_path(logical, internal=True)
    if storage_version == 1:
        return no_links(Path(directory) / logical)
    if storage_version != 2:
        raise InstallError('Unsupported installer payload storage')
    return no_links(Path(directory) / (hashlib.sha256(logical.encode('utf-8')).hexdigest() + '.payload'))


def state_dlls(root):
    state = root / '.installer'
    if not state.exists():
        return []
    return sorted(str(path.relative_to(root)) for path in state.rglob('*')
                  if path.is_file() and path.suffix.casefold() == '.dll')


def require_safe_state(root, *, recovering=False):
    if (root / '.installer/storage-migration.json').exists():
        raise InstallError('Interrupted state migration. Resume the reviewed migrate_installer_state.py operation first')
    if not recovering and state_dlls(root):
        raise InstallError('Legacy installer state contains plugin-discoverable DLLs. Close Valheim and use tools/migrate_installer_state.py before continuing')


def validate_snapshot(data):
    if not isinstance(data, dict) or set(data) not in ({'schemaVersion', 'beforeReceipt', 'changes'}, {'schemaVersion', 'beforeReceipt', 'changes', 'storageVersion'}) or data['schemaVersion'] != 1:
        raise InstallError('Invalid transaction snapshot')
    if type(data.get('storageVersion', 1)) is not int or data.get('storageVersion', 1) not in (1, 2):
        raise InstallError('Unknown installer payload storage version')
    if data['beforeReceipt'] is not None:
        validate_receipt(data['beforeReceipt'])
    if not isinstance(data['changes'], list) or len(data['changes']) > 2 * (MAX_FILES + 1):
        raise InstallError('Invalid backup changes')
    seen = set()
    for change in data['changes']:
        if set(change) != {'path', 'before', 'after'}:
            raise InstallError('Invalid backup change')
        safe_path(change['path'], internal=True)
        if change['path'].casefold() in seen:
            raise InstallError('Duplicate backup path')
        seen.add(change['path'].casefold())
        for kind in ('before', 'after'):
            if change[kind] is not None:
                records_valid([change[kind]], internal=True)
                if change[kind]['path'] != change['path']:
                    raise InstallError('Backup path mismatch')
    return data


def snapshot_at(root, identifier):
    if not re.fullmatch('[a-f0-9]{32}', str(identifier)):
        raise InstallError('Invalid backup identifier')
    data = validate_snapshot(read_json(root / '.installer/backups' / identifier / 'snapshot.json'))
    for change in data['changes']:
        if change['before'] is not None:
            source = payload_path(root / '.installer/backups' / identifier / 'files', change['path'], data.get('storageVersion', 1))
            if source.stat().st_size != change['before']['size'] or sha256(source) != change['before']['sha256']:
                raise InstallError('Backup integrity mismatch: ' + change['path'])
    return data


def preview(game, package_path=None, *, operation='install', profile='Balanced', enable_replacement=False):
    try:
        return _preview(game, package_path, operation=operation, profile=profile, enable_replacement=enable_replacement)
    except (PackageError, OSError, KeyError, TypeError) as error:
        raise InstallError(str(error)) from error


def _preview(game, package_path=None, *, operation, profile, enable_replacement):
    if type(enable_replacement) is not bool:
        raise InstallError('Replacement opt-in must be a boolean')
    if operation not in ('install', 'update', 'uninstall', 'rollback', 'recover') or profile not in PROFILES:
        raise InstallError('Unknown operation or profile')
    game, platform = target_game(game)
    root = game / OWNED
    inspect_tree(root)
    require_safe_state(root, recovering=operation == 'recover')
    previous = receipt_at(root)
    pending_path = root / '.installer/pending.json'
    preparation_path = root / '.installer/preparing.json'
    if preparation_path.exists() and not pending_path.exists() and operation != 'recover':
        raise InstallError('Interrupted preparation found. Preview and apply recover before continuing')
    if pending_path.exists() and operation != 'recover':
        raise InstallError('Interrupted transaction found. Preview and apply recover before continuing')
    owned = {r['path']: r for r in previous['files']} if previous else {}
    changes, sources, digest, restore_id, phase = [], {}, None, None, 'commit'
    desired = None
    version = previous['version'] if previous else None
    if operation in ('install', 'update'):
        if package_path is None:
            raise InstallError('Choose an experimental package ZIP first')
        package = Package.read(package_path)
        if package.manifest['platform'] != platform:
            raise InstallError('Package platform does not match the Valheim installation')
        package_path, digest, version = package.path, package.digest, package.manifest['version']
        if enable_replacement and not any(r['path'] == 'assets/bindings.json' for r in package.manifest['files']):
            raise InstallError('This package does not contain game material bindings')
        settings = encoded(dict(schemaVersion=1, profile=profile, experimental=True,
                                enableGameReplacement=enable_replacement, **PROFILES[profile]))
        wanted = {r['path']: r for r in package.manifest['files']}
        wanted['profile.json'] = descriptor('profile.json', settings)
        for incoming in wanted:
            for previous_name in owned:
                if incoming.startswith(previous_name + '/') or previous_name.startswith(incoming + '/'):
                    raise InstallError('File/directory shape changes require a separate reviewed uninstall: ' + previous_name + ' -> ' + incoming)
        sources = {name: ('zip', name) for name in wanted}
        sources['profile.json'] = ('bytes', settings)
        # Also inspect retired paths: a modified old owned file must not disappear on update.
        for name in sorted(wanted.keys() | owned.keys()):
            before = existing(root, name)
            if before is not None and name not in owned:
                raise InstallError('Refusing to overwrite unowned file: ' + name + '. Move it aside after reviewing it')
            if before is not None and before != owned.get(name):
                raise InstallError('Refusing to overwrite modified owned file: ' + name + '. Preserve and review it first')
            after = wanted.get(name)
            action = 'keep' if before == after else 'add' if before is None else 'remove' if after is None else 'replace'
            changes.append(Change(action, name, before, after))
        desired = dict(schemaVersion=1, product='ValheimImpact', version=version, platform=platform,
                       profile=profile, files=list(wanted.values()), lastBackup=None)
    elif operation == 'uninstall':
        if not previous or not owned:
            raise InstallError('No owned installation to uninstall')
        for name, expected in sorted(owned.items()):
            before = existing(root, name)
            changes.append(Change('remove' if before == expected else 'preserve' if before else 'keep', name, before, None))
        desired = dict(previous, files=[], version=None, lastBackup=None)
    else:
        if operation == 'recover':
            if pending_path.is_file():
                pending = read_json(pending_path)
                if not isinstance(pending, dict) or set(pending) != {'backup'}:
                    raise InstallError('Invalid recovery journal')
                restore_id = pending['backup']
            elif preparation_path.is_file():
                preparation = read_json(preparation_path)
                if not isinstance(preparation, dict) or set(preparation) != {'backup', 'beforeReceipt'}:
                    raise InstallError('Invalid preparation marker')
                restore_id, phase = preparation['backup'], 'prepare'
                if not re.fullmatch('[a-f0-9]{32}', str(restore_id)):
                    raise InstallError('Invalid preparation identifier')
                desired = preparation['beforeReceipt']
                if desired is not None:
                    validate_receipt(desired)
                if desired != previous:
                    raise InstallError('Ownership receipt changed during interrupted preparation')
            else:
                raise InstallError('No interrupted transaction to recover')
        else:
            restore_id = previous['lastBackup'] if previous else None
        if not restore_id:
            raise InstallError('No previous transaction is available for rollback')
        if phase == 'commit':
            snapshot = snapshot_at(root, restore_id)
            for saved in snapshot['changes']:
                name = saved['path']
                before = existing(root, name)
                allowed = [saved['after'], saved['before']] if operation == 'recover' else [saved['after']]
                if before not in allowed:
                    raise InstallError('Refusing to overwrite a file modified since the transaction: ' + name)
                after = saved['before']
                changes.append(Change('keep' if before == after else 'remove' if after is None else 'add' if before is None else 'replace', name, before, after))
                if after is not None:
                    sources[name] = ('file', payload_path(root / '.installer/backups' / restore_id / 'files', name, snapshot.get('storageVersion', 1)))
            desired = snapshot['beforeReceipt']
        version = desired['version'] if desired else None
        profile = desired['profile'] if desired else profile
    plan = Plan(game, operation, profile, Path(package_path) if package_path else None, digest, version,
                changes, previous, desired, restore_id, phase, sources=sources, enable_replacement=enable_replacement)
    planned_snapshot = dict(schemaVersion=1, storageVersion=2, beforeReceipt=previous, changes=[dict(path=c.path, before=c.before, after=c.after) for c in changes if c.action in ('add', 'remove', 'replace')])
    if len(encoded(planned_snapshot)) > MAX_STATE_BYTES or len(encoded(desired)) > MAX_STATE_BYTES:
        raise InstallError('Planned ownership or rollback state exceeds the supported capacity')
    plan.token = hashlib.sha256(encoded(plan.summary())).hexdigest()
    return plan


def atomic_json(path, value):
    no_links(path)
    data = encoded(value)
    if len(data) > MAX_STATE_BYTES:
        raise InstallError('Installer state exceeds size limit')
    temporary = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    with temporary.open('xb') as target:
        target.write(data)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)


def copy_checked(source, destination, expected):
    no_links(source)
    no_links(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    result, count = hashlib.sha256(), 0
    with Path(source).open('rb') as reader, destination.open('xb') as writer:
        while data := reader.read(CHUNK):
            count += len(data)
            if count > expected['size']:
                raise InstallError('Source exceeds reviewed size')
            result.update(data)
            writer.write(data)
        writer.flush()
        os.fsync(writer.fileno())
    if count != expected['size'] or result.hexdigest() != expected['sha256']:
        raise InstallError('Source changed after review: ' + expected['path'])


def restore_snapshot(root, identifier):
    closed_game()
    snapshot = snapshot_at(root, identifier)
    staging = root / '.installer/staging' / identifier
    inspect_tree(staging)
    if staging.exists():
        allowed = {payload_path(staging, change['path'], snapshot.get('storageVersion', 1)): change['after']
                   for change in snapshot['changes'] if change['after'] is not None}
        for source in staging.rglob('*'):
            if not source.is_file():
                continue
            expected = allowed.get(source)
            if expected is None or source.stat().st_size != expected['size'] or sha256(source) != expected['sha256']:
                raise InstallError('Unrecognized or modified interrupted staging payload: ' + str(source))
    # Validate all affected paths before starting recovery.
    for saved in snapshot['changes']:
        if existing(root, saved['path']) not in [saved['before'], saved['after']]:
            raise InstallError('File changed during transaction; manual review required: ' + saved['path'])
    for saved in reversed(snapshot['changes']):
        closed_game()
        target = root / saved['path']
        if saved['before'] is None:
            if target.exists():
                target.unlink()
        else:
            temporary = root / '.installer/staging' / ('restore-' + uuid.uuid4().hex + '.payload')
            copy_checked(payload_path(root / '.installer/backups' / identifier / 'files', saved['path'], snapshot.get('storageVersion', 1)), temporary, saved['before'])
            no_links(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary, target)
    receipt = root / '.installer/receipt.json'
    if snapshot['beforeReceipt'] is None:
        atomic_json(receipt, dict(schemaVersion=1, product='ValheimImpact', version=None,
                                 platform='windows-x86_64' if sys.platform == 'win32' else 'linux-x86_64',
                                 profile='Balanced', files=[], lastBackup=None))
    else:
        atomic_json(receipt, snapshot['beforeReceipt'])
    if staging.exists():
        closed_game()
        inspect_tree(staging)
        shutil.rmtree(staging)
    (root / '.installer/pending.json').unlink(missing_ok=True)
    (root / '.installer/preparing.json').unlink(missing_ok=True)


def apply(plan, *, reviewed_token, progress=None):
    """Apply precisely the previewed state. No force flag bypasses ownership conflicts."""
    if not reviewed_token or reviewed_token != plan.token:
        raise InstallError('A matching review token is required. Preview the changes first')
    progress = progress or (lambda value: None)
    closed_game()
    fresh = preview(plan.game, plan.package_path, operation=plan.operation, profile=plan.profile, enable_replacement=plan.enable_replacement)
    if fresh.token != reviewed_token:
        raise InstallError('Files or package changed after review. Preview again')
    plan = fresh
    root, state = plan.game / OWNED, plan.game / OWNED / '.installer'
    state.mkdir(parents=True, exist_ok=True)
    lock_path = state / 'lock'
    try:
        lock = lock_path.open('x')
    except FileExistsError as error:
        raise InstallError('Another installer may be active. If it crashed, close all installers and remove only .installer/lock before recovery') from error
    identifier, journal_written, completed = uuid.uuid4().hex, False, False
    backup = state / 'backups' / identifier
    staging = state / 'staging' / identifier
    try:
        lock.write(str(os.getpid()))
        lock.close()
        # Recheck under our lock before creating transaction files.
        inspect_tree(root)
        closed_game()
        if plan.operation == 'recover':
            if plan.phase == 'prepare':
                for directory in (state / 'backups' / plan.restore_id, state / 'staging' / plan.restore_id):
                    inspect_tree(directory)
                    if directory.exists():
                        shutil.rmtree(directory)
                (state / 'preparing.json').unlink()
            else:
                restore_snapshot(root, plan.restore_id)
            migration_required = bool(state_dlls(root))
            progress('Interrupted transaction recovered' + ('. Legacy state migration is required before launching Valheim' if migration_required else ''))
            return dict(ok=True, operation='recover', backup=plan.restore_id, migrationRequired=migration_required)
        atomic_json(state / 'preparing.json', dict(backup=identifier, beforeReceipt=plan.previous_receipt))
        backup.mkdir(parents=True)
        staging.mkdir(parents=True)
        mutations = [c for c in plan.changes if c.action in ('add', 'remove', 'replace')]
        snapshot = dict(schemaVersion=1, storageVersion=2, beforeReceipt=plan.previous_receipt,
                        changes=[dict(path=c.path, before=c.before, after=c.after) for c in mutations])
        for change in mutations:
            if change.before is not None:
                copy_checked(root / change.path, payload_path(backup / 'files', change.path), change.before)
        progress('Previous files backed up. Staging verified content')
        archive = zipfile.ZipFile(plan.package_path) if plan.package_path else None
        try:
            for change in mutations:
                if change.after is None:
                    continue
                dest = payload_path(staging, change.path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                kind, source = plan.sources[change.path]
                if kind == 'file':
                    copy_checked(source, dest, change.after)
                else:
                    digest, count = hashlib.sha256(), 0
                    with dest.open('xb') as writer:
                        if kind == 'bytes':
                            writer.write(source)
                            digest.update(source)
                            count = len(source)
                        else:
                            with archive.open('payload/' + source) as reader:
                                while data := reader.read(CHUNK):
                                    count += len(data)
                                    if count > change.after['size']:
                                        raise InstallError('Payload expanded beyond reviewed size')
                                    writer.write(data)
                                    digest.update(data)
                        writer.flush()
                        os.fsync(writer.fileno())
                    if count != change.after['size'] or digest.hexdigest() != change.after['sha256']:
                        raise InstallError('Payload changed after review')
        finally:
            if archive:
                archive.close()
        for change in mutations:
            if existing(root, change.path) != change.before:
                raise InstallError('File changed while staging: ' + change.path)
        closed_game()
        atomic_json(backup / 'snapshot.json', snapshot)
        atomic_json(state / 'pending.json', dict(backup=identifier))
        journal_written = True
        (state / 'preparing.json').unlink()
        for index, change in enumerate(mutations, 1):
            closed_game()
            dest = no_links(root / change.path)
            if existing(root, change.path) != change.before:
                raise InstallError('File changed during transaction: ' + change.path)
            if change.after is None:
                dest.unlink()
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.replace(payload_path(staging, change.path), dest)
            progress(f'{index}/{len(mutations)}: {change.action} {change.path}')
        closed_game()
        if plan.desired_receipt is None:
            # Keep an empty ownership receipt so rollback of a first install remains undoable.
            desired = dict(schemaVersion=1, product='ValheimImpact', version=None, platform=target_game(plan.game)[1], profile=plan.profile, files=[], lastBackup=identifier)
        else:
            desired = dict(plan.desired_receipt, lastBackup=identifier)
        atomic_json(state / 'receipt.json', desired)
        (state / 'pending.json').unlink()
        journal_written = False
        completed = True
        progress('Complete. Local rollback backup retained')
        return dict(ok=True, operation=plan.operation, backup=identifier, destination=str(root))
    except Exception as error:
        if journal_written:
            try:
                restore_snapshot(root, identifier)
            except Exception as recovery_error:
                raise InstallError(f'Changes stopped. Recovery journal retained. Close Valheim, then use recover. Cause: {error}. Recovery: {recovery_error}') from error
            raise InstallError('Transaction failed and was rolled back: ' + str(error)) from error
        raise InstallError('No installation files changed: ' + str(error)) from error
    finally:
        lock.close()
        lock_path.unlink(missing_ok=True)
        # Do not follow filesystem links during cleanup.
        try:
            inspect_tree(staging)
            if staging.exists():
                shutil.rmtree(staging)
            if not journal_written and not completed and plan.operation != 'recover':
                (state / 'preparing.json').unlink(missing_ok=True)
            if not journal_written and not completed and backup.exists():
                inspect_tree(backup)
                shutil.rmtree(backup)
            for directory in (state / 'staging', state / 'backups', state, root):
                try:
                    no_links(directory)
                    directory.rmdir()
                except OSError:
                    pass
        except (OSError, PackageError, InstallError):
            pass


def verify(game):
    try:
        game, _ = target_game(game)
        root = game / OWNED
        inspect_tree(root)
        require_safe_state(root)
        receipt = receipt_at(root)
        if (root / '.installer/pending.json').exists() or (root / '.installer/preparing.json').exists():
            return dict(ok=False, installed=bool(receipt), issues=['Interrupted transaction requires recovery'])
        if not receipt or not receipt['files']:
            return dict(ok=True, installed=False, issues=[])
        issues = []
        for entry in receipt['files']:
            current = existing(root, entry['path'])
            if current != entry:
                issues.append(('Missing: ' if current is None else 'Modified: ') + entry['path'])
        return dict(ok=not issues, installed=True, version=receipt['version'], profile=receipt['profile'], issues=issues)
    except (InstallError, PackageError, OSError, TypeError, KeyError) as error:
        return dict(ok=False, installed=False, issues=[str(error)])
