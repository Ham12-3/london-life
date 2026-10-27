"""Model every ordinary zoo and park building in Blender, properly: walls with real thickness and
openings cut through them, windows set back in their reveals (glass, frame, glazing bars, stone sill
and lintel), open doorways with stone surrounds, panelled front doors on the houses, a stone plinth,
a cornice or a parapet with coping, and hipped slate/tile roofs with eaves, soffits and fascias.

    node tools/blender_world/prepare.mjs                          (footprints, doors, roof skeletons)
    python tools/blender_mcp.py run tools/blender_world/buildings.py

Replaces the "Buildings" object in the "London Zoo" collection made by scene.py.
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
Builder, offset = lb.Builder, lb.offset

sspec = importlib.util.spec_from_file_location("zoo_scene_mats", os.path.join(os.path.dirname(__file__), "materials.py"))
mats = importlib.util.module_from_spec(sspec)
sspec.loader.exec_module(mats)

data = json.load(open(os.path.join(ROOT, "work", "blender", "buildings.json"), encoding="utf-8"))

T = 0.3  # wall thickness
WINDOWS = {
    "sash": dict(w=1.0, h=1.6, spacing=2.5, sill=0.9, frame="frame_white", bars=[0.5], mullions=[]),
    "wide": dict(w=1.9, h=1.3, spacing=4.2, sill=1.0, frame="frame_dark", bars=[], mullions=[0.5]),
}
DOOR_COLOURS = ["door_black", "door_navy", "door_green", "door_oxblood", "door_slate"]


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def facing(B, pts, mat, d, uvs=None):
    """Add a face, wound so its normal points along d."""
    n = cross(sub(pts[1], pts[0]), sub(pts[2], pts[0]))
    if n[0] * d[0] + n[1] * d[1] + n[2] * d[2] < 0:
        pts = pts[::-1]
        uvs = uvs[::-1] if uvs else None
    B.face(pts, mat, uvs=uvs)


def box(B, centre, size, ux, uy, mat):
    """Box with its x along the wall (ux, uy), y outward, z up."""
    sx, sy, sz = size[0] / 2, size[1] / 2, size[2] / 2
    nx, ny = uy, -ux
    P = lambda a, b, c: (centre[0] + ux * a + nx * b, centre[1] + uy * a + ny * b, centre[2] + c)
    for d, quad in (((0, 0, 1), [P(-sx, -sy, sz), P(sx, -sy, sz), P(sx, sy, sz), P(-sx, sy, sz)]),
                    ((0, 0, -1), [P(-sx, -sy, -sz), P(sx, -sy, -sz), P(sx, sy, -sz), P(-sx, sy, -sz)]),
                    ((nx, ny, 0), [P(-sx, sy, -sz), P(sx, sy, -sz), P(sx, sy, sz), P(-sx, sy, sz)]),
                    ((-nx, -ny, 0), [P(-sx, -sy, -sz), P(sx, -sy, -sz), P(sx, -sy, sz), P(-sx, -sy, sz)]),
                    ((ux, uy, 0), [P(sx, -sy, -sz), P(sx, sy, -sz), P(sx, sy, sz), P(sx, -sy, sz)]),
                    ((-ux, -uy, 0), [P(-sx, -sy, -sz), P(-sx, sy, -sz), P(-sx, sy, sz), P(-sx, -sy, sz)])):
        facing(B, quad, mat, d)


def building(B, b):
    R = [tuple(p) for p in b["ring"][:-1]]
    n = len(R)
    h = b["h"]
    floors = max(1, round(h / 3.5))
    fh = h / floors
    wall = mats.wall(b["finish"], b["paint"])
    O, I = offset(R, T / 2), offset(R, -T / 2)
    K = WINDOWS.get(b["windows"])
    lengths = [math.dist(R[i], R[(i + 1) % n]) for i in range(n)]
    front = max(range(n), key=lambda i: lengths[i]) if b["house"] else -1
    # Doors go on the edge nearest each door point.
    door_on = {}
    for d in b["doors"]:
        best, bd = None, 0.8
        for i in range(n):
            a, c = R[i], R[(i + 1) % n]
            L = lengths[i] or 1
            t = max(0, min(1, ((d[0] - a[0]) * (c[0] - a[0]) + (d[1] - a[1]) * (c[1] - a[1])) / (L * L)))
            dist = math.hypot(a[0] + (c[0] - a[0]) * t - d[0], a[1] + (c[1] - a[1]) * t - d[1])
            if dist < bd:
                best, bd = (i, t * L), dist
        if best:
            door_on.setdefault(best[0], []).append(best[1])

    for i in range(n):
        a, c, L = R[i], R[(i + 1) % n], lengths[i]
        if L < 0.05:
            continue
        ux, uy = (c[0] - a[0]) / L, (c[1] - a[1]) / L
        nx, ny = uy, -ux
        Oa, Oc, Ia, Ic = O[i], O[(i + 1) % n], I[i], I[(i + 1) % n]
        out = lambda u, v, f=0.0: (Oa[0] + (Oc[0] - Oa[0]) * u / L + (Ia[0] - Oa[0]) * f + (Ic[0] - Oc[0] - Ia[0] + Oa[0]) * f * u / L,
                                   Oa[1] + (Oc[1] - Oa[1]) * u / L + (Ia[1] - Oa[1]) * f + (Ic[1] - Oc[1] - Ia[1] + Oa[1]) * f * u / L, v)
        inn = lambda u, v: out(u, v, 1.0)

        # Openings on this wall: (u0, u1, v0, v1, kind).
        opens = []
        for u in door_on.get(i, []):
            u = min(max(u, 1.5), L - 1.5) if L > 3.2 else L / 2
            opens.append((max(0.25, u - 1.2), min(L - 0.25, u + 1.2), 0.0, min(2.7, h - 0.4), "door"))
        if K and L > 1.6:
            cnt = int((L - 0.9) // K["spacing"])
            if cnt >= 1:
                start = (L - (cnt - 1) * K["spacing"]) / 2
                for f in range(floors):
                    v0 = f * fh + K["sill"]
                    v1 = v0 + K["h"]
                    if v1 > (f + 1) * fh - 0.3:
                        continue
                    for k in range(cnt):
                        u = start + k * K["spacing"]
                        u0, u1 = u - K["w"] / 2, u + K["w"] / 2
                        if any(not (u1 + 0.35 < o[0] or u0 - 0.35 > o[1]) and o[4] == "door" for o in opens):
                            continue
                        kind = "window"
                        if i == front and f == 0 and k == cnt // 2:
                            u0, u1, v0, v1, kind = u - 0.55, u + 0.55, 0.15, 2.45, "front"
                        opens.append((u0, u1, v0, v1, kind))
        # The wall face as a grid around the openings.
        us = sorted({0.0, L, *[o[0] for o in opens], *[o[1] for o in opens]})
        vs = sorted({0.0, h, *[o[2] for o in opens], *[o[3] for o in opens]})
        for k in range(len(us) - 1):
            for j in range(len(vs) - 1):
                u0, u1, v0, v1 = us[k], us[k + 1], vs[j], vs[j + 1]
                uc, vc = (u0 + u1) / 2, (v0 + v1) / 2
                if u1 - u0 < 1e-4 or v1 - v0 < 1e-4 or any(o[0] <= uc <= o[1] and o[2] <= vc <= o[3] for o in opens):
                    continue
                facing(B, [out(u0, v0), out(u1, v0), out(u1, v1), out(u0, v1)], wall, (nx, ny, 0))
                facing(B, [inn(u0, v0), inn(u1, v0), inn(u1, v1), inn(u0, v1)], "plaster", (-nx, -ny, 0))
        facing(B, [out(0, h), out(L, h), inn(L, h), inn(0, h)], wall, (0, 0, 1))
        # Each opening: reveals through the wall, then what fills it.
        for u0, u1, v0, v1, kind in opens:
            facing(B, [out(u0, v0), out(u0, v1), inn(u0, v1), inn(u0, v0)], wall, (ux, uy, 0))
            facing(B, [out(u1, v0), out(u1, v1), inn(u1, v1), inn(u1, v0)], wall, (-ux, -uy, 0))
            facing(B, [out(u0, v1), out(u1, v1), inn(u1, v1), inn(u0, v1)], wall, (0, 0, -1))
            if v0 > 0.01:
                facing(B, [out(u0, v0), out(u1, v0), inn(u1, v0), inn(u0, v0)], wall, (0, 0, 1))
            uc, w, hh = (u0 + u1) / 2, u1 - u0, v1 - v0
            mid = out(uc, (v0 + v1) / 2, 0.33)
            if kind == "window":
                g = 0.35
                facing(B, [out(u0, v0, g), out(u1, v0, g), out(u1, v1, g), out(u0, v1, g)], "glass", (nx, ny, 0))
                fr = K["frame"]
                for cx, cz, sx, sz in ((uc, v1 - 0.035, w, 0.07), (uc, v0 + 0.035, w, 0.07), (u0 + 0.035, (v0 + v1) / 2, 0.07, hh), (u1 - 0.035, (v0 + v1) / 2, 0.07, hh)):
                    p = out(cx, cz, 0.3)
                    box(B, p, (sx, 0.08, sz), ux, uy, fr)
                for fb in K["bars"]:
                    box(B, out(uc, v0 + hh * fb, 0.3), (w, 0.05, 0.045), ux, uy, fr)
                for fm in K["mullions"]:
                    box(B, out(u0 + w * fm, (v0 + v1) / 2, 0.3), (0.05, 0.05, hh), ux, uy, fr)
                sill = out(uc, v0 - 0.035, 0.0)
                box(B, (sill[0] + nx * 0.06, sill[1] + ny * 0.06, sill[2]), (w + 0.24, 0.24, 0.07), ux, uy, "stone")
                if b["house"]:
                    lin = out(uc, v1 + 0.1, 0.0)
                    box(B, (lin[0] + nx * 0.02, lin[1] + ny * 0.02, lin[2]), (w + 0.3, 0.05, 0.2), ux, uy, "stone")
            elif kind == "front":
                d = out(uc, v0 + 1.05, 0.4)
                box(B, d, (w, 0.06, 2.1), ux, uy, DOOR_COLOURS[int(b["r"] * 997) % len(DOOR_COLOURS)])
                for px, pz in ((-0.24, 0.55), (0.24, 0.55), (-0.24, -0.45), (0.24, -0.45)):
                    box(B, (d[0] + ux * px + nx * 0.04, d[1] + uy * px + ny * 0.04, d[2] + pz), (0.38, 0.03, 0.7), ux, uy, DOOR_COLOURS[int(b["r"] * 997) % len(DOOR_COLOURS)])
                facing(B, [out(u0, v1 - 0.01, 0.35), out(u1, v1 - 0.01, 0.35), out(u1, v1 + 0.0, 0.35), out(u0, v1 + 0.0, 0.35)], "glass", (nx, ny, 0))
                step = out(uc, 0.08, 0.0)
                box(B, (step[0] + nx * 0.25, step[1] + ny * 0.25, 0.08), (w + 0.5, 0.5, 0.16), ux, uy, "stone")
                for s in (-1, 1):
                    p = out(uc + s * (w / 2 + 0.09), v1 / 2 + 0.1, 0.0)
                    box(B, (p[0] + nx * 0.05, p[1] + ny * 0.05, p[2]), (0.18, 0.12, v1 + 0.2), ux, uy, "stone")
            else:  # open doorway into the building
                for s in (-1, 1):
                    p = out(uc + s * (w / 2 + 0.08), (v1 + 0.15) / 2, 0.0)
                    box(B, (p[0] + nx * 0.05, p[1] + ny * 0.05, p[2]), (0.16, 0.14, v1 + 0.15), ux, uy, "stone")
                p = out(uc, v1 + 0.08, 0.0)
                box(B, (p[0] + nx * 0.05, p[1] + ny * 0.05, p[2]), (w + 0.32, 0.16, 0.16), ux, uy, "stone")

        # Plinth along the solid stretches at the foot of the wall.
        doors_u = sorted((o[0], o[1]) for o in opens if o[4] in ("door", "front"))
        cuts, t0 = [], 0.0
        for d0, d1 in doors_u:
            if d0 > t0:
                cuts.append((t0, d0))
            t0 = max(t0, d1)
        if t0 < L:
            cuts.append((t0, L))
        for c0, c1 in cuts:
            if c1 - c0 < 0.05:
                continue
            p0, p1 = out(c0, 0), out(c1, 0)
            q0 = (p0[0] + nx * 0.05, p0[1] + ny * 0.05)
            q1 = (p1[0] + nx * 0.05, p1[1] + ny * 0.05)
            facing(B, [(q0[0], q0[1], 0), (q1[0], q1[1], 0), (q1[0], q1[1], 0.45), (q0[0], q0[1], 0.45)], "plinth", (nx, ny, 0))
            facing(B, [(q0[0], q0[1], 0.45), (q1[0], q1[1], 0.45), (p1[0], p1[1], 0.45), (p0[0], p0[1], 0.45)], "plinth", (0, 0, 1))

    def band(ring_out, ring_in, z0, z1, mat, bottom=True):
        m = len(ring_out)
        for i in range(m):
            p, q = ring_out[i], ring_out[(i + 1) % m]
            pi, qi = ring_in[i], ring_in[(i + 1) % m]
            nx, ny = q[1] - p[1], -(q[0] - p[0])
            facing(B, [(p[0], p[1], z0), (q[0], q[1], z0), (q[0], q[1], z1), (p[0], p[1], z1)], mat, (nx, ny, 0))
            facing(B, [(p[0], p[1], z1), (q[0], q[1], z1), (qi[0], qi[1], z1), (pi[0], pi[1], z1)], mat, (0, 0, 1))
            if bottom:
                facing(B, [(p[0], p[1], z0), (q[0], q[1], z0), (qi[0], qi[1], z0), (pi[0], pi[1], z0)], mat, (0, 0, -1))

    roof = b["roof"]
    if roof:
        band(offset(R, T / 2 + 0.1), O, h - 0.28, h, "stone")
        V = [(x, y, h + t * roof["slope"]) for x, y, t in roof["vertices"]]
        sl = math.sqrt(1 + roof["slope"] ** 2)
        cover = roof["cover"] + "_uv"
        for poly in roof["polygons"]:
            vs = [roof["vertices"][k] for k in poly]
            e = next((k for k in range(len(vs)) if vs[k][2] < 1e-6 and vs[(k + 1) % len(vs)][2] < 1e-6), 0)
            pa, pb = vs[e], vs[(e + 1) % len(vs)]
            ln = math.hypot(pb[0] - pa[0], pb[1] - pa[1]) or 1
            ex, ey = (pb[0] - pa[0]) / ln, (pb[1] - pa[1]) / ln
            pts = [V[k] for k in poly]
            uvs = [((v[0] - pa[0]) * ex + (v[1] - pa[1]) * ey, v[2] * sl) for v in vs]
            facing(B, pts, cover, (0, 0, 1), uvs)
            facing(B, [(x, y, z - 0.14) for x, y, z in pts], "timber_white", (0, 0, -1))
            # Fascia board along the eave.
            facing(B, [(pa[0], pa[1], h - 0.14), (pb[0], pb[1], h - 0.14), (pb[0], pb[1], h + 0.02), (pa[0], pa[1], h + 0.02)], "timber_white", (ey, -ex, 0))
        top = h + max(t for _, _, t in roof["vertices"]) * roof["slope"]
    else:
        P_o, P_i = offset(R, 0.125), offset(R, -0.125)
        band(offset(R, T / 2 + 0.06), O, h - 0.22, h, "stone")
        band(P_o, P_i, h, h + 0.75, wall, bottom=False)
        m = len(P_i)
        for i in range(m):  # inner face of the parapet
            p, q = P_i[i], P_i[(i + 1) % m]
            facing(B, [(p[0], p[1], h), (q[0], q[1], h), (q[0], q[1], h + 0.75), (p[0], p[1], h + 0.75)], wall, (-(q[1] - p[1]), q[0] - p[0], 0))
        band(offset(R, 0.21), offset(R, -0.21), h + 0.75, h + 0.84, "stone")
        facing(B, [(x, y, h + 0.02) for x, y in P_i], "roof_flat", (0, 0, 1))
        top = h + 0.84
    # Inside: floor and a ceiling.
    facing(B, [(x, y, 0.06) for x, y in I], "floor_int", (0, 0, 1))
    facing(B, [(x, y, h - 0.02) for x, y in I], "plaster", (0, 0, -1))
    return top


old = bpy.data.objects.get("Buildings")
if old:
    bpy.data.objects.remove(old, do_unlink=True)
B = Builder()
skipped = 0
for b in data:
    try:
        building(B, b)
    except Exception as e:  # noqa: BLE001 - one odd outline shouldn't stop the rest
        skipped += 1
obj = B.build("Buildings")
col = bpy.data.collections.get("Buildings")
for c in list(obj.users_collection):
    c.objects.unlink(obj)
col.objects.link(obj)
result = {"buildings": len(data) - skipped, "skipped": skipped, "faces": len(obj.data.polygons)}
