"""Re-apply the zoo's materials to the landmark models (after materials.py changes), without
rebuilding the scene.
    python tools/blender_mcp.py run tools/blender_world/remap.py
"""
import bpy
import importlib.util
import os

spec = importlib.util.spec_from_file_location("zoo_mats", os.path.join(os.path.dirname(__file__), "materials.py"))
mats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mats)

col = bpy.data.collections.get("Landmarks")
done = 0
for o in col.all_objects if col else []:
    for slot in getattr(o, "material_slots", []):
        if slot.material:
            m = mats.landmark(slot.material.name.split(".")[0])
            if m:
                slot.material = m
                done += 1
print("remapped", done)
