"""Render every exported animal side by side (work/animals_preview.png) to check the models.

    blender --background --factory-startup --python tools/animals/preview.py
"""
import bpy
import json
import math
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "public", "assets", "animals")
OUT = os.path.join(ROOT, "work", "animals_preview.png")
LOG = os.path.join(ROOT, "work", "animals_preview.log")
log = open(LOG, "w")

try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ids = list(json.load(open(os.path.join(SRC, "animals.json"))).keys())
    cols = 6
    for k, sid in enumerate(ids):
        bpy.ops.import_scene.gltf(filepath=os.path.join(SRC, sid + ".glb"))
        for o in bpy.context.selected_objects:
            if o.parent is None:
                o.location = ((k % cols) * 3.2, -(k // cols) * 4.5, 0)
                o.rotation_euler = (0, 0, math.radians(-35))
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "VERTEX"
    scene.display.shading.show_shadows = True
    scene.render.resolution_x, scene.render.resolution_y = 1600, 1100
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    scene.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 21
    cam.location = (8.0, -30.0, 12.0)
    cam.rotation_euler = (math.radians(72), 0, 0)
    scene.camera = cam
    scene.render.filepath = OUT
    bpy.ops.render.render(write_still=True)
    print("done", file=log, flush=True)
except Exception:
    import traceback
    print(traceback.format_exc(), file=log)
    print("failed", file=log, flush=True)
