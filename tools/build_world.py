"""Convert the OpenStreetMap extract of ZSL London Zoo into world.json for the simulation.

Usage:  python -I tools/build_world.py [data/osm-zoo.json] [public/world.json]

Coordinates are projected to local metres around the zoo centre:
  +x = east, +z = south (three.js convention, so north is -z), y = up.
"""
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "osm-zoo.json"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "public" / "world.json"
SHOTLIST = ROOT / "tools" / "shotlist.json"

LAT0, LON0 = 51.5353, -0.1552
M_PER_LAT = 110540.0
M_PER_LON = 111320.0 * math.cos(math.radians(LAT0))
ZOO_RELATION = 231792

PATH_WIDTH = {
    "footway": 2.5, "path": 2.0, "pedestrian": 5.0, "steps": 2.5, "corridor": 2.0,
    "cycleway": 3.0, "service": 4.5, "unclassified": 6.0, "residential": 6.5,
    "tertiary": 7.5, "secondary": 8.0, "primary": 9.0, "track": 3.0,
}
ROAD_TYPES = {"primary", "secondary", "tertiary", "unclassified", "residential", "service"}

GROUND_KIND = {
    ("landuse", "grass"): "grass", ("leisure", "garden"): "garden", ("leisure", "park"): "park",
    ("landuse", "forest"): "wood", ("natural", "wood"): "wood", ("natural", "scrub"): "scrub",
    ("natural", "sand"): "sand", ("natural", "bare_rock"): "rock", ("leisure", "pitch"): "pitch",
    ("leisure", "playground"): "playground", ("landuse", "animal_enclosure"): "enclosure",
    ("leisure", "nature_reserve"): "garden", ("amenity", "parking"): "paved",
    ("landuse", "residential"): "paved",
}
BARRIER_HEIGHT = {"fence": 1.6, "wall": 1.2, "hedge": 1.6, "retaining_wall": 1.2, "city_wall": 3.0}
PASSABLE_BARRIER_NODES = {"gate", "entrance", "lift_gate", "bollard", "kerb", "cycle_barrier", "stile", "turnstile"}
FURNITURE = {
    ("amenity", "bench"): "bench", ("highway", "street_lamp"): "lamp",
    ("amenity", "waste_basket"): "bin", ("amenity", "toilets"): "toilets",
    ("amenity", "drinking_water"): "water", ("tourism", "information"): "info",
    ("tourism", "artwork"): "artwork", ("amenity", "clock"): "clock",
    ("leisure", "picnic_table"): "picnic", ("amenity", "bicycle_parking"): "bikes",
}


def proj(lat, lon):
    return (round((lon - LON0) * M_PER_LON, 2), round(-(lat - LAT0) * M_PER_LAT, 2))


def pts(geom):
    return [proj(g["lat"], g["lon"]) for g in geom if g]


def closed(p):
    return len(p) > 3 and abs(p[0][0] - p[-1][0]) < 0.01 and abs(p[0][1] - p[-1][1]) < 0.01


def area(p):
    return 0.5 * sum(p[i][0] * p[i + 1][1] - p[i + 1][0] * p[i][1] for i in range(len(p) - 1))


def centroid(p):
    xs = [q[0] for q in p[:-1]] or [p[0][0]]
    zs = [q[1] for q in p[:-1]] or [p[0][1]]
    return (round(sum(xs) / len(xs), 2), round(sum(zs) / len(zs), 2))


