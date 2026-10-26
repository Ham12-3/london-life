// Architectural detail for every mapped building. OpenStreetMap only gives an outline and a height,
// so the look follows rules, the way Streets GL dresses OSM cities:
//   - a stone plinth at the foot of the walls and a cornice band at the eaves
//   - rows of windows per storey on every wall long enough (sash windows on the houses, wide
//     glazing on zoo buildings), each with a frame, sill and glass that reflects the sky, and a bright
//     pane on the inside face so rooms look daylit
//   - door surrounds at every doorway
//   - hipped slate or tile roofs from the outline's straight skeleton, or flat roofs behind a parapet
import * as THREE from "three/webgpu";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { SkeletonBuilder } from "straight-skeleton";
import { pbr } from "./materials.js";

const WALL = 0.3; // wall thickness, as in world.js
const OVERHANG = 0.35; // eaves overhang of pitched roofs

export const initBuildingDetail = () => SkeletonBuilder.init();

// Window kinds: size (m), spacing between centres, frame colour, glazing bars.
const WINDOWS = {
  sash: { w: 1.0, h: 1.6, spacing: 2.5, sill: 0.9, frame: 0xefeee8, bars: [0.5], mullions: [] },
  wide: { w: 1.9, h: 1.3, spacing: 4.2, sill: 1.0, frame: 0x353d39, bars: [], mullions: [0.5] },
};

// London front doors: black, navy, racing green, oxblood, slate blue.
const DOOR_COLOURS = [0x15181a, 0x1c2a44, 0x1f3a2b, 0x5a1d1d, 0x3d5566];
const len2 = (e) => (e.c[0] - e.a[0]) ** 2 + (e.c[1] - e.a[1]) ** 2;

function hashOf(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return (h >>> 0) / 4294967296;
}

function area(ring) {
  let a = 0;
  for (let i = 0; i < ring.length - 1; i++) a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
  return a / 2;
}

// A box from a to b along the ground, between heights y0..y1, `depth` thick, centred `offset`
// metres outward from the line (outward = right of a→b on a counter-clockwise ring).
function band(a, b, y0, y1, depth, offset = 0, extend = 0) {
  const dx = b[0] - a[0], dz = b[1] - a[1], len = Math.hypot(dx, dz);
  const ux = dx / len, uz = dz / len, ox = uz * offset, oz = -ux * offset;
  const g = new THREE.BoxGeometry(len + extend * 2, y1 - y0, depth);
  g.rotateY(-Math.atan2(dz, dx));
  g.translate((a[0] + b[0]) / 2 + ox, (y0 + y1) / 2, (a[1] + b[1]) / 2 + oz);
  return g;
}

function paint(g, color) {
  const c = new THREE.Color(color), n = g.attributes.position.count, rgb = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) rgb.set([c.r, c.g, c.b], i * 3);
  g.setAttribute("color", new THREE.BufferAttribute(rgb, 3));
  return g;
}

// Window parts in local space: the window faces +z, centred on the wall face at z = 0.
function windowParts(k) {
  const { w, h } = k, t = 0.07, d = 0.09;
  const frame = [
    new THREE.BoxGeometry(w + t * 2, t, d).translate(0, h / 2 + t / 2, d / 2),
    new THREE.BoxGeometry(w + t * 2, t, d).translate(0, -h / 2 - t / 2, d / 2),
    new THREE.BoxGeometry(t, h, d).translate(-w / 2 - t / 2, 0, d / 2),
    new THREE.BoxGeometry(t, h, d).translate(w / 2 + t / 2, 0, d / 2),
    ...k.bars.map((f) => new THREE.BoxGeometry(w, 0.045, d * 0.7).translate(0, -h / 2 + h * f, d * 0.35)),
    ...k.mullions.map((f) => new THREE.BoxGeometry(0.05, h, d * 0.7).translate(-w / 2 + w * f, 0, d * 0.35)),
  ];
  const stone = [
    new THREE.BoxGeometry(w + 0.24, 0.07, 0.2).translate(0, -h / 2 - t - 0.035, 0.1), // sill
    new THREE.BoxGeometry(w + 0.3, 0.2, 0.05).translate(0, h / 2 + t + 0.1, 0.025), // lintel
  ];
  return {
    frame: mergeGeometries(frame.map((g) => g.toNonIndexed())),
    stone: mergeGeometries(stone.map((g) => g.toNonIndexed())),
    glass: new THREE.PlaneGeometry(w, h).translate(0, 0, 0.012),
  };
}

