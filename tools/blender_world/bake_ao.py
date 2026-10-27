"""Bake ambient occlusion for the zoo with Cycles and export the baked buildings and terrain for
the web app.

    python tools/blender_mcp.py run tools/blender_world/save_copy.py   (live scene -> work/blender/zoo.blend)
    blender --background work/blender/zoo.blend --python tools/blender_world/bake_ao.py [-- ground | atlas]

`-- ground` redoes only the ground image, `-- atlas` only the buildings and earthworks (and their
export). Everything takes about 40 minutes on a desktop CPU; AO_TEST=1 makes a quick
low-resolution test bake.

Ambient occlusion is how much open sky each point sees: dark where walls meet the ground, under
tree canopies, in window reveals and doorways, inside rooms, down in the tunnel ramps and the canal
cutting. It doesn't depend on where the sun is, so the app's moving sun shadows stay right; the
app applies it to sky (ambient) light only.

- Buildings and earthworks get a second UV map (Smart UV Project) and an occlusion atlas each
  (public/assets/blender/ao_buildings.jpg, ao_earthworks.jpg), read through TEXCOORD_1. Per-vertex
  values don't work here: the walls are long triangles fanned between the window openings, and the
  shading would smear along them.
- The ground is nearly flat, so its occlusion goes into one top-down image of the zoo
  (public/assets/terrain/ao.jpg, ~22 cm a pixel) that the app looks up by world position; the grass
  reads it too.
"""
import bpy
import json
import math
import numpy as np
import os
import sys
import time
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG = os.path.join(ROOT, "work", "bake_ao.log")
log = open(LOG, "w")


def say(*a):
    print(*a, file=log, flush=True)


t0 = time.time()
scene = bpy.context.scene
TEST = bool(os.environ.get("AO_TEST"))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
DO_GROUND = not ARGS or "ground" in ARGS
DO_ATLAS = not ARGS or "atlas" in ARGS

REGION = (-460.0, 460.0, -360.0, 360.0)  # Blender x0, x1, y0, y1 covered by the ground image
GROUND_SIZE = (512, 400) if TEST else (4096, 3200)
ATLASES = [("Buildings", 512 if TEST else 4096, "ao_buildings.jpg"),
           ("Earthworks", 256 if TEST else 2048, "ao_earthworks.jpg")]
OUT = os.path.join(ROOT, "public", "assets", "blender")
TERRAIN_DIR = os.path.join(ROOT, "public", "assets", "terrain")

# Cycles AO bake on the CPU.
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 4 if TEST else 48
scene.cycles.use_denoising = False
scene.render.bake.margin = 4
scene.render.image_settings.quality = 90
scene.world.light_settings.distance = 7.0  # metres: contact shading, not whole-scene darkness


def select_only(o):
    for x in scene.objects:
        x.select_set(False)
    o.select_set(True)
    bpy.context.view_layer.objects.active = o


def new_image(name, w, h):
    img = bpy.data.images.new(name, w, h, alpha=False)
    img.generated_color = (1, 1, 1, 1)
    return img


def save_jpg(img, path, blur=0):
    if blur:  # takes out the sampling grain (occlusion is soft anyway)
        w, h = img.size
        px = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
        g = px.reshape(h, w, 4)[..., 0]
        for _ in range(blur):
            p = np.pad(g, 1, mode="edge")
            g = sum(p[dy:dy + h, dx:dx + w] for dy in range(3) for dx in range(3)) / 9
        px = np.repeat(g[..., None], 4, -1)
        px[..., 3] = 1
        img.pixels.foreach_set(px.ravel())
    img.filepath_raw = path
    img.file_format = "JPEG"
    img.save()


def bake_atlas(name, size, file):
    """A second UV map packed over the whole object, and the occlusion baked into it."""
    o = bpy.data.objects.get(name)
    if not o:
        return
    me = o.data
    for a in [a for a in me.color_attributes if a.name == "AO"]:  # from the old per-vertex bake
        me.color_attributes.remove(a)
    if "AOUV" in me.uv_layers:
        me.uv_layers.remove(me.uv_layers["AOUV"])
    me.uv_layers[0].active_render = True
    me.uv_layers.active = me.uv_layers.new(name="AOUV")  # second map -> TEXCOORD_1
    select_only(o)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.0001, area_weight=0.0,
                             correct_aspect=True, scale_to_bounds=False)
    # Its own packing leaves most of the square empty with this many islands (window frames, sills,
    # lintels); the island packer does much better.
    scene.tool_settings.use_uv_select_sync = True
    bpy.ops.uv.pack_islands(shape_method="AABB", rotate=True, margin_method="FRACTION", margin=0.0001)
    bpy.ops.object.mode_set(mode="OBJECT")
    aouv = me.uv_layers["AOUV"]  # layer references go stale across edit mode
    uvs = np.empty(len(me.loops) * 2, dtype=np.float32)
    aouv.data.foreach_get("uv", uvs)
    uvs = uvs.reshape(-1, 2)
    cover = 0.0
    for p in me.polygons:  # shoelace area of each face in the atlas
        q = uvs[p.loop_start:p.loop_start + p.loop_total]
        cover += 0.5 * abs(np.dot(q[:, 0], np.roll(q[:, 1], -1)) - np.dot(q[:, 1], np.roll(q[:, 0], -1)))
    area = sum(p.area for p in me.polygons)
    texel = math.sqrt(area / (cover * size * size)) * 100
    say(f"{name}: unwrapped {len(me.polygons)} faces, {cover:.0%} of the atlas, ~{texel:.0f} cm a pixel ({time.time() - t0:.0f}s)")
    img = new_image(f"AO {name}", size, size)
    added = []
    for slot in o.material_slots:
        m = slot.material
        if not m:
            continue
        m.use_nodes = True
        n = m.node_tree.nodes.new("ShaderNodeTexImage")
        n.image = img
        m.node_tree.nodes.active = n
        added.append((m, n))
    bpy.ops.object.bake(type="AO", target="IMAGE_TEXTURES", uv_layer="AOUV")
    for m, n in added:
        m.node_tree.nodes.remove(n)
    me.uv_layers.active = me.uv_layers[0]
    save_jpg(img, os.path.join(OUT, file))
    say(f"{name}: baked {size}x{size} atlas, {os.path.getsize(os.path.join(OUT, file)) // 1024} KB ({time.time() - t0:.0f}s)")


