"""Aim the zoo camera from work/blender/cam.json: {"pos": [x, y, z], "look": [x, y, z], "lens": 24}
(Blender axes). The viewport looks through it, so a viewport screenshot shows that view.
    python tools/blender_mcp.py run tools/blender_world/camera.py
"""
import bpy
import json
import os
from mathutils import Vector

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
c = json.load(open(os.path.join(ROOT, "work", "blender", "cam.json")))
cam = bpy.data.objects["Zoo Camera"]
cam.location = Vector(c["pos"])
cam.rotation_euler = (Vector(c["look"]) - Vector(c["pos"])).to_track_quat("-Z", "Y").to_euler()
cam.data.lens = c.get("lens", 24)
bpy.context.scene.camera = cam
for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        area.spaces[0].region_3d.view_perspective = "CAMERA"
        area.tag_redraw()
