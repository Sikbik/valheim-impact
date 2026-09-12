"""Review original roof UVs with authored standard and corner fringe cutouts.

Run inside Blender. Original-containing images and geometry remain under local/.
Existing scenes and the current document are preserved. No native shader claim.
"""
import importlib.util
import json
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'local/meadows-pass/straw-uv'


def load_helper(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helpers = load_helper('straw_uv_helpers', 'UVReview.py')
roof = load_helper('straw_roof_helpers', 'RoofUVReview.py')


def cutout_material(name, path):
    result = helpers.image_material(name, path, (1, 1))
    result.use_backface_culling = False
    nodes, links = result.node_tree.nodes, result.node_tree.links
    texture = next(node for node in nodes if node.type == 'TEX_IMAGE')
    texture.interpolation = 'Closest'
    clip = nodes.new('ShaderNodeMath')
    clip.operation = 'GREATER_THAN'
    clip.inputs[1].default_value = 175.5 / 255  # Integer alpha >= 176 at cutoff 0.69.
    links.new(texture.outputs['Alpha'], clip.inputs[0])
    shader = next(node for node in nodes if node.type == 'BSDF_PRINCIPLED')
    links.new(clip.outputs[0], shader.inputs['Alpha'])
    return result


def build():
    name = 'VI Straw Fringe UV Review'
    if name in bpy.data.scenes:
        raise RuntimeError('Preserve the existing straw review before rebuilding')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    notes_path = ROOT / 'local/roof-review/default-roof/notes.json'
    notes = json.loads(notes_path.read_text())
    previous_scene = bpy.context.window.scene
    document_path = bpy.data.filepath
    existing = list(bpy.data.scenes)
    before = {scene.name: roof.scene_snapshot(scene) for scene in existing}
    scene = bpy.data.scenes.new(name)
    bpy.context.window.scene = scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x, scene.render.resolution_y = 3840, 2160
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.view_settings.view_transform = 'AgX'
    scene.world = bpy.data.worlds.new(name + ' World')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.027, .045, .07, 1)
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = .65
    camera_data = bpy.data.cameras.new(name + ' Camera')
    camera = bpy.data.objects.new(name + ' Camera', camera_data)
    scene.collection.objects.link(camera)
    camera.location = (0, -24, 18)
    camera.rotation_euler = (-camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera_data.type, camera_data.ortho_scale = 'ORTHO', 19
    scene.camera = camera
    right = camera.rotation_euler.to_quaternion() @ Vector((1, 0, 0))
    up = camera.rotation_euler.to_quaternion() @ Vector((0, 1, 0))
    toward = camera.location.normalized()
    label_material = helpers.material('Straw labels', (.82, .86, .9), True)

    def label(body, x, y, size=.2):
        data = bpy.data.curves.new(name + ' Label', 'FONT')
        data.body, data.size = body, size
        obj = bpy.data.objects.new(name + ' ' + body[:30], data)
        scene.collection.objects.link(obj)
        obj.location = right * x + up * y + toward * 10
        obj.rotation_euler = camera.rotation_euler
        data.materials.append(label_material)

    label('VALHEIM IMPACT  /  STRAW FRINGE UV REVIEW', -8.8, 4.6, .33)
    label('Same original meshes, UV0, material slot order and companion albedos in both rows.', -8.8, 4.08)
    label('ORIGINAL 64 PX', -8.8, 3.5)
    label('AUTHORED 512 PX', -8.8, -.25)
    label('Cutoff 0.69  /  Point and Repeat base-level sampling  /  no original masks in authored artwork', -8.8, -4.16, .18)
    label('Local Blender UV evidence. Game shader, weather, LOD transitions and final art approval remain separate.', -8.8, -4.63, .17)
    sources = {
        'standard_original': ROOT / 'local/roof-review/default-roof/straw_roof.png',
        'corner_original': ROOT / 'local/roof-review/default-roof/straw_roof_corner.png',
        'standard_authored': ROOT / 'assets/meadows/straw-fringe-standard-v1.png',
        'corner_authored': ROOT / 'assets/meadows/straw-fringe-corner-v1.png',
        'timber_original': ROOT / 'local/meadows-inspection/-8477877035390755812.png',
    }
    for path in sources.values():
        if not path.is_file() or path.is_symlink():
            raise ValueError('Expected a regular reviewed input')
    # These two borrowed albedos remain identical in each comparison pair.
    timber = helpers.image_material('Straw companion timber', sources['timber_original'], (1, 1))
    opaque = helpers.image_material('Straw companion opaque', sources['standard_original'], (1, 1))
    materials = {key: cutout_material(key, path) for key, path in sources.items() if key != 'timber_original'}
    report_meshes = []
    for column, filename in enumerate(('wood_roof_new.obj', 'wood_roof_45_new.obj', 'wood_roof_ocorner_45_new.obj')):
        source = next(row for row in notes['meshes'] if Path(row['local_obj']).name == filename)
        path = ROOT / source['local_obj']
        if helpers.digest(path) != source['sha256']:
            raise ValueError('Original mesh hash mismatch')
        uv, groups = roof.obj_face_data(path)
        if [len(group['faces']) for group in groups] != source['submesh_triangles']:
            raise ValueError('Original material slot topology mismatch')
        mesh = helpers.obj_mesh(path, 'VI Straw ' + source['name'])
        uv_error, cursor = 0.0, 0
        for slot, group in enumerate(groups):
            for indices in group['faces']:
                polygon = mesh.polygons[cursor]
                polygon.material_index = slot
                for loop, uv_index in zip(polygon.loop_indices, indices):
                    actual = mesh.uv_layers.active.data[loop].uv
                    uv_error = max(uv_error, *(abs(actual[i] - uv[uv_index][i]) for i in (0, 1)))
                cursor += 1
        if uv_error > 1e-7:
            raise ValueError('Imported UV corners differ')
        for material in (timber, opaque, materials['standard_original'], materials['corner_original'])[:len(groups)]:
            mesh.materials.append(material)
        x = -5.5 + column * 5.55
        label(source['name'], x - 2.35, 3.05, .22)
        points = [v.co for v in mesh.vertices]
        px, py = [v.dot(right) for v in points], [v.dot(up) for v in points]
        scale = min(4.8 / (max(px) - min(px)), 2.65 / (max(py) - min(py)))
        depth = [v.dot(toward) for v in points]
        center = (right * ((min(px) + max(px)) / 2) + up * ((min(py) + max(py)) / 2)
                  + toward * ((min(depth) + max(depth)) / 2))
        pair = []
        for suffix, y in [('original', 1.55), ('authored', -2.15)]:
            obj = bpy.data.objects.new('VI Straw ' + source['name'] + ' ' + suffix, mesh)
            scene.collection.objects.link(obj)
            obj.location = right * x + up * y - center * scale
            obj.scale = (scale,) * 3
            for slot in range(len(groups)):
                obj.material_slots[slot].link = 'OBJECT'
                obj.material_slots[slot].material = (timber if slot == 0 else opaque if slot == 1
                    else materials[('standard_' if slot == 2 else 'corner_') + suffix])
            pair.append(obj.name)
        report_meshes.append({'mesh_id': source['id'], 'name': source['name'],
                              'mesh_sha256': source['sha256'], 'submesh_triangles': source['submesh_triangles'],
                              'fringe_slots': list(range(2, len(groups))), 'uv_corners_checked': len(mesh.loops),
                              'max_uv_error': uv_error, 'pair_shares_mesh_and_uv': True,
                              'objects': pair})
    for label_text, position, energy, color in [('Key', (-7, -9, 14), 2200, (1, .9, .74)),
                                              ('Fill', (8, -7, 8), 1700, (.72, .84, 1))]:
        data = bpy.data.lights.new(name + label_text, 'AREA')
        data.energy, data.size, data.color = energy, 9, color
        obj = bpy.data.objects.new(name + label_text, data)
        scene.collection.objects.link(obj)
        obj.location = position
        obj.rotation_euler = (-obj.location).to_track_quat('-Z', 'Y').to_euler()
    after = {item.name: roof.scene_snapshot(item) for item in existing}
    if before != after:
        raise RuntimeError('An existing scene changed')
    report = {'schema_version': 1, 'meshes': report_meshes, 'cutoff': .69,
              'uv_scale': [1, 1], 'uv_offset': [0, 0], 'dimensions': [3840, 2160],
              'inputs': {key: {'sha256': helpers.digest(path), 'path': str(path.relative_to(ROOT))} for key, path in sources.items()},
              'original_scene_preserved': True, 'open_document_preserved': bpy.data.filepath == document_path,
              'companion_slots_unchanged': [0, 1], 'backface_culling_disabled': True,
              'sampler': 'Closest / Repeat, base level only', 'native_shader': False}
    (OUTPUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / 'straw-review.blend'), copy=True)
    if bpy.data.filepath != document_path:
        raise RuntimeError('Saving review changed the open document')
    scene.render.filepath = str(OUTPUT / 'roof-cutouts-top-4k.png')
    bpy.context.window.scene = previous_scene
    print(json.dumps({'scene': name, 'meshes': len(report_meshes), 'existing_scenes_preserved': True}))


if __name__ == '__main__':
    build()
