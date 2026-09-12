#!/usr/bin/env python3
"""Validate the bounded public before and after comparison publication."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from PIL import Image

try:
    from check_public_content import _image_categories
except ImportError:
    from tools.check_public_content import _image_categories


ROOT = Path(__file__).resolve().parents[1]
COMPARISONS = Path('status-site/public/comparisons')
MAX_SHEET_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_SHEETS = 256
MAX_AFTER_BYTES = 256 * 1024
SHA256 = re.compile(r'^[0-9a-f]{64}$')
WEBP_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*\.webp$')
PRIVATE_PATH = re.compile(r'(?:/(?:home|Users)/[^\s]+|[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\s]+)')


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _constant(_value):
    raise ValueError('Non-finite JSON number')


def _read_json(path):
    try:
        return json.loads(path.read_bytes(), object_pairs_hook=_object, parse_constant=_constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid JSON file: ' + path.name) from error


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _webp(base, name, role):
    if not isinstance(name, str) or not WEBP_NAME.fullmatch(name):
        raise ValueError(role + ' must use a safe WebP basename')
    path = base / name
    if path.is_symlink():
        raise ValueError(role + ' must not be a symlink: ' + name)
    if not path.is_file():
        raise ValueError(role + ' file is missing: ' + name)
    return path


def _clean_webp(path):
    data = path.read_bytes()
    categories = _image_categories(data, '.webp', [])
    if categories:
        raise ValueError('Invalid or metadata-bearing WebP: ' + path.name)
    try:
        with Image.open(path) as image:
            image.load()
            if image.format != 'WEBP':
                raise ValueError
            return image.size
    except Exception as error:
        raise ValueError('Invalid WebP: ' + path.name) from error


def _expect_hash(value, label):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError(label + ' must be a lowercase SHA-256')


def _authored_ids(status):
    result = set()
    for evidence in status.get('evidence', []):
        for target in evidence.get('targets', []):
            if 'authored' in target.get('stages', []):
                result.add(target.get('asset_id'))
    for asset in status.get('assets', []):
        stages = asset.get('stages', {})
        if stages.get('authored') is True:
            result.add(asset.get('id'))
    return result


def _reject_private_strings(value):
    if isinstance(value, str) and PRIVATE_PATH.search(value):
        raise ValueError('Comparison manifest contains a private path')
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_private_strings(key)
            _reject_private_strings(item)
    elif isinstance(value, list):
        for item in value:
            _reject_private_strings(item)


def validate(root=ROOT):
    root = Path(root)
    base = root / COMPARISONS
    index_path = base / 'index.json'
    catalog_path = root / 'assets/status/catalog.json'
    status_path = root / 'assets/status/manifest.json'
    provenance_path = root / 'assets/provenance.json'
    for path in (index_path, catalog_path, status_path, provenance_path):
        if path.is_symlink() or not path.is_file():
            raise ValueError('Required input is missing or a symlink: ' + path.name)
    index = _read_json(index_path)
    catalog = _read_json(catalog_path)
    status = _read_json(status_path)
    provenance = _read_json(provenance_path)
    _reject_private_strings(index)
    if index.get('schema_version') != 1 or index.get('tile_size') != 192 or index.get('columns') != 8:
        raise ValueError('Comparison schema, tile size, or column count is invalid')
    expected_catalog_hash = _hash(catalog_path)
    if index.get('catalog_sha256') != expected_catalog_hash:
        raise ValueError('Comparison catalog hash does not match catalog bytes')
    catalog_assets = catalog.get('assets')
    records = index.get('assets')
    if not isinstance(catalog_assets, list) or not isinstance(records, dict):
        raise ValueError('Catalog assets and comparison assets have invalid types')
    kinds = {}
    for asset in catalog_assets:
        identifier, kind = asset.get('id'), asset.get('kind')
        if not _valid_identifier(identifier) or identifier in kinds or kind not in ('texture', 'mesh'):
            raise ValueError('Catalog identity or kind is invalid')
        kinds[identifier] = kind
    if set(records) != set(kinds):
        raise ValueError('Comparison identity set must exactly equal the catalog identity set')

    sheets = index.get('sheets')
    if not isinstance(sheets, list) or not 1 <= len(sheets) <= MAX_SHEETS:
        raise ValueError('Sheet count is invalid')
    sheet_map, indexed_files, total_bytes = {}, set(), 0
    for sheet in sheets:
        if not isinstance(sheet, dict):
            raise ValueError('Sheet record is invalid')
        name = sheet.get('file')
        path = _webp(base, name, 'sheet')
        if name in indexed_files:
            raise ValueError('Duplicate indexed WebP: ' + name)
        indexed_files.add(name)
        size = path.stat().st_size
        if size > MAX_SHEET_BYTES:
            raise ValueError('Sheet exceeds byte limit: ' + name)
        total_bytes += size
        _expect_hash(sheet.get('sha256'), 'sheet hash')
        if _hash(path) != sheet['sha256']:
            raise ValueError('Sheet hash mismatch: ' + name)
        decoded = _clean_webp(path)
        if (sheet.get('width'), sheet.get('height')) != (1536, 1536) or decoded != (1536, 1536):
            raise ValueError('Sheet dimensions must be exactly 1536 by 1536: ' + name)
        if (sheet.get('kind') != 'reference-preview' or sheet.get('original_game_pixels') is not True or
                sheet.get('license') != 'Game reference, excluded from project artwork license'):
            raise ValueError('Sheet reference classification or license is invalid: ' + name)
        sheet_map[name] = sheet

    provenance_map = {}
    for item in provenance.get('assets', []):
        dest = item.get('dest')
        if dest in provenance_map:
            raise ValueError('Duplicate authored provenance destination')
        provenance_map[dest] = item
    authored = _authored_ids(status)
    occupied, after_count, available, unavailable = set(), 0, 0, 0
    for identifier, record in records.items():
        if not isinstance(record, dict):
            raise ValueError('Comparison asset record is invalid')
        before = record.get('before')
        if before is None:
            unavailable += 1
            if record.get('status') != 'unavailable' or not isinstance(record.get('reason'), str) or not record['reason'].strip():
                raise ValueError('Unavailable asset must include a reason: ' + identifier)
        else:
            available += 1
            if record.get('status') != 'available' or not isinstance(before, dict):
                raise ValueError('Available comparison record is invalid: ' + identifier)
            name = before.get('sheet')
            if name not in sheet_map:
                raise ValueError('Sprite references an unknown sheet: ' + identifier)
            if before.get('kind') != kinds[identifier]:
                raise ValueError('Sprite kind differs from catalog kind: ' + identifier)
            x, y = before.get('x'), before.get('y')
            if (before.get('width'), before.get('height')) != (192, 192) or not isinstance(x, int) or not isinstance(y, int):
                raise ValueError('Sprite must fit an exact 192 tile: ' + identifier)
            if x < 0 or y < 0 or x % 192 or y % 192 or x + 192 > 1536 or y + 192 > 1536:
                raise ValueError('Sprite is outside sheet bounds: ' + identifier)
            location = (name, x, y)
            if location in occupied:
                raise ValueError('Duplicate sprite position: ' + identifier)
            occupied.add(location)
        after_items = record.get('after', [])
        if not isinstance(after_items, list):
            raise ValueError('After comparisons must be a list: ' + identifier)
        if after_items and identifier not in authored:
            raise ValueError('After comparison lacks an authored stage: ' + identifier)
        for after in after_items:
            if not isinstance(after, dict):
                raise ValueError('After comparison record is invalid: ' + identifier)
            name = after.get('file')
            path = _webp(base, name, 'after')
            if name in indexed_files:
                raise ValueError('Duplicate indexed WebP: ' + name)
            indexed_files.add(name); after_count += 1
            size = path.stat().st_size; total_bytes += size
            if size > MAX_AFTER_BYTES:
                raise ValueError('After file exceeds byte limit: ' + name)
            width, height = _clean_webp(path)
            if width > 512 or height > 512:
                raise ValueError('After file exceeds dimension limit: ' + name)
            _expect_hash(after.get('sha256'), 'after hash')
            if _hash(path) != after['sha256']:
                raise ValueError('After hash mismatch: ' + name)
            source = after.get('source')
            if not isinstance(source, str) or source.startswith('/') or '\\' in source or '..' in source.split('/'):
                raise ValueError('After source path is unsafe')
            source_path = root / source
            if source_path.is_symlink() or not source_path.is_file():
                raise ValueError('After source is missing or a symlink')
            _expect_hash(after.get('source_sha256'), 'source hash')
            if _hash(source_path) != after['source_sha256']:
                raise ValueError('After source hash mismatch: ' + identifier)
            registered = provenance_map.get(source)
            if (not registered or registered.get('sha256') != after['source_sha256'] or
                    registered.get('original_game_pixels') is not False):
                raise ValueError('After source provenance is missing or invalid: ' + identifier)
            if not all(isinstance(after.get(key), str) and after[key].strip() for key in ('label', 'scope')):
                raise ValueError('After label and scope are required: ' + identifier)
    actual_webps = {p.name for p in base.iterdir() if p.suffix.lower() == '.webp'}
    if actual_webps != indexed_files:
        raise ValueError('Every published comparison WebP must be indexed exactly once')
    if total_bytes > MAX_TOTAL_BYTES:
        raise ValueError('Published comparison WebPs exceed total byte limit')
    return {'assets': len(records), 'available': available, 'unavailable': unavailable,
            'sheets': len(sheets), 'after_files': after_count, 'bytes': total_bytes}


def _valid_identifier(value):
    return isinstance(value, str) and bool(value) and len(value) <= 256


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='validate without changing files')
    parser.add_argument('--root', type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        report = validate(args.root)
    except ValueError as error:
        print('comparison check failed: ' + str(error), file=sys.stderr)
        return 1
    print('comparison check passed: ' + ', '.join(f'{key}={value}' for key, value in report.items()))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
