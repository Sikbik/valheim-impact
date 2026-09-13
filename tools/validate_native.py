"""Check owned bundle serialization and actual Vulkan base-mip GPU readbacks."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.prepare_unity import safe_path

ROOT = Path(__file__).resolve().parents[1]


def validate_sampler(texture, record, wrap_mode):
    if wrap_mode not in ('repeat', 'clamp'):
        raise ValueError('Staged wrap_mode must be repeat or clamp')
    expected = 0 if wrap_mode == 'repeat' else 1
    settings = texture.m_TextureSettings
    if (record.get('wrapMode') != wrap_mode
            or (settings.m_WrapU, settings.m_WrapV, settings.m_WrapW) != (expected,) * 3
            or settings.m_FilterMode != 2 or settings.m_Aniso != 4 or settings.m_MipBias != 0):
        raise ValueError('Owned texture sampler differs from its recipe: ' + record['id'])
    return wrap_mode


def compare_readback(reference, actual, srgb):
    if reference.shape != actual.shape or reference.ndim != 3 or reference.shape[2] != 4:
        raise ValueError('GPU readback dimensions differ')
    expected = reference.astype(np.float64) / 255.0
    if srgb:
        rgb = expected[:, :, :3]
        expected[:, :, :3] = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    error = np.abs(actual.astype(np.float64) - expected * 255)
    result = {'mean_error': float(error.mean()), 'max_error': float(error.max())}
    # BC3 interpolation and 8-bit linear-target quantization differ slightly
    # between the independent decoder and the GPU. A flipped atlas is far worse.
    if result['max_error'] > 4 or result['mean_error'] > .6:
        raise ValueError('GPU readback exceeds BC3 sampling tolerance: ' + str(result))
    return result


def main():
    import UnityPy  # Only bundle inspection needs the inspection dependency set.
    root, stage = ROOT / 'unity/Bundles', ROOT / 'build/staging/meadows'
    catalog = json.loads(safe_path(root, 'catalog.json').read_text())
    staging = json.loads(safe_path(stage, 'manifest.json').read_text())
    staged = {record['id']: record for record in staging['assets']}
    if len(staged) != len(staging['assets']) or set(staged) != {record['id'] for record in catalog['textures']}:
        raise ValueError('Native catalog and staged texture identities differ')
    if catalog.get('graphicsApi') != 'Vulkan' or catalog.get('colorSpace') != 'Linear':
        raise ValueError('This evidence requires the Vulkan, Linear authoring configuration')
    reports = []
    for record in catalog['textures']:
        bundle = safe_path(root, record['path'])
        if hashlib.sha256(bundle.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Bundle content changed: ' + record['id'])
        textures = [o.read() for o in UnityPy.load(str(bundle)).objects if o.type.name == 'Texture2D']
        if len(textures) != 1:
            raise ValueError('Expected exactly one owned texture')
        texture = textures[0]
        wrap_mode = validate_sampler(texture, record, staged[record['id']].get('wrap_mode'))
        payload = texture.get_image_data()
        if (len(payload) != record['payloadBytes'] or texture.m_IsReadable
                or texture.m_StreamData.size != record['payloadBytes'] or len(texture.image_data) != 0
                or texture.m_Width != record['width'] or texture.m_Height != record['height']
                or texture.m_MipCount != record['mipCount'] or texture.m_TextureFormat != 12
                or hashlib.sha256(payload).hexdigest() != record['payloadSha256']):
            raise ValueError('Owned texture streaming contract failed: ' + record['id'])
        readback = safe_path(root, record['gpuReadback'])
        if hashlib.sha256(readback.read_bytes()).hexdigest() != record['gpuReadbackSha256']:
            raise ValueError('GPU readback changed')
        reference = np.asarray(Image.open(safe_path(stage, record['id'] + '.dds')).convert('RGBA'))
        actual = np.asarray(Image.open(readback).convert('RGBA'))
        errors = compare_readback(reference, actual, record['isSrgb'])
        reports.append({'id': record['id'], 'width': record['width'], 'height': record['height'],
                        'payload_bytes': len(payload), 'stream_payload_verified': True,
                        'cpu_readable': False, 'wrap_mode': wrap_mode,
                        'sampler_verified': True, 'gpu_sampling': errors})
    report = {'editor': catalog['editorVersion'], 'graphics_api': catalog['graphicsApi'],
              'color_space': catalog['colorSpace'], 'textures': reports,
              'compressed_payload_bytes': sum(t['payload_bytes'] for t in reports),
              'native_bundles_bytes': sum(safe_path(root, r['path']).stat().st_size for r in catalog['textures']),
              'gpu_base_mip_validation': True, 'game_validation': False,
              'note': 'Native layout and GPU sampling evidence, not a VRAM or frame-time benchmark.'}
    output = ROOT / 'docs/evidence/native-validation.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'textures': len(reports), 'payload_bytes': report['compressed_payload_bytes'],
                      'max_gpu_error': max(r['gpu_sampling']['max_error'] for r in reports),
                      'output': str(output)}))


if __name__ == '__main__':
    main()
