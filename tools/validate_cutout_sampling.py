"""Compare finite native cutout samples against independent BC3 decoding.

Run after CutoutSamplingProbe.Run in the matching Editor. Raw images remain in
local storage. The public output contains hashes and scalar measurements only.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import numpy as np
from PIL import Image
import texture2ddecoder

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.prepare_unity import safe_path
from tools.validate_native import compare_readback

ROOT = Path(__file__).resolve().parents[1]


def compare_mask(alpha, mask, cutoff, *, quantized_native_alpha=False, sampled_alpha=None):
    """Allow sparse one-byte BC3 rounding uncertainty at the exact cutoff."""
    if (type(cutoff) not in (int, float) or not math.isfinite(cutoff) or
            not 0 < cutoff < 1 or alpha.ndim != 2 or alpha.size == 0 or
            mask.shape != (*alpha.shape, 4) or alpha.dtype != np.uint8 or
            mask.dtype != np.uint8):
        raise ValueError('Invalid alpha, native mask dimensions or cutoff')
    if sampled_alpha is not None and (sampled_alpha.shape != alpha.shape or
                                       sampled_alpha.dtype != np.uint8):
        raise ValueError('Invalid sampled native alpha')
    if not np.all((mask == 0) | (mask == 255)) or not np.all(mask == mask[:, :, :1]):
        raise ValueError('Expected a binary RGBA native mask')
    native = mask[:, :, 0] == 255
    expected = alpha >= math.ceil(cutoff * 255)
    mismatched = native != expected
    mask_reference = alpha if sampled_alpha is None else sampled_alpha
    reference_expected = mask_reference >= math.ceil(cutoff * 255)
    reference_mismatched = native != reference_expected
    if np.any(reference_mismatched &
              (np.abs(mask_reference.astype(float) - cutoff * 255) > 1)):
        raise ValueError('Native mask differs away from cutoff rounding uncertainty')
    disagreements = int(mismatched.sum())
    # A fractional GPU sample may contain many sub-byte alpha values that all
    # round to the same saved byte. That PNG cannot independently reconstruct
    # the shader threshold; report these differences instead of approving them.
    if not quantized_native_alpha and disagreements > max(1, math.floor(alpha.size * .005)):
        raise ValueError('Native mask has too many threshold disagreements')
    return {'disagreements': disagreements,
            'decoder_passing_pixels': int(expected.sum()),
            'native_passing_pixels': int(native.sum()),
            'total_pixels': int(alpha.size),
            'native_coverage': float(native.mean())}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(texture_id):
    if not re.fullmatch('[a-z][a-z0-9_]{0,79}', texture_id):
        raise ValueError('Invalid owned texture identifier')
    stage = ROOT / 'build/staging/meadows'
    native = ROOT / 'local/meadows-pass/native-cutout' / texture_id
    report_path = safe_path(native, 'report.json')
    report = json.loads(report_path.read_text())
    if (report.get('complete') is not True or report.get('ownedObjectsDestroyed') is not True or
            report.get('textureId') != texture_id or report.get('editorVersion') != '6000.0.75f1' or
            report.get('graphicsApi') != 'Vulkan' or report.get('colorSpace') != 'Linear' or
            report.get('gameShaderValidated') is not False):
        raise ValueError('Incomplete or incompatible native report')
    cutoff = report['cutoff']
    manifest = json.loads(safe_path(stage, 'manifest.json').read_text())
    candidates = [a for a in manifest['assets'] if a['id'] == texture_id]
    if len(candidates) != 1:
        raise ValueError('Expected exactly one staged texture identity')
    asset = candidates[0]
    if asset.get('alpha_cutoff') != cutoff and abs(asset.get('alpha_cutoff', -1) - cutoff) > 1e-7:
        raise ValueError('Cutoff differs from staged material requirement')
    catalog = json.loads(safe_path(ROOT / 'unity/Bundles', 'catalog.json').read_text())
    entries = [e for e in catalog['textures'] if e['id'] == texture_id]
    if len(entries) != 1 or entries[0]['sha256'] != report['bundleSha256']:
        raise ValueError('Report does not identify the current native bundle')
    bundle = safe_path(ROOT / 'unity/Bundles', entries[0]['path'])
    if digest(bundle) != report['bundleSha256']:
        raise ValueError('Native bundle changed')
    dds_path = safe_path(stage, asset['dds'])
    if digest(dds_path) != asset['dds_sha256']:
        raise ValueError('Staged DDS changed')
    # Establish that the native artifact contains this exact bottom-up payload.
    import UnityPy
    objects = [o.read() for o in UnityPy.load(str(bundle)).objects if o.type.name == 'Texture2D']
    unity_dds = safe_path(stage, asset['unity_dds'])
    if (digest(unity_dds) != asset['unity_dds_sha256'] or len(objects) != 1 or
            objects[0].get_image_data() != unity_dds.read_bytes()[128:]):
        raise ValueError('Native texture differs from the staged payload')
    blob = dds_path.read_bytes()
    width, height = asset['dimensions']
    samples = report['samples']
    if (len(samples) != 2 * asset['mip_count'] - 1 or
            len({(s['filter'], s['lod']) for s in samples}) != len(samples)):
        raise ValueError('Missing or duplicated native sample')
    levels = []
    offset = 128
    for level in range(asset['mip_count']):
        rows = [s for s in samples if s['filter'] == 'Point' and s['lod'] == level]
        if len(rows) != 1 or (rows[0]['width'], rows[0]['height']) != (width, height):
            raise ValueError('Native point mip dimensions differ')
        row = rows[0]
        size = max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * 16
        raw = texture2ddecoder.decode_bc3(blob[offset:offset + size], width, height)
        decoded = np.asarray(Image.frombytes('RGBA', (width, height), raw, 'raw', 'BGRA'))
        color, mask = read_samples(native, row)
        errors = compare_readback(decoded, color, True)
        comparison = compare_mask(decoded[:, :, 3], mask, cutoff, sampled_alpha=color[:, :, 3])
        if comparison['native_passing_pixels'] != row['passingPixels']:
            raise ValueError('Native mask count differs from report')
        levels.append({'level': level, 'dimensions': [width, height],
                       'gpu_sampling': errors, **comparison,
                       'color_sha256': row['colorSha256'], 'mask_sha256': row['maskSha256']})
        width, height = max(1, width // 2), max(1, height // 2)
        offset += size
    if (width, height) != (1, 1) or offset != len(blob):
        raise ValueError('Expected a complete BC3 mip chain')
    fractional = []
    for level in range(asset['mip_count'] - 1):
        rows = [s for s in samples if s['filter'] == 'Trilinear' and s['lod'] == level + .5]
        if len(rows) != 1 or (rows[0]['width'], rows[0]['height']) != (128, 128):
            raise ValueError('Missing fractional native sample')
        row = rows[0]
        color, mask = read_samples(native, row)
        comparison = compare_mask(color[:, :, 3], mask, cutoff, quantized_native_alpha=True)
        if row['passingPixels'] != comparison['native_passing_pixels']:
            raise ValueError('Fractional native count differs')
        fractional.append({'lod': row['lod'], 'dimensions': [128, 128],
                           'coverage': comparison['native_coverage'],
                           'threshold_rounding_disagreements': comparison['disagreements'],
                           'color_sha256': row['colorSha256'], 'mask_sha256': row['maskSha256']})
    return {'schema_version': 1, 'texture_id': texture_id,
            'source_sha256': asset['source_sha256'], 'bundle_sha256': report['bundleSha256'],
            'dds_sha256': asset['dds_sha256'], 'unity_dds_sha256': asset['unity_dds_sha256'],
            'native_report_sha256': digest(report_path), 'editor': report['editorVersion'],
            'graphics_api': 'Vulkan', 'color_space': 'Linear', 'cutoff': cutoff,
            'owned_objects_destroyed': True, 'point_mips': levels,
            'fractional_trilinear_diagnostics': fractional,
            'game_shader_validated': False,
            'limitations': ['Texel coverage is not screen-space or whole-mesh coverage.',
                            'Small mips have quantized silhouettes; a single texel is either visible or absent.',
                            'Fractional native samples are diagnostic, not acceptance of LOD transitions in game.',
                            'No game shader, weather, world, or performance approval.']}


def read_samples(root, row):
    images = []
    for kind in ('color', 'mask'):
        path = safe_path(root, row[kind + 'File'])
        if digest(path) != row[kind + 'Sha256']:
            raise ValueError('Native readback hash mismatch')
        with Image.open(path) as image:
            if image.mode != 'RGBA' or image.size != (row['width'], row['height']):
                raise ValueError('Unexpected native readback format or dimensions')
            images.append(np.asarray(image))
    return images


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('texture_id')
    args = parser.parse_args()
    result = validate(args.texture_id)
    destination = ROOT / 'docs/evidence' / (args.texture_id + '-sampling.json')
    destination.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'texture': args.texture_id, 'mips': len(result['point_mips']),
                      'fractional_samples': len(result['fractional_trilinear_diagnostics']),
                      'owned_objects_destroyed': True}))
