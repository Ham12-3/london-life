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

log_file = open(LOG, "w", encoding="utf-8")


def log(*a):
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
    # The mesh: a constrained Delaunay surface over the outline, pulled up to the peaks and relaxed.
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
    vco, _edges, faces = res[0], res[1], res[2]
    orig = res[3]
    fixed, z = {}, []
    for i, co in enumerate(vco):
        src = orig[i][0] if orig[i] else None
        if src is not None and src < nb:
            fixed[i] = 0.6
        elif src is not None and src in apex_idx:
            fixed[i] = peaks[apex_idx.index(src)][2] - 0.2
        tent = max(0.6, max(h - (h - 0.6) * math.hypot(co.x - x, co.y - y) / 17.0 for x, y, h in peaks))
        z.append(fixed.get(i, tent))
    nbrs = [set() for _ in vco]
    for f in faces:
        for i in range(len(f)):
            nbrs[f[i]].add(f[i - 1])
            nbrs[f[i - 1]].add(f[i])
    for _ in range(60):  # relax towards a tension surface
        z = [z[i] if i in fixed else 0.5 * z[i] + 0.5 * sum(z[j] for j in nbrs[i]) / max(1, len(nbrs[i])) for i in range(len(vco))]
    B.shared([(co.x, co.y, z[i]) for i, co in enumerate(vco)], [list(f) for f in faces], "net", lambda p: (p[0] / 2, p[1] / 2))
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


BUILDERS = {
    "penguin-pool": penguin_pool, "snowdon-aviary": snowdon_aviary, "casson-pavilion": casson_pavilion,
    "clock-tower": clock_tower, "giraffe-house": giraffe_house, "raven-cage": raven_cage,
    "blackburn-pavilion": blackburn_pavilion,
}
BEVEL = {"penguin-pool": 0.03, "casson-pavilion": 0.03, "giraffe-house": 0.02, "clock-tower": 0.015, "blackburn-pavilion": 0.02}


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
            "replaces": [] if L["id"] == "snowdon-aviary" else [L["name"]], "top": round(info["top"], 2),
        }
        bpy.data.objects.remove(obj)
    json.dump(list(index.values()), open(index_path, "w"), indent=1)
    log("done")


try:
    main()
except Exception:
    import traceback
    log(traceback.format_exc())
    log("failed")
