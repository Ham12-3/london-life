// Prepares every ordinary building (landmarks have their own models) for modelling in Blender:
// outline, height, doorways, window style and, for pitched roofs, the straight skeleton.
//
//   node tools/blender_world/prepare.mjs     -> work/blender/buildings.json
//
// Uses the same rules as src/buildings.js and src/world.js, so Blender and the web app agree.
// Output is in Blender axes: x east, y north (world -z), z up; rings counter-clockwise.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

globalThis.self ??= globalThis;
globalThis.window ??= globalThis;
const require = createRequire(import.meta.url);
const { SkeletonBuilder } = require("straight-skeleton");

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const world = JSON.parse(fs.readFileSync(path.join(root, "public/world.json"), "utf8"));
const landmarks = JSON.parse(fs.readFileSync(path.join(root, "public/assets/landmarks/landmarks.json"), "utf8"));
const replaced = new Set(landmarks.flatMap((l) => l.replaces));

const DOOR_WIDTH = 2.4;
const WALL_PALETTE = [0x9c5b43, 0xb36b4f, 0xd8cdb8, 0xe8e2d4, 0x8a7f72, 0xc9b28c, 0x7d6a5a];
const ZOO_PALETTE = [0xe9e4d6, 0xd9c7a3, 0xb7c4b0, 0xcfd6d8, 0xa98c6a];
const WALL_FINISH = { 0x9c5b43: "brick_red", 0xb36b4f: "brick_red", 0x7d6a5a: "brick_buff", 0x8a7f72: "brick_buff" };

function fnv(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}
const area = (r) => r.slice(0, -1).reduce((s, p, i) => s + p[0] * r[i + 1][1] - r[i + 1][0] * p[1], 0) / 2;

function offsetRing(ring, d) {
  const pts = ring.slice(0, -1), n = pts.length, out = [];
  for (let i = 0; i < n; i++) {
    const p = pts[(i + n - 1) % n], c = pts[i], q = pts[(i + 1) % n];
    const e1 = [c[0] - p[0], c[1] - p[1]], e2 = [q[0] - c[0], q[1] - c[1]];
    const l1 = Math.hypot(...e1) || 1, l2 = Math.hypot(...e2) || 1;
    const n1 = [e1[1] / l1, -e1[0] / l1], n2 = [e2[1] / l2, -e2[0] / l2];
    const k = d / Math.max(1 + n1[0] * n2[0] + n1[1] * n2[1], 0.25);
    out.push([c[0] + (n1[0] + n2[0]) * k, c[1] + (n1[1] + n2[1]) * k]);
  }
  return [...out, out[0]];
}

function simplify(ring, tol = 0.12) {
  let pts = ring.slice(0, -1);
  for (let pass = 0; pass < 3; pass++) {
    const keep = [];
    for (let i = 0; i < pts.length; i++) {
      const a = pts[(i + pts.length - 1) % pts.length], b = pts[i], c = pts[(i + 1) % pts.length];
      const ab = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const cross = Math.abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / (Math.hypot(c[0] - a[0], c[1] - a[1]) || 1);
      if (ab > tol && cross > tol * 0.4) keep.push(b);
    }
    if (keep.length < 3) break;
    pts = keep;
  }
  return [...pts, pts[0]];
}

// Doorways for zoo buildings with none mapped: the edge facing the nearest footpath (as world.js).
const walkways = world.paths.filter((p) => p.kind !== "road" && !p.tunnel).map((p) => p.pts);
function nearestPathDist(x, z) {
  let bd = Infinity;
  for (const pts of walkways)
    for (let i = 0; i < pts.length - 1; i++) {
      const [ax, az] = pts[i], [bx, bz] = pts[i + 1];
      const dx = bx - ax, dz = bz - az;
      const t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / (dx * dx + dz * dz || 1e-9)));
      bd = Math.min(bd, (ax + t * dx - x) ** 2 + (az + t * dz - z) ** 2);
    }
  return Math.sqrt(bd);
}

await SkeletonBuilder.init();
const out = [];
let pitched = 0;
for (const [bi, b] of world.buildings.entries()) {
  if (replaced.has(b.name)) continue;
  const id = b.name || `b${bi}`;
  const r = fnv(id) / 4294967296;
  const palette = b.inZoo ? ZOO_PALETTE : WALL_PALETTE;
  const color = palette[fnv(id) % palette.length];
  const house = !b.inZoo && b.kind !== "garages" && b.kind !== "service";
  let doors = b.inZoo ? [...b.doors] : [];
  if (b.inZoo && doors.length === 0) {
    let best = null, bd = Infinity;
    for (let i = 0; i < b.pts.length - 1; i++) {
      const [ax, az] = b.pts[i], [bx, bz] = b.pts[i + 1];
      if (Math.hypot(bx - ax, bz - az) < DOOR_WIDTH + 0.6) continue;
      const d = nearestPathDist((ax + bx) / 2, (az + bz) / 2);
      if (d < bd) { bd = d; best = [(ax + bx) / 2, (az + bz) / 2]; }
    }
    if (best) doors.push(best);
  }
  let ring = b.pts.map(([x, z]) => [+x.toFixed(3), +(-z).toFixed(3)]);
  if (area(ring) < 0) ring = ring.reverse();
  const a = Math.abs(area(ring));
  // Roof choice, as src/buildings.js.
  let pitch = 0, cover = "slate", maxRise = 5;
  if (house && a < 2500) pitch = 34;
  else if (b.kind === "pavilion") { pitch = 38; cover = "tiles"; }
  else if (b.inZoo && a < 90) { pitch = 30; cover = r < 0.5 ? "tiles" : "slate"; maxRise = 3; }
  else if (b.inZoo && a < 700 && r < 0.4) { pitch = 24; cover = "tiles"; maxRise = 3.5; }
  let roof = null;
  if (pitch) {
    try {
      const sk = SkeletonBuilder.buildFromPolygon([offsetRing(simplify(ring), 0.35)]);
      if (sk) {
        const maxT = Math.max(...sk.vertices.map((v) => v[2]));
        let slope = Math.tan((pitch * Math.PI) / 180);
        if (maxT * slope > maxRise) slope = maxRise / maxT;
        if (slope >= Math.tan((12 * Math.PI) / 180)) { roof = { cover, slope, vertices: sk.vertices, polygons: sk.polygons }; pitched++; }
      }
    } catch { /* irregular outline: flat roof */ }
  }
  out.push({
    id, name: b.name || null, h: b.h, inZoo: b.inZoo, house, ring,
    doors: doors.map(([x, z]) => [x, -z]),
    finish: b.inZoo ? "render" : WALL_FINISH[color] || "render",
    paint: color, windows: house ? "sash" : r > 0.33 ? "wide" : "none", r, roof,
  });
}
const dest = path.join(root, "work/blender/buildings.json");
fs.mkdirSync(path.dirname(dest), { recursive: true });
fs.writeFileSync(dest, JSON.stringify(out));
console.log(`${out.length} buildings (${pitched} with pitched roofs) -> ${path.relative(root, dest)}`);
