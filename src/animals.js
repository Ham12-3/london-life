// Placeholder animals that wander inside their real enclosure outlines.
// Each species is swapped for an image-to-3D model once one is listed in public/assets/manifest.json.
import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { pointInPoly } from "./world.js";

// Keyword in the OSM area name -> species look. len/height in metres.
const SPECIES = [
  { match: /gorilla/i, label: "Western lowland gorilla", shape: "ape", len: 0.9, height: 1.6, color: 0x2b2b2b, count: 4 },
  { match: /lion/i, label: "Asiatic lion", shape: "quad", len: 2.0, height: 1.1, color: 0xc89b5a, count: 3 },
  { match: /tiger/i, label: "Sumatran tiger", shape: "quad", len: 2.1, height: 1.0, color: 0xd9822b, count: 2 },
  { match: /giraffe/i, label: "Giraffe", shape: "quad", len: 2.2, height: 1.9, neck: 2.2, color: 0xd8a55a, count: 3 },
  { match: /zebra/i, label: "Zebra", shape: "quad", len: 1.9, height: 1.3, color: 0xe8e8e8, count: 3 },
  { match: /okapi/i, label: "Okapi", shape: "quad", len: 1.9, height: 1.5, neck: 0.6, color: 0x5a3324, count: 2 },
  { match: /warthog/i, label: "Warthog", shape: "quad", len: 1.2, height: 0.7, color: 0x6b5a4a, count: 3 },
  { match: /hippo/i, label: "Pygmy hippo", shape: "quad", len: 1.6, height: 0.8, color: 0x5d4a52, count: 2 },
  { match: /camel/i, label: "Bactrian camel", shape: "quad", len: 2.4, height: 1.9, neck: 0.8, color: 0xa47c4f, count: 2 },
  { match: /alpaca|llama/i, label: "Alpaca", shape: "quad", len: 1.3, height: 1.0, neck: 0.9, color: 0xe2d2b5, count: 3 },
  { match: /ostrich|emu/i, label: "Ostrich", shape: "bird", len: 1.0, height: 1.3, neck: 0.9, color: 0x2e2a28, count: 3 },
  { match: /penguin/i, label: "Humboldt penguin", shape: "penguin", len: 0.3, height: 0.6, color: 0x161616, count: 14 },
  { match: /flamingo/i, label: "Flamingo", shape: "bird", len: 0.6, height: 0.9, neck: 0.6, color: 0xf08aa0, count: 10 },
  { match: /pelican/i, label: "Pelican", shape: "bird", len: 0.9, height: 0.8, neck: 0.4, color: 0xf2f2ee, count: 4 },
  { match: /wallab|outback/i, label: "Wallaby", shape: "quad", len: 0.8, height: 0.7, color: 0x8b7a68, count: 4 },
  { match: /meerkat|mongoose/i, label: "Meerkat", shape: "penguin", len: 0.2, height: 0.35, color: 0xb59a74, count: 8 },
  { match: /otter/i, label: "Otter", shape: "quad", len: 0.9, height: 0.35, color: 0x4a3a2c, count: 3 },
  { match: /coati/i, label: "Coati", shape: "quad", len: 0.8, height: 0.4, color: 0x7a5a3a, count: 4 },
  { match: /deer/i, label: "Chinese water deer", shape: "quad", len: 1.0, height: 0.6, color: 0x9a7a54, count: 3 },
  { match: /goat|farmyard/i, label: "Pygmy goat", shape: "quad", len: 0.8, height: 0.6, color: 0x6b5f55, count: 4 },
  { match: /pig/i, label: "Mangalitsa pig", shape: "quad", len: 1.1, height: 0.7, color: 0xb88a55, count: 3 },
  { match: /lemur/i, label: "Ring-tailed lemur", shape: "ape", len: 0.4, height: 0.5, color: 0x9a9a9a, count: 6 },
  { match: /monkey|macaque|mangabey|langur|gibbon|titi|tamarin/i, label: "Monkey", shape: "ape", len: 0.45, height: 0.7, color: 0x5a4636, count: 5 },
];

function legs(group, mat, len, legH, width) {
  const geo = new THREE.CylinderGeometry(width, width * 0.8, legH, 6);
  for (const [dx, dz] of [[0.35, 0.22], [0.35, -0.22], [-0.35, 0.22], [-0.35, -0.22]]) {
    const leg = new THREE.Mesh(geo, mat);
    leg.position.set(dx * len, legH / 2, dz * len * 0.6);
    leg.castShadow = true;
    group.add(leg);
  }
}

