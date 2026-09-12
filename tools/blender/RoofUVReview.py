"""Build an isolated Blender comparison using original roof UV0 and material slots.

Run inside Blender with __file__ set to this path. All original-containing
outputs stay under ignored local/roof-review. This is an albedo/UV review only.
"""
import importlib.util
import json
import math
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'local/roof-review'
SCENE_NAME = 'VI Roof UV Review'
PROMPT = 'lets continue with our work, keep going through it progressing it'

_spec = importlib.util.spec_from_file_location('vi_uv_helpers', Path(__file__).with_name('UVReview.py'))
helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helpers)


def scene_snapshot(scene):
    result = helpers.snapshot(scene)
    for obj in scene.objects:
        result[obj.name]['materials'] = [
            {'link': slot.link, 'name': slot.material.name if slot.material else None}
            for slot in obj.material_slots
        ]
    return result


def obj_face_data(path):
    """Keep each UnityPy OBJ group as a submesh, including its UV face corners."""
    uvs, groups, current = [], [], None
    for line in path.read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == 'vt':
            uvs.append(tuple(map(float, parts[1:3])))
        elif parts[0] == 'g':
            if current and current['faces']:
                groups.append(current)
            current = {'name': parts[1], 'faces': [], 'face_lines': []}
        elif parts[0] == 'f':
            if current is None:
                raise ValueError('Expected UnityPy OBJ submesh groups')
            current['faces'].append([int(part.split('/')[1]) - 1 for part in parts[1:]])
            current['face_lines'].append(line)
    if current and current['faces']:
        groups.append(current)
    return uvs, groups


def selected_mesh(source):
    path = ROOT / source['local_obj']
    if helpers.digest(path) != source['sha256']:
        raise ValueError('Original mesh differs from local layout evidence')
    uv, groups = obj_face_data(path)
    counts = [len(group['faces']) for group in groups]
    if counts != source['submesh_triangles']:
        raise ValueError('OBJ groups do not match recorded submesh counts')
    selected = set(source['selected_material_slots'])
    # A separate local OBJ retains the exact original vertex, UV and normal
    # records, with only the selected face groups. Other roof submeshes can
    # obscure the atlas surface and are outside this atlas-specific comparison.
    selected_path = OUTPUT / 'selected' / path.name
    selected_path.parent.mkdir(parents=True, exist_ok=True)
    records = [line for line in path.read_text().splitlines()
               if line.split() and line.split()[0] in ('v', 'vn', 'vt')]
    for slot, group in enumerate(groups):
        if slot in selected:
            records.append('g ' + group['name'])
            records.extend(group['face_lines'])
    selected_path.write_text('\n'.join(records) + '\n')
    mesh = helpers.obj_mesh(selected_path, Path(source['source_paths'][0]).stem)
    cursor, max_uv_error, roof_faces = 0, 0.0, 0
    for slot, group in enumerate(groups):
        if slot not in selected:
            continue
        for indices in group['faces']:
            polygon = mesh.polygons[cursor]
            polygon.material_index = 0
            roof_faces += 1
            for loop, uv_index in zip(polygon.loop_indices, indices):
                actual = mesh.uv_layers.active.data[loop].uv
                max_uv_error = max(max_uv_error, *(abs(actual[i] - uv[uv_index][i]) for i in (0, 1)))
            cursor += 1
    if max_uv_error > 1e-7:
        raise ValueError('Imported UV0 differs from original face corners')
    return mesh, {
        'mesh_id': source['mesh_id'], 'local_obj': source['local_obj'],
        'sha256': source['sha256'], 'submesh_triangle_counts': counts,
        'selected_original_material_slots': sorted(selected),
        'atlas_triangles': roof_faces, 'excluded_triangles': sum(counts) - roof_faces,
        'selected_obj': str(selected_path.relative_to(ROOT)),
        'selected_obj_sha256': helpers.digest(selected_path),
        'uv_face_corners_checked': len(mesh.loops), 'max_uv_error': max_uv_error,
        'original_uv_sha256': mesh['original_uv_sha256'],
    }


