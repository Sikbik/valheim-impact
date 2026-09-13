"""Reproduce mushroom albedo bases from the hash-verified owned atlas source.

The atlas already contains the fitted cap, stalk and underside colors. This
helper reads no geometry, masks or other images. Use requirements-assets.txt;
the recorded PNG encoder is Pillow 12.3.0 with zlib 1.3.2.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path

from PIL import Image


SOURCE = ('assets/meadows/mushroom-atlas-source-v1.png',
          'dff9af0a61c0e6da9f28ab66b3695f15c04d3fff10cd4acaab11bbbe8dadad34')
OUTPUTS = (
    ('mushroom-atlas-hd-v1.png',
     '94bc997a44d0a5de8fa7e38c37f8d7f87952c6d21c42d2c2b4fd2d64ac6ec58d'),
    ('mushroom-atlas-balanced-v1.png',
     '9c40bc014fbeeda426b8fcc25dcdd06afdd63f58650bc31bcb2c2434b3c77a94'),
)


def owned_source(root):
    relative, expected = SOURCE
    path = Path(root).absolute() / relative
    if any(parent.is_symlink() for parent in [path, *path.parents]):
        raise ValueError('Linked input paths are not supported')
    if not path.is_file():
        raise ValueError('Owned atlas hash mismatch: ' + relative)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('Owned atlas hash mismatch: ' + relative)
    with Image.open(io.BytesIO(data)) as image:
        if image.format != 'PNG' or image.mode != 'RGBA' or image.size != (2048, 2048):
            raise ValueError('Owned atlas format, mode or dimensions differ')
        if image.getextrema()[3] != (255, 255):
            raise ValueError('Owned atlas alpha must be uniformly opaque')
        # Reconstruct pixels without carrying ancillary source metadata.
        return Image.frombytes('RGBA', image.size, image.tobytes())


def reproduce(root, output_dir):
    output = Path(output_dir).absolute()
    if any(path.is_symlink() for path in [output, *output.parents]):
        raise ValueError('Linked output paths are not supported')
    for name, _ in OUTPUTS:
        path = output / name
        if path.exists() or path.is_symlink():
            raise ValueError('Output already exists or is linked: ' + name)
    source = owned_source(root)
    encoded = []
    # Both bases sample the 2048 source independently. Balanced does not resize HD.
    for size, (name, expected) in zip((512, 256), OUTPUTS):
        image = source.resize((size, size), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format='PNG', optimize=False, compress_level=6)
        data = buffer.getvalue()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('PNG bytes differ from the pinned recipe; check dependency versions')
        encoded.append((name, data, expected))
    # Verify both encoded files before creating either output.
    output.mkdir(parents=True, exist_ok=True)
    for name, data, _ in encoded:
        with (output / name).open('xb') as stream:
            stream.write(data)
    return [{'name': name, 'sha256': digest} for name, _, digest in encoded]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='Repository root')
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='Destination for both fitted atlas PNGs')
    args = parser.parse_args()
    try:
        result = reproduce(args.root, args.output_dir)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
