"""Strict, bounded package validation. Hashes provide integrity, not publisher identity."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import stat
import struct
import zipfile

MAX_FILES = 4096
MAX_FILE_BYTES = 2 * 1024**3
MAX_TOTAL_BYTES = 8 * 1024**3
MAX_MANIFEST_BYTES = 2 * 1024**2
MAX_CENTRAL_BYTES = 4 * 1024**2
CHUNK = 1024 * 1024


class PackageError(ValueError):
    pass


def safe_path(value, *, internal=False):
    if not isinstance(value, str) or len(value) > 220:
        raise PackageError('Invalid package path')
    parts = value.split('/')
    for part in parts:
        if (not part or part in ('.', '..') or part.endswith(('.', ' ')) or
                not re.fullmatch(r'[A-Za-z0-9_. -]+', part) or
                part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(10)), *('LPT'+str(i) for i in range(10))}):
            raise PackageError('Unsafe package path: ' + value)
    if any(p.lower().endswith('.ress') for p in parts):
        raise PackageError('Original resource payloads are forbidden: ' + value)
    if parts[0].casefold() == '.installer' or (not internal and value.casefold() == 'profile.json'):
        raise PackageError('Reserved installer path: ' + value)
    return value


def no_links(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise PackageError('Symlink path is forbidden: ' + str(part))
        if hasattr(part, 'is_junction') and part.is_junction():
            raise PackageError('Junction path is forbidden: ' + str(part))
    return path


def sha256(path):
    no_links(path)
    if not Path(path).is_file():
        raise PackageError('Expected a regular file: ' + str(path))
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(CHUNK):
            result.update(chunk)
    return result.hexdigest()


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PackageError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs)
    except (ValueError, UnicodeError) as error:
        raise PackageError('Invalid JSON: ' + str(error)) from error


def records_valid(records, *, internal=False):
    if not isinstance(records, list) or len(records) > MAX_FILES + (1 if internal else 0):
        raise PackageError('Package file count exceeds limit')
    seen, prefixes, total = set(), set(), 0
    for entry in records:
        if not isinstance(entry, dict) or set(entry) != {'path', 'size', 'sha256'}:
            raise PackageError('Invalid file descriptor')
        name = safe_path(entry['path'], internal=internal)
        key = name.casefold()
        if key in seen:
            raise PackageError('Duplicate or case-colliding path: ' + name)
        seen.add(key)
        parts = key.split('/')
        prefixes.update('/'.join(parts[:i]) for i in range(1, len(parts)))
        if type(entry['size']) is not int or not 0 <= entry['size'] <= MAX_FILE_BYTES:
            raise PackageError('File size exceeds limit: ' + name)
        if not isinstance(entry['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', entry['sha256']):
            raise PackageError('Invalid SHA256: ' + name)
        total += entry['size']
    if prefixes & seen:
        raise PackageError('Package path is both a file and a directory')
    # Enforce matching spelling of directory ancestors even on a case-sensitive host.
    spelling = {}
    for entry in records:
        parts = entry['path'].split('/')
        for i in range(1, len(parts) + 1):
            p = '/'.join(parts[:i])
            if p.casefold() in spelling and spelling[p.casefold()] != p:
                raise PackageError('Case-colliding directory: ' + p)
            spelling[p.casefold()] = p
    if total > MAX_TOTAL_BYTES + (4096 if internal else 0):
        raise PackageError('Package expanded size exceeds limit')


def preflight_zip(path):
    """Bound central-directory count and bytes before ZipFile allocates ZipInfo objects.

    Supports ordinary ZIP and fixed-size single-disk ZIP64 end records. Rejects
    split archives, extensible ZIP64 end records and unexplained trailing bytes.
    """
    size = path.stat().st_size
    if size > MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES:
        raise PackageError('Archive size exceeds limit')
    with path.open('rb') as reader:
        reader.seek(max(0, size - 65557))
        tail = reader.read(65557)
        position = tail.rfind(b'PK\x05\x06')
        if position < 0 or len(tail) - position < 22:
            raise PackageError('Missing ZIP end record')
        _, disk, central_disk, disk_count, count, central_size, offset, comment = struct.unpack_from('<4s4H2IH', tail, position)
        end = size - len(tail) + position
        if position + 22 + comment != len(tail) or disk or central_disk or disk_count != count:
            raise PackageError('Unsupported split archive or trailing ZIP data')
        boundary = end
        reader.seek(max(0, end - 20))
        locator = reader.read(20)
        if locator[:4] == b'PK\x06\x07':
            _, disk, zip64_offset, disks = struct.unpack('<4sIQI', locator)
            if disk or disks != 1 or zip64_offset + 56 != end - 20:
                raise PackageError('Unsupported ZIP64 end bounds')
            reader.seek(zip64_offset)
            raw = reader.read(56)
            if len(raw) != 56:
                raise PackageError('Truncated ZIP64 end record')
            signature, record_size, _, _, disk, central_disk, disk_count, count, central_size, offset = struct.unpack('<4sQHHIIQQQQ', raw)
            if signature != b'PK\x06\x06' or record_size != 44 or disk or central_disk or disk_count != count:
                raise PackageError('Unsupported ZIP64 end record')
            boundary = zip64_offset
        elif count == 65535 or offset == 0xffffffff or central_size == 0xffffffff:
            raise PackageError('Missing required ZIP64 locator')
        if count > MAX_FILES + 1 or central_size > MAX_CENTRAL_BYTES:
            raise PackageError('Archive central directory exceeds count or byte limit')
        if offset + central_size != boundary or offset < 0:
            raise PackageError('Invalid archive central-directory bounds')
        reader.seek(offset)
        observed = 0
        while reader.tell() < boundary:
            header = reader.read(46)
            if len(header) != 46 or header[:4] != b'PK\x01\x02':
                raise PackageError('Invalid central-directory entry')
            name, extra, comment, disk_start = struct.unpack_from('<4H', header, 28)
            if disk_start or reader.tell() + name + extra + comment > boundary:
                raise PackageError('Invalid central-directory entry bounds')
            observed += 1
            if observed > MAX_FILES + 1:
                raise PackageError('Archive file count exceeds limit')
            reader.seek(name + extra + comment, 1)
        if observed != count:
            raise PackageError('Central-directory count mismatch')


@dataclass(frozen=True)
class Package:
    path: Path
    manifest: dict
    digest: str

    @classmethod
    def read(cls, path):
        path = no_links(path)
        try:
            preflight_zip(path)
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                if len(infos) > MAX_FILES + 1:
                    raise PackageError('Archive file count exceeds limit')
                names = set()
                for info in infos:
                    key = info.filename.casefold()
                    mode = info.external_attr >> 16
                    if key in names or info.is_dir() or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                        raise PackageError('Duplicate, directory or symlink archive entry: ' + info.filename)
                    if info.flag_bits & 1 or info.file_size > MAX_FILE_BYTES:
                        raise PackageError('Encrypted or oversized entry')
                    names.add(key)
                info = archive.getinfo('manifest.json')
                if info.file_size > MAX_MANIFEST_BYTES:
                    raise PackageError('Manifest exceeds limit')
                manifest = strict_json(archive.read(info))
                required = {'schemaVersion', 'product', 'version', 'platform', 'experimental', 'files'}
                if not isinstance(manifest, dict) or set(manifest) != required:
                    raise PackageError('Unexpected manifest fields')
                if manifest['schemaVersion'] != 1 or manifest['product'] != 'ValheimImpact' or manifest['experimental'] is not True:
                    raise PackageError('Expected experimental ValheimImpact schema 1 package')
                if not isinstance(manifest['version'], str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?', manifest['version']):
                    raise PackageError('Invalid package version')
                if manifest['platform'] not in ('linux-x86_64', 'windows-x86_64'):
                    raise PackageError('Unsupported package platform')
                records_valid(manifest['files'])
                if not manifest['files']:
                    raise PackageError('Package has no payload')
                expected = {'manifest.json'} | {'payload/' + r['path'] for r in manifest['files']}
                if {i.filename for i in infos} != expected:
                    raise PackageError('Unexplained or missing archive entries')
                for entry in manifest['files']:
                    info = archive.getinfo('payload/' + entry['path'])
                    if info.file_size != entry['size']:
                        raise PackageError('Declared size mismatch: ' + entry['path'])
                    result, count = hashlib.sha256(), 0
                    with archive.open(info) as source:
                        while data := source.read(CHUNK):
                            count += len(data)
                            if count > entry['size']:
                                raise PackageError('Expanded file exceeds declared size')
                            result.update(data)
                    if count != entry['size'] or result.hexdigest() != entry['sha256']:
                        raise PackageError('SHA256 integrity mismatch: ' + entry['path'])
            return cls(path, manifest, sha256(path))
        except (OSError, KeyError, struct.error, zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
            raise PackageError('Cannot verify package: ' + str(error)) from error