def point_in(poly, x, z):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, zi = poly[i]
        xj, zj = poly[j]
        if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / (zj - zi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def stitch(ways):
    """Join multipolygon member ways into closed rings."""
    ways = [list(w) for w in ways if len(w) > 1]
    rings = []
    while ways:
        ring = ways.pop(0)
        changed = True
        while not closed(ring) and changed:
            changed = False
            for i, w in enumerate(ways):
                if w[0] == ring[-1]:
                    ring += w[1:]
                elif w[-1] == ring[-1]:
                    ring += w[-2::-1]
                elif w[-1] == ring[0]:
                    ring = w[:-1] + ring
                elif w[0] == ring[0]:
                    ring = w[:0:-1] + ring
                else:
                    continue
                ways.pop(i)
                changed = True
                break
        if closed(ring):
            rings.append(ring)
    return rings


def element_rings(e):
    if e["type"] == "way" and "geometry" in e:
        p = pts(e["geometry"])
        return [p] if closed(p) else []
    if e["type"] == "relation":
        outers = [pts(m["geometry"]) for m in e.get("members", []) if m.get("type") == "way" and m.get("role", "outer") in ("outer", "") and "geometry" in m]
        return stitch(outers)
    return []


def main():
    data = json.loads(SRC.read_text(encoding="utf-8"))
    els = data["elements"]
    nodes = {e["id"]: e for e in els if e["type"] == "node"}

    zoo_rings = next((element_rings(e) for e in els if e["type"] == "relation" and e["id"] == ZOO_RELATION), [])

    def in_zoo(x, z):
        return any(point_in(r, x, z) for r in zoo_rings)

    # Nodes that are shared with a walkable way mark openings in fences and building walls.
    walk_nodes = set()
    for e in els:
        t = e.get("tags", {})
        if e["type"] == "way" and t.get("highway") in PATH_WIDTH:
            walk_nodes.update(e.get("nodes", []))
    opening_nodes = set(walk_nodes)
    for nid, n in nodes.items():
        t = n.get("tags", {})
        if t.get("barrier") in PASSABLE_BARRIER_NODES or "entrance" in t or "door" in t:
            opening_nodes.add(nid)

    world = {
        "origin": {"lat": LAT0, "lon": LON0},
        "zoo": zoo_rings, "paths": [], "buildings": [], "ground": [], "water": [], "bridges": [],
        "barriers": [], "areas": [], "pois": [], "trees": [], "furniture": [], "start": None,
    }

    def openings_for(e):
        out = []
        for nid, g in zip(e.get("nodes", []), e.get("geometry", [])):
            if nid in opening_nodes and g:
                out.append(proj(g["lat"], g["lon"]))
        return out

    rng = random.Random(1828)

    for e in els:
        t = e.get("tags", {})
        if not t:
            continue
        name = t.get("name")

        if e["type"] == "node":
            x, z = proj(e["lat"], e["lon"])
            if t.get("natural") == "tree":
                world["trees"].append([x, z, round(rng.uniform(7, 14), 1)])
            for (k, v), kind in FURNITURE.items():
                if t.get(k) == v:
                    world["furniture"].append({"kind": kind, "x": x, "z": z, "name": name})
            if name and (t.get("tourism") == "attraction" or t.get("zoo") or "barrier" in t or t.get("tourism") == "artwork" or t.get("amenity") == "clock"):
                world["pois"].append({"name": name, "x": x, "z": z, "kind": t.get("tourism") or t.get("barrier") or t.get("amenity") or "poi"})
            if name == "London Zoo main entrance":
                world["start"] = {"x": x, "z": z}
            continue

        if e["type"] == "way" and "geometry" in e:
            p = pts(e["geometry"])
            hw = t.get("highway")
            if hw in PATH_WIDTH and t.get("area") != "yes":
                width = 8.0 if name == "The Broad Walk" else PATH_WIDTH[hw]
                world["paths"].append({
                    "pts": p, "w": width, "kind": "road" if hw in ROAD_TYPES else hw,
                    "tunnel": t.get("tunnel") in ("yes", "building_passage"), "bridge": t.get("bridge") == "yes", "name": name,
                })
                if t.get("bridge") == "yes":
                    world["bridges"].append({"line": p, "w": width + 1.0})
            if t.get("natural") == "tree_row":
                for i in range(len(p) - 1):
                    (ax, az), (bx, bz) = p[i], p[i + 1]
                    n = max(1, int(math.hypot(bx - ax, bz - az) / 8))
                    for k in range(n):
                        f = k / n
                        world["trees"].append([round(ax + (bx - ax) * f, 2), round(az + (bz - az) * f, 2), round(rng.uniform(9, 15), 1)])
            if t.get("barrier") in BARRIER_HEIGHT:
                try:
                    h = float(str(t.get("height", "")).replace("m", "").strip())
                except ValueError:
                    h = BARRIER_HEIGHT[t["barrier"]]
                world["barriers"].append({"pts": p, "kind": t["barrier"], "h": h, "gaps": openings_for(e)})
            if t.get("waterway") == "canal" and not closed(p):
                world["water"].append({"line": p, "w": 14.0, "name": name})

        rings = element_rings(e)
        if not rings:
            continue
        for ring in rings:
            if area(ring) > 0:
                ring = ring[::-1]  # keep a consistent winding
            cx, cz = centroid(ring)
            if "building" in t and t.get("building") not in ("roof",) and t.get("tunnel") != "yes":
                levels = float(str(t.get("building:levels", "1")).split(";")[0] or 1)
                h = float(str(t.get("height", "0")).replace("m", "").strip() or 0) or max(4.0, levels * 3.6)
                if t.get("building") == "cage":
                    h = max(h, 8.0)
                inside = in_zoo(cx, cz)
                world["buildings"].append({
                    "pts": ring, "h": round(h, 1), "name": name, "kind": t["building"], "inZoo": inside,
                    "doors": openings_for(e) if e["type"] == "way" else [],
                    "attraction": t.get("tourism") == "attraction",
                })
            if t.get("natural") == "water" or t.get("water") or t.get("leisure") == "swimming_pool":
                world["water"].append({"pts": ring, "name": name, "kind": t.get("water", "water")})
            if t.get("man_made") == "bridge":
                world["bridges"].append({"pts": ring})
            for (k, v), kind in GROUND_KIND.items():
                if t.get(k) == v:
                    world["ground"].append({"pts": ring, "kind": kind})
                    if kind == "wood":
                        # Scatter trees through woodland so it reads as woodland at eye level.
                        xs, zs = [q[0] for q in ring], [q[1] for q in ring]
                        a = abs(area(ring))
                        for _ in range(min(120, int(a / 90))):
                            x, z = rng.uniform(min(xs), max(xs)), rng.uniform(min(zs), max(zs))
                            if point_in(ring, x, z):
                                world["trees"].append([round(x, 2), round(z, 2), round(rng.uniform(8, 16), 1)])
                    break
            if name and (t.get("tourism") == "attraction" or t.get("zoo") or t.get("landuse") == "animal_enclosure"):
                world["areas"].append({"name": name, "pts": ring, "c": [cx, cz], "a": round(abs(area(ring)), 1),
                                       "enclosure": bool(t.get("zoo") == "enclosure" or t.get("landuse") == "animal_enclosure")})

    add_crossings(world)
    if not world["start"]:
        world["start"] = {"x": 0.0, "z": 0.0}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(world, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")

    write_shotlist(world)
    print(f"wrote {OUT}: {len(world['paths'])} paths, {len(world['buildings'])} buildings, "
          f"{len(world['areas'])} areas, {len(world['pois'])} pois, {len(world['trees'])} trees, "
          f"{len(world['barriers'])} barriers, {len(world['water'])} water")


def seg_cross(a, b, c, d):
    """Intersection point of segments a-b and c-d, or None."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-9:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if 0 <= t <= 1 and 0 <= u <= 1:
        return (round(a[0] + t * r[0], 2), round(a[1] + t * r[1], 2))
    return None


def add_crossings(world):
    """Open a doorway or fence gap wherever a mapped path crosses a building wall or barrier,
    even when OSM doesn't share a node there."""
    def segs(lines):
        out = []
        for pts in lines:
            for i in range(len(pts) - 1):
                a, b = pts[i], pts[i + 1]
                out.append((a, b, min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1])))
        return out

    walk = segs(p["pts"] for p in world["paths"] if p["kind"] != "road")
    every = segs(p["pts"] for p in world["paths"])

    def crossings(ring, candidates):
        found = []
        for i in range(len(ring) - 1):
            a, b = ring[i], ring[i + 1]
            x0, x1, z0, z1 = min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1])
            for c, d, cx0, cx1, cz0, cz1 in candidates:
                if cx1 < x0 or cx0 > x1 or cz1 < z0 or cz0 > z1:
                    continue
                p = seg_cross(a, b, c, d)
                if p:
                    found.append(p)
        return found

    for b in world["buildings"]:
        if b["inZoo"]:
            b["doors"] += crossings(b["pts"], walk)
    for br in world["barriers"]:
        br["gaps"] += crossings(br["pts"], every)


