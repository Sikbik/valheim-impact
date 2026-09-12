"""Remove named PNG/WebP metadata into a new file without re-encoding artwork.

Usage: python tools/clean_image_metadata.py INPUT --output NEWFILE

PNG text, EXIF and caBX chunks and WebP EXIF/XMP chunks are removed. Other
chunks, including compressed image data and color profiles, are preserved.
WebP RIFF sizes and the VP8X metadata flags are updated. Inputs are limited to
64 MiB and 100,000 chunks. Container validation does not decode image bitstreams
or certify that remaining chunks contain no private information. Keep the raw
source private, review the cleaned file, then record its actual output hash.

Container references:
https://www.w3.org/TR/png-3/
https://developers.google.com/speed/webp/docs/riff_container
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import zlib

MAX_BYTES = 64 * 1024 * 1024
MAX_CHUNKS = 100000
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
PNG_METADATA = {b'tEXt', b'zTXt', b'iTXt', b'eXIf', b'caBX'}
WEBP_METADATA = {b'EXIF', b'XMP '}


def _png(data):
    output, removed = [PNG_SIGNATURE], set()
    offset, count, image_bytes = 8, 0, 0
    header = palette = ended = image_seen = image_ended = transparency = False
    color = depth = palette_entries = None
    while offset < len(data):
        count += 1
        if count > MAX_CHUNKS or len(data) - offset < 12:
            raise ValueError('Truncated PNG or chunk count exceeds limit')
        size = struct.unpack_from('>I', data, offset)[0]
        kind = data[offset + 4:offset + 8]
        end = offset + size + 12
        if (size > 0x7fffffff or end > len(data) or
                any(not (65 <= c <= 90 or 97 <= c <= 122) for c in kind) or kind[2] & 32):
            raise ValueError('Invalid PNG chunk header or length')
        payload = data[offset + 8:end - 4]
        if zlib.crc32(kind + payload) != struct.unpack_from('>I', data, end - 4)[0]:
            raise ValueError('PNG chunk CRC mismatch')
        if not header and kind != b'IHDR':
            raise ValueError('PNG must begin with IHDR')
        if kind == b'IHDR':
            if header or size != 13:
                raise ValueError('Invalid or duplicate PNG header')
            width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', payload)
            depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
            if (not 1 <= width <= 0x7fffffff or not 1 <= height <= 0x7fffffff or
                    depth not in depths.get(color, ()) or compression != 0 or filtering != 0 or interlace not in (0, 1)):
                raise ValueError('Unsupported or invalid PNG image header')
            header = True
        elif kind == b'PLTE':
            if palette or image_seen or transparency or color in (0, 4) or not 3 <= size <= 768 or size % 3:
                raise ValueError('Invalid PNG palette or chunk order')
            palette_entries = size // 3
            if color == 3 and palette_entries > 1 << depth:
                raise ValueError('PNG palette exceeds indexed bit depth')
            palette = True
        elif kind == b'tRNS':
            if (transparency or image_seen or color in (4, 6) or
                    (color == 0 and size != 2) or (color == 2 and size != 6) or
                    (color == 3 and (not palette or not 1 <= size <= palette_entries))):
                raise ValueError('Invalid PNG transparency or chunk order')
            transparency = True
        elif kind == b'IDAT':
            if image_ended or (color == 3 and not palette):
                raise ValueError('Invalid PNG image chunk order')
            image_seen = True
            image_bytes += size
        elif kind == b'IEND':
            if size or not image_seen or not image_bytes or end != len(data):
                raise ValueError('Invalid PNG end or missing image data')
            ended = True
        elif not kind[0] & 32:
            raise ValueError('Unknown critical PNG chunk')
        if image_seen and kind != b'IDAT':
            image_ended = True
        if kind in PNG_METADATA:
            removed.add(kind.decode('ascii'))
        else:
            output.append(data[offset:end])
        offset = end
    if not header or not ended:
        raise ValueError('PNG lacks mandatory chunks')
    return b''.join(output), sorted(removed)


def _riff_chunks(data, count):
    offset, chunks = 0, []
    while offset < len(data):
        count[0] += 1
        if count[0] > MAX_CHUNKS or len(data) - offset < 8:
            raise ValueError('Truncated WebP or chunk count exceeds limit')
        kind = data[offset:offset + 4]
        size = struct.unpack_from('<I', data, offset + 4)[0]
        end = offset + 8 + size
        padded_end = end + size % 2
        if (padded_end > len(data) or any(not 32 <= c <= 126 for c in kind) or
                (size % 2 and data[end] != 0)):
            raise ValueError('Invalid WebP chunk length or padding')
        chunks.append((kind, data[offset + 8:end], data[offset:padded_end]))
        offset = padded_end
    return chunks


def _image_header(kind, payload):
    if kind == b'VP8L':
        if len(payload) < 6 or payload[0] != 0x2f:
            raise ValueError('Invalid WebP lossless image header')
        value = int.from_bytes(payload[1:5], 'little')
        if value >> 29:
            raise ValueError('Unsupported WebP lossless version')
        return (value & 0x3fff) + 1, ((value >> 14) & 0x3fff) + 1
    if len(payload) < 10 or payload[0] & 1 or payload[3:6] != b'\x9d\x01\x2a':
        raise ValueError('Invalid WebP lossy image header')
    width, height = struct.unpack_from('<HH', payload, 6)
    width, height = width & 0x3fff, height & 0x3fff
    if not width or not height:
        raise ValueError('Invalid WebP lossy dimensions')
    return width, height


def _frame(chunks):
    alpha = False
    image = None
    for kind, payload, _ in chunks:
        if kind == b'ALPH':
            if alpha or image is not None or not payload or payload[0] & 0xc0 or payload[0] & 3 > 1:
                raise ValueError('Invalid WebP alpha chunk')
            alpha = True
        elif kind in (b'VP8 ', b'VP8L'):
            if image is not None or (alpha and kind == b'VP8L'):
                raise ValueError('Invalid duplicate WebP image or alpha combination')
            image = _image_header(kind, payload)
        elif kind in (b'VP8X', b'ICCP', b'ANIM', b'ANMF') or kind in WEBP_METADATA:
            raise ValueError('Unexpected WebP frame subchunk')
    if image is None:
        raise ValueError('WebP frame lacks image data')
    return image, alpha


def _webp(data):
    if len(data) < 12 or data[8:12] != b'WEBP' or struct.unpack_from('<I', data, 4)[0] != len(data) - 8:
        raise ValueError('Invalid WebP RIFF signature or size')
    count = [0]
    chunks = _riff_chunks(data[12:], count)
    if not chunks:
        raise ValueError('WebP lacks image chunks')
    kinds = [kind for kind, _, _ in chunks]
    extended = kinds[0] == b'VP8X'
    for singleton in (b'VP8X', b'ICCP', b'EXIF', b'XMP ', b'ANIM'):
        if kinds.count(singleton) > 1:
            raise ValueError('Duplicate WebP singleton chunk')
    if not extended:
        if any(kind in (b'VP8X', b'ICCP', b'ANIM', b'ANMF', b'ALPH') or kind in WEBP_METADATA for kind in kinds):
            raise ValueError('WebP extended features require a leading VP8X')
        _frame(chunks)
        return data, []
    header = chunks[0][1]
    if len(header) != 10 or header[0] & 0xc1 or any(header[1:4]):
        raise ValueError('Invalid WebP extended header')
    flags = header[0]
    canvas = (1 + int.from_bytes(header[4:7], 'little'), 1 + int.from_bytes(header[7:10], 'little'))
    if canvas[0] * canvas[1] > 0xffffffff:
        raise ValueError('WebP canvas exceeds container limits')
    for flag, kind in ((0x20, b'ICCP'), (0x08, b'EXIF'), (0x04, b'XMP '), (0x02, b'ANIM')):
        if bool(flags & flag) != (kind in kinds):
            raise ValueError('WebP feature flags differ from chunks')
    if b'ICCP' in kinds and any(kind in (b'ANIM', b'ANMF', b'ALPH', b'VP8 ', b'VP8L')
                                for kind in kinds[:kinds.index(b'ICCP')]):
        raise ValueError('WebP color profile follows image data')
    image_chunks = [(kind, payload, raw) for kind, payload, raw in chunks[1:]
                    if kind not in WEBP_METADATA and kind != b'ICCP']
    if flags & 2:
        frames = 0
        animation_seen = False
        for kind, payload, _ in image_chunks:
            if kind == b'ANIM':
                if len(payload) != 6 or frames:
                    raise ValueError('Invalid WebP animation control')
                animation_seen = True
            elif kind == b'ANMF':
                if not animation_seen or len(payload) < 16 or payload[15] & 0xfc:
                    raise ValueError('Invalid WebP animation frame')
                left = 2 * int.from_bytes(payload[:3], 'little')
                top = 2 * int.from_bytes(payload[3:6], 'little')
                size = (1 + int.from_bytes(payload[6:9], 'little'), 1 + int.from_bytes(payload[9:12], 'little'))
                dimensions, alpha = _frame(_riff_chunks(payload[16:], count))
                if dimensions != size or left + size[0] > canvas[0] or top + size[1] > canvas[1] or (alpha and not flags & 0x10):
                    raise ValueError('WebP animation frame differs from canvas or alpha flags')
                frames += 1
            elif kind in (b'VP8X', b'ALPH', b'VP8 ', b'VP8L'):
                raise ValueError('Unexpected image outside a WebP animation frame')
        if not frames:
            raise ValueError('WebP animation has no frames')
    else:
        dimensions, alpha = _frame(image_chunks)
        if dimensions != canvas or (alpha and not flags & 0x10):
            raise ValueError('WebP image differs from canvas or alpha flags')
    kept, removed = [], set()
    for kind, payload, raw in chunks:
        if kind in WEBP_METADATA:
            removed.add(kind.decode('ascii'))
        elif kind == b'VP8X':
            kept.append(raw[:8] + bytes([payload[0] & ~0x0c]) + raw[9:])
        else:
            kept.append(raw)
    body = b'WEBP' + b''.join(kept)
    return b'RIFF' + struct.pack('<I', len(body)) + body, sorted(removed)


def clean_bytes(data):
    """Validate a bounded container and preserve every non-removed chunk payload."""
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise ValueError('Input exceeds 64 MiB or is not bytes')
    if data.startswith(PNG_SIGNATURE):
        output, removed = _png(data)
        return output, 'PNG', removed
    if data.startswith(b'RIFF'):
        output, removed = _webp(data)
        return output, 'WebP', removed
    raise ValueError('Only PNG and WebP containers are supported')


def _path(value):
    path = Path(value).expanduser().absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('Source and output paths must not follow symlinks')
    if any(not parent.is_dir() for parent in path.parents):
        raise ValueError('Every parent directory must already exist')
    return path


def clean_file(source, output):
    """Read a regular source and exclusively create a distinct cleaned output."""
    created = False
    target = None
    identity = None
    try:
        source, target = _path(source), _path(output)
        if not source.is_file():
            raise ValueError('Source must be a regular file')
        if target.exists() or source.resolve() == target.resolve():
            raise ValueError('Output must be a distinct new file')
        descriptor = os.open(source, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            state = os.fstat(stream.fileno())
            if not stat.S_ISREG(state.st_mode) or state.st_size > MAX_BYTES:
                raise ValueError('Source must be regular and no larger than 64 MiB')
            data = stream.read(MAX_BYTES + 1)
        cleaned, format_name, removed = clean_bytes(data)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        created = True
        with os.fdopen(descriptor, 'wb') as stream:
            state = os.fstat(stream.fileno())
            identity = state.st_dev, state.st_ino
            stream.write(cleaned)
            stream.flush()
            os.fsync(stream.fileno())
        return {'schema_version': 1, 'format': format_name,
                'source_sha256': hashlib.sha256(data).hexdigest(),
                'output_sha256': hashlib.sha256(cleaned).hexdigest(),
                'source_bytes': len(data), 'output_bytes': len(cleaned),
                'removed_chunk_types': removed, 'pixel_decoding_performed': False}
    except BaseException as error:
        if created and target is not None and identity is not None:
            try:
                current = target.lstat()
                if (current.st_dev, current.st_ino) == identity:
                    target.unlink()
            except OSError:
                pass
        if isinstance(error, OSError):
            raise ValueError('File access failed; source and any pre-existing output were preserved') from None
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', required=True, type=Path, help='Distinct output file, which must not exist')
    args = parser.parse_args()
    try:
        result = clean_file(args.input, args.output)
    except ValueError as error:
        parser.exit(2, 'Metadata cleanup refused: ' + str(error) + '\n')
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
