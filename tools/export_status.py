"""Export public asset metadata with exact, explicitly curated evidence claims.

No original image, mesh, stream or evidence-document contents are copied.
The manifest pins the snapshot timestamp, input identity and evidence hashes.
"""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

try:
    from .texture_inventory import category_estimate
except ImportError:
    from texture_inventory import category_estimate

ROOT = Path(__file__).resolve().parents[1]
STAGES = ('inventoried', 'authored', 'uv_reviewed', 'native_validated',
          'game_fixture_validated', 'approved')
CATEGORIES = {'building', 'character', 'effect', 'equipment_item', 'support_map',
              'terrain_water', 'ui', 'unclassified', 'vegetation', 'world_surface'}
STAGE_DEFINITIONS = {
    'inventoried': 'Unique serialized original asset metadata recorded.',
    'authored': 'An authored replacement is explicitly mapped to this original asset.',
    'uv_reviewed': 'Authored appearance reviewed on identified original mesh UVs, within cited scope.',
    'native_validated': 'Identified authored replacement passed the cited native loading or sampling check.',
    'game_fixture_validated': 'Identified replacement or retained mesh participated in the cited game fixture.',
    'approved': 'Explicit final approval recorded for the stated scope.',
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def public_text(value, label, empty=False):
    if not isinstance(value, str) or (not value and not empty):
        raise ValueError(f'Invalid {label}')
    if any(ord(char) < 32 for char in value) or '\\' in value:
        raise ValueError(f'Private or unsafe {label}')
    if re.search(r'(^|[\s"(])(?:/|~[/]|[A-Za-z]:[/]|file:|local/|build/)', value):
        raise ValueError(f'Private or unsafe {label}')
    return value


def container_paths(values):
    """Keep Unity project-relative source identities, never machine paths."""
    result = set()
    for value in values:
        if (not isinstance(value, str) or not value.startswith('Assets/')
                or '\\' in value or any(ord(char) < 32 for char in value)
                or any(part in ('', '.', '..') for part in value.split('/'))):
            continue
        result.add(value)
    return sorted(result)


def asset_records(inventory):
    records = {}
    for kind, key in (('texture', 'textures'), ('mesh', 'meshes')):
        for source in inventory[key]:
            identity = source.get('id')
            if not isinstance(identity, str) or not re.fullmatch(r'CAB-[A-Za-z0-9]+:-?(0|[1-9][0-9]*)', identity):
                raise ValueError('Invalid CAB:path_id asset identity')
            dimensions = source.get('dimensions') if kind == 'texture' else None
            if dimensions is not None and (not isinstance(dimensions, list)
                    or len(dimensions) not in (2, 3)
                    or any(type(size) is not int or size < 0 for size in dimensions)):
                raise ValueError(f'Invalid texture dimensions for {identity}')
            record = dict(id=identity, kind=kind,
                          object_name=public_text(source.get('name') or '', 'object name', empty=True),
                          container_paths=container_paths(source.get('container_paths', [])),
                          category=source.get('category_estimate'), dimensions=dimensions)
            if identity in records:
                current = records[identity]
                for field in ('kind', 'object_name', 'category', 'dimensions'):
                    if current[field] != record[field]:
                        raise ValueError(f'Conflicting duplicate asset {identity}: {field}')
                current['container_paths'] = sorted(set(current['container_paths']) | set(record['container_paths']))
            else:
                records[identity] = record
    for record in records.values():
        paths = record['container_paths']
        record['name'] = (PurePosixPath(paths[0]).stem if record['kind'] == 'mesh' and paths
                          else record['object_name'] or 'Unnamed')
        if record['category'] not in CATEGORIES:
            record['category'] = category_estimate(paths[0] if paths else record['name'])
        record['stages'] = {stage: stage == 'inventoried' for stage in STAGES}
        record['evidence'] = {}
    return records


def evidence_file(root, value, expected_hash):
    if (not isinstance(value, str) or '\\' in value
            or not value.startswith(('docs/evidence/', 'assets/'))
            or any(part in ('', '.', '..') for part in value.split('/'))
            or PurePosixPath(value).suffix not in ('.json', '.md', '.txt')):
        raise ValueError('Evidence path must be a public project metadata path')
    path = root / value
    if (not path.is_file() or not path.resolve().is_relative_to(root.resolve())
            or any((root / Path(*PurePosixPath(value).parts[:index])).is_symlink()
                   for index in range(1, len(PurePosixPath(value).parts) + 1))):
        raise ValueError(f'Evidence file missing or linked: {value}')
    if not re.fullmatch('[a-f0-9]{64}', str(expected_hash)) or sha256(path.read_bytes()) != expected_hash:
        raise ValueError(f'Evidence hash mismatch: {value}')
    return value


def build_status(inventory, manifest, repo_root, *, inventory_sha256, manifest_sha256):
    if manifest.get('schema_version') != 1:
        raise ValueError('Unsupported status manifest schema')
    stamp = manifest.get('snapshot_at')
    if not isinstance(stamp, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z', stamp):
        raise ValueError('Snapshot timestamp must be pinned UTC ISO-8601')
    try:
        datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError('Invalid snapshot timestamp') from error
    if inventory_sha256 != manifest.get('inventory_sha256'):
        raise ValueError('Inventory hash differs from the reviewed identity mapping')
    records = asset_records(inventory)
    evidence, evidence_ids = [], set()
    for source in manifest.get('evidence', []):
        identity = source.get('id')
        if not isinstance(identity, str) or not re.fullmatch('[a-z0-9][a-z0-9-]*', identity) or identity in evidence_ids:
            raise ValueError('Invalid or duplicate evidence ID')
        evidence_ids.add(identity)
        path = evidence_file(Path(repo_root), source.get('path'), source.get('sha256'))
        targets, completed = set(), set()
        for target in source.get('targets', []):
            if set(target) != {'asset_id', 'stages'}:
                raise ValueError('Evidence target requires only exact asset_id and stages')
            asset_id = target['asset_id']
            if asset_id not in records:
                raise ValueError(f'Unknown asset target: {asset_id}')
            stages = target['stages']
            if not isinstance(stages, list) or any(stage not in STAGES[1:] for stage in stages):
                raise ValueError(f'Unknown stage for {asset_id}')
            targets.add(asset_id)
            completed.update(stages)
            for stage in stages:
                records[asset_id]['stages'][stage] = True
            for stage in stages or ['reference']:
                records[asset_id]['evidence'].setdefault(stage, []).append(identity)
        evidence.append(dict(id=identity, path=path, sha256=source['sha256'],
                             title=public_text(source['title'], 'evidence title'),
                             scope=public_text(source['scope'], 'evidence scope'),
                             targets=sorted(targets), target_count=len(targets), stages=sorted(completed)))
    noted = set()
    for note in manifest.get('asset_notes', []):
        identity = note.get('asset_id')
        if identity not in records or identity in noted:
            raise ValueError('Unknown asset or duplicate asset note')
        noted.add(identity)
        records[identity]['note'] = public_text(note['note'], 'asset note')
    assets = [records[key] for key in sorted(records)]
    for asset in assets:
        asset['evidence'] = {stage: sorted(set(ids)) for stage, ids in sorted(asset['evidence'].items())}
    counts = {kind: {stage: sum(asset['kind'] == kind and asset['stages'][stage] for asset in assets)
                     for stage in STAGES} for kind in ('texture', 'mesh')}
    return dict(
        schema_version=1, snapshot_at=stamp,
        inputs=dict(inventory_sha256=inventory_sha256, status_manifest_sha256=manifest_sha256),
        stage_definitions=STAGE_DEFINITIONS,
        status_semantics='False means no matching completion evidence is recorded. Stages are independent and scoped; inventory is not visible replacement coverage.',
        category_method='Path and filename estimates, not confirmed scene or biome coverage.',
        summary=dict(textures=counts['texture']['inventoried'], meshes=counts['mesh']['inventoried'],
                     authored_models=counts['mesh']['authored'], evidence_records=len(evidence),
                     evidence_target_assets=len({target for item in evidence for target in item['targets']}),
                     stage_counts=counts,
                     category_counts={kind: dict(sorted(Counter(asset['category'] for asset in assets
                                                                if asset['kind'] == kind).items()))
                                      for kind in ('texture', 'mesh')}),
        evidence=sorted(evidence, key=lambda item: item['id']), assets=assets)


def export_file(inventory_path, manifest_path, output_path, repo_root):
    inventory_path, manifest_path, output_path = map(Path, (inventory_path, manifest_path, output_path))
    if output_path.resolve() in (inventory_path.resolve(), manifest_path.resolve()) or output_path.is_symlink():
        raise ValueError('Status output must not overwrite an input or follow a symlink')
    inventory_bytes, manifest_bytes = inventory_path.read_bytes(), manifest_path.read_bytes()
    result = build_status(json.loads(inventory_bytes), json.loads(manifest_bytes), repo_root,
                          inventory_sha256=sha256(inventory_bytes), manifest_sha256=sha256(manifest_bytes))
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(encoded, encoding='utf-8')
    return result


CATALOG_FIELDS = {'schema_version', 'inventory_sha256', 'assets'}
CATALOG_ASSET_FIELDS = {'id', 'kind', 'source_name', 'object_name', 'category',
                        'dimensions', 'container_paths'}
MAX_CATALOG_BYTES = 32 * 1024 * 1024


def _catalog_hash(value, label):
    if not isinstance(value, str) or re.fullmatch('[a-f0-9]{64}', value) is None:
        raise ValueError(f'Invalid {label}')
    return value


def _catalog_text(value, label, *, empty=False):
    public_text(value, label, empty=empty)
    if len(value) > 1024 or any(ord(char) == 127 for char in value):
        raise ValueError(f'Invalid {label}')
    # Unity uses model@animation.fbx names. Remove only that file extension
    # before checking for email-like text, retaining exact published identities.
    email_text = re.sub(r'(?i)\.fbx$', '', value)
    if re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', email_text) or re.search(
            r'(?i)(?:https?://|steamapps|valheim_Data|\.resS\b|\bBearer\s|'
            r'\b(?:token|password|secret|api_key)\s*[=:]|github_pat_|gh[pousr]_[A-Za-z0-9])', value):
        raise ValueError(f'Private or unsafe {label}')
    return value


def catalog_to_inventory(catalog):
    """Validate public identity metadata and construct minimal legacy input.

    Even identical duplicate rows are errors. Progress and payload fields are
    never accepted into this format.
    """
    if not isinstance(catalog, dict) or set(catalog) != CATALOG_FIELDS:
        raise ValueError('Catalog fields differ from strict public schema')
    if type(catalog['schema_version']) is not int or catalog['schema_version'] != 1:
        raise ValueError('Unsupported catalog schema')
    _catalog_hash(catalog['inventory_sha256'], 'original inventory_sha256')
    assets = catalog['assets']
    if not isinstance(assets, list) or len(assets) > 100000:
        raise ValueError('Catalog assets must be a bounded list')
    inventory, seen = {'textures': [], 'meshes': []}, set()
    for asset in assets:
        if not isinstance(asset, dict) or set(asset) != CATALOG_ASSET_FIELDS:
            raise ValueError('Catalog asset fields differ from strict public schema')
        identity = asset['id']
        if (not isinstance(identity, str) or
                re.fullmatch(r'CAB-[0-9a-f]{32}:(?:0|[1-9][0-9]{0,18}|-[1-9][0-9]{0,18})', identity) is None or
                not -(2**63) <= int(identity.split(':')[1]) < 2**63):
            raise ValueError('Invalid exact catalog asset identity')
        if identity in seen:
            raise ValueError('Catalog contains duplicate asset identity')
        seen.add(identity)
        kind = asset['kind']
        if kind not in ('texture', 'mesh'):
            raise ValueError('Invalid catalog asset kind')
        category = asset['category']
        if not isinstance(category, str) or category not in CATEGORIES:
            raise ValueError('Invalid catalog category')
        for field in ('source_name', 'object_name'):
            value = _catalog_text(asset[field], field, empty=field == 'object_name')
            if '/' in value:
                raise ValueError('Catalog names must not contain paths')
        dimensions = asset['dimensions']
        if kind == 'mesh':
            if dimensions is not None:
                raise ValueError('Mesh catalog dimensions must be null')
        elif (not isinstance(dimensions, list) or len(dimensions) not in (2, 3) or
                any(type(size) is not int or not 0 <= size <= 65536 for size in dimensions)):
            raise ValueError('Invalid catalog texture dimensions')
        paths = asset['container_paths']
        if not isinstance(paths, list) or len(paths) > 256:
            raise ValueError('Catalog container paths must be a bounded list')
        for path in paths:
            _catalog_text(path, 'container path')
            if (not path.startswith('Assets/') or ':' in path or
                    any(part in ('', '.', '..') for part in path.split('/'))):
                raise ValueError('Catalog requires Assets-relative container paths')
        if paths != sorted(set(paths)):
            raise ValueError('Catalog container paths must be sorted and unique')
        name = (PurePosixPath(paths[0]).stem if kind == 'mesh' and paths
                else asset['object_name'] or 'Unnamed')
        if asset['source_name'] != name:
            raise ValueError('Catalog source_name differs from original metadata identity')
        record = dict(id=identity, name=asset['object_name'], category_estimate=category,
                      dimensions=dimensions, container_paths=list(paths))
        inventory['textures' if kind == 'texture' else 'meshes'].append(record)
    for records in inventory.values():
        records.sort(key=lambda record: record['id'])
    return inventory


def catalog_from_snapshot(snapshot):
    """Select only stable identity metadata from an already public snapshot."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('assets'), list):
        raise ValueError('Expected public snapshot assets')
    try:
        catalog = dict(schema_version=1, inventory_sha256=snapshot['inputs']['inventory_sha256'],
                       assets=[dict(id=asset['id'], kind=asset['kind'], source_name=asset['name'],
                                    object_name=asset['object_name'], category=asset['category'],
                                    dimensions=asset['dimensions'], container_paths=asset['container_paths'])
                               for asset in snapshot['assets']])
    except (KeyError, TypeError) as error:
        raise ValueError('Public snapshot lacks required catalog metadata') from error
    catalog_to_inventory(catalog)
    catalog['assets'].sort(key=lambda record: record['id'])
    return catalog


def _catalog_json(data):
    if len(data) > MAX_CATALOG_BYTES:
        raise ValueError('Public metadata exceeds bounded size')
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError('Duplicate metadata key')
            result[key] = value
        return result
    def invalid_constant(_):
        raise ValueError('Non-finite metadata number')
    result = json.loads(data, object_pairs_hook=pairs, parse_constant=invalid_constant)
    if not isinstance(result, dict):
        raise ValueError('Expected metadata object')
    return result


def build_catalog_status(catalog_bytes, manifest_bytes, repo_root):
    """Refresh public status through the existing exact evidence validator.

    inventory_sha256 identifies the original inventory behind the catalog.
    catalog_sha256 verifies this pipeline's actual input bytes. Neither the raw
    inventory nor an installed game is required.
    """
    manifest = _catalog_json(manifest_bytes)
    expected = _catalog_hash(manifest.get('catalog_sha256'), 'manifest catalog_sha256')
    if sha256(catalog_bytes) != expected:
        raise ValueError('Catalog hash differs from reviewed metadata')
    catalog = _catalog_json(catalog_bytes)
    inventory = catalog_to_inventory(catalog)
    if type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        raise ValueError('Unsupported status manifest schema')
    _catalog_hash(manifest.get('inventory_sha256'), 'manifest inventory_sha256')
    result = build_status(inventory, manifest, repo_root,
                          inventory_sha256=catalog['inventory_sha256'],
                          manifest_sha256=sha256(manifest_bytes))
    result['inputs']['catalog_sha256'] = expected
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--inventory', type=Path, default=ROOT/'local/texture-inventory/complete/inventory.json')
    parser.add_argument('--manifest', type=Path, default=ROOT/'assets/status/manifest.json')
    parser.add_argument('--output', type=Path, default=ROOT/'local/status-tracker/inventory.json')
    args = parser.parse_args()
    result = export_file(args.inventory, args.manifest, args.output, args.root)
    print(json.dumps(result['summary'], sort_keys=True))


if __name__ == '__main__':
    main()
