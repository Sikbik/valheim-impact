"""Reproduce the owned raspberry atlases from their hash-verified parents.

Use requirements-assets.txt. The recorded PNG encoder is Pillow 12.3.0 with
zlib 1.3.2. Both output hashes are checked before either output is written.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates


SOURCES = {
    'red': ('assets/meadows/raspberry-surface-source-v1.png',
            'fc77fa48534dcdc3dde50e23524e6fd7b0444e663df273c5bda5e4655d43a43d', 'RGB'),
    'leaf': ('assets/meadows/dandelion-leaf-source-v1.png',
             '0b585efae5dce086cff61acd100a2c46295dd7d81a52bcaa1090a7e5268758ab', 'RGBA'),
}
OUTPUTS = (
    ('raspberry-atlas-hd-v1.png',
     'd97655a5ff683f41c6b740343444b8abb92066f78d91495f451c4c680a9f4805'),
    ('raspberry-atlas-balanced-v1.png',
     '43cd1cb387fba4c0734afa276a5ce918f95e6f84b598a0c87a0eb8b0173b39cd'),
)
MASTER_SIZE = 2048


def owned_source(root, relative, expected_hash, mode):
    path = Path(root).absolute() / relative
    if any(parent.is_symlink() for parent in [path, *path.parents]):
        raise ValueError('Linked input paths are not supported')
    if not path.is_file():
        raise ValueError('Owned parent hash mismatch: ' + relative)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError('Owned parent hash mismatch: ' + relative)
    with Image.open(io.BytesIO(data)) as image:
        if image.mode != mode or image.size != (1254, 1254):
            raise ValueError('Owned parent mode or dimensions differ: ' + relative)
        return np.array(Image.frombytes(mode, image.size, image.tobytes()))


def smoothstep(values):
    values = np.clip(values, 0, 1)
    return values * values * (3 - 2 * values)


def reflected_coordinates(values, length):
    folded = np.mod(values, 2 * (length - 1))
    return np.where(folded <= length - 1, folded, 2 * (length - 1) - folded)


def sample_rgb(pixels, x, y):
    shape = np.broadcast_shapes(x.shape, y.shape)
    x = np.broadcast_to(x, shape)
    y = np.broadcast_to(y, shape)
    return np.stack([
        map_coordinates(pixels[:, :, channel].astype(np.float64), [y, x],
                        order=1, mode='nearest', prefilter=False)
        for channel in range(3)
    ], axis=-1)


def match_red_edges(pixels, width):
    # Pair opposite edge rows/columns before adding the green atlas regions.
    for axis in (1, 0):
        for distance in range(width):
            first = [slice(None)] * 3
            last = [slice(None)] * 3
            first[axis] = distance
            last[axis] = -1 - distance
            first, last = tuple(first), tuple(last)
            low, high = pixels[first].copy(), pixels[last].copy()
            middle = (low + high) / 2
            weight = (1 - distance / width) ** 2
            pixels[first] = low * (1 - weight) + middle * weight
            pixels[last] = high * (1 - weight) + middle * weight
    return pixels


def fitted_images(red, leaf):
    u = (np.arange(MASTER_SIZE, dtype=np.float64)[None, :] + .5) / MASTER_SIZE
    v = 1 - (np.arange(MASTER_SIZE, dtype=np.float64)[:, None] + .5) / MASTER_SIZE
    # Uniform scaling preserves the source cell proportions before surface mapping.
    factor = 1254 / .8
    source_x = reflected_coordinates(627 + (u - .193187) * factor, 1254)
    source_y = reflected_coordinates((.792281 - v) * factor, 1254)
    rgb = sample_rgb(red, source_x, source_y)
    match_red_edges(rgb, 41)

    for x0, y0, x1, y1 in ((616, 256, 635, 1121), (626, 350, 671, 851)):
        if leaf[y0:y1, x0:x1, 3].min() < 250:
            raise ValueError('Owned leaf interior is insufficiently opaque')

    # Analytic placement constants retain the reviewed neck and shaft alignment.
    neck = np.interp(
        u.ravel(), [.1686979979276657, .1859789937734604, .2022390067577362],
        [.791949987411499, .7842710018157959, .7922809720039368])[None, :]
    horizontal = smoothstep((u - .130) / .020) * smoothstep((.242 - u) / .020)
    stem_weight = horizontal * smoothstep((v - neck + .002) / .004)
    stem_weight = np.maximum(
        stem_weight, horizontal * smoothstep((.010 - v) / .010))
    stem_y = 1120 - np.clip(
        (np.where(v < .010, v + 1, v) - .7842710018157959)
        / (.9868990182876587 - .7842710018157959), 0, 1) * 864
    stem_x = 616 + np.clip(
        (u - .1686979979276657) / (.2022390067577362 - .1686979979276657),
        0, 1) * 18
    stem = sample_rgb(leaf, stem_x, stem_y)
    rgb = rgb * (1 - stem_weight[:, :, None]) + stem * stem_weight[:, :, None]

    # Continue calyx padding across the vertical Repeat boundary.
    wrapped_v = np.where(v > .9, v - 1, v)
    calyx_weight = (smoothstep((u - .355) / .020)
                    * smoothstep((.645 - u) / .030)
                    * smoothstep((.145 - wrapped_v) / .030)
                    * smoothstep((wrapped_v + .030) / .020))
    spine0 = np.interp(
        u.ravel(), [.39947399497032166, .40104201436042786,
                    .48827099800109863, .5643010139465332],
        [.090324, .090324, .0921740010380745, .0921740010380745])[None, :]
    spine1 = np.interp(
        u.ravel(), [.39947399497032166, .5049660205841064, .579276978969574],
        [.04447700083255768, .04030199907720089, .04447700083255768])[None, :]
    first_band = wrapped_v >= .05757800117135048
    along0 = np.clip(
        (u - .39947399497032166) / (.5643010139465332 - .39947399497032166), 0, 1)
    along1 = np.clip(
        (.5818300247192383 - u) / (.5818300247192383 - .39947399497032166), 0, 1)
    along = np.where(first_band, along0, along1)
    spine = np.where(first_band, spine0, spine1)
    calyx_y = 850 - along * 500
    calyx_x = 626 + 44 * np.clip((spine - wrapped_v) / .032, 0, 1)
    calyx = sample_rgb(leaf, calyx_x, calyx_y)
    rgb = rgb * (1 - calyx_weight[:, :, None]) + calyx * calyx_weight[:, :, None]

    rgba = np.dstack((np.rint(rgb).clip(0, 255).astype(np.uint8),
                      np.full((MASTER_SIZE, MASTER_SIZE), 255, np.uint8)))
    master = Image.fromarray(rgba)
    # Each final base is sampled from the full master, independently.
    return tuple(master.resize((size, size), Image.Resampling.LANCZOS)
                 for size in (512, 256))


def reproduce(root, output_dir):
    output = Path(output_dir).absolute()
    if any(path.is_symlink() for path in [output, *output.parents]):
        raise ValueError('Linked output paths are not supported')
    for name, _ in OUTPUTS:
        path = output / name
        if path.exists() or path.is_symlink():
            raise ValueError('Output already exists or is linked: ' + name)
    parents = {name: owned_source(root, *arguments)
               for name, arguments in SOURCES.items()}
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
