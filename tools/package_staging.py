"""Create a local offline review archive, not an installable game release."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.asset_pipeline import ROOT, safe_file, sha256


def collect(stage, manifest):
    files = []
    for asset in manifest['assets']:
        for field in ('png', 'dds', 'unity_dds'):
            if field not in asset:
                continue
            path = safe_file(stage, asset[field])
            if sha256(path) != asset[field + '_sha256']:
                raise ValueError('Staged content changed: ' + str(path))
            if path in files:
                raise ValueError('Duplicate archive entry')
            files.append(path)
    return files


def main():
    stage = ROOT / 'build/staging/meadows'
    manifest_path = safe_file(stage, 'manifest.json')
    manifest = json.loads(manifest_path.read_text())
    files = collect(stage, manifest)
    entries = [('studies/' + path.name, path) for path in files]
    entries.append(('studies/manifest.json', manifest_path))
    for path in ['build/runtime/ValheimImpact.Core.dll', 'build/runtime/ValheimImpact.Unity.dll',
                 'docs/RUNTIME.md', 'docs/VALIDATION.md', 'assets/provenance.json']:
        entries.append((path.removeprefix('build/'), safe_file(ROOT, path)))
    output = ROOT / 'build/valheim-impact-meadows-offline.zip'
    if output.exists():
        raise ValueError('Archive exists; choose a fresh build by removing only this prior project output')
    manifest = {name:sha256(path) for name, path in entries}
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as archive:
        for name, path in entries:
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 12, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
        archive.writestr('OFFLINE-ONLY.txt', 'Authored studies and disabled diagnostics. Not installed or game validated. See docs/VALIDATION.md.\n')
        archive.writestr('SHA256.json', json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'archive':str(output), 'sha256':sha256(output), 'entries':len(entries)+2}))


if __name__ == '__main__':
    main()
