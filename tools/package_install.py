"""Build an experimental install ZIP from explicitly owned and validated inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import struct
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer.package import CHUNK, Package, PackageError, no_links, safe_path, sha256, strict_json

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ('ValheimImpact.Core.dll', 'ValheimImpact.Unity.dll')
NOTICE = b'''Valheim Impact: EXPERIMENTAL DIAGNOSTIC / PROBE BUILD

This is an authored Meadows foundation, not a finished HD visual overhaul.
Game material replacement requires explicit installer opt-in and a compatible
binding allowlist. Only listed base-texture slots are replaced. Original assets and mods are
not included. Native texture readback does not validate model or shader streaming,
game compatibility, frame times, total VRAM use, or a 6 GB hardware target.

Balanced is the default development profile for a 6 GB VRAM / 16 GB RAM / 1080p
target. High is intended for higher resolution and 4K evaluation. Component
budgets are not total system or graphics memory limits.

Close Valheim before installing, updating, uninstalling or rolling back. The
installer records owned files and keeps local transaction backups under
BepInEx/plugins/ValheimImpact/.installer. Existing mods and saves stay outside
its ownership. Packages are unsigned: hashes verify integrity, not publisher identity.
'''


def local_json(path):
    path = no_links(path)
    if path.stat().st_size > 4 * 1024**2:
        raise ValueError('Input manifest is too large')
    return strict_json(path.read_bytes())


def under(root, relative):
    safe_path(relative)
    return no_links(Path(root) / relative)


def build_package(*, catalog, output, runtime_dir=ROOT/'build/runtime',
                  staging_manifest=ROOT/'build/staging/meadows/manifest.json',
                  provenance=ROOT/'assets/provenance.json', source_root=ROOT, version='0.1.0-experimental', bindings=None):
    catalog, output, staging_manifest = no_links(catalog), no_links(output), no_links(staging_manifest)
    if output.exists():
        raise ValueError('Output exists. Choose a fresh output path')
    data, stage, origins = local_json(catalog), local_json(staging_manifest), local_json(provenance)
    if data.get('schemaVersion') != 1 or data.get('editorVersion') != '6000.0.75f1' or data.get('nativeReadback') is not True:
        raise ValueError('A matching Unity 6000.0.75f1 catalog with nativeReadback=true is required')
    targets = {'StandaloneLinux64': 'linux-x86_64', 'StandaloneWindows64': 'windows-x86_64'}
    if data.get('target') not in targets:
        raise ValueError('Unsupported native bundle target')
    authored = {}
    for entry in origins['assets']:
        if entry.get('original_game_pixels') is False:
            authored[entry['dest']] = entry['sha256']
    inputs = {}
    for item in stage['assets']:
        if item['id'] in inputs:
            raise ValueError('Duplicate staged asset ID')
        inputs[item['id']] = item
    if not data.get('textures') or len(data['textures']) != len(inputs):
        raise ValueError('Native catalog must match the staged authored asset set')
    entries = [(name, no_links(Path(runtime_dir) / name)) for name in RUNTIME]
    entries.append(('assets/catalog.json', catalog))
    seen = set()
    for texture in data['textures']:
        identifier = texture['id']
        if identifier in seen or identifier not in inputs:
            raise ValueError('Duplicate or unknown native texture ID')
        seen.add(identifier)
        item = inputs[identifier]
        # Image periodicity is independent of sampling. Historical staging used
        # Repeat; an absent native declaration remains unknown in packaged bytes.
        staged_wrap = item.get('wrap_mode', 'repeat')
        if type(staged_wrap) is not str or staged_wrap not in ('repeat', 'clamp'):
            raise ValueError('Invalid staged wrap mode: ' + identifier)
        if 'wrapMode' in texture:
            declared_wrap = texture['wrapMode']
            if type(declared_wrap) is not str or declared_wrap not in ('repeat', 'clamp'):
                raise ValueError('Invalid declared native wrap mode: ' + identifier)
            if declared_wrap != staged_wrap:
                raise ValueError('Native sampler differs from staged wrap mode: ' + identifier)
        source = under(source_root, item['source'])
        if authored.get(item['source']) != item['source_sha256'] or sha256(source) != item['source_sha256']:
            raise ValueError('Source provenance mismatch: ' + identifier)
        native = under(staging_manifest.parent, item['unity_dds'])
        if sha256(native) != item['unity_dds_sha256']:
            raise ValueError('Staged native DDS integrity mismatch: ' + identifier)
        payload_hash, payload_size = hashlib.sha256(), 0
        with native.open('rb') as reader:
            header = reader.read(128)
            if len(header) != 128 or header[:4] != b'DDS ' or header[84:88] != b'DXT5':
                raise ValueError('Expected staged BC3 DDS')
            while chunk := reader.read(CHUNK):
                payload_hash.update(chunk)
                payload_size += len(chunk)
        expected = dict(width=item['dimensions'][0], height=item['dimensions'][1], mipCount=item['mip_count'], payloadBytes=item['compressed_payload_bytes'], isSrgb=item['srgb'], payloadSha256=payload_hash.hexdigest())
        if any(texture.get(key) != value for key, value in expected.items()) or payload_size != expected['payloadBytes']:
            raise ValueError('Native descriptor differs from authored payload: ' + identifier)
        relative = safe_path(texture['path'])
        if not relative.endswith('.bundle'):
            raise ValueError('Only explicit native .bundle paths can be packaged')
        bundle = under(catalog.parent, relative)
        if sha256(bundle) != texture['sha256']:
            raise ValueError('Native bundle integrity mismatch: ' + identifier)
        entries.append(('assets/' + relative, bundle))
    if bindings is not None:
        bindings = no_links(bindings)
        rules = local_json(bindings)
        if (set(rules) != {'schemaVersion', 'bindings'} or type(rules['schemaVersion']) is not int or rules['schemaVersion'] not in (1, 2, 3) or
                not isinstance(rules['bindings'], list) or not 1 <= len(rules['bindings']) <= 32):
            raise ValueError('Invalid binding allowlist')
        ids, slots = set(), set()
        fields = {'id', 'materialName', 'shaderName', 'textureProperty', 'originalTextureName',
                  'originalWidth', 'originalHeight', 'ownedTextureId'}
        descriptors = {t['id']: t for t in data['textures']}
        for rule in rules['bindings']:
            if not isinstance(rule, dict) or set(rule) not in (fields, fields | {'cutout'}, fields | {'grass'}):
                raise ValueError('Invalid binding fields')
            for key in fields - {'originalWidth', 'originalHeight'}:
                if not isinstance(rule[key], str) or not rule[key].strip() or len(rule[key]) > 256 or '\0' in rule[key]:
                    raise ValueError('Invalid exact binding identity')
            slot = (rule['materialName'], rule['shaderName'], rule['textureProperty'])
            target = descriptors.get(rule['ownedTextureId'])
            if (rule['id'] in ids or slot in slots or rule['textureProperty'] != '_MainTex' or
                    target is None or target['isSrgb'] is not True or
                    any(type(rule[k]) is not int or not 1 <= rule[k] <= 16384 for k in ('originalWidth', 'originalHeight'))):
                raise ValueError('Duplicate, unsupported or unknown binding')
            if 'cutout' in rule:
                state = rule['cutout']
                state_fields = {'mode', 'cutoff', 'cull', 'zWrite', 'srcBlend', 'dstBlend', 'renderQueue', 'alphaTest'}
                if (rules['schemaVersion'] not in (2, 3) or rule['shaderName'] != 'Custom/Piece' or
                        not isinstance(state, dict) or set(state) != state_fields):
                    raise ValueError('Invalid explicit cutout expectation')
                if (any(type(state[key]) not in (int, float)
                        for key in state_fields - {'renderQueue', 'alphaTest'}) or
                        state['mode'] != 1 or not 0 < state['cutoff'] < 1 or state['cull'] not in (0, 2) or
                        state['zWrite'] != 1 or state['srcBlend'] != 1 or state['dstBlend'] != 0 or
                        type(state['renderQueue']) is not int or not 1000 <= state['renderQueue'] <= 2500 or
                        type(state['alphaTest']) is not bool):
                    raise ValueError('Blended, incomplete or unsupported cutout expectation')
                # Runtime state is System.Single. Values strictly inside (0,1)
                # as Python doubles can round onto a forbidden endpoint there.
                cutoff32 = struct.unpack('<f', struct.pack('<f', state['cutoff']))[0]
                if not 0 < cutoff32 < 1:
                    raise ValueError('Cutout threshold leaves its supported range at runtime float precision')
            if rule['shaderName'] == 'Custom/Grass' and 'grass' not in rule:
                raise ValueError('Grass requires its explicit schema 3 expectation')
            if 'grass' in rule:
                state = rule['grass']
                state_fields = {'fixedPasses', 'cutoff', 'renderQueue', 'terrainTextureName', 'terrainWidth',
                                'terrainHeight', 'terrainColorScale', 'swayDistance', 'pushDistance'}
                if (rules['schemaVersion'] != 3 or rule['shaderName'] != 'Custom/Grass' or
                        not isinstance(state, dict) or set(state) != state_fields):
                    raise ValueError('Invalid explicit grass expectation')
                if (state['fixedPasses'] != 'Custom/Grass-v1' or state['terrainTextureName'] != 'grass_terrain_color' or
                        any(type(state[key]) is not int or state[key] != value
                            for key, value in [('renderQueue', 2000), ('terrainWidth', 1024), ('terrainHeight', 1024)])):
                    raise ValueError('Unsupported fixed grass shader or terrain identity')
                def single(value):
                    if type(value) not in (int, float):
                        raise ValueError('Grass values must be JSON numbers')
                    try:
                        return struct.unpack('<f', struct.pack('<f', value))[0]
                    except (OverflowError, struct.error) as error:
                        raise ValueError('Grass value exceeds runtime float range') from error
                if (single(state['cutoff']) != single(.46) or single(state['terrainColorScale']) != single(.01)):
                    raise ValueError('Grass cutoff or terrain scale differs from reviewed state')
                identity = (rule['materialName'], rule['originalTextureName'], rule['originalWidth'], rule['originalHeight'],
                            single(state['swayDistance']), single(state['pushDistance']))
                if identity not in (('grasscross_meadows', 'grass_meadows', 128, 128, single(2.3), single(2)),
                                    ('grasscross_meadows_short', 'grass_meadows_short', 64, 64, single(1), single(.5))):
                    raise ValueError('Grass material, texture or variant state differs from reviewed identity')
            ids.add(rule['id']); slots.add(slot)
        entries.append(('assets/bindings.json', bindings))
    payloads = {name: (path, dict(path=name, size=path.stat().st_size, sha256=sha256(path))) for name, path in entries}
    if len(payloads) != len(entries):
        raise ValueError('Duplicate package payload')
    payloads['EXPERIMENTAL.txt'] = (NOTICE, dict(path='EXPERIMENTAL.txt', size=len(NOTICE), sha256=hashlib.sha256(NOTICE).hexdigest()))
    manifest = dict(schemaVersion=1, product='ValheimImpact', version=version, platform=targets[data['target']], experimental=True,
                    files=[value[1] for _, value in sorted(payloads.items())])
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + '.tmp-' + uuid.uuid4().hex)
    try:
        with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr('manifest.json', json.dumps(manifest, indent=2) + '\n')
            for name, (source, _) in sorted(payloads.items()):
                info = zipfile.ZipInfo('payload/' + name, date_time=(2026, 9, 12, 0, 0, 0))
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                if isinstance(source, bytes):
                    archive.writestr(info, source)
                else:
                    no_links(source)
                    with source.open('rb') as reader, archive.open(info, 'w', force_zip64=True) as writer:
                        while chunk := reader.read(CHUNK):
                            writer.write(chunk)
        verified = Package.read(temporary)
        # Exclusive output creation avoids silently overwriting a concurrent build.
        with output.open('xb') as writer, temporary.open('rb') as reader:
            while chunk := reader.read(CHUNK):
                writer.write(chunk)
        return dict(output=str(output), sha256=verified.digest, files=len(manifest['files']), platform=manifest['platform'], experimental=True)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime-dir', type=Path, default=ROOT/'build/runtime')
    parser.add_argument('--staging-manifest', type=Path, default=ROOT/'build/staging/meadows/manifest.json')
    parser.add_argument('--provenance', type=Path, default=ROOT/'assets/provenance.json')
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--bindings', type=Path, help='Explicit metadata-only game material allowlist')
    parser.add_argument('--version', default='0.1.0-experimental')
    args = parser.parse_args()
    try:
        print(json.dumps(build_package(**vars(args)), indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, 'Package build stopped: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
