"""Regression checks for identity isolation and bounded preview generation."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from PIL import Image
from tools.build_inventory_previews import object_id, safe_bundle, slot, thumbnail, texture_thumbnail


class PreviewTests(unittest.TestCase):
    def test_exact_identity_does_not_merge_same_name_or_path_id(self):
        a = SimpleNamespace(assets_file=SimpleNamespace(name='CAB-a'),path_id=-33)
        b = SimpleNamespace(assets_file=SimpleNamespace(name='CAB-b'),path_id=-33)
        self.assertEqual(object_id(a),'CAB-a:-33')
        self.assertNotEqual(object_id(a),object_id(b))

    def test_packing_boundaries_and_unique_slots(self):
        self.assertEqual(slot(0),(0,0,0))
        self.assertEqual(slot(63),(0,1344,1344))
        self.assertEqual(slot(64),(1,0,0))
        self.assertEqual(len({slot(i) for i in range(13523)}),13523)
        self.assertTrue(all(x+192<=1536 and y+192<=1536 for _,x,y in map(slot,range(13523))))

    def test_no_upscale_preserves_alpha_and_caps_large_images(self):
        im = Image.new('RGBA',(8,4),(20,40,60,128))
        out = thumbnail(im)
        self.assertEqual(out.size,(192,192))
        self.assertEqual(out.getbbox(),(92,94,100,98))
        self.assertEqual(out.getpixel((92,94)),(20,40,60,128))
        out = thumbnail(Image.new('RGBA',(1000,500),(255,255,255,255)))
        self.assertEqual(out.getbbox(),(0,48,192,144))

    def test_array_montage_labels_layer_count_and_keeps_tile_bound(self):
        data = SimpleNamespace(image_data=b'present', images=[Image.new('RGBA',(128,128),(i*10,0,0,255)) for i in range(6)])
        out, note = texture_thumbnail(data, 'Texture2DArray')
        self.assertEqual(out.size,(192,192))
        self.assertIn('6 layers; first 6 shown',note)
        self.assertEqual(out.getpixel((96,32)),(10,0,0,255))
        self.assertEqual(out.getpixel((32,160)),(0,0,0,0))

    def test_bundle_paths_reject_traversal_absolute_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root/'a123';path.write_bytes(b'')
            self.assertEqual(safe_bundle(root,'a123'),path)
            for value in ('../a123','/a123','a/b','a\\b','..'):
                with self.assertRaises(ValueError): safe_bundle(root,value)
            (root/'link').symlink_to(path)
            with self.assertRaises(ValueError): safe_bundle(root,'link')


if __name__ == '__main__': unittest.main()
