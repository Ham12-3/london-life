"""Build the whole of London Zoo inside Blender from the map (public/world.json).

Run inside a live Blender through the Blender MCP add-on:
    python tools/blender_mcp.py run tools/blender_world/scene.py

Everything goes into a "London Zoo" collection (rebuilt from scratch on each run): ground and land
cover, paths and roads, ponds and the canal, every building, the landmark models from
tools/landmarks, trees, a physical sky and the sun. Surfaces use the same CC0 Poly Haven scans as the
web app, box-projected in world metres.

Blender axes: x east, y north (= -z in world.json), z up.
"""
import bpy
import importlib.util
import json
import math
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

spec = importlib.util.spec_from_file_location("landmark_build", os.path.join(ROOT, "tools", "landmarks", "build.py"))
lb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lb)
Builder, ccw, offset = lb.Builder, lb.ccw, lb.offset

world = json.load(open(os.path.join(ROOT, "public", "world.json"), encoding="utf-8"))
landmarks = json.load(open(os.path.join(ROOT, "public", "assets", "landmarks", "landmarks.json"), encoding="utf-8"))
replaced = {n for L in landmarks for n in L["replaces"]}
B2 = lambda p: (p[0], -p[1])  # world (x, z) -> Blender (x, y)


spec_m = importlib.util.spec_from_file_location("zoo_mats", os.path.join(os.path.dirname(__file__), "materials.py"))
mats = importlib.util.module_from_spec(spec_m)
spec_m.loader.exec_module(mats)
srgb = mats.srgb


GROUND = {"park": "lawn", "grass": "lawn", "garden": "lawn", "pitch": "lawn", "wood": "woodland", "scrub": "woodland",
          "playground": "dirt", "enclosure": "dirt", "sand": "sand", "rock": "rock", "paved": "paving"}
PATHS = {"road": ("asphalt", 0.06), "footway": ("paving", 0.07), "path": ("gravel", 0.07), "pedestrian": ("paving", 0.07),
         "steps": ("steps", 0.075), "corridor": ("concrete", 0.1), "cycleway": ("cycleway", 0.065)}
WALL_FINISH = {0x9c5b43: "brick_red", 0xb36b4f: "brick_red", 0x7d6a5a: "brick_buff", 0x8a7f72: "brick_buff"}
WALL_PALETTE = [0x9c5b43, 0xb36b4f, 0xd8cdb8, 0xe8e2d4, 0x8a7f72, 0xc9b28c, 0x7d6a5a]


def fnv(s):
    h = 2166136261
    for ch in s:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


# ---------- scene ----------

def fresh_collection(name):
    old = bpy.data.collections.get(name)
    if old:
        for o in list(old.all_objects):
            bpy.data.objects.remove(o, do_unlink=True)
        for c in list(old.children_recursive):
            bpy.data.collections.remove(c)
        bpy.data.collections.remove(old)
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


def place(obj, col):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    col.objects.link(obj)


root = fresh_collection("London Zoo")
cols = {}
for n in ("Ground", "Paths", "Water", "Buildings", "Landmarks", "Trees"):
    cols[n] = bpy.data.collections.new(n)
    root.children.link(cols[n])
for o in ("Cube",):  # Blender's default cube sits in the middle of the zoo
    if o in bpy.data.objects:
        bpy.data.objects[o].hide_set(True)
        bpy.data.objects[o].hide_render = True

# Ground: Regent's Park lawn, the zoo grounds, then land cover by kind.
G = Builder()
G.face([(-900, -900, 0), (900, -900, 0), (900, 900, 0), (-900, 900, 0)], "lawn")
for r in world["zoo"]:
    G.face([(*B2(p), 0.005) for p in ccw([B2(p) for p in r[:-1]])][::1] and [(x, y, 0.005) for x, y in ccw([B2(p) for p in r[:-1]])], "zoo_ground")
heights = {"park": 0.01, "grass": 0.02, "garden": 0.025, "wood": 0.02, "scrub": 0.03, "pitch": 0.03, "playground": 0.03, "enclosure": 0.035, "sand": 0.04, "rock": 0.045, "paved": 0.03}
for gp in world["ground"]:
    if gp["kind"] in GROUND and len(gp["pts"]) > 3:
        G.face([(x, y, heights[gp["kind"]]) for x, y in ccw([B2(p) for p in gp["pts"][:-1]])], GROUND[gp["kind"]])
place(G.build("Ground"), cols["Ground"])

