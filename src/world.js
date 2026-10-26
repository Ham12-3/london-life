// Builds the zoo scene from world.json (generated from OpenStreetMap by tools/build_world.py)
// and the collision data the player walks against.
import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { pbr } from "./materials.js";
import { waterMaterial } from "./water.js";
import { BuildingDetail } from "./buildings.js";

// Surfaces: Poly Haven texture set, metres per repeat, tint. `grass` (0..1) is how densely the
// wind-blown grass grows there (see grass.js).
export const GROUND_STYLE = {
  park: { tex: "sparse_grass", tile: 3, colorize: [0.075, 0.13, 0.03], y: 0.01, grass: 1 },
  grass: { tex: "sparse_grass", tile: 3, colorize: [0.075, 0.13, 0.03], y: 0.02, grass: 1 },
  garden: { tex: "sparse_grass", tile: 3, colorize: [0.07, 0.12, 0.03], y: 0.025, grass: 0.8 },
  wood: { tex: "forest_floor", tile: 3, tint: 0xffffff, y: 0.02, grass: 0.25 },
  scrub: { tex: "forest_floor", tile: 3, tint: 0xd8e0c0, y: 0.03, grass: 0.5 },
  pitch: { tex: "sparse_grass", tile: 3, colorize: [0.08, 0.14, 0.035], y: 0.03, grass: 0.9 },
  playground: { tex: "park_dirt", tile: 3, tint: 0xffffff, y: 0.03, grass: 0 },
  enclosure: { tex: "park_dirt", tile: 3, tint: 0xffffff, y: 0.035, grass: 0.35 },
  sand: { tex: "coast_sand_01", tile: 3, tint: 0xffffff, y: 0.04, grass: 0 },
  rock: { tex: "aerial_rocks_02", tile: 4, tint: 0xffffff, y: 0.045, grass: 0 },
  paved: { tex: "concrete_pavement", tile: 3, tint: 0xffffff, y: 0.03, grass: 0 },
};
export const PATH_STYLE = {
  road: { tex: "asphalt_02", tile: 4, tint: 0xb0b0b0, y: 0.06 },
  footway: { tex: "concrete_pavement", tile: 3, tint: 0xf0ece4, y: 0.07 },
  path: { tex: "gravel_ground_01", tile: 2.5, tint: 0xffffff, y: 0.07 },
  pedestrian: { tex: "concrete_pavement", tile: 3, tint: 0xffffff, y: 0.07 },
  steps: { tex: "precast_stone_paving", tile: 2, tint: 0xffffff, y: 0.075 },
  corridor: { tex: "concrete_floor_02", tile: 3, tint: 0xffffff, y: 0.1 },
  cycleway: { tex: "asphalt_02", tile: 4, tint: 0xd08070, y: 0.065 },
};
const WALL_PALETTE = [0x9c5b43, 0xb36b4f, 0xd8cdb8, 0xe8e2d4, 0x8a7f72, 0xc9b28c, 0x7d6a5a];
const ZOO_PALETTE = [0xe9e4d6, 0xd9c7a3, 0xb7c4b0, 0xcfd6d8, 0xa98c6a];
// Wall finish by paint colour: red brick, buff London stock brick, or painted render tinted that colour.
const WALL_FINISH = { 0x9c5b43: "brick_red", 0xb36b4f: "brick_red", 0x7d6a5a: "brick_buff", 0x8a7f72: "brick_buff" };
const WALL_MATERIALS = {
  brick_red: () => pbr("brick_wall_02", { tile: 2 }),
  brick_buff: () => pbr("brick_wall_003", { tile: 2 }),
  render: () => pbr("white_stucco", { tile: 3, vertexTint: true, normalScale: 0.6 }),
};
const DOOR_WIDTH = 2.4;
const DOOR_HEIGHT = 2.7;
const WALL_THICKNESS = 0.3;
const CELL = 8;

// ---------- geometry helpers ----------

