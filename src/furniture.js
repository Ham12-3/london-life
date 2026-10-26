// Street furniture modelled in Blender (tools/furniture/): London park benches, litter bins,
// Victorian lamp posts, drinking fountains, picnic tables, cycle stands, and spear-topped railings
// along every fence. Placements come from tools/furniture/place.py. Each item is instanced (one draw
// per material, however many there are); railings are drawn only near the walker, like the
// detailed trees, since there are almost 3,000 sections of them.
import * as THREE from "three/webgpu";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { pbr } from "./materials.js";

const ITEMS = ["bench", "bin", "lamp", "water", "picnic", "bikes", "railing"];
const SOLID = { bench: 0.55, bin: 0.32, lamp: 0.2, water: 0.35, picnic: 0.9, bikes: 0.2 };
export const RAILING_RANGE = 70;

export async function hasFurniture() {
  try {
    return (await fetch("assets/furniture/placements.json", { method: "HEAD" })).ok;
  } catch {
    return false;
  }
}

let materials = null;
function materialFor(name) {
  const std = (o) => new THREE.MeshStandardMaterial(o);
  materials ??= {
    iron: std({ color: 0x1a201d, roughness: 0.45, metalness: 0.6 }),
    iron_railing: std({ color: 0x141816, roughness: 0.5, metalness: 0.5 }),
    timber_bench: pbr("wood_planks", { tile: 1.2, tint: 0xb89a78 }),
    bin_green: std({ color: 0x1f3a2b, roughness: 0.4, metalness: 0.3 }),
    gold: std({ color: 0xd8aa46, roughness: 0.3, metalness: 1 }),
    lamp_glass: std({ color: 0xf2e6c8, roughness: 0.15, metalness: 0, emissive: 0x6a5a38, transparent: true, opacity: 0.85 }),
    stone: pbr("white_stucco", { tile: 2, tint: 0xd8d0c0, normalScale: 0.6 }),
    steel: std({ color: 0x9a9da0, roughness: 0.3, metalness: 0.9 }),
    paint_141614: std({ color: 0x141614, roughness: 0.6 }),
  };
  return materials[name.replace(/\.\d+$/, "")] || null;
}

export async function addFurniture(scene, collision) {
  const placements = await (await fetch("assets/furniture/placements.json")).json();
  const loader = new GLTFLoader().setDRACOLoader(new DRACOLoader().setDecoderPath("draco/"));
  const parts = {};
  await Promise.all(ITEMS.map(async (name) => {
    const gltf = await loader.loadAsync(`assets/furniture/${name}.glb`);
    parts[name] = [];
    gltf.scene.traverse((o) => { if (o.isMesh) parts[name].push({ geo: o.geometry, mat: materialFor(o.material.name) || o.material }); });
  }));

  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), pos = new THREE.Vector3(), sc = new THREE.Vector3(1, 1, 1);
  const up = new THREE.Vector3(0, 1, 0);
  const place = (mesh, i, [x, z, yaw, len]) => {
    sc.set(len ? len / 2.5 : 1, 1, 1);
    mesh.setMatrixAt(i, m4.compose(pos.set(x, 0, z), q.setFromAxisAngle(up, yaw), sc));
  };

  // Everything but railings: placed once.
  for (const name of ITEMS.filter((n) => n !== "railing")) {
    const list = placements[name] || [];
    if (!list.length) continue;
    for (const { geo, mat } of parts[name]) {
      const mesh = new THREE.InstancedMesh(geo, mat, list.length);
      list.forEach((p, i) => place(mesh, i, p));
      mesh.castShadow = name !== "bikes";
      mesh.receiveShadow = true;
      mesh.computeBoundingSphere();
      scene.add(mesh);
    }
    for (const [x, z] of list) collision.addCircle(x, z, SOLID[name]);
  }

  // Railings: only the sections near the walker, rebuilt as you move.
  const rails = placements.railing || [];
  const railMeshes = parts.railing.map(({ geo, mat }) => {
    const mesh = new THREE.InstancedMesh(geo, mat, rails.length);
    mesh.count = 0;
    mesh.castShadow = mesh.receiveShadow = true;
    mesh.frustumCulled = false;
    scene.add(mesh);
    return mesh;
  });
  let lastX = Infinity, lastZ = Infinity;
  return {
    update(p) {
      if ((p.x - lastX) ** 2 + (p.z - lastZ) ** 2 < 16) return;
      lastX = p.x;
      lastZ = p.z;
      let n = 0;
      for (const r of rails) {
        if ((r[0] - p.x) ** 2 + (r[1] - p.z) ** 2 > RAILING_RANGE * RAILING_RANGE) continue;
        for (const mesh of railMeshes) place(mesh, n, r);
        n++;
      }
      for (const mesh of railMeshes) {
        mesh.count = n;
        mesh.instanceMatrix.needsUpdate = true;
      }
    },
  };
}
