"""Fit a Brush splat (in COLMAP's arbitrary frame) onto its real footprint in world.json,
crop it to that footprint, and add it to public/assets/manifest.json.

Usage:  python -I tools/align_splat.py <name> "<OSM place name>" [--eye 1.7]
  e.g.  python -I tools/align_splat.py casson-pavilion "Casson Pavilion"

Reads   work/<name>/sparse/0/{images,points3D}.txt and public/assets/splats/<name>.ply
Writes  public/assets/splats/<name>-fit.ply (cropped, sky haze removed) and a manifest item with a world matrix.

How the fit works:
  up     = average camera "up" (Flow clips are shot level, at eye height)
  centre = median of the sparse points (the subject, for orbits and walk-through dollies alike)
  scale  = cameras sit --eye metres above the reconstructed ground, clamped to 0.6-1.6x the footprint size
  place  = scene centre on the footprint centre, turned so the side the clip filmed faces the
           nearest walkway: visitors on the path see the scene the way the camera did.
Matching AI geometry to the real footprint proved unreliable (the AI invents its own buildings), so
the footprint only decides where the scene goes and what gets cropped.
"""
import json
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_SPLAT_M = 1.5   # largest splat kept, in metres (bigger ones streak from new angles)
MIN_OPACITY = 0.08


# ---------- small linear algebra ----------

def sub(a, b): return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
def add(a, b): return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
def mul(a, s): return [a[0] * s, a[1] * s, a[2] * s]
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
def norm(a):
    n = math.sqrt(dot(a, a)) or 1.0
    return [a[0] / n, a[1] / n, a[2] / n]


def solve3(m, v):
    def det(a):
        return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
                - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
                + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    d = det(m)
    out = []
    for c in range(3):
        mc = [row[:] for row in m]
        for r in range(3):
            mc[r][c] = v[r]
        out.append(det(mc) / d)
    return out


def quat_to_rows(qw, qx, qy, qz):
    """Rows of the world->camera rotation: camera right, down, forward expressed in world coords."""
    return [
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ]


def percentile(vals, p):
    s = sorted(vals)
    return s[min(len(s) - 1, max(0, int(p * len(s))))]


# ---------- IO ----------

def read_cameras(path):
    lines = [l for l in path.read_text().splitlines() if l and not l.startswith("#")]
    cams = []
    for l in lines[0::2]:
        p = l.split()
        qw, qx, qy, qz, tx, ty, tz = map(float, p[1:8])
        R = quat_to_rows(qw, qx, qy, qz)
        t = [tx, ty, tz]
        centre = mul([sum(R[r][c] * t[r] for r in range(3)) for c in range(3)], -1)
        cams.append({"c": centre, "down": R[1], "fwd": R[2]})
    return cams


def read_points(path):
    pts = []
    for l in path.read_text().splitlines():
        if l and not l.startswith("#"):
            p = l.split()
            pts.append([float(p[1]), float(p[2]), float(p[3])])
    return pts


def read_ply(path):
    data = path.read_bytes()
    end = data.find(b"end_header\n") + len(b"end_header\n")
    header = data[:end].decode("latin1").splitlines()
    n = int(next(l for l in header if l.startswith("element vertex")).split()[-1])
    props = [l.split()[-1] for l in header if l.startswith("property")]
    if any(l.split()[1] != "float" for l in header if l.startswith("property")):
        raise SystemExit("expected an all-float PLY from Brush")
    return header, props, data[end:], n


# ---------- fit ----------

class Mask:
    """Footprint rasterised at 0.5 m, so inside tests are a dict lookup."""
    def __init__(self, poly, cell=0.5):
        self.cell = cell
        xs, zs = [p[0] for p in poly], [p[1] for p in poly]
        self.cells = set()
        x = min(xs)
        while x <= max(xs):
            z = min(zs)
            while z <= max(zs):
                if point_in(poly, x, z):
                    self.cells.add((round(x / cell), round(z / cell)))
                z += cell
            x += cell

    def has(self, x, z):
        return (round(x / self.cell), round(z / self.cell)) in self.cells

    def dilated(self, metres):
        out = Mask.__new__(Mask)
        out.cell = self.cell
        r = int(metres / self.cell)
        out.cells = {(i + a, j + b) for (i, j) in self.cells for a in range(-r, r + 1) for b in range(-r, r + 1) if a * a + b * b <= r * r}
        return out


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