def bake_ground():
    """The ground is layered (lawn underneath, zoo ground, woodland and paving a few cm above it,
    paths above those), so baking its own faces would let buried layers write black into the image.
    Instead a temporary receiver sheet lies just above the topmost ground surface (found by casting
    down: ground, paths, water, the earthworks' ramps and decks), and only it is baked."""
    x0, x1, y0, y1 = REGION
    xs = np.arange(x0, x1 + 0.01, 1.0)
    ys = np.arange(y0, y1 + 0.01, 1.0)
    gx, gy = np.meshgrid(xs, ys)  # rows along Blender y
    depsgraph = bpy.context.evaluated_depsgraph_get()
    trees = [BVHTree.FromObject(bpy.data.objects[n], depsgraph) for n in ("Ground", "Paths", "Water", "Earthworks")
             if n in bpy.data.objects]  # all at the origin, unrotated
    down = Vector((0, 0, -1))

    def top_surface(x, y):
        o = Vector((x, y, 40.0))
        zs = [hit[0].z for hit in (t.ray_cast(o, down, 60) for t in trees) if hit[0] is not None]
        return max(zs) if zs else 0.0

    gz = np.array([top_surface(x, y) for x, y in zip(gx.ravel(), gy.ravel())]).reshape(gx.shape) + 0.15
    say(f"ground receiver: {gz.size} points ({time.time() - t0:.0f}s)")
    cols = len(xs)
    verts = np.stack([gx, gy, gz], -1).reshape(-1, 3)
    r, c = np.meshgrid(np.arange(len(ys) - 1), np.arange(cols - 1), indexing="ij")
    a = (r * cols + c).ravel()
    faces = np.stack([a, a + 1, a + cols + 1, a + cols], -1)
    me = bpy.data.meshes.new("AOReceiver")
    me.from_pydata(verts.tolist(), [], faces.tolist())
    uv = me.uv_layers.new(name="UVMap")
    loop_v = np.array([lp.vertex_index for lp in me.loops])
    uvs = np.stack([(verts[loop_v, 0] - x0) / (x1 - x0), (verts[loop_v, 1] - y0) / (y1 - y0)], -1)
    uv.data.foreach_set("uv", uvs.ravel())
    receiver = bpy.data.objects.new("AOReceiver", me)
    scene.collection.objects.link(receiver)
    img = new_image("GroundAO", *GROUND_SIZE)
    mat = bpy.data.materials.new("AOBake")
    mat.use_nodes = True
    n = mat.node_tree.nodes.new("ShaderNodeTexImage")
    n.image = img
    mat.node_tree.nodes.active = n
    me.materials.append(mat)
    select_only(receiver)
    bpy.ops.object.bake(type="AO", target="IMAGE_TEXTURES")
    bpy.data.objects.remove(receiver)
    path = os.path.join(TERRAIN_DIR, "ao.jpg")
    save_jpg(img, path, blur=2)
    # World x/z of the image: u along x; v from Blender y0 (world z = -y0) towards y1.
    json.dump({"x0": x0, "x1": x1, "z_at_v0": -y0, "z_at_v1": -y1, "distance": 7.0},
              open(os.path.join(TERRAIN_DIR, "ao.json"), "w"))
    say(f"baked ground image {GROUND_SIZE[0]}x{GROUND_SIZE[1]}: {os.path.getsize(path) // 1024} KB ({time.time() - t0:.0f}s)")


def export(names, file):
    for x in scene.objects:
        x.select_set(x.name in names)
    bpy.context.view_layer.objects.active = bpy.data.objects[names[0]]
    kw = dict(filepath=os.path.join(OUT, file), export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
              export_image_format="NONE", export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=7,
              export_draco_position_quantization=16, export_draco_texcoord_quantization=14)
    try:
        bpy.ops.export_scene.gltf(**kw, export_vertex_color="NONE")
    except TypeError:
        bpy.ops.export_scene.gltf(**kw, export_colors=False)
    say(f"{file}: {os.path.getsize(os.path.join(OUT, file)) // 1024} KB")


if DO_ATLAS:
    for name, size, file in ATLASES:
        bake_atlas(name, size, file)
if DO_GROUND:
    bake_ground()
if DO_ATLAS:
    export(["Buildings"], "buildings.glb")
    export(["Ground", "Paths", "Water", "Earthworks"], "terrain.glb")
say(f"done ({time.time() - t0:.0f}s)")
