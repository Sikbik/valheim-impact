"""Coverage-preserving alpha adjustment for authored cutout mip chains."""
import argparse
import io
import json
import math
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def cutoff_byte(cutoff):
    if isinstance(cutoff, bool) or not isinstance(cutoff, (int, float)):
        raise TypeError('alpha_cutoff must be a finite number strictly between zero and one')
    if not math.isfinite(cutoff) or not 0 < cutoff < 1:
        raise ValueError('alpha_cutoff must be a finite number strictly between zero and one')
    return int(math.ceil(cutoff * 255))


def _scaled_alpha(alpha, scale):
    original = np.asarray(alpha, dtype=np.uint8)
    adjusted = np.rint(np.clip(original.astype(np.float64) * scale, 0, 255)).astype(np.uint8)
    adjusted[original == 0] = 0
    adjusted[(original > 0) & (adjusted == 0)] = 1
    return adjusted


def _candidate_scales(alpha, threshold):
    positive = np.unique(alpha[alpha > 0])
    scales = [1.0]
    boundaries = sorted({(threshold - .5) / int(value) for value in positive})
    if boundaries:
        scales.append(max(boundaries[0] / 2, np.finfo(float).tiny))
        scales.extend((left + right) / 2 for left, right in zip(boundaries, boundaries[1:]))
        scales.append(boundaries[-1] * 2)
    for value in positive:
        boundary = (threshold - .5) / int(value)
        scales.extend((max(np.nextafter(boundary, -math.inf), np.finfo(float).tiny), boundary,
                       np.nextafter(boundary, math.inf)))
    return scales


def preserve_cutout_coverage(alpha, cutoff, target_coverage):
    """Uniformly scale alpha to the nearest achievable texel coverage.

    Equal alpha values remain equal, exact zero stays zero, and no spatial mask
    is introduced to manufacture a requested count.
    """
    threshold = cutoff_byte(cutoff)
    if isinstance(target_coverage, bool) or not isinstance(target_coverage, (int, float)):
        raise TypeError('target_coverage must be a finite number from zero through one')
    if not math.isfinite(target_coverage) or not 0 <= target_coverage <= 1:
        raise ValueError('target_coverage must be a finite number from zero through one')
    alpha = np.asarray(alpha, dtype=np.uint8)
    if alpha.ndim != 2 or alpha.size == 0:
        raise ValueError('alpha must be a non-empty two-dimensional array')

    candidates = []
    for scale in _candidate_scales(alpha, threshold):
        adjusted = _scaled_alpha(alpha, scale)
        achieved = float((adjusted >= threshold).mean())
        nonzero = adjusted[alpha > 0].astype(np.float64)
        margin = float(np.min(np.abs(nonzero - (threshold - .5)))) if nonzero.size else 255.0
        candidates.append((abs(achieved - target_coverage), achieved, -margin,
                           abs(math.log(scale)), scale, adjusted))
    _, achieved, _, _, scale, adjusted = min(candidates, key=lambda item: item[:5])
    error = achieved - target_coverage
    return adjusted, {
        'target_coverage': float(target_coverage),
        'achieved_coverage': achieved,
        'coverage_error': error,
        'coverage_quantum': 1 / alpha.size,
        'target_unattainable': not math.isclose(error, 0, abs_tol=1e-15),
        'alpha_scale': float(scale),
        'cutoff': float(cutoff),
        'cutoff_byte_minimum': threshold,
    }


