"""Reproduce the owned flint surfaces from their hash-verified RGB parent.

Use requirements-assets.txt. The recorded PNG encoder uses Pillow 12.3.0 and
zlib 1.3.2; both output hashes are checked before either file is created.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform

import numpy as np
from PIL import Image

if __package__:
    from .asset_pipeline import periodic_rgb, quantize, resize_float
else:
    from asset_pipeline import periodic_rgb, quantize, resize_float


SOURCE = ('assets/meadows/flint-surface-source-v1.png',
          'e442822a1195d25266b0a1b34f2a3c8c604630c7454eb18729088a986725a7f5')
OUTPUTS = (
    ('flint-hd-v1.png',
     '87bb36cb4fd07085d5dad411d2371a02366452631da52caaebe4325f82e94dc3'),
    ('flint-balanced-v1.png',
     'ba062c317bfd97e5a4d32a18bf3518fb8cc78692bdbf300087dfb016075f7a47'),
)
RGB_HASHES = {
    'flint-hd-v1.png': '81279f252e904a3e098453af86df0bc437cf43378fa43ba41a9a8a51908c0867',
    'flint-balanced-v1.png': '0c182c96ed300198ddf85795ba0a929fec03e6bec4590bf82c38a16fc30e6aac',
}


def owned_source(root):
    relative, expected = SOURCE
    path = Path(root).absolute() / relative
    if any(parent.is_symlink() for parent in [path, *path.parents]):
        raise ValueError('Linked input paths are not supported')
    if not path.is_file():
        raise ValueError('Owned parent hash mismatch: ' + relative)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('Owned parent hash mismatch: ' + relative)
    with Image.open(io.BytesIO(data)) as image:
        if image.mode != 'RGB' or image.size != (1254, 1254):
            raise ValueError('Owned parent mode or dimensions differ')
        return Image.frombytes('RGB', image.size, image.tobytes())


def fit_balanced(hd):
    """Opaque linear-light BOX mip with explicit power evaluation precision."""
    rgb = np.asarray(hd, dtype=np.float64) / 255
    linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    small = resize_float(linear, (hd.width // 2, hd.height // 2))
    # Keep the reviewed float32 exponent and subsequent float32 operations;
    # evaluate power in float64 before explicitly rounding it back to float32.
    powered = (small.astype(np.float64) ** float(np.float32(1 / 2.4))).astype(np.float32)
    rgb = np.where(small <= .0031308, small * 12.92, 1.055 * powered - .055)
    return Image.fromarray(quantize(rgb))


def fitted_images(source):
    parent = Image.fromarray(periodic_rgb(np.asarray(source)))
    size = parent.width
    # Surround one complete period with periodic filter support on all sides.
    padded = Image.new('RGB', (size * 3, size * 3))
    for y in range(3):
        for x in range(3):
            padded.paste(parent, (x * size, y * size))
    hd = padded.resize((1024, 1024), Image.Resampling.LANCZOS,
                       box=(size, size, size * 2, size * 2))
    balanced = fit_balanced(hd)
    return hd, balanced


def reproduce(root, output_dir):
    output = Path(output_dir).absolute()
    if any(path.is_symlink() for path in [output, *output.parents]):
        raise ValueError('Linked output paths are not supported')
    for name, _ in OUTPUTS:
        path = output / name
        if path.exists() or path.is_symlink():
            raise ValueError('Output already exists or is linked: ' + name)
    images = fitted_images(owned_source(root))
    encoded = []
    for image, (name, expected) in zip(images, OUTPUTS):
        buffer = io.BytesIO()
        image.save(buffer, format='PNG', optimize=False, compress_level=6)
        data = buffer.getvalue()
        png_hash = hashlib.sha256(data).hexdigest()
        rgb_hash = hashlib.sha256(image.tobytes()).hexdigest()
        if png_hash != expected or rgb_hash != RGB_HASHES[name]:
            details = dict(output=name, pixels_match=rgb_hash == RGB_HASHES[name],
                           png_matches=png_hash == expected,
                           expected_rgb_sha256=RGB_HASHES[name], actual_rgb_sha256=rgb_hash,
                           expected_png_sha256=expected, actual_png_sha256=png_hash,
                           versions=dict(python=platform.python_version(), numpy=np.__version__,
                                         Pillow=Image.__version__, pillow_zlib=Image.core.zlib_version,
                                         pillow_zlib_ng=getattr(Image.core, 'zlib_ng_version', None)))
            raise ValueError('Fitted output differs from the pinned recipe: ' + json.dumps(details, sort_keys=True))
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
                        help='New destination for both fitted surface PNGs')
    args = parser.parse_args()
    try:
        results = reproduce(args.root, args.output_dir)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