function flatShape(pts, y) {
  const shape = new THREE.Shape(pts.map(([x, z]) => new THREE.Vector2(x, -z)));
  const g = new THREE.ShapeGeometry(shape);
  g.rotateX(-Math.PI / 2);
  g.translate(0, y, 0);
  return g;
}

function ribbon(pts, width, y, joints = true) {
  const pos = [], nrm = [], uv = [], idx = [];
  const half = width / 2;
  let run = 0;
  for (let i = 0; i < pts.length - 1; i++) {
    const [ax, az] = pts[i], [bx, bz] = pts[i + 1];
    const len = Math.hypot(bx - ax, bz - az);
    if (len < 1e-3) continue;
    const nx = (-(bz - az) / len) * half, nz = ((bx - ax) / len) * half;
    const base = pos.length / 3;
    pos.push(ax - nx, y, az - nz, ax + nx, y, az + nz, bx + nx, y, bz + nz, bx - nx, y, bz - nz);
    for (let k = 0; k < 4; k++) nrm.push(0, 1, 0);
    uv.push(0, run, 1, run, 1, run + len, 0, run + len);
    idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
    run += len;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("normal", new THREE.Float32BufferAttribute(nrm, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx);
  const parts = [g];
  if (joints) {
    for (const [x, z] of pts) {
      const c = new THREE.CircleGeometry(half, 10);
      c.rotateX(-Math.PI / 2);
      c.translate(x, y, z);
      parts.push(c.toNonIndexed());
    }
    return mergeGeometries([g.toNonIndexed(), ...parts.slice(1)]);
  }
  return g;
}

const nonIndexed = (g) => (g.index ? g.toNonIndexed() : g);

function wallBox(ax, az, bx, bz, y0, y1, thickness) {
  const len = Math.hypot(bx - ax, bz - az);
  const g = new THREE.BoxGeometry(len, y1 - y0, thickness);
  g.rotateY(-Math.atan2(bz - az, bx - ax));
  g.translate((ax + bx) / 2, (y0 + y1) / 2, (az + bz) / 2);
  return g;
}

function paint(g, color) {
  const c = new THREE.Color(color);
  const n = g.attributes.position.count;
  const arr = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) arr.set([c.r, c.g, c.b], i * 3);
  g.setAttribute("color", new THREE.BufferAttribute(arr, 3));
  return g;
}

function hash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

function bbox(pts) {
  let minX = Infinity, minZ = Infinity, maxX = -Infinity, maxZ = -Infinity;
  for (const [x, z] of pts) {
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (z < minZ) minZ = z;
    if (z > maxZ) maxZ = z;
  }
  return { minX, minZ, maxX, maxZ };
}

export function pointInPoly(pts, x, z) {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, zi] = pts[i], [xj, zj] = pts[j];
    if (zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi + 1e-12) + xi) inside = !inside;
  }
  return inside;
}

function distToSeg(px, pz, ax, az, bx, bz) {
  const dx = bx - ax, dz = bz - az;
  const l2 = dx * dx + dz * dz || 1e-9;
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (pz - az) * dz) / l2));
  return Math.hypot(px - (ax + t * dx), pz - (az + t * dz));
}

function distToLine(pts, x, z) {
  let d = Infinity;
  for (let i = 0; i < pts.length - 1; i++) d = Math.min(d, distToSeg(x, z, ...pts[i], ...pts[i + 1]));
  return d;
}