function makeAnimal(sp) {
  const g = new THREE.Group();
  const mat = new THREE.MeshStandardMaterial({ color: sp.color, roughness: 0.9 });
  const add = (geo, x, y, z, m = mat) => {
    const mesh = new THREE.Mesh(geo, m);
    mesh.position.set(x, y, z);
    mesh.castShadow = true;
    g.add(mesh);
    return mesh;
  };
  if (sp.shape === "quad") {
    const legH = sp.height * 0.55;
    const bodyR = sp.height * 0.25;
    const body = add(new THREE.CapsuleGeometry(bodyR, sp.len - bodyR * 2, 4, 10), 0, legH + bodyR * 0.6, 0);
    body.rotation.z = Math.PI / 2;
    legs(g, mat, sp.len, legH + bodyR * 0.3, Math.max(0.04, bodyR * 0.28));
    const neckLen = sp.neck || 0.15;
    const neck = add(new THREE.CylinderGeometry(bodyR * 0.35, bodyR * 0.5, neckLen, 8), sp.len / 2, legH + bodyR + neckLen / 2, 0);
    neck.rotation.z = -0.25;
    add(new THREE.SphereGeometry(bodyR * 0.65, 10, 8), sp.len / 2 + 0.15, legH + bodyR + neckLen, 0);
  } else if (sp.shape === "ape") {
    add(new THREE.CapsuleGeometry(sp.height * 0.22, sp.height * 0.35, 4, 10), 0, sp.height * 0.45, 0);
    add(new THREE.SphereGeometry(sp.height * 0.15, 10, 8), 0.05, sp.height * 0.9, 0);
    legs(g, mat, sp.len, sp.height * 0.3, sp.height * 0.06);
  } else if (sp.shape === "penguin") {
    add(new THREE.CapsuleGeometry(sp.height * 0.22, sp.height * 0.45, 4, 10), 0, sp.height * 0.45, 0);
    add(new THREE.SphereGeometry(sp.height * 0.2, 10, 8, 0, Math.PI), 0.05, sp.height * 0.45, 0,
      new THREE.MeshStandardMaterial({ color: sp.color === 0x161616 ? 0xf3f3f3 : 0xd8c4a0 })).rotation.y = -Math.PI / 2;
  } else {
    const legH = sp.height * 0.5;
    const body = add(new THREE.SphereGeometry(sp.len * 0.35, 10, 8), 0, legH + sp.len * 0.2, 0);
    body.scale.set(1.3, 0.8, 0.9);
    const neck = add(new THREE.CylinderGeometry(0.04, 0.06, sp.neck, 6), sp.len * 0.3, legH + sp.len * 0.2 + sp.neck / 2, 0);
    neck.rotation.z = -0.15;
    add(new THREE.SphereGeometry(0.09, 8, 6), sp.len * 0.38, legH + sp.len * 0.2 + sp.neck, 0);
    const legGeo = new THREE.CylinderGeometry(0.025, 0.025, legH, 5);
    add(legGeo, 0, legH / 2, 0.08);
    add(legGeo, 0, legH / 2, -0.08);
  }
  return flatten(g);
}

// One mesh per animal (parts baked in, colours per vertex): a hundred animals stay a hundred draw calls
// per pass instead of six hundred.
const animalMaterial = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.9 });
function flatten(group) {
  const parts = group.children.map((m) => {
    m.updateMatrix();
    const geo = m.geometry.clone().applyMatrix4(m.matrix);
    const n = geo.attributes.position.count, c = m.material.color, rgb = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) rgb.set([c.r, c.g, c.b], i * 3);
    geo.setAttribute("color", new THREE.BufferAttribute(rgb, 3));
    return geo;
  });
  const mesh = new THREE.Mesh(mergeGeometries(parts), animalMaterial);
  mesh.castShadow = true;
  return mesh;
}

function randomPointIn(area, rnd) {
  for (let i = 0; i < 40; i++) {
    const x = area.bb.minX + rnd() * (area.bb.maxX - area.bb.minX);
    const z = area.bb.minZ + rnd() * (area.bb.maxZ - area.bb.minZ);
    if (pointInPoly(area.pts, x, z)) return [x, z];
  }
  return area.c;
}

export function spawnAnimals(world, scene, { replacedSpecies = new Set(), capturedPlaces = new Set() } = {}) {
  let seed = 42;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const animals = [];
  for (const a of world.areas) {
    const sp = SPECIES.find((s) => s.match.test(a.name));
    // A captured splat of the enclosure already shows its animals.
    if (!sp || replacedSpecies.has(sp.label) || capturedPlaces.has(a.name)) continue;
    const xs = a.pts.map((p) => p[0]), zs = a.pts.map((p) => p[1]);
    const area = { ...a, bb: { minX: Math.min(...xs), maxX: Math.max(...xs), minZ: Math.min(...zs), maxZ: Math.max(...zs) } };
    const count = Math.max(1, Math.min(sp.count, Math.round(a.a / 40)));
    for (let i = 0; i < count; i++) {
      const mesh = makeAnimal(sp);
      const [x, z] = randomPointIn(area, rnd);
      mesh.position.set(x, 0, z);
      mesh.rotation.y = rnd() * Math.PI * 2;
      scene.add(mesh);
      animals.push({ mesh, area, species: sp, target: randomPointIn(area, rnd), wait: rnd() * 5, speed: 0.4 + sp.len * 0.3, rnd });
    }
  }
  return {
    animals,
    update(dt) {
      for (const an of animals) {
        if (an.wait > 0) { an.wait -= dt; continue; }
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
        p.y = Math.abs(Math.sin(performance.now() / 180)) * 0.03;
      }
    },
  };
}
