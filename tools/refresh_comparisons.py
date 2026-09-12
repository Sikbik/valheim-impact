#!/usr/bin/env python3
"""Refresh reviewed authored comparison thumbnails, preserving reference previews.

Output bytes are deterministic for the installed Pillow/WebP encoder. A different
encoder version requires an explicit refresh and review. Validation finishes in
an isolated directory before publication; ordinary write failures roll back all
changed owned files. Publication does not promise crash-atomic multi-file writes.
"""
import argparse
import copy
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile

from PIL import Image

try:
    from tools import check_comparisons as checks
except ModuleNotFoundError:
    import check_comparisons as checks

ROOT = Path(__file__).resolve().parents[1]
RECIPE = 'assets/status/comparisons.json'


def safe_file(root, relative):
    if (not isinstance(relative, str) or not relative or '\\' in relative or
            PurePosixPath(relative).is_absolute() or
            any(part in ('', '.', '..') for part in relative.split('/'))):
        raise ValueError('Unsafe relative path')
    path = Path(root)
    if path.is_symlink():
        raise ValueError('Linked root is forbidden')
    for part in relative.split('/'):
        path = path / part
        if path.is_symlink():
            raise ValueError('Input or parent is a symlink')
    if not path.is_file():
        raise ValueError('Required regular file is missing: ' + relative)
    return path


def thumbnail(path):
    with Image.open(path) as source:
        source.load()
        image = Image.frombytes('RGBA', source.size, source.convert('RGBA').tobytes())
    image.thumbnail((512, 512), Image.Resampling.LANCZOS)
    stream = io.BytesIO()
    image.save(stream, 'WEBP', quality=90, method=6, exact=True)
    return stream.getvalue()


def publish(base, files):
    """Replace owned files individually and restore their prior bytes on error."""
    previous = {name: (base / name).read_bytes() if (base / name).exists() else None for name in files}
    pending, changed = {}, []
    try:
        for name, data in files.items():
            with tempfile.NamedTemporaryFile(dir=base, suffix='.tmp', delete=False) as handle:
                pending[name] = Path(handle.name)
                handle.write(data)
        for name, temp in pending.items():
            os.replace(temp, base / name)
            changed.append(name)
    except Exception:
        for name in reversed(changed):
            if previous[name] is None:
                (base / name).unlink()
            else:
                with tempfile.NamedTemporaryFile(dir=base, suffix='.tmp', delete=False) as handle:
                    rollback = Path(handle.name)
                    handle.write(previous[name])
                try:
                    os.replace(rollback, base / name)
                finally:
                    rollback.unlink(missing_ok=True)
        raise
    finally:
        for temp in pending.values():
            temp.unlink(missing_ok=True)


def refresh(root=ROOT, check=False):
    root = Path(root).absolute()
    base = root / checks.COMPARISONS
    index = checks._read_json(safe_file(root, str(checks.COMPARISONS / 'index.json')))
    recipe = checks._read_json(safe_file(root, RECIPE))
    if set(recipe) != {'schema_version', 'previews'} or recipe['schema_version'] != 1 or not isinstance(recipe['previews'], list):
        raise ValueError('Invalid comparison recipe schema')
    catalog_path = safe_file(root, 'assets/status/catalog.json')
    catalog_hash = checks._hash(catalog_path)
    if index.get('catalog_sha256', catalog_hash) != catalog_hash:
        raise ValueError('Existing comparison catalog hash differs')
    result = copy.deepcopy(index)
    result['catalog_sha256'] = catalog_hash
    provenance = checks._read_json(safe_file(root, 'assets/provenance.json'))
    registered = {item['dest']: item for item in provenance['assets']}
    if len(registered) != len(provenance['assets']):
        raise ValueError('Duplicate authored provenance destination')
    sheets = {item['file'] for item in index['sheets']}
    owners = {item['file']: identifier for identifier, entry in index['assets'].items() for item in entry.get('after', [])}
    files, sources = {}, set()
    for row in recipe['previews']:
        if not isinstance(row, dict) or set(row) != {'asset_id', 'file', 'source', 'source_sha256', 'label', 'scope'}:
            raise ValueError('Invalid preview recipe fields')
        identifier, name, source = row['asset_id'], row['file'], row['source']
        if not isinstance(identifier, str) or identifier not in result['assets']:
            raise ValueError('Unmapped preview identity')
        if not isinstance(name, str) or not checks.WEBP_NAME.fullmatch(name) or not name.startswith('after-'):
            raise ValueError('Preview requires a safe after WebP basename')
        if name in sheets or name in files or (name in owners and owners[name] != identifier):
            raise ValueError('Duplicate or conflicting preview filename')
        if (base / name).exists() and name not in owners:
            raise ValueError('Refusing to overwrite an unowned file')
        if (base / name).is_symlink():
            raise ValueError('Output is a symlink')
        if not isinstance(source, str) or not source.startswith('assets/'):
            raise ValueError('Preview source must be under assets/')
        path = safe_file(root, source)
        checks._expect_hash(row['source_sha256'], 'source hash')
        record = registered.get(source)
        if (checks._hash(path) != row['source_sha256'] or not record or
                record.get('sha256') != row['source_sha256'] or record.get('original_game_pixels') is not False):
            raise ValueError('Preview source hash or authored provenance differs')
        files[name] = thumbnail(path)
        sources.add(source)
        after = {key: value for key, value in row.items() if key != 'asset_id'}
        after['sha256'] = hashlib.sha256(files[name]).hexdigest()
        entries = result['assets'][identifier].setdefault('after', [])
        entries[:] = [entry for entry in entries if entry['file'] != name] + [after]
    import json
    files['index.json'] = (json.dumps(result, separators=(',', ':'), ensure_ascii=False) + '\n').encode()
    # Validate reference sheets, old after entries and all generated files through
    # the same public checker without ever rewriting the live index first.
    with tempfile.TemporaryDirectory(prefix='comparison-review-') as directory:
        staged = Path(directory)
        staged_base = staged / checks.COMPARISONS
        staged_base.mkdir(parents=True)
        for path in base.iterdir():
            if path.suffix.lower() == '.webp':
                shutil.copyfile(safe_file(root, str(path.relative_to(root))), staged_base / path.name)
        for entry in result['assets'].values():
            sources.update(item['source'] for item in entry.get('after', []))
        for relative in sources | {'assets/status/catalog.json', 'assets/status/manifest.json', 'assets/provenance.json'}:
            source = safe_file(root, relative)
            destination = staged / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        for name, data in files.items():
            (staged_base / name).write_bytes(data)
        report = checks.validate(staged)
    if check:
        if any(not (base / name).is_file() or (base / name).read_bytes() != data for name, data in files.items()):
            raise ValueError('Comparison output differs; run refresh and review encoder output')
    else:
        publish(base, files)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--root', type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        report = refresh(args.root, args.check)
    except (ValueError, OSError) as error:
        print('comparison refresh failed: ' + str(error), file=sys.stderr)
        return 1
    print('comparison refresh passed: ' + str(report['after_files']) + ' authored previews')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