// Split edge a→b into solid intervals, leaving a doorway centred on each opening that lies on it.
function solidIntervals(a, b, openings, width) {
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
  const cuts = [];
  for (const [ox, oz] of openings) {
    if (distToSeg(ox, oz, a[0], a[1], b[0], b[1]) > 0.6) continue;
    const t = ((ox - a[0]) * (b[0] - a[0]) + (oz - a[1]) * (b[1] - a[1])) / (len * len);
    const half = width / 2 / len;
    cuts.push([Math.max(0, t - half), Math.min(1, t + half)]);
  }
  cuts.sort((p, q) => p[0] - q[0]);
  const solid = [];
  let t0 = 0;
  for (const [c0, c1] of cuts) {
    if (c0 > t0) solid.push([t0, c0]);
    t0 = Math.max(t0, c1);
  }
  if (t0 < 1) solid.push([t0, 1]);
  const lerp = (t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  return {
    solid: solid.filter(([s, e]) => (e - s) * len > 0.05).map(([s, e]) => [lerp(s), lerp(e)]),
    gaps: cuts.map(([s, e]) => [lerp(s), lerp(e)]),
  };
}

// ---------- collision ----------

export class Collision {
  constructor() {
    this.grid = new Map();
    this.water = [];
    this.bridges = [];
  }
  key(cx, cz) {
    return cx * 100003 + cz;
  }
  insert(item, minX, minZ, maxX, maxZ) {
    for (let cx = Math.floor(minX / CELL); cx <= Math.floor(maxX / CELL); cx++)
      for (let cz = Math.floor(minZ / CELL); cz <= Math.floor(maxZ / CELL); cz++) {
        const k = this.key(cx, cz);
        if (!this.grid.has(k)) this.grid.set(k, []);
        this.grid.get(k).push(item);
      }
  }
  addSegment(ax, az, bx, bz) {
    this.insert({ seg: [ax, az, bx, bz] }, Math.min(ax, bx), Math.min(az, bz), Math.max(ax, bx), Math.max(az, bz));
  }
  addCircle(x, z, r) {
    this.insert({ circle: [x, z, r] }, x - r, z - r, x + r, z + r);
  }
  nearby(x, z) {
    const out = new Set();
    const cx = Math.floor(x / CELL), cz = Math.floor(z / CELL);
    for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++) for (const it of this.grid.get(this.key(cx + i, cz + j)) || []) out.add(it);
    return out;
  }
  // Push a circle of radius r at (x, z) out of every nearby wall, fence and trunk.
  resolve(x, z, r) {
    for (let iter = 0; iter < 3; iter++) {
      for (const it of this.nearby(x, z)) {
        let cx, cz, rr;
        if (it.seg) {
          const [ax, az, bx, bz] = it.seg;
          const dx = bx - ax, dz = bz - az;
          const t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / (dx * dx + dz * dz || 1e-9)));
          cx = ax + t * dx; cz = az + t * dz; rr = r + WALL_THICKNESS / 2;
        } else {
          [cx, cz] = it.circle; rr = r + it.circle[2];
        }
        const d = Math.hypot(x - cx, z - cz);
        if (d < rr && d > 1e-6) {
          x = cx + ((x - cx) / d) * rr;
          z = cz + ((z - cz) / d) * rr;
        }
      }
    }
    return [x, z];
  }
  inWater(x, z) {
    const wet = this.water.some((w) =>
      w.line ? distToLine(w.line, x, z) < w.w / 2
        : x >= w.bb.minX && x <= w.bb.maxX && z >= w.bb.minZ && z <= w.bb.maxZ && pointInPoly(w.pts, x, z));
    if (!wet) return false;
    return !this.bridges.some((b) => (b.line ? distToLine(b.line, x, z) < b.w / 2 : pointInPoly(b.pts, x, z)));
  }
}

// ---------- textures ----------

function railingTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  g.fillStyle = "#1f2a22";
  for (let x = 2; x < 64; x += 11) g.fillRect(x, 4, 3, 60);
  g.fillRect(0, 4, 64, 4);
  g.fillRect(0, 40, 64, 3);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function makeLabel(text, { size = 28, color = "#fff", bg = "rgba(20,30,25,0.72)" } = {}) {
  const c = document.createElement("canvas");
  const g = c.getContext("2d");
  g.font = `600 ${size}px system-ui, sans-serif`;
  const w = Math.ceil(g.measureText(text).width) + 24;
  c.width = w;
  c.height = size + 18;
  g.font = `600 ${size}px system-ui, sans-serif`;
  g.fillStyle = bg;
  g.beginPath();
  g.roundRect(0, 0, c.width, c.height, 10);
  g.fill();
  g.fillStyle = color;
  g.textBaseline = "middle";
  g.fillText(text, 12, c.height / 2 + 1);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthWrite: false, transparent: true }));
  s.scale.set(c.width / 60, c.height / 60, 1);
  return s;
}

