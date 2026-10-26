// The zoo's landmark buildings, modelled in Blender from their real footprints (tools/landmarks/).
// The GLBs carry only material names; each name gets the same physically based surfaces as the rest
// of the zoo here, so a Blender model and a generated building of the same brick look the same.
import * as THREE from "three/webgpu";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { pbr } from "./materials.js";
import { waterMaterial } from "./water.js";

export async function loadLandmarkIndex() {
  try {
    const res = await fetch("assets/landmarks/landmarks.json");
    return res.ok ? await res.json() : [];
  } catch {
    return [];
  }
}

function clockTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 256;
  const g = c.getContext("2d");
  g.fillStyle = "#1c2420";
  g.fillRect(0, 0, 256, 256);
  g.fillStyle = "#f4f1e8";
  g.beginPath();
  g.arc(128, 128, 118, 0, Math.PI * 2);
  g.fill();
  g.strokeStyle = "#c9a54a";
  g.lineWidth = 6;
  g.stroke();
  g.fillStyle = "#1a1a1a";
  g.font = "bold 26px Georgia, serif";
  g.textAlign = "center";
  g.textBaseline = "middle";
  const numerals = ["XII", "I", "II", "III", "IIII", "V", "VI", "VII", "VIII", "IX", "X", "XI"];
  numerals.forEach((n, i) => {
    const a = (i / 12) * Math.PI * 2 - Math.PI / 2;
    g.fillText(n, 128 + Math.cos(a) * 92, 128 + Math.sin(a) * 92);
  });
  // Hands at ten past two, the classic clock-face pose.
  g.lineCap = "round";
  const hand = (a, len, w) => {
    g.lineWidth = w;
    g.beginPath();
    g.moveTo(128, 128);
    g.lineTo(128 + Math.cos(a - Math.PI / 2) * len, 128 + Math.sin(a - Math.PI / 2) * len);
    g.stroke();
  };
  g.strokeStyle = "#111";
  hand((2 + 10 / 60) / 12 * Math.PI * 2, 55, 8);
  hand((10 / 60) * Math.PI * 2, 82, 5);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function netTexture() {
  // Stainless-steel aviary mesh, as an alpha map: white wires on black (see-through) gaps.
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d");
  g.fillStyle = "#000";
  g.fillRect(0, 0, 128, 128);
  g.strokeStyle = "#ffffff";
  g.lineWidth = 3;
  for (let i = -128; i <= 256; i += 16) {
    g.beginPath(); g.moveTo(i, 0); g.lineTo(i + 128, 128); g.stroke();
    g.beginPath(); g.moveTo(i, 128); g.lineTo(i + 128, 0); g.stroke();
  }
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(6, 6); // UVs run 1 unit per 2 m: ~16 cm mesh
  return t;
}

