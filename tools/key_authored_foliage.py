"""Derive a local alpha candidate from project-authored foliage RGB."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, label

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.asset_pipeline import quantize, safe_destination
from tools.key_authored_straw import _atomic_write, _reject_alias, _source_file

ROOT = Path(__file__).resolve().parents[1]
MAX_SOURCE_DIMENSION = 2048
MAX_SOURCE_BYTES = 64 * 1024 * 1024


def _local_output(relative, suffix):
    if not isinstance(relative, str):
        raise ValueError('Expected an explicit local output path')
    path = safe_destination(ROOT, relative)
    parts = Path(relative).parts
    if len(parts) < 2 or parts[0] != 'local' or path.suffix.lower() != suffix:
        raise ValueError('Candidate outputs must be contained in local/ with the expected file type')
    return path


def derive_alpha(image, transparent=10, opaque=32):
    """Return RGBA with alpha estimated only from authored RGB chroma."""
    if image.mode != 'RGB':
        raise ValueError('This explicit preprocessing step requires RGB input')
    if image.width != image.height or not 1 <= image.width <= MAX_SOURCE_DIMENSION:
        raise ValueError('Expected a square authored RGB image no larger than 2048 pixels')
    if (type(transparent) is not int or type(opaque) is not int or
            not 0 <= transparent < opaque <= 255):
        raise ValueError('Expected integer thresholds 0 <= transparent < opaque <= 255')

    rgb = np.asarray(image)
    channels = rgb.astype(np.int16)
    score = channels.max(axis=2) - channels.min(axis=2)
    confident = score >= opaque
    background = score <= transparent
    if not np.any(confident) or not np.any(background):
        raise ValueError('Need both confident foliage and neutral-background pixels')

    weight = np.clip((score.astype(np.float64) - transparent) / (opaque - transparent), 0, 1)
    alpha = quantize(weight * weight * (3 - 2 * weight))
    distances, indices = distance_transform_edt(~confident, return_indices=True)
    padded_rgb = rgb[indices[0], indices[1]]
    rgba = np.concatenate((padded_rgb, alpha[:, :, None]), axis=2)
    partial = (alpha > 0) & (alpha < 255)
    foreground, component_count = label(alpha > 0)
    del foreground
    passing = alpha >= 128
    partial_distances = distances[partial]
    report = {
        'status': 'candidate for visual review',
        'method_version': 1,
        'method': 'RGB chroma score, smoothstep alpha, nearest confident authored RGB padding',
        'chroma_score': 'max(R,G,B)-min(R,G,B), 8-bit RGB channel units',
        'thresholds': {'transparent_at_or_below': transparent, 'opaque_at_or_above': opaque},
        'dimensions': list(image.size),
        'alpha_extrema': [int(alpha.min()), int(alpha.max())],
        'alpha_counts': {'zero': int(np.count_nonzero(alpha == 0)),
                         'opaque': int(np.count_nonzero(alpha == 255)),
                         'intermediate': int(np.count_nonzero(partial))},
        'mean_alpha': float(np.mean(alpha, dtype=np.float64) / 255),
        'cutoff': 0.5,
        'cutoff_byte_minimum': 128,
        'coverage_at_cutoff': float(passing.mean()),
        'edge_occupancy_at_cutoff': {
            'top': float(passing[0].mean()), 'bottom': float(passing[-1].mean()),
            'left': float(passing[:, 0].mean()), 'right': float(passing[:, -1].mean()),
        },
        'connected_foreground_components': int(component_count),
        'confident_authored_pixels': int(np.count_nonzero(confident)),
        'partial_color_lookup_distance_max': float(partial_distances.max()) if partial_distances.size else 0.0,
        'native_validated': False,
        'game_validated': False,
        'uv_approved': False,
        'limitations': [
            'Source RGB contains no real alpha; this is an estimated authored mask, not recovered transparency.',
            'Neutral foliage colors can be removed, and colorful background contamination can remain.',
            'Partial alpha depends on explicit chroma thresholds rather than a measured composite.',
            'Nearest-color padding can borrow a neighboring authored leaf or branch color.',
            'Geometry, UV fit, compressed mips, native sampling, game rendering, and art approval remain unvalidated.',
        ],
    }
    return Image.fromarray(rgba), report


def build(input_path, expected_sha256,
          output='local/meadows-trees/foliage/beech-branch-derived.png',
          report='local/meadows-trees/foliage/beech-branch-derived.json',
          transparent=10, opaque=32):
    source = _source_file(input_path)
    if not isinstance(expected_sha256, str) or re.fullmatch('[0-9a-f]{64}', expected_sha256) is None:
        raise ValueError('An explicit lowercase source SHA256 is required')
    destination = _local_output(output, '.png')
    report_path = _local_output(report, '.json')
    for path in (destination, report_path):
        _reject_alias(path, source)
    _reject_alias(destination, report_path)
    if source.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError('Authored source exceeds the bounded file size')
    source_bytes = source.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != expected_sha256:
        raise ValueError('Authored RGB source hash mismatch')
    with Image.open(io.BytesIO(source_bytes)) as original:
        if original.format != 'PNG':
            raise ValueError('Expected an authored PNG image')
        image, metadata = derive_alpha(original, transparent, opaque)
    encoded = io.BytesIO()
    image.save(encoded, format='PNG', compress_level=9)
    png_bytes = encoded.getvalue()
    metadata.update({
        'schema_version': 1,
        'source': {'path': str(source), 'sha256': expected_sha256, 'mode': 'RGB',
                   'designation': 'explicit user-designated authored RGB'},
        'output': output,
        'report': report,
        'sha256': hashlib.sha256(png_bytes).hexdigest(),
        'original_game_pixels': False,
        'original_masks_used': False,
        'axes': 'input dimensions and top-down rows preserved, no crop or flip',
    })
    report_bytes = (json.dumps(metadata, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    _atomic_write(destination, png_bytes)
    _atomic_write(report_path, report_bytes)
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', default='local/meadows-trees/foliage/beech-branch-derived.png')
    parser.add_argument('--report', default='local/meadows-trees/foliage/beech-branch-derived.json')
    parser.add_argument('--transparent', type=int, default=10)
    parser.add_argument('--opaque', type=int, default=32)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.input, arguments.sha256, arguments.output, arguments.report,
                           arguments.transparent, arguments.opaque), indent=2, sort_keys=True))
