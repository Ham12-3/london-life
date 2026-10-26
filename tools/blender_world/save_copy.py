"""Save a copy of the live Blender zoo to work/blender/zoo.blend, for headless jobs (bake_ao.py)
to open without touching the scene you're working in.

    python tools/blender_mcp.py run tools/blender_world/save_copy.py
"""
import bpy
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
path = os.path.join(ROOT, "work", "blender", "zoo.blend")
os.makedirs(os.path.dirname(path), exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
print("saved", os.path.getsize(path) // (1024 * 1024), "MB")
