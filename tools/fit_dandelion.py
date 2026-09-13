"""Reproduce both owned dandelion atlases from their hash-verified RGBA parents.

Use the dependencies in requirements-assets.txt. The recorded PNG encoder uses
Pillow 12.3.0 and zlib 1.3.2; both output hashes are checked before writing.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


SOURCES = {
    'head': ('assets/meadows/dandelion-head-source-v1.png',
             'c635865c6676eaf48053e3d49f9c99a6b8e9ebcce5ab26cc36de691cf5e0694b'),
    'leaf': ('assets/meadows/dandelion-leaf-source-v1.png',
             '0b585efae5dce086cff61acd100a2c46295dd7d81a52bcaa1090a7e5268758ab'),
}
OUTPUTS = (
    ('dandelion-atlas-hd-v1.png',
     '17028ec8e889e8306b9a1d0c489be650c190fc6b6e3ab3cec3fade8fd27fa1d4'),
    ('dandelion-atlas-balanced-v1.png',
     '639b491a193d2883d324cb4cc01520712759d870c578dee3882537f35d1af31f'),
)


def owned_source(root, relative, expected_hash):
    path = Path(root).absolute() / relative
    if any(parent.is_symlink() for parent in [path, *path.parents]):
        raise ValueError('Linked input paths are not supported')
    if not path.is_file():
        raise ValueError('Owned parent hash mismatch: ' + relative)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError('Owned parent hash mismatch: ' + relative)
    # Decode exactly the bytes just verified, then discard inherited metadata.
    with Image.open(io.BytesIO(data)) as image:
        if image.mode != 'RGBA' or image.size != (1254, 1254):
            raise ValueError('Owned parent mode or dimensions differ: ' + relative)
        return Image.frombytes('RGBA', image.size, image.tobytes())


def clean_component(image):
    pixels = np.array(image)
    labels, _ = ndimage.label(pixels[:, :, 3] > 0,
                             structure=np.ones((3, 3), dtype=np.uint8))
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    if np.count_nonzero(sizes > 32) != 1:
        raise ValueError('Owned alpha must contain exactly one retained component')
    detached = np.flatnonzero((sizes > 0) & (sizes <= 32))
    pixels[np.isin(labels, detached), 3] = 0
    return pixels


def alpha_remap(alpha):
    # Preserve the passing silhouette at byte 36 and reach opaque at byte 192.
    return np.where(alpha < 36, 0, np.rint(np.clip(
        36 + (alpha.astype(np.float64) - 36) * 219 / 156, 36, 255))).astype(np.uint8)


def fitted_images(head, leaf):
    processed = {'head': clean_component(head), 'leaf': clean_component(leaf)}
    atlas = np.zeros((512, 512, 4), dtype=np.uint8)
    for name, x, y, width, height in (
            ('head', 64, 51, 123, 138), ('leaf', 260, 28, 169, 438)):
        pixels = processed[name]
        yy, xx = np.where(pixels[:, :, 3] > 0)
        crop = (int(xx.min()), int(yy.min()), int(xx.max() + 1), int(yy.max() + 1))
        shape = Image.fromarray(pixels).crop(crop)
        resized = shape.convert('RGBa').resize(
            (width, height), Image.Resampling.LANCZOS).convert('RGBA')
        atlas[y:y + height, x:x + width] = np.array(resized)

    # Alpha-weighted row colors come only from the retained owned leaf midrib.
    strip = processed['leaf'][256:1120, 616:635]
    alpha = strip[:, :, 3].astype(np.float64)
    if alpha.min() < 250:
        raise ValueError('Owned midrib source is insufficiently opaque')
    profile = np.rint((strip[:, :, :3].astype(np.float64) * alpha[:, :, None]).sum(1)
                      / alpha.sum(1)[:, None]).clip(0, 255).astype(np.uint8)
    profile = np.array(Image.fromarray(profile[:, None, :]).resize(
        (1, 512), Image.Resampling.BILINEAR))[::-1, 0]
    # Reverse tip-to-root source rows into the stem's root-to-flower orientation.
    atlas[:, 440:496, :3] = profile[:, None, :]
    atlas[:, 440:496, 3] = 255

    positive = atlas[:, :, 3] >= 128
    distance, indices = ndimage.distance_transform_edt(~positive, return_indices=True)
    pad = (~positive) & (distance <= 8)
    atlas[pad, :3] = atlas[indices[0][pad], indices[1][pad], :3]
    atlas[:, :, 3] = alpha_remap(atlas[:, :, 3])
    hd = Image.fromarray(atlas)
    balanced = np.array(hd.resize((256, 256), Image.Resampling.LANCZOS))
    balanced[:, :, 3] = alpha_remap(balanced[:, :, 3])
    return hd, Image.fromarray(balanced)


def reproduce(root, output_dir):
    output = Path(output_dir).absolute()
    if any(path.is_symlink() for path in [output, *output.parents]):
        raise ValueError('Linked output paths are not supported')
    for name, _ in OUTPUTS:
        path = output / name
        if path.exists() or path.is_symlink():
            raise ValueError('Output already exists or is linked: ' + name)
    parents = {name: owned_source(root, relative, expected)
               for name, (relative, expected) in SOURCES.items()}
    encoded = []
    for image, (name, expected) in zip(fitted_images(**parents), OUTPUTS):
        buffer = io.BytesIO()
        image.save(buffer, format='PNG', optimize=False, compress_level=6)
        data = buffer.getvalue()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('PNG bytes differ from the pinned recipe; check dependency versions')
        encoded.append((name, data, expected))
    output.mkdir(parents=True, exist_ok=True)
    for name, data, _ in encoded:
        # Exclusive creation also refuses a leaf that appeared after preflight.
        with (output / name).open('xb') as stream:
            stream.write(data)
    return [{'name': name, 'sha256': digest} for name, _, digest in encoded]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='Repository root')
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='New destination for both fitted atlas PNGs')
    args = parser.parse_args()
    try:
        results = reproduce(args.root, args.output_dir)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
