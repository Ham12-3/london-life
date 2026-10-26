"""Place the Blender street furniture (tools/furniture/) in the Blender zoo, from the same
placements as the web app: benches, bins, Victorian lamp posts, fountains, picnic tables, cycle
stands, and railing sections along every fence. Linked duplicates of one model per item.
    python tools/furniture/place.py
    python tools/blender_mcp.py run tools/blender_world/furniture.py
"""
import bpy
import importlib.util
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "public", "assets", "furniture")
spec = importlib.util.spec_from_file_location("zoo_mats", os.path.join(os.path.dirname(__file__), "materials.py"))
mats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mats)

root = bpy.data.collections["London Zoo"]
col = bpy.data.collections.get("Furniture")
if col:
    for o in list(col.all_objects):
        bpy.data.objects.remove(o, do_unlink=True)
else:
    col = bpy.data.collections.new("Furniture")
    root.children.link(col)
placements = json.load(open(os.path.join(SRC, "placements.json")))
count = 0
for name, items in placements.items():
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(SRC, name + ".glb"))
    protos = [o for o in set(bpy.data.objects) - before if o.type == "MESH"]
    for o in set(bpy.data.objects) - before:
        for c in list(o.users_collection):
            c.objects.unlink(o)
    for p in protos:
        p.data.transform(p.matrix_world)  # bake the import's axis conversion into the mesh
        for slot in p.material_slots:
            if slot.material:
                m = mats.landmark(slot.material.name.split(".")[0])
                if m:
                    slot.material = m
    for item in items:
        x, z, yaw = item[:3]
        for p in protos:
            o = bpy.data.objects.new(f"{name}.{count}", p.data)
            o.location = (x, -z, 0)
            o.rotation_euler = (0, 0, yaw)
            if len(item) > 3:
                o.scale = (item[3] / 2.5, 1, 1)
            col.objects.link(o)
        count += 1
print("furniture placed:", count)
