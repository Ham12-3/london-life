"""Point Blender's viewport through the zoo camera in rendered (Eevee) mode, without overlays.
    python tools/blender_mcp.py run tools/blender_world/view.py
"""
import bpy

scene = bpy.context.scene
for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
    try:
        scene.render.engine = engine
        break
    except TypeError:
        continue
scene.camera = bpy.data.objects["Zoo Camera"]
for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        sp = area.spaces[0]
        sp.shading.type = "RENDERED"
        sp.overlay.show_overlays = False
        sp.region_3d.view_perspective = "CAMERA"
        sp.clip_end = 3000
result = scene.render.engine
