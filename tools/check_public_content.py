"""Check publication privacy and artifact provenance using the standard library.

Default input is Git-tracked paths. Use --files PATH... or --files-from LIST.txt
to check a proposed publication list instead. The command never changes files.
JSON output contains only relative paths and categories, never matched values.
Exit status is 0 for a clean list, 1 for findings, or 2 for a command-line error.

Authored artifacts under assets/ need an exact file hash and explicit
original_game_pixels:false in assets/provenance.json. Models additionally need
original_geometry:false. These are checked declarations, not proof of authorship.
PNG text, EXIF and provenance blocks and WebP EXIF/XMP blocks must stay in private
source originals. Color profiles are preserved, with textual profile tags checked
for private markers. Image parsing checks container structure, not rendered pixels.

Optional --allow-email PATH=ADDRESS permits an exact public credit address only
in an author/credit/attribution file or a copyright/author notice in a legal file.
Pseudonyms without an address need no exception. Existing legal notices are never
rewritten or removed by this tool.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
MAX_FILES = 10000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_PROFILE_BYTES = 4 * 1024 * 1024
MODEL_SUFFIXES = {'.obj', '.fbx', '.blend', '.gltf', '.glb', '.dae', '.stl', '.ply'}
IMAGE_SUFFIXES = {'.png', '.webp'}
ARTIFACT_SUFFIXES = MODEL_SUFFIXES | IMAGE_SUFFIXES | {'.dds', '.ktx', '.ktx2'}
FORBIDDEN_SUFFIXES = {'.ress', '.dat', '.dll', '.pdb', '.exe', '.so', '.dylib', '.bundle', '.unity3d',
                      '.zip', '.7z', '.tar', '.gz', '.db', '.sqlite', '.log', '.key', '.pem', '.pfx',
                      '.p12', '.jks', '.keystore', '.pyc'}
PRIVATE_PARTS = {'local', '.local', 'build', 'dist', 'bin', 'obj', 'node_modules', '.venv', '__pycache__',
                 'downloads', 'extracted', 'cache', 'reference', 'reference-images', 'steamapps',
                 'bepinex', 'valheim_data', 'saves', 'credentials'}
PUBLIC_HIDDEN = {'.github', '.gitignore', '.gitattributes', '.editorconfig', '.nvmrc', '.oxfmtrc.json',
                 '.oxlintrc.json', '.prettierignore', '.prettierrc', '.prettierrc.json',
                 '.eslintrc', '.eslintrc.json'}
HOME_PATH = re.compile(r'(?:/(?:home|Users)/[^\s"\'<>`,;|]+|[A-Za-z]:\\+(?:Users|Documents and Settings)\\+[^\s"\'<>`,;|]+)')
EMAIL = re.compile(r'(?<![\w.+%-])[\w.+%-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}')
ANIMATION_PATH = re.compile(r'(?i)\bassets[/\\][^\s"\'<>`]*@[^/\\\s"\'<>`]+\.fbx\b')
CREDENTIAL = re.compile(
    r'gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|'
    r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|'
    r'(?i:\bBearer\s+[A-Za-z0-9._~+/-]{12,}|\b(?:api[_-]?key|access[_-]?token|password|secret|token)\b'
    r'["\']?\s*[:=]\s*["\']?[A-Za-z0-9_./+=-]{12,}(?=\s*(?:$|[,;#\r\n"\'])))', re.MULTILINE)
SYNTHETIC_TESTS = {'tests/test_tracker_evidence.py', 'tests/test_status_catalog.py'}
SYNTHETIC_EMAIL = 'person' + '@' + 'example.com'
SYNTHETIC_HOMES = {'/' + 'home/private' + ending for ending in
                   ('', '.json', '.png', '/image.png', '/source', '/debug-data', '/' + SYNTHETIC_EMAIL)}
REGISTRIES = {'assets/provenance.json': ('dest', ''),
              'status-site/public/art/provenance.json': ('file', 'status-site/public/')}


def _valid_path(name):
    return (isinstance(name, str) and bool(name) and not name.startswith('/') and '\\' not in name and
            not any(ord(c) < 32 or ord(c) == 127 for c in name) and
            all(part not in ('', '.', '..') for part in name.split('/')) and
            not re.match(r'^[A-Za-z]:', name))


def _display_path(name):
    if not _valid_path(name):
        return '<invalid-path>'
    return '<redacted-path>' if EMAIL.search(name) or CREDENTIAL.search(name) else name


def _forbidden(name):
    path = PurePosixPath(name)
    parts = [part.lower() for part in path.parts]
    if any(part in PRIVATE_PARTS for part in parts):
        return True
    if any(part.startswith('.') and part not in PUBLIC_HIDDEN for part in parts):
        return True
    if path.suffix.lower() in FORBIDDEN_SUFFIXES or parts[-1] == 'agents.md':
        return True
    if parts[-1] in ('local.json', 'credentials.json', 'secrets.json'):
        return True
    if parts[-1].startswith('local.') and '.example.' not in parts[-1]:
        return True
    if name in ('unity/Packages/manifest.json', 'unity/Packages/packages-lock.json'):
        return True
    if parts[0] == 'unity' and any(part in {'library', 'temp', 'logs', 'usersettings', 'memorycaptures',
                                          'builds', 'ownedinputs', 'bundles', 'generatedruntime',
                                          'probes', 'captures'} for part in parts[1:]):
        return True
    return path.suffix.lower() in MODEL_SUFFIXES | {'.dds', '.ktx', '.ktx2'} and parts[0] != 'assets'


def _notice_kind(name):
    basename = PurePosixPath(name).name.upper()
    stem = re.sub(r'\.(?:MD|TXT|RST)$', '', basename)
    if stem in ('AUTHORS', 'CREDITS', 'ATTRIBUTION'):
        return 'credit'
    if stem in ('LICENSE', 'LICENCE', 'COPYING', 'NOTICE', 'NOTICES', 'THIRD_PARTY_NOTICES', 'THIRD-PARTY-NOTICES'):
        return 'legal'
    return None


def _email_permitted(name, text, match, allowed):
    if name in SYNTHETIC_TESTS and match.group() == SYNTHETIC_EMAIL:
        return True
    if name == 'tests/test_status_catalog.py' and match.group() == SYNTHETIC_EMAIL + '.png':
        return True
    if name == 'tools/export_status.py' and match.group() == 'model' + '@' + 'animation.fbx':
        line_start = text.rfind('\n', 0, match.start()) + 1
        if text[line_start:match.start()].strip() == '# Unity uses' and text[match.end():].startswith(' names.'):
            return True
    if any(span.start() <= match.start() and span.end() >= match.end() for span in ANIMATION_PATH.finditer(text)):
        return True
    if (name, match.group()) not in allowed:
        return False
    if _notice_kind(name) == 'credit':
        return True
    line_number = text.count('\n', 0, match.start())
    context = '\n'.join(text.splitlines()[max(0, line_number - 2):line_number + 1])
    return bool(re.search(r'\b(?:copyright|authors?|maintainers?)\b|©', context, re.I))


def _profile_texts(profile):
    """Read textual ICC tag types; leave color-transform tables as binary data."""
    if (not 132 <= len(profile) <= MAX_PROFILE_BYTES or profile[36:40] != b'acsp' or
            struct.unpack_from('>I', profile)[0] != len(profile)):
        raise ValueError('Invalid profile')
    count = struct.unpack_from('>I', profile, 128)[0]
    if count > 1024 or 132 + count * 12 > len(profile):
        raise ValueError('Invalid profile tag table')
    result = []
    for index in range(count):
        offset, size = struct.unpack_from('>II', profile, 136 + index * 12)
        if offset < 132 + count * 12 or size < 8 or offset + size > len(profile):
            raise ValueError('Invalid profile tag range')
        tag = profile[offset:offset + size]
        if tag[:4] == b'text':
            result.append(tag[8:].decode('utf-8', errors='replace'))
        elif tag[:4] == b'desc':
            if len(tag) < 12:
                raise ValueError('Invalid profile description')
            length = struct.unpack_from('>I', tag, 8)[0]
            end = 12 + length
            if end > len(tag):
                raise ValueError('Invalid profile description range')
            result.append(tag[12:end].decode('utf-8', errors='replace'))
            if end + 8 <= len(tag):
                unicode_length = struct.unpack_from('>I', tag, end + 4)[0] * 2
                if end + 8 + unicode_length > len(tag):
                    raise ValueError('Invalid profile Unicode description')
                result.append(tag[end + 8:end + 8 + unicode_length].decode('utf-16-be', errors='replace'))
                result.append(tag[end + 8 + unicode_length:].decode('utf-8', errors='replace'))
        elif tag[:4] == b'mluc':
            if len(tag) < 16:
                raise ValueError('Invalid localized profile text')
            records, record_size = struct.unpack_from('>II', tag, 8)
            if records > 1024 or record_size < 12 or 16 + records * record_size > len(tag):
                raise ValueError('Invalid localized profile table')
            for record in range(records):
                length, start = struct.unpack_from('>II', tag, 20 + record * record_size)
                if length % 2 or start < 16 + records * record_size or start + length > len(tag):
                    raise ValueError('Invalid localized profile text range')
                result.append(tag[start:start + length].decode('utf-16-be', errors='replace'))
    return result


def _image_categories(data, suffix, profile_texts):
    """Inspect bounded container chunks without decoding image data or metadata."""
    found = set()
    if suffix == '.png':
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            return {'invalid_image'}
        offset, kinds = 8, []
        while offset + 12 <= len(data):
            size = struct.unpack_from('>I', data, offset)[0]
            end = offset + size + 12
            if end > len(data):
                return found | {'invalid_image'}
            kind = data[offset + 4:offset + 8]
            if zlib.crc32(data[offset + 4:end - 4]) & 0xffffffff != struct.unpack_from('>I', data, end - 4)[0]:
                return found | {'invalid_image'}
            if kind not in (b'IHDR', b'PLTE', b'IDAT', b'IEND', b'tRNS', b'sRGB', b'gAMA', b'iCCP',
                             b'cHRM', b'sBIT', b'bKGD', b'pHYs'):
                found.add('embedded_image_metadata')
            if kind == b'iCCP':
                payload = data[offset + 8:end - 4]
                separator = payload.find(b'\x00')
                try:
                    if not 1 <= separator <= 79 or separator + 1 >= len(payload) or payload[separator + 1] != 0:
                        raise ValueError('Invalid compressed profile')
                    decoder = zlib.decompressobj()
                    profile = decoder.decompress(payload[separator + 2:], MAX_PROFILE_BYTES + 1)
                    if len(profile) > MAX_PROFILE_BYTES or not decoder.eof or decoder.unused_data:
                        raise ValueError('Invalid or oversized profile')
                    profile_texts.append(payload[:separator].decode('latin-1'))
                    profile_texts.extend(_profile_texts(profile))
                except (ValueError, zlib.error):
                    found.add('invalid_image')
            if kind == b'IHDR' and (size != 13 or kinds):
                found.add('invalid_image')
            kinds.append(kind)
            offset = end
            if kind == b'IEND':
                if size != 0:
                    found.add('invalid_image')
                break
        if offset != len(data) or not kinds or kinds[0] != b'IHDR' or kinds[-1] != b'IEND' or b'IDAT' not in kinds:
            found.add('invalid_image')
    elif suffix == '.webp':
        if len(data) < 12 or data[:4] != b'RIFF' or data[8:12] != b'WEBP' or struct.unpack_from('<I', data, 4)[0] + 8 != len(data):
            return {'invalid_image'}
        offset, image_chunk = 12, False
        while offset + 8 <= len(data):
            kind = data[offset:offset + 4]
            size = struct.unpack_from('<I', data, offset + 4)[0]
            payload_start = offset + 8
            offset += 8 + size + (size & 1)
            if offset > len(data):
                return found | {'invalid_image'}
            if kind not in (b'VP8 ', b'VP8L', b'VP8X', b'ALPH', b'ANIM', b'ANMF', b'ICCP'):
                found.add('embedded_image_metadata')
            if kind == b'ICCP':
                try:
                    profile_texts.extend(_profile_texts(data[payload_start:payload_start + size]))
                except ValueError:
                    found.add('invalid_image')
            image_chunk |= kind in (b'VP8 ', b'VP8L', b'ANMF')
        if offset != len(data) or not image_chunk:
            found.add('invalid_image')
    return found


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate metadata key')
        result[key] = value
    return result


def scan(root, paths, allowed_emails=()):
    root = Path(root).absolute()
    paths = list(paths)
    findings, cached = set(), {}
    total_bytes = 0

    def add(name, category):
        findings.add((_display_path(name), category))

    def read(name):
        nonlocal total_bytes
        if name in cached:
            return cached[name]
        cached[name] = None
        if not _valid_path(name):
            add(name, 'invalid_path')
            return None
        path = root / name
        if any(part.is_symlink() for part in (path, *path.parents)):
            add(name, 'symlink')
            return None
        if _forbidden(name):
            add(name, 'forbidden_path')
            return None
        try:
            if not stat.S_ISREG(path.stat().st_mode):
                add(name, 'not_regular_file')
                return None
            if path.stat().st_size > MAX_FILE_BYTES:
                add(name, 'file_size_limit')
                return None
            with path.open('rb') as stream:
                data = stream.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES or total_bytes + len(data) > MAX_TOTAL_BYTES:
                add(name, 'file_size_limit')
                return None
            total_bytes += len(data)
            cached[name] = data
            return data
        except FileNotFoundError:
            add(name, 'missing_file')
        except OSError:
            add(name, 'read_error')
        return None

    allowed = set()
    for name, address in allowed_emails:
        if not _valid_path(name) or not _notice_kind(name) or not isinstance(address, str) or EMAIL.fullmatch(address) is None:
            add(name, 'invalid_email_policy')
        else:
            allowed.add((name, address))

    if len(paths) > MAX_FILES:
        add('<file-list>', 'file_count_limit')
        paths = []
    selected = sorted(set(paths))
    for name in selected:
        read(name)

    needed_registries = {name for name in selected if name in REGISTRIES}
    if any(name.startswith('assets/') and PurePosixPath(name).suffix.lower() in ARTIFACT_SUFFIXES for name in selected):
        needed_registries.add('assets/provenance.json')
    if any(name.startswith('status-site/public/art/') and PurePosixPath(name).suffix.lower() in IMAGE_SUFFIXES for name in selected):
        needed_registries.add('status-site/public/art/provenance.json')
    registered = set()
    for registry_name in sorted(needed_registries):
        raw = read(registry_name)
        if raw is None:
            add(registry_name, 'artifact_provenance')
            continue
        field, prefix = REGISTRIES[registry_name]
        try:
            document = json.loads(raw, object_pairs_hook=_strict_object)
            if not isinstance(document, dict) or document.get('schema_version') != 1 or not isinstance(document.get('assets'), list) or len(document['assets']) > MAX_FILES:
                raise ValueError('Invalid registry')
            seen = set()
            for record in document['assets']:
                if not isinstance(record, dict) or not isinstance(record.get(field), str):
                    raise ValueError('Invalid artifact record')
                relative = record[field]
                if not _valid_path(relative):
                    add(registry_name, 'artifact_provenance')
                    continue
                name = prefix + relative
                suffix = PurePosixPath(name).suffix.lower()
                if (name in seen or (not name.startswith('assets/') and not prefix) or
                        (prefix and not relative.startswith('art/')) or suffix not in ARTIFACT_SUFFIXES):
                    add(registry_name, 'artifact_provenance')
                    continue
                seen.add(name)
                registered.add(name)
                if record.get('original_game_pixels') is not False:
                    add(name, 'artifact_provenance')
                if suffix in MODEL_SUFFIXES and record.get('original_geometry') is not False:
                    add(name, 'original_geometry')
                content = read(name)
                if content is None:
                    add(name, 'artifact_missing')
                if (not isinstance(record.get('sha256'), str) or re.fullmatch('[a-f0-9]{64}', record['sha256']) is None or
                        content is not None and hashlib.sha256(content).hexdigest() != record['sha256']):
                    add(name, 'artifact_hash')
        except (ValueError, UnicodeDecodeError, TypeError):
            add(registry_name, 'artifact_provenance')
    for name in selected:
        if name.startswith('assets/') and PurePosixPath(name).suffix.lower() in ARTIFACT_SUFFIXES and name not in registered:
            add(name, 'artifact_provenance')
        if name.startswith('status-site/public/art/') and PurePosixPath(name).suffix.lower() in IMAGE_SUFFIXES and name not in registered:
            add(name, 'artifact_provenance')

    for name, data in cached.items():
        if data is None:
            continue
        suffix = PurePosixPath(name).suffix.lower()
        texts = []
        if suffix in IMAGE_SUFFIXES:
            # Pixel payloads can coincidentally contain address-shaped bytes.
            # Only the image container and permitted non-text chunks are public.
            for category in _image_categories(data, suffix, texts):
                add(name, category)
        else:
            # Include printable metadata in binary model files, retaining invalid
            # byte separators so unrelated byte runs do not become joined prose.
            texts.append(data.decode('utf-8', errors='replace'))
        for text in texts:
            for match in HOME_PATH.finditer(text):
                if name not in SYNTHETIC_TESTS or match.group() not in SYNTHETIC_HOMES:
                    add(name, 'private_home_path')
            if any(not _email_permitted(name, text, match, allowed) for match in EMAIL.finditer(text)):
                add(name, 'email_address')
            if CREDENTIAL.search(text):
                add(name, 'credential_marker')
        if data.startswith((b'UnityFS\0', b'UnityWeb\0', b'UnityRaw\0')):
            add(name, 'game_payload')
    return {'schema_version': 1, 'checked_files': len(selected),
            'findings': [{'path': name, 'category': category} for name, category in sorted(findings)]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('--files', nargs='+', metavar='PATH')
    inputs.add_argument('--files-from', type=Path, metavar='LIST')
    parser.add_argument('--allow-email', action='append', default=[], metavar='PATH=ADDRESS')
    args = parser.parse_args(argv)
    try:
        if args.files is not None:
            paths = args.files
        elif args.files_from is not None:
            with args.files_from.open(encoding='utf-8') as stream:
                paths = [line.rstrip('\r\n') for line in stream if line.strip()]
        else:
            output = subprocess.check_output(['git', '-C', str(args.root), 'ls-files', '-z'], stderr=subprocess.DEVNULL)
            paths = [path for path in output.decode('utf-8').split('\0') if path]
        allowances = []
        for value in args.allow_email:
            path, separator, address = value.partition('=')
            allowances.append((path, address if separator else ''))
        report = scan(args.root, paths, allowances)
    except (OSError, UnicodeDecodeError, subprocess.CalledProcessError):
        report = {'schema_version': 1, 'checked_files': 0,
                  'findings': [{'path': '<file-list>', 'category': 'file_list_error'}]}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report['findings'] else 0


if __name__ == '__main__':
    sys.exit(main())
