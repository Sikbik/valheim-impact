"""Read-only SoftRef texture/material inventory. Original references belong in local/."""
import argparse
from collections import Counter, defaultdict
import gc
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXTENSIONS = {'.png', '.tga', '.jpg', '.jpeg', '.psd', '.exr', '.tif', '.tiff', '.dds', '.cubemap'}
DEFAULT_MATERIALS = {'stone_huge', 'woodwall', 'woodpole', 'wood_roof_mat', 'beech_bark'}
RENDERER_TYPES = {'MeshRenderer', 'SkinnedMeshRenderer', 'ParticleSystemRenderer', 'LineRenderer', 'TrailRenderer'}
TEXTURE_TYPES = {'Texture2D', 'Texture2DArray', 'Texture3D', 'Cubemap'}


def object_key(serialized_file, path_id):
    """Path IDs are scoped to a serialized file, never to a texture name."""
    return f'{str(serialized_file).replace(chr(92), chr(47)).rstrip(chr(47)).split(chr(47))[-1]}:{int(path_id)}'


def deduplicate(records):
    result = {}
    for record in records:
        key = record['id']
        if key not in result:
            result[key] = dict(record)
            continue
        current = result[key]
        for name, value in record.items():
            if name in {'sources', 'container_paths'}:
                current[name] = sorted(set(current.get(name, [])) | set(value))
            elif current.get(name) != value:
                raise ValueError(f'Conflicting object metadata for {key}: {name}')
    return [result[key] for key in sorted(result)]


def category_estimate(path):
    """Conservative filename/path heuristic, not a visibility or usage claim."""
    value = path.replace('\\', '/').lower()
    stem = Path(value).stem
    if any(part in value for part in ['/icons/', '/icon/', '/gui/', '/ui/', '/fonts/']):
        return 'ui'
    if re.search(r'(?:_n|_normal|_normals|_m|_mask|_metallic|_s|_specular|_ao|_height|_bump|_roughness)$', stem):
        return 'support_map'
    if any(part in value for part in ['/fx/', '/vfx/', '/effects/', '/particles/']):
        return 'effect'
    if '/characters/' in value:
        return 'character'
    if '/items/' in value:
        return 'equipment_item'
    if '/pieces/' in value:
        return 'building'
    if any(part in value for part in ['beech', 'birch', 'fir_tree', '/fir/', '/pine/', 'bark', 'leaf', 'leaves', '/grass', '/bush']):
        return 'vegetation'
    if any(part in value for part in ['/terrain/', '/heightmaps/', '/water/']):
        return 'terrain_water'
    if any(part in value for part in ['/world/', '/environment/', '/props/']):
        return 'world_surface'
    return 'unclassified'


def parse_manifest(text):
    if 'asset locations:' not in text:
        raise ValueError('SoftRef asset locations section missing')
    section = text.split('asset locations:', 1)[1]
    records = []
    current = None
    for raw in section.splitlines():
        line = raw.strip()
        if line.startswith('- asset ID: '):
            if current is not None:
                records.append(current)
            current = {'asset_id': line.split(': ', 1)[1]}
        elif current is not None and line.startswith('bundle: '):
            current['bundle'] = line.split(': ', 1)[1]
        elif current is not None and line.startswith('path in bundle: '):
            current['path'] = line.split(': ', 1)[1]
    if current is not None:
        records.append(current)
    for record in records:
        if set(record) != {'asset_id', 'bundle', 'path'} or not re.fullmatch(r'[a-zA-Z0-9_-]+', record['bundle']):
            raise ValueError('Malformed or unsafe SoftRef asset location')
    return records


def manifest_bundle_names(assets, text, scope):
    names = {asset['bundle'] for asset in assets if scope == 'all' or Path(asset['path']).suffix.lower() in IMAGE_EXTENSIONS}
    if scope == 'all':
        dependency_section = text.split('asset locations:', 1)[0]
        names.update(re.findall(r'^- bundle: (\S+)', dependency_section, re.MULTILINE))
        names.update(re.findall(r'^  - (\S+)', dependency_section, re.MULTILINE))
    return sorted(names)


