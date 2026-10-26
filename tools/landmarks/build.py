"""Model London Zoo's landmark buildings in Blender on their real OSM footprints and export them.

    powershell tools/landmarks/blender.ps1        (runs prepare.mjs, then this script, headless)

Each landmark becomes public/assets/landmarks/<id>.glb, modelled in metres around its own origin.
Surfaces carry material *names* only (brick_buff, copper, glass...): src/landmarks.js gives them the
same Poly Haven materials as the rest of the zoo, so the landmarks and generated buildings match.
public/assets/landmarks/landmarks.json lists where each goes and which generic buildings it replaces.

Blender axes: x east, y north, z up. glTF export turns that into three.js's x east, y up, z south.
"""
import bpy
import json
import math
import os
import sys
from mathutils import Vector
from mathutils.geometry import delaunay_2d_cdt

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INPUT = os.path.join(ROOT, "work", "landmarks", "input.json")
OUT = os.path.join(ROOT, "public", "assets", "landmarks")
LOG = os.path.join(ROOT, "work", "landmarks", "build.log")

log_file = None


def log(*a):
    global log_file
    log_file = log_file or open(LOG, "w", encoding="utf-8")
    print(*a, file=log_file, flush=True)


# ---------- 2D helpers ----------

def ring(poly):
    """Open list of (x, y) from a closed ring."""
    pts = [tuple(p) for p in poly]
    return pts[:-1] if pts[0] == pts[-1] else pts


def area2(pts):
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))) / 2


def ccw(pts):
    return pts if area2(pts) > 0 else pts[::-1]


def centroid(pts):
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def offset(pts, d):
    """Mitred offset of a counter-clockwise ring: d > 0 grows it, d < 0 shrinks it."""
    n, out = len(pts), []
    for i in range(n):
        p, c, q = pts[i - 1], pts[i], pts[(i + 1) % n]
        e1, e2 = (c[0] - p[0], c[1] - p[1]), (q[0] - c[0], q[1] - c[1])
        l1, l2 = math.hypot(*e1) or 1, math.hypot(*e2) or 1
        n1, n2 = (e1[1] / l1, -e1[0] / l1), (e2[1] / l2, -e2[0] / l2)
        k = d / max(1 + n1[0] * n2[0] + n1[1] * n2[1], 0.25)
        out.append((c[0] + (n1[0] + n2[0]) * k, c[1] + (n1[1] + n2[1]) * k))
    return out


def inside(pts, x, y):
    res = False
    for i in range(len(pts)):
        (xi, yi), (xj, yj) = pts[i], pts[i - 1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            res = not res
    return res


def axes(pts):
    """Principal axis (unit u), its normal v, and half extents along each."""
    cx, cy = centroid(pts)
    sxx = sum((p[0] - cx) ** 2 for p in pts)
    syy = sum((p[1] - cy) ** 2 for p in pts)
    sxy = sum((p[0] - cx) * (p[1] - cy) for p in pts)
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
    u, v = (math.cos(ang), math.sin(ang)), (-math.sin(ang), math.cos(ang))
    a = max(abs((p[0] - cx) * u[0] + (p[1] - cy) * u[1]) for p in pts)
    b = max(abs((p[0] - cx) * v[0] + (p[1] - cy) * v[1]) for p in pts)
    return (cx, cy), u, v, a, b


def ellipse(c, u, v, a, b, n=40):
    return [(c[0] + u[0] * a * math.cos(t) + v[0] * b * math.sin(t), c[1] + u[1] * a * math.cos(t) + v[1] * b * math.sin(t))
            for t in (2 * math.pi * i / n for i in range(n))]


def resample(pts, step):
    out = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
        out += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)]
    return out


# ---------- mesh builder ----------

class Builder:
    """Collects faces with a material name each, then makes one Blender object."""

    def __init__(self):
        self.verts, self.faces, self.mats, self.uvs, self.smooth = [], [], [], [], []
        self.names = []

    def mat(self, name):
        if name not in self.names:
            self.names.append(name)
        return self.names.index(name)

    def face(self, pts, mat, uvs=None, smooth=False):
        base = len(self.verts)
        self.verts += [tuple(p) for p in pts]
        self.faces.append(list(range(base, base + len(pts))))
        self.mats.append(self.mat(mat))
        self.uvs.append(uvs or [(p[0] / 2, p[1] / 2 + p[2] / 2) for p in pts])
        self.smooth.append(smooth)

    def shared(self, verts, faces, mat, uv_fn, smooth=True):
        """A surface whose faces share vertices, so it shades smoothly."""
        base = len(self.verts)
        self.verts += [tuple(v) for v in verts]
        for f in faces:
            self.faces.append([base + i for i in f])
            self.mats.append(self.mat(mat))
            self.uvs.append([uv_fn(verts[i]) for i in f])
            self.smooth.append(smooth)

    def prism(self, pts, z0, z1, mat, top=True, bottom=False, top_mat=None, ztop=None):
        """Vertical walls round a counter-clockwise ring; ztop(x, y) lets the top slope."""
        zt = ztop or (lambda x, y: z1)
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            self.face([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], zt(*b)), (a[0], a[1], zt(*a))], mat)
        if top:
            self.face([(p[0], p[1], zt(*p)) for p in pts], top_mat or mat)
        if bottom:
            self.face([(p[0], p[1], z0) for p in pts[::-1]], mat)

    def ring_wall(self, pts, z0, z1, t, mat):
        inner = offset(pts, -t)
        n = len(pts)
        for i in range(n):
            a, b, ia, ib = pts[i], pts[(i + 1) % n], inner[i], inner[(i + 1) % n]
            self.face([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)], mat)
            self.face([(ib[0], ib[1], z0), (ia[0], ia[1], z0), (ia[0], ia[1], z1), (ib[0], ib[1], z1)], mat)
            self.face([(a[0], a[1], z1), (b[0], b[1], z1), (ib[0], ib[1], z1), (ia[0], ia[1], z1)], mat)

    def box(self, c, size, yaw, mat):
        sx, sy, sz = size[0] / 2, size[1] / 2, size[2] / 2
        cs, sn = math.cos(yaw), math.sin(yaw)
        P = lambda x, y, z: (c[0] + x * cs - y * sn, c[1] + x * sn + y * cs, c[2] + z)
        v = [P(x, y, z) for z in (-sz, sz) for y in (-sy, sy) for x in (-sx, sx)]
        for f in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)):
            self.face([v[i] for i in f], mat)

    def tube(self, a, b, r, mat, n=8):
        a, b = Vector(a), Vector(b)
        d = (b - a)
        if d.length < 1e-6:
            return
        d.normalize()
        side = d.cross(Vector((0, 0, 1)) if abs(d.z) < 0.95 else Vector((1, 0, 0))).normalized()
        up = side.cross(d).normalized()
        ring_a = [a + (side * math.cos(t) + up * math.sin(t)) * r for t in (2 * math.pi * k / n for k in range(n))]
        ring_b = [p + (b - a) for p in ring_a]
        for k in range(n):
            self.face([ring_a[k], ring_a[(k + 1) % n], ring_b[(k + 1) % n], ring_b[k]], mat, smooth=True)

    def polyline_tube(self, pts, r, mat, n=8):
        for i in range(len(pts) - 1):
            self.tube(pts[i], pts[i + 1], r, mat, n)

    def slab_sweep(self, path, width, thick, mat):
        """A flat slab (ramp) following a 3D path, level across its width."""
        rings = []
        for i, p in enumerate(path):
            q = path[min(i + 1, len(path) - 1)] if i < len(path) - 1 else p
            o = path[max(i - 1, 0)]
            t = Vector((q[0] - o[0], q[1] - o[1], 0)).normalized()
            s = Vector((t.y, -t.x, 0)) * (width / 2)
            P = Vector(p)
            rings.append([P - s, P + s, P + s - Vector((0, 0, thick)), P - s - Vector((0, 0, thick))])
        for i in range(len(rings) - 1):
            A, B = rings[i], rings[i + 1]
            for k in range(4):
                self.face([A[k], A[(k + 1) % 4], B[(k + 1) % 4], B[k]][::-1], mat)
        self.face(rings[0], mat)
        self.face(rings[-1][::-1], mat)

    def dome(self, c, r, h, mat, seg=16, rings_n=6):
        cx, cy, cz = c
        pts = [[(cx + r * math.cos(phi) * math.cos(2 * math.pi * k / seg), cy + r * math.cos(phi) * math.sin(2 * math.pi * k / seg),
                 cz + h * math.sin(phi)) for k in range(seg)] for phi in (math.pi / 2 * j / rings_n for j in range(rings_n))]
        top = (cx, cy, cz + h)
        for j in range(rings_n - 1):
            for k in range(seg):
                self.face([pts[j][k], pts[j][(k + 1) % seg], pts[j + 1][(k + 1) % seg], pts[j + 1][k]], mat, smooth=True)
        for k in range(seg):
            self.face([pts[-1][k], pts[-1][(k + 1) % seg], top], mat, smooth=True)

    def sphere(self, c, r, mat, seg=12):
        self.dome(c, r, r, mat, seg, 5)
        self.dome(c, r, -r, mat, seg, 5)

    def roof(self, sk, mat_for):
        """Hipped roof from a straight skeleton; mat_for(face_points) picks each face's material."""
        V = [(x, y, sk["eave"] + t * sk["slope"]) for x, y, t in sk["vertices"]]
        for poly in sk["polygons"]:
            pts = [V[i] for i in poly]
            # Faces come out wound either way: make them face up.
            nz = sum((pts[i][0] - pts[i - 1][0]) * (pts[i][1] + pts[i - 1][1]) for i in range(len(pts)))
            if nz > 0:
                pts = pts[::-1]
            for part, m in mat_for(pts):
                if len(part) >= 3:
                    self.face(part, m)

    def build(self, name, bevel=0.0):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(self.verts, [], self.faces)
        mesh.update()
        for nm in self.names:
            mat = bpy.data.materials.get(nm) or bpy.data.materials.new(nm)
            mesh.materials.append(mat)
        mesh.polygons.foreach_set("material_index", self.mats)
        mesh.polygons.foreach_set("use_smooth", self.smooth)
        uv = mesh.uv_layers.new(name="UVMap")
        for poly, uvs in zip(mesh.polygons, self.uvs):
            for li, (s, t) in zip(poly.loop_indices, uvs):
                uv.data[li].uv = (s, t)
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        if bevel:
            m = obj.modifiers.new("Bevel", "BEVEL")
            m.width = bevel
            m.segments = 1
            m.limit_method = "ANGLE"
            m.angle_limit = math.radians(35)
        return obj