def preserve_bc3_tail_coverage(image, cutoff, target_coverage):
    """Choose an explainable uniform alpha scale using decoded BC3 coverage."""
    import texture2ddecoder
    threshold = cutoff_byte(cutoff)
    rgba = np.asarray(image.convert('RGBA'))
    alpha = rgba[:, :, 3]
    candidates = []
    for scale in _candidate_scales(alpha, threshold):
        pixels = rgba.copy()
        pixels[:, :, 3] = _scaled_alpha(alpha, scale)
        pad_y, pad_x = (-image.height) % 4, (-image.width) % 4
        padded = Image.fromarray(np.pad(pixels, ((0, pad_y), (0, pad_x), (0, 0)), mode='edge'))
        stream = io.BytesIO()
        padded.save(stream, format='DDS', pixel_format='DXT5')
        raw = texture2ddecoder.decode_bc3(stream.getvalue()[128:], padded.width, padded.height)
        decoded = np.asarray(Image.frombytes('RGBA', padded.size, raw, 'raw', 'BGRA'))[:image.height, :image.width]
        encoded_coverage = float((pixels[:, :, 3] >= threshold).mean())
        decoded_coverage = float((decoded[:, :, 3] >= threshold).mean())
        decoded_alpha = decoded[:, :, 3].astype(np.float64)
        passing = decoded_alpha >= threshold
        if np.any(passing):
            decoded_margin = float(np.min(decoded_alpha[passing] - cutoff * 255))
        else:
            decoded_margin = float(cutoff * 255 - decoded_alpha.max())
        candidates.append((abs(decoded_coverage - target_coverage),
                           -decoded_margin, abs(encoded_coverage - target_coverage),
                           decoded_coverage, abs(math.log(scale)), scale, pixels))
    _, negative_margin, _, decoded_coverage, _, scale, pixels = min(
        candidates, key=lambda item: item[:6])
    return Image.fromarray(pixels), {'alpha_scale': float(scale),
        'decoded_coverage': decoded_coverage, 'decoded_cutoff_margin': -negative_margin,
        'target_coverage': float(target_coverage)}


def report_chain(mips, cutoff, ordinary_mips=None):
    threshold = cutoff_byte(cutoff)
    base = np.asarray(mips[0].convert('RGBA'))[:, :, 3]
    target = float((base >= threshold).mean())
    levels = []
    for level, mip in enumerate(mips):
        alpha = np.asarray(mip.convert('RGBA'))[:, :, 3]
        achieved = float((alpha >= threshold).mean())
        record = {'level': level, 'dimensions': list(mip.size),
                  'passing_pixels': int((alpha >= threshold).sum()),
                  'total_pixels': int(alpha.size), 'coverage': achieved,
                  'base_coverage_delta': achieved - target, 'coverage_quantum': 1 / alpha.size}
        if ordinary_mips is not None:
            ordinary_alpha = np.asarray(ordinary_mips[level].convert('RGBA'))[:, :, 3]
            ordinary_coverage = float((ordinary_alpha >= threshold).mean())
            record['ordinary_coverage'] = ordinary_coverage
            if level:
                if max(mip.size) <= 4:
                    _, adjustment = preserve_bc3_tail_coverage(ordinary_mips[level], cutoff, target)
                else:
                    _, adjustment = preserve_cutout_coverage(ordinary_alpha, cutoff, target)
                record.update(alpha_scale=adjustment['alpha_scale'],
                              target_unattainable=not math.isclose(achieved, target, abs_tol=1e-15))
        levels.append(record)
    return {'cutoff': float(cutoff), 'cutoff_byte_minimum': threshold,
            'authored_base_coverage': target, 'mips': levels}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--cutoff', type=float, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import texture2ddecoder
    from tools.asset_pipeline import encode_dds, mip_chain
    image = Image.open(args.image).convert('RGBA')
    ordinary = mip_chain(image, 'albedo')
    corrected = mip_chain(image, 'albedo', alpha_cutoff=args.cutoff)
    report = report_chain(corrected, args.cutoff, ordinary_mips=ordinary)
    blob = encode_dds(corrected)
    offset = 128
    compressed = []
    threshold = cutoff_byte(args.cutoff)
    for level, mip in enumerate(corrected):
        size = max(1, (mip.width + 3) // 4) * max(1, (mip.height + 3) // 4) * 16
        raw = texture2ddecoder.decode_bc3(blob[offset:offset + size], mip.width, mip.height)
        decoded = np.asarray(Image.frombytes('RGBA', mip.size, raw, 'raw', 'BGRA'))
        expected = report['mips'][level]['coverage']
        actual = float((decoded[:, :, 3] >= threshold).mean())
        quantum = 1 / (mip.width * mip.height)
        allowed = .01 + min(1.0, 16 * quantum)
        if expected > 0 and actual == 0:
            raise ValueError('Compressed cutout lost every passing texel')
        if abs(actual - expected) > allowed:
            raise ValueError('Compressed cutout coverage differs beyond per-mip tolerance')
        compressed.append({'level': level, 'dimensions': list(mip.size), 'coverage': expected,
                           'decoded_coverage': actual, 'coverage_delta': actual - expected,
                           'coverage_quantum': quantum, 'allowed_coverage_delta': allowed})
        offset += size
    report.update(bc3_decoder='texture2ddecoder ' + texture2ddecoder.__version__,
                  compressed_mips=compressed, native_render_validation=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'mips': len(report['mips'])}))


if __name__ == '__main__':
    main()