def validate_output(output, game):
    output = Path(output).absolute()
    for part in [output, *output.parents]:
        if part.is_symlink():
            raise ValueError(f'Output contains a symlink: {part}')
    output = output.resolve()
    if output == game.resolve() or game.resolve() in output.parents:
        raise ValueError('Inventory output must be outside the game installation')
    return output


def write_json(path, record):
    if path.is_symlink():
        raise ValueError(f'Refusing linked output: {path}')
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def pointer_key(assets_file, pointer):
    path_id = pointer['m_PathID']
    if not path_id:
        return None
    file_id = pointer['m_FileID']
    name = assets_file.name if file_id == 0 else assets_file.externals[file_id - 1].path
    return object_key(name, path_id)


def local_object(assets_file, pointer):
    if pointer and pointer['m_FileID'] == 0:
        return assets_file.objects.get(pointer['m_PathID'])
    return None


def summarize(textures, materials, renderers, unresolved):
    return {'textures': len(textures), 'materials': len(materials),
            'serialized_renderers': len(renderers), 'unresolved_links': len(unresolved),
            'texture_category_estimates': dict(sorted(Counter(t['category_estimate'] for t in textures).items())),
            'visible_replacements_validated': 0,
            'note': 'Serialized metadata and category estimates do not establish loaded, visible, replaced or UV-validated coverage.'}


def uv_statistics(points, triangles, scale=(1, 1), offset=(0, 0)):
    import math
    indices = sorted({index for triangle in triangles for index in triangle})
    raw = [points[index][:2] for index in indices]
    transformed = [[point[axis] * scale[axis] + offset[axis] for axis in range(2)] for point in raw]
    if any(not math.isfinite(value) for point in raw + transformed for value in point):
        raise ValueError('Nonfinite UV coordinate')
    def bounds(values):
        return [[op(point[axis] for point in values) for axis in range(2)] for op in (min, max)] if values else None
    return dict(vertices_used=len(indices), raw_bounds=bounds(raw), transformed_bounds=bounds(transformed),
                transformed_outside_unit_square=sum(not (0 <= pair[0] <= 1 and 0 <= pair[1] <= 1) for pair in transformed))


def hierarchy(reader):
    names, keys = [], []
    tree = reader.read_typetree()
    game_object = local_object(reader.assets_file, tree['m_GameObject'])
    visited = set()
    while game_object is not None and game_object.path_id not in visited and len(visited) < 256:
        visited.add(game_object.path_id)
        game_tree = game_object.read_typetree()
        names.append(game_tree.get('m_Name', ''))
        keys.append(object_key(game_object.assets_file.name, game_object.path_id))
        parent = None
        for component in game_tree.get('m_Component', []):
            obj = local_object(game_object.assets_file, component['component'])
            if obj is not None and obj.type.name in {'Transform', 'RectTransform'}:
                parent = local_object(obj.assets_file, obj.read_typetree()['m_Father'])
                break
        game_object = local_object(parent.assets_file, parent.read_typetree()['m_GameObject']) if parent else None
    return '/'.join(reversed(names)), list(reversed(keys))


