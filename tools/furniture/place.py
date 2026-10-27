"""Where the street furniture goes: public/assets/furniture/placements.json, read by both the web app
(src/furniture.js) and the Blender scene (tools/blender_world/furniture.py).

    python tools/furniture/place.py

Everything OpenStreetMap maps is kept. OSM has far fewer lamps, benches and bins than the zoo
really has, so more are set along the footpaths at realistic spacing: lamp posts every ~32 m on
alternating sides, benches every ~48 m facing the path, a bin by every other bench, skipping spots
inside buildings, water or too close to something else. Every mapped fence becomes runs of 2.5 m
railing sections, leaving the gaps where paths cross.

Entries are [x, z, yaw] in world.json metres (railings add a length). yaw turns the model's
local +z (its front) towards (sin yaw, cos yaw), as three.js's rotation.y does.
"""
import json
import math
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
world = json.load(open(os.path.join(ROOT, "public", "world.json"), encoding="utf-8"))

KINDS = ("bench", "bin", "lamp", "water", "picnic", "bikes")
out = {k: [] for k in KINDS}
out["railing"] = []


def inside(pts, x, z):
    res = False
    for i in range(len(pts)):
        (xi, zi), (xj, zj) = pts[i], pts[i - 1]
        if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / (zj - zi + 1e-12) + xi:
            res = not res
    return res


def bbox(pts):
    xs, zs = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(zs), max(xs), max(zs)


blockers = [(b["pts"], bbox(b["pts"])) for b in world["buildings"]]
blockers += [(w["pts"], bbox(w["pts"])) for w in world["water"] if w.get("pts")]
for g in world["ground"]:
    if g["kind"] in ("rock", "sand"):
        blockers.append((g["pts"], bbox(g["pts"])))
zoo = world["zoo"]
grid = {}


def free(x, z, r=1.6):
    for pts, (x0, z0, x1, z1) in blockers:
        if x0 - 1 < x < x1 + 1 and z0 - 1 < z < z1 + 1 and inside(pts, x, z):
            return False
    cx, cz = int(x // 4), int(z // 4)
    for i in (-1, 0, 1):
        for j in (-1, 0, 1):
            for (px, pz) in grid.get((cx + i, cz + j), []):
                if math.hypot(px - x, pz - z) < r:
                    return False
    for tx, tz, _ in world["trees"]:
        if abs(tx - x) < 1.2 and abs(tz - z) < 1.2:
            return False
    return True


def take(kind, x, z, yaw):
    out[kind].append([round(x, 2), round(z, 2), round(yaw, 3)])
    grid.setdefault((int(x // 4), int(z // 4)), []).append((x, z))


# 1. What's mapped.
for f in world["furniture"]:
    if f["kind"] in out:
        take(f["kind"], f["x"], f["z"], (hash((round(f["x"]), round(f["z"]))) % 4) * math.pi / 2)

# 2. Along the footpaths.
for p in world["paths"]:
    if p["kind"] not in ("footway", "path", "pedestrian") or p.get("tunnel") or p.get("bridge"):
        continue
    pts, half = p["pts"], p["w"] / 2
    run, next_lamp, next_bench, side, benches = 0.0, 12.0, 24.0, 1, 0
    for a, b in zip(pts, pts[1:]):
        ln = math.dist(a, b)
        if ln < 1e-3:
            continue
        ux, uz = (b[0] - a[0]) / ln, (b[1] - a[1]) / ln
        nx, nz = -uz, ux  # left of travel
        while next_lamp < run + ln or next_bench < run + ln:
            if next_lamp <= next_bench:
                t = next_lamp - run
                x, z = a[0] + ux * t + nx * side * (half + 0.6), a[1] + uz * t + nz * side * (half + 0.6)
                if free(x, z, 6):
                    take("lamp", x, z, 0)
                side = -side
                next_lamp += 32
            else:
                t = next_bench - run
                s = -side
                x, z = a[0] + ux * t + nx * s * (half + 0.9), a[1] + uz * t + nz * s * (half + 0.9)
                fx, fz = -nx * s, -nz * s  # the bench faces the path
                if free(x, z, 3):
                    take("bench", x, z, math.atan2(fx, fz))
                    benches += 1
                    bx, bz = x + ux * 1.6, z + uz * 1.6
                    if benches % 2 == 0 and free(bx, bz, 1.2):
                        take("bin", bx, bz, math.atan2(fx, fz))
                next_bench += 48
        run += ln

# 3. Railings along every fence, with gaps where paths cross (as world.js does).
for br in world["barriers"]:
    if br["kind"] != "fence":
        continue
    for a, b in zip(br["pts"], br["pts"][1:]):
        ln = math.dist(a, b)
        if ln < 0.2:
            continue
        ux, uz = (b[0] - a[0]) / ln, (b[1] - a[1]) / ln
        cuts = []
        for gx, gz in br.get("gaps", []):
            t = (gx - a[0]) * ux + (gz - a[1]) * uz
            if -1.1 < t < ln + 1.1 and abs((gx - a[0]) * -uz + (gz - a[1]) * ux) < 0.6:
                cuts.append((max(0, t - 1.1), min(ln, t + 1.1)))
        cuts.sort()
        t0, spans = 0.0, []
        for c0, c1 in cuts:
            if c0 > t0:
                spans.append((t0, c0))
            t0 = max(t0, c1)
        if t0 < ln:
            spans.append((t0, ln))
        yaw = math.atan2(-uz, ux)  # local +x along the fence
        for s0, s1 in spans:
            L = s1 - s0
            if L < 0.3:
                continue
            n = max(1, round(L / 2.5))
            for k in range(n):
                c = s0 + (k + 0.5) * L / n
                x, z = a[0] + ux * c, a[1] + uz * c
                if any(x0 < x < x1 and z0 < z < z1 and inside(pts, x, z) for pts, (x0, z0, x1, z1) in blockers[:len(world["buildings"])]):
                    continue  # mapped fences sometimes run through a building's footprint
                out["railing"].append([round(x, 2), round(z, 2), round(yaw, 3), round(L / n, 3)])

dest = os.path.join(ROOT, "public", "assets", "furniture", "placements.json")
json.dump(out, open(dest, "w"))
print({k: len(v) for k, v in out.items()}, "->", os.path.relpath(dest, ROOT))