# Water and bridges.
W = Builder()
for w in world["water"]:
    if w.get("line"):
        pts = [B2(p) for p in w["line"]]
        for a, b in zip(pts, pts[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            ln = math.hypot(dx, dy) or 1
            nx, ny = -dy / ln * w["w"] / 2, dx / ln * w["w"] / 2
            W.face([(a[0] - nx, a[1] - ny, 0.05), (b[0] - nx, b[1] - ny, 0.05), (b[0] + nx, b[1] + ny, 0.05), (a[0] + nx, a[1] + ny, 0.05)], "water")
    elif len(w["pts"]) > 3:
        W.face([(x, y, 0.05) for x, y in ccw([B2(p) for p in w["pts"][:-1]])], "water")
place(W.build("Water"), cols["Water"])

# Paths: ribbons with round joints.
P = Builder()
for p in world["paths"]:
    if len(p["pts"]) < 2 or p.get("tunnel"):
        continue
    mat, z = PATHS.get(p["kind"], PATHS["footway"])
    z = 0.14 if p.get("bridge") else z
    pts, half = [B2(q) for q in p["pts"]], p["w"] / 2
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy)
        if ln < 1e-3:
            continue
        nx, ny = -dy / ln * half, dx / ln * half
        P.face([(a[0] - nx, a[1] - ny, z), (b[0] - nx, b[1] - ny, z), (b[0] + nx, b[1] + ny, z), (a[0] + nx, a[1] + ny, z)], "boards" if p.get("bridge") else mat)
    for x, y in pts:
        P.face([(x + half * math.cos(t), y + half * math.sin(t), z - 0.002) for t in (2 * math.pi * k / 10 for k in range(10))], mat)
place(P.build("Paths"), cols["Paths"])

# Buildings: walls and flat roofs for now (landmarks bring their own models).
Bd = Builder()
for i, b in enumerate(world["buildings"]):
    if b.get("name") in replaced or len(b["pts"]) < 4:
        continue
    ring = ccw([B2(p) for p in b["pts"][:-1]])
    pal = [0xe9e4d6, 0xd9c7a3, 0xb7c4b0, 0xcfd6d8, 0xa98c6a] if b["inZoo"] else WALL_PALETTE
    color = pal[fnv(b.get("name") or f"b{i}") % len(pal)]
    finish = "render" if b["inZoo"] else WALL_FINISH.get(color, "render")
    Bd.prism(ring, 0, b["h"], finish, top=True, top_mat="roof_flat")
    Bd.prism(offset(ring, 0.06), 0, 0.45, "stone", top=False)
place(Bd.build("Buildings", bevel=0.02), cols["Buildings"])

# Landmarks: the Blender models from tools/landmarks, with these materials.
for L in landmarks:
    path = os.path.join(ROOT, L["url"].replace("/", os.sep).replace("assets" + os.sep, "public" + os.sep + "assets" + os.sep, 1))
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    for o in set(bpy.data.objects) - before:
        place(o, cols["Landmarks"])
        if o.parent is None:
            o.location = (L["origin"][0], -L["origin"][1], 0)
        if o.type == "MESH":
            for slot in o.material_slots:
                base = slot.material.name.split(".")[0] if slot.material else None
                if base in bpy.data.materials and slot.material.name != base:
                    slot.material = bpy.data.materials[base]

# Trees: one shared trunk-and-crown mesh, linked copies at every mapped tree.
T = Builder()
T.tube((0, 0, 0), (0, 0, 0.45), 0.035, "bark", 8)
T.sphere((0, 0, 0.62), 0.3, "leaves", 12)
proto = T.build("Tree")
place(proto, cols["Trees"])
proto.hide_set(True)
proto.hide_render = True
for x, z, h in world["trees"]:
    o = proto.copy()
    o.location = (x, -z, 0)
    o.scale = (h, h, h)
    o.rotation_euler[2] = (fnv(f"{x:.1f},{z:.1f}") % 628) / 100
    cols["Trees"].objects.link(o)
    o.hide_set(False)
    o.hide_render = False

# Sky and sun: an afternoon sun in the south-west, as in the web app.
scene = bpy.context.scene
wd = scene.world or bpy.data.worlds.new("World")
scene.world = wd
wd.use_nodes = True
wn = wd.node_tree
wn.nodes.clear()
sky = wn.nodes.new("ShaderNodeTexSky")
for t in ("NISHITA", "MULTIPLE_SCATTERING", "SINGLE_SCATTERING", "HOSEK_WILKIE"):
    try:
        sky.sky_type = t
        break
    except TypeError:
        continue
try:
    sky.sun_elevation = math.radians(46)
    sky.sun_rotation = math.radians(215 - 90)
except AttributeError:
    pass
bg = wn.nodes.new("ShaderNodeBackground")
bg.inputs["Strength"].default_value = 0.25
wo = wn.nodes.new("ShaderNodeOutputWorld")
wn.links.new(sky.outputs[0], bg.inputs[0])
wn.links.new(bg.outputs[0], wo.inputs[0])
sun = bpy.data.objects.get("Zoo Sun")
if not sun:
    sun = bpy.data.objects.new("Zoo Sun", bpy.data.lights.new("Zoo Sun", "SUN"))
    root.objects.link(sun)
sun.data.energy = 4.0
sun.data.angle = math.radians(0.6)
sun.rotation_euler = (math.radians(90 - 46), 0, math.radians(215 - 90 + 180))
try:
    scene.view_settings.view_transform = "AgX"
except TypeError:
    pass

# A camera at the main entrance, at eye height, and the viewport looking through it in material view.
s = world["start"]
cam = bpy.data.objects.get("Zoo Camera")
if not cam:
    cam = bpy.data.objects.new("Zoo Camera", bpy.data.cameras.new("Zoo Camera"))
    root.objects.link(cam)
cam.data.lens = 24
cam.location = (s["x"], -(s["z"] - 10), 1.7)
cam.rotation_euler = (math.radians(88), 0, math.radians(180))
scene.camera = cam
for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        sp = area.spaces[0]
        sp.shading.type = "MATERIAL"
        sp.clip_end = 3000
        sp.region_3d.view_perspective = "CAMERA"

result = {"objects": len(root.all_objects), "trees": len(world["trees"]), "landmarks": len(landmarks)}
