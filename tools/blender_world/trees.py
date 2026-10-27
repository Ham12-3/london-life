"""Replace the placeholder trees with the Ez-Tree oaks, ashes and aspens (as in the web app): real
branches with bark textures and alpha-cut leaf cards, at every mapped tree, sized to its height.

    node tools/blender_world/trees_export.mjs
    python tools/blender_mcp.py run tools/blender_world/trees.py
"""
import bpy
import json
import math
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "work", "blender", "trees")
variants = json.load(open(os.path.join(SRC, "trees.json")))
world = json.load(open(os.path.join(ROOT, "public", "world.json"), encoding="utf-8"))
# Plus the trees the landmark models add (the plane trees at the main gates), as the web app does.
for L in json.load(open(os.path.join(ROOT, "public", "assets", "landmarks", "landmarks.json"))):
    world["trees"] += L.get("trees", [])


def srgb(h):
    c = [((h >> s) & 255) / 255 for s in (16, 8, 0)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def img(name, color=True):
    im = bpy.data.images.load(os.path.join(SRC, name), check_existing=True)
    im.colorspace_settings.name = "sRGB" if color else "Non-Color"
    return im


def bark_material(v):
    name = "bark_" + v["bark"]["color"].split(".")[0]
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    uvmap = nt.nodes.new("ShaderNodeMapping")
    uvmap.inputs["Scale"].default_value = (v["bark"]["repeat"][0], v["bark"]["repeat"][1], 1)
    nt.links.new(nt.nodes.new("ShaderNodeTexCoord").outputs["UV"], uvmap.inputs[0])
    col = nt.nodes.new("ShaderNodeTexImage")
    col.image = img(v["bark"]["color"])
    nt.links.new(uvmap.outputs[0], col.inputs[0])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
    mix.inputs[0].default_value = 1
    nt.links.new(col.outputs[0], mix.inputs[6])
    mix.inputs[7].default_value = (*srgb(v["bark"]["tint"]), 1)
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    if v["bark"]["normal"]:
        nrm = nt.nodes.new("ShaderNodeTexImage")
        nrm.image = img(v["bark"]["normal"], False)
        nt.links.new(uvmap.outputs[0], nrm.inputs[0])
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(nrm.outputs[0], nm.inputs["Color"])
        nt.links.new(nm.outputs[0], bsdf.inputs["Normal"])
    bsdf.inputs["Roughness"].default_value = 0.9
    return m


def leaf_material(v):
    name = "leaf_" + v["leaf"]["color"].split(".")[0]
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    out = nt.nodes["Material Output"]
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img(v["leaf"]["color"])
    nt.links.new(nt.nodes.new("ShaderNodeTexCoord").outputs["UV"], tex.inputs[0])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
    mix.inputs[0].default_value = 1
    nt.links.new(tex.outputs[0], mix.inputs[6])
    mix.inputs[7].default_value = (*srgb(v["leaf"]["tint"]), 1)
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.75
    # Light through the leaves: blend in a translucent shader.
    trans = nt.nodes.new("ShaderNodeBsdfTranslucent")
    nt.links.new(mix.outputs[2], trans.inputs["Color"])
    blend = nt.nodes.new("ShaderNodeMixShader")
    blend.inputs[0].default_value = 0.3
    nt.links.new(bsdf.outputs[0], blend.inputs[1])
    nt.links.new(trans.outputs[0], blend.inputs[2])
    # Cut the leaf shape out of the card.
    clip = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(tex.outputs["Alpha"], clip.inputs[0])
    nt.links.new(nt.nodes.new("ShaderNodeBsdfTransparent").outputs[0], clip.inputs[1])
    nt.links.new(blend.outputs[0], clip.inputs[2])
    nt.links.new(clip.outputs[0], out.inputs["Surface"])
    if hasattr(m, "surface_render_method"):
        m.surface_render_method = "DITHERED"
    else:
        m.blend_method = "CLIP"
    m.use_backface_culling = False
    return m


def make_mesh(v):
    me = bpy.data.meshes.new("tree_" + v["name"])
    verts, faces, uvs, mat_idx = [], [], [], []
    for part, mi in ((v["branches"], 0), (v["leaves"], 1)):
        base = len(verts)
        p = part["position"]
        verts += [(p[i], -p[i + 2], p[i + 1]) for i in range(0, len(p), 3)]  # three.js y-up -> Blender z-up
        uv = part["uv"] or [0.0] * (len(p) // 3 * 2)
        idx = part["index"]
        for t in range(0, len(idx), 3):
            f = (base + idx[t], base + idx[t + 1], base + idx[t + 2])
            faces.append(f)
            uvs.append([(uv[2 * (k - base)], uv[2 * (k - base) + 1]) for k in f])
            mat_idx.append(mi)
    me.from_pydata(verts, [], faces)
    me.update()
    layer = me.uv_layers.new(name="UVMap")
    for poly, fuv in zip(me.polygons, uvs):
        for li, uvv in zip(poly.loop_indices, fuv):
            layer.data[li].uv = uvv
    me.polygons.foreach_set("material_index", mat_idx)
    me.polygons.foreach_set("use_smooth", [True] * len(faces))
    me.materials.append(bark_material(v))
    me.materials.append(leaf_material(v))
    return me


trees_col = bpy.data.collections["Trees"]
for o in list(trees_col.objects):
    bpy.data.objects.remove(o, do_unlink=True)
meshes = [make_mesh(v) for v in variants]
plane = next((k for k, v in enumerate(variants) if v.get("plane")), None)
others = [k for k in range(len(variants)) if k != plane]
for i, (x, z, h) in enumerate(world["trees"]):
    r = abs(math.sin(x * 12.9898 + z * 78.233)) % 1
    height = h * (0.9 + r * 0.25)
    # London planes for 40% of trees, the rest cycling the other species: the web app's rule.
    v = plane if plane is not None and abs(math.sin(x * 4.17 + z * 9.31)) % 1 < 0.4 else others[i % len(others)]
    o = bpy.data.objects.new(f"Tree.{i:03d}", meshes[v])
    o.location = (x, -z, 0)
    o.scale = (height, height, height)
    o.rotation_euler = (0, 0, r * 6.28)
    trees_col.objects.link(o)
