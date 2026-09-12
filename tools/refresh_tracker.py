"""Validate all public tracker inputs, then refresh or check derived files."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.export_status import build_catalog_status
from tools.export_tracker_evidence import build_pages, export_pages, parse_json, read_source
from tools.prepare_status_site import prepare, _unlinked, _replace
from tools.validate_roadmap import validate_roadmap

ROOT = Path(__file__).resolve().parents[1]


def refresh(root=ROOT, *, check=False):
    root = Path(root).resolve()
    manifest_bytes = read_source(root, 'assets/status/manifest.json')
    manifest = parse_json(manifest_bytes)
    snapshot = build_catalog_status(read_source(root, 'assets/status/catalog.json'), manifest_bytes, root)
    roadmap = parse_json(read_source(root, 'assets/status/roadmap.json'))
    validate_roadmap(roadmap, snapshot, manifest, root)
    pages = build_pages(root, manifest)
    destination = root / 'status-site/public/evidence'
    roadmap_path = root / 'status-site/data/roadmap.json'
    encoded_roadmap = (json.dumps(roadmap, indent=2, ensure_ascii=False) + '\n').encode()
    outputs = [root / 'status-site/public/data/inventory.json', root / 'status-site/data/summary.json',
               roadmap_path, *[destination / name for name in pages]]
    for path in outputs:
        _unlinked(path)
        if path.exists() and not path.is_file():
            raise ValueError('Tracker output must be a regular file')
    if destination.exists() and (not destination.is_dir() or
            {path.name for path in destination.iterdir()} - set(pages)):
        raise ValueError('Unexpected files in tracker evidence directory')
    if check and (not roadmap_path.is_file() or roadmap_path.read_bytes() != encoded_roadmap):
        raise ValueError('Tracker roadmap is stale')
    # All schemas, evidence, approval gates and destinations are checked before writes.
    prepare(root, check=check)
    export_pages(root, root / 'assets/status/manifest.json', destination, check=check)
    if not check:
        _replace(roadmap_path, encoded_roadmap)
    return {'assets': len(snapshot['assets']), 'biomes': len(roadmap['biomes']),
            'evidence_pages': len(pages), 'current': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--check', action='store_true', help='Compare without writing files')
    args = parser.parse_args()
    print(json.dumps(refresh(args.root, check=args.check), sort_keys=True))


if __name__ == '__main__':
    main()
