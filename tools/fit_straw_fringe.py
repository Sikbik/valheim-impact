"""Fit an explicitly authored RGBA straw fringe without borrowing game masks.

Run with a repository-relative JSON recipe containing schema_version=1,
variant="standard" or "corner", size=512, source={path, sha256}, output and
report. Paths are contained in the repository. The source must have one matching
assets/provenance.json record with original_game_pixels and original_masks_used
both explicitly false.

This tool does not infer alpha from RGB, read reference images, match original
coverage, crop, flip, threshold, or force periodic edges. It measures a complete
uncompressed mip chain for review; those measurements do not validate Unity,
BC3 compression, a native shader, or the silhouette on the game mesh.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.asset_pipeline import mip_chain, quantize, resize_float, safe_destination, safe_file

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = 0.69
CUTOFF_BYTE = 176  # ceil(0.69 * 255), including the saved float approximation.
REFERENCE_PASSING_PIXELS = {'standard': 2446, 'corner': 2427}
MAX_SOURCE_DIMENSION = 4096
MAX_SOURCE_BYTES = 64 * 1024 * 1024


def _pixels(image):
    if image.mode != 'RGBA':
        raise ValueError('Authored fringe must have an actual RGBA channel, not painted transparency')
    if image.width != image.height or not 1 <= image.width <= MAX_SOURCE_DIMENSION:
        raise ValueError('Authored fringe must be square and no larger than 4096 pixels')
    return np.asarray(image)


def _require_cutout(pixels, label):
    alpha = pixels[:, :, 3]
    if not np.any(alpha < CUTOFF_BYTE) or not np.any(alpha >= CUTOFF_BYTE):
        raise ValueError(label + ' must contain alpha both below and at or above the 0.69 cutoff')


def fit_fringe(image, size=512):
    """Resample the complete authored image with alpha-weighted linear RGB.

    Small power-of-two sizes support offline tests; build recipes require 512.
    Equal-size inputs preserve every RGBA byte, including invisible RGB padding.
    """
    if type(size) is not int or not 1 <= size <= 512 or size & (size - 1):
        raise ValueError('Fitted size must be a power of two between 1 and 512')
    pixels = _pixels(image)
    _require_cutout(pixels, 'Authored source')
    if image.size == (size, size):
        return image.copy()
    values = pixels.astype(np.float32) / 255
    rgb, alpha = values[:, :, :3], values[:, :, 3:4]
    linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    small = resize_float(np.concatenate((linear * alpha, alpha), axis=2), (size, size))
    alpha = small[:, :, 3:4]
    linear = small[:, :, :3] / np.maximum(alpha, 1e-8)
    rgb = np.where(linear <= .0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - .055)
    result = quantize(np.concatenate((rgb, alpha), axis=2))
    _require_cutout(result, 'The fitted image')
    return Image.fromarray(result)


def _alpha_metrics(image, level):
    alpha = np.asarray(image)[:, :, 3]
    passing = alpha >= CUTOFF_BYTE
    count = int(np.count_nonzero(passing))
    return {
        'level': level,
        'dimensions': list(image.size),
        'rgba_sha256': hashlib.sha256(image.tobytes()).hexdigest(),
        'alpha_extrema': [int(alpha.min()), int(alpha.max())],
        'alpha_counts': {'zero': int(np.count_nonzero(alpha == 0)),
                         'opaque': int(np.count_nonzero(alpha == 255)),
                         'intermediate': int(np.count_nonzero((alpha > 0) & (alpha < 255)))},
        'mean_alpha': float(np.mean(alpha, dtype=np.float64) / 255),
        'passing_pixels': count,
        'total_pixels': int(alpha.size),
        'coverage': count / alpha.size,
        'edge_coverage': {'top': float(passing[0].mean()), 'bottom': float(passing[-1].mean()),
                          'left': float(passing[:, 0].mean()), 'right': float(passing[:, -1].mean())},
        'repeat_edge_mean_alpha_difference': {
            'left_right': float(np.abs(alpha[:, 0].astype(float) - alpha[:, -1]).mean() / 255),
            'top_bottom': float(np.abs(alpha[0].astype(float) - alpha[-1]).mean() / 255)},
    }


def validate_fringe(image, variant):
    """Report raw alpha coverage without imposing a reference mask or coverage."""
    if variant not in REFERENCE_PASSING_PIXELS:
        raise ValueError('Unknown straw fringe variant')
    _require_cutout(_pixels(image), 'The fitted image')
    mips = [_alpha_metrics(mip, level) for level, mip in enumerate(mip_chain(image, 'albedo'))]
    reference = REFERENCE_PASSING_PIXELS[variant] / 4096
    return {
        'dimensions': list(image.size),
        'cutoff': CUTOFF,
        'cutoff_byte_minimum': CUTOFF_BYTE,
        'mip_filter': 'BOX, linear sRGB RGB weighted by alpha; alpha averaged, no coverage adjustment',
        'mips': mips,
        'mips_without_cutout': [m['level'] for m in mips if m['coverage'] in (0, 1)],
        'mips_with_zero_visible_pixels': [m['level'] for m in mips if m['passing_pixels'] == 0],
        'reference_comparison': {
            'source': 'docs/evidence/default-roof-layout.json, scalar counts only',
            'passing_pixels': REFERENCE_PASSING_PIXELS[variant], 'total_pixels': 4096,
            'coverage': reference, 'base_coverage_delta': mips[0]['coverage'] - reference,
            'used_to_modify_alpha': False,
        },
        'native_shader_validated': False,
        'compressed_mips_validated': False,
        'limitations': [
            'Alpha coverage is a texel measurement, not visible screen or mesh coverage.',
            'Mip cutout loss is reported without changing the newly authored silhouette.',
            'Original Point/Repeat sampling, geometry, two-sided shading and compressed mips need native review.',
        ],
    }


def _json_bytes(document):
    return (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')


def _read_json(path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Metadata exceeds the bounded document size')
    return json.loads(path.read_text(encoding='utf-8'))


def _reject_alias(first, second):
    if first == second or (first.exists() and second.exists() and first.samefile(second)):
        raise ValueError('Output alias would overwrite a source, metadata, or another output: ' + str(second))


def _atomic_write(path, data):
    """Publish each completed file atomically; the report is published last.

    The two outputs are not a filesystem transaction. Its PNG hash lets a reader
    reject a stale report if publication is interrupted between files.
    """
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


def build(recipe_path):
    recipe_path = Path(recipe_path)
    if recipe_path.is_absolute():
        try:
            recipe_path = recipe_path.relative_to(ROOT.absolute())
        except ValueError as error:
            raise ValueError('Recipe must be contained in the repository') from error
    recipe_path = safe_file(ROOT, recipe_path)
    recipe = _read_json(recipe_path)
    if (not isinstance(recipe, dict) or
            set(recipe) != {'schema_version', 'variant', 'size', 'source', 'output', 'report'} or
            type(recipe['schema_version']) is not int or recipe['schema_version'] != 1 or
            type(recipe['size']) is not int or recipe['size'] != 512 or
            not isinstance(recipe['variant'], str) or recipe['variant'] not in REFERENCE_PASSING_PIXELS):
        raise ValueError('Expected a version 1 standard/corner fringe recipe with size 512')
    entry = recipe['source']
    if (not isinstance(entry, dict) or set(entry) != {'path', 'sha256'} or
            not isinstance(entry['path'], str) or not isinstance(entry['sha256'], str) or
            re.fullmatch('[0-9a-f]{64}', entry['sha256']) is None or
            not isinstance(recipe['output'], str) or not isinstance(recipe['report'], str)):
        raise ValueError('Expected an explicit source path/SHA256 and output/report paths')
    source = safe_file(ROOT, entry['path'])
    provenance_path = safe_file(ROOT, 'assets/provenance.json')
    destination = safe_destination(ROOT, recipe['output'])
    report_path = safe_destination(ROOT, recipe['report'])
    for output in (destination, report_path):
        for protected in (source, recipe_path, provenance_path):
            _reject_alias(output, protected)
    _reject_alias(destination, report_path)
    if source.suffix.lower() != '.png' or destination.suffix.lower() != '.png' or report_path.suffix.lower() != '.json':
        raise ValueError('Source/output must be PNG and the report must be JSON')
    provenance = _read_json(provenance_path)
    if not isinstance(provenance, dict) or not isinstance(provenance.get('assets'), list):
        raise ValueError('Invalid authored provenance registry')
    records = [record for record in provenance['assets']
               if isinstance(record, dict) and record.get('dest') == entry['path']]
    if (len(records) != 1 or records[0].get('sha256') != entry['sha256'] or
            records[0].get('original_game_pixels') is not False or
            records[0].get('original_masks_used') is not False):
        raise ValueError('Authored source provenance is missing, ambiguous or mismatched')
    if source.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError('Authored source exceeds the bounded file size')
    source_bytes = source.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != entry['sha256']:
        raise ValueError('Authored source hash mismatch')
    with Image.open(io.BytesIO(source_bytes)) as original:
        if original.format != 'PNG':
            raise ValueError('Authored source must be a PNG image')
        image = fit_fringe(original, recipe['size'])
        source_dimensions = list(original.size)
        source_mode = original.mode
    report = validate_fringe(image, recipe['variant'])
    encoded = io.BytesIO()
    image.save(encoded, format='PNG', compress_level=9)
    png_bytes = encoded.getvalue()
    report.update({
        'schema_version': 1, 'variant': recipe['variant'],
        'source': dict(entry, dimensions=source_dimensions, mode=source_mode),
        'recipe': {'path': str(recipe_path.relative_to(ROOT)),
                   'sha256': hashlib.sha256(recipe_path.read_bytes()).hexdigest()},
        'provenance': {'path': 'assets/provenance.json',
                       'record_sha256': hashlib.sha256(_json_bytes(records[0])).hexdigest()},
        'output': recipe['output'], 'report': recipe['report'],
        'sha256': hashlib.sha256(png_bytes).hexdigest(),
        'original_game_pixels': False,
        'original_masks_used': False,
        'fit': 'whole-image BOX with alpha-weighted linear RGB, top-down rows preserved',
        'alpha_source': 'authored RGBA input alpha; this fitting step applies no reference mask or color key',
    })
    report_bytes = _json_bytes(report)
    _atomic_write(destination, png_bytes)
    _atomic_write(report_path, report_bytes)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe', type=Path)
    print(json.dumps(build(parser.parse_args().recipe), indent=2, sort_keys=True))