// ---------- world ----------

export function buildWorld(world, scene, { hiddenBuildings = new Set(), capturedPlaces = new Set() } = {}) {
  const col = new Collision();
  const labels = [];

  // Places with a captured splat bring their own ground, water and trees; the simulated ones
  // inside them are skipped so they don't cover the splat (collision is kept).
  const captured = [...world.areas, ...world.buildings]
    .filter((p) => capturedPlaces.has(p.name))
    .map((p) => ({ pts: p.pts, bb: bbox(p.pts) }));
  const inCaptured = (x, z) => captured.some((c) =>
    x >= c.bb.minX && x <= c.bb.maxX && z >= c.bb.minZ && z <= c.bb.maxZ && pointInPoly(c.pts, x, z));
  const centreOf = (pts) => [pts.reduce((s, p) => s + p[0], 0) / pts.length, pts.reduce((s, p) => s + p[1], 0) / pts.length];

  // Base ground: Regent's Park lawns stretching to the fog.
  const base = new THREE.Mesh(new THREE.PlaneGeometry(4000, 4000), pbr("sparse_grass", { tile: 3, colorize: [0.075, 0.13, 0.03] }));
  base.rotation.x = -Math.PI / 2;
  base.receiveShadow = true;
  scene.add(base);

  // Zoo grounds are mostly paved/gravel between attractions.
  const zooGround = world.zoo.map((r) => flatShape(r, 0.005));
  if (zooGround.length) {
    const m = new THREE.Mesh(mergeGeometries(zooGround), pbr("sparse_grass", { tile: 3, colorize: [0.085, 0.12, 0.04] }));
    m.receiveShadow = true;
    scene.add(m);
  }

  // Land cover.
  const byKind = {};
  for (const gp of world.ground) {
    const st = GROUND_STYLE[gp.kind];
    if (!st || inCaptured(...centreOf(gp.pts))) continue;
    try {
      (byKind[gp.kind] ||= []).push(flatShape(gp.pts, st.y));
    } catch { /* degenerate polygon */ }
  }
  for (const [kind, geos] of Object.entries(byKind)) {
    const m = new THREE.Mesh(mergeGeometries(geos), pbr(GROUND_STYLE[kind].tex, GROUND_STYLE[kind]));
    m.receiveShadow = true;
    scene.add(m);
  }

  // Water: ponds, moats, pools and the Regent's Canal.
  const waterGeos = [];
  for (const w of world.water) {
    if (w.line) {
      waterGeos.push(nonIndexed(ribbon(w.line, w.w, 0.05)));
      col.water.push({ line: w.line, w: w.w });
    } else {
      if (!inCaptured(...centreOf(w.pts))) waterGeos.push(nonIndexed(flatShape(w.pts, 0.05)));
      col.water.push({ pts: w.pts, bb: bbox(w.pts) });
    }
  }
  if (waterGeos.length) {
    const water = new THREE.Mesh(mergeGeometries(waterGeos.map((g) => { g.deleteAttribute("uv"); return g; })),
      waterMaterial());
    water.receiveShadow = true;
    scene.add(water);
  }

  // Bridges over water.
  const bridgeGeos = [];
  for (const b of world.bridges) {
    if (b.line) bridgeGeos.push(nonIndexed(ribbon(b.line, b.w, 0.12)));
    else bridgeGeos.push(nonIndexed(flatShape(b.pts, 0.12)));
    col.bridges.push(b);
  }
  if (bridgeGeos.length) {
    const bridges = new THREE.Mesh(mergeGeometries(bridgeGeos.map((g) => { g.deleteAttribute("uv"); return g; })),
      pbr("wood_planks", { tile: 2, tint: 0xd8d0c4 }));
    bridges.receiveShadow = true;
    scene.add(bridges);
  }

  // Paths and roads.
  const pathGeos = {};
  for (const p of world.paths) {
    if (p.pts.length < 2) continue;
    const kind = PATH_STYLE[p.kind] ? p.kind : "footway";
    (pathGeos[kind] ||= []).push(ribbon(p.pts, p.w, p.bridge ? 0.14 : PATH_STYLE[kind].y));
  }
  for (const [kind, geos] of Object.entries(pathGeos)) {
    const m = new THREE.Mesh(mergeGeometries(geos), pbr(PATH_STYLE[kind].tex, PATH_STYLE[kind]));
    m.receiveShadow = true;
    scene.add(m);
  }

  // Path vertices, used to pick doorways and teleport targets.
  const walkways = world.paths.filter((p) => p.kind !== "road" && !p.tunnel).map((p) => p.pts);
  const nearestPathPoint = (x, z) => {
    let best = null, bd = Infinity;
    for (const pts of walkways)
      for (let i = 0; i < pts.length - 1; i++) {
        const [ax, az] = pts[i], [bx, bz] = pts[i + 1];
        const dx = bx - ax, dz = bz - az;
        const t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / (dx * dx + dz * dz || 1e-9)));
        const px = ax + t * dx, pz = az + t * dz;
        const d = (px - x) ** 2 + (pz - z) ** 2;
        if (d < bd) { bd = d; best = [px, pz]; }
      }
    return best;
  };

  // Buildings: walls with doorways (so every zoo building can be entered), interior floor, roof.
  const wallGeos = { brick_red: [], brick_buff: [], render: [] }, roofGeos = [], floorGeos = [], ceilingGeos = [];
  const buildingInfo = [];
  const detail = new BuildingDetail();
  for (const [bi, b] of world.buildings.entries()) {
    const ring = b.pts;
    const id = b.name || `b${bi}`;
    const doors = [...b.doors];
    if (b.inZoo && doors.length === 0) {
      // No mapped entrance: open the edge facing the nearest path.
      let best = null, bd = Infinity;
      for (let i = 0; i < ring.length - 1; i++) {
        const [ax, az] = ring[i], [bx, bz] = ring[i + 1];
        if (Math.hypot(bx - ax, bz - az) < DOOR_WIDTH + 0.6) continue;
        const mx = (ax + bx) / 2, mz = (az + bz) / 2;
        const pp = nearestPathPoint(mx, mz);
        const d = pp ? Math.hypot(pp[0] - mx, pp[1] - mz) : 0;
        if (d < bd) { bd = d; best = [mx, mz]; }
      }
      if (best) doors.push(best);
    }
    const palette = b.inZoo ? ZOO_PALETTE : WALL_PALETTE;
    const color = palette[hash(id) % palette.length];
    const finish = wallGeos[b.inZoo ? "render" : WALL_FINISH[color] || "render"];
    // Buildings inside a captured enclosure are part of its splat; keep their walls for collision only.
    const hidden = hiddenBuildings.has(b.name) || inCaptured(...centreOf(ring.slice(0, -1)));
    const edges = [];
    for (let i = 0; i < ring.length - 1; i++) {
      const a = ring[i], c = ring[i + 1];
      if (Math.hypot(c[0] - a[0], c[1] - a[1]) < 0.05) continue;
      const { solid, gaps } = solidIntervals(a, c, b.inZoo ? doors : [], DOOR_WIDTH);
      edges.push({ a, c, solid, gaps });
      for (const [p, q] of solid) {
        col.addSegment(p[0], p[1], q[0], q[1]);
        if (!hidden) finish.push(paint(wallBox(p[0], p[1], q[0], q[1], 0, b.h, WALL_THICKNESS), color));
      }
      if (!hidden && b.h > DOOR_HEIGHT + 0.2)
        for (const [p, q] of gaps) finish.push(paint(wallBox(p[0], p[1], q[0], q[1], DOOR_HEIGHT, b.h, WALL_THICKNESS), color));
    }
    // Plinth, cornice or parapet, windows, door surrounds and (often) a pitched roof: see buildings.js.
    const style = hidden ? { roof: "flat", top: b.h } : detail.add(b, id, edges, finish, color);
    if (!hidden) {
      try {
        if (style.roof === "flat") roofGeos.push(paint(flatShape(ring, b.h), b.kind === "cage" ? 0x3a3f3a : 0x5c5852));
        if (b.inZoo) {
          floorGeos.push(flatShape(ring, 0.11));
          ceilingGeos.push(flatShape(ring, b.h - 0.05));
        }
      } catch { /* degenerate polygon */ }
    }
    buildingInfo.push({ name: b.name, pts: ring, bb: bbox(ring), h: b.h, inZoo: b.inZoo, doors });
    if (b.name && b.inZoo) {
      const xs = ring.map((p) => p[0]), zs = ring.map((p) => p[1]);
      const label = makeLabel(b.name, { size: 26 });
      label.position.set(xs.reduce((s, v) => s + v, 0) / xs.length, style.top + 1.4, zs.reduce((s, v) => s + v, 0) / zs.length);
      labels.push(label);
      scene.add(label);
    }
  }
  detail.build(scene);
  for (const [finish, geos] of Object.entries(wallGeos)) {
    if (!geos.length) continue;
    const walls = new THREE.Mesh(mergeGeometries(geos), WALL_MATERIALS[finish]());
    walls.castShadow = walls.receiveShadow = true;
    scene.add(walls);
  }
  const roofs = new THREE.Mesh(mergeGeometries(roofGeos), pbr("concrete_floor_02", { tile: 3, vertexTint: true, side: THREE.DoubleSide }));
  roofs.castShadow = roofs.receiveShadow = true;
  scene.add(roofs);
  if (ceilingGeos.length) {
    // Self-lit ceilings stand in for interior lighting (real lights per building cost too much).
    const ceilings = new THREE.Mesh(mergeGeometries(ceilingGeos),
      new THREE.MeshStandardMaterial({ color: 0xe9e4d8, emissive: 0x8a857a, roughness: 1, side: THREE.BackSide }));
    scene.add(ceilings);
  }
  if (floorGeos.length) {
    const floor = new THREE.Mesh(mergeGeometries(floorGeos), pbr("concrete_floor_02", { tile: 2, tint: 0xe8e0d0, roughness: 0.7 }));
    floor.receiveShadow = true;
    scene.add(floor);
  }

  // Fences, walls and hedges, with gaps wherever a path crosses them.
  const railing = railingTexture();
  const fenceGeos = [], solidBarrierGeos = [], masonryGeos = [];
  for (const br of world.barriers) {
    for (let i = 0; i < br.pts.length - 1; i++) {
      const { solid } = solidIntervals(br.pts[i], br.pts[i + 1], br.gaps, 2.2);
      for (const [p, q] of solid) {
        col.addSegment(p[0], p[1], q[0], q[1]);
        const len = Math.hypot(q[0] - p[0], q[1] - p[1]);
        if (br.kind === "fence") {
          const g = new THREE.PlaneGeometry(len, br.h);
          const uv = g.attributes.uv;
          for (let k = 0; k < uv.count; k++) uv.setX(k, uv.getX(k) * len);
          g.rotateY(-Math.atan2(q[1] - p[1], q[0] - p[0]));
          g.translate((p[0] + q[0]) / 2, br.h / 2, (p[1] + q[1]) / 2);
          fenceGeos.push(g);
        } else {
          if (br.kind === "hedge") solidBarrierGeos.push(paint(wallBox(p[0], p[1], q[0], q[1], 0, br.h, 0.9), 0x3f6b2f));
          else masonryGeos.push(wallBox(p[0], p[1], q[0], q[1], 0, br.h, 0.35));
        }
      }
    }
  }
  if (fenceGeos.length) {
    const fences = new THREE.Mesh(mergeGeometries(fenceGeos),
      new THREE.MeshStandardMaterial({ map: railing, alphaTest: 0.5, side: THREE.DoubleSide, roughness: 0.6, metalness: 0.4 }));
    fences.castShadow = true;
    scene.add(fences);
  }
  if (solidBarrierGeos.length) {
    const m = new THREE.Mesh(mergeGeometries(solidBarrierGeos), new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.95 }));
    m.castShadow = m.receiveShadow = true;
    scene.add(m);
  }
  if (masonryGeos.length) {
    const m = new THREE.Mesh(mergeGeometries(masonryGeos), pbr("brick_wall_003", { tile: 2 }));
    m.castShadow = m.receiveShadow = true;
    scene.add(m);
  }

  // Trees: trunks are solid; the trees themselves are drawn by trees.js.
  const trees = world.trees.filter(([x, z]) => !inCaptured(x, z));
  for (const [x, z] of trees) col.addCircle(x, z, 0.4);
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3();

  // Street furniture.
  const furnitureKinds = {
    bench: { geo: new THREE.BoxGeometry(1.8, 0.45, 0.6).translate(0, 0.45, 0), color: 0x6b4a2f, r: 0.5 },
    picnic: { geo: new THREE.BoxGeometry(1.8, 0.75, 1.5).translate(0, 0.38, 0), color: 0x7a5a3a, r: 0.8 },
    bin: { geo: new THREE.CylinderGeometry(0.3, 0.3, 0.9, 10).translate(0, 0.45, 0), color: 0x24382a, r: 0.3 },
    lamp: { geo: new THREE.CylinderGeometry(0.07, 0.1, 4.2, 6).translate(0, 2.1, 0), color: 0x1d2420, r: 0.15 },
    water: { geo: new THREE.CylinderGeometry(0.25, 0.3, 1, 8).translate(0, 0.5, 0), color: 0x3c4e5a, r: 0.3 },
    info: { geo: new THREE.BoxGeometry(1.2, 2, 0.15).translate(0, 1, 0), color: 0x2f5d50, r: 0.3 },
  };
  for (const [kind, spec] of Object.entries(furnitureKinds)) {
    const items = world.furniture.filter((f) => f.kind === kind);
    if (!items.length) continue;
    const mesh = new THREE.InstancedMesh(spec.geo, new THREE.MeshStandardMaterial({ color: spec.color, roughness: 0.8 }), items.length);
    items.forEach((f, i) => {
      m4.compose(p.set(f.x, 0, f.z), q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), (hash(`${f.x}${f.z}`) % 4) * (Math.PI / 2)), s.set(1, 1, 1));
      mesh.setMatrixAt(i, m4);
      col.addCircle(f.x, f.z, spec.r);
    });
    mesh.castShadow = true;
    scene.add(mesh);
  }

  // Labels for attractions, enclosures and named points of interest.
  for (const a of world.areas) {
    const label = makeLabel(a.name, { size: 30, bg: "rgba(26,58,40,0.8)" });
    label.position.set(a.c[0], 4.5, a.c[1]);
    labels.push(label);
    scene.add(label);
  }
  for (const poi of world.pois) {
    const label = makeLabel(poi.name, { size: 22, bg: "rgba(40,40,40,0.7)" });
    label.position.set(poi.x, 3, poi.z);
    labels.push(label);
    scene.add(label);
  }

  const areas = [...world.areas].sort((x, y) => x.a - y.a).map((a) => ({ ...a, bb: bbox(a.pts) }));
  const whereAmI = (x, z) => {
    const inside = buildingInfo.find((b) => b.name && x >= b.bb.minX && x <= b.bb.maxX && z >= b.bb.minZ && z <= b.bb.maxZ && pointInPoly(b.pts, x, z));
    const area = areas.find((a) => x >= a.bb.minX && x <= a.bb.maxX && z >= a.bb.minZ && z <= a.bb.maxZ && pointInPoly(a.pts, x, z));
    const inZoo = world.zoo.some((r) => pointInPoly(r, x, z));
    return { building: inside?.name || null, area: area?.name || null, inZoo };
  };

  return { collision: col, labels, buildings: buildingInfo, nearestPathPoint, whereAmI, trees };
}