def inspect_mesh(reader, output):
    """Export a bounded set of local references; never include coordinates in coverage."""
    from UnityPy.helpers.MeshHelper import MeshHandler
    from UnityPy.export.MeshExporter import export_mesh_obj
    from PIL import Image, ImageDraw
    mesh = reader.read()
    handler = MeshHandler(mesh)
    handler.process()
    uv = handler.m_UV0
    triangles = handler.get_triangles()
    identifier = object_key(reader.assets_file.name, reader.path_id)
    basename = hashlib.sha256(identifier.encode()).hexdigest()[:16]
    obj_path = output / (basename + '.obj')
    if obj_path.is_symlink():
        raise ValueError('Refusing linked mesh output')
    obj_path.write_text(export_mesh_obj(mesh))
    result = dict(id=identifier, name=mesh.m_Name, vertices=handler.m_VertexCount,
                  local_obj=obj_path.name, submesh_triangles=[len(group) for group in triangles],
                  submesh_uv=[uv_statistics(uv, group) for group in triangles] if uv else [],
                  coordinate_convention='OBJ export mirrors Unity X and reverses winding; UV0 unchanged')
    if uv:
        import math
        finite = all(math.isfinite(component) for pair in uv for component in pair[:2])
        result['uv0_finite'] = finite
        if finite:
            minimum = [min(pair[axis] for pair in uv) for axis in range(2)]
            maximum = [max(pair[axis] for pair in uv) for axis in range(2)]
            result['uv0_bounds'] = [minimum, maximum]
            result['uv0_outside_unit_square'] = sum(not (0 <= pair[0] <= 1 and 0 <= pair[1] <= 1) for pair in uv)
            canvas = Image.new('RGB', (768, 768), '#20242a')
            draw = ImageDraw.Draw(canvas)
            extent = max(maximum[0]-minimum[0], maximum[1]-minimum[1], 1e-6)
            def point(index):
                return ((uv[index][0]-minimum[0])/extent*720+24, 744-(uv[index][1]-minimum[1])/extent*720)
            for group in triangles:
                for triangle in group:
                    points = [point(index) for index in triangle]
                    draw.line(points + [points[0]], fill='#85b8da', width=1)
            png_path = output / (basename + '-uv.png')
            if png_path.is_symlink():
                raise ValueError('Refusing linked UV output')
            canvas.save(png_path)
            result['local_uv_png'] = png_path.name
    else:
        result['uv0_present'] = False
    return result