def clip_z(pts, zc):
    """Split a planar polygon at height zc into (below, above) parts."""
    below, above = [], []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        for out, keep in ((below, lambda p: p[2] <= zc), (above, lambda p: p[2] >= zc)):
            if keep(a):
                out.append(a)
            if (a[2] - zc) * (b[2] - zc) < 0:
                t = (zc - a[2]) / (b[2] - a[2])
                out.append(tuple(a[k] + (b[k] - a[k]) * t for k in range(3)))
    return below, above


# ---------- landmarks ----------

def penguin_pool(L, B):
    """Berthold Lubetkin & Tecton, 1934: an elliptical white concrete enclosure with two interlocking,
    unsupported spiral ramps over a blue pool."""
    P = ccw(ring(L["footprints"][0]))
    c, u, v, a, b = axes(P)
    B.ring_wall(P, 0, 1.15, 0.28, "concrete_white")
    B.face([(x, y, 0.09) for x, y in offset(P, -0.28)], "concrete_floor")  # above the map's own pool water
    pc = (c[0] + u[0] * a * 0.36, c[1] + u[1] * a * 0.36)
    pool = ellipse(pc, u, v, a * 0.5, b * 0.6, 48)
    B.ring_wall(pool, 0.04, 0.42, 0.22, "concrete_white")
    B.face([(x, y, 0.3) for x, y in offset(pool, -0.22)], "pool_water")
    # Two ramps winding round each other: each climbs a half-and-a-bit turn from the floor.
    o = (c[0] - u[0] * a * 0.1, c[1] - u[1] * a * 0.1)
    for k, s in enumerate((1, -1)):
        ctr = (o[0] + v[0] * b * 0.1 * s, o[1] + v[1] * b * 0.1 * s)
        path = []
        for i in range(61):
            f = i / 60
            th = math.pi * (0.5 + k) + s * math.pi * 1.15 * f
            r_u, r_v = a * 0.42, b * 0.44
            x = ctr[0] + u[0] * r_u * math.cos(th) + v[0] * r_v * math.sin(th)
            y = ctr[1] + u[1] * r_u * math.cos(th) + v[1] * r_v * math.sin(th)
            path.append((x, y, 0.06 + 1.55 * (3 * f * f - 2 * f * f * f)))
        B.slab_sweep(path, 1.05, 0.16, "concrete_white")
    # Nesting boxes along the far end of the wall.
    for i in range(5):
        t = -0.75 + i * 0.12
        x, y = c[0] + u[0] * a * t * 1.1 + v[0] * (b - 0.75), c[1] + u[1] * a * t * 1.1 + v[1] * (b - 0.75)
        B.box((x, y, 0.35), (1.2, 0.7, 0.62), math.atan2(u[1], u[0]), "concrete_white")
    return {"top": 2.0}


def tension_net(B, P, peaks, base, reach=17.0, mat="net"):
    """Mesh draped over an outline (held at height `base`) and pulled up to mast/frame peaks: a
    constrained Delaunay surface over the outline, tented to the peaks, then relaxed like a cable net."""
    bnd = resample(P, 1.6)
    pts = list(bnd)
    gx = min(p[0] for p in P)
    while gx < max(p[0] for p in P):
        gy = min(p[1] for p in P)
        while gy < max(p[1] for p in P):
            if inside(P, gx, gy) and min(math.hypot(gx - q[0], gy - q[1]) for q in bnd) > 1.0:
                pts.append((gx, gy))
            gy += 1.7
        gx += 1.7
    apex_idx = []
    for (x, y, h) in peaks:
        apex_idx.append(len(pts))
        pts.append((x, y))
    nb = len(bnd)
    res = delaunay_2d_cdt([Vector(p) for p in pts], [(i, (i + 1) % nb) for i in range(nb)], [], 1, 1e-4)
    vco, faces, orig = res[0], res[2], res[3]
    fixed, z = {}, []
    for i, co in enumerate(vco):
        src = orig[i][0] if orig[i] else None
        if src is not None and src < nb:
            fixed[i] = base
        elif src is not None and src in apex_idx:
            fixed[i] = peaks[apex_idx.index(src)][2] - 0.2
        tent = max(base, max(h - (h - base) * math.hypot(co.x - x, co.y - y) / reach for x, y, h in peaks))
        z.append(fixed.get(i, tent))
    nbrs = [set() for _ in vco]
    for f in faces:
        for i in range(len(f)):
            nbrs[f[i]].add(f[i - 1])
            nbrs[f[i - 1]].add(f[i])
    for _ in range(60):  # relax towards a tension surface
        z = [z[i] if i in fixed else 0.5 * z[i] + 0.5 * sum(z[j] for j in nbrs[i]) / max(1, len(nbrs[i])) for i in range(len(vco))]
    B.shared([(co.x, co.y, z[i]) for i, co in enumerate(vco)], [list(f) for f in faces], mat, lambda p: (p[0] / 2, p[1] / 2))


