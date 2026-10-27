"""Render every exported animal in a grid (work/animals_preview.png) to check the models. Each animal
is scaled to fill its cell, so the meerkat is as easy to judge as the giraffe.

    blender --background --factory-startup --python tools/animals/preview.py [-- species ...]
"""
import bpy
import json
import math
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "public", "assets", "animals")
OUT = os.path.join(ROOT, "work", "animals_preview.png")
LOG = os.path.join(ROOT, "work", "animals_preview.log")
log = open(LOG, "w")

try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    only = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ids = [i for i in json.load(open(os.path.join(SRC, "animals.json"))).keys() if not only or i in only]
    cols = min(6, len(ids))
    rows = math.ceil(len(ids) / cols)
    cell = 3.0
    for k, sid in enumerate(ids):
        bpy.ops.import_scene.gltf(filepath=os.path.join(SRC, sid + ".glb"))
        for o in bpy.context.selected_objects:
            if o.parent is None:
                bpy.context.view_layer.update()
                dims = o.dimensions
                s = cell * 0.8 / max(dims.x, dims.y, dims.z, 1e-3)
                o.scale = (s, s, s)
                o.location = ((k % cols) * cell, 0, -(k // cols) * cell)  # rows stacked upwards in the view
                o.rotation_euler = (0, 0, math.radians(-30))
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "VERTEX"
    scene.display.shading.show_shadows = False
    scene.display.shading.show_cavity = True
    scene.render.resolution_x, scene.render.resolution_y = 420 * cols, 420 * rows
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    scene.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = cell * max(cols, rows)
    cam.location = ((cols - 1) * cell / 2, -30, -(rows - 1) * cell / 2 + cell * 0.42)
    cam.rotation_euler = (math.radians(90), 0, 0)
    scene.camera = cam
    scene.render.filepath = OUT
    bpy.ops.render.render(write_still=True)
    print("done", file=log, flush=True)
except Exception:
    import traceback
    print(traceback.format_exc(), file=log)
    print("failed", file=log, flush=True)
