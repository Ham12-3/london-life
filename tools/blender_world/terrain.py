"""Give the Blender zoo its ground levels (tools/terrain/height.py) and the works that go with them:
the ground, paths and ponds follow the canal cutting and the tunnel ramps; the Regent's Canal
lies 5.5 m down with brick walls at the water; the tunnels under the Outer Circle get brick
ramp walls, vaulted brick passages and classical stone portals (after Decimus Burton's East
Tunnel); bridges get brick parapets with stone coping and piers down to the water.

    python tools/terrain/height.py
    python tools/blender_mcp.py run tools/blender_world/terrain.py     (after scene.py)
"""
import bmesh
import bpy
import importlib.util
import json
import math
import os
import struct

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
spec = importlib.util.spec_from_file_location("landmark_build", os.path.join(ROOT, "tools", "landmarks", "build.py"))
lb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lb)
Builder = lb.Builder
mspec = importlib.util.spec_from_file_location("zoo_mats", os.path.join(os.path.dirname(__file__), "materials.py"))
mats = importlib.util.module_from_spec(mspec)
mspec.loader.exec_module(mats)

T = json.load(open(os.path.join(ROOT, "public", "assets", "terrain", "terrain.json")))
H = struct.unpack(f"<{T['nx'] * T['nz']}f", open(os.path.join(ROOT, "public", "assets", "terrain", "height.bin"), "rb").read())
world = json.load(open(os.path.join(ROOT, "public", "world.json"), encoding="utf-8"))


def height(x, z):
    """Bilinear ground level at world (x, z)."""
    gx, gz = (x - T["x0"]) / T["step"], (z - T["z0"]) / T["step"]
    i, j = int(math.floor(gx)), int(math.floor(gz))
    if i < 0 or j < 0 or i >= T["nx"] - 1 or j >= T["nz"] - 1:
        return 0.0
    fx, fz = gx - i, gz - j
    h = lambda a, b: H[b * T["nx"] + a]
    return (h(i, j) * (1 - fx) + h(i + 1, j) * fx) * (1 - fz) + (h(i, j + 1) * (1 - fx) + h(i + 1, j + 1) * fx) * fz


def low(x, z):
    """Is (x, z) in or next to ground that isn't level?"""
    for dx in (-3, 0, 3):
        for dz in (-3, 0, 3):
            if height(x + dx, z + dz) < -0.02:
                return True
    return False


