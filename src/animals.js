// Animals that wander inside their real enclosure outlines.
// Each species is a Blender model (tools/animals/build.py) with its coat painted into vertex
// colours; every animal of a species is one instance of it, and their legs swing on the GPU as they
// walk (one draw call per species, however many animals).
import * as THREE from "three/webgpu";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { attribute, positionLocal, positionGeometry, time, sin, cos, abs, vec3, float, uniformArray, instanceIndex } from "three/tsl";
import { pointInPoly } from "./world.js";

// Keyword in the OSM area name -> species model. len in metres (sets walking pace).
const SPECIES = [
  { id: "gorilla", match: /gorilla/i, label: "Western lowland gorilla", len: 0.9, count: 4 },
  { id: "lion", match: /lion/i, label: "Asiatic lion", len: 2.0, count: 3 },
  { id: "tiger", match: /tiger/i, label: "Sumatran tiger", len: 2.1, count: 2 },
  { id: "giraffe", match: /giraffe/i, label: "Giraffe", len: 2.2, count: 3 },
  { id: "zebra", match: /zebra/i, label: "Zebra", len: 1.9, count: 3 },
  { id: "okapi", match: /okapi/i, label: "Okapi", len: 1.9, count: 2 },
  { id: "warthog", match: /warthog/i, label: "Warthog", len: 1.2, count: 3 },
  { id: "hippo", match: /hippo/i, label: "Pygmy hippo", len: 1.6, count: 2 },
  { id: "camel", match: /camel/i, label: "Bactrian camel", len: 2.4, count: 2 },
  { id: "alpaca", match: /alpaca|llama/i, label: "Alpaca", len: 1.3, count: 3 },
  { id: "ostrich", match: /ostrich|emu/i, label: "Ostrich", len: 1.0, count: 3 },
  { id: "penguin", match: /penguin/i, label: "Humboldt penguin", len: 0.3, count: 14 },
  { id: "flamingo", match: /flamingo/i, label: "Flamingo", len: 0.6, count: 10 },
  { id: "pelican", match: /pelican/i, label: "Pelican", len: 0.9, count: 4 },
  { id: "wallaby", match: /wallab|outback/i, label: "Wallaby", len: 0.8, count: 4 },
  { id: "meerkat", match: /meerkat|mongoose/i, label: "Meerkat", len: 0.2, count: 8 },
  { id: "otter", match: /otter/i, label: "Otter", len: 0.9, count: 3 },
  { id: "coati", match: /coati/i, label: "Coati", len: 0.8, count: 4 },
  { id: "deer", match: /deer/i, label: "Chinese water deer", len: 1.0, count: 3 },
  { id: "goat", match: /goat|farmyard/i, label: "Pygmy goat", len: 0.8, count: 4 },
  { id: "pig", match: /pig/i, label: "Mangalitsa pig", len: 1.1, count: 3 },
  { id: "lemur", match: /lemur/i, label: "Ring-tailed lemur", len: 0.4, count: 6 },
  { id: "monkey", match: /monkey|macaque|mangabey|langur|gibbon|titi|tamarin/i, label: "Monkey", len: 0.45, count: 5 },
];

// Tag each vertex with the leg it belongs to: (hip x, hip y, weight, gait phase). Vertices below a
// hip and close to that leg's axis swing with it; diagonal legs move together (a trot), and two-legged
// animals alternate.
function legAttribute(geo, rig) {
  const pos = geo.attributes.position, n = pos.count, out = new Float32Array(n * 4);
  const reach = rig.legR * 2.6;
  for (let i = 0; i < n; i++) {
    const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
    let best = -1, bd = Infinity;
    rig.legs.forEach(([lx, , lz], j) => {
      const d = (x - lx) ** 2 + (z - lz) ** 2;
      if (d < bd) { bd = d; best = j; }
    });
    const [lx, ly, lz] = rig.legs[best];
    const below = ly - y;
    const w = Math.sqrt(bd) < reach && below > 0 ? Math.min(1, below / (ly * 0.3 + 1e-3)) : 0;
    const front = lx > 0.02, side = lz > 0;
    out.set([lx, ly, w * w * (3 - 2 * w), front === side ? 0 : Math.PI], i * 4);
  }
  geo.setAttribute("leg", new THREE.BufferAttribute(out, 4));
}

function walkingMaterial(rig, sp, walk) {
  const leg = attribute("leg", "vec4");
  // Per animal (walking 0..1, own phase, cos heading, sin heading): a uniform array by instance.
  const state = uniformArray(walk, "vec4").element(instanceIndex);
  // One stride per ~0.9 hip heights travelled, so the feet don't skate.
  const hip = Math.max(...rig.legs.map((l) => l[1]));
  const freq = (2 * Math.PI * (0.4 + sp.len * 0.3)) / Math.max(0.12, hip * 0.9);
  const phase = time.mul(freq).add(state.y);
  const theta = sin(phase.add(leg.w)).mul(0.42).mul(leg.z).mul(state.x);
  // Swing in the model's own space, then turn that offset by the animal's heading and add it to the
  // placed position (three applies the instance matrix before positionNode).
  const p = positionGeometry;
  const dx = p.x.sub(leg.x), dy = p.y.sub(leg.y);
  const offX = leg.x.add(dx.mul(cos(theta))).sub(dy.mul(sin(theta))).sub(p.x);
  const offY = leg.y.add(dx.mul(sin(theta))).add(dy.mul(cos(theta))).sub(p.y).add(abs(sin(phase)).mul(hip * 0.035).mul(state.x));
  const m = new THREE.MeshStandardNodeMaterial({ vertexColors: true, roughness: 0.85 });
  m.positionNode = positionLocal.add(vec3(offX.mul(state.z), offY, offX.mul(state.w).negate()));
  return m;
}

