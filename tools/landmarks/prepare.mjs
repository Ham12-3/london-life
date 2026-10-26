// Gathers the real OSM footprints of the zoo's landmark buildings and works out their hipped
// roofs (straight skeletons), for tools/landmarks/build.py to model in Blender.
//
//   node tools/landmarks/prepare.mjs        -> work/landmarks/input.json
//
// Coordinates are converted to Blender's: x east, y north (world -z), z up, in metres, relative to
// each landmark's own origin (the centre of its main footprint).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

// The straight-skeleton bundle is built for browsers: give it the globals it checks for.
globalThis.self ??= globalThis;
globalThis.window ??= globalThis;
const require = createRequire(import.meta.url);
const { SkeletonBuilder } = require("straight-skeleton");

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const world = JSON.parse(fs.readFileSync(path.join(root, "public/world.json"), "utf8"));

// id, footprint source, roofs to skeletonise: [footprint index, eave height, pitch, overhang]
const LANDMARKS = [
  { id: "penguin-pool", building: "Lubetkin Pool" },
  { id: "snowdon-aviary", area: "Monkey Valley" },
  { id: "casson-pavilion", building: "Casson Pavilion" },
  { id: "clock-tower", building: "Clock Tower", roofs: [[0, 4.6, 32, 0.35]] },
  { id: "giraffe-house", building: "The Giraffe House", roofs: [[0, 8.0, 26, 0.45]] },
  { id: "raven-cage", building: "Raven Cage" },
  { id: "blackburn-pavilion", building: "Blackburn Pavilion", roofs: [[0, 6.6, 30, 0.4]] },
];

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

// Drop near-duplicate and collinear points: the skeleton is cleaner and so is the model.
function simplify(ring, tol = 0.15) {
  let pts = ring.slice(0, -1);
  for (let pass = 0; pass < 3; pass++) {
    const keep = [];
    for (let i = 0; i < pts.length; i++) {
      const a = pts[(i + pts.length - 1) % pts.length], b = pts[i], c = pts[(i + 1) % pts.length];
      const ab = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const cross = Math.abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / (Math.hypot(c[0] - a[0], c[1] - a[1]) || 1);
      if (ab > tol && cross > tol * 0.5) keep.push(b);
    }
    pts = keep;
  }
  return [...pts, pts[0]];
}

await SkeletonBuilder.init();
const out = [];
for (const L of LANDMARKS) {
  const src = L.area ? world.areas.filter((a) => a.name === L.area) : world.buildings.filter((b) => b.name === L.building);
  if (!src.length) { console.warn(`missing ${L.building || L.area}`); continue; }
  src.sort((a, b) => Math.abs(area(b.pts)) - Math.abs(area(a.pts))); // main footprint first
  const main = src[0].pts;
  const cx = main.slice(0, -1).reduce((s, p) => s + p[0], 0) / (main.length - 1);
  const cz = main.slice(0, -1).reduce((s, p) => s + p[1], 0) / (main.length - 1);
  const footprints = src.map((s) => {
    let r = s.pts.map(([x, z]) => [+(x - cx).toFixed(3), +(-(z - cz)).toFixed(3)]);
    if (area(r) < 0) r = r.reverse(); // counter-clockwise in Blender's x/y
    return r;
  });
  const roofs = (L.roofs || []).map(([fi, eave, pitch, overhang]) => {
    const ring = offsetRing(simplify(footprints[fi]), overhang);
    const sk = SkeletonBuilder.buildFromPolygon([ring]);
    if (!sk) { console.warn(`${L.id}: no skeleton`); return null; }
    return { eave, slope: Math.tan((pitch * Math.PI) / 180), vertices: sk.vertices, polygons: sk.polygons };
  }).filter(Boolean);
  out.push({ id: L.id, name: L.building || L.area, origin: [cx, cz], footprints, roofs });
  console.log(`${L.id}: ${footprints.length} footprint(s), ${roofs.length} roof(s)`);
}
const dest = path.join(root, "work/landmarks/input.json");
fs.mkdirSync(path.dirname(dest), { recursive: true });
fs.writeFileSync(dest, JSON.stringify(out));
console.log(`wrote ${path.relative(root, dest)}`);
