"""Model the zoo's animals in Blender and export one GLB per species.

    blender --background --factory-startup --python tools/animals/build.py [-- species ...]

Each animal is a skeleton of joints with a thickness at each joint; Blender's Skin modifier wraps it
in a smooth body and Subdivision rounds it off. Coat markings (giraffe patches, zebra and tiger
stripes, a penguin's white front, a lemur's ringed tail...) are painted into vertex colours.

Animals face +x (Blender), stand on z = 0, in metres. Alongside the GLBs, animals.json records each
species' leg joints (hip height and position) so src/animals.js can swing the legs as they walk.
"""
import bpy
import json
import math
import os
import random
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "public", "assets", "animals")
LOG = os.path.join(ROOT, "work", "animals.log")
os.makedirs(os.path.dirname(LOG), exist_ok=True)
log_file = open(LOG, "w", encoding="utf-8")


def log(*a):
    print(*a, file=log_file, flush=True)


def hexrgb(h):
    """sRGB hex -> linear rgb (vertex colours are stored linear)."""
    c = [((h >> s) & 255) / 255 for s in (16, 8, 0)]
    return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]


def mix(a, b, t):
    return [a[i] + (b[i] - a[i]) * t for i in range(3)]


class Skel:
    def __init__(self):
        self.v, self.r, self.e, self.legs = [], [], [], []

    def add(self, p, r, parent=None):
        """r is a radius, or (width, depth) for an oval cross-section."""
        self.v.append(tuple(p))
        self.r.append(r if isinstance(r, tuple) else (r, r))
        i = len(self.v) - 1
        if parent is not None:
            self.e.append((parent, i))
        return i

    def chain(self, parent, pts):
        i = parent
        for p, r in pts:
            i = self.add(p, r, i)
        return i


# ---------- body plans ----------

def quadruped(s, L, H, R, legR, neck=0.3, neck_ang=55, head=0.35, head_r=None, tail=0.4, ears=True,
              hump=0, ossicones=False, snout=1.0, mane=0, leg_spread=0.62):
    head_r = head_r or R * 0.55
    W = R * leg_spread
    # Bodies are deeper than they are wide: the chest deepest, the waist slimmer, the rump rounded.
    hip = s.add((-L / 2, 0, H - R * 0.02), (R * 0.95, R * 0.8), None)
    mid = s.add((0, 0, H + R * 0.02), (R * 0.95, R * 0.78), hip)
    sho = s.add((L / 2 * 0.95, 0, H + R * 0.08), (R * 1.08, R * 0.82), mid)
    for x0, spine, back in ((L / 2 * 0.92, sho, False), (-L / 2 * 0.92, hip, True)):
        for side in (1, -1):
            top = s.add((x0, W * side, H - R * 0.55), legR * (1.5 if back else 1.3), spine)
            knee_x = x0 + (-0.06 if back else 0.03) * H
            s.chain(top, [((knee_x, W * side, H * 0.42), legR * 0.85), ((x0, W * side, 0.08), legR * 0.62), ((x0 + legR * 0.6, W * side, 0.02), legR * 0.66)])
            s.legs.append((x0, W * side, H - R * 0.55))
    a = math.radians(neck_ang)
    n1 = s.add((L / 2 + math.sin(a) * neck * 0.5, 0, H + R * 0.2 + math.cos(a) * neck * 0.5), max(R * 0.55, head_r * 0.9) + mane, sho)
    n2 = s.add((L / 2 + math.sin(a) * neck, 0, H + R * 0.2 + math.cos(a) * neck), head_r * 0.85 + mane * 0.6, n1)
    hx, hz = s.v[n2][0], s.v[n2][2]
    h1 = s.add((hx + head * 0.35, 0, hz + head * 0.02), head_r, n2)
    s.add((hx + head * snout, 0, hz - head * 0.22), head_r * 0.55, h1)
    if ears:
        for side in (1, -1):
            s.add((hx + head * 0.2, head_r * 0.75 * side, hz + head_r * 0.95), head_r * 0.22, h1)
    if ossicones:
        for side in (1, -1):
            s.add((hx + head * 0.2, head_r * 0.35 * side, hz + head_r * 1.5), head_r * 0.13, h1)
    if hump:
        for x in ((-L * 0.18, L * 0.2) if hump == 2 else (0,)):
            s.add((x, 0, H + R * 0.95), R * 0.5, mid)
    if tail:
        s.chain(hip, [((-L / 2 - tail * 0.35, 0, H - tail * 0.25), R * 0.16), ((-L / 2 - tail * 0.55, 0, H - tail * 0.85), R * 0.08)])
    return {"eye": (hx + head * 0.42, head_r * 0.7, hz + head_r * 0.35)}