def build():
    if SCENE_NAME in bpy.data.scenes:
        raise RuntimeError('Roof review scene already exists. Preserve it before another build.')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    layout_path = OUTPUT / 'layout.json'
    fitting_path = ROOT / 'assets/meadows/roof-atlas-layout.json'
    original_path = ROOT / 'local/texture-inventory/complete/references/dd86765d1b3d0435.png'
    authored_path = ROOT / 'assets/meadows/roof-atlas-v1.png'
    inputs = {'original_albedo': original_path, 'authored_albedo': authored_path,
              'reference_layout': layout_path, 'authored_layout': fitting_path}
    for path in inputs.values():
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing or symlinked review input: ' + str(path))
    layout = json.loads(layout_path.read_text())
    fitting = json.loads(fitting_path.read_text())
    if any(region['quarter_turns'] != 0 for region in fitting['regions']):
        raise ValueError('This review expects the inspected zero-rotation atlas fit')
    if helpers.digest(original_path) != layout['original_png_sha256']:
        raise ValueError('Original texture differs from local layout evidence')
    existing_scenes = list(bpy.data.scenes)
    before = {scene.name: scene_snapshot(scene) for scene in existing_scenes}
    document_path = bpy.data.filepath
    scene = bpy.data.scenes.new(SCENE_NAME)
    scene['review_owner'] = 'Valheim Impact local roof UV review'
    scene['user_prompt'] = PROMPT
    scene['validation_scope'] = 'Original UV0 and selected submesh. Albedo-only Blender lighting.'
    bpy.context.window.scene = scene
    collection = scene.collection
    scene.render.engine = 'BLENDER_EEVEE'
    scene.eevee.shadow_pool_size = '1024'
    scene.eevee.shadow_ray_count = 2
    scene.render.resolution_x, scene.render.resolution_y = 3840, 2160
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '8'
    scene.render.filepath = str(OUTPUT / 'roof-review-4k.png')
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'AgX'
    scene.world = bpy.data.worlds.new('VI Roof Review World')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.022, 0.036, 0.052, 1)
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.65
    camera_data = bpy.data.cameras.new('VI Roof Review Camera')
    camera = bpy.data.objects.new('VI Roof Review Camera', camera_data)
    collection.objects.link(camera)
    camera.location = (0, -24, 16)
    center = Vector((0, 0, 0))
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera_data.type, camera_data.ortho_scale = 'ORTHO', 20
    scene.camera = camera
    right = camera.rotation_euler.to_quaternion() @ Vector((1, 0, 0))
    up = camera.rotation_euler.to_quaternion() @ Vector((0, 1, 0))
    toward_camera = camera.location.normalized()
    white = helpers.material('Roof Typography', (0.82, 0.88, 0.92), True)
    muted = helpers.material('Roof Muted Typography', (0.42, 0.53, 0.62), True)
    accent = helpers.material('Roof Accent Typography', (0.71, 0.79, 0.52), True)

    def text(body, x, y, size=0.22, align='LEFT', mat=white):
        curve = bpy.data.curves.new('VI Roof Review Label', 'FONT')
        curve.body, curve.size, curve.align_x = body, size, align
        obj = bpy.data.objects.new('VI Roof Review ' + body[:36], curve)
        collection.objects.link(obj)
        obj.location = right*x + up*y + toward_camera*8
        obj.rotation_euler = camera.rotation_euler
        obj.data.materials.append(mat)
        return obj

    text('VALHEIM IMPACT', -9.2, 4.88, 0.38)
    text('ROOF ATLAS  /  ACTUAL MESH UV0', -9.18, 4.48, 0.19, mat=muted)
    text('ORIGINAL  |  128 PX', -9.18, 3.33, 0.17, mat=muted)
    text('AUTHORED  |  1024 PX', -9.18, -0.53, 0.17, mat=accent)
    original = helpers.image_material('Roof Original', original_path, (1.0, 1.0))
    authored = helpers.image_material('Roof Authored', authored_path, (1.0, 1.0))
    # The observed wood_roof_d sampler is Point/Repeat. Blender Closest follows
    # the same base-level point sampling; this does not validate native mipmaps.
    for mat in (original, authored):
        next(node for node in mat.node_tree.nodes if node.type == 'TEX_IMAGE').interpolation = 'Closest'
    specs = [
        ('Wood_roof_67.obj', '67 ROOF', -5.7, 0),
        ('Wood_roof_IC_67.obj', 'INNER CORNER', 0.5, 180),
        ('Wood_roof_IC_67_LOD.obj', 'INNER CORNER LOD', 6.7, 180),
    ]
    evidence = []
    for filename, label, x, yaw in specs:
        source = next(item for item in layout['meshes'] if Path(item['source_paths'][0]).name == filename)
        mesh, proof = selected_mesh(source)
        mesh.materials.append(original)
        slot = proof['selected_original_material_slots'][0]
        text(label, x, 3.99, 0.24, 'CENTER')
        text(f'slot {slot}  /  {proof["atlas_triangles"]} atlas triangles', x, 3.65, 0.18, 'CENTER', muted)
        pair = []
        for label_suffix, y, mat in [('Original', 1.73, original), ('Authored', -2.12, authored)]:
            model = bpy.data.objects.new('VI Roof Review ' + filename[:-4] + ' ' + label_suffix, mesh)
            collection.objects.link(model)
            model.material_slots[0].link = 'OBJECT'
            model.material_slots[0].material = mat
            model.rotation_euler.z = math.radians(yaw)
            rotation = model.rotation_euler.to_matrix()
            used_vertices = {index for polygon in mesh.polygons for index in polygon.vertices}
            points = [rotation @ mesh.vertices[index].co for index in used_vertices]
            projected_x = [point.dot(right) for point in points]
            projected_y = [point.dot(up) for point in points]
            amount = min(4.6 / (max(projected_x) - min(projected_x)),
                         2.95 / (max(projected_y) - min(projected_y)))
            midpoint = sum(points, Vector()) / len(points)
            # Centre the projected bounds rather than the vertex distribution.
            midpoint += right*((max(projected_x)+min(projected_x))/2-midpoint.dot(right))
            midpoint += up*((max(projected_y)+min(projected_y))/2-midpoint.dot(up))
            model.scale = (amount,) * 3
            model.location = right*x + up*y - midpoint*amount
            pair.append(model.name)
        proof['objects'] = pair
        proof['pair_shares_mesh_and_uv'] = bpy.data.objects[pair[0]].data == bpy.data.objects[pair[1]].data
        proof['review_yaw_degrees'] = yaw
        evidence.append(proof)
    for name, location, energy, size, color in [
        ('Key', (-8, -10, 14), 2600, 9, (1.0, 0.92, 0.80)),
        ('Fill', (9, -8, 8), 2200, 10, (0.80, 0.88, 1.0)),
        ('Rim', (0, 5, 10), 1500, 8, (0.84, 0.92, 1.0)),
    ]:
        data = bpy.data.lights.new('VI Roof Review ' + name, 'AREA')
        data.energy, data.shape, data.size, data.color = energy, 'DISK', size, color
        obj = bpy.data.objects.new('VI Roof Review ' + name, data)
        collection.objects.link(obj)
        obj.location = location
        obj.rotation_euler = (-obj.location).to_track_quat('-Z', 'Y').to_euler()
    text('UV scale (1, 1)  /  offset (0, 0)  /  both atlas regions retain their original grain axes.', -9.18, -4.12, 0.20)
    text('Isolated wood_roof_mat submeshes. Other material slots are excluded from this atlas comparison.', -9.18, -4.49, 0.19, mat=muted)
    text('Albedo-only Blender review. Native shader, mipmaps, weather, placement and LOD transitions need separate validation.', -9.18, -4.87, 0.16, mat=muted)
    after = {item.name: scene_snapshot(item) for item in existing_scenes}
    if before != after:
        raise RuntimeError('An existing scene changed during isolated review build')
    report = {
        'schema_version': 1, 'scene': scene.name, 'resolution': [3840, 2160],
        'render_engine': scene.render.engine, 'view_transform': scene.view_settings.view_transform,
        'user_prompt': PROMPT, 'albedo_only': True, 'uv_scale': [1, 1], 'uv_offset': [0, 0],
        'sampler': {'blender': 'Closest / REPEAT', 'native_observed': 'Point / Repeat',
                    'limitation': 'Native mipmaps and sampler parity are not rendered or approved here.'},
        'original_scene_snapshots_before': before, 'original_scene_snapshots_after': after,
        'all_existing_scenes_preserved': before == after,
        'open_document_path_before': document_path,
        'inputs': {key: {'path': str(path.relative_to(ROOT)), 'sha256': helpers.digest(path)}
                   for key, path in inputs.items()},
        'meshes': evidence,
        'limits': ['Generic Principled albedo lighting, no Custom/Piece shader or normal map.',
                   'Other material slots are excluded so overlapping roof panels do not obscure the selected atlas faces.',
                   'Samples are positioned individually, without prefab hierarchy or placement transforms.',
                   'Three representative wood_roof_mat meshes, not every roof or every LOD.'],
    }
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / 'roof-review.blend'), copy=True)
    report['open_document_path_after'] = bpy.data.filepath
    report['open_document_path_preserved'] = bpy.data.filepath == document_path
    if not report['open_document_path_preserved']:
        raise RuntimeError('Saving review changed the open document path')
    (OUTPUT / 'blender-review.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'scene': scene.name, 'all_existing_scenes_preserved': True,
                      'blend': str(OUTPUT / 'roof-review.blend'), 'meshes': evidence}))


if __name__ == '__main__':
    build()
