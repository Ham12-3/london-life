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

// id, footprint source, roofs to skeletonise: [footprint index, eave height, pitch, overhang].
// Footprints come from a named building, OSM building indices (`ids`, for unnamed ones), or an area;
// with `within`, the area's outline comes first, then every building standing inside it, and
// `roofsAll` gives each of those buildings a hipped roof.
const LANDMARKS = [
  { id: "penguin-pool", building: "Lubetkin Pool" },
  { id: "snowdon-aviary", area: "Monkey Valley" },
  { id: "casson-pavilion", building: "Casson Pavilion" },
  { id: "clock-tower", building: "Clock Tower", roofs: [[0, 4.6, 32, 0.35]] },
  { id: "giraffe-house", building: "The Giraffe House", roofs: [[0, 8.0, 26, 0.45]] },
  { id: "raven-cage", building: "Raven Cage" },
  { id: "blackburn-pavilion", building: "Blackburn Pavilion", roofs: [[0, 6.6, 30, 0.4]] },
  { id: "main-entrance", building: "London Zoo Entrance" },
  { id: "reptile-house", ids: [133], label: "Reptile House", roofs: [[0, 7.6, 24, 0.45]] },
  { id: "gorilla-kingdom", area: "Gorilla Kingdom", within: 12, roofsAll: [5.2, 22, 1.1] },
  { id: "rainforest-life", area: "Rainforest Life", within: 2 },
  { id: "land-of-the-lions", area: "Land of the Lions", within: 8 },
  { id: "tiger-territory", area: "Tiger Territory", within: 6, roofsAll: [3.4, 34, 0.9] },
  // The Mappin Terraces (1914): mapped as a cluster of bare-rock outlines behind the Mappin Pavilion.
  { id: "mappin-terraces", ground: "rock", box: [-165, -55, 0, 70], label: "Mappin Terraces" },
  { id: "guy-the-gorilla", poi: "Guy the Gorilla" },
  // Step 5: the remaining animal houses. `add` appends buildings (by name or index) to an area's
  // footprints; `pools` brings the mapped water inside the area.
  { id: "penguin-beach", area: "Penguin Beach", add: ["The Beach Hut"], pools: true },
  { id: "butterfly-paradise", ids: [132], label: "Butterfly Paradise" },
  { id: "tiny-giants", ids: [119], label: "Tiny Giants" },
  { id: "in-with-the-monkeys", area: "In with the Monkeys", add: [155, 156, 158] },
  { id: "komodo-dragon-house", ids: [27], label: "Attenborough Komodo Dragon House" },
  { id: "giants-of-the-galapagos", building: "Giants of the Galápagos" },
  { id: "gir-lion-lodges", ids: [127, 126, 171, 172, 173, 174, 175, 176, 177], label: "Gir Lion Lodges",
    roofsAll: [2.9, 24, 0.5], roofFirst: true },
  { id: "mappin-pavilion", building: "Mappin Pavilion", roofs: [[0, 6.4, 28, 0.7]] },
];

