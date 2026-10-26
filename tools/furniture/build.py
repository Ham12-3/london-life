"""Model the zoo's street furniture in Blender and export one GLB per item to public/assets/furniture/.

    blender --background --factory-startup --python tools/furniture/build.py

London park bench (cast-iron ends, timber slats), litter bin, Victorian cast-iron lamp post with a
glazed lantern, drinking fountain, picnic table, Sheffield cycle stands, and a 2.5 m run of
spear-topped iron railings (repeated along every mapped fence).

Models stand on z = 0, centred on the origin; their length runs along x and their front faces -y
(three.js +z). Materials go out by name; the app and the Blender scene give them real surfaces.
"""
import bpy
import importlib.util
import math
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "public", "assets", "furniture")
LOG = os.path.join(ROOT, "work", "furniture.log")
os.makedirs(OUT, exist_ok=True)
os.makedirs(os.path.dirname(LOG), exist_ok=True)
log = open(LOG, "w")

spec = importlib.util.spec_from_file_location("landmark_build", os.path.join(ROOT, "tools", "landmarks", "build.py"))
lb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lb)
Builder = lb.Builder


def bench(B):
    for x in (-0.82, 0.82):  # cast-iron ends: legs, seat bearer, arm
        B.tube((x, -0.24, 0), (x, -0.2, 0.43), 0.025, "iron", 8)
        B.tube((x, 0.22, 0), (x, 0.18, 0.43), 0.025, "iron", 8)
        B.tube((x, -0.26, 0.43), (x, 0.24, 0.43), 0.022, "iron", 8)
        B.tube((x, 0.2, 0.43), (x, 0.3, 0.86), 0.022, "iron", 8)
        B.polyline_tube([(x, 0.22, 0.62), (x, -0.05, 0.66), (x, -0.25, 0.63), (x, -0.27, 0.58)], 0.02, "iron", 8)
        B.tube((x, -0.24, 0.58), (x, -0.24, 0.43), 0.018, "iron", 8)
    for k in range(5):  # seat slats
        y = -0.23 + k * 0.105
        B.box((0, y, 0.465), (1.82, 0.085, 0.035), 0, "timber_bench")
    for k in range(3):  # back slats, leaning back
        t = 0.52 + k * 0.12
        B.box((0, 0.2 + (t - 0.43) * 0.23, t + 0.04), (1.82, 0.03, 0.09), 0, "timber_bench")


def bin_(B):
    B.prism([(0.27 * math.cos(a), 0.27 * math.sin(a)) for a in (2 * math.pi * k / 20 for k in range(20))], 0, 0.78, "bin_green", top=False)
    B.prism([(0.29 * math.cos(a), 0.29 * math.sin(a)) for a in (2 * math.pi * k / 20 for k in range(20))], 0.62, 0.68, "gold", top=False, bottom=True)
    B.prism([(0.3 * math.cos(a), 0.3 * math.sin(a)) for a in (2 * math.pi * k / 20 for k in range(20))], 0.78, 0.84, "bin_green", top=True, bottom=True)
    B.dome((0, 0, 0.84), 0.26, 0.14, "bin_green", 20, 4)
    B.face([(-0.14, -0.299, 0.66), (0.14, -0.299, 0.66), (0.14, -0.299, 0.76), (-0.14, -0.299, 0.76)], "paint_141614")


def lamp(B):
    """Victorian cast-iron lamp column with a square glazed lantern."""
    oc = lambda r: [(r * math.cos(a + math.pi / 8), r * math.sin(a + math.pi / 8)) for a in (2 * math.pi * k / 8 for k in range(8))]
    B.prism(oc(0.2), 0, 0.5, "iron", top=True)
    B.prism(oc(0.16), 0.5, 0.62, "iron", top=True)
    for z0, r0, z1, r1 in ((0.62, 0.11, 2.6, 0.075), (2.6, 0.075, 3.3, 0.06)):
        n = 12
        for k in range(n):  # fluted column
            a0, a1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
            f0, f1 = 1 + 0.08 * (k % 2), 1 + 0.08 * ((k + 1) % 2)
            B.face([(r0 * f0 * math.cos(a0), r0 * f0 * math.sin(a0), z0), (r0 * f1 * math.cos(a1), r0 * f1 * math.sin(a1), z0),
                    (r1 * f1 * math.cos(a1), r1 * f1 * math.sin(a1), z1), (r1 * f0 * math.cos(a0), r1 * f0 * math.sin(a0), z1)], "iron", smooth=True)
    B.box((0, 0, 3.0), (0.62, 0.035, 0.035), 0, "iron")  # ladder bar
    for s in (-1, 1):
        B.sphere((0.31 * s, 0, 3.0), 0.03, "iron", 8)
    B.prism(oc(0.1), 3.3, 3.4, "iron", top=True, bottom=True)
    # Lantern: tapering glazed box between iron frames, a cap and a finial.
    zb, zt, rb, rt = 3.45, 3.95, 0.14, 0.2
    sq = lambda r, z: [(r, -r, z), (r, r, z), (-r, r, z), (-r, -r, z)]
    b, t = sq(rb, zb), sq(rt, zt)
    for i in range(4):
        B.face([b[i], b[(i + 1) % 4], t[(i + 1) % 4], t[i]], "lamp_glass")
        B.tube(b[i], t[i], 0.012, "iron", 6)
    B.prism([(x, y) for x, y, _ in b], zb - 0.05, zb, "iron", top=True, bottom=True)
    cap = sq(0.24, zt)
    for i in range(4):
        B.face([cap[i], cap[(i + 1) % 4], (0, 0, zt + 0.22)], "iron")
    B.face([c for c in cap[::-1]], "iron")
    B.tube((0, 0, zt + 0.2), (0, 0, zt + 0.36), 0.015, "iron", 6)
    B.sphere((0, 0, zt + 0.37), 0.03, "iron", 8)


