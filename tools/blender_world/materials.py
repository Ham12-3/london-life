"""Materials for the Blender zoo: Poly Haven scans (public/assets/textures) as Principled BSDFs,
box-projected in object metres (objects sit at the world origin, so that's world metres), and plain
painted/metal/glass finishes. Shared by scene.py and buildings.py.
"""
import bpy
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TEX = os.path.join(ROOT, "public", "assets", "textures")


def image(path, color):
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = "sRGB" if color else "Non-Color"
    return img


def pbr(name, tex, tile=2.0, tint=(1, 1, 1), colorize=None, rough=1.0, uv=False):
    """Principled material from a Poly Haven set, box-projected in object (= world) metres, or
    along the mesh's own UVs (in metres) when uv=True (roof slopes)."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1 / tile, 1 / tile, 1 / tile)
    nt.links.new(coord.outputs["UV" if uv else "Object"], mapping.inputs[0])

    def tex_node(kind, color):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = image(os.path.join(TEX, tex, f"{kind}.jpg"), color)
        n.projection = "FLAT" if uv else "BOX"
        n.projection_blend = 0.3
        nt.links.new(mapping.outputs[0], n.inputs[0])
        return n

    diff = tex_node("diff", True)
    col = diff.outputs[0]
    if colorize:
        bw = nt.nodes.new("ShaderNodeRGBToBW")
        nt.links.new(col, bw.inputs[0])
        mul = nt.nodes.new("ShaderNodeMix")
        mul.data_type = "RGBA"
        mul.blend_type = "MULTIPLY"
        mul.inputs[0].default_value = 1
        nt.links.new(bw.outputs[0], mul.inputs[6])
        mul.inputs[7].default_value = (*[c * 11 for c in colorize], 1)  # scan luminance ~0.09 -> target albedo
        col = mul.outputs[2]
    elif tint != (1, 1, 1):
        mul = nt.nodes.new("ShaderNodeMix")
        mul.data_type = "RGBA"
        mul.blend_type = "MULTIPLY"
        mul.inputs[0].default_value = 1
        nt.links.new(col, mul.inputs[6])
        mul.inputs[7].default_value = (*tint, 1)
        col = mul.outputs[2]
    nt.links.new(col, bsdf.inputs["Base Color"])
    arm = tex_node("arm", False)
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(arm.outputs[0], sep.inputs[0])
    if rough != 1.0:
        r = nt.nodes.new("ShaderNodeMath")
        r.operation = "MULTIPLY"
        r.inputs[1].default_value = rough
        nt.links.new(sep.outputs[1], r.inputs[0])
        nt.links.new(r.outputs[0], bsdf.inputs["Roughness"])
    else:
        nt.links.new(sep.outputs[1], bsdf.inputs["Roughness"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.35
    bw2 = nt.nodes.new("ShaderNodeRGBToBW")
    nt.links.new(diff.outputs[0], bw2.inputs[0])
    nt.links.new(bw2.outputs[0], bump.inputs["Height"])
    nt.links.new(bump.outputs[0], bsdf.inputs["Normal"])
    return m


def plain(name, color, rough=0.6, metal=0.0, alpha=1.0, transmission=0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Alpha"].default_value = alpha
    if transmission:
        b.inputs["Transmission Weight"].default_value = transmission
    return m


def srgb(h):
    c = [((h >> s) & 255) / 255 for s in (16, 8, 0)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


LAWN = (0.075, 0.13, 0.03)
MATERIALS = {
    "lawn": lambda: pbr("lawn", "sparse_grass", 3, colorize=LAWN),
    "zoo_ground": lambda: pbr("zoo_ground", "sparse_grass", 3, colorize=(0.085, 0.12, 0.04)),
    "woodland": lambda: pbr("woodland", "forest_floor", 3),
    "dirt": lambda: pbr("dirt", "park_dirt", 3),
    "sand": lambda: pbr("sand", "coast_sand_01", 3),
    "rock": lambda: pbr("rock", "aerial_rocks_02", 4),
    "paving": lambda: pbr("paving", "concrete_pavement", 3, tint=srgb(0xf0ece4)),
    "gravel": lambda: pbr("gravel", "gravel_ground_01", 2.5),
    "asphalt": lambda: pbr("asphalt", "asphalt_02", 4, tint=srgb(0xb0b0b0)),
    "steps": lambda: pbr("steps", "precast_stone_paving", 2),
    "cycleway": lambda: pbr("cycleway", "asphalt_02", 4, tint=srgb(0xd08070)),
    "boards": lambda: pbr("boards", "wood_planks", 2),
    "brick_red": lambda: pbr("brick_red", "brick_wall_02", 2, tint=srgb(0xe0a08c)),
    "brick_buff": lambda: pbr("brick_buff", "brick_wall_003", 2),
    "render": lambda: pbr("render", "white_stucco", 3, tint=srgb(0xe6e1d4)),
    "roof_flat": lambda: pbr("roof_flat", "concrete_floor_02", 3, tint=srgb(0x8e8a84)),
    "slate": lambda: pbr("slate", "roof_slates_02", 2),
    "tiles": lambda: pbr("tiles", "clay_roof_tiles", 2),
    "stone": lambda: pbr("stone", "white_stucco", 2, tint=srgb(0xe4ddcc)),
    "concrete": lambda: pbr("concrete", "concrete_floor_02", 3, tint=srgb(0xd8d4cc)),
    "concrete_white": lambda: pbr("concrete_white", "white_stucco", 3, tint=srgb(0xf2f0ea)),
    "concrete_floor": lambda: pbr("concrete_floor", "concrete_pavement", 2.5),
    "concrete_ribbed": lambda: pbr("concrete_ribbed", "white_stucco", 2, tint=srgb(0xb9b2a4)),
    "concrete_roof": lambda: pbr("concrete_roof", "concrete_floor_02", 3, tint=srgb(0x8e8a84)),
    "terracotta": lambda: pbr("terracotta", "white_stucco", 2, tint=srgb(0xb8673f)),
    "water": lambda: plain("water", srgb(0x0e1c18), rough=0.03),
    "pool_water": lambda: plain("pool_water", srgb(0x1f7f92), rough=0.05),
    "glass": lambda: plain("glass", srgb(0x334550), rough=0.03, metal=0.55),
    "glass_roof": lambda: plain("glass_roof", srgb(0x4a5a60), rough=0.08, metal=0.4),
    "copper": lambda: plain("copper", srgb(0x5f9a84), rough=0.55, metal=0.25),
    "alu": lambda: plain("alu", srgb(0xc8ccd0), rough=0.35, metal=0.9),
    "net": lambda: plain("net", srgb(0xb4bac0), rough=0.4, metal=0.7, alpha=0.3),
    "timber_white": lambda: plain("timber_white", srgb(0xefede6)),
    "timber_dark": lambda: plain("timber_dark", srgb(0x3a2e26), rough=0.7),
    "clock_face": lambda: plain("clock_face", srgb(0xf4f1e8), rough=0.4),
    "lead": lambda: plain("lead", srgb(0x6a7077), rough=0.5, metal=0.35),
    "gold": lambda: plain("gold", srgb(0xd8aa46), rough=0.3, metal=1.0),
    "iron": lambda: plain("iron", srgb(0x1e2723), rough=0.5, metal=0.5),
    "bark": lambda: plain("bark", srgb(0x4a3a2e), rough=0.9),
    "leaves": lambda: plain("leaves", srgb(0x3d5f2a), rough=0.8),
    "hedge": lambda: plain("hedge", srgb(0x3f6b2f), rough=0.9),
    "railing": lambda: plain("railing", srgb(0x1f2a22), rough=0.5, metal=0.4),
}
MATERIALS.update({
    "plaster": lambda: plain("plaster", srgb(0xe8e3d8), rough=0.9),
    "floor_int": lambda: pbr("floor_int", "concrete_floor_02", 2, tint=srgb(0xe8e0d0)),
    "plinth": lambda: pbr("plinth", "concrete_floor_02", 2, tint=srgb(0x8c867c)),
    "frame_white": lambda: plain("frame_white", srgb(0xefeee8), rough=0.5),
    "frame_dark": lambda: plain("frame_dark", srgb(0x353d39), rough=0.5),
    "door_black": lambda: plain("door_black", srgb(0x15181a), rough=0.35),
    "door_navy": lambda: plain("door_navy", srgb(0x1c2a44), rough=0.35),
    "door_green": lambda: plain("door_green", srgb(0x1f3a2b), rough=0.35),
    "door_oxblood": lambda: plain("door_oxblood", srgb(0x5a1d1d), rough=0.35),
    "door_slate": lambda: plain("door_slate", srgb(0x3d5566), rough=0.35),
    "slate_uv": lambda: pbr("slate_uv", "roof_slates_02", 2, uv=True),
    "tiles_uv": lambda: pbr("tiles_uv", "clay_roof_tiles", 2, uv=True),
})


MATERIALS.update({
    "brick_brown": lambda: pbr("brick_brown", "brick_wall_02", 2, tint=srgb(0x8a6a62)),
    "tiles_dark": lambda: pbr("tiles_dark", "roof_slates_02", 2, tint=srgb(0x8a8a90), uv=True),
    "timber_weathered": lambda: pbr("timber_weathered", "wood_plank_wall", 2.5, tint=srgb(0xc8bba8)),
    "thatch": lambda: pbr("thatch", "reed_roof_04", 2.5),
    "corrugated": lambda: pbr("corrugated", "corrugated_iron_02", 2),
    "corrugated_rust": lambda: pbr("corrugated_rust", "rusty_corrugated_iron", 2),
    "sandstone": lambda: pbr("sandstone", "red_sandstone_wall", 2.5),
    "steel": lambda: plain("steel", srgb(0x8a8d90), rough=0.35, metal=0.9),
    "rope": lambda: plain("rope", srgb(0x8a7558), rough=0.9),
    "bronze": lambda: plain("bronze", srgb(0x5a4632), rough=0.38, metal=1.0),
    "rock_face": lambda: pbr("rock_face", "concrete_floor_02", 3, tint=srgb(0xd8d2c4)),
    "ledge": lambda: pbr("ledge", "concrete_floor_02", 3, tint=srgb(0xb0aa98)),
})


def picture(name):
    """Painted sign or banner from public/assets/landmarks/textures, on the mesh's UVs."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], nt.nodes.new("ShaderNodeOutputMaterial").inputs[0])
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(os.path.join(ROOT, "public", "assets", "landmarks", "textures", name + ".png"), check_existing=True)
    nt.links.new(nt.nodes.new("ShaderNodeTexCoord").outputs["UV"], tex.inputs[0])
    nt.links.new(tex.outputs[0], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.6
    return m


def landmark(name):
    """Material for a landmark surface name, including render_/paint_/fabric_<hex> and pictures."""
    # Imported GLBs bring placeholder materials with these same names, so (re)build them every time.
    if name in MATERIALS:
        return MATERIALS[name]()
    kind, _, hexcol = name.partition("_")
    if kind in ("render", "paint", "fabric") and len(hexcol) == 6:
        c = srgb(int(hexcol, 16))
        if kind == "render":
            return pbr(name, "white_stucco", 3, tint=c)
        return plain(name, c, rough=0.45 if kind == "paint" else 0.85)
    if name.startswith(("sign_", "banner_", "shutter", "mosaic_")):
        return picture(name)
    return None


def ensure_all():
    for f in MATERIALS.values():
        f()


def wall(finish, paint):
    """Brick walls keep the scan's colour; rendered walls are painted the building's colour."""
    if finish != "render":
        return finish
    name = f"render_{paint:06x}"
    if name not in bpy.data.materials:
        pbr(name, "white_stucco", 3, tint=srgb(paint))
    return name


ensure_all()

