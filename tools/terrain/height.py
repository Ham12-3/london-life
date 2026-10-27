"""The zoo's ground levels: public/assets/terrain/height.bin (+ terrain.json), used by Blender
(tools/blender_world/terrain.py builds the ground from it) and by the web app (everything that
stands on the ground samples it).

    python tools/terrain/height.py

The zoo itself is close to level; what changes it is:
- the Regent's Canal, running through the north of the zoo in a cutting: water ~5.5 m down, a
  towpath just above it on the north side, and steep banks up to the zoo;
- the tunnels under the Outer Circle (Decimus Burton's East Tunnel and its western partner): open
  ramps slope down to the tunnel floor, 3.6 m below the road, either side of the covered part.
Ground under and right around buildings stays level.

Heights are metres relative to the zoo's paths, on a 2 m grid in world.json x/z. terrain.json also
lists each tunnel (path, covered stretch, floor level) so walkers can go under the road.
"""
import json
import math
import os
import struct

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "public", "assets", "terrain")
os.makedirs(OUT, exist_ok=True)
world = json.load(open(os.path.join(ROOT, "public", "world.json"), encoding="utf-8"))

STEP = 2.0
X0, X1, Z0, Z1 = -820.0, 820.0, -720.0, 720.0
NX, NZ = int((X1 - X0) / STEP) + 1, int((Z1 - Z0) / STEP) + 1

WATER, TOWPATH, CUT_W = -5.5, -4.5, 14.0   # canal water level, towpath level, bank width
TUNNEL_FLOOR, RAMP = -3.6, 18.0             # tunnel floor, ramp length each side


def seg_dist(px, pz, a, b):
    dx, dz = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dz * dz or 1e-9
    t = max(0.0, min(1.0, ((px - a[0]) * dx + (pz - a[1]) * dz) / l2))
    return math.hypot(a[0] + dx * t - px, a[1] + dz * t - pz), t


def inside(pts, x, z):
    res = False
    for i in range(len(pts)):
        (xi, zi), (xj, zj) = pts[i], pts[i - 1]
        if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / (zj - zi + 1e-12) + xi:
            res = not res
    return res


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


# The canal: its centrelines (the water polygons tagged canal are the same water, and the basin).
canal_lines = [w["line"] for w in world["water"] if w.get("line") and (w.get("name") or "").startswith("Regent")]
canal_lines += [w["line"] for w in world["water"] if w.get("line") and not w.get("name")]
canal_polys = [w["pts"] for w in world["water"] if w.get("pts") and w.get("kind") == "canal"]
canal_segs = [(a, b) for line in canal_lines for a, b in zip(line, line[1:])]


def canal_height(x, z):
    """Ground level from the canal cutting (0 away from it)."""
    d = min((seg_dist(x, z, a, b)[0] for a, b in canal_segs), default=1e9) - 7.0
    for poly in canal_polys:
        if inside(poly, x, z):
            d = min(d, -1.0)
    if d > 4.0 + CUT_W:
        return 0.0
    if d < 0:
        return WATER - 1.0  # canal bed (under the water surface)
    if d < 4.0:
        return TOWPATH
    return TOWPATH + (0 - TOWPATH) * smooth((d - 4.0) / CUT_W)


# Tunnels: where each tunnel path passes under a road.
roads = [p for p in world["paths"] if p["kind"] == "road" and not p.get("tunnel")]
tunnels = []
for p in world["paths"]:
    if not p.get("tunnel"):
        continue
    pts = p["pts"]
    length = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    if length < 20:
        continue  # short underpasses inside the zoo: left level
    best = None
    s_run = 0.0
    for a, b in zip(pts, pts[1:]):
        L = math.dist(a, b)
        for k in range(int(L) + 1):
            t = k / max(1, int(L))
            x, z = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            for r in roads:
                for ra, rb in zip(r["pts"], r["pts"][1:]):
                    d, _ = seg_dist(x, z, ra, rb)
                    if d < r["w"] / 2 and (best is None or d < best[0]):
                        best = (d, s_run + t * L, r["w"])
        s_run += L
    if not best:
        continue
    s_mid, road_w = best[1], best[2]
    covered = (max(0.0, s_mid - road_w / 2 - 2.5), min(length, s_mid + road_w / 2 + 2.5))
    tunnels.append({"pts": pts, "w": p["w"], "length": round(length, 2), "covered": [round(covered[0], 2), round(covered[1], 2)], "floor": TUNNEL_FLOOR})


def along(pts, x, z):
    """(distance from the path, distance along it) for the nearest point on a polyline."""
    best, run = (1e9, 0.0), 0.0
    for a, b in zip(pts, pts[1:]):
        d, t = seg_dist(x, z, a, b)
        L = math.dist(a, b)
        if d < best[0]:
            best = (d, run + t * L)
        run += L
    return best


def tunnel_height(x, z):
    """Open tunnel ramps cut into the ground; the covered stretch keeps the ground (it's underground)."""
    h = 0.0
    for t in tunnels:
        d, s = along(t["pts"], x, z)
        if d > t["w"] / 2 + 1.2:
            continue
        c0, c1 = t["covered"]
        if c0 <= s <= c1:
            continue
        gap = c0 - s if s < c0 else s - c1
        h = min(h, TUNNEL_FLOOR * (1 - smooth(gap / RAMP)))
    return h


# Keep ground level under and around buildings.
flat = []
for b in world["buildings"]:
    xs, zs = [p[0] for p in b["pts"]], [p[1] for p in b["pts"]]
    flat.append((b["pts"], min(xs) - 3, max(xs) + 3, min(zs) - 3, max(zs) + 3))

grid = []
for j in range(NZ):
    z = Z0 + j * STEP
    for i in range(NX):
        x = X0 + i * STEP
        h = canal_height(x, z)
        if h > -0.001:
            h = tunnel_height(x, z)
        if h < 0 and h > WATER - 0.5:
            for pts, x0, x1, z0, z1 in flat:
                if x0 < x < x1 and z0 < z < z1 and min(seg_dist(x, z, pts[k], pts[k + 1])[0] for k in range(len(pts) - 1)) < 3 or (x0 < x < x1 and z0 < z < z1 and inside(pts, x, z)):
                    h = 0.0
                    break
        grid.append(h)

with open(os.path.join(OUT, "height.bin"), "wb") as f:
    f.write(struct.pack(f"<{len(grid)}f", *grid))
meta = {"x0": X0, "z0": Z0, "step": STEP, "nx": NX, "nz": NZ, "water": WATER, "towpath": TOWPATH, "tunnels": tunnels,
        "canal": [[[round(x, 2), round(z, 2)] for x, z in line] for line in canal_lines]}
json.dump(meta, open(os.path.join(OUT, "terrain.json"), "w"))
print(f"{NX}x{NZ} grid, lowest {min(grid):.1f} m, {sum(1 for h in grid if h < -0.05)} cells below level, {len(tunnels)} tunnels")