def snowdon_aviary(L, B):
    """Cedric Price, Lord Snowdon & Frank Newby, 1964: aluminium tetrahedral frames held in tension,
    with stainless-steel mesh draped between their peaks. Now Monkey Valley."""
    P = ccw(ring(L["footprints"][0]))
    c, u, v, a, b = axes(P)
    B.ring_wall(P, 0, 0.6, 0.3, "concrete")
    at = lambda s, t: (c[0] + u[0] * a * s + v[0] * b * t, c[1] + u[1] * a * s + v[1] * b * t)
    peaks = []
    for s, t, h in ((-0.42, 0.22, 21.0), (-0.42, -0.22, 17.0), (0.36, -0.2, 19.0), (0.36, 0.2, 15.5)):
        x, y = at(s, t)
        while not inside(P, x, y):
            x, y = (x * 0.8 + c[0] * 0.2, y * 0.8 + c[1] * 0.2)
        peaks.append((x, y, h))
    # Frames: each peak stands on three raking legs; the pairs are tied by a top chord.
    for (x, y, h) in peaks:
        for k in range(3):
            ang = math.atan2(u[1], u[0]) + math.pi / 2 + 2 * math.pi * k / 3
            R = 7.5
            gx, gy = x + R * math.cos(ang), y + R * math.sin(ang)
            while not inside(P, gx, gy) and R > 2:
                R *= 0.85
                gx, gy = x + R * math.cos(ang), y + R * math.sin(ang)
            B.tube((gx, gy, 0.6), (x, y, h), 0.2, "alu", 10)
    B.tube(peaks[0], peaks[1], 0.14, "alu")
    B.tube(peaks[2], peaks[3], 0.14, "alu")
    tension_net(B, P, peaks, 0.6)
    return {"top": max(h for _, _, h in peaks) + 0.5}


def casson_pavilion(L, B):
    """Sir Hugh Casson, 1965 (the old Elephant and Rhino Pavilion): a cluster of ribbed concrete
    towers with sloping copper roofs and clerestory glazing, like a herd at a watering hole."""
    P = ccw(ring(L["footprints"][0]))
    c, u, v, a, b = axes(P)
    B.prism(P, 0, 3.4, "concrete_ribbed", top=True, top_mat="concrete_roof")
    # Tower positions: k-means over the footprint's interior.
    samples = []
    x0, x1 = min(p[0] for p in P), max(p[0] for p in P)
    y0, y1 = min(p[1] for p in P), max(p[1] for p in P)
    for i in range(40):
        for j in range(40):
            x, y = x0 + (x1 - x0) * (i + 0.5) / 40, y0 + (y1 - y0) * (j + 0.5) / 40
            if inside(P, x, y):
                samples.append((x, y))
    K = 5
    cents = [samples[len(samples) * k // K] for k in range(K)]
    for _ in range(25):
        groups = [[] for _ in range(K)]
        for s in samples:
            groups[min(range(K), key=lambda k: (s[0] - cents[k][0]) ** 2 + (s[1] - cents[k][1]) ** 2)].append(s)
        cents = [centroid(g) if g else cents[k] for k, g in enumerate(groups)]
    heights = [13.0, 11.2, 12.4, 10.4, 11.8]
    slopes = [u, v, (-u[0], -u[1]), (-v[0], -v[1]), u]
    for k, (cx, cy) in enumerate(cents):
        half = 4.6
        while half > 2.4:
            corners = [(cx + u[0] * half * sx + v[0] * half * sy, cy + u[1] * half * sx + v[1] * half * sy) for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1))]
            if all(inside(P, *p) for p in corners):
                break
            half *= 0.9
        H, d = heights[k], slopes[k]
        cut = half * 0.22
        oct_pts = []
        for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1)):
            for (px, py) in (((half - cut) * sx, half * sy), (half * sx, (half - cut) * sy)) if sx * sy > 0 else ((half * sx, (half - cut) * sy), ((half - cut) * sx, half * sy)):
                oct_pts.append((cx + u[0] * px + v[0] * py, cy + u[1] * px + v[1] * py))
        oct_pts = ccw(oct_pts)
        rise = 2.8
        zroof = lambda x, y, H=H, d=d, half=half, cx=cx, cy=cy: H - rise / 2 + rise / 2 * ((x - cx) * d[0] + (y - cy) * d[1]) / half
        B.prism(oct_pts, 0, H, "concrete_ribbed", top=False, ztop=lambda x, y: zroof(x, y) - 0.05)
        # Vertical fins down each face (the bush-hammered ribs).
        for i in range(len(oct_pts)):
            p, q = oct_pts[i], oct_pts[(i + 1) % len(oct_pts)]
            ln = math.hypot(q[0] - p[0], q[1] - p[1])
            nx, ny = (q[1] - p[1]) / ln, -(q[0] - p[0]) / ln
            for m in range(1, int(ln / 0.75)):
                t = m * 0.75 / ln
                fx, fy = p[0] + (q[0] - p[0]) * t + nx * 0.1, p[1] + (q[1] - p[1]) * t + ny * 0.1
                top = zroof(fx, fy) - 0.5
                B.box((fx, fy, (0.5 + top) / 2), (0.13, 0.2, top - 0.5), math.atan2(q[1] - p[1], q[0] - p[0]), "concrete_ribbed")
        # Copper roof slab with an overhang, and clerestory glazing under its high edge.
        ov = offset(oct_pts, 0.55)
        B.face([(x, y, zroof(x, y) + 0.22) for x, y in ov], "copper")
        B.face([(x, y, zroof(x, y)) for x, y in ov[::-1]], "copper")
        for i in range(len(ov)):
            p, q = ov[i], ov[(i + 1) % len(ov)]
            B.face([(p[0], p[1], zroof(*p)), (q[0], q[1], zroof(*q)), (q[0], q[1], zroof(*q) + 0.22), (p[0], p[1], zroof(*p) + 0.22)], "copper")
        hp = [p for p in oct_pts if ((p[0] - cx) * d[0] + (p[1] - cy) * d[1]) > half * 0.7]
        if len(hp) >= 2:
            p, q = hp[0], hp[-1]
            nx, ny = d[0] * 0.04, d[1] * 0.04
            z1 = min(zroof(*p), zroof(*q)) - 0.15
            B.face([(p[0] + nx, p[1] + ny, z1 - 1.3), (q[0] + nx, q[1] + ny, z1 - 1.3), (q[0] + nx, q[1] + ny, z1), (p[0] + nx, p[1] + ny, z1)], "glass")
            B.face([(q[0] + nx, q[1] + ny, z1 - 1.3), (p[0] + nx, p[1] + ny, z1 - 1.3), (p[0] + nx, p[1] + ny, z1), (q[0] + nx, q[1] + ny, z1)], "glass")
    return {"top": max(heights) + 0.5}


def clock_tower(L, B):
    """Decimus Burton, 1828: a small brick building under a slate roof, with a white timber clock
    stage, an open lantern, a lead cupola and a weather vane."""
    P = ccw(ring(L["footprints"][0]))
    c, u, v, a, b = axes(P)
    B.prism(P, 0, 4.6, "brick_buff", top=False)
    B.prism(offset(P, 0.05), 0, 0.5, "stone", top=False)
    for sk in L["roofs"]:
        B.roof(sk, lambda pts: [(pts, "slate")])
    T = ccw(ring(L["footprints"][1])) if len(L["footprints"]) > 1 else P
    tx, ty = centroid(T)
    yaw = math.atan2(u[1], u[0])
    B.box((tx, ty, 3.2), (3.0, 3.0, 6.4), yaw, "brick_buff")
    B.box((tx, ty, 6.52), (3.3, 3.3, 0.25), yaw, "stone")
    B.box((tx, ty, 7.82), (2.5, 2.5, 2.35), yaw, "timber_white")
    for k in range(4):
        ang = yaw + k * math.pi / 2
        nx, ny = math.cos(ang), math.sin(ang)
        sx, sy = -ny, nx
        cx, cy, zc, r = tx + nx * 1.27, ty + ny * 1.27, 7.85, 0.72
        q = [(cx - sx * r, cy - sy * r, zc - r), (cx + sx * r, cy + sy * r, zc - r), (cx + sx * r, cy + sy * r, zc + r), (cx - sx * r, cy - sy * r, zc + r)]
        B.face(q, "clock_face", uvs=[(0, 0), (1, 0), (1, 1), (0, 1)])
    B.box((tx, ty, 9.11), (2.9, 2.9, 0.22), yaw, "timber_white")
    for k in range(8):
        ang = yaw + math.pi / 8 + k * math.pi / 4
        B.tube((tx + 0.95 * math.cos(ang), ty + 0.95 * math.sin(ang), 9.22), (tx + 0.95 * math.cos(ang), ty + 0.95 * math.sin(ang), 10.6), 0.07, "timber_white")
    octo = [(tx + 1.15 * math.cos(yaw + math.pi / 8 + k * math.pi / 4), ty + 1.15 * math.sin(yaw + math.pi / 8 + k * math.pi / 4)) for k in range(8)]
    B.prism(octo, 10.6, 10.78, "timber_white", top=True, bottom=True)
    B.dome((tx, ty, 10.78), 1.0, 1.05, "lead")
    B.tube((tx, ty, 11.8), (tx, ty, 12.7), 0.035, "gold")
    B.sphere((tx, ty, 11.95), 0.13, "gold")
    B.box((tx + math.cos(yaw) * 0.25, ty + math.sin(yaw) * 0.25, 12.45), (0.9, 0.03, 0.28), yaw, "iron")
    return {"top": 12.7}