// Offset a counter-clockwise ring outward by d (mitred, with sharp corners clamped).
function offsetRing(ring, d) {
  const pts = ring.slice(0, -1), n = pts.length, out = [];
  for (let i = 0; i < n; i++) {
    const p = pts[(i + n - 1) % n], c = pts[i], q = pts[(i + 1) % n];
    const e1 = [c[0] - p[0], c[1] - p[1]], e2 = [q[0] - c[0], q[1] - c[1]];
    const l1 = Math.hypot(...e1) || 1, l2 = Math.hypot(...e2) || 1;
    const n1 = [e1[1] / l1, -e1[0] / l1], n2 = [e2[1] / l2, -e2[0] / l2];
    let mx = n1[0] + n2[0], mz = n1[1] + n2[1];
    const dot = 1 + n1[0] * n2[0] + n1[1] * n2[1];
    const k = d / Math.max(dot, 0.25);
    out.push([c[0] + mx * k, c[1] + mz * k]);
  }
  out.push(out[0]);
  return out;
}

// Hipped roof from the straight skeleton: every face rises from its eave at the same pitch.
// UVs run along the eave (u) and up the slope (v), in metres, so slates line up with the eaves.
function hipRoof(ring, eaveY, pitchDeg, maxRise) {
  const sk = SkeletonBuilder.buildFromPolygon([ring]);
  if (!sk) return null;
  const maxT = Math.max(...sk.vertices.map((v) => v[2]));
  let slope = Math.tan(THREE.MathUtils.degToRad(pitchDeg));
  if (maxT * slope > maxRise) slope = maxRise / maxT;
  if (slope < Math.tan(THREE.MathUtils.degToRad(12))) return null; // too big to pitch: flat roof instead
  const pos = [], uv = [];
  const slopeLen = Math.sqrt(1 + slope * slope);
  for (const face of sk.polygons) {
    const vs = face.map((i) => sk.vertices[i]);
    // The eave is the face's edge with both ends on the outline (time 0).
    let e = 0;
    for (let i = 0; i < vs.length; i++) if (vs[i][2] < 1e-6 && vs[(i + 1) % vs.length][2] < 1e-6) { e = i; break; }
    const a = vs[e], b = vs[(e + 1) % vs.length];
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, ux = (b[0] - a[0]) / len, uz = (b[1] - a[1]) / len;
    const contour = vs.map((v) => new THREE.Vector2(v[0], v[1]));
    let tris;
    try { tris = THREE.ShapeUtils.triangulateShape(contour, []); } catch { continue; }
    for (const tri of tris) {
      const P = tri.map((i) => new THREE.Vector3(vs[i][0], eaveY + vs[i][2] * slope, vs[i][1]));
      const nrm = new THREE.Vector3().subVectors(P[1], P[0]).cross(new THREE.Vector3().subVectors(P[2], P[0]));
      const order = nrm.y >= 0 ? [0, 1, 2] : [0, 2, 1];
      for (const j of order) {
        const v = vs[tri[j]];
        pos.push(P[j].x, P[j].y, P[j].z);
        uv.push((v[0] - a[0]) * ux + (v[1] - a[1]) * uz, v[2] * slopeLen);
      }
    }
  }
  if (!pos.length) return null;
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.computeVertexNormals();
  return { geo: g, top: eaveY + maxT * slope };
}

export class BuildingDetail {
  constructor() {
    this.plinth = [];
    this.cornice = [];
    this.doors = [];
    this.roofs = { slate: [], tile: [] };
    this.windows = { sash: [], wide: [] }; // per window: matrix (outside face)
    this.frontDoors = []; // { matrix, color }
  }

