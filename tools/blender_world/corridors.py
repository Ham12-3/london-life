"""Cut the ground and path faces out of the open tunnel ramps, where the earthworks (terrain.py)
bring their own paved floor and brick walls; otherwise the ground's coarse slopes cut across the
ramp. The covered stretch keeps its ground and road on top.

Run by terrain.py, or on its own:
    python tools/blender_mcp.py run tools/blender_world/corridors.py
"""
import bmesh
import bpy
import json
import math
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def open_ramp(T, x, z):
    """Is world (x, z) inside an open (uncovered) tunnel ramp?"""
    for t in T["tunnels"]:
        half, run = t["w"] / 2 + 1.25, 0.0
        for a, b in zip(t["pts"], t["pts"][1:]):
            L = math.dist(a, b) or 1e-9
            s = max(0.0, min(1.0, ((x - a[0]) * (b[0] - a[0]) + (z - a[1]) * (b[1] - a[1])) / (L * L)))
            if math.hypot(a[0] + (b[0] - a[0]) * s - x, a[1] + (b[1] - a[1]) * s - z) < half:
                along = run + s * L
                c0, c1 = t["covered"]
                if not (c0 <= along <= c1):
                    gap = c0 - along if along < c0 else along - c1
                    if gap < 18:
                        return True
            run += L
    return False


def cut(obj, T):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    doomed = [f for f in bm.faces if open_ramp(T, f.calc_center_median().x, -f.calc_center_median().y)]
    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return len(doomed)


if __name__ == "__main__" or "__file__" in globals() and not globals().get("_imported"):
    T = json.load(open(os.path.join(ROOT, "public", "assets", "terrain", "terrain.json")))
    print("ramp faces cut:", sum(cut(bpy.data.objects[n], T) for n in ("Ground", "Paths")))