def giraffe_house(L, B):
    """Decimus Burton, 1836-37: yellow stock brick with very tall doors for the giraffes, a stone
    band at the eaves and a hipped slate roof with ridge ventilators. Still in use."""
    P = ccw(ring(L["footprints"][0]))
    B.prism(P, 0, 8.0, "brick_buff", top=False)
    B.prism(offset(P, 0.06), 0, 0.6, "stone", top=False)
    B.prism(offset(P, 0.08), 7.55, 8.0, "stone", top=False)
    top = 8.0
    for sk in L["roofs"]:
        B.roof(sk, lambda pts: [(pts, "slate")])
        ts = sorted(sk["vertices"], key=lambda vtx: -vtx[2])
        top = sk["eave"] + ts[0][2] * sk["slope"]
        used = []
        for x, y, t in ts:
            if len(used) == 2:
                break
            if t * sk["slope"] > 1.5 and all(math.hypot(x - ux, y - uy) > 6 for ux, uy in used):
                used.append((x, y))
                zr = sk["eave"] + t * sk["slope"]
                B.box((x, y, zr + 0.45), (2.6, 1.6, 0.9), 0, "timber_white")
                B.box((x, y, zr + 1.0), (3.0, 2.0, 0.2), 0, "slate")
    # The tall giraffe doors: every ~7.5 m along the long walls.
    for i in range(len(P)):
        p, q = P[i], P[(i + 1) % len(P)]
        ln = math.hypot(q[0] - p[0], q[1] - p[1])
        if ln < 7:
            continue
        ux, uy = (q[0] - p[0]) / ln, (q[1] - p[1]) / ln
        nx, ny = uy, -ux
        yaw = math.atan2(uy, ux)
        n = int(ln // 7.5)
        for k in range(n):
            t = (k + 0.5) * ln / n
            x, y = p[0] + ux * t, p[1] + uy * t
            B.box((x + nx * 0.06, y + ny * 0.06, 2.95), (2.8, 0.12, 5.6), yaw, "timber_dark")
            B.box((x + nx * 0.1, y + ny * 0.1, 5.95), (3.4, 0.2, 0.4), yaw, "stone")
            for s in (-1, 1):
                B.box((x + ux * s * 1.55 + nx * 0.08, y + uy * s * 1.55 + ny * 0.08, 2.9), (0.3, 0.16, 5.8), yaw, "stone")
    return {"top": top + 1.2}


def raven_cage(L, B):
    """Decimus Burton, 1829: an octagonal wrought-iron cage under an ogee dome of scrolled ribs."""
    P = ring(L["footprints"][0])
    cx, cy = centroid(P)
    r = 1.42
    oc = [(cx + r * math.cos(math.pi / 8 + k * math.pi / 4), cy + r * math.sin(math.pi / 8 + k * math.pi / 4)) for k in range(8)]
    B.prism(offset(ccw(oc), 0.18), 0, 0.45, "stone", top=True)
    for k in range(8):
        p, q = oc[k], oc[(k + 1) % 8]
        B.tube((p[0], p[1], 0.45), (p[0], p[1], 4.6), 0.055, "iron")
        for m in range(1, 6):
            t = m / 6
            B.tube((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t, 0.45), (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t, 4.6), 0.018, "iron", 6)
        for z in (0.62, 2.6, 4.6):
            B.tube((p[0], p[1], z), (q[0], q[1], z), 0.03, "iron", 6)
        rib = []
        for i in range(13):
            s = i / 12
            rr = r * (1 + 0.28 * math.sin(math.pi * min(1, s * 1.6))) * (1 - s) ** 0.85
            ang = math.pi / 8 + k * math.pi / 4
            rib.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang), 4.6 + 2.6 * s))
        B.polyline_tube(rib, 0.04, "iron", 6)
    B.sphere((cx, cy, 7.35), 0.17, "gold")
    B.tube((cx, cy, 7.5), (cx, cy, 8.1), 0.03, "gold")
    return {"top": 8.2}


