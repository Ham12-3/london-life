"""Export the Blender-modelled buildings for the web app: public/assets/blender/buildings.glb.
Materials go out by name only; src/blenderworld.js gives them the app's PBR surfaces.
    python tools/blender_mcp.py run tools/blender_world/export.py
"""
import bpy
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "public", "assets", "blender")
os.makedirs(OUT, exist_ok=True)

obj = bpy.data.objects["Buildings"]
for o in bpy.context.view_layer.objects:
    o.select_set(o == obj)
bpy.context.view_layer.objects.active = obj
path = os.path.join(OUT, "buildings.glb")
bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
                          export_image_format="NONE", export_draco_mesh_compression_enable=True,
                          export_draco_mesh_compression_level=7, export_draco_position_quantization=16)
print(f"buildings.glb: {len(obj.data.polygons)} faces, {os.path.getsize(path) // 1024} KB")
