"""Validate biome browsing membership independently of artwork and review scope."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.export_status import catalog_to_inventory
from tools.export_tracker_evidence import BIOME_NAMES, parse_json, public_text, read_source, sequence
from tools.prepare_status_site import _replace, _unlinked

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'assets/status/biome-membership.json'
DESTINATION = 'status-site/public/data/biomes.json'
SUMMARY = 'status-site/data/biome-summary.json'
KINDS = {'vegetation', 'location', 'spawn', 'clutter', 'biome-definition', 'directory', 'reviewed-scope'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def build(source_bytes, catalog_bytes):
    source, catalog = parse_json(source_bytes), parse_json(catalog_bytes)
    if (set(source) != {'schema_version', 'catalog_sha256', 'inventory_sha256', 'scope', 'sources'} or
            type(source.get('schema_version')) is not int or source['schema_version'] != 1):
        raise ValueError('Unknown biome membership schema or fields')
    catalog_to_inventory(catalog)
    if source['catalog_sha256'] != digest(catalog_bytes):
        raise ValueError('Biome membership catalog hash differs')
    if source['inventory_sha256'] != catalog['inventory_sha256']:
        raise ValueError('Biome membership inventory identity differs')
    scope = public_text(source['scope'])
    if len(scope) > 2000:
        raise ValueError('Biome membership scope is too long')
    catalog_assets = {a['id']: a for a in catalog['assets']}
    groups = {key: set() for key in BIOME_NAMES}
    seen = set()
    for row in sequence(source['sources'], 20000):
        if not isinstance(row, dict) or set(row) != {'id', 'kind', 'label', 'biomes', 'asset_ids'}:
            raise ValueError('Unknown biome source fields')
        identifier, label = public_text(row['id']), public_text(row['label'])
        if len(identifier) > 256 or len(label) > 500 or identifier in seen or not isinstance(row['kind'], str) or row['kind'] not in KINDS:
            raise ValueError('Duplicate or invalid biome source')
        seen.add(identifier)
        biomes, asset_ids = sequence(row['biomes'], 9), sequence(row['asset_ids'], 100000)
        if (not biomes or not asset_ids or any(not isinstance(b, str) or b not in groups for b in biomes) or
                len(set(biomes)) != len(biomes) or
                any(not isinstance(a, str) or a not in catalog_assets for a in asset_ids) or
                len(set(asset_ids)) != len(asset_ids)):
            raise ValueError('Unknown, empty or duplicate biome membership')
        for name in biomes:
            groups[name].update(asset_ids)
    frequency = Counter(asset for members in groups.values() for asset in members)
    return {'schema_version': 1,
            'inputs': {'catalog_sha256': digest(catalog_bytes), 'source_sha256': digest(source_bytes),
                       'inventory_sha256': source['inventory_sha256']},
            'scope': scope,
            'biomes': [{'id': key, 'name': name, 'asset_ids': sorted(groups[key]),
                        'texture_count': sum(catalog_assets[a]['kind'] == 'texture' for a in groups[key]),
                        'mesh_count': sum(catalog_assets[a]['kind'] == 'mesh' for a in groups[key])}
                       for key, name in BIOME_NAMES.items()],
            'summary': {'assigned': len(frequency), 'unassigned': len(catalog_assets) - len(frequency),
                        'shared': sum(count > 1 for count in frequency.values())}}


def prepare(root=ROOT, *, check=False):
    root = Path(root).resolve()
    result = build(read_source(root, SOURCE), read_source(root, 'assets/status/catalog.json'))
    published_bytes = (json.dumps(result, separators=(',', ':'), ensure_ascii=False) + '\n').encode()
    summary = {**result, 'data_sha256': digest(published_bytes), 'biomes': [{k: v for k, v in row.items() if k != 'asset_ids'} for row in result['biomes']]}
    outputs = [(root / DESTINATION, result), (root / SUMMARY, summary)]
    encoded = []
    for output, value in outputs:
        _unlinked(output)
        data = (json.dumps(value, separators=(',', ':'), ensure_ascii=False) + '\n').encode()
        if output.exists() and not output.is_file():
            raise ValueError('Biome output must be a regular file')
        if check and (not output.is_file() or output.read_bytes() != data):
            raise ValueError('Biome browsing inventory is stale')
        encoded.append((output, data))
    if not check:
        for output, data in encoded:
            output.parent.mkdir(parents=True, exist_ok=True)
            _replace(output, data)
    return result['summary']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(check=args.check), sort_keys=True))


if __name__ == '__main__':
    main()
