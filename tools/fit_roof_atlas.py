"""Fit only authored images to an explicit, fully covered opaque atlas grid."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.asset_pipeline import periodic_rgb, safe_file, safe_destination

ROOT = Path(__file__).resolve().parents[1]


def compose_atlas(sources, layout):
    reference, output = layout['reference_size'], layout['output_size']
    if (len(reference) != 2 or len(output) != 2 or
            any(type(v) is not int or v < 1 or v > 4096 for v in reference + output) or
            any(v & (v - 1) for v in output) or
            any(output[i] % reference[i] for i in (0, 1))):
        raise ValueError('Atlas dimensions must use a bounded integral reference grid')
    regions = layout['regions']
    if not isinstance(regions, list) or not 1 <= len(regions) <= 32:
        raise ValueError('Expected a bounded region list')
    coverage = np.zeros((reference[1], reference[0]), dtype=np.uint8)
    prepared = []
    for region in regions:
        box, turns = region['box'], region['quarter_turns']
        if (len(box) != 4 or any(type(v) is not int for v in box) or
                not 0 <= box[0] < box[2] <= reference[0] or
                not 0 <= box[1] < box[3] <= reference[1] or
                type(turns) is not int or not 0 <= turns <= 3):
            raise ValueError('Invalid atlas region or rotation')
        patch = coverage[box[1]:box[3], box[0]:box[2]]
        if np.any(patch):
            raise ValueError('Atlas regions overlap')
        patch[:] = 1
        image = sources[region['source']].convert('RGBA')
        if image.getchannel('A').getextrema() != (255, 255):
            raise ValueError('Opaque atlas input contains transparency')
        if turns:
            image = image.transpose((Image.Transpose.ROTATE_90, Image.Transpose.ROTATE_180,
                                     Image.Transpose.ROTATE_270)[turns - 1])
        dest = [box[i] * output[i % 2] // reference[i % 2] for i in range(4)]
        width, height = dest[2] - dest[0], dest[3] - dest[1]
        # Uniform scale and centered crop preserve grain proportions. Resizing a
        # complete square directly into a narrow atlas band would squash detail.
        scale = max(width / image.width, height / image.height)
        image = image.resize((math.ceil(image.width * scale), math.ceil(image.height * scale)), Image.Resampling.LANCZOS)
        x, y = (image.width - width) // 2, (image.height - height) // 2
        pixels = np.asarray(image.crop((x, y, x + width, y + height))).copy()
        pixels[:, :, :3] = periodic_rgb(pixels[:, :, :3])
        prepared.append((dest, pixels))
    if not np.all(coverage):
        raise ValueError('Atlas has uncovered pixels')
    pixels = np.zeros((output[1], output[0], 4), dtype=np.uint8)
    for (x0, y0, x1, y1), patch in prepared:
        pixels[y0:y1, x0:x1] = patch
    return Image.fromarray(pixels)


def reject_output_alias(destination, protected):
    if destination == protected or (destination.exists() and destination.samefile(protected)):
        raise ValueError('Atlas output would overwrite a source or metadata file: ' + str(protected))


def build(layout_path):
    layout_path = Path(layout_path).absolute()
    layout = json.loads(layout_path.read_text())
    destination = safe_destination(ROOT, layout['output'])
    provenance_path = safe_file(ROOT, 'assets/provenance.json')
    reject_output_alias(destination, layout_path)
    reject_output_alias(destination, provenance_path)
    provenance = json.loads(provenance_path.read_text())
    if not isinstance(provenance, dict) or not isinstance(provenance.get('assets'), list):
        raise ValueError('Invalid authored provenance registry')
    sources = {}
    for key, entry in layout['sources'].items():
        path = safe_file(ROOT, entry['path'])
        reject_output_alias(destination, path)
        records = [record for record in provenance['assets']
                   if isinstance(record, dict) and record.get('dest') == entry['path']]
        if (len(records) != 1 or records[0].get('sha256') != entry['sha256'] or
                records[0].get('original_game_pixels') is not False):
            raise ValueError('Authored source provenance is missing, ambiguous or mismatched: ' + key)
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('Authored source hash mismatch: ' + key)
        with Image.open(path) as image:
            sources[key] = image.copy()
    image = compose_atlas(sources, layout)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)
    return {'output': str(destination.relative_to(ROOT)), 'dimensions': list(image.size),
            'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
            'alpha_extrema': list(image.getchannel('A').getextrema()), 'original_game_pixels': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('layout', nargs='?', type=Path, default=ROOT / 'assets/meadows/roof-atlas-layout.json')
    print(json.dumps(build(parser.parse_args().layout), indent=2))