def ape(s, L, H, R, legR, tail=0.0, head_r=None):
    head_r = head_r or R * 0.55
    hip = s.add((0, 0, H * 0.45), R)
    chest = s.add((L * 0.3, 0, H * 0.72), R * 1.15, hip)
    neck = s.add((L * 0.42, 0, H * 0.9), head_r * 0.8, chest)
    head = s.add((L * 0.47, 0, H * 0.98), head_r, neck)
    s.add((L * 0.47 + head_r * 0.75, 0, H * 0.93), head_r * 0.55, head)
    for side in (1, -1):
        sh = s.add((L * 0.3, R * 1.05 * side, H * 0.74), legR * 1.4, chest)
        s.chain(sh, [((L * 0.42, R * 1.2 * side, H * 0.42), legR), ((L * 0.48, R * 1.1 * side, 0.06), legR * 0.8), ((L * 0.52, R * 1.1 * side, 0.03), legR * 0.85)])
        s.legs.append((L * 0.3, R * 1.05 * side, H * 0.74))
        top = s.add((0, R * 0.65 * side, H * 0.4), legR * 1.3, hip)
        s.chain(top, [((0.06 * H, R * 0.7 * side, H * 0.22), legR * 0.9), ((0.02, R * 0.7 * side, 0.05), legR * 0.7), ((0.02 + legR, R * 0.7 * side, 0.02), legR * 0.75)])
        s.legs.append((0, R * 0.65 * side, H * 0.4))
    if tail:
        s.chain(hip, [((-tail * 0.4, 0, H * 0.5), legR * 0.5), ((-tail * 0.8, 0, H * 0.75), legR * 0.4), ((-tail, 0, H * 0.95), legR * 0.35)])
    return {"eye": (L * 0.47 + head_r * 0.55, head_r * 0.45, H * 1.0)}


def bird(s, L, H, R, neck, beak, leg_h, beak_down=0.0, pouch=0.0):
    body_z = leg_h + R
    tailv = s.add((-L * 0.5, 0, body_z + R * 0.1), R * 0.35)
    b1 = s.add((-L * 0.1, 0, body_z), R, tailv)
    b2 = s.add((L * 0.25, 0, body_z + R * 0.15), R * 0.8, b1)
    for side in (1, -1):
        top = s.add((0, R * 0.35 * side, body_z - R * 0.6), R * 0.18, b1)
        s.chain(top, [((-0.03, R * 0.35 * side, leg_h * 0.5), R * 0.07), ((0.0, R * 0.35 * side, 0.03), R * 0.05), ((0.08, R * 0.35 * side, 0.015), R * 0.06)])
        s.legs.append((0, R * 0.35 * side, body_z - R * 0.6))
    n1 = s.add((L * 0.42, 0, body_z + neck * 0.35), R * 0.3, b2)
    n2 = s.add((L * 0.3, 0, body_z + neck * 0.75), R * 0.26, n1)
    hd = s.add((L * 0.38, 0, body_z + neck), R * 0.32, n2)
    tip = s.add((L * 0.38 + beak, 0, body_z + neck - beak * beak_down), R * 0.07, hd)
    if pouch:
        s.add((L * 0.38 + beak * 0.6, 0, body_z + neck - pouch), R * 0.18, hd)
    return {"eye": (L * 0.4, R * 0.25, body_z + neck + R * 0.12)}