def score(local, mask, yaw, s, ox, oz):
    c, sn = math.cos(yaw), math.sin(yaw)
    inside, hit = 0, set()
    for x, z in local:
        wx, wz = (c * x - sn * z) * s + ox, (sn * x + c * z) * s + oz
        k = (round(wx / mask.cell), round(wz / mask.cell))
        if k in mask.cells:
            inside += 1
            hit.add((k[0] // 4, k[1] // 4))  # 2 m blocks
    if not hasattr(mask, "n_blocks"):
        mask.n_blocks = len({(i // 4, j // 4) for i, j in mask.cells})
    return (inside / len(local)) * (len(hit) / mask.n_blocks)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    eye = float(sys.argv[sys.argv.index("--eye") + 1]) if "--eye" in sys.argv else 1.7
    if "--eye" in sys.argv:
        args = [a for a in args if a != sys.argv[sys.argv.index("--eye") + 1]]
    name, place = args[0], args[1]
    model = ROOT / "work" / name / "sparse" / "0"
    cams = read_cameras(model / "images.txt")
    pts = read_points(model / "points3D.txt")

    world = json.loads((ROOT / "public" / "world.json").read_text(encoding="utf-8"))
    building = next((b for b in world["buildings"] if b["name"] == place), None)
    area = next((a for a in world["areas"] if a["name"] == place), None)
    poi = next((p for p in world["pois"] if p["name"] == place), None)
    poly = (building or area or {}).get("pts")
    if not poly and poi:
        # Point features (statues, small animal spots) get a 16 m square footprint.
        h = 8.0
        poly = [[poi["x"] - h, poi["z"] - h], [poi["x"] + h, poi["z"] - h], [poi["x"] + h, poi["z"] + h],
                [poi["x"] - h, poi["z"] + h], [poi["x"] - h, poi["z"] - h]]
    if not poly:
        raise SystemExit(f'"{place}" is not a building, area or point in world.json')
    # OSM heights are often missing (default 1 storey), so use generous fixed bands.
    fit_cap, crop_cap = 30.0, 40.0
    # Enclosures keep their own ground (sand, pools, grass); buildings sit on the simulated paving.
    floor = 0.05 if building else -0.3

    # Frame from the cameras: "up" from their orientation, the scene centre as the median of the
    # sparse points (works for orbits and for walk-through dollies alike).
    up = norm(mul([sum(c["down"][i] for c in cams) for i in range(3)], -1))
    centre = [sorted(p[i] for p in pts)[len(pts) // 2] for i in range(3)]
    cam_mean = [sum(c["c"][i] for c in cams) / len(cams) for i in range(3)]
    to_cam = sub(cam_mean, centre)
    flat = sub(to_cam, mul(up, dot(to_cam, up)))
    if dot(flat, flat) < 1e-12:  # cameras straight above the centre: any horizontal axis will do
        flat = cross(up, [1, 0, 0]) if abs(up[0]) < 0.9 else cross(up, [0, 0, 1])
    zax = norm(flat)  # local +z points from the scene towards where it was filmed from
    xax = cross(up, zax)

    def to_local(p):
        d = sub(p, centre)
        return [dot(d, xax), dot(d, up), dot(d, zax)]

    cam_h = sum(to_local(c["c"])[1] for c in cams) / len(cams)
    lp = [to_local(p) for p in pts]
    radius = percentile([math.hypot(p[0], p[2]) for p in lp], 0.7)
    near = [p for p in lp if math.hypot(p[0], p[2]) < radius]
    ground = percentile([p[1] for p in near], 0.03)

    cx = sum(p[0] for p in poly[:-1]) / (len(poly) - 1)
    cz = sum(p[1] for p in poly[:-1]) / (len(poly) - 1)
    foot_r = max(4.0, percentile([math.hypot(p[0] - cx, p[1] - cz) for p in poly[:-1]], 0.7))
    mask = Mask(poly)

    # Scale: cameras at eye height. Clamp so the scene stays roughly footprint-sized when the
    # reconstructed ground is unreliable (AI video invents its own proportions).
    s = eye / (cam_h - ground) if cam_h - ground > 1e-6 else foot_r / radius
    s = min(max(s, 0.6 * foot_r / radius), 1.6 * foot_r / radius)
    print(f"cameras {len(cams)}, points {len(pts)}; eye height {cam_h - ground:.3f} units -> {s:.3f} m/unit, "
          f"scene radius {radius * s:.1f} m vs footprint {foot_r:.1f} m")

    # Place the scene on the footprint, turned so the filmed side faces the nearest walkway.
    best_d, path_pt = float("inf"), (cx, cz + 1)
    for path in world["paths"]:
        if path["kind"] == "road" or path.get("tunnel"):
            continue
        pp = path["pts"]
        for i in range(len(pp) - 1):
            (ax, az), (bx, bz) = pp[i], pp[i + 1]
            dx, dz = bx - ax, bz - az
            t = max(0.0, min(1.0, ((cx - ax) * dx + (cz - az) * dz) / (dx * dx + dz * dz or 1e-9)))
            qx, qz = ax + t * dx, az + t * dz
            d = math.hypot(qx - cx, qz - cz)
            if 0.5 < d < best_d:
                best_d, path_pt = d, (qx, qz)
    dirx, dirz = path_pt[0] - cx, path_pt[1] - cz
    yaw = math.atan2(-dirx, dirz)  # maps local +z onto the direction of the path
    ox, oz = cx, cz
    best = (round(radius * s / foot_r, 3),)
    print(f"facing path {best_d:.1f} m away: yaw {math.degrees(yaw):.1f} deg, centre ({ox:.1f}, {oz:.1f})")

    # world = T(ox, -ground*s, oz) * Ry(yaw) * S(s) * [xax up zax]^T * (p - centre)
    c, sn = math.cos(yaw), math.sin(yaw)
    rows = []
    for axis_row in ([c, 0, -sn], [0, 1, 0], [sn, 0, c]):
        # combine yaw row with the basis change: world_i = sum_j yawrow_j * basis_j . d
        rows.append([s * (axis_row[0] * xax[k] + axis_row[1] * up[k] + axis_row[2] * zax[k]) for k in range(3)])
    trans = [ox, -ground * s, oz]
    trans = [trans[i] - dot(rows[i], centre) for i in range(3)]

    def to_world(p):
        return [dot(rows[i], p) + trans[i] for i in range(3)]

    # Crop the splat to the footprint (plus a margin) so the AI's ground and trees don't
    # fight with the simulated ones.
    src = ROOT / "public" / "assets" / "splats" / f"{name}.ply"
    header, props, body, n = read_ply(src)
    stride = len(props) * 4
    ix = props.index("x")
    i_scale = [props.index(f"scale_{k}") for k in range(3)]
    i_opac = props.index("opacity")
    keep_mask = mask.dilated(2.5)
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None:
        # Vectorised crop: Colab-trained splats run to 200k per place, too many for a Python loop.
        data = np.frombuffer(body, np.float32, count=n * len(props)).reshape(n, len(props))
        world_pts = data[:, ix:ix + 3].astype(np.float64) @ np.array(rows).T + np.array(trans)
        cells = np.array(sorted(keep_mask.cells))
        lo = cells.min(0)
        grid = np.zeros(tuple(cells.max(0) - lo + 1), bool)
        grid[cells[:, 0] - lo[0], cells[:, 1] - lo[1]] = True
        ci = np.round(world_pts[:, 0] / keep_mask.cell).astype(np.int64) - lo[0]
        cj = np.round(world_pts[:, 2] / keep_mask.cell).astype(np.int64) - lo[1]
        inside = (ci >= 0) & (cj >= 0) & (ci < grid.shape[0]) & (cj < grid.shape[1])
        inside[inside] = grid[ci[inside], cj[inside]]
        size = np.exp(data[:, i_scale].max(1)) * s
        opacity = 1 / (1 + np.exp(-data[:, i_opac]))
        sel = inside & (world_pts[:, 1] > floor) & (world_pts[:, 1] < crop_cap) & (size < MAX_SPLAT_M) & (opacity > MIN_OPACITY)
        kept = data[sel].tobytes()
        count = int(sel.sum())
    else:
        kept = bytearray()
        count = 0
        for i in range(n):
            off = i * stride
            p = struct.unpack_from("<3f", body, off + ix * 4)
            wx, wy, wz = to_world(p)
            if not (floor < wy < crop_cap and keep_mask.has(wx, wz)):
                continue
            # Drop the AI sky: huge or nearly transparent splats read as fog from any new angle.
            size = math.exp(max(struct.unpack_from("<f", body, off + k * 4)[0] for k in i_scale)) * s
            opacity = 1 / (1 + math.exp(-struct.unpack_from("<f", body, off + i_opac * 4)[0]))
            if size < MAX_SPLAT_M and opacity > MIN_OPACITY:
                kept += body[off:off + stride]
                count += 1
    out = src.with_name(f"{name}-fit.ply")
    new_header = "\n".join(f"element vertex {count}" if l.startswith("element vertex") else l for l in header) + "\n"
    out.write_bytes(new_header.encode("latin1") + bytes(kept))
    print(f"kept {count} of {n} splats -> {out.relative_to(ROOT)}")

    # three.js Matrix4.fromArray takes column-major order.
    matrix = [rows[0][0], rows[1][0], rows[2][0], 0,
              rows[0][1], rows[1][1], rows[2][1], 0,
              rows[0][2], rows[1][2], rows[2][2], 0,
              trans[0], trans[1], trans[2], 1]
    manifest_path = ROOT / "public" / "assets" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    item = {
        "id": name, "type": "splat", "url": f"assets/splats/{name}-fit.ply", "anchor": place,
        "replacesBuilding": bool(building), "matrix": [round(x, 6) for x in matrix], "centre": [round(ox, 2), round(oz, 2)],
        "fit": {"sceneToFootprint": best[0], "yawDeg": round(math.degrees(yaw), 1), "metresPerUnit": round(s, 4)},
    }
    manifest["items"] = [i for i in manifest.get("items", []) if i.get("id") != name] + [item]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"manifest updated: {name}")


if __name__ == "__main__":
    main()
