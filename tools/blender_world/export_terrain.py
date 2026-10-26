"""Export the Blender ground (with its levels), paths, water and earthworks for the web app:
public/assets/blender/terrain.glb (Draco). Run after terrain.py.
    python tools/blender_mcp.py run tools/blender_world/export_terrain.py
"""
import bpy
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
names = ("Ground", "Paths", "Water", "Earthworks")
for o in bpy.context.view_layer.objects:
    o.select_set(o.name in names)
bpy.context.view_layer.objects.active = bpy.data.objects["Ground"]
path = os.path.join(ROOT, "public", "assets", "blender", "terrain.glb")
bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
                          export_image_format="NONE", export_draco_mesh_compression_enable=True,
                          export_draco_mesh_compression_level=7, export_draco_position_quantization=16)
print("terrain.glb", sum(len(bpy.data.objects[n].data.polygons) for n in names), "faces", os.path.getsize(path) // 1024, "KB")
