#!/usr/bin/env python3
"""Build bounded reference thumbnails from exact installed asset identities.

Outputs are game reference imagery, excluded from the project artwork license.
Run only with explicit permission to display these comparative previews. Original
resources and decoded geometry are never written. Work/cache/logs must stay local.
"""
import argparse
from collections import defaultdict
import gc
import hashlib
import json
import math
from pathlib import Path
import re

from PIL import Image, ImageDraw
import numpy as np

TILE = 192
COLUMNS = 8


def object_id(obj):
    return f'{Path(obj.assets_file.name).name}:{int(obj.path_id)}'


def safe_bundle(root, name):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('Invalid bundle basename')
    path = root / name
    if path.is_symlink() or path.resolve().parent != root.resolve():
        raise ValueError('Bundle must be a direct regular local file')
    return path


def thumbnail(image, cap=TILE):
    image = image.convert('RGBA')
    image.thumbnail((cap, cap), Image.Resampling.LANCZOS)
    out = Image.new('RGBA', (cap, cap))
    out.paste(image, ((cap-image.width)//2, (cap-image.height)//2))
    return out


def slot(index):
    return index // 64, (index % 8)*TILE, ((index // 8) % 8)*TILE


def mesh_thumbnail(mesh):
    from UnityPy.helpers.MeshHelper import MeshHandler
    handler = MeshHandler(mesh)
    handler.process()
    vertices = np.asarray(handler.m_Vertices, dtype=np.float64)[:, :3]
    triangles = np.asarray([t for part in handler.get_triangles() for t in part], dtype=np.int64)
    if not len(vertices) or not triangles.size or not np.isfinite(vertices).all():
        raise ValueError('Empty or nonfinite mesh')
    if triangles.ndim != 2 or triangles.shape[1] != 3 or triangles.min() < 0 or triangles.max() >= len(vertices):
        raise ValueError('Invalid triangle indices')
    # Preserve all triangles within the bound. Larger geometry is reported as
    # unavailable instead of silently dropping parts of its silhouette.
    if len(triangles) > 100000:
        raise ValueError('Mesh exceeds 100000 triangle preview bound')
    rotation = np.array([[.70710678, -.40824829, .57735027], [0, .81649658, .57735027], [-.70710678, -.40824829, .57735027]])
    projected = vertices @ rotation
    span = np.ptp(projected[:, :2], axis=0).max()
    if span <= 1e-12:
        raise ValueError('Degenerate mesh extent')
    points = (projected[:, :2]-(projected[:, :2].min(0)+projected[:, :2].max(0))/2) * (TILE-24)/span
    points[:, 0] += TILE/2
    points[:, 1] = TILE/2-points[:, 1]
    faces = vertices[triangles]
    normals = np.cross(faces[:, 1]-faces[:, 0], faces[:, 2]-faces[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    normals /= np.maximum(lengths[:, None], 1e-12)
    light = np.array([-.35, .8, -.48]); light /= np.linalg.norm(light)
    shade = 100 + 130*np.abs(normals @ light)
    out = Image.new('RGBA', (TILE, TILE))
    draw = ImageDraw.Draw(out)
    # Orthographic painter ordering is bounded and deterministic. It is a shape
    # preview, not an exact depth-buffer render or an in-game material view.
    for i in np.argsort(projected[triangles, 2].mean(axis=1), kind='stable'):
        if lengths[i] <= 1e-12:
            continue
        gray = int(shade[i])
        draw.polygon([tuple(p) for p in points[triangles[i]]], fill=(gray,gray,gray,255))
    return out


def texture_thumbnail(data, type_name):
    if type_name == 'Texture2D':
        return thumbnail(data.image), None
    if type_name == 'Texture2DArray':
        if not data.image_data and data.m_StreamData and data.m_StreamData.path:
            from UnityPy.helpers.ResourceReader import get_resource_data
            data.image_data = get_resource_data(data.m_StreamData.path, data.object_reader.assets_file, data.m_StreamData.offset, data.m_StreamData.size)
        images = data.images
        if not images:
            raise ValueError('No array layers')
        count = len(images)
        shown = min(count, 16)
        columns = math.ceil(math.sqrt(shown))
        cell = TILE // columns
        out = Image.new('RGBA', (TILE, TILE))
        for i, im in enumerate(images[:shown]):
            out.paste(thumbnail(im, cell), ((i%columns)*cell, (i//columns)*cell))
        return out, f'Texture2DArray, {count} layers; first {shown} shown'
    if type_name == 'Cubemap':
        from UnityPy.export.Texture2DConverter import parse_image_data
        raw = data.get_image_data()
        face_size = data.m_CompleteImageSize
        if data.m_ImageCount != 6 or len(raw) != face_size*6:
            raise ValueError('Cubemap face layout unsupported')
        out = Image.new('RGBA', (TILE, TILE))
        for i in range(6):
            face = parse_image_data(raw[i*face_size:(i+1)*face_size], data.m_Width, data.m_Height, data.m_TextureFormat, data.object_reader.version, data.object_reader.platform)
            out.paste(thumbnail(face, 64), ((i%3)*64, 32+(i//3)*64))
        return out, 'Cubemap, all 6 serialized faces in a montage'
    raise ValueError('Texture type has no supported visual decoder')


def build(args):
    import UnityPy
    inventory = json.loads(args.inventory.read_text())
    catalog = json.loads(args.catalog.read_text())['assets']
    rows = {r['id']: r for r in inventory['textures']+inventory['meshes']}
    groups = defaultdict(list)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    cache = output.parent/'cache'; cache.mkdir(exist_ok=True)
    log = output.parent/'private-errors.jsonl'
    manifest = dict(schema_version=1, tile_size=TILE, columns=COLUMNS, sheets=[], assets={})
    for asset in catalog:
        identity = asset['id']
        manifest['assets'][identity] = dict(before=None, status='unavailable', reason='Exact asset was not decoded')
        row = rows.get(identity)
        if row and row.get('sources'):
            groups[sorted(row['sources'])[0]].append(asset)
    bundles = args.bundles or Path(inventory['game_root'])/'valheim_Data/StreamingAssets/SoftRef/Bundles'
    completed = 0
    for bundle_name, assets in sorted(groups.items()):
        needed = [a for a in assets if not (cache/(hashlib.sha256(a['id'].encode()).hexdigest()+'.json')).exists()]
        if needed:
            try:
                env = UnityPy.load(str(safe_bundle(bundles,bundle_name)))
                objects = {object_id(o): o for o in env.objects if o.type.name in {'Mesh','Texture2D','Texture2DArray','Texture3D','Cubemap','CubemapArray'}}
                for asset in needed:
                    identity = asset['id']; key = hashlib.sha256(identity.encode()).hexdigest()
                    try:
                        obj = objects[identity]
                        if (obj.type.name == 'Mesh') != (asset['kind'] == 'mesh'):
                            raise ValueError('Exact object kind mismatch')
                        data = obj.read()
                        if asset['kind'] == 'mesh':
                            preview = mesh_thumbnail(data)
                            note = 'Neutral orthographic mesh shape, flat shading and painter ordering; original material not shown'
                        else:
                            preview, note = texture_thumbnail(data,obj.type.name)
                        preview.save(cache/(key+'.png'))
                        result = dict(status='available', kind=asset['kind'])
                        if note: result['note'] = note
                    except Exception as exc:
                        reason = 'Preview decoder does not support this asset'
                        row = rows[identity]
                        if row.get('dimensions') == [0, 0]:
                            reason = 'Runtime font texture has no stored pixels'
                        elif row.get('type') == 'Texture3D':
                            reason = 'Volume texture slice decoding is not supported'
                        result = dict(status='unavailable', reason=reason)
                        with log.open('a') as f: f.write(json.dumps(dict(id=identity,error=str(exc),exception=type(exc).__name__))+'\n')
                    (cache/(key+'.json')).write_text(json.dumps(result))
                del env, objects
            except Exception as exc:
                with log.open('a') as f: f.write(json.dumps(dict(bundle=bundle_name,error=str(exc)))+'\n')
            gc.collect()
        completed += len(assets)
        print(f'{completed}/{len(catalog)} assets inspected ({bundle_name})',flush=True)
    sheet = None
    available = 0
    def save_sheet(index, image):
        name = f'before-{index:03d}.webp'
        path = output/name
        image.save(path, 'WEBP', quality=82, method=4, exact=True)
        manifest['sheets'].append(dict(file=name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),width=1536,height=1536,kind='reference-preview',original_game_pixels=True,license='Game reference, excluded from project artwork license'))
    for asset in sorted(catalog,key=lambda a:a['id']):
        identity = asset['id']; key = hashlib.sha256(identity.encode()).hexdigest()
        metadata = cache/(key+'.json')
        if not metadata.exists(): continue
        result = json.loads(metadata.read_text())
        if result['status'] != 'available':
            manifest['assets'][identity] = dict(before=None,**result)
            continue
        index,x,y = slot(available)
        if available%64 == 0:
            if sheet is not None: save_sheet(index-1,sheet)
            sheet = Image.new('RGBA',(1536,1536))
        with Image.open(cache/(key+'.png')) as tile:
            sheet.paste(tile,(x,y))
        before = dict(sheet=f'before-{index:03d}.webp',x=x,y=y,width=TILE,height=TILE,kind=result['kind'])
        if result.get('note'): before['note'] = result['note']
        manifest['assets'][identity] = dict(before=before,status='available')
        available += 1
    if sheet is not None: save_sheet((available-1)//64,sheet)
    (output/'manifest.json').write_text(json.dumps(manifest,separators=(',',':'))+'\n')
    print(json.dumps(dict(total=len(catalog),available=available,unavailable=len(catalog)-available,sheets=len(manifest['sheets']))),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',type=Path,default=Path('local/texture-inventory/complete/inventory.json'))
    parser.add_argument('--catalog',type=Path,default=Path('assets/status/catalog.json'))
    parser.add_argument('--bundles',type=Path)
    parser.add_argument('--output',type=Path,default=Path('local/meadows-pass/previews/generated'))
    build(parser.parse_args())