async function loadSpecies(ids) {
  const res = await fetch("assets/animals/animals.json").catch(() => null);
  const index = res && res.ok ? await res.json() : {};
  const loader = new GLTFLoader().setDRACOLoader(new DRACOLoader().setDecoderPath("draco/")); // models are Draco-compressed
  const out = new Map();
  await Promise.all(ids.map(async (id) => {
    if (!index[id]) return;
    try {
      const gltf = await loader.loadAsync(`assets/animals/${id}.glb`);
      let geo = null;
      gltf.scene.traverse((o) => { if (o.isMesh && !geo) geo = o.geometry; });
      if (!geo) return;
      if (geo.attributes.color && geo.attributes.color.itemSize === 4) {
        const c = geo.attributes.color, rgb = new Float32Array(c.count * 3);
        for (let i = 0; i < c.count; i++) rgb.set([c.getX(i), c.getY(i), c.getZ(i)], i * 3);
        geo.setAttribute("color", new THREE.BufferAttribute(rgb, 3));
      }
      legAttribute(geo, index[id]);
      out.set(id, { geo, rig: index[id] });
    } catch (err) {
      console.warn(`animal ${id} failed to load`, err);
    }
  }));
  return out;
}

function randomPointIn(area, rnd) {
  for (let i = 0; i < 40; i++) {
    const x = area.bb.minX + rnd() * (area.bb.maxX - area.bb.minX);
    const z = area.bb.minZ + rnd() * (area.bb.maxZ - area.bb.minZ);
    if (pointInPoly(area.pts, x, z)) return [x, z];
  }
  return area.c;
}

export async function spawnAnimals(world, scene, { replacedSpecies = new Set(), capturedPlaces = new Set(), terrain = { heightAt: () => 0 } } = {}) {
  let seed = 42;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const animals = [];
  const herds = new Map(); // species -> { animals }
  for (const a of world.areas) {
    const sp = SPECIES.find((s) => s.match.test(a.name));
    // A captured splat of the enclosure already shows its animals.
    if (!sp || replacedSpecies.has(sp.label) || capturedPlaces.has(a.name)) continue;
    const xs = a.pts.map((p) => p[0]), zs = a.pts.map((p) => p[1]);
    const area = { ...a, bb: { minX: Math.min(...xs), maxX: Math.max(...xs), minZ: Math.min(...zs), maxZ: Math.max(...zs) } };
    const count = Math.max(1, Math.min(sp.count, Math.round(a.a / 40)));
    if (!herds.has(sp)) herds.set(sp, { animals: [] });
    for (let i = 0; i < count; i++) {
      const mesh = new THREE.Object3D(); // placement only; drawn by the species' InstancedMesh
      const [x, z] = randomPointIn(area, rnd);
      mesh.position.set(x, terrain.heightAt(x, z), z);
      mesh.rotation.y = rnd() * Math.PI * 2;
      const an = { mesh, area, species: sp, target: randomPointIn(area, rnd), wait: rnd() * 5, speed: 0.4 + sp.len * 0.3, rnd, walking: 0 };
      herds.get(sp).animals.push(an);
      animals.push(an);
    }
  }
  const models = await loadSpecies([...herds.keys()].map((sp) => sp.id));
  for (const [sp, herd] of herds) {
    const model = models.get(sp.id);
    if (!model) continue;
    herd.walk = herd.animals.map((an) => new THREE.Vector4(0, an.rnd() * 6.28, 1, 0));
    herd.inst = new THREE.InstancedMesh(model.geo, walkingMaterial(model.rig, sp, herd.walk), herd.animals.length);
    herd.inst.castShadow = true;
    herd.inst.receiveShadow = true;
    herd.inst.frustumCulled = false; // animals wander; the bounds would go stale
    herd.animals.forEach((an, i) => { an.mesh.updateMatrix(); herd.inst.setMatrixAt(i, an.mesh.matrix); });
    scene.add(herd.inst);
  }
  return {
    animals,
    update(dt) {
      for (const an of animals) {
        const moving = an.wait <= 0;
        an.walking += ((moving ? 1 : 0) - an.walking) * Math.min(1, dt * 4);
        if (!moving) { an.wait -= dt; continue; }
        const p = an.mesh.position;
        const dx = an.target[0] - p.x, dz = an.target[1] - p.z;
        const d = Math.hypot(dx, dz);
        if (d < 0.3) {
          an.target = randomPointIn(an.area, an.rnd);
          an.wait = 2 + an.rnd() * 8;
          continue;
        }
        const heading = Math.atan2(-dz, dx);
        let diff = heading - an.mesh.rotation.y;
        diff = Math.atan2(Math.sin(diff), Math.cos(diff));
        an.mesh.rotation.y += diff * Math.min(1, dt * 3);
        const step = Math.min(d, an.speed * dt);
        p.x += (dx / d) * step;
        p.z += (dz / d) * step;
        p.y = terrain.heightAt(p.x, p.z);
      }
      for (const herd of herds.values()) {
        if (!herd.inst) continue;
        herd.animals.forEach((an, i) => {
          an.mesh.updateMatrix();
          herd.inst.setMatrixAt(i, an.mesh.matrix);
          const w = herd.walk[i], a = an.mesh.rotation.y;
          w.x = an.walking;
          w.z = Math.cos(a);
          w.w = Math.sin(a);
        });
        herd.inst.instanceMatrix.needsUpdate = true;
      }
    },
  };
}
