"""Eevee settings for a realistic look: ray-traced reflections (windows and water pick up the sky),
soft shadows, high-quality sky lighting, AgX colour.
    python tools/blender_mcp.py run tools/blender_world/render_settings.py
"""
import bpy

scene = bpy.context.scene
ee = scene.eevee
for attr, value in (("use_raytracing", True), ("use_shadows", True), ("shadow_ray_count", 2), ("shadow_step_count", 8),
                    ("use_volumetric_shadows", False), ("taa_samples", 32), ("taa_render_samples", 64)):
    if hasattr(ee, attr):
        setattr(ee, attr, value)
if hasattr(ee, "ray_tracing_options"):
    ee.ray_tracing_options.resolution_scale = "2"
    if hasattr(ee.ray_tracing_options, "use_denoise"):
        ee.ray_tracing_options.use_denoise = True
if hasattr(ee, "fast_gi_method"):
    ee.fast_gi_method = "GLOBAL_ILLUMINATION"
try:
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
except TypeError:
    pass
sun = bpy.data.objects.get("Zoo Sun")
if sun:
    sun.data.energy = 4.5
    if hasattr(sun.data, "shadow_soft_size"):
        sun.data.angle = 0.012