const centroid = (r) => [r.slice(0, -1).reduce((s, p) => s + p[0], 0) / (r.length - 1), r.slice(0, -1).reduce((s, p) => s + p[1], 0) / (r.length - 1)];
function inside(pts, x, z) {
  let res = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, zi] = pts[i], [xj, zj] = pts[j];
    if (zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi + 1e-12) + xi) res = !res;
  }
  return res;
}
function edgeDist(pts, x, z) {
  let d = Infinity;
  for (let i = 0; i < pts.length - 1; i++) {
    const [ax, az] = pts[i], [bx, bz] = pts[i + 1], dx = bx - ax, dz = bz - az;
    const t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / (dx * dx + dz * dz || 1e-9)));
    d = Math.min(d, Math.hypot(ax + t * dx - x, az + t * dz - z));
  }
  return d;
}
// world.js ids: a building's name, or b<index> when it has none.
const idOf = (b) => b.name || `b${world.buildings.indexOf(b)}`;

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
  let src, replaces = [];
  if (L.poi) {
    const p = world.pois.find((x) => x.name === L.poi);
    if (!p) { console.warn(`missing ${L.poi}`); continue; }
    out.push({ id: L.id, name: L.poi, origin: [p.x, p.z], footprints: [], roofs: [], replaces: [] });
    console.log(`${L.id}: at ${p.x.toFixed(1)}, ${p.z.toFixed(1)}`);
    continue;
  }
  if (L.ground) {
    const [x0, x1, z0, z1] = L.box;
    src = world.ground.filter((g) => {
      const [x, z] = centroid(g.pts);
      return g.kind === L.ground && x > x0 && x < x1 && z > z0 && z < z1;
    }).sort((a, b) => Math.abs(area(b.pts)) - Math.abs(area(a.pts)));
  } else if (L.within) {
    const a = world.areas.find((x) => x.name === L.area);
    if (!a) { console.warn(`missing ${L.area}`); continue; }
    // Buildings inside the area, or within `within` metres of its outline (gates, houses on the edge).
    const blds = world.buildings.filter((b) => { const c = centroid(b.pts); return inside(a.pts, ...c) || edgeDist(a.pts, ...c) < L.within; });
    src = [a, ...blds];
    replaces = blds.map(idOf);
  } else if (L.ids) {
    src = L.ids.map((i) => world.buildings[i]);
    replaces = src.map(idOf);
  } else {
    src = L.area ? world.areas.filter((a) => a.name === L.area) : world.buildings.filter((b) => b.name === L.building);
    if (!src.length) { console.warn(`missing ${L.building || L.area}`); continue; }
    src.sort((a, b) => Math.abs(area(b.pts)) - Math.abs(area(a.pts))); // main footprint first
    replaces = L.area ? [] : [...new Set(src.map(idOf))];
  }
  if (L.add) {
    const blds = L.add.map((k) => (typeof k === "number" ? world.buildings[k] : world.buildings.find((b) => b.name === k)));
    src = [...src, ...blds.filter(Boolean)];
    replaces = [...replaces, ...blds.filter(Boolean).map(idOf)];
  }
  const main = src[0].pts;
  const cx = main.slice(0, -1).reduce((s, p) => s + p[0], 0) / (main.length - 1);
  const cz = main.slice(0, -1).reduce((s, p) => s + p[1], 0) / (main.length - 1);
  const footprints = src.map((s) => {
    let r = s.pts.map(([x, z]) => [+(x - cx).toFixed(3), +(-(z - cz)).toFixed(3)]);
    if (area(r) < 0) r = r.reverse(); // counter-clockwise in Blender's x/y
    return r;
  });
  const roofSpecs = [...(L.roofs || [])];
  if (L.roofsAll) for (let fi = L.roofFirst ? 0 : 1; fi < footprints.length; fi++) roofSpecs.push([fi, ...L.roofsAll]);
  const local = (pts) => { let r = pts.map(([x, z]) => [+(x - cx).toFixed(3), +(-(z - cz)).toFixed(3)]); return area(r) < 0 ? r.reverse() : r; };
  const pools = L.pools ? world.water.filter((w) => w.pts && inside(src[0].pts, ...centroid(w.pts))).map((w) => local(w.pts)) : undefined;
  const roofs = roofSpecs.map(([fi, eave, pitch, overhang]) => {
    const ring = offsetRing(simplify(footprints[fi]), overhang);
    const sk = SkeletonBuilder.buildFromPolygon([ring]);
    if (!sk) { console.warn(`${L.id}: no skeleton for footprint ${fi}`); return null; }
    return { fi, eave, slope: Math.tan((pitch * Math.PI) / 180), vertices: sk.vertices, polygons: sk.polygons };
  }).filter(Boolean);
  out.push({ id: L.id, name: L.label || L.building || L.area, origin: [cx, cz], footprints, roofs, replaces, ...(pools ? { pools } : {}) });
  console.log(`${L.id}: ${footprints.length} footprint(s), ${roofs.length} roof(s)`);
}
const dest = path.join(root, "work/landmarks/input.json");
fs.mkdirSync(path.dirname(dest), { recursive: true });
fs.writeFileSync(dest, JSON.stringify(out));
console.log(`wrote ${path.relative(root, dest)}`);