def write_shotlist(world):
    """One Google Flow prompt per named place inside the zoo, for batch generation."""
    seen, shots = set(), []
    places = [(a["name"], a["c"], "area") for a in world["areas"]]
    places += [(b["name"], centroid(b["pts"]), "building") for b in world["buildings"] if b["name"] and b["inZoo"]]
    places += [(p["name"], (p["x"], p["z"]), p["kind"]) for p in world["pois"]]
    existing = {}
    if SHOTLIST.exists():
        existing = {s["id"]: s for s in json.loads(SHOTLIST.read_text(encoding="utf-8"))["shots"]}
    for name, (x, z), kind in places:
        sid = "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")
        while "--" in sid:
            sid = sid.replace("--", "-")
        if sid in seen:
            continue
        seen.add(sid)
        subject = f"the {name} at ZSL London Zoo, Regent's Park, London"
        prompt = (f"Slow, smooth orbit camera move at eye level around {subject}. "
                  "Bright overcast daylight, completely static scene, no people, nothing moving, "
                  "sharp focus, photorealistic, consistent lighting, steady stabilised camera.")
        shot = {"id": sid, "name": name, "kind": kind, "x": x, "z": z, "prompt": prompt, "status": "todo", "video": None}
        if sid in existing:
            shot.update({k: existing[sid][k] for k in ("prompt", "status", "video") if k in existing[sid]})
        shots.append(shot)
    SHOTLIST.write_text(json.dumps({
        "settings": {"tool": "Google Flow", "model": "Omni 1.1 Flash", "resolution": "360p", "duration": "8s", "count": 1, "credits_per_clip": 6},
        "shots": shots,
    }, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