def scan_bundle(bundle, output, targets, max_objects, mesh_limit):
    import UnityPy
    environment = UnityPy.load(str(bundle))
    objects = environment.objects
    if len(objects) > max_objects:
        raise ValueError(f'Object budget exceeded: {bundle.name}: {len(objects)}')
    paths = defaultdict(list)
    for path, pointer in environment.container.items():
        key = pointer_key(pointer.assetsfile, {'m_FileID': pointer.m_FileID, 'm_PathID': pointer.m_PathID})
        paths[key].append(path)
    result = {name: [] for name in ['textures', 'materials', 'shaders', 'renderers', 'meshes', 'uv_references', 'errors']}
    result['object_counts'] = dict(Counter(obj.type.name for obj in objects))
    target_readers = {}
    readers = {}
    mesh_readers = {}
    shader_names = {}
    def base(obj, name):
        key = object_key(obj.assets_file.name, obj.path_id)
        return dict(id=key, name=name, path_id=str(obj.path_id), serialized_file=obj.assets_file.name,
                    sources=[bundle.name], container_paths=sorted(paths[key]))
    for obj in objects:
        kind = obj.type.name
        if kind not in TEXTURE_TYPES | {'Material', 'Shader', 'Mesh'}:
            continue
        key = object_key(obj.assets_file.name, obj.path_id)
        if kind == 'Mesh':
            result['meshes'].append(base(obj, obj.peek_name()))
            mesh_readers[key] = obj
            continue
        tree = obj.read_typetree()
        record = base(obj, tree.get('m_Name', ''))
        if kind in TEXTURE_TYPES:
            record.update(type=kind, dimensions=[tree.get('m_Width'), tree.get('m_Height')],
                          depth=tree.get('m_Depth'), texture_format=tree.get('m_TextureFormat', tree.get('m_Format')),
                          mip_count=tree.get('m_MipCount'), color_space=tree.get('m_ColorSpace'),
                          complete_image_size=tree.get('m_CompleteImageSize'), stream=tree.get('m_StreamData'),
                          settings=tree.get('m_TextureSettings'), alpha_inspected=False)
            record['category_estimate'] = category_estimate(record['container_paths'][0] if record['container_paths'] else record['name'])
            result['textures'].append(record)
            readers[key] = obj
        elif kind == 'Shader':
            record['name'] = tree.get('m_ParsedForm', {}).get('m_Name') or tree.get('m_Name', '')
            shader_names[key] = record['name']
            result['shaders'].append(record)
        else:
            properties = tree['m_SavedProperties']
            record.update(shader_id=pointer_key(obj.assets_file, tree['m_Shader']),
                          textures=[dict(property=prop, texture_id=pointer_key(obj.assets_file, slot['m_Texture']),
                                         scale=slot['m_Scale'], offset=slot['m_Offset'])
                                    for prop, slot in properties['m_TexEnvs']],
                          floats=dict(properties.get('m_Floats', [])), colors=dict(properties.get('m_Colors', [])),
                          ints=dict(properties.get('m_Ints', [])), custom_render_queue=tree.get('m_CustomRenderQueue'),
                          keywords=tree.get('m_ValidKeywords', tree.get('m_ShaderKeywords')), tags=tree.get('stringTagMap'))
            result['materials'].append(record)
            if record['name'] in targets:
                target_readers[key] = obj
    material_by_id = {m['id']: m for m in result['materials']}
    target_candidates = defaultdict(list)
    for obj in objects:
        if obj.type.name not in RENDERER_TYPES:
            continue
        tree = obj.read_typetree()
        material_ids = [pointer_key(obj.assets_file, pointer) for pointer in tree.get('m_Materials', [])]
        game_object = local_object(obj.assets_file, tree.get('m_GameObject'))
        game_tree = game_object.read_typetree() if game_object else {}
        mesh_pointer = tree.get('m_Mesh')
        if mesh_pointer is None:
            for component in game_tree.get('m_Component', []):
                component_obj = local_object(obj.assets_file, component['component'])
                if component_obj is not None and component_obj.type.name == 'MeshFilter':
                    mesh_pointer = component_obj.read_typetree()['m_Mesh']
                    break
        mesh_id = pointer_key(obj.assets_file, mesh_pointer) if mesh_pointer else None
        record = base(obj, game_tree.get('m_Name', ''))
        record.update(type=obj.type.name, material_ids=material_ids, mesh_id=mesh_id,
                      game_object_id=pointer_key(obj.assets_file, tree['m_GameObject']), enabled=tree.get('m_Enabled'))
        result['renderers'].append(record)
        for index, mat_id in enumerate(material_ids):
            if mat_id in target_readers and mesh_id in mesh_readers:
                target_candidates[mat_id].append((record, index, obj))
    reference_dir = output / 'references'
    reference_dir.mkdir(exist_ok=True)
    exported_meshes = {}
    for mat_id, reader in sorted(target_readers.items()):
        material = material_by_id[mat_id]
        material['shader_name'] = shader_names.get(material['shader_id'])
        inspected = set()
        for renderer, index, renderer_reader in target_candidates[mat_id]:
            mesh_id = renderer['mesh_id']
            if mesh_id in inspected:
                continue
            inspected.add(mesh_id)
            if len(inspected) > mesh_limit:
                break
            try:
                if mesh_id not in exported_meshes:
                    exported_meshes[mesh_id] = inspect_mesh(mesh_readers[mesh_id], reference_dir)
                hierarchy_name, hierarchy_keys = hierarchy(renderer_reader)
                result['uv_references'].append(dict(material_id=mat_id, material_name=material['name'],
                    hierarchy=hierarchy_name, prefab_paths=sorted({path for key in hierarchy_keys for path in paths[key]}),
                    renderer_id=renderer['id'], renderer_name=renderer['name'], material_slot=index,
                    mesh=exported_meshes[mesh_id], validation='UV coordinates extracted; authored game rendering not yet validated'))
            except Exception as error:
                result['errors'].append(dict(stage='uv_reference', object_id=mesh_id, message=str(error)))
        for slot in material['textures']:
            tex_id = slot['texture_id']
            if tex_id not in readers:
                continue
            texture = next(t for t in result['textures'] if t['id'] == tex_id)
            if texture['alpha_inspected']:
                continue
            try:
                pixels = readers[tex_id].read().image.convert('RGBA')
                path = reference_dir / (hashlib.sha256(tex_id.encode()).hexdigest()[:16] + '.png')
                if path.is_symlink():
                    raise ValueError('Refusing linked texture output')
                pixels.save(path)
                alpha = pixels.getchannel('A')
                histogram = alpha.histogram()
                texture.update(alpha_inspected=True, alpha_extrema=list(alpha.getextrema()),
                               alpha_zero=histogram[0], alpha_opaque=histogram[255], local_png=path.name)
            except Exception as error:
                result['errors'].append(dict(stage='alpha_reference', object_id=tex_id, message=str(error)))
    return result


