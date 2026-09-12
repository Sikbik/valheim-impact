"""Independently decode every staged BC3 mip and report measured image fidelity."""
import io
import json
from pathlib import Path
import struct
import sys

import numpy as np
from PIL import Image
import texture2ddecoder

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.asset_pipeline import ROOT, sha256, safe_file, bc3_bytes
from tools.cutout_mips import cutoff_byte


def cutout_coverage_measurement(source_alpha, decoded_alpha, cutoff):
    threshold = cutoff_byte(cutoff)
    source_alpha = np.asarray(source_alpha)
    decoded_alpha = np.asarray(decoded_alpha)
    if source_alpha.shape != decoded_alpha.shape or source_alpha.ndim != 2 or source_alpha.size == 0:
        raise ValueError('Cutout alpha planes must have matching non-empty dimensions')
    coverage = float((source_alpha >= threshold).mean())
    decoded_coverage = float((decoded_alpha >= threshold).mean())
    if coverage > 0 and decoded_coverage == 0:
        raise ValueError('Compressed cutout lost every passing texel')
    quantum = 1 / source_alpha.size
    allowed = .01 + min(1.0, 16 * quantum)
    return dict(coverage=coverage, decoded_coverage=decoded_coverage,
                coverage_delta=decoded_coverage - coverage,
                coverage_quantum=quantum, allowed_coverage_delta=allowed,
                cutoff=float(cutoff), cutoff_byte_minimum=threshold)


def main():
    stage = ROOT / 'build/staging/meadows'
    manifest = json.loads(safe_file(stage, 'manifest.json').read_text())
    results = []
    for asset in manifest['assets']:
        for kind in ['png', 'dds', 'unity_dds']:
            if sha256(safe_file(stage, asset[kind])) != asset[kind + '_sha256']:
                raise ValueError('Digest mismatch')
        image = np.asarray(Image.open(stage / asset['png']).convert('RGBA'))
        width, height = asset['dimensions']
        blob = (stage / asset['dds']).read_bytes()
        unity_blob = (stage / asset['unity_dds']).read_bytes()
        if len(blob) != bc3_bytes(width, height) + 128 or len(blob) != len(unity_blob):
            raise ValueError('Incorrect chain size')
        if struct.unpack_from('<I', blob, 28)[0] != asset['mip_count']:
            raise ValueError('Incorrect mip count')
        offset, levels, decoded = 128, 0, None
        alpha_cutoff = asset.get('alpha_cutoff')
        cutout_mips = []
        while True:
            size = max(1, (width+3)//4) * max(1, (height+3)//4) * 16
            raw = texture2ddecoder.decode_bc3(blob[offset:offset+size], width, height)
            pixels = np.asarray(Image.frombytes('RGBA', (width, height), raw, 'raw', 'BGRA'))
            unity_raw = texture2ddecoder.decode_bc3(unity_blob[offset:offset+size], width, height)
            unity_pixels = np.asarray(Image.frombytes('RGBA', (width, height), unity_raw, 'raw', 'BGRA'))
            if not np.array_equal(pixels, unity_pixels[::-1]):
                # Tiny levels have different padded block partitions. Bound decoder error.
                if np.abs(pixels.astype(float) - unity_pixels[::-1]).max() > 35:
                    raise ValueError('Native storage orientation differs beyond BC3 tolerance')
            if levels == 0:
                decoded = pixels
            if asset['role'] == 'albedo' and asset['alpha_policy'] == 'cutout' and alpha_cutoff is not None:
                expected = asset['cutout_mips'][levels]
                threshold = cutoff_byte(alpha_cutoff)
                decoded_coverage = float((pixels[:, :, 3] >= threshold).mean())
                quantum = 1 / (width * height)
                measurement = dict(level=levels, dimensions=[width, height], cutoff=float(alpha_cutoff),
                    cutoff_byte_minimum=threshold, coverage=expected['coverage'],
                    decoded_coverage=decoded_coverage,
                    coverage_delta=decoded_coverage - expected['coverage'], coverage_quantum=quantum,
                    allowed_coverage_delta=.01 + min(1.0, 16 * quantum))
                if measurement['coverage'] > 0 and decoded_coverage == 0:
                    raise ValueError('Compressed cutout lost every passing texel')
                if abs(measurement['coverage_delta']) > measurement['allowed_coverage_delta']:
                    raise ValueError('Compressed cutout coverage differs beyond per-mip tolerance')
                cutout_mips.append(measurement)
            offset += size
            levels += 1
            if (width, height) == (1, 1):
                break
            width, height = max(1,width//2), max(1,height//2)
        if levels != asset['mip_count'] or offset != len(blob):
            raise ValueError('Mip payload boundaries mismatch')
        error = np.abs(image.astype(float) - decoded.astype(float))
        record = dict(id=asset['id'], decoded_mips=levels, rgb_mean_absolute_error=float(error[:,:,:3].mean()),
                      alpha_mean_absolute_error=float(error[:,:,3].mean()),
                      coverage_at_128=float((image[:,:,3] >= 128).mean()),
                      decoded_coverage_at_128=float((decoded[:,:,3] >= 128).mean()))
        if cutout_mips:
            record['cutout_mips'] = cutout_mips
        if asset['role'] == 'albedo' and asset['alpha_policy'] == 'cutout' and alpha_cutoff is None:
            if abs(record['coverage_at_128'] - record['decoded_coverage_at_128']) > .01:
                raise ValueError('Base cutout coverage changed by over one percentage point')
        if asset['role'] == 'normal':
            xy = decoded[:,:,(3,1)].astype(float) / 127.5 - 1
            record['max_decoded_tangent_xy_length'] = float(np.linalg.norm(xy,axis=2).max())
            if record['max_decoded_tangent_xy_length'] > 1:
                raise ValueError('Invalid decoded normal hemisphere')
        if asset['periodic']:
            record['png_edge_max_error'] = int(max(np.abs(image[0].astype(int)-image[-1]).max(),
                                                  np.abs(image[:,0].astype(int)-image[:,-1]).max()))
        results.append(record)
    output = ROOT / 'docs/evidence/asset-validation.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(decoder='texture2ddecoder ' + texture2ddecoder.__version__,
        engine_render_validation=False, assets=results), indent=2) + '\n')
    print(json.dumps({'textures':len(results), 'decoded_mips':sum(r['decoded_mips'] for r in results), 'output':str(output)}))


if __name__ == '__main__':
    main()
