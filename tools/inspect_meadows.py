"""Inspect exact installed material pointers and extract local alpha references."""
import argparse
import json
from pathlib import Path

import UnityPy

TARGETS = {'woodwall', 'woodpole', 'wood_roof_mat', 'stone_huge', 'beech_leaf',
           'beech_bark', 'birch_leaf', 'grasscross', 'grasscross_meadows', 'grasscross_meadows_short'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / 'local/meadows-inspection'
    output.mkdir(parents=True, exist_ok=True)
    environment = UnityPy.load(str(args.bundle))
    materials, textures = [], {}
    for obj in environment.objects:
        if obj.type.name != 'Material':
            continue
        mat = obj.read()
        if mat.m_Name not in TARGETS:
            continue
        tree = obj.read_typetree()
        record = {'name': mat.m_Name, 'path_id': obj.path_id,
                  'shader_pointer': tree['m_Shader'], 'textures': []}
        for property_name, slot in mat.m_SavedProperties.m_TexEnvs:
            if not slot.m_Texture.path_id:
                continue
            try:
                tex_obj = slot.m_Texture.deref()
                tex = tex_obj.read()
                identity = str(tex_obj.path_id)
                if identity not in textures:
                    pixels = tex.image.convert('RGBA')
                    filename = identity + '.png'
                    pixels.save(output / filename)
                    alpha = pixels.getchannel('A')
                    histogram = alpha.histogram()
                    textures[identity] = dict(name=tex.m_Name, path_id=tex_obj.path_id,
                        dimensions=[tex.m_Width, tex.m_Height], texture_format=tex.m_TextureFormat,
                        mip_count=tex.m_MipCount, color_space=tex.m_ColorSpace,
                        alpha_extrema=list(alpha.getextrema()), alpha_zero=histogram[0],
                        alpha_opaque=histogram[255], local_png=filename)
                record['textures'].append(dict(property=property_name, texture_id=identity,
                    name=tex.m_Name, scale={'x':slot.m_Scale.x, 'y':slot.m_Scale.y},
                    offset={'x':slot.m_Offset.x, 'y':slot.m_Offset.y}))
            except (FileNotFoundError, KeyError) as error:
                record['textures'].append(dict(property=property_name, unresolved=str(error)))
        materials.append(record)
    report = dict(bundle=str(args.bundle.resolve()), materials=materials, textures=list(textures.values()),
                  game_uv_mesh_validation=False, visible_renderer_validation=False,
                  note='Direct installed material pointers. Original reference PNGs stay local and excluded from staging.')
    (output / 'inspection.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'output': str(output), 'materials': len(materials), 'textures': len(textures)}))


if __name__ == '__main__':
    main()