def plan_mesh_references(materials, renderers, meshes, existing, targets, limit):
    target_ids = {material['id'] for material in materials if material['name'] in targets}
    mesh_by_id = {mesh['id']: mesh for mesh in meshes}
    inspected = defaultdict(set)
    for reference in existing:
        inspected[reference['material_id']].add(reference['mesh']['id'])
    plan = []
    for renderer in sorted(renderers, key=lambda item: item['id']):
        mesh_id = renderer['mesh_id']
        if mesh_id not in mesh_by_id:
            continue
        for slot, material_id in enumerate(renderer['material_ids']):
            if material_id not in target_ids or mesh_id in inspected[material_id] or len(inspected[material_id]) >= limit:
                continue
            inspected[material_id].add(mesh_id)
            plan.append(dict(material_id=material_id, renderer_id=renderer['id'], material_slot=slot,
                             mesh_id=mesh_id, source_bundle=mesh_by_id[mesh_id]['sources'][0]))
    return plan


def extract_cross_bundle_references(combined, bundles_dir, output, targets, limit):
    import UnityPy
    plan = plan_mesh_references(combined['materials'], combined['renderers'], combined['meshes'],
                               combined['uv_references'], targets, limit)
    materials = {material['id']: material for material in combined['materials']}
    renderers = {renderer['id']: renderer for renderer in combined['renderers']}
    for bundle_name in sorted({item['source_bundle'] for item in plan}):
        bundle_path = bundles_dir / bundle_name
        if bundle_path.is_symlink():
            raise ValueError('Refusing linked reference bundle')
        environment = UnityPy.load(str(bundle_path))
        wanted = {item['mesh_id'] for item in plan if item['source_bundle'] == bundle_name}
        objects = {object_key(obj.assets_file.name, obj.path_id): obj for obj in environment.objects
                   if obj.type.name == 'Mesh' and object_key(obj.assets_file.name, obj.path_id) in wanted}
        for item in plan:
            if item['source_bundle'] != bundle_name:
                continue
            try:
                mesh = inspect_mesh(objects[item['mesh_id']], output / 'references')
                material = materials[item['material_id']]
                renderer = renderers[item['renderer_id']]
                combined['uv_references'].append(dict(material_id=material['id'], material_name=material['name'],
                    material_slot=item['material_slot'], renderer_id=renderer['id'], renderer_name=renderer['name'],
                    renderer_source_bundles=renderer['sources'], mesh=mesh,
                    validation='Cross-bundle material/mesh join; authored game rendering not yet validated'))
            except Exception as error:
                combined['errors'].append(dict(stage='cross_bundle_uv', object_id=item['mesh_id'], message=str(error)))
        del objects, environment
        gc.collect()