def upright(s, H, R, beak=0.0, tail=0.0, flippers=True):
    base = s.add((0, 0, 0.06), R * 0.6)
    belly = s.add((0, 0, H * 0.35), R, base)
    chest = s.add((0.01, 0, H * 0.62), R * 0.85, belly)
    head = s.add((0.02, 0, H * 0.86), R * 0.62, chest)
    if beak:
        s.add((R * 0.6 + beak, 0, H * 0.84), R * 0.12, head)
    else:
        s.add((R * 0.7, 0, H * 0.84), R * 0.3, head)
    for side in (1, -1):
        sh = s.add((0, R * 0.8 * side, H * 0.6), R * 0.2, chest)
        s.add((0.03, R * 1.05 * side, H * 0.32), R * 0.12 if flippers else R * 0.1, sh)
        ft = s.add((0.0, R * 0.38 * side, 0.08), R * 0.2, base)
        s.add((R * 0.45, R * 0.4 * side, 0.02), R * 0.16, ft)
        s.legs.append((0, R * 0.38 * side, H * 0.2))
    if tail:
        s.chain(base, [((-R * 0.8, 0, 0.1), R * 0.18), ((-tail, 0, 0.04), R * 0.08)])
    return {"eye": (R * 0.5, R * 0.3, H * 0.9)}


# ---------- coats ----------

def coat(kind, base, belly=None, extra=None, H=1.0, L=1.0, eye=None):
    base, belly = hexrgb(base), hexrgb(belly) if belly else None
    extra = hexrgb(extra) if extra else None
    rnd = random.Random(7)
    sites = [(rnd.uniform(-L, L), rnd.uniform(-0.6, 0.6), rnd.uniform(0, H * 2.5)) for _ in range(900)] if kind == "giraffe" else []
    black, white = hexrgb(0x161616), hexrgb(0xf2f0ea)

    def colour(x, y, z):
        c = base
        if belly and z < H * 0.95 and abs(y) < 0.5 * H and kind not in ("penguin",):
            c = mix(c, belly, max(0.0, min(1.0, (H * 0.95 - z) / (H * 0.3))) * 0.6)
        if kind == "giraffe":
            d = sorted((x - a) ** 2 + (y - b) ** 2 + (z - cz) ** 2 for a, b, cz in sites)[:2]
            if math.sqrt(d[1]) - math.sqrt(d[0]) < 0.03:
                c = hexrgb(0xf1e2c0)
            elif z < H * 0.3:
                c = mix(c, hexrgb(0xf1e2c0), 0.6)
        elif kind == "zebra":
            band = math.sin(x * 22 + math.sin(z * 4) * 2.2) if z > H * 0.5 else math.sin(z * 34)
            c = black if band > 0.15 else white
        elif kind == "tiger":
            if math.sin(x * 15 + math.sin(z * 7) * 2.5 + y * 2) > 0.72 and z > H * 0.35:
                c = black
        elif kind == "okapi":
            if z < H * 0.6 and x < 0 and math.sin(z * 30) > 0.2:
                c = white
        elif kind == "penguin":
            c = white if (x > 0.02 and z < H * 0.8) else black
            if z > H * 0.82 and x > 0.05:
                c = hexrgb(0xe08a3c) if x > 0.12 else black
            if z < 0.06:
                c = hexrgb(0xd9a3a0)
        elif kind == "lemur":
            if x < -0.25 and math.sin(z * 40) > 0:
                c = black
            if x > 0.2 and z > H * 0.85:
                c = white
        elif kind == "lion":
            if extra and x > L * 0.35 and z > H * 0.9:
                c = extra
        elif kind == "flamingo":
            if extra and x > 0.45:
                c = extra
        if eye and (x - eye[0]) ** 2 + (abs(y) - eye[1]) ** 2 + (z - eye[2]) ** 2 < 0.0012 * max(H, 0.4):
            c = black
        return c
    return colour


