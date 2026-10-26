// Buildings modelled in Blender (tools/blender_world/): real wall thickness, windows set into their
// openings, door surrounds, plinths, cornices, parapets and hipped roofs. The GLB carries material
// names only; they get the app's PBR surfaces here, so they match everything else.
import * as THREE from "three/webgpu";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { pbr } from "./materials.js";

export const BLENDER_BUILDINGS = "assets/blender/buildings.glb";

export async function hasBlenderBuildings() {
  try {
    const res = await fetch(BLENDER_BUILDINGS, { method: "HEAD" });
    return res.ok;
  } catch {
    return false;
  }
}

const std = (o) => new THREE.MeshStandardMaterial(o);
const FIXED = {
  brick_red: () => pbr("brick_wall_02", { tile: 2, tint: 0xe0a08c }),
  brick_buff: () => pbr("brick_wall_003", { tile: 2 }),
  stone: () => pbr("white_stucco", { tile: 2, tint: 0xe4ddcc, normalScale: 0.6 }),
  plinth: () => pbr("concrete_floor_02", { tile: 2, tint: 0x8c867c }),
  plaster: () => std({ color: 0xe8e3d8, roughness: 0.9 }),
  floor_int: () => pbr("concrete_floor_02", { tile: 2, tint: 0xe8e0d0, roughness: 0.7 }),
  roof_flat: () => pbr("concrete_floor_02", { tile: 3, tint: 0x8e8a84 }),
  slate_uv: () => pbr("roof_slates_02", { tile: 2, uv: "mesh", side: THREE.DoubleSide }),
  tiles_uv: () => pbr("clay_roof_tiles", { tile: 2, uv: "mesh", side: THREE.DoubleSide }),
  timber_white: () => std({ color: 0xefede6, roughness: 0.6 }),
  glass: () => std({ color: 0x334550, roughness: 0.03, metalness: 0.55, side: THREE.DoubleSide }),
  frame_white: () => std({ color: 0xefeee8, roughness: 0.5 }),
  frame_dark: () => std({ color: 0x353d39, roughness: 0.5 }),
  door_black: () => std({ color: 0x15181a, roughness: 0.35 }),
  door_navy: () => std({ color: 0x1c2a44, roughness: 0.35 }),
  door_green: () => std({ color: 0x1f3a2b, roughness: 0.35 }),
  door_oxblood: () => std({ color: 0x5a1d1d, roughness: 0.35 }),
  door_slate: () => std({ color: 0x3d5566, roughness: 0.35 }),
};

const cache = new Map();
function materialFor(name) {
  const base = name.replace(/\.\d+$/, "");
  if (cache.has(base)) return cache.get(base);
  let m;
  const paint = base.match(/^render_([0-9a-f]{6})$/);
  if (paint) m = pbr("white_stucco", { tile: 3, tint: parseInt(paint[1], 16), normalScale: 0.6 });
  else m = FIXED[base] ? FIXED[base]() : null;
  cache.set(base, m);
  return m;
}

export async function addBlenderBuildings(scene) {
  const draco = new DRACOLoader().setDecoderPath("draco/");
  const loader = new GLTFLoader().setDRACOLoader(draco);
  const gltf = await loader.loadAsync(BLENDER_BUILDINGS);
  gltf.scene.traverse((o) => {
    if (!o.isMesh) return;
    const swap = (m) => materialFor(m.name) || m;
    o.material = Array.isArray(o.material) ? o.material.map(swap) : swap(o.material);
    o.castShadow = o.receiveShadow = true;
  });
  scene.add(gltf.scene);
  draco.dispose();
  return gltf.scene;
}
