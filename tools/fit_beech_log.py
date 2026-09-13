"""Reproduce the owned beech-log atlas from its two hash-verified RGB parents."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

BARK_PATH = 'assets/meadows/beech-bark-surface-v1.png'
ENDGRAIN_PATH = 'assets/meadows/beech-endgrain-source-v1.png'
BARK_SHA256 = '6fabc3e0c779f0ecbb43ce163d6378ae9a75b368ea4de1f6b8dbdd4e2b74acc4'
ENDGRAIN_SHA256 = 'd35e2f68f795bf3d60e8c9393ce5866dc109be57a0251e81d0d12dcc10b54735'
EXPECTED_ATLAS_SHA256 = '6b93f1e013aea0d18436af08f91b382cd5f040500892f3953686dde971718599'


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def owned_source(root, relative, expected_hash, expected_size):
    root = Path(root).absolute()
    path = root / relative
    if any(parent.is_symlink() for parent in [path, *path.parents]):
        raise ValueError('Linked input paths are not supported')
    if not path.is_file() or sha256(path) != expected_hash:
        raise ValueError('Owned parent hash mismatch: ' + relative)
    with Image.open(path) as image:
        if image.size != expected_size:
            raise ValueError('Owned parent dimensions differ: ' + relative)
        # A new image retains decoded RGB only, without inherited container metadata.
        return Image.frombytes('RGB', image.size, image.convert('RGB').tobytes())


def fitted_atlas(bark, endgrain):
    source = np.asarray(bark, dtype=np.float64).copy()
    band = 48
    endpoint = (source[:, :band].mean(axis=1) + source[:, -band:].mean(axis=1)) / 2
    for index in range(band):
        weight = (1 - index / (band - 1)) ** 2
        source[:, index] = (1 - weight) * source[:, index] + weight * endpoint
        source[:, -1-index] = (1 - weight) * source[:, -1-index] + weight * endpoint

    u_min, u_max = 0.008963000029325485, 0.5556619763374329
    v_min, v_max = 0.01092700008302927, 0.9265729784965515
    size = 1024
    u, v = np.meshgrid((np.arange(size) + 0.5) / size,
                       1 - (np.arange(size) + 0.5) / size)
    source_u = ((u - u_min) / (u_max - u_min)) % 1
    source_v = np.clip((v_max - v) / (v_max - v_min), 0, 1)
    x = source_u * (source.shape[1] - 1)
    y = source_v * (source.shape[0] - 1)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    x1 = np.minimum(x0 + 1, source.shape[1] - 1)
    y1 = np.minimum(y0 + 1, source.shape[0] - 1)
    fx, fy = (x - x0)[:, :, None], (y - y0)[:, :, None]
    rgb = ((source[y0, x0] * (1 - fx) + source[y0, x1] * fx) * (1 - fy)
           + (source[y1, x0] * (1 - fx) + source[y1, x1] * fx) * fy)
    atlas = Image.fromarray(np.rint(rgb).astype(np.uint8)).convert('RGBA')
    grain = ImageEnhance.Color(endgrain).enhance(0.72).resize(
        (148, 148), Image.Resampling.LANCZOS)
    for box in ((619, 25, 767, 173), (622, 222, 770, 370)):
        atlas.paste(grain, box)
    return atlas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='Repository root')
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='Destination for the source atlas and optional preview')
    parser.add_argument('--balanced-preview', action='store_true',
                        help='Also write the full-atlas 512px Lanczos derivative')
    args = parser.parse_args()
    bark = owned_source(args.root, BARK_PATH, BARK_SHA256, (1024, 1024))
    endgrain = owned_source(args.root, ENDGRAIN_PATH, ENDGRAIN_SHA256, (1254, 1254))
    output = args.output_dir.absolute()
    if any(path.is_symlink() for path in [output, *output.parents]):
        raise ValueError('Linked output paths are not supported')
    atlas_path = output / 'beech-log-atlas-v1.png'
    preview_path = output / 'beech-log-balanced-preview.png'
    for path in [atlas_path, preview_path] if args.balanced_preview else [atlas_path]:
        if path.exists() or path.is_symlink():
            raise ValueError('Output already exists or is linked: ' + path.name)
    atlas = fitted_atlas(bark, endgrain)
    output.mkdir(parents=True, exist_ok=True)
    atlas.save(atlas_path, format='PNG', optimize=True, compress_level=9)
    if sha256(atlas_path) != EXPECTED_ATLAS_SHA256:
        raise ValueError('PNG bytes differ from the pinned recipe; check encoder versions')
    results = [{'name': atlas_path.name, 'sha256': sha256(atlas_path)}]
    if args.balanced_preview:
        atlas.resize((512, 512), Image.Resampling.LANCZOS).save(
            preview_path, format='PNG', optimize=True, compress_level=9)
        results.append({'name': preview_path.name, 'sha256': sha256(preview_path)})
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