# id: (plan, params, coat)
SPECIES = {
    "gorilla": (ape, dict(L=0.9, H=1.5, R=0.33, legR=0.11), ("plain", 0x2a2a2a, 0x3a3a3a)),
    "monkey": (ape, dict(L=0.42, H=0.65, R=0.13, legR=0.04, tail=0.6), ("plain", 0x5a4636, 0x8a7a66)),
    "lemur": (ape, dict(L=0.38, H=0.5, R=0.11, legR=0.035, tail=0.6), ("lemur", 0x9a9a98, 0xe6e4de)),
    "lion": (quadruped, dict(L=1.8, H=1.05, R=0.36, legR=0.09, neck=0.35, head=0.42, tail=0.9, mane=0.12), ("lion", 0xc4975a, 0xe0c69a, 0x6e4a2a)),
    "tiger": (quadruped, dict(L=1.9, H=0.95, R=0.34, legR=0.085, neck=0.3, head=0.4, tail=0.95), ("tiger", 0xd9822b, 0xf2ead8)),
    "giraffe": (quadruped, dict(L=2.0, H=2.0, R=0.42, legR=0.07, neck=2.3, neck_ang=28, head=0.55, tail=0.9, ossicones=True, leg_spread=0.5), ("giraffe", 0xb06a2c, 0xe8d6b0)),
    "zebra": (quadruped, dict(L=1.8, H=1.3, R=0.36, legR=0.075, neck=0.7, neck_ang=45, head=0.55, tail=0.7, snout=1.05), ("zebra", 0x222222)),
    "okapi": (quadruped, dict(L=1.8, H=1.5, R=0.36, legR=0.075, neck=0.75, neck_ang=40, head=0.5, tail=0.5), ("okapi", 0x4a2c1f, 0x5a3a2a)),
    "warthog": (quadruped, dict(L=1.1, H=0.65, R=0.27, legR=0.06, neck=0.15, neck_ang=80, head=0.4, tail=0.35), ("plain", 0x6b5a4a, 0x7d6c5c)),
    "hippo": (quadruped, dict(L=1.5, H=0.75, R=0.4, legR=0.13, neck=0.15, neck_ang=80, head=0.45, head_r=0.3, tail=0.2), ("plain", 0x5d4a52, 0x9a7a7a)),
    "camel": (quadruped, dict(L=2.2, H=1.8, R=0.42, legR=0.09, neck=1.0, neck_ang=55, head=0.5, tail=0.45, hump=2), ("plain", 0xa47c4f, 0xc49c6f)),
    "alpaca": (quadruped, dict(L=1.2, H=0.95, R=0.32, legR=0.07, neck=0.75, neck_ang=18, head=0.32, tail=0.2), ("plain", 0xe2d2b5, 0xf0e4cc)),
    "deer": (quadruped, dict(L=1.0, H=0.6, R=0.2, legR=0.04, neck=0.35, neck_ang=40, head=0.28, tail=0.12), ("plain", 0x9a7a54, 0xd8c4a4)),
    "goat": (quadruped, dict(L=0.8, H=0.6, R=0.22, legR=0.045, neck=0.25, neck_ang=40, head=0.26, tail=0.12), ("plain", 0x6b5f55, 0x9a8f85)),
    "pig": (quadruped, dict(L=1.1, H=0.65, R=0.32, legR=0.06, neck=0.12, neck_ang=80, head=0.35, tail=0.15), ("plain", 0xb88a55, 0xd0a878)),
    "otter": (quadruped, dict(L=0.9, H=0.3, R=0.12, legR=0.035, neck=0.15, neck_ang=70, head=0.18, tail=0.45), ("plain", 0x4a3a2c, 0x8a7a66)),
    "coati": (quadruped, dict(L=0.75, H=0.38, R=0.13, legR=0.035, neck=0.12, neck_ang=70, head=0.24, tail=0.55, snout=1.3), ("plain", 0x7a5a3a, 0xa08060)),
    "wallaby": (quadruped, dict(L=0.6, H=0.6, R=0.2, legR=0.06, neck=0.25, neck_ang=20, head=0.22, tail=0.6), ("plain", 0x8b7a68, 0xc8b8a4)),
    "ostrich": (bird, dict(L=1.0, H=2.2, R=0.42, neck=0.95, beak=0.12, leg_h=1.0), ("plain", 0x2e2a28, 0xd9cfc4)),
    "flamingo": (bird, dict(L=0.55, H=1.2, R=0.17, neck=0.6, beak=0.13, leg_h=0.7, beak_down=0.8), ("flamingo", 0xf08aa0, None, 0x222222)),
    "pelican": (bird, dict(L=0.9, H=1.0, R=0.28, neck=0.35, beak=0.38, leg_h=0.3, pouch=0.12), ("plain", 0xf2f2ee, 0xe8e0d0)),
    "penguin": (upright, dict(H=0.62, R=0.16, beak=0.07, flippers=True), ("penguin", 0x161616)),
    "meerkat": (upright, dict(H=0.34, R=0.07, tail=0.22, flippers=False), ("plain", 0xb59a74, 0xd8c4a4)),
}


