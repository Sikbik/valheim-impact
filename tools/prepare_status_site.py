"""Refresh the public tracker from the pinned catalog and reviewed evidence.

No installed game or ignored original inventory is needed. Check mode reads and
compares files only. Both snapshots are fully validated before either is written;
individual files are atomically replaced. A check detects interrupted mixed pairs.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.export_status import MAX_CATALOG_BYTES, build_catalog_status

ROOT = Path(__file__).resolve().parents[1]


def _unlinked(path):
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError('Tracker metadata paths must not follow symlinks')
    if any(parent.exists() and not parent.is_dir() for parent in path.parents):
        raise ValueError('Tracker metadata parent is not a directory')


def _read(path):
    _unlinked(path)
    if not path.is_file() or path.stat().st_size > MAX_CATALOG_BYTES:
        raise ValueError('Missing or oversized public tracker metadata')
    data = path.read_bytes()
    if len(data) > MAX_CATALOG_BYTES:
        raise ValueError('Oversized public tracker metadata')
    return data


def _replace(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.status-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def prepare(root=ROOT, *, check=False):
    root = Path(root)
    snapshot = build_catalog_status(_read(root / 'assets/status/catalog.json'),
                                    _read(root / 'assets/status/manifest.json'), root)
    files = {
        root / 'status-site/public/data/inventory.json': (json.dumps(
            snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode(),
        root / 'status-site/data/summary.json': (json.dumps(
            {key: value for key, value in snapshot.items() if key != 'assets'}, indent=2, sort_keys=True,
            allow_nan=False) + '\n').encode(),
    }
    for path in files:
        _unlinked(path)
        if path.exists() and not path.is_file():
            raise ValueError('Tracker destination is not a regular file')
    if check:
        for path, content in files.items():
            if not path.is_file() or path.read_bytes() != content:
                raise ValueError('Tracker snapshot is stale: ' + path.relative_to(root).as_posix())
    else:
        for path, content in files.items():
            _replace(path, content)
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--check', action='store_true', help='Read-only check that both tracker snapshots are current')
    args = parser.parse_args()
    prepare(args.root, check=args.check)
    print('Tracker snapshot matches reviewed evidence.' if args.check else 'Tracker snapshot refreshed from reviewed evidence.')


if __name__ == '__main__':
    main()