def conform(obj, max_edge=2.5, offset=lambda x, z, zc: zc + height(x, z), passes=9):
    """Subdivide an object's faces near the cutting until edges are short, then drop every vertex
    onto the ground (Blender y = -world z)."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])

    def near(e):
        a, b = e.verts[0].co, e.verts[1].co
        n = max(1, int(e.calc_length() / 2))
        return any(low(a.x + (b.x - a.x) * k / n, -(a.y + (b.y - a.y) * k / n)) for k in range(n + 1))

    for _ in range(passes):
        long_edges = [e for e in bm.edges if e.calc_length() > max_edge and near(e)]
        if not long_edges:
            break
        bmesh.ops.subdivide_edges(bm, edges=long_edges, cuts=1)
        bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 3])
    for v in bm.verts:
        v.co.z = offset(v.co.x, -v.co.y, v.co.z)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def grid_base(obj, cell=40.0):
    """Replace the single-quad park lawn with a coarse grid so it can be subdivided locally."""
    me = obj.data
    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    if len(me.polygons) != 1:
        return
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    bm = bmesh.new()
    nx, ny = int((x1 - x0) / cell), int((y1 - y0) / cell)
    vs = [[bm.verts.new((x0 + (x1 - x0) * i / nx, y0 + (y1 - y0) * j / ny, 0)) for i in range(nx + 1)] for j in range(ny + 1)]
    for j in range(ny):
        for i in range(nx):
            bm.faces.new((vs[j][i], vs[j][i + 1], vs[j + 1][i + 1], vs[j + 1][i]))
    bm.to_mesh(me)
    bm.free()


col = bpy.data.collections["London Zoo"]
ground = bpy.data.objects["Ground"]
# The base lawn is one face of the Ground mesh: give the whole Ground a coarse grid first by
# splitting faces larger than the grid cell.
bm = bmesh.new()
bm.from_mesh(ground.data)
big = [f for f in bm.faces if f.calc_area() > 40000]
if big:
    bmesh.ops.subdivide_edges(bm, edges=list({e for f in big for e in f.edges}), cuts=44, use_grid_fill=True)
bm.to_mesh(ground.data)
bm.free()
conform(ground)

# Paths: bridges stay at deck level; everything else follows the ground.
paths = bpy.data.objects["Paths"]
conform(paths, max_edge=2.0)
# Bridge decks (their boards) stay up at deck level, over the cutting.
me = paths.data
boards = next((i for i, m in enumerate(me.materials) if m and m.name.split(".")[0] == "boards"), None)
if boards is not None:
    for poly in me.polygons:
        if poly.material_index == boards:
            for vi in poly.vertices:
                me.vertices[vi].co.z = 0.14
    me.update()

# Open tunnel ramps: the earthworks bring their own floor and walls.
cspec = importlib.util.spec_from_file_location("corridors", os.path.join(os.path.dirname(__file__), "corridors.py"))
corridors = importlib.util.module_from_spec(cspec)
corridors._imported = True
cspec.loader.exec_module(corridors)
for name in ("Ground", "Paths"):
    corridors.cut(bpy.data.objects[name], T)

# Water: the canal sits at canal level, the ponds stay where they are.
water = bpy.data.objects["Water"]
bm = bmesh.new()
bm.from_mesh(water.data)
canal_level = T["water"]
for v in bm.verts:
    if height(v.co.x, -v.co.y) < canal_level + 0.2:
        v.co.z = canal_level
for f in bm.faces:
    if all(height(v.co.x, -v.co.y) < -0.5 for v in f.verts):
        for v in f.verts:
            v.co.z = canal_level
bm.to_mesh(water.data)
bm.free()

# Works: canal walls, tunnels, bridges.
old = bpy.data.objects.get("Earthworks")
if old:
    bpy.data.objects.remove(old, do_unlink=True)
B = Builder()
W2B = lambda p: (p[0], -p[1])

# Brick walls where the canal meets its towpath and banks.
for line in T["canal"]:
    pts = [W2B(p) for p in line]
    for side in (1, -1):
        prev = None
        for a, b in zip(pts, pts[1:]):
            L = math.dist(a, b)
            if L < 0.5:
                continue
            nx, ny = -(b[1] - a[1]) / L * side, (b[0] - a[0]) / L * side
            for k in range(int(L // 2) + 1):
                t = min(L, k * 2.0)
                x, y = a[0] + (b[0] - a[0]) * t / L + nx * 7.0, a[1] + (b[1] - a[1]) * t / L + ny * 7.0
                if prev and math.dist(prev, (x, y)) < 4 and height(x, -y) < -4:
                    B.face([(prev[0], prev[1], canal_level - 1.0), (x, y, canal_level - 1.0), (x, y, T["towpath"] + 0.15), (prev[0], prev[1], T["towpath"] + 0.15)], "brick_buff")
                    B.face([(prev[0], prev[1], T["towpath"] + 0.15), (x, y, T["towpath"] + 0.15), (x + nx * 0.4, y + ny * 0.4, T["towpath"] + 0.15), (prev[0] + nx * 0.4, prev[1] + ny * 0.4, T["towpath"] + 0.15)], "stone")
                prev = (x, y)

# Tunnels under the Outer Circle.
for tun in T["tunnels"]:
    pts = [W2B(p) for p in tun["pts"]]
    half = tun["w"] / 2 + 1.2
    c0, c1 = tun["covered"]
    floor = tun["floor"]
    samples, run = [], 0.0
    for a, b in zip(pts, pts[1:]):
        L = math.dist(a, b)
        for k in range(int(L) + 1):
            t = k / max(1, int(L))
            ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            samples.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, run + t * L, ux, uy))
        run += L
    def depth(s):
        if c0 <= s <= c1:
            return floor
        gap = c0 - s if s < c0 else s - c1
        t = max(0.0, min(1.0, gap / 18.0))
        return floor * (1 - t * t * (3 - 2 * t))
    # The tunnel floor (a paved path) and the walls either side.
    for (x0, y0, s0, ux, uy), (x1, y1, s1, _, _) in zip(samples, samples[1:]):
        nx, ny = -uy, ux
        z0, z1 = depth(s0), depth(s1)
        B.face([(x0 - nx * half, y0 - ny * half, z0 + 0.06), (x1 - nx * half, y1 - ny * half, z1 + 0.06), (x1 + nx * half, y1 + ny * half, z1 + 0.06), (x0 + nx * half, y0 + ny * half, z0 + 0.06)], "paving")
        covered = c0 <= (s0 + s1) / 2 <= c1
        for sd in (1, -1):
            ax, ay, bx, by = x0 + nx * half * sd, y0 + ny * half * sd, x1 + nx * half * sd, y1 + ny * half * sd
            top = 2.6 + min(z0, z1) if covered else 0.45
            if not covered and z0 > -0.1 and z1 > -0.1:
                continue
            B.face([(ax, ay, min(z0, z1) - 0.1), (bx, by, min(z0, z1) - 0.1), (bx, by, top), (ax, ay, top)], "brick_buff")
            if not covered:  # coping on the ramp walls
                B.face([(ax, ay, top), (bx, by, top), (bx + nx * sd * 0.35, by + ny * sd * 0.35, top), (ax + nx * sd * 0.35, ay + ny * sd * 0.35, top)], "stone")
        if covered:  # the brick barrel vault
            zc = 2.6 + floor
            segs = 10
            for k in range(segs):
                t0, t1 = math.pi * k / segs, math.pi * (k + 1) / segs
                p = lambda xx, yy, t: (xx + nx * half * math.cos(t), yy + ny * half * math.cos(t), zc + half * 0.7 * math.sin(t))
                B.face([p(x0, y0, t0), p(x1, y1, t0), p(x1, y1, t1), p(x0, y0, t1)], "brick_buff")
    # Classical stone portals at both ends of the covered stretch.
    for s_end, dirn in ((c0, -1), (c1, 1)):
        smp = min(samples, key=lambda q: abs(q[2] - s_end))
        x, y, s, ux, uy = smp
        nx, ny = -uy, ux
        zf = floor
        ox, oy = x + ux * dirn * 0.15, y + uy * dirn * 0.15
        for sd in (1, -1):  # pilasters
            px, py = ox + nx * (half + 0.4) * sd, oy + ny * (half + 0.4) * sd
            B.box((px, py, zf + 1.9), (0.7, 0.7, 3.8), math.atan2(uy, ux), "stone")
        B.box((ox, oy, zf + 3.95), (2 * half + 2.2, 0.8, 0.55), math.atan2(ny, nx), "stone")  # cornice over the arch
        B.box((ox, oy, zf + 4.35), (2 * half + 1.6, 0.6, 0.3), math.atan2(ny, nx), "stone")
        arch_r = half
        for k in range(12):  # voussoirs round the arch head
            t0, t1 = math.pi * k / 12, math.pi * (k + 1) / 12
            zc = zf + 2.6
            q = lambda t, r: (ox + nx * r * math.cos(t), oy + ny * r * math.cos(t), zc + r * 0.7 * math.sin(t))
            B.face([q(t0, arch_r), q(t1, arch_r), q(t1, arch_r + 0.45), q(t0, arch_r + 0.45)], "stone")

# Bridges over the cutting: parapets and piers.
for p in world["paths"]:
    if not p.get("bridge"):
        continue
    pts = [W2B(q) for q in p["pts"]]
    half = p["w"] / 2
    lowest = min(height(x, -y) for x, y in pts)
    if lowest > -1:
        continue  # a bridge over a pond: the deck alone is enough
    for a, b in zip(pts, pts[1:]):
        L = math.dist(a, b)
        if L < 0.3:
            continue
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        nx, ny = -uy, ux
        for sd in (1, -1):
            ax, ay, bx, by = a[0] + nx * (half + 0.15) * sd, a[1] + ny * (half + 0.15) * sd, b[0] + nx * (half + 0.15) * sd, b[1] + ny * (half + 0.15) * sd
            B.box(((ax + bx) / 2, (ay + by) / 2, 0.68), (L + 0.3, 0.3, 1.1), math.atan2(uy, ux), "brick_red")
            B.box(((ax + bx) / 2, (ay + by) / 2, 1.27), (L + 0.4, 0.42, 0.1), math.atan2(uy, ux), "stone")
        # Deck slab and fascia.
        B.face([(a[0] - nx * (half + 0.3), a[1] - ny * (half + 0.3), -0.55), (a[0] + nx * (half + 0.3), a[1] + ny * (half + 0.3), -0.55),
                (b[0] + nx * (half + 0.3), b[1] + ny * (half + 0.3), -0.55), (b[0] - nx * (half + 0.3), b[1] - ny * (half + 0.3), -0.55)], "brick_red")
        # Piers where the deck spans the cutting.
        for t in (0.3, 0.7):
            x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            g = height(x, -y)
            if g < -1:
                B.box((x, y, (g - 0.5 - 0.55) / 2), (0.9, 2 * half + 0.6, -0.55 - g + 0.5), math.atan2(uy, ux), "brick_red")

works = B.build("Earthworks")
for c in list(works.users_collection):
    c.objects.unlink(works)
col.objects.link(works)
for o in works.material_slots:
    m = mats.landmark(o.material.name.split(".")[0]) if o.material else None
    if m:
        o.material = m

# Trees and furniture stand on the ground.
for c in ("Trees", "Furniture"):
    for o in bpy.data.collections[c].objects:
        o.location.z = height(o.location.x, -o.location.y)
print("terrain applied")
