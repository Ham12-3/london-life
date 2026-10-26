"""Reload the landmark models (public/assets/landmarks) into the Blender zoo after rebuilding them,
without rebuilding the rest of the scene.
    python tools/blender_mcp.py run tools/blender_world/landmarks_reload.py
"""
import bpy
import importlib.util
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
spec = importlib.util.spec_from_file_location("zoo_mats", os.path.join(os.path.dirname(__file__), "materials.py"))
mats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mats)

col = bpy.data.collections["Landmarks"]
for o in list(col.objects):
    bpy.data.objects.remove(o, do_unlink=True)
for L in json.load(open(os.path.join(ROOT, "public", "assets", "landmarks", "landmarks.json"), encoding="utf-8")):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(ROOT, "public", L["url"].replace("/", os.sep)))
    for o in set(bpy.data.objects) - before:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        col.objects.link(o)
        if o.parent is None:
            o.location = (L["origin"][0], -L["origin"][1], 0)
        for slot in getattr(o, "material_slots", []):
            if slot.material:
                m = mats.landmark(slot.material.name.split(".")[0])
                if m:
                    slot.material = m
print("landmarks reloaded:", len(col.objects))
