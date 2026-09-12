import hashlib
import copy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from tools.package_install import build_package
from installer.package import Package, PackageError


def hash_bytes(data):
    return hashlib.sha256(data).hexdigest()


class PackageBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / 'bundles').mkdir()
        (self.root / 'stage').mkdir()
        (self.root / 'source.png').write_bytes(b'authored source fixture')
        provenance = dict(assets=[dict(dest='source.png', sha256=hash_bytes(b'authored source fixture'), original_game_pixels=False)])
        (self.root / 'provenance.json').write_text(json.dumps(provenance))
        header = bytearray(128)
        header[:4], header[84:88] = b'DDS ', b'DXT5'
        dds = bytes(header) + b'x' * 48
        (self.root / 'stage/stone-unity.dds').write_bytes(dds)
        self.asset = dict(id='stone', source='source.png', source_sha256=hash_bytes(b'authored source fixture'), unity_dds='stone-unity.dds', unity_dds_sha256=hash_bytes(dds), dimensions=[4,4], mip_count=3, compressed_payload_bytes=48, srgb=True)
        (self.root / 'stage/manifest.json').write_text(json.dumps(dict(assets=[self.asset])))
        bundle = b'UnityFS owned fixture'
        (self.root / 'bundles/stone.bundle').write_bytes(bundle)
        self.catalog = dict(schemaVersion=1, editorVersion='6000.0.75f1', target='StandaloneLinux64', nativeReadback=True,
                            textures=[dict(id='stone', path='stone.bundle', assetName='assets/owned/stone.asset', sha256=hash_bytes(bundle), payloadSha256=hash_bytes(b'x'*48), width=4, height=4, mipCount=3, payloadBytes=48, isSrgb=True)])
        (self.root / 'bundles/catalog.json').write_text(json.dumps(self.catalog))
        for name in ['ValheimImpact.Core.dll', 'ValheimImpact.Unity.dll']:
            (self.root / name).write_bytes(b'owned runtime fixture')

    def tearDown(self):
        self.temporary.cleanup()

    def build(self, **options):
        return build_package(catalog=self.root/'bundles/catalog.json', output=self.root/'package.zip',
            runtime_dir=self.root, staging_manifest=self.root/'stage/manifest.json', provenance=self.root/'provenance.json', source_root=self.root, version='0.1.0', **options)

    def test_binding_allowlist_is_packaged_and_unknown_texture_is_rejected(self):
        binding = dict(id='stone', materialName='stone_huge', shaderName='Custom/StaticRock',
                       textureProperty='_MainTex', originalTextureName='rock_256',
                       originalWidth=512, originalHeight=512, ownedTextureId='missing')
        path = self.root / 'bindings.json'
        path.write_text(json.dumps(dict(schemaVersion=1, bindings=[binding])))
        with self.assertRaises(ValueError):
            self.build(bindings=path)
        binding['ownedTextureId'] = 'stone'
        path.write_text(json.dumps(dict(schemaVersion=1, bindings=[binding])))
        self.build(bindings=path)
        package = Package.read(self.root / 'package.zip')
        self.assertIn('assets/bindings.json', {x['path'] for x in package.manifest['files']})

    def test_allowlist_omits_incidental_sources_and_readback_artifacts(self):
        (self.root / 'bundles/private.png').write_bytes(b'not release content')
        (self.root / 'bundles/huge.resS').symlink_to('/not/followed')
        self.build()
        package = Package.read(self.root / 'package.zip')
        self.assertEqual({entry['path'] for entry in package.manifest['files']}, {'ValheimImpact.Core.dll', 'ValheimImpact.Unity.dll', 'assets/catalog.json', 'assets/stone.bundle', 'EXPERIMENTAL.txt'})

    def cutout_manifest(self):
        return dict(schemaVersion=2, bindings=[dict(id='fringe', materialName='straw_roof_alpha', shaderName='Custom/Piece',
            textureProperty='_MainTex', originalTextureName='straw_roof', originalWidth=128, originalHeight=128, ownedTextureId='stone',
            cutout=dict(mode=1, cutoff=.69, cull=0, zWrite=1, srcBlend=1, dstBlend=0, renderQueue=2000, alphaTest=False))])

    def test_cutout_v2_is_packaged_without_rewriting_explicit_state(self):
        manifest = self.cutout_manifest()
        path = self.root / 'bindings.json'
        payload = json.dumps(manifest).encode()
        path.write_bytes(payload)
        self.build(bindings=path)
        with zipfile.ZipFile(self.root / 'package.zip') as archive:
            self.assertEqual(archive.read('payload/assets/bindings.json'), payload)
        descriptor = next(entry for entry in Package.read(self.root / 'package.zip').manifest['files'] if entry['path'] == 'assets/bindings.json')
        self.assertEqual(descriptor['sha256'], hash_bytes(payload))

    def test_cutout_v2_rejects_implicit_or_blended_state_before_packaging(self):
        variants = []
        legacy = self.cutout_manifest()
        legacy['schemaVersion'] = 1
        variants.append(legacy)
        for key, value in [('mode', 2), ('cutoff', 0), ('cutoff', float('nan')), ('cull', 1), ('zWrite', 0),
                           ('srcBlend', 5), ('dstBlend', 10), ('renderQueue', 3000), ('renderQueue', 2000.0),
                           ('alphaTest', 0), ('mode', True), ('unknown', False)]:
            manifest = self.cutout_manifest()
            manifest['bindings'][0]['cutout'][key] = value
            variants.append(manifest)
        for key in self.cutout_manifest()['bindings'][0]['cutout']:
            manifest = self.cutout_manifest()
            del manifest['bindings'][0]['cutout'][key]
            variants.append(manifest)
        unknown_shader = self.cutout_manifest()
        unknown_shader['bindings'][0]['shaderName'] = 'Unknown/Cutout'
        variants.append(unknown_shader)
        null_state = self.cutout_manifest()
        null_state['bindings'][0]['cutout'] = None
        variants.append(null_state)
        for index, manifest in enumerate(variants):
            with self.subTest(case=index):
                path = self.root / 'bindings.json'
                path.write_text(json.dumps(manifest))
                try:
                    with self.assertRaises(ValueError):
                        self.build(bindings=path)
                    self.assertFalse((self.root / 'package.zip').exists())
                finally:
                    (self.root / 'package.zip').unlink(missing_ok=True)

    def test_cutout_v2_can_include_an_opaque_rule_without_opt_in(self):
        manifest = self.cutout_manifest()
        opaque = copy.deepcopy(manifest['bindings'][0])
        opaque.update(id='solid', materialName='straw_roof')
        del opaque['cutout']
        manifest['bindings'].append(opaque)
        path = self.root / 'bindings.json'
        path.write_text(json.dumps(manifest))
        self.build(bindings=path)
        with zipfile.ZipFile(self.root / 'package.zip') as archive:
            self.assertEqual(json.loads(archive.read('payload/assets/bindings.json')), manifest)

    def test_cutout_threshold_must_remain_inside_range_after_runtime_float_conversion(self):
        for cutoff in (0.9999999999, 1e-50):
            with self.subTest(cutoff=cutoff):
                manifest = self.cutout_manifest()
                manifest['bindings'][0]['cutout']['cutoff'] = cutoff
                path = self.root / 'bindings.json'
                path.write_text(json.dumps(manifest))
                try:
                    with self.assertRaises(ValueError):
                        self.build(bindings=path)
                    self.assertFalse((self.root / 'package.zip').exists())
                finally:
                    (self.root / 'package.zip').unlink(missing_ok=True)

    def test_tampered_dds_and_non_authored_provenance_block_package(self):
        (self.root / 'stage/stone-unity.dds').write_bytes(b'changed')
        with self.assertRaises((ValueError, PackageError)):
            self.build()
        self.assertFalse((self.root / 'package.zip').exists())

    def test_bundle_link_is_rejected_without_following_it(self):
        bundle = self.root / 'bundles/stone.bundle'
        bundle.unlink()
        bundle.symlink_to(self.root / 'source.png')
        with self.assertRaises((ValueError, PackageError)):
            self.build()

    def test_missing_native_validation_blocks_package(self):
        self.catalog['nativeReadback'] = False
        (self.root / 'bundles/catalog.json').write_text(json.dumps(self.catalog))
        with self.assertRaises((ValueError, PackageError)):
            self.build()