  // Decide the building's style. Returns { roof: "flat" | "hip", top } so world.js knows whether
  // to lay its own flat roof and where to hang the label.
  add(b, id, edges, finishGeos, color) {
    let ring = b.pts.map((p) => [p[0], p[1]]);
    if (area(ring) < 0) ring = ring.reverse();
    const r = hashOf(id), a = Math.abs(area(ring));
    const house = !b.inZoo && b.kind !== "garages" && b.kind !== "service";
    const h = b.h;

    // Roof choice: houses and small zoo buildings get pitched roofs; big zoo halls stay flat.
    let pitch = 0, cover = "slate", maxRise = 5;
    if (house && a < 2500) pitch = 34;
    else if (b.kind === "pavilion") { pitch = 38; cover = "tile"; }
    else if (b.inZoo && a < 90) { pitch = 30; cover = r < 0.5 ? "tile" : "slate"; maxRise = 3; }
    else if (b.inZoo && a < 700 && r < 0.4) { pitch = 24; cover = "tile"; maxRise = 3.5; }
    let roof = null;
    if (pitch) {
      try { roof = hipRoof(offsetRing(ring, OVERHANG), h, pitch, maxRise); } catch { roof = null; }
    }
    if (roof) this.roofs[cover].push(roof.geo);

    // Bands: plinth at the foot, cornice at the eaves (pitched) or parapet + coping (flat).
    const stone = 0xd9d3c6;
    for (const e of edges) {
      for (const [p, q] of e.solid) this.plinth.push(paint(band(p, q, 0, 0.45, WALL + 0.08), 0x8c867c));
      if (roof) this.cornice.push(paint(band(e.a, e.c, h - 0.28, h, WALL + 0.22, 0, 0.11), stone));
      else {
        finishGeos.push(paint(band(e.a, e.c, h, h + 0.75, 0.24, 0, 0.12), color));
        this.cornice.push(paint(band(e.a, e.c, h + 0.75, h + 0.84, 0.42, 0, 0.21), stone));
        this.cornice.push(paint(band(e.a, e.c, h - 0.22, h, WALL + 0.12, 0, 0.06), stone));
      }
      for (const [p, q] of e.gaps) this.doorSurround(p, q, color);
    }

    // Windows: none on a third of the zoo's buildings (animal houses and stores are often blank).
    const kind = house ? "sash" : "wide";
    const outward = area(b.pts) >= 0 ? 1 : -1; // edges keep the map's winding
    // Houses get a front door in place of the middle ground-floor window on their longest wall.
    const front = house ? edges.reduce((best, e) => (len2(e) > len2(best) ? e : best), edges[0]) : null;
    if (house || r > 0.33) this.addWindows(edges, h, WINDOWS[kind], this.windows[kind], outward, front, r);
    return { roof: roof ? "hip" : "flat", top: roof ? roof.top : h + 0.84 };
  }

  doorSurround(p, q) {
    const d = 2.7, t = 0.14;
    const dx = q[0] - p[0], dz = q[1] - p[1], len = Math.hypot(dx, dz);
    if (len < 1) return;
    const ux = dx / len, uz = dz / len;
    const at = (s) => [p[0] + ux * s, p[1] + uz * s];
    this.doors.push(
      band(at(-t), at(0), 0, d + t, WALL + 0.12),
      band(at(len), at(len + t), 0, d + t, WALL + 0.12),
      band(at(-t), at(len + t), d, d + t + 0.08, WALL + 0.14),
    );
  }

  addWindows(edges, h, k, out, outward, front, r) {
    const floors = Math.max(1, Math.round(h / 3.5));
    const fh = h / floors;
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
    for (const e of edges) {
      const dx = e.c[0] - e.a[0], dz = e.c[1] - e.a[1], L = Math.hypot(dx, dz);
      const ux = dx / L, uz = dz / L, nx = uz * outward, nz = -ux * outward;
      q.setFromAxisAngle(up, Math.atan2(nx, nz));
      for (const [si, [p, s]] of e.solid.entries()) {
        const len = Math.hypot(s[0] - p[0], s[1] - p[1]);
        const count = Math.floor((len - 0.9) / k.spacing);
        if (count < 1) continue;
        const start = (len - (count - 1) * k.spacing) / 2;
        const doorAt = e === front && si === 0 ? Math.floor(count / 2) : -1;
        for (let f = 0; f < floors; f++) {
          const y = f * fh + k.sill + k.h / 2;
          if (y + k.h / 2 > (f + 1) * fh - 0.3) continue;
          for (let i = 0; i < count; i++) {
            const t = start + i * k.spacing;
            const x = p[0] + ux * t + nx * (WALL / 2), z = p[1] + uz * t + nz * (WALL / 2);
            if (f === 0 && i === doorAt) {
              this.frontDoors.push({ matrix: m4.compose(new THREE.Vector3(x, 0, z), q, new THREE.Vector3(1, 1, 1)).clone(), color: DOOR_COLOURS[Math.floor(r * DOOR_COLOURS.length)] });
              continue;
            }
            out.push(m4.compose(new THREE.Vector3(x, y, z), q, new THREE.Vector3(1, 1, 1)).clone());
          }
        }
      }
    }
  }

