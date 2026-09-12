"""Explicit local candidate derivation from authored warm-straw RGB.

This opt-in preprocessing step estimates alpha from a neutral gray/white
background painted into a user-designated authored RGB image. It does not recover
true source alpha. It never reads original game images or masks, and it does not
make the strict RGBA fringe fitter accept RGB input.

Example: python tools/key_authored_straw.py /absolute/authored.png --sha256 HASH
Outputs are restricted to local/ and remain candidates for visual review.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, label

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.asset_pipeline import quantize, safe_destination

ROOT = Path(__file__).resolve().parents[1]
MAX_SOURCE_DIMENSION = 2048
MAX_SOURCE_BYTES = 64 * 1024 * 1024


def derive_alpha(image, transparent=8, opaque=64):
    """Keep full layout and derive a graded mask solely from authored RGB.

    The warm score is min(R-B, 2*(G-B)) in 8-bit channel units. Smoothstep between
    explicit thresholds provides partial alpha. Every non-confident pixel takes
    RGB from the nearest confident source pixel, including invisible padding.
    This removes neutral RGB from edges without borrowing any new colors.
    """
    if image.mode != 'RGB':
        raise ValueError('This explicit preprocessing step requires RGB input')
    if image.width != image.height or not 1 <= image.width <= MAX_SOURCE_DIMENSION:
        raise ValueError('Expected a square authored RGB image no larger than 2048 pixels')
    if (type(transparent) is not int or type(opaque) is not int or
            not 0 <= transparent < opaque <= 255):
        raise ValueError('Expected integer thresholds 0 <= transparent < opaque <= 255')
    rgb = np.asarray(image)
    channels = rgb.astype(np.int16)
    score = np.minimum(channels[:, :, 0] - channels[:, :, 2],
                       2 * (channels[:, :, 1] - channels[:, :, 2]))
    confident = score >= opaque
    background = score <= transparent
    if not np.any(confident) or not np.any(background):
        raise ValueError('Need both confident warm straw and neutral-background pixels')
    weight = np.clip((score.astype(np.float64) - transparent) / (opaque - transparent), 0, 1)
    alpha = quantize(weight * weight * (3 - 2 * weight))
    distances, indices = distance_transform_edt(~confident, return_indices=True)
    # EDT indices always select a confident authored pixel. Confident RGB keeps
    # its own exact bytes; no luminance, generated color, or original mask enters.
    padded_rgb = rgb[indices[0], indices[1]]
    rgba = np.concatenate((padded_rgb, alpha[:, :, None]), axis=2)
    partial = (alpha > 0) & (alpha < 255)
    partial_distances = distances[partial]
    gaps, _ = label(alpha == 0)
    edge_labels = np.unique(np.concatenate((gaps[0], gaps[-1], gaps[:, 0], gaps[:, -1], [0])))
    gap_sizes = np.bincount(gaps.ravel())
    gap_sizes[edge_labels] = 0
    passing = alpha >= 176
    report = {
        'status': 'candidate for visual review', 'method_version': 1,
        'method': 'warm RGB chroma key, smoothstep alpha, nearest confident authored RGB padding',
        'warm_score': 'min(R-B, 2*(G-B)), 8-bit RGB channel units',
        'thresholds': {'transparent_at_or_below': transparent, 'opaque_at_or_above': opaque},
        'dimensions': list(image.size),
        'alpha_extrema': [int(alpha.min()), int(alpha.max())],
        'alpha_counts': {'zero': int(np.count_nonzero(alpha == 0)),
                         'opaque': int(np.count_nonzero(alpha == 255)),
                         'intermediate': int(np.count_nonzero(partial))},
        'confident_authored_pixels': int(np.count_nonzero(confident)),
        'mean_alpha': float(np.mean(alpha, dtype=np.float64) / 255),
        'cutoff': 0.69, 'cutoff_byte_minimum': 176,
        'coverage_at_cutoff': float(passing.mean()),
        'background_class_pixels_retained_at_cutoff': int(np.count_nonzero(background & passing)),
        'edge_coverage_at_cutoff': {'top': float(passing[0].mean()), 'bottom': float(passing[-1].mean()),
                                   'left': float(passing[:, 0].mean()), 'right': float(passing[:, -1].mean())},
        'edge_review': {
            'partial_pixels_farther_than_two_pixels': int(np.count_nonzero(partial_distances > 2)),
            'partial_color_lookup_distance_max': float(partial_distances.max()) if partial_distances.size else 0.0,
            'partial_color_lookup_distance_p95': float(np.percentile(partial_distances, 95)) if partial_distances.size else 0.0,
            'enclosed_fully_transparent_components': int(np.count_nonzero(gap_sizes)),
            'largest_enclosed_fully_transparent_component_pixels': int(gap_sizes.max()),
            'halo_render_validated': False,
        },
        'game_validated': False, 'uv_approved': False,
        'limitations': [
            'Source RGB contains no real alpha; this is a heuristic mask, not recovered source transparency.',
            'Neutral or desaturated straw can be removed, and warm background contamination can survive.',
            'Partial alpha depends on explicit color thresholds, not a measured foreground/background composite.',
            'Nearest-color padding may borrow a neighboring strand color at thin tips or small gaps.',
            'Enclosed transparent components may be intended gaps or removed neutral fibers; none are filled.',
            'Review on dark and light backgrounds, then validate fitted and compressed mips on actual geometry.',
        ],
    }
    return Image.fromarray(rgba), report


def _source_file(path):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('Symlinks are forbidden in the authored input path')
    if not path.is_file() or path.suffix.lower() != '.png':
        raise ValueError('Expected a regular authored PNG input')
    return path


def _local_output(relative, suffix):
    if not isinstance(relative, str):
        raise ValueError('Expected an explicit local output path')
    path = safe_destination(ROOT, relative)
    parts = Path(relative).parts
    if len(parts) < 2 or parts[0] != 'local' or path.suffix.lower() != suffix:
        raise ValueError('Candidate outputs must be contained in local/ with the expected file type')
    return path


def _reject_alias(first, second):
    if first == second or (first.exists() and second.exists() and first.samefile(second)):
        raise ValueError('Output alias would overwrite the source or another output')


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.' + path.name + '.', suffix='.tmp',
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build(input_path, expected_sha256, output='local/status-tracker/straw-fringe-derived.png',
          report='local/status-tracker/straw-fringe-derived.json', transparent=8, opaque=64):
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
        'output': output, 'report': report,
        'sha256': hashlib.sha256(png_bytes).hexdigest(),
        'original_game_pixels': False,
        'original_masks_used': False,
        'axes': 'input dimensions and top-down rows preserved, no crop or flip',
    })
    report_bytes = (json.dumps(metadata, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')
    # Each file is atomic, not the pair. Report last; its PNG SHA detects stale
    # metadata if publication is interrupted between files.
    _atomic_write(destination, png_bytes)
    _atomic_write(report_path, report_bytes)
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', default='local/status-tracker/straw-fringe-derived.png')
    parser.add_argument('--report', default='local/status-tracker/straw-fringe-derived.json')
    parser.add_argument('--transparent', type=int, default=8)
    parser.add_argument('--opaque', type=int, default=64)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.input, arguments.sha256, arguments.output, arguments.report,
                           arguments.transparent, arguments.opaque), indent=2, sort_keys=True))