def run(args):
    game = args.game.resolve()
    output = validate_output(args.output, game)
    # Original image and mesh references may only be written in the ignored local tree.
    local = ROOT / 'local'
    if local not in output.parents:
        raise ValueError('Use an output directory beneath the project local/ directory')
    output.mkdir(parents=True, exist_ok=True)
    validate_output(output / 'references', game)
    softref = game / 'valheim_Data/StreamingAssets/SoftRef'
    manifest = args.manifest or softref / 'manifest_extended'
    bundles_dir = args.bundles or softref / 'Bundles'
    manifest_text = manifest.read_text(encoding='utf-8-sig')
    assets = parse_manifest(manifest_text)
    bundle_names = manifest_bundle_names(assets, manifest_text, args.scope)
    if args.bundle:
        bundle_names = sorted(set(args.bundle))
    if len(bundle_names) > args.max_bundles:
        raise ValueError('Bundle count budget exceeded')
    targets = set(args.inspect_material or DEFAULT_MATERIALS)
    combined = {key: [] for key in ['textures', 'materials', 'shaders', 'renderers', 'meshes', 'uv_references', 'errors']}
    input_bundles = []
    counts = Counter()
    for index, name in enumerate(bundle_names):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', name):
            raise ValueError('Unsafe bundle name')
        bundle = bundles_dir / name
        if bundle.is_symlink() or not bundle.is_file():
            raise ValueError(f'Missing or linked bundle: {bundle}')
        stat = bundle.stat()
        if stat.st_size > args.max_bundle_bytes:
            raise ValueError(f'Bundle byte budget exceeded: {name}')
        print(f'[{index+1}/{len(bundle_names)}] {name}', flush=True)
        fingerprint = dict(name=name, bytes=stat.st_size, mtime_ns=stat.st_mtime_ns, sha256=sha256(bundle))
        result = scan_bundle(bundle, output, targets, args.max_objects, args.meshes_per_material)
        after = bundle.stat()
        if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError(f'Input changed during inspection: {name}')
        fingerprint['object_counts'] = result.pop('object_counts')
        counts.update(fingerprint['object_counts'])
        input_bundles.append(fingerprint)
        for key in combined:
            combined[key].extend(result[key])
        del result
        gc.collect()  # Retain metadata records, release the previous Unity bundle and resources.
    for key in ['textures', 'materials', 'shaders', 'renderers', 'meshes']:
        combined[key] = deduplicate(combined[key])
    textures = {record['id']: record for record in combined['textures']}
    shaders = {record['id']: record for record in combined['shaders']}
    unresolved = []
    for material in combined['materials']:
        shader = shaders.get(material['shader_id'])
        material['shader_name'] = shader['name'] if shader else None
        if not shader:
            unresolved.append(dict(material_id=material['id'], property='shader', pointer=material['shader_id']))
        for slot in material['textures']:
            texture = textures.get(slot['texture_id'])
            slot['texture_name'] = texture['name'] if texture else None
            if slot['texture_id'] and not texture:
                unresolved.append(dict(material_id=material['id'], property=slot['property'], pointer=slot['texture_id']))
    extract_cross_bundle_references(combined, bundles_dir, output, targets, args.meshes_per_material)
    report = dict(schema_version=1, scope=args.scope if not args.bundle else 'explicit_bundles',
                  manifest_sha256=sha256(manifest), manifest_asset_locations=len(assets),
                  manifest_image_locations=sum(Path(a['path']).suffix.lower() in IMAGE_EXTENSIONS for a in assets),
                  game_root=str(game), input_bundles=input_bundles, object_counts=dict(counts),
                  manifest_assets=assets, unresolved=unresolved, **combined)
    report['summary'] = summarize(combined['textures'], combined['materials'], combined['renderers'], unresolved)
    write_json(output / 'inventory.json', report)
    write_json(output / 'summary.json', dict(schema_version=1, manifest_sha256=report['manifest_sha256'],
               scope=report['scope'], bundles_scanned=len(input_bundles), manifest_asset_locations=len(assets),
               manifest_image_locations=report['manifest_image_locations'], **report['summary']))
    print(json.dumps(report['summary'], sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--bundles', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'local/texture-inventory')
    parser.add_argument('--scope', choices=['all', 'image-bundles'], default='all')
    parser.add_argument('--bundle', action='append', help='Inspect explicit bundle name(s), label partial scope')
    parser.add_argument('--inspect-material', action='append')
    parser.add_argument('--max-bundles', type=int, default=1024)
    parser.add_argument('--max-bundle-bytes', type=int, default=3 * 1024**3)
    parser.add_argument('--max-objects', type=int, default=750000)
    parser.add_argument('--meshes-per-material', type=int, default=3)
    args = parser.parse_args()
    if min(args.max_bundles, args.max_bundle_bytes, args.max_objects, args.meshes_per_material) <= 0:
        parser.error('Budgets must be positive')
    run(args)


if __name__ == '__main__':
    main()
