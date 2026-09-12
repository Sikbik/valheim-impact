"""Container cleanup preserves encoded artwork and refuses unsafe output paths."""
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

try:
    from tools import clean_image_metadata as cleaner
except ImportError:
    cleaner = None

try:
    from PIL import Image, features
except ImportError:
    Image = None


PNG = b'\x89PNG\r\n\x1a\n'


def png_chunk(kind, payload=b''):
    return (struct.pack('>I', len(payload)) + kind + payload +
            struct.pack('>I', zlib.crc32(kind + payload)))


def png(extra=b''):
    return (PNG + png_chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)) +
            extra + png_chunk(b'IDAT', zlib.compress(b'\x00\xc8\x78\x28\x80')) + png_chunk(b'IEND'))


def riff_chunk(kind, payload):
    return kind + struct.pack('<I', len(payload)) + payload + (b'\x00' if len(payload) % 2 else b'')


def webp(*chunks):
    body = b'WEBP' + b''.join(chunks)
    return b'RIFF' + struct.pack('<I', len(body)) + body


def vp8x(flags=0):
    return riff_chunk(b'VP8X', bytes([flags]) + bytes(9))


# This fixture tests a valid lossless header and container, not bitstream decoding.
VP8L = riff_chunk(b'VP8L', b'\x2f' + bytes(4) + b'\x00')


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(cleaner, 'metadata cleaner is required')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'input.png'
        self.output = self.root / 'clean.png'

    def clean(self, data):
        self.source.write_bytes(data)
        before = self.source.stat().st_mtime_ns
        report = cleaner.clean_file(self.source, self.output)
        self.assertEqual(self.source.read_bytes(), data)
        self.assertEqual(self.source.stat().st_mtime_ns, before)
        self.assertEqual(report['source_sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(report['output_sha256'], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertFalse(report['pixel_decoding_performed'])
        return self.output.read_bytes(), report

    def test_png_removes_named_metadata_and_preserves_color_and_encoded_chunks(self):
        profile = png_chunk(b'iCCP', b'profile\x00\x00' + zlib.compress(b'profile bytes'))
        colors = png_chunk(b'gAMA', struct.pack('>I', 45455)) + profile
        kinds = [b'tEXt', b'zTXt', b'iTXt', b'eXIf', b'caBX']
        metadata = b''.join(png_chunk(kind, b'private value') for kind in kinds)
        result, report = self.clean(png(colors + metadata))
        self.assertEqual(result, png(colors))
        self.assertEqual(report['removed_chunk_types'], sorted(kind.decode() for kind in kinds))
        self.assertNotIn('private value', json.dumps(report))
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_already_clean_png_is_byte_identical_and_repeat_metadata_is_all_removed(self):
        result, report = self.clean(png())
        self.assertEqual(result, png())
        self.assertEqual(report['removed_chunk_types'], [])
        self.output.unlink()
        result, report = self.clean(png(png_chunk(b'tEXt', b'a') * 2))
        self.assertEqual(result, png())
        self.assertEqual(report['removed_chunk_types'], ['tEXt'])

    def test_png_invalid_crc_truncation_order_and_header_leave_no_output(self):
        valid = png()
        header = png_chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))
        idat = png_chunk(b'IDAT', zlib.compress(b'\0\0\0\0\0'))
        end = png_chunk(b'IEND')
        bad_crc = bytearray(valid); bad_crc[-1] ^= 1
        cases = [bytes(bad_crc), valid[:-1], valid + b'private tail', PNG + header + end,
                 PNG + idat + header + end, PNG + header * 2 + idat + end,
                 PNG + header + idat + png_chunk(b'IEND', b'x'),
                 PNG + header + idat + png_chunk(b'tEXt', b'x') + idat + end,
                 PNG + header + png_chunk(b'ABCD', b'x') + idat + end,
                 png()[:8] + struct.pack('>I', 0xffffffff) + b'IDAT',
                 PNG + png_chunk(b'IHDR', struct.pack('>IIBBBBB', 0, 1, 8, 6, 0, 0, 0)) + idat + end,
                 PNG + png_chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 1, 6, 0, 0, 0)) + idat + end]
        for data in cases:
            with self.subTest(data=data[:32]):
                self.source.write_bytes(data)
                with self.assertRaises(ValueError):
                    cleaner.clean_file(self.source, self.output)
                self.assertFalse(self.output.exists())
                self.assertEqual(self.source.read_bytes(), data)

    def test_palette_png_requires_palette_before_image_and_preserves_transparency(self):
        header = png_chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 3, 0, 0, 0))
        palette = png_chunk(b'PLTE', b'\x10\x20\x30')
        alpha = png_chunk(b'tRNS', b'\x80')
        pixels = png_chunk(b'IDAT', zlib.compress(b'\0\0'))
        valid = PNG + header + palette + alpha + pixels + png_chunk(b'IEND')
        result, _ = self.clean(valid)
        self.assertEqual(result, valid)
        self.output.unlink()
        for data in [valid.replace(palette, b''), valid.replace(palette + alpha, alpha + palette)]:
            self.source.write_bytes(data)
            with self.assertRaises(ValueError):
                cleaner.clean_file(self.source, self.output)
            self.assertFalse(self.output.exists())

    def test_webp_cleans_metadata_flags_and_riff_size_preserving_profile_payload(self):
        profile = riff_chunk(b'ICCP', b'profile bytes')
        image = webp(vp8x(0x2c), profile, VP8L, riff_chunk(b'EXIF', b'private'), riff_chunk(b'XMP ', b'value'))
        result, report = self.clean(image)
        self.assertEqual(result, webp(vp8x(0x20), profile, VP8L))
        self.assertEqual(report['format'], 'WebP')
        self.assertEqual(report['removed_chunk_types'], ['EXIF', 'XMP '])
        self.assertEqual(struct.unpack_from('<I', result, 4)[0], len(result) - 8)

    def test_simple_webp_is_unchanged(self):
        result, report = self.clean(webp(VP8L))
        self.assertEqual(result, webp(VP8L))
        self.assertEqual(report['removed_chunk_types'], [])

    def test_animated_webp_preserves_frame_and_flags_other_than_metadata(self):
        frame = riff_chunk(b'ANMF', bytes(16) + VP8L)
        animation = riff_chunk(b'ANIM', bytes(6))
        result, _ = self.clean(webp(vp8x(0x0a), animation, frame, riff_chunk(b'EXIF', b'x')))
        self.assertEqual(result, webp(vp8x(0x02), animation, frame))

    def test_webp_malformed_sizes_padding_missing_images_and_features_rejected(self):
        valid = webp(VP8L)
        padded = webp(vp8x(0x08), VP8L, riff_chunk(b'EXIF', b'x'))
        cases = [valid[:-1], valid + b'private tail', webp(), webp(vp8x()),
                 webp(VP8L, VP8L), webp(vp8x(), vp8x(), VP8L), webp(VP8L, vp8x()),
                 webp(vp8x(1), VP8L), webp(vp8x(0x20), VP8L),
                 webp(vp8x(), riff_chunk(b'ICCP', b'profile'), VP8L),
                 webp(vp8x(0x02), riff_chunk(b'ANIM', bytes(6))),
                 webp(vp8x(0x02), riff_chunk(b'ANMF', bytes(16) + VP8L)),
                 webp(vp8x(), riff_chunk(b'ALPH', b'\0'), VP8L),
                 webp(riff_chunk(b'VP8L', b'wrong')), padded[:-1] + b'\xff',
                 b'RIFF' + struct.pack('<I', 12) + b'WEBPVP8L' + struct.pack('<I', 0xffffffff)]
        for data in cases:
            with self.subTest(data=data[:32]):
                self.source.write_bytes(data)
                with self.assertRaises(ValueError):
                    cleaner.clean_file(self.source, self.output)
                self.assertFalse(self.output.exists())
                self.assertEqual(self.source.read_bytes(), data)

    def test_size_and_chunk_limits_reject_before_output(self):
        self.source.write_bytes(png())
        with patch.object(cleaner, 'MAX_BYTES', len(png()) - 1):
            with self.assertRaises(ValueError):
                cleaner.clean_file(self.source, self.output)
        with patch.object(cleaner, 'MAX_CHUNKS', 2):
            with self.assertRaises(ValueError):
                cleaner.clean_file(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_failed_output_sync_removes_only_the_new_file(self):
        self.source.write_bytes(png())
        with patch.object(cleaner.os, 'fsync', side_effect=OSError('simulated write failure')):
            with self.assertRaises(ValueError):
                cleaner.clean_file(self.source, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), png())

    def test_exclusive_creation_preserves_a_concurrent_output_collision(self):
        self.source.write_bytes(png())
        original_open = os.open

        def collide(path, flags, *args, **kwargs):
            if flags & os.O_EXCL:
                self.output.write_bytes(b'concurrent unrelated output')
            return original_open(path, flags, *args, **kwargs)

        with patch.object(cleaner.os, 'open', side_effect=collide):
            with self.assertRaises(ValueError):
                cleaner.clean_file(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b'concurrent unrelated output')
        self.assertEqual(self.source.read_bytes(), png())

    def test_direct_source_link_and_fifo_are_refused_without_output(self):
        self.source.symlink_to(self.root / 'target.png')
        (self.root / 'target.png').write_bytes(png())
        with self.assertRaises(ValueError):
            cleaner.clean_file(self.source, self.output)
        self.assertTrue(self.source.is_symlink())
        self.source.unlink()
        if hasattr(os, 'mkfifo'):
            os.mkfifo(self.source)
            with self.assertRaises(ValueError):
                cleaner.clean_file(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_output_source_alias_links_and_nonregular_paths_preserved(self):
        self.source.write_bytes(png())
        self.output.write_bytes(b'existing content')
        for destination in (self.source, self.output):
            with self.assertRaises(ValueError):
                cleaner.clean_file(self.source, destination)
        self.assertEqual(self.output.read_bytes(), b'existing content')
        self.assertEqual(self.source.read_bytes(), png())
        self.output.unlink()
        linked = self.root / 'linked'; linked.symlink_to(self.root, target_is_directory=True)
        for source, destination in [(linked / 'input.png', self.output), (self.source, linked / 'clean.png'),
                                    (self.root, self.output), (self.source, self.root)]:
            with self.assertRaises(ValueError):
                cleaner.clean_file(source, destination)
        self.output.symlink_to(self.source)
        with self.assertRaises(ValueError):
            cleaner.clean_file(self.source, self.output)
        self.assertTrue(self.output.is_symlink())
        self.output.unlink()
        os.link(self.source, self.output)
        with self.assertRaises(ValueError):
            cleaner.clean_file(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), png())

    def test_cli_report_excludes_input_paths_and_metadata_values(self):
        self.source.write_bytes(png(png_chunk(b'tEXt', b'private-person-secret')))
        script = Path(__file__).resolve().parents[1] / 'tools/clean_image_metadata.py'
        result = subprocess.run([sys.executable, str(script), str(self.source), '--output', str(self.output)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['removed_chunk_types'], ['tEXt'])
        self.assertNotIn(str(self.root), result.stdout + result.stderr)
        self.assertNotIn('private-person-secret', result.stdout + result.stderr)
        failed = subprocess.run([sys.executable, str(script), str(self.source), '--output', str(self.output)],
                                capture_output=True, text=True)
        self.assertNotEqual(failed.returncode, 0)
        self.assertNotIn(str(self.root), failed.stdout + failed.stderr)

    @unittest.skipUnless(Image is not None, 'Pillow is optional for decoded-pixel characterization')
    def test_real_png_and_webp_keep_decoded_rgba_samples(self):
        original = Image.new('RGBA', (3, 2))
        original.putdata([(20, 80, 130, 255), (0, 180, 10, 80), (130, 55, 0, 0)] * 2)
        formats = [('PNG', {})]
        if features.check('webp'):
            formats += [('WEBP', {'lossless': lossless, 'exif': b'metadata bytes', 'xmp': b'metadata bytes'})
                        for lossless in (True, False)]
        for format_name, options in formats:
            with self.subTest(format=format_name, options=options):
                stream = io.BytesIO()
                original.save(stream, format=format_name, **options)
                data = stream.getvalue()
                if format_name == 'PNG':
                    data = data[:-12] + png_chunk(b'tEXt', b'Comment\0metadata') + data[-12:]
                result, _ = self.clean(data)
                with Image.open(io.BytesIO(data)) as before, Image.open(io.BytesIO(result)) as after:
                    self.assertEqual(before.convert('RGBA').tobytes(), after.convert('RGBA').tobytes())
                    self.assertEqual(before.size, after.size)
                self.output.unlink()


if __name__ == '__main__':
    unittest.main()
