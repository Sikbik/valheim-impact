#!/usr/bin/env python3
"""Stage only owned inputs; optionally execute an explicitly selected Unity Editor."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_FILES = ('Assets/Editor/MeadowsBuild.cs', 'ProjectSettings/ProjectVersion.txt',
                  'ProjectSettings/ProjectSettings.asset', 'Packages/manifest.json')


def safe_path(root, relative):
    root = Path(root).absolute()
    relative = Path(relative)
    if relative.is_absolute() or not relative.parts or any(p in ('.', '..') for p in relative.parts):
        raise ValueError('Expected a contained relative path')
    candidate = root / relative
    for part in (root, *root.parents, candidate, *candidate.parents):
        if part.is_symlink():
            raise ValueError('Symlinks are forbidden: ' + str(part))
    if any(p.lower().endswith('.ress') for p in relative.parts):
        raise ValueError('Resource files are forbidden')
    return candidate


def validate_inputs(source):
    manifest = json.loads(safe_path(source, 'manifest.json').read_text())
    if manifest.get('schema_version') != 1 or not manifest.get('assets'):
        raise ValueError('Unsupported or empty staging manifest')
    seen, inputs = set(), []
    for record in manifest['assets']:
        identifier = record['id']
        if not re.fullmatch('[a-z][a-z0-9_]*', identifier) or identifier in seen:
            raise ValueError('Invalid or duplicate identifier')
        seen.add(identifier)
        name = record['unity_dds']
        if name != identifier + '-unity.dds':
            raise ValueError('Unexpected payload filename')
        path = safe_path(source, name)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != record['unity_dds_sha256']:
            raise ValueError('Payload hash mismatch')
        w, h = record['dimensions']
        if any(type(v) is not int or v < 1 or v > 16384 or v & (v - 1) for v in (w, h)):
            raise ValueError('Invalid dimensions')
        count, size, mw, mh = 0, 0, w, h
        while True:
            count += 1
            size += max(1, (mw + 3) // 4) * max(1, (mh + 3) // 4) * 16
            if mw == mh == 1:
                break
            mw, mh = max(1, mw // 2), max(1, mh // 2)
        if (len(data) != size + 128 or data[:4] != b'DDS ' or data[84:88] != b'DXT5'
                or struct.unpack_from('<I', data, 4)[0] != 124
                or struct.unpack_from('<II', data, 12) != (h, w)
                or struct.unpack_from('<I', data, 28)[0] != count
                or record['mip_count'] != count or record['compressed_payload_bytes'] != size):
            raise ValueError('Invalid full BC3 mip chain')
        if record['unity_row_order'] != 'bottom-up per mip; strip 128-byte DDS header':
            raise ValueError('Wrong row order')
        if record['role'] not in ('albedo', 'normal') or record['srgb'] is not (record['role'] == 'albedo'):
            raise ValueError('Invalid color space')
        if record['role'] == 'normal' and record['normal_encoding'] != 'DXT5nm A=X G=Y':
            raise ValueError('Invalid normal encoding')
        inputs.append((name, data))
    return manifest, inputs


def prepare(root=ROOT, authoring=False):
    root = Path(root).absolute()
    source = safe_path(root, 'build/staging/meadows')
    destination = safe_path(root, 'unity' if authoring else 'build/unity-project')
    manifest, inputs = validate_inputs(source)
    if authoring:
        version = safe_path(destination, 'ProjectSettings/ProjectVersion.txt').read_text()
        if 'm_EditorVersion: 6000.0.75f1' not in version.splitlines():
            raise ValueError('The authoring project must use Unity 6000.0.75f1')
    copies = [] if authoring else [(name, safe_path(root / 'unity', 'Packages/manifest.public.json' if name == 'Packages/manifest.json' else name).read_bytes()) for name in TEMPLATE_FILES]
    copies += [('OwnedInputs/' + name, data) for name, data in inputs]
    copies += [('OwnedInputs/manifest.json', (json.dumps(manifest, indent=2) + '\n').encode())]
    # Preflight every output before writing any files, including existing link ancestors.
    for name, _ in copies:
        safe_path(destination, name)
    for name, data in copies:
        output = safe_path(destination, name)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
    return destination, len(inputs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--editor', type=Path, help='Explicit Unity 6000.0.75f1 Editor executable; execute build after staging')
    parser.add_argument('--authoring', action='store_true', help='Stage inputs into the existing unity/ project, preserving its settings and packages')
    args = parser.parse_args()
    if args.authoring and args.editor:
        parser.error('Use the connected Editor to build the authoring project; --editor is for the separate staging project')
    if args.editor and (not args.editor.is_file()):
        parser.error('Unity Editor executable does not exist')
    project, count = prepare(authoring=args.authoring)
    print(f'Staged {count} owned payloads in {project}', flush=True)
    if args.editor:
        subprocess.run([str(args.editor.absolute()), '-batchmode', '-force-vulkan', '-quit',
                        '-projectPath', str(project), '-buildTarget', 'Linux64',
                        '-executeMethod', 'MeadowsBuild.Build', '-logFile', str(project / 'editor-build.log')], check=True)
    else:
        print('Editor not executed. Native bundles and engine validation remain pending.')


if __name__ == '__main__':
    main()