def fountain(B):
    B.prism([(0.22 * math.cos(a), 0.22 * math.sin(a)) for a in (2 * math.pi * k / 16 for k in range(16))], 0, 0.85, "stone", top=False)
    B.dome((0, 0, 0.85), 0.32, -0.12, "stone", 16, 3)
    B.prism([(0.32 * math.cos(a), 0.32 * math.sin(a)) for a in (2 * math.pi * k / 16 for k in range(16))], 0.85, 0.92, "stone", top=False, bottom=True)
    B.tube((0, 0.1, 0.86), (0, 0.04, 0.98), 0.012, "steel", 6)


def picnic(B):
    B.box((0, 0, 0.74), (1.8, 0.8, 0.05), 0, "timber_bench")
    for s in (-1, 1):
        B.box((0, s * 0.62, 0.44), (1.8, 0.28, 0.045), 0, "timber_bench")
        for x in (-0.7, 0.7):
            B.tube((x, s * 0.05, 0.72), (x, s * 0.7, 0.0), 0.035, "timber_bench", 6)


def bikes(B):
    for x in (-1.0, 0.0, 1.0):  # Sheffield stands: inverted U of steel tube
        pts = [(x, -0.35, 0)] + [(x, -0.35 + 0.1 * (1 - math.cos(t)), 0.75 + 0.1 * math.sin(t)) for t in (0.0, 0.6, 1.2, 1.57)]
        pts += [(x, 0.35 - 0.1 * (1 - math.cos(t)), 0.75 + 0.1 * math.sin(t)) for t in (1.2, 0.6, 0.0)] + [(x, 0.35, 0)]
        B.polyline_tube(pts, 0.03, "steel", 8)


def railing(B):
    """2.5 m of London railings: flat rails, square bars with spear heads, a post with a ball."""
    L = 2.5
    for z in (0.12, 1.02):
        B.box((0, 0, z), (L, 0.05, 0.012), 0, "iron_railing")
    n = 20
    for k in range(n):
        x = -L / 2 + (k + 0.5) * L / n
        B.box((x, 0, 0.58), (0.016, 0.016, 1.12), 0, "iron_railing")
        tip = [(x, 0, 1.22)]
        base = [(x - 0.022, 0, 1.14), (x, 0.022, 1.14), (x + 0.022, 0, 1.14), (x, -0.022, 1.14)]
        for i in range(4):
            B.face([base[i], base[(i + 1) % 4], tip[0]], "iron_railing")
    B.box((-L / 2, 0, 0.63), (0.055, 0.055, 1.26), 0, "iron_railing")
    B.sphere((-L / 2, 0, 1.3), 0.04, "iron_railing", 8)


ITEMS = {"bench": bench, "bin": bin_, "lamp": lamp, "water": fountain, "picnic": picnic, "bikes": bikes, "railing": railing}

bpy.ops.wm.read_factory_settings(use_empty=True)
for name, make in ITEMS.items():
    B = Builder()
    make(B)
    obj = B.build(name)
    for o in bpy.context.scene.objects:
        o.select_set(o == obj)
    bpy.context.view_layer.objects.active = obj
    path = os.path.join(OUT, name + ".glb")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
                              export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=7)
    print(f"{name}: ~{sum(len(p.vertices) - 2 for p in obj.data.polygons)} tris, {B.names}", file=log, flush=True)
    bpy.data.objects.remove(obj)
print("done", file=log, flush=True)