def blackburn_pavilion(L, B):
    """1883 (built as the Reptile House), now the tropical bird house: red brick with a terracotta
    frieze, round-arched windows and a hipped roof glazed at its crown."""
    P = ccw(ring(L["footprints"][0]))
    B.prism(P, 0, 6.6, "brick_red", top=False)
    B.prism(offset(P, 0.06), 0, 0.7, "stone", top=False)
    B.prism(offset(P, 0.1), 6.1, 6.6, "terracotta", top=False)
    top = 6.6
    for sk in L["roofs"]:
        maxz = sk["eave"] + max(t for _, _, t in sk["vertices"]) * sk["slope"]
        zc = sk["eave"] + (maxz - sk["eave"]) * 0.45
        B.roof(sk, lambda pts: [(clip_z(pts, zc)[0], "slate"), (clip_z(pts, zc)[1], "glass_roof")])
        top = maxz
    for i in range(len(P)):
        p, q = P[i], P[(i + 1) % len(P)]
        ln = math.hypot(q[0] - p[0], q[1] - p[1])
        if ln < 4:
            continue
        ux, uy = (q[0] - p[0]) / ln, (q[1] - p[1]) / ln
        nx, ny = uy, -ux
        n = int(ln // 3.6)
        for k in range(n):
            t = (k + 0.5) * ln / n
            x, y = p[0] + ux * t, p[1] + uy * t
            for off, w, mat in ((0.025, 0.85, "stone"), (0.04, 0.65, "glass")):
                shape = [(-w, 1.4), (w, 1.4), (w, 3.9)] + [(w * math.cos(math.pi * j / 10), 3.9 + w * math.sin(math.pi * j / 10)) for j in range(1, 10)] + [(-w, 3.9)]
                B.face([(x + ux * sx + nx * off, y + uy * sx + ny * off, z) for sx, z in shape], mat)
    return {"top": top + 0.5}


SIGN_UV = [(0, 0), (1, 0), (1, 1), (0, 1)]


def edges_of(P):
    """(a, b, length, along-x, along-y, out-x, out-y) for each edge of a counter-clockwise ring."""
    out = []
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        ln = math.hypot(b[0] - a[0], b[1] - a[1])
        if ln > 1e-3:
            ux, uy = (b[0] - a[0]) / ln, (b[1] - a[1]) / ln
            out.append((a, b, ln, ux, uy, uy, -ux))
    return out


def wall_panel(B, a, ux, uy, nx, ny, u0, u1, z0, z1, proud, mat, uvs=None):
    """A flat panel on a wall face, `proud` metres out from it, between u0..u1 along the wall."""
    p = lambda u, z: (a[0] + ux * u + nx * proud, a[1] + uy * u + ny * proud, z)
    B.face([p(u0, z0), p(u1, z0), p(u1, z1), p(u0, z1)], mat, uvs=uvs)


def pyramid_roof(B, cx, cy, half, yaw, eave, rise, mat, under="timber_white", overhang=0.7):
    """Square hipped (pyramid) roof with an overhang, soffit and finial."""
    h = half + overhang
    cs, sn = math.cos(yaw), math.sin(yaw)
    corners = [(cx + (x * cs - y * sn), cy + (x * sn + y * cs), eave) for x, y in ((-h, -h), (h, -h), (h, h), (-h, h))]
    apex = (cx, cy, eave + rise)
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        ln = math.dist(a, b)
        slope = math.hypot(h, rise)
        B.face([a, b, apex], mat, uvs=[(0, 0), (ln, 0), (ln / 2, slope)])
    B.face([(x, y, z - 0.12) for x, y, z in corners[::-1]], under)
    B.tube(apex, (cx, cy, eave + rise + 0.7), 0.04, "iron")
    B.sphere((cx, cy, eave + rise + 0.25), 0.12, "iron")


def arched_window(B, x, y, ux, uy, nx, ny, w, z0, z1, mats=("stone", "glass")):
    for off, ww, mat in ((0.025, w / 2 + 0.2, mats[0]), (0.045, w / 2, mats[1])):
        shape = [(-ww, z0), (ww, z0), (ww, z1)] + [(ww * math.cos(math.pi * j / 12), z1 + ww * math.sin(math.pi * j / 12)) for j in range(1, 12)] + [(-ww, z1)]
        B.face([(x + ux * sx + nx * off, y + uy * sx + ny * off, z) for sx, z in shape], mat)


def entrance_world_local(L):
    """The main entrance, in this landmark's local Blender coordinates."""
    world = json.load(open(os.path.join(ROOT, "public", "world.json"), encoding="utf-8"))
    s = world["start"]
    return (s["x"] - L["origin"][0], -(s["z"] - L["origin"][1]))


def main_entrance(L, B):
    """The Outer Circle entrance: two square white lodges with steep dark-tiled pyramid roofs either
    side of a low turnstile block (white columns, roller shutters) under a flat canopy on dark steel
    posts, with the painted LONDON ZOO fascia, crook lamp posts with banners, all behind a brick
    plinth. The building behind is low, rendered and parapeted."""
    P = ccw(ring(L["footprints"][0]))
    render = "render_f1eee6"
    B.prism(P, 0, 3.8, render, top=True, top_mat="roof_flat")
    B.prism(offset(P, 0.05), 0, 0.5, "brick_red", top=False)
    B.ring_wall(P, 3.8, 4.4, 0.25, render)
    B.ring_wall(offset(P, 0.06), 4.4, 4.5, 0.37, "stone")
    # The frontage faces the Outer Circle (north): the long edge whose outside looks north.
    front = max((e for e in edges_of(P) if e[2] > 8), key=lambda e: e[6] * 10 + (e[0][1] + e[1][1]) / 2 * 0.01)
    a, b, Lf, ux, uy, nx, ny = front
    yaw = math.atan2(uy, ux)
    at = lambda u, out=0.0: (a[0] + ux * u + nx * out, a[1] + uy * u + ny * out)
    # Lodges at each end.
    lodge = 4.6
    for u in (1.6, Lf - 1.6):
        cx, cy = at(u, -lodge / 2 + 0.6)
        B.box((cx, cy, 2.4), (lodge, lodge, 4.8), yaw, render)
        B.box((cx, cy, 0.3), (lodge + 0.12, lodge + 0.12, 0.6), yaw, "brick_red")
        for sx in (-1, 1):  # brick quoins up the corners
            for sy in (-1, 1):
                qx = cx + (ux * sx - (-nx) * 0) * (lodge / 2 - 0.15) + nx * sy * (lodge / 2 - 0.15)
                qy = cy + uy * sx * (lodge / 2 - 0.15) + ny * sy * (lodge / 2 - 0.15)
                B.box((qx, qy, 2.4), (0.34, 0.34, 4.8), yaw, "brick_red")
        wx, wy = cx + nx * (lodge / 2 + 0.02), cy + ny * (lodge / 2 + 0.02)
        B.box((wx, wy, 2.6), (1.2, 0.06, 1.4), yaw, "frame_white")
        B.box((wx + nx * 0.01, wy + ny * 0.01, 2.6), (1.0, 0.06, 1.2), yaw, "glass")
        B.box((cx, cy, 4.9), (lodge + 0.3, lodge + 0.3, 0.2), yaw, "stone")
        pyramid_roof(B, cx, cy, lodge / 2, yaw, 5.0, 2.9, "tiles_dark", overhang=0.75)
    # Turnstile frontage between the lodges: shutters between white columns.
    u0, u1 = 1.6 + lodge / 2 + 0.3, Lf - 1.6 - lodge / 2 - 0.3
    bays = max(2, round((u1 - u0) / 2.4))
    bw = (u1 - u0) / bays
    for k in range(bays):
        s0, s1 = u0 + k * bw + 0.22, u0 + (k + 1) * bw - 0.22
        wall_panel(B, a, ux, uy, nx, ny, s0, s1, 0.25, 2.9, 0.05, "shutter", uvs=[(0, 0), (1, 0), (1, 2.6 / 1.28), (0, 2.6 / 1.28)])
    for k in range(bays + 1):
        px, py = at(u0 + k * bw, 0.25)
        B.tube((px, py, 0), (px, py, 3.1), 0.16, "render_f7f5ef", 12)
        B.box((px, py, 0.12), (0.45, 0.45, 0.24), yaw, "stone")
        B.box((px, py, 3.1), (0.45, 0.45, 0.16), yaw, "stone")
    # Canopy on dark posts, with the painted fascia along its front.
    c0, c1, depth = u0 - 1.2, u1 + 1.2, 3.2
    q = lambda u, out, z: (a[0] + ux * u + nx * out, a[1] + uy * u + ny * out, z)
    for z, d in ((3.35, (0, 0, 1)), (3.17, (0, 0, -1))):
        quad = [q(c0, 0, z), q(c1, 0, z), q(c1, depth, z), q(c0, depth, z)]
        B.face(quad if d[2] > 0 else quad[::-1], "paint_2b302d")
    B.face([q(c0, depth, 3.17), q(c1, depth, 3.17), q(c1, depth, 4.45), q(c0, depth, 4.45)], "banner_zoo", uvs=SIGN_UV)
    B.face([q(c1, depth - 0.08, 3.17), q(c0, depth - 0.08, 3.17), q(c0, depth - 0.08, 4.45), q(c1, depth - 0.08, 4.45)], "paint_1f4a2c")
    for u in [c0 + 0.3 + i * (c1 - c0 - 0.6) / 3 for i in range(4)]:
        px, py, _ = q(u, depth - 0.15, 0)
        B.tube((px, py, 0), (px, py, 3.17), 0.07, "paint_2b302d", 10)
    # Crook lamp posts with banners, out on the pavement.
    for u in (-2.5, Lf + 2.5):
        px, py = at(u, 4.0)
        crook = [(px, py, 0), (px, py, 5.2)] + [(px + ux * 0.45 * (1 - math.cos(t)), py + uy * 0.45 * (1 - math.cos(t)), 5.2 + 0.45 * math.sin(t)) for t in (0.4, 0.9, 1.4, 1.9, 2.4, 2.9)]
        B.polyline_tube(crook, 0.06, "paint_e8e8e2", 8)
        bx, by = px + ux * 0.12, py + uy * 0.12
        B.face([(bx, by, 2.6), (bx + ux * 0.6, by + uy * 0.6, 2.6), (bx + ux * 0.6, by + uy * 0.6, 4.6), (bx, by, 4.6)], "fabric_1f6b3a")
    return {"top": 8.6}


def reptile_house(L, B):
    """Joan Procter and Sir Edward Guy Dawber, 1927: dark stock brick with stone dressings; the
    entrance bay has a stone doorcase on two columns carved REPTILE HOUSE, under a great arched
    window; tall round-arched windows down the sides; a hipped roof glazed along its crown."""
    P = ccw(ring(L["footprints"][0]))
    B.prism(P, 0, 7.6, "brick_brown", top=False)
    B.prism(offset(P, 0.06), 0, 0.8, "stone", top=False)
    B.prism(offset(P, 0.12), 7.15, 7.6, "stone", top=False)
    top = 7.6
    for sk in L["roofs"]:
        maxz = sk["eave"] + max(t for _, _, t in sk["vertices"]) * sk["slope"]
        zc = sk["eave"] + (maxz - sk["eave"]) * 0.6
        B.roof(sk, lambda pts: [(clip_z(pts, zc)[0], "slate"), (clip_z(pts, zc)[1], "glass_roof")])
        top = maxz
    ex, ey = entrance_world_local(L)
    es = edges_of(P)
    front = min((e for e in es if e[2] > 9), key=lambda e: math.hypot((e[0][0] + e[1][0]) / 2 - ex, (e[0][1] + e[1][1]) / 2 - ey))
    for e in es:
        a, b, ln, ux, uy, nx, ny = e
        n = int(ln // 4.6)
        for k in range(n):
            t = (k + 0.5) * ln / n
            x, y = a[0] + ux * t, a[1] + uy * t
            if e is front and abs(t - ln / 2) < 5.5:
                continue
            arched_window(B, x, y, ux, uy, nx, ny, 1.4, 3.0, 5.6)
            px, py = x + ux * ln / n / 2, y + uy * ln / n / 2
            if k < n - 1:
                B.box((px + nx * 0.08, py + ny * 0.08, 3.8), (0.55, 0.16, 7.6), math.atan2(uy, ux), "brick_brown")
    a, b, ln, ux, uy, nx, ny = front
    yaw = math.atan2(uy, ux)
    mx, my = a[0] + ux * ln / 2, a[1] + uy * ln / 2
    o = lambda d: (mx + nx * d, my + ny * d)
    bx, by = o(0.3)
    B.box((bx, by, 4.4), (9.2, 0.6, 8.8), yaw, "brick_brown")  # the projecting entrance bay
    B.box((bx, by, 8.9), (9.6, 0.8, 0.25), yaw, "stone")
    fx, fy = o(0.62)
    B.face([(fx - ux * 1.35, fy - uy * 1.35, 0.15), (fx + ux * 1.35, fy + uy * 1.35, 0.15), (fx + ux * 1.35, fy + uy * 1.35, 3.4), (fx - ux * 1.35, fy - uy * 1.35, 3.4)], "timber_dark")
    for s in (-1, 1):  # the doorcase columns
        cx, cy = o(0.85)
        cx, cy = cx + ux * s * 1.75, cy + uy * s * 1.75
        B.box((cx, cy, 0.25), (0.62, 0.62, 0.5), yaw, "stone")
        B.tube((cx, cy, 0.5), (cx, cy, 3.5), 0.22, "stone", 14)
        B.box((cx, cy, 3.62), (0.62, 0.62, 0.24), yaw, "stone")
    ex2, ey2 = o(0.9)
    B.box((ex2, ey2, 4.05), (4.8, 0.6, 0.7), yaw, "stone")  # entablature
    sx, sy = o(1.21)
    B.face([(sx - ux * 2.2, sy - uy * 2.2, 3.82), (sx + ux * 2.2, sy + uy * 2.2, 3.82), (sx + ux * 2.2, sy + uy * 2.2, 4.32), (sx - ux * 2.2, sy - uy * 2.2, 4.32)], "sign_reptile", uvs=SIGN_UV)
    # The great arched window over the door, with radiating glazing bars and a carved keystone.
    gx, gy = o(0.62)
    zc, r = 5.0, 2.3
    semi = [(gx + ux * r * math.cos(math.pi * j / 20), gy + uy * r * math.cos(math.pi * j / 20), zc + r * math.sin(math.pi * j / 20)) for j in range(21)]
    B.face(semi, "glass")
    for j in range(21 - 1):
        t0, t1 = math.pi * j / 20, math.pi * (j + 1) / 20
        pts = [(gx + ux * rr * math.cos(t) + nx * 0.02, gy + uy * rr * math.cos(t) + ny * 0.02, zc + rr * math.sin(t)) for rr, t in ((r, t0), (r, t1), (r + 0.45, t1), (r + 0.45, t0))]
        B.face(pts, "stone")
    for j in range(1, 6):
        t = math.pi * j / 6
        B.tube((gx + nx * 0.04, gy + ny * 0.04, zc), (gx + ux * r * math.cos(t) + nx * 0.04, gy + uy * r * math.cos(t) + ny * 0.04, zc + r * math.sin(t)), 0.03, "iron", 6)
    B.tube((gx - ux * r + nx * 0.04, gy - uy * r + ny * 0.04, zc), (gx + ux * r + nx * 0.04, gy + uy * r + ny * 0.04, zc), 0.035, "iron", 6)
    kx, ky = o(0.75)
    B.box((kx, ky, zc + r + 0.25), (0.7, 0.35, 0.9), yaw, "stone")
    return {"top": top + 0.5}


def gorilla_kingdom(L, B):
    """Gorilla Kingdom (2007): a timber gorilla house under a deep thatched roof on posts, with big
    viewing windows onto the island; the island ringed by a moat, with boulders and climbing poles."""
    A = ccw(ring(L["footprints"][0]))
    ac = centroid(A)
    for fi, fp in enumerate(L["footprints"][1:], start=1):
        P = ccw(ring(fp))
        if abs(area2(P)) < 40:
            continue
        B.prism(P, 0, 5.2, "timber_weathered", top=False)
        B.prism(offset(P, 0.05), 0, 0.6, "stone", top=False)
        for sk in [r for r in L["roofs"] if r.get("fi") == fi]:
            B.roof(sk, lambda pts: [(pts, "thatch")])
            ring_o = offset(P, 0.8)
            for k in range(0, len(ring_o)):
                x, y = ring_o[k]
                B.tube((x, y, 0), (x, y, 5.15), 0.13, "timber_dark", 8)
        for a, b, ln, ux, uy, nx, ny in edges_of(P):
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            if ln > 5 and (ac[0] - mx) * nx + (ac[1] - my) * ny > 0:  # faces the island: big glass
                wall_panel(B, a, ux, uy, nx, ny, 0.8, ln - 0.8, 0.7, 4.2, 0.04, "glass")
                for t in [0.8 + i * (ln - 1.6) / max(1, int((ln - 1.6) / 2.2)) for i in range(int((ln - 1.6) / 2.2) + 1)]:
                    B.box((a[0] + ux * t + nx * 0.07, a[1] + uy * t + ny * 0.07, 2.45), (0.14, 0.12, 3.5), math.atan2(uy, ux), "timber_dark")
    # Moat and island.
    outer, inner = offset(A, -1.2), offset(A, -4.5)
    n = len(outer)
    for i in range(n):
        p, q, pi, qi = outer[i], outer[(i + 1) % n], inner[i], inner[(i + 1) % n]
        B.face([(p[0], p[1], 0.07), (q[0], q[1], 0.07), (qi[0], qi[1], 0.07), (pi[0], pi[1], 0.07)], "water")
    rnd = __import__("random").Random(3)
    isl = offset(A, -8)
    for k in range(7):
        for _ in range(30):
            x, y = rnd.uniform(min(p[0] for p in isl), max(p[0] for p in isl)), rnd.uniform(min(p[1] for p in isl), max(p[1] for p in isl))
            if inside(isl, x, y):
                break
        r = rnd.uniform(1.0, 2.2)
        B.dome((x, y, 0), r * 1.3, r * rnd.uniform(0.8, 1.4), "rock", 10, 5)
    for k in range(3):
        cx, cy = ac[0] + math.cos(k * 2.1) * 5, ac[1] + math.sin(k * 2.1) * 5
        B.tube((cx, cy, 0), (cx, cy, 7.5 - k), 0.16, "timber_dark", 8)
        nxt = (ac[0] + math.cos((k + 1) * 2.1) * 5, ac[1] + math.sin((k + 1) * 2.1) * 5)
        B.tube((cx, cy, 5.5 - k * 0.6), (nxt[0], nxt[1], 5.5 - (k + 1) % 3 * 0.6), 0.09, "timber_dark", 6)
        for j in range(6):
            t = j / 5
            B.tube((cx, cy, 5.5 - k * 0.6 - 0.1), (cx + (nxt[0] - cx) * t, cy + (nxt[1] - cy) * t, 2.0), 0.025, "rope", 4)
    return {"top": 8.5}


def rainforest_life(L, B):
    """Rainforest Life (2012): a low rendered base under a tall glazed barrel vault on steel arches."""
    P = ccw(ring(L["footprints"][1] if len(L["footprints"]) > 1 else L["footprints"][0]))
    B.prism(P, 0, 4.2, "render_d6d0c2", top=False)
    B.prism(offset(P, 0.05), 0, 0.6, "stone", top=False)
    B.prism(offset(P, 0.1), 3.9, 4.2, "stone", top=False)
    (cx, cy), u, v, a, b = axes(P)
    a, b = a - 0.6, b - 0.6
    rise = min(8.5, b * 0.85)
    nu, nv = max(4, int(a * 2 / 2.2)), 16
    pt = lambda i, j: (cx + u[0] * (-a + 2 * a * i / nu) + v[0] * (-b * math.cos(math.pi * j / nv)),
                       cy + u[1] * (-a + 2 * a * i / nu) + v[1] * (-b * math.cos(math.pi * j / nv)),
                       4.2 + rise * math.sin(math.pi * j / nv))
    for i in range(nu):
        for j in range(nv):
            B.face([pt(i, j), pt(i + 1, j), pt(i + 1, j + 1), pt(i, j + 1)], "glass_roof")
    for i in range(0, nu + 1, 2):
        B.polyline_tube([pt(i, j) for j in range(nv + 1)], 0.09, "paint_e8e8e2", 6)
    for j in range(2, nv, 4):
        B.tube(pt(0, j), pt(nu, j), 0.06, "paint_e8e8e2", 6)
    for i in (0, nu):
        c = pt(i, 0)
        mid = (c[0] + v[0] * b, c[1] + v[1] * b, 4.2)
        for j in range(nv):
            B.face([mid, pt(i, j), pt(i, j + 1)], "glass_roof")
    floor = [(x, y, 4.15) for x, y in offset(P, -0.3)]
    B.face(floor, "roof_flat")
    return {"top": 4.2 + rise + 0.5}


VILLAGE = ["render_e9b44c", "render_5fa9b3", "render_d97c86", "render_ece0c4", "render_7fb069", "render_c9653a"]
SIGNS = ["sign_chai", "sign_stores", "sign_sweets", "sign_tailor"]


def land_of_the_lions(L, B):
    """Land of the Lions (2016), the Gir Forest of India: Sasan Gir station with its platform canopy,
    a broad-gauge track and name boards; a high street of colour-washed shops with corrugated
    awnings and painted signs; bunting across the street; a ruined Hindu temple in the lions' land;
    and a tuk-tuk."""
    rnd = __import__("random").Random(11)
    A = ccw(ring(L["footprints"][0]))
    fps = [ccw(ring(f)) for f in L["footprints"][1:]]
    big = max(range(len(fps)), key=lambda i: abs(area2(fps[i]))) if fps else -1
    tops = []
    sign_k = 0
    for i, P in enumerate(fps):
        ar = abs(area2(P))
        if ar < 8:
            continue
        if i == big:
            # Sasan Gir station.
            B.prism(P, 0, 5.0, "render_f0d9a0", top=True, top_mat="roof_flat")
            B.prism(offset(P, 0.06), 4.4, 5.0, "paint_b03a2e", top=False)
            B.prism(offset(P, 0.05), 0, 0.6, "stone", top=False)
            es = edges_of(P)
            for a, b, ln, ux, uy, nx, ny in es:
                for k in range(int(ln // 3.2)):
                    t = (k + 0.5) * ln / int(ln // 3.2)
                    arched_window(B, a[0] + ux * t, a[1] + uy * t, ux, uy, nx, ny, 1.1, 0.4, 2.7, ("paint_b03a2e", "paint_3a2a20"))
            a, b, ln, ux, uy, nx, ny = max(es, key=lambda e: e[2])
            q = lambda t, out, z: (a[0] + ux * t + nx * out, a[1] + uy * t + ny * out, z)
            B.face([q(0, 0, 0.6), q(ln, 0, 0.6), q(ln, 3.6, 0.6), q(0, 3.6, 0.6)], "stone")  # platform
            B.face([q(0, 3.6, 0), q(ln, 3.6, 0), q(ln, 3.6, 0.6), q(0, 3.6, 0.6)], "stone")
            B.face([q(-0.5, 0, 4.0), q(ln + 0.5, 0, 4.0), q(ln + 0.5, 3.8, 3.4), q(-0.5, 3.8, 3.4)], "corrugated")
            B.face([q(-0.5, 3.8, 3.36), q(ln + 0.5, 3.8, 3.36), q(ln + 0.5, 0, 3.96), q(-0.5, 0, 3.96)], "paint_2e5e4e")
            for t in [0.5 + k * (ln - 1) / max(1, int((ln - 1) / 3)) for k in range(int((ln - 1) / 3) + 1)]:
                p0 = q(t, 3.3, 0.6)
                B.tube(p0, (p0[0], p0[1], 3.5), 0.07, "paint_2e5e4e", 8)
            for t in (2.0, ln - 2.0):  # station name boards
                p0, p1 = q(t - 1.2, 3.2, 2.0), q(t + 1.2, 3.2, 2.0)
                B.face([p0, p1, (p1[0], p1[1], 2.6), (p0[0], p0[1], 2.6)], "sign_station", uvs=SIGN_UV)
                for pp in (p0, p1):
                    B.tube((pp[0], pp[1], 0.6), (pp[0], pp[1], 2.62), 0.04, "paint_2b302d", 6)
            # Broad-gauge track along the platform.
            for k in range(int(ln / 0.65)):
                t = k * 0.65 + 0.3
                c = q(t, 5.2, 0.08)
                B.box(c, (0.25, 2.6, 0.14), math.atan2(uy, ux), "timber_dark")
            for off in (5.2 - 0.84, 5.2 + 0.84):
                c = q(ln / 2, off, 0.2)
                B.box(c, (ln, 0.07, 0.14), math.atan2(uy, ux), "steel")
            B.face([q(0, 3.7, 0.02), q(ln, 3.7, 0.02), q(ln, 6.7, 0.02), q(0, 6.7, 0.02)], "gravel")
            tops.append(5.0)
            # A tuk-tuk waiting at the station.
            tx, ty, _ = q(ln * 0.3, -3.0, 0)
            yaw = math.atan2(uy, ux)
            B.box((tx, ty, 0.75), (2.4, 1.3, 0.9), yaw, "paint_f2c230")
            B.box((tx, ty, 1.9), (2.5, 1.35, 0.08), yaw, "paint_1e1e1e")
            for sx in (-1, 1):
                for sy in (-1, 1):
                    B.tube((tx + math.cos(yaw) * sx * 1.1 - math.sin(yaw) * sy * 0.6, ty + math.sin(yaw) * sx * 1.1 + math.cos(yaw) * sy * 0.6, 1.2),
                           (tx + math.cos(yaw) * sx * 1.1 - math.sin(yaw) * sy * 0.6, ty + math.sin(yaw) * sx * 1.1 + math.cos(yaw) * sy * 0.6, 1.9), 0.03, "paint_1e1e1e", 6)
            for sx, sy in ((1.0, 0), (-0.9, 0.55), (-0.9, -0.55)):
                wx, wy = tx + math.cos(yaw) * sx - math.sin(yaw) * sy, ty + math.sin(yaw) * sx + math.cos(yaw) * sy
                B.tube((wx - math.sin(yaw) * 0.08, wy + math.cos(yaw) * 0.08, 0.27), (wx + math.sin(yaw) * 0.08, wy - math.cos(yaw) * 0.08, 0.27), 0.27, "paint_1e1e1e", 12)
            continue
        # A village shop.
        h = rnd.choice([3.6, 4.2, 5.4])
        col = VILLAGE[i % len(VILLAGE)]
        B.prism(P, 0, h, col, top=True, top_mat="roof_flat")
        B.prism(offset(P, 0.04), 0, 0.5, "paint_6b5a48", top=False)
        B.ring_wall(P, h, h + 0.6, 0.2, col)
        es = edges_of(P)
        a, b, ln, ux, uy, nx, ny = max(es, key=lambda e: e[2])
        q = lambda t, out, z: (a[0] + ux * t + nx * out, a[1] + uy * t + ny * out, z)
        B.face([q(0.2, 0, 2.7), q(ln - 0.2, 0, 2.7), q(ln - 0.2, 1.7, 2.25), q(0.2, 1.7, 2.25)], "corrugated_rust")
        B.face([q(0.2, 1.7, 2.22), q(ln - 0.2, 1.7, 2.22), q(ln - 0.2, 0, 2.67), q(0.2, 0, 2.67)], "corrugated_rust")
        for t in (0.4, ln - 0.4):
            p0 = q(t, 1.6, 0)
            B.tube(p0, (p0[0], p0[1], 2.3), 0.04, "timber_dark", 6)
        if ln > 2.5:
            sw = min(3.0, ln - 0.6)
            p0, p1 = q(ln / 2 - sw / 2, 0.06, 2.85), q(ln / 2 + sw / 2, 0.06, 2.85)
            B.face([p0, p1, (p1[0], p1[1], 3.55), (p0[0], p0[1], 3.55)], SIGNS[sign_k % len(SIGNS)], uvs=SIGN_UV)
            sign_k += 1
            wall_panel(B, a, ux, uy, nx, ny, ln / 2 - 0.9, ln / 2 + 0.9, 0.2, 2.4, 0.03, "paint_3a2a20")
        for e in es:
            ea, eb, eln, eux, euy, enx, eny = e
            if eln > 2.2 and e[0] != a:
                wall_panel(B, ea, eux, euy, enx, eny, eln / 2 - 0.45, eln / 2 + 0.45, 1.2, 2.3, 0.03, "paint_3a2a20")
                for s in (-1, 1):  # painted shutters
                    wall_panel(B, ea, eux, euy, enx, eny, eln / 2 + s * 0.45 + (0 if s > 0 else -0.45), eln / 2 + s * 0.45 + (0.45 if s > 0 else 0), 1.2, 2.3, 0.05, "paint_2f7fb0")
        tops.append(h + 0.6)
    # Bunting across the street between the buildings.
    cents = [centroid(P) for P in fps if abs(area2(P)) >= 8]
    flags = ["fabric_e8452c", "fabric_f4c430", "fabric_2e9e5b", "fabric_3b6fd8", "fabric_e85ca0"]
    for i in range(len(cents)):
        for j in range(i + 1, len(cents)):
            (x0, y0), (x1, y1) = cents[i], cents[j]
            d = math.hypot(x1 - x0, y1 - y0)
            if not 8 < d < 40:
                continue
            n = int(d / 0.55)
            for k in range(1, n):
                t = k / n
                x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
                z = 4.6 - math.sin(math.pi * t) * 0.9
                ux, uy = (x1 - x0) / d, (y1 - y0) / d
                B.face([(x - ux * 0.16, y - uy * 0.16, z), (x + ux * 0.16, y + uy * 0.16, z), (x, y, z - 0.32)], flags[k % len(flags)])
    # The ruined Hindu temple in the lions' land.
    inner = offset(A, -9)
    tx, ty = centroid(A)
    for _ in range(60):
        x, y = rnd.uniform(min(p[0] for p in inner), max(p[0] for p in inner)), rnd.uniform(min(p[1] for p in inner), max(p[1] for p in inner))
        if inside(inner, x, y) and all(math.hypot(x - c[0], y - c[1]) > 12 for c in cents):
            tx, ty = x, y
            break
    B.box((tx, ty, 0.4), (5.0, 5.0, 0.8), 0.3, "sandstone")
    B.box((tx, ty, 2.1), (2.8, 2.8, 2.6), 0.3, "sandstone")
    z, w = 3.4, 2.6
    while w > 0.5:  # the curving shikhara tower, course by course
        B.box((tx, ty, z + 0.2), (w, w, 0.4), 0.3, "sandstone")
        z += 0.4
        w *= 0.88
    B.dome((tx, ty, z), 0.55, 0.3, "sandstone", 12, 3)
    B.tube((tx, ty, z + 0.3), (tx, ty, z + 0.9), 0.06, "gold", 6)
    for k in range(6):  # fallen stones
        ang = rnd.uniform(0, 6.28)
        B.box((tx + math.cos(ang) * rnd.uniform(3.5, 6), ty + math.sin(ang) * rnd.uniform(3.5, 6), 0.25), (rnd.uniform(0.6, 1.2), rnd.uniform(0.4, 0.8), 0.5), ang, "sandstone")
    return {"top": max(tops + [z + 1])}


def tiger_territory(L, B):
    """Tiger Territory (2013), Indonesian-inspired: a stainless-steel mesh enclosure up to 17 m high
    on four masts, held by perimeter posts and cables; rustic timber viewing pavilions under steep
    corrugated roofs."""
    A = ccw(ring(L["footprints"][0]))
    (cx, cy), u, v, a, b = axes(A)
    ring_in = offset(A, -0.4)
    for x, y in resample(ring_in, 6.0):
        B.tube((x, y, 0), (x, y, 4.6), 0.08, "alu", 8)
    peaks = []
    for s, t, h in ((-0.45, -0.35, 17.0), (-0.4, 0.38, 15.0), (0.42, -0.3, 16.0), (0.45, 0.35, 14.0)):
        x, y = cx + u[0] * a * s + v[0] * b * t, cy + u[1] * a * s + v[1] * b * t
        while not inside(A, x, y):
            x, y = x * 0.8 + cx * 0.2, y * 0.8 + cy * 0.2
        B.tube((x, y, 0), (x, y, h), 0.22, "alu", 12)
        peaks.append((x, y, h))
    tension_net(B, ring_in, peaks, 4.6, reach=22.0)
    for fi, fp in enumerate(L["footprints"][1:], start=1):
        P = ccw(ring(fp))
        B.prism(P, 0, 3.4, "timber_weathered", top=False)
        B.prism(offset(P, 0.05), 0, 0.4, "stone", top=False)
        for sk in [r for r in L["roofs"] if r.get("fi") == fi]:
            B.roof(sk, lambda pts: [(pts, "corrugated")])
        for x, y in offset(P, 0.6):
            B.tube((x, y, 0), (x, y, 3.35), 0.12, "timber_dark", 8)
        for ea, eb, ln, ux, uy, nx, ny in edges_of(P):
            if ln > 3:
                wall_panel(B, ea, ux, uy, nx, ny, 0.6, ln - 0.6, 1.0, 2.6, 0.03, "glass")
    return {"top": 17.5}


BUILDERS = {
    "penguin-pool": penguin_pool, "snowdon-aviary": snowdon_aviary, "casson-pavilion": casson_pavilion,
    "clock-tower": clock_tower, "giraffe-house": giraffe_house, "raven-cage": raven_cage,
    "blackburn-pavilion": blackburn_pavilion, "main-entrance": main_entrance, "reptile-house": reptile_house,
    "gorilla-kingdom": gorilla_kingdom, "rainforest-life": rainforest_life, "land-of-the-lions": land_of_the_lions,
    "tiger-territory": tiger_territory,
}
BEVEL = {"penguin-pool": 0.03, "casson-pavilion": 0.03, "giraffe-house": 0.02, "clock-tower": 0.015, "blackburn-pavilion": 0.02,
         "reptile-house": 0.02}


def main():
    only = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    bpy.ops.wm.read_factory_settings(use_empty=True)
    os.makedirs(OUT, exist_ok=True)
    data = json.load(open(INPUT, encoding="utf-8"))
    index_path = os.path.join(OUT, "landmarks.json")
    index = {e["id"]: e for e in (json.load(open(index_path)) if os.path.exists(index_path) else [])}
    for L in data:
        if only and L["id"] not in only:
            continue
        B = Builder()
        info = BUILDERS[L["id"]](L, B)
        obj = B.build(L["id"], BEVEL.get(L["id"], 0))
        for o in bpy.context.scene.objects:
            o.select_set(o == obj)
        bpy.context.view_layer.objects.active = obj
        path = os.path.join(OUT, L["id"] + ".glb")
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_apply=True, export_yup=True)
        tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
        log(f"{L['id']}: {len(obj.data.vertices)} verts, ~{tris} tris, materials {B.names} -> {os.path.getsize(path) // 1024} KB")
        index[L["id"]] = {
            "id": L["id"], "name": L["name"], "url": f"assets/landmarks/{L['id']}.glb", "origin": L["origin"],
            "replaces": L.get("replaces", []), "top": round(info["top"], 2),
        }
        bpy.data.objects.remove(obj)
    json.dump(list(index.values()), open(index_path, "w"), indent=1)
    log("done")


if __name__ == "__main__":  # importable by tools/blender_world/scene.py
    try:
        main()
    except Exception:
        import traceback
        log(traceback.format_exc())
        log("failed")
