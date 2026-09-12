"""Create a separate, local Blender UV review scene without changing existing objects.

Run inside Blender with __file__ set to this path. Inputs and outputs are local;
this is albedo/UV evidence, not a reproduction of Valheim's shaders or weather.
"""
import hashlib
import json
import math
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'local/uv-review'
REFERENCES = ROOT / 'local/texture-inventory/complete/references'
SCENE_NAME = 'VI UV Review'
PROMPT = 'keep going, lets see this project through. there are a lot of textures from valheim that need replacing from it, also we should disable the current mods in valheim so we are only testing ours that we create as we go.'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(scene):
    return {obj.name: dict(type=obj.type, matrix=[list(row) for row in obj.matrix_world],
                          data=obj.data.name if obj.data else None,
                          vertices=len(obj.data.vertices) if obj.type == 'MESH' else None)
            for obj in scene.objects}


def material(name, color, emission=False):
    mat = bpy.data.materials.new('VI Review ' + name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    shader = nodes.new('ShaderNodeEmission' if emission else 'ShaderNodeBsdfPrincipled')
    shader.inputs['Color' if emission else 'Base Color'].default_value = (*color, 1)
    if not emission:
        shader.inputs['Roughness'].default_value = 0.72
    mat.node_tree.links.new(shader.outputs[0], output.inputs['Surface'])
    return mat


def image_material(name, image_path, uv_scale):
    mat = material(name, (1, 1, 1))
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    image = bpy.data.images.load(str(image_path), check_existing=False)
    image.colorspace_settings.name = 'sRGB'
    texture = nodes.new('ShaderNodeTexImage')
    texture.image = image
    texture.interpolation = 'Linear'
    texture.extension = 'REPEAT'
    texture.label = image_path.name
    texcoord = nodes.new('ShaderNodeTexCoord')
    multiply = nodes.new('ShaderNodeVectorMath')
    multiply.operation = 'MULTIPLY'
    multiply.inputs[1].default_value = (*uv_scale, 1)
    multiply.label = 'Exact material UV scale; offset (0, 0)'
    links.new(texcoord.outputs['UV'], multiply.inputs[0])
    links.new(multiply.outputs[0], texture.inputs['Vector'])
    shader = next(node for node in nodes if node.type == 'BSDF_PRINCIPLED')
    links.new(texture.outputs['Color'], shader.inputs['Base Color'])
    shader.inputs['Alpha'].default_value = 1
    mat['uv_scale'] = list(uv_scale)
    mat['uv_offset'] = [0.0, 0.0]
    mat['albedo_only_review'] = True
    return mat


def obj_mesh(path, name, pole_transform=None):
    positions, normals, uv, faces, uvfaces = [], [], [], [], []
    for line in path.read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == 'v':
            positions.append(Vector(tuple(map(float, parts[1:4]))))
        elif parts[0] == 'vn':
            normals.append(Vector(tuple(map(float, parts[1:4]))))
        elif parts[0] == 'vt':
            uv.append(tuple(map(float, parts[1:3])))
        elif parts[0] == 'f':
            indices = [part.split('/') for part in parts[1:]]
            faces.append([int(index[0]) - 1 for index in indices])
            uvfaces.append([int(index[1]) - 1 for index in indices])
    # OBJ exporter mirrors Unity X. Convert back, apply the observed local
    # prefab shape transform if present, then convert to Blender's Z-up axes.
    from_obj = Matrix.Diagonal((-1.0, 1.0, 1.0, 1.0))
    to_blender = Matrix(((-1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    shape = Matrix.Identity(4)
    if pole_transform:
        rotation = pole_transform['rotation']
        scale = pole_transform['scale']
        shape = Quaternion((rotation['w'], rotation['x'], rotation['y'], rotation['z'])).to_matrix().to_4x4()
        shape = shape @ Matrix.Diagonal((scale['x'], scale['y'], scale['z'], 1))
    transform = to_blender @ shape @ from_obj
    vertices = [transform @ vertex for vertex in positions]
    normal_transform = transform.to_3x3().inverted().transposed()
    converted_normals = [(normal_transform @ normal).normalized() for normal in normals]
    mesh = bpy.data.meshes.new('VI Review ' + name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    layer = mesh.uv_layers.new(name='Original UV0')
    for polygon, indices in zip(mesh.polygons, uvfaces):
        for loop_index, uv_index in zip(polygon.loop_indices, indices):
            layer.data[loop_index].uv = uv[uv_index]
        polygon.use_smooth = True
    if len(converted_normals) == len(vertices):
        mesh.normals_split_custom_set_from_vertices(converted_normals)
    mesh['original_obj_sha256'] = digest(path)
    mesh['original_uv_sha256'] = hashlib.sha256(json.dumps(uvfaces).encode() + json.dumps(uv).encode()).hexdigest()
    return mesh


def build():
    if SCENE_NAME in bpy.data.scenes:
        raise RuntimeError('VI UV Review already exists. Preserve or explicitly review it before rebuilding.')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    original_scene = bpy.context.scene
    before = snapshot(original_scene)
    inputs = {
        'rock_mesh': REFERENCES / '9d1363d98f9e24cd.obj',
        'pole_mesh': REFERENCES / '30e1f6076349ad28.obj',
        'rock_original': REFERENCES / '3f13565a76703a3b.png',
        'timber_original': REFERENCES / '26074fb3ca5fb45c.png',
        'rock_authored': ROOT / 'build/staging/meadows/granite_hd_albedo.png',
        'timber_authored': ROOT / 'build/staging/meadows/timber_hd_albedo.png',
    }
    for path in inputs.values():
        if not path.is_file() or path.is_symlink():
            raise RuntimeError('Missing or linked review input: ' + str(path))
    pole_transform = json.loads((OUTPUT / 'pole-transform.json').read_text())[0]
    scene = bpy.data.scenes.new(SCENE_NAME)
    scene['review_owner'] = 'Valheim Impact local UV review'
    scene['user_prompt'] = PROMPT
    scene['validation_scope'] = 'Actual mesh UV0 with observed material scale. Albedo-only Blender lighting.'
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
    scene.render.filepath = str(OUTPUT / 'uv-review-4k.png')
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'AgX'
    scene.world = bpy.data.worlds.new('VI Review World')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.12, 0.16, 0.21, 1)
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.4
    camera_data = bpy.data.cameras.new('VI Review Camera')
    camera = bpy.data.objects.new('VI Review Camera', camera_data)
    collection.objects.link(camera)
    camera.location = (0, -18, 10.0)
    center = Vector((0, 0, 1.5))
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera_data.type = 'ORTHO'
    camera_data.ortho_scale = 18
    camera_data.lens = 50
    scene.camera = camera
    right = camera.rotation_euler.to_quaternion() @ Vector((1, 0, 0))
    up = camera.rotation_euler.to_quaternion() @ Vector((0, 1, 0))
    toward_camera = (camera.location - center).normalized()
    white = material('Typography', (0.81, 0.86, 0.9), True)
    muted = material('Muted Typography', (0.36, 0.47, 0.56), True)
    accent = material('Accent Typography', (0.56, 0.77, 0.68), True)

    def text(body, x, y, size=0.21, align='LEFT', mat=white):
        curve = bpy.data.curves.new('VI Review Label', 'FONT')
        curve.body, curve.size, curve.align_x = body, size, align
        curve.space_character = 1.08
        obj = bpy.data.objects.new('VI Review ' + body[:36], curve)
        collection.objects.link(obj)
        obj.location = center + right*x + up*y + toward_camera*5
        obj.rotation_euler = camera.rotation_euler
        obj.data.materials.append(mat)
        return obj

    text('VALHEIM IMPACT', -8.15, 4.15, 0.42)
    text('LOCAL UV REVIEW  /  ORIGINAL GAME MESHES', -8.12, 3.74, 0.19, mat=muted)
    text('STONE  /  stone_huge', -4.1, 2.92, 0.24, 'CENTER', accent)
    text('TIMBER  /  woodpole', 4.1, 2.92, 0.24, 'CENTER', accent)
    for x, label in [(-6.15, 'Original'), (-2.05, 'Authored'), (2.05, 'Original'), (6.15, 'Authored')]:
        text(label, x, 2.49, 0.21, 'CENTER')
    floor_material = material('Ground', (0.026, 0.041, 0.055))
    floor_mesh = bpy.data.meshes.new('VI Review Ground')
    floor_mesh.from_pydata([(-30,-30,-0.12),(30,-30,-0.12),(30,30,-0.12),(-30,30,-0.12)], [], [(0,1,2,3)])
    floor = bpy.data.objects.new('VI Review Ground', floor_mesh)
    collection.objects.link(floor)
    floor.data.materials.append(floor_material)
    rock = obj_mesh(inputs['rock_mesh'], 'Rock_3_Untitled')
    pole = obj_mesh(inputs['pole_mesh'], 'wood_pole with local shape transform', pole_transform)
    models = []
    for name, mesh, texture, x, scale in [
        ('Rock Original',rock,inputs['rock_original'],-6.15,(1.0,1.0)),
        ('Rock Authored',rock,inputs['rock_authored'],-2.05,(1.0,1.0)),
        ('Pole Original',pole,inputs['timber_original'],2.05,(0.3,0.13)),
        ('Pole Authored',pole,inputs['timber_authored'],6.15,(0.3,0.13)),
    ]:
        model = bpy.data.objects.new('VI Review ' + name, mesh)
        collection.objects.link(model)
        # Material links are per object so the original/authored pair shares
        # identical geometry and the same UV data without sharing its material.
        mat = image_material(name, texture, scale)
        if not mesh.materials:
            mesh.materials.append(mat)
        model.material_slots[0].link = 'OBJECT'
        model.material_slots[0].material = mat
        points = [Vector(corner) for corner in model.bound_box]
        low = Vector(tuple(min(point[axis] for point in points) for axis in range(3)))
        high = Vector(tuple(max(point[axis] for point in points) for axis in range(3)))
        size = high - low
        amount = (3.02 if mesh == rock else 3.05) / size.z
        model.scale = (amount,)*3
        model.rotation_euler.z = math.radians(-18 if mesh == rock else 18)
        model.location = Vector((x,0,0.05)) - Vector(((low.x+high.x)*0.5*amount,(low.y+high.y)*0.5*amount,low.z*amount))
        models.append(model)
    for name, location, energy, size, color in [
        ('Key',(-7,-7,11),2000,8,(1.0,0.91,0.79)),
        ('Fill',(7,-3,8),1500,8,(0.75,0.85,1.0)),
        ('Rim',(0,4,8),1700,7,(0.85,0.92,1.0)),
    ]:
        light_data = bpy.data.lights.new('VI Review ' + name, 'AREA')
        light_data.energy, light_data.shape, light_data.size, light_data.color = energy, 'DISK', size, color
        light = bpy.data.objects.new('VI Review ' + name, light_data)
        collection.objects.link(light)
        light.location = location
        light.rotation_euler = (Vector((0,0,1))-light.location).to_track_quat('-Z','Y').to_euler()
    text('UV scale (1, 1)  /  offset (0, 0)', -4.1, -2.18, 0.19, 'CENTER', muted)
    text('UV scale (0.3, 0.13)  /  offset (0, 0)', 4.1, -2.18, 0.19, 'CENTER', muted)
    text('rock_256: 512 px  |  authored: 1024 px', -4.1, -2.56, 0.17, 'CENTER', muted)
    text('Planks5c_low: 128 px  |  authored: 1024 px', 4.1, -2.56, 0.17, 'CENTER', muted)
    text('Same geometry, UV0 and material scale within each pair.', -8.12, -3.70, 0.21)
    text('Albedo-only Blender lighting. Native shader, moss, normals, weather and LOD results require separate validation.', -8.12, -4.10, 0.16, mat=muted)
    after = snapshot(original_scene)
    if before != after:
        raise RuntimeError('Existing scene objects changed unexpectedly')
    report = dict(scene=scene.name,original_scene=original_scene.name,original_objects_before=before,
                  original_objects_after=after,original_scene_preserved=before==after,
                  resolution=[3840,2160],render_engine=scene.render.engine,
                  authored_albedo_only=True,original_uv0_preserved=True,
                  pole_shape_transform=pole_transform,
                  inputs={key:dict(path=str(path),sha256=digest(path)) for key,path in inputs.items()},
                  models=[dict(name=obj.name,mesh=obj.data.name,vertices=len(obj.data.vertices),triangles=len(obj.data.polygons),
                               uv_scale=list(obj.material_slots[0].material['uv_scale']),uv_offset=[0,0],
                               mesh_source_sha256=obj.data['original_obj_sha256'],uv_source_sha256=obj.data['original_uv_sha256']) for obj in models],
                  limitation='UV/albedo inspection only. No native-game rendering approval or performance conclusion.')
    (OUTPUT/'blender-review.json').write_text(json.dumps(report,indent=2)+'\n')
    # Save an isolated copy, preserving the open document path and all existing
    # scenes/objects. The copy opens directly on the new review scene.
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT/'uv-review.blend'), copy=True)
    print(json.dumps(dict(scene=scene.name,blend=str(OUTPUT/'uv-review.blend'),render=scene.render.filepath,
                          original_scene_preserved=True,models=[obj.name for obj in models])))


if __name__ == '__main__':
    build()
