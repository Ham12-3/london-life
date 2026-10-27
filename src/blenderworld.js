// Buildings modelled in Blender (tools/blender_world/): real wall thickness, windows set into their
// openings, door surrounds, plinths, cornices, parapets and hipped roofs. The GLB carries material
// names only; they get the app's PBR surfaces here, so they match everything else.
import * as THREE from "three/webgpu";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { pbr } from "./materials.js";
import { waterMaterial } from "./water.js";
import { GROUND_STYLE, PATH_STYLE } from "./world.js";
import { texture, uv, positionWorld } from "three/tsl";
import { groundAO } from "./terrain.js";

export const BLENDER_BUILDINGS = "assets/blender/buildings.glb";
export const BLENDER_TERRAIN = "assets/blender/terrain.glb";

const exists = async (url) => {
  try {
    return (await fetch(url, { method: "HEAD" })).ok;
  } catch {
    return false;
  }
};
export const hasBlenderBuildings = () => exists(BLENDER_BUILDINGS);
export const hasBlenderTerrain = () => exists(BLENDER_TERRAIN);

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
  // The ground, paths and water of the Blender terrain, as world.js draws them.
  lawn: () => pbr(GROUND_STYLE.grass.tex, GROUND_STYLE.grass),
  zoo_ground: () => pbr("sparse_grass", { tile: 3, colorize: [0.085, 0.12, 0.04] }),
  woodland: () => pbr(GROUND_STYLE.wood.tex, GROUND_STYLE.wood),
  dirt: () => pbr(GROUND_STYLE.enclosure.tex, GROUND_STYLE.enclosure),
  sand: () => pbr(GROUND_STYLE.sand.tex, GROUND_STYLE.sand),
  rock: () => pbr(GROUND_STYLE.rock.tex, GROUND_STYLE.rock),
  paving: () => pbr(PATH_STYLE.footway.tex, PATH_STYLE.footway),
  gravel: () => pbr(PATH_STYLE.path.tex, PATH_STYLE.path),
  asphalt: () => pbr(PATH_STYLE.road.tex, PATH_STYLE.road),
  steps: () => pbr(PATH_STYLE.steps.tex, PATH_STYLE.steps),
  cycleway: () => pbr(PATH_STYLE.cycleway.tex, PATH_STYLE.cycleway),
  concrete: () => pbr(PATH_STYLE.corridor.tex, PATH_STYLE.corridor),
  boards: () => pbr("wood_planks", { tile: 2, tint: 0xd8d0c4 }),
  water: () => waterMaterial(),
};

const cache = new Map();
function materialFor(name) {
  const base = name.replace(/\.\d+$/, "");
  if (cache.has(base)) return cache.get(base);
  let m;
  const paint = base.match(/^render_([0-9a-f]{6})$/);
  if (paint) m = pbr("white_stucco", { tile: 3, tint: parseInt(paint[1], 16), normalScale: 0.6 });
  else m = FIXED[base] ? FIXED[base]() : null;
  if (m && base === "glass") m.userData.noAO = true;
  cache.set(base, m);
  return m;
}

// Ambient occlusion baked in Blender (tools/blender_world/bake_ao.py) multiplies a material's sky
// light only: from an atlas on the second UV set (TEXCOORD_1) on buildings and earthworks, from the
// top-down ground image on the ground and paths. Glass keeps its sky reflections.
async function loadAtlas(url) {
  if (!(await exists(url))) return null;
  const t = await new THREE.TextureLoader().loadAsync(url);
  t.flipY = false; // glTF UVs
  t.colorSpace = THREE.SRGBColorSpace;
  // No mipmaps: they'd bleed the dark room interiors into neighbouring islands at a distance.
  t.generateMipmaps = false;
  t.minFilter = THREE.LinearFilter;
  return t;
}

const aoCache = new Map();
function withAO(m, kind, terrain, atlas) {
  if (m.userData.noAO) return m;
  const key = `${m.uuid}:${kind}:${atlas?.uuid}`;
  if (aoCache.has(key)) return aoCache.get(key);
  const ao = kind === "atlas" ? texture(atlas, uv(1)).r : groundAO(terrain, positionWorld.xz, positionWorld.y);
  let c;
  if (m.isNodeMaterial) {
    c = m.clone();
    c.aoNode = m.aoNode ? m.aoNode.mul(ao) : ao;
  } else {
    c = new THREE.MeshStandardNodeMaterial();
    c.setValues({ color: m.color, roughness: m.roughness, metalness: m.metalness, side: m.side, transparent: m.transparent,
      opacity: m.opacity, emissive: m.emissive, map: m.map, alphaTest: m.alphaTest });
    c.aoNode = ao;
  }
  aoCache.set(key, c);
  return c;
}

function applyAO(o, terrain, atlas) {
  const kind = atlas && o.geometry.attributes.uv1 ? "atlas" : /^(Ground|Paths)/.test(o.name) && terrain?.ao ? "ground" : null;
  if (!kind) return;
  const set = (m) => withAO(m, kind, terrain, atlas);
  o.material = Array.isArray(o.material) ? o.material.map(set) : set(o.material);
}

export async function addBlenderTerrain(scene, terrain) {
  const draco = new DRACOLoader().setDecoderPath("draco/");
  const [gltf, atlas] = await Promise.all([
    new GLTFLoader().setDRACOLoader(draco).loadAsync(BLENDER_TERRAIN), loadAtlas("assets/blender/ao_earthworks.jpg"),
  ]);
  gltf.scene.traverse((o) => {
    if (!o.isMesh) return;
    const swap = (m) => materialFor(m.name) || m;
    o.material = Array.isArray(o.material) ? o.material.map(swap) : swap(o.material);
    if (!o.name.startsWith("Water")) applyAO(o, terrain, atlas);
    o.receiveShadow = true;
    o.castShadow = o.name.startsWith("Earthworks");
    if (o.name.startsWith("Earthworks")) {
      // Walls are single faces: show both sides (the canal walls are seen from across the water).
      const two = (m) => { const c = m.clone(); c.side = THREE.DoubleSide; return c; };
      o.material = Array.isArray(o.material) ? o.material.map(two) : two(o.material);
    }
  });
  scene.add(gltf.scene);
  draco.dispose();
  return gltf.scene;
}

export async function addBlenderBuildings(scene) {
  const draco = new DRACOLoader().setDecoderPath("draco/");
  const loader = new GLTFLoader().setDRACOLoader(draco);
  const [gltf, atlas] = await Promise.all([loader.loadAsync(BLENDER_BUILDINGS), loadAtlas("assets/blender/ao_buildings.jpg")]);
  gltf.scene.traverse((o) => {
    if (!o.isMesh) return;
    const swap = (m) => materialFor(m.name) || m;
    o.material = Array.isArray(o.material) ? o.material.map(swap) : swap(o.material);
    applyAO(o, null, atlas);
    o.castShadow = o.receiveShadow = true;
  });
  scene.add(gltf.scene);
  draco.dispose();
  return gltf.scene;
}