def build(sid):
    plan, params, spec = SPECIES[sid]
    kind, base, belly, *rest = list(spec) + [None] * (3 - len(spec))
    s = Skel()
    info = plan(s, **params)
    mesh = bpy.data.meshes.new(sid + "_skel")
    mesh.from_pydata(s.v, s.e, [])
    obj = bpy.data.objects.new(sid + "_skel", mesh)
    bpy.context.scene.collection.objects.link(obj)
    skin = obj.modifiers.new("Skin", "SKIN")
    layer = mesh.skin_vertices[0].data
    for i, r in enumerate(s.r):
        layer[i].radius = r
    layer[0].use_root = True
    sub = obj.modifiers.new("Subdivision", "SUBSURF")
    # Patterned coats need more vertices to hold their markings.
    sub.levels = sub.render_levels = 2 if kind in ("giraffe", "zebra", "tiger", "okapi", "lemur") else 1
    dg = bpy.context.evaluated_depsgraph_get()
    body = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    bpy.data.objects.remove(obj)
    out = bpy.data.objects.new(sid, body)
    bpy.context.scene.collection.objects.link(out)
    for p in body.polygons:
        p.use_smooth = True
    H = params.get("H", 1.0)
    L = params.get("L", 1.0)
    paint = coat(kind, base, belly, rest[0] if rest and rest[0] else None, H=H, L=L, eye=info.get("eye"))
    col = body.color_attributes.new("Col", "BYTE_COLOR", "POINT")
    for i, v in enumerate(body.vertices):
        c = paint(*v.co)
        col.data[i].color = (c[0], c[1], c[2], 1.0)
    body.color_attributes.active_color = col
    mat = bpy.data.materials.get("animal") or bpy.data.materials.new("animal")
    body.materials.append(mat)
    for o in bpy.context.scene.objects:
        o.select_set(o == out)
    bpy.context.view_layer.objects.active = out
    path = os.path.join(OUT, sid + ".glb")
    kw = dict(filepath=path, export_format="GLB", use_selection=True, export_apply=True, export_yup=True)
    try:
        bpy.ops.export_scene.gltf(**kw, export_vertex_color="ACTIVE")
    except TypeError:
        bpy.ops.export_scene.gltf(**kw, export_colors=True)
    tris = sum(len(p.vertices) - 2 for p in body.polygons)
    log(f"{sid}: {len(body.vertices)} verts, ~{tris} tris -> {os.path.getsize(path) // 1024} KB")
    bpy.data.objects.remove(out)
    # Legs in three.js axes (x forward, y up, z = -Blender y).
    leg_r = params.get("legR") or params.get("R", 0.2) * 0.2
    return {"legs": [[round(x, 3), round(z, 3), round(-y, 3)] for x, y, z in s.legs], "height": H, "legR": round(leg_r, 3)}


def main():
    only = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    bpy.ops.wm.read_factory_settings(use_empty=True)
    os.makedirs(OUT, exist_ok=True)
    index_path = os.path.join(OUT, "animals.json")
    index = json.load(open(index_path)) if os.path.exists(index_path) else {}
    for sid in SPECIES:
        if only and sid not in only:
            continue
        index[sid] = build(sid)
    json.dump(index, open(index_path, "w"), indent=1)
    log("done")


try:
    main()
except Exception:
    import traceback
    log(traceback.format_exc())
    log("failed")