let materials = null;
function landmarkMaterials() {
  if (materials) return materials;
  const std = (o) => new THREE.MeshStandardMaterial(o);
  materials = {
    concrete_white: pbr("white_stucco", { tile: 3, tint: 0xf2f0ea, normalScale: 0.5 }),
    concrete_floor: pbr("concrete_pavement", { tile: 2.5, tint: 0xe8e4dc }),
    concrete: pbr("concrete_floor_02", { tile: 3, tint: 0xd8d4cc }),
    concrete_ribbed: pbr("white_stucco", { tile: 2, tint: 0xb9b2a4, normalScale: 1.4 }),
    concrete_roof: pbr("concrete_floor_02", { tile: 3, tint: 0x8e8a84 }),
    brick_buff: pbr("brick_wall_003", { tile: 2 }),
    brick_red: pbr("brick_wall_02", { tile: 2, tint: 0xe0a08c }),
    stone: pbr("white_stucco", { tile: 2, tint: 0xe4ddcc, normalScale: 0.6 }),
    terracotta: pbr("white_stucco", { tile: 2, tint: 0xb8673f }),
    slate: pbr("roof_slates_02", { tile: 2, side: THREE.DoubleSide }),
    pool_water: std({ color: 0x1f7f92, roughness: 0.06, metalness: 0.05 }),
    alu: std({ color: 0xc8ccd0, roughness: 0.35, metalness: 0.9 }),
    // Close up you see the wires; further off they blend into a light silver veil.
    net: std({ color: 0xb4bac0, roughness: 0.4, metalness: 0.7, alphaMap: netTexture(), transparent: true, opacity: 0.85, depthWrite: false, side: THREE.DoubleSide }),
    copper: std({ color: 0x5f9a84, roughness: 0.55, metalness: 0.25 }),
    glass: std({ color: 0x334550, roughness: 0.03, metalness: 0.55, side: THREE.DoubleSide }),
    glass_roof: std({ color: 0x4a5a60, roughness: 0.08, metalness: 0.4, side: THREE.DoubleSide }),
    timber_white: std({ color: 0xefede6, roughness: 0.6 }),
    timber_dark: std({ color: 0x3a2e26, roughness: 0.7 }),
    clock_face: std({ map: clockTexture(), roughness: 0.4 }),
    lead: std({ color: 0x6a7077, roughness: 0.5, metalness: 0.35 }),
    gold: std({ color: 0xd8aa46, roughness: 0.3, metalness: 1 }),
    iron: std({ color: 0x1e2723, roughness: 0.5, metalness: 0.5 }),
  };
  Object.assign(materials, {
    brick_brown: pbr("brick_wall_02", { tile: 2, tint: 0x8a6a62 }),
    tiles_dark: pbr("roof_slates_02", { tile: 2, uv: "mesh", tint: 0x8a8a90, side: THREE.DoubleSide }),
    timber_weathered: pbr("wood_plank_wall", { tile: 2.5, tint: 0xc8bba8 }),
    thatch: pbr("reed_roof_04", { tile: 2.5, side: THREE.DoubleSide }),
    corrugated: pbr("corrugated_iron_02", { tile: 2, side: THREE.DoubleSide }),
    corrugated_rust: pbr("rusty_corrugated_iron", { tile: 2, side: THREE.DoubleSide }),
    sandstone: pbr("red_sandstone_wall", { tile: 2.5 }),
    rock: pbr("aerial_rocks_02", { tile: 3 }),
    gravel: pbr("gravel_ground_01", { tile: 2.5 }),
    roof_flat: pbr("concrete_floor_02", { tile: 3, tint: 0x8e8a84 }),
    frame_white: std({ color: 0xefeee8, roughness: 0.5 }),
    steel: std({ color: 0x8a8d90, roughness: 0.35, metalness: 0.9 }),
    rope: std({ color: 0x8a7558, roughness: 0.9 }),
    water: waterMaterial(),
    paving: pbr("concrete_pavement", { tile: 3, tint: 0xf0ece4 }),
    bronze: std({ color: 0x5a4632, roughness: 0.38, metalness: 1 }),
    // Concrete cast as rock: buff-grey, not mossy.
    rock_face: pbr("concrete_floor_02", { tile: 3, tint: 0xd8d2c4 }),
    ledge: pbr("concrete_floor_02", { tile: 3, tint: 0xb0aa98 }),
    // Step 5's animal houses.
    glass_clear: std({ color: 0xd6e6e8, roughness: 0.05, metalness: 0.1, transparent: true, opacity: 0.22, depthWrite: false, side: THREE.DoubleSide }),
    polytunnel: std({ color: 0xa8d47a, roughness: 0.5, transparent: true, opacity: 0.8, side: THREE.DoubleSide }),
    sedum: pbr("sparse_grass", { tile: 2, colorize: [0.13, 0.15, 0.05] }),
    tiles_clay: pbr("clay_roof_tiles", { tile: 2, side: THREE.DoubleSide }),
    decking: pbr("wood_planks", { tile: 2, tint: 0xc8b8a0 }),
  });
  return materials;
}

// Materials named by pattern: render_<hex> (painted render), paint_<hex> (gloss paint),
// fabric_<hex> (awnings, bunting, banners), sign_*/banner_*/shutter/mosaic_*/mural_* (painted images).
const loader = new THREE.TextureLoader();
function imageMaterial(name) {
  const t = loader.load(`assets/landmarks/textures/${name}.png`);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  t.flipY = false; // glTF UVs run from the top of the image
  if (name === "shutter") t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return new THREE.MeshStandardMaterial({ map: t, roughness: 0.6, side: THREE.DoubleSide });
}
function materialFor(name) {
  const mats = landmarkMaterials();
  const base = name.replace(/\.\d+$/, "");
  if (mats[base]) return mats[base];
  const m = base.match(/^(render|paint|fabric)_([0-9a-f]{6})$/);
  let made = null;
  if (m) {
    const c = parseInt(m[2], 16);
    if (m[1] === "render") made = pbr("white_stucco", { tile: 3, tint: c, normalScale: 0.7 });
    else if (m[1] === "paint") made = new THREE.MeshStandardMaterial({ color: c, roughness: 0.45 });
    else made = new THREE.MeshStandardMaterial({ color: c, roughness: 0.85, side: THREE.DoubleSide });
  } else if (/^(sign_|banner_|shutter|mosaic_|mural_)/.test(base)) {
    made = imageMaterial(base);
  }
  if (made) mats[base] = made;
  return made;
}

export async function addLandmarks(index, scene) {
  const loader = new GLTFLoader().setDRACOLoader(new DRACOLoader().setDecoderPath("draco/")); // models are Draco-compressed
  const groups = await Promise.all(index.map(async (L) => {
    try {
      const gltf = await loader.loadAsync(L.url);
      gltf.scene.traverse((o) => {
        if (!o.isMesh) return;
        const swap = (m) => materialFor(m.name) || m;
        o.material = Array.isArray(o.material) ? o.material.map(swap) : swap(o.material);
        o.castShadow = o.receiveShadow = true;
      });
      gltf.scene.position.set(L.origin[0], 0, L.origin[1]);
      scene.add(gltf.scene);
      return gltf.scene;
    } catch (err) {
      console.warn(`landmark ${L.id} failed to load`, err);
      return null;
    }
  }));
  return groups.filter(Boolean);
}