  build(scene) {
    const add = (geos, mat, shadow = true) => {
      if (!geos.length) return;
      const m = new THREE.Mesh(mergeGeometries(geos.map((g) => (g.index ? g.toNonIndexed() : g))), mat);
      m.castShadow = shadow;
      m.receiveShadow = true;
      scene.add(m);
    };
    add(this.plinth, pbr("concrete_floor_02", { tile: 2, vertexTint: true, normalScale: 0.8 }));
    add(this.cornice, pbr("white_stucco", { tile: 2, vertexTint: true, normalScale: 0.5 }));
    add(this.doors, new THREE.MeshStandardMaterial({ color: 0x2e3532, roughness: 0.6 }));
    add(this.roofs.slate, pbr("roof_slates_02", { tile: 2, uv: "mesh", side: THREE.DoubleSide }));
    add(this.roofs.tile, pbr("clay_roof_tiles", { tile: 2, uv: "mesh", side: THREE.DoubleSide }));

    // Glass: dark, but mirror-smooth and part metallic so it picks up the sky and clouds.
    const glass = new THREE.MeshStandardMaterial({ color: 0x334550, roughness: 0.03, metalness: 0.55 });
    const daylight = new THREE.MeshBasicMaterial({ color: 0xc9d6df });
    const stoneMat = new THREE.MeshStandardMaterial({ color: 0xe0dace, roughness: 0.8 });
    if (this.frontDoors.length) {
      // Panelled door with a fanlight above, a stone surround and a step.
      const door = mergeGeometries([
        new THREE.BoxGeometry(1.05, 2.2, 0.06).translate(0, 1.27, 0.03),
        new THREE.BoxGeometry(0.4, 0.5, 0.03).translate(-0.24, 1.75, 0.075),
        new THREE.BoxGeometry(0.4, 0.5, 0.03).translate(0.24, 1.75, 0.075),
        new THREE.BoxGeometry(0.4, 0.75, 0.03).translate(-0.24, 0.85, 0.075),
        new THREE.BoxGeometry(0.4, 0.75, 0.03).translate(0.24, 0.85, 0.075),
      ].map((g) => g.toNonIndexed()));
      const surround = mergeGeometries([
        new THREE.BoxGeometry(1.45, 0.16, 0.5).translate(0, 0.08, 0.25), // step
        new THREE.BoxGeometry(0.16, 2.95, 0.12).translate(-0.6, 1.47, 0.06),
        new THREE.BoxGeometry(0.16, 2.95, 0.12).translate(0.6, 1.47, 0.06),
        new THREE.BoxGeometry(1.5, 0.18, 0.16).translate(0, 3.0, 0.08),
      ].map((g) => g.toNonIndexed()));
      const fanlight = new THREE.PlaneGeometry(1.05, 0.5).translate(0, 2.65, 0.012);
      const n = this.frontDoors.length;
      const doors = new THREE.InstancedMesh(door, new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.35 }), n);
      const surrounds = new THREE.InstancedMesh(surround, new THREE.MeshStandardMaterial({ color: 0xe6e2d8, roughness: 0.7 }), n);
      const fanlights = new THREE.InstancedMesh(fanlight, glass, n);
      const c = new THREE.Color();
      this.frontDoors.forEach((d, i) => {
        for (const m of [doors, surrounds, fanlights]) m.setMatrixAt(i, d.matrix);
        doors.setColorAt(i, c.set(d.color));
      });
      for (const m of [doors, surrounds, fanlights]) { m.receiveShadow = true; scene.add(m); }
    }
    const flip = new THREE.Matrix4().makeRotationY(Math.PI).setPosition(0, 0, -WALL - 0.03);
    const tmp = new THREE.Matrix4();
    for (const [kind, mats] of Object.entries(this.windows)) {
      if (!mats.length) continue;
      const k = WINDOWS[kind], parts = windowParts(k);
      const frameMat = new THREE.MeshStandardMaterial({ color: k.frame, roughness: 0.5 });
      const meshes = [
        [parts.glass, glass, false], [parts.frame, frameMat, false], [parts.stone, stoneMat, false], [parts.glass, daylight, true],
      ].map(([geo, mat, inside]) => {
        const m = new THREE.InstancedMesh(geo, mat, mats.length);
        mats.forEach((mx, i) => m.setMatrixAt(i, inside ? tmp.multiplyMatrices(mx, flip) : mx));
        m.receiveShadow = !inside;
        scene.add(m);
        return m;
      });
      meshes[0].computeBoundingSphere();
    }
  }
}
