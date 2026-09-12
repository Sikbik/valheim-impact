"""Deterministic authored studies. Never reads the game or deploys to it."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def safe_destination(root, relative):
    """Preflight a contained file path, including every existing ancestor."""
    root = Path(root).absolute()
    relative = Path(relative)
    if relative.is_absolute() or not relative.parts or any(p in ('.', '..') for p in relative.parts):
        raise ValueError('Expected a contained relative file')
    if relative.suffix.lower() not in ('.png', '.json', '.dds', '.dll', '.md'):
        raise ValueError('File type is not allowlisted')
    for part in [root, *root.parents]:
        if part.is_symlink():
            raise ValueError('Linked root is forbidden')
    path = root
    for part in relative.parts:
        path /= part
        if path.is_symlink():
            raise ValueError('Symlinks are forbidden')
    if path.exists() and not path.is_file():
        raise ValueError('Expected a file destination: ' + str(path))
    return path


def safe_file(root, relative):
    """Only regular, explicitly named owned files, with no linked ancestors."""
    path = safe_destination(root, relative)
    if not path.is_file():
        raise ValueError('Expected a regular file: ' + str(path))
    return path


def quantize(values):
    return np.rint(np.clip(values, 0, 1) * 255).astype(np.uint8)


def periodic_rgb(rgb):
    result = rgb.astype(np.float64).copy()
    for axis in (0, 1):
        values = np.swapaxes(result, 0, axis)
        left, right = values[0].copy(), values[-1].copy()
        target = (left + right) / 2
        band = min(24, max(1, len(values) // 4))
        for i in range(band):
            weight = (1 - i / band) ** 2
            values[i] += (target - left) * weight
            values[-1-i] += (target - right) * weight
        values[-1] = values[0]
    return np.rint(np.clip(result, 0, 255)).astype(np.uint8)


def fit_albedo(image, size, alpha=None, periodic=False):
    """Resample an owned tile, or apply an exact source-sized alpha mask.

    Game atlases must be fitted region by region outside this tile-only function.
    Alpha is never guessed from a checkerboard or luminance.
    """
    if alpha is not None and alpha.size != tuple(size):
        raise ValueError('Authoritative alpha must already have the target dimensions')
    pixels = np.array(image.convert('RGBA').resize(size, Image.Resampling.LANCZOS))
    if periodic:
        pixels[:, :, :3] = periodic_rgb(pixels[:, :, :3])
    if alpha is not None:
        pixels[:, :, 3] = np.asarray(alpha.convert('L'))
    return Image.fromarray(pixels)


def normal_from_height(height, strength=0.15, periodic=True):
    """PNG rows go down; Unity tangent V goes up. Return linear DXT5nm RGBA."""
    height = np.asarray(height, dtype=np.float64)
    dx = (np.roll(height, -1, 1) - np.roll(height, 1, 1)) * strength / 2
    dy = (np.roll(height, -1, 0) - np.roll(height, 1, 0)) * strength / 2
    if not periodic:
        dx[:, (0, -1)] = 0
        dy[(0, -1), :] = 0
    xyz = np.stack((-dx, dy, np.ones_like(height)), axis=-1)
    xyz /= np.linalg.norm(xyz, axis=-1, keepdims=True)
    packed = np.ones((*height.shape, 4))
    packed[:, :, 3] = xyz[:, :, 0] * .5 + .5
    packed[:, :, 1] = xyz[:, :, 1] * .5 + .5
    pixels = quantize(packed)
    if periodic:
        pixels = periodic_rgb(pixels)
    return Image.fromarray(pixels)


def resize_float(values, size):
    return np.stack([np.asarray(Image.fromarray(values[:, :, c].astype(np.float32)).resize(
        size, Image.Resampling.BOX)) for c in range(values.shape[2])], axis=2)


def mip_chain(image, role):
    if role not in ('albedo', 'normal'):
        raise ValueError('Unsupported texture role')
    result = [image.convert('RGBA')]
    while result[-1].size != (1, 1):
        current = result[-1]
        size = max(1, current.width // 2), max(1, current.height // 2)
        values = np.asarray(current, dtype=np.float64) / 255
        if role == 'albedo':
            rgb, alpha = values[:, :, :3], values[:, :, 3:4]
            linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
            small = resize_float(np.concatenate((linear * alpha, alpha), axis=2), size)
            alpha = small[:, :, 3:4]
            linear = small[:, :, :3] / np.maximum(alpha, 1e-8)
            rgb = np.where(linear <= .0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - .055)
            values = np.concatenate((rgb, alpha), axis=2)
        else:
            xy = values[:, :, (3, 1)] * 2 - 1
            z = np.sqrt(np.maximum(0, 1 - (xy * xy).sum(axis=2, keepdims=True)))
            xyz = resize_float(np.concatenate((xy, z), axis=2), size)
            xyz /= np.maximum(np.linalg.norm(xyz, axis=2, keepdims=True), 1e-8)
            values = np.ones((size[1], size[0], 4))
            values[:, :, 3] = xyz[:, :, 0] * .5 + .5
            values[:, :, 1] = xyz[:, :, 1] * .5 + .5
        result.append(Image.fromarray(quantize(values)))
    return result


def bc3_bytes(width, height):
    if width <= 0 or height <= 0:
        raise ValueError('Dimensions must be positive')
    total = 0
    while True:
        total += max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * 16
        if (width, height) == (1, 1):
            return total
        width, height = max(1, width // 2), max(1, height // 2)


def encode_dds(mips):
    """BC3/DXT5 DDS with complete mip payloads and top-down file rows."""
    if not mips or mips[-1].size != (1, 1):
        raise ValueError('A complete mip chain is required')
    payloads = []
    expected = mips[0].size
    for mip in mips:
        if mip.size != expected:
            raise ValueError('Invalid mip dimensions')
        expected = max(1, expected[0] // 2), max(1, expected[1] // 2)
        pixels = np.asarray(mip.convert('RGBA'))
        pad_y, pad_x = (-mip.height) % 4, (-mip.width) % 4
        padded = Image.fromarray(np.pad(pixels, ((0, pad_y), (0, pad_x), (0, 0)), mode='edge'))
        stream = io.BytesIO()
        padded.save(stream, format='DDS', pixel_format='DXT5')
        payloads.append(stream.getvalue()[128:])
    width, height = mips[0].size
    header = b'DDS ' + struct.pack('<7I', 124, 0xA1007, height, width, len(payloads[0]), 0, len(mips))
    header += bytes(44) + struct.pack('<II4s5I', 32, 4, b'DXT5', 0, 0, 0, 0, 0)
    header += struct.pack('<5I', 0x401008, 0, 0, 0, 0)
    result = header + b''.join(payloads)
    if len(result) != 128 + bc3_bytes(width, height):
        raise ValueError('Encoded chain size mismatch')
    return result


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def encode_unity_dds(mips):
    """Bottom-up BC3 storage for Unity LoadRawTextureData, same tangent signs."""
    return encode_dds([mip.transpose(Image.Transpose.FLIP_TOP_BOTTOM) for mip in mips])


def build(manifest_path):
    specification = json.loads(manifest_path.read_text())
    output = ROOT / 'build/staging/meadows'
    # Check the full output set before the first mutation, including links on
    # a later normal map or the final manifest, not just the first albedo.
    names = ['manifest.json', 'contact-sheet.png']
    identifiers = set()
    for asset in specification['assets']:
        if asset['id'] in identifiers or not asset['id'].replace('_', '').isalnum():
            raise ValueError('Invalid or duplicate asset identifier')
        identifiers.add(asset['id'])
        for role in ('albedo', 'normal'):
            names.extend(asset['id'] + '_' + role + suffix for suffix in ('.png', '.dds', '-unity.dds'))
    for name in names:
        safe_destination(ROOT, 'build/staging/meadows/' + name)
    output.mkdir(parents=True, exist_ok=True)
    records, thumbnails = [], []
    for asset in specification['assets']:
        source = safe_file(ROOT, asset['source'])
        image = Image.open(source).convert('RGBA')
        original_size = list(image.size)
        box = asset.get('crop_box', [0, 0, image.width, image.height])
        if not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
            raise ValueError('Crop outside actual image')
        cropped = image.crop(box)
        alpha = np.asarray(cropped)[:, :, 3]
        if asset['alpha_policy'] == 'cutout' and not (alpha.min() == 0 and alpha.max() == 255):
            raise ValueError('Cutout requires actual transparent and opaque pixels')
        if asset['alpha_policy'] == 'opaque' and not np.all(alpha == 255):
            raise ValueError('Opaque assets must be fully opaque')
        albedo = fit_albedo(cropped, tuple(asset['size']), periodic=asset['periodic'])
        height = np.asarray(albedo.convert('L'), dtype=np.float64) / 255
        normal = normal_from_height(height, asset['normal_strength'], asset['periodic'])
        for role, prepared in [('albedo', albedo), ('normal', normal)]:
            identifier = asset['id'] + '_' + role
            if not identifier.replace('_', '').isalnum():
                raise ValueError('Unsafe asset identifier')
            png = output / (identifier + '.png')
            dds = output / (identifier + '.dds')
            unity_dds = output / (identifier + '-unity.dds')
            prepared.save(png)
            mips = mip_chain(prepared, role)
            dds.write_bytes(encode_dds(mips))
            unity_dds.write_bytes(encode_unity_dds(mips))
            pixels = np.asarray(prepared)
            records.append(dict(id=identifier, source=asset['source'], source_sha256=sha256(source),
                source_dimensions=original_size, crop_box=box, dimensions=list(prepared.size),
                role=role, srgb=role == 'albedo', normal_encoding='DXT5nm A=X G=Y' if role == 'normal' else None,
                alpha_policy=asset['alpha_policy'] if role == 'albedo' else 'tangent_x',
                alpha_range=[int(pixels[:, :, 3].min()), int(pixels[:, :, 3].max())],
                mip_count=len(mips), compressed_payload_bytes=len(dds.read_bytes()) - 128,
                png=png.name, png_sha256=sha256(png), dds=dds.name, dds_sha256=sha256(dds),
                unity_dds=unity_dds.name, unity_dds_sha256=sha256(unity_dds),
                unity_row_order='bottom-up per mip; strip 128-byte DDS header',
                periodic=asset['periodic'], game_uv_validated=False, engine_validated=False))
        thumbnails.append((asset['id'], albedo))
    report = dict(schema_version=1, status='offline-authored-probe-only', assets=records,
        compressed_payload_bytes=sum(r['compressed_payload_bytes'] for r in records),
        native_bundles_built=False, vulkan_shader_support='untested', deployment='not-installed')
    (output / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    board = Image.new('RGB', (3 * 320, ((len(thumbnails) + 2) // 3) * 350), '#1c2429')
    draw = ImageDraw.Draw(board)
    for i, (label, im) in enumerate(thumbnails):
        x, y = i % 3 * 320, i // 3 * 350
        tile = im.resize((312, 312), Image.Resampling.LANCZOS)
        board.paste(tile, (x + 4, y + 4), tile.getchannel('A'))
        draw.text((x + 10, y + 324), label + ' | OFFLINE STUDY', fill='#dfd8bb')
    board.save(output / 'contact-sheet.png')
    print(json.dumps({'output': str(output), 'textures': len(records),
                      'compressed_payload_bytes': report['compressed_payload_bytes']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', nargs='?', default=str(ROOT / 'assets/meadows/prototype.json'))
    build(Path(parser.parse_args().manifest).resolve())
