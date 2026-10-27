// Wind-blown grass: a field of individual blades around the walker that grows only where the map
// says there's lawn. A top-down mask of the whole zoo (lawns white, paths/buildings/water black)
// sets the density; the blades are a fixed patch that wraps around the camera so each one stays put
// in the world as you walk. Everything is computed on the GPU in TSL.
import * as THREE from "three/webgpu";
import {
  attribute, uniform, texture, time, vec2, vec3, vec4, float, sin, cos, mod, smoothstep, step, mix,
  cameraViewMatrix, positionGeometry,
} from "three/tsl";
import { GROUND_STYLE } from "./world.js";
import { groundAO } from "./terrain.js";

const PATCH = 60; // metres across; blades fade out before the edge
const DENSITY = 30; // blades per square metre at full quality
export const GRASS_AMOUNT = { high: 1, medium: 0.7, low: 0.4 };

function densityMask(world) {
  const half = 700, px = 2048, k = px / (half * 2);
  const c = document.createElement("canvas");
  c.width = c.height = px;
  const g = c.getContext("2d");
  const toPx = ([x, z]) => [(x + half) * k, (z + half) * k];
  const poly = (pts, fill) => {
    g.fillStyle = fill;
    g.beginPath();
    pts.forEach((p, i) => (i ? g.lineTo(...toPx(p)) : g.moveTo(...toPx(p))));
    g.closePath();
    g.fill();
  };
  const line = (pts, w, stroke) => {
    g.strokeStyle = stroke;
    g.lineWidth = w * k;
    g.lineCap = g.lineJoin = "round";
    g.beginPath();
    pts.forEach((p, i) => (i ? g.lineTo(...toPx(p)) : g.moveTo(...toPx(p))));
    g.stroke();
  };
  const grey = (v) => `rgb(${Math.round(v * 255)},${Math.round(v * 255)},${Math.round(v * 255)})`;
  g.fillStyle = "#fff"; // Regent's Park lawns
  g.fillRect(0, 0, px, px);
  for (const r of world.zoo) poly(r, grey(0.7));
  for (const gp of world.ground) if (GROUND_STYLE[gp.kind]) poly(gp.pts, grey(GROUND_STYLE[gp.kind].grass));
  for (const w of world.water) (w.line ? line(w.line, w.w + 1, "#000") : poly(w.pts, "#000"));
  for (const p of world.paths) if (p.pts.length > 1) line(p.pts, p.tunnel ? p.w + 3 : p.w + 0.5, "#000"); // tunnels: the ramp between its walls
  for (const b of world.bridges) (b.line ? line(b.line, b.w, "#000") : poly(b.pts, "#000"));
  for (const b of world.buildings) poly(b.pts, "#000");
  for (const c of world.clear || []) poly(c, "#000"); // paved forecourts from landmark models
  const t = new THREE.CanvasTexture(c);
  t.flipY = false;
  t.colorSpace = THREE.NoColorSpace;
  t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
  return { tex: t, half };
}

function bladeGeometry(count) {
  // Each blade: 3 segments tapering to a point (7 vertices, 5 triangles).
  const SEG = [0, 0.4, 0.75, 1];
  const shape = [], blade = [], index = [];
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (let i = 0; i < count; i++) {
    const ox = (rnd() - 0.5) * PATCH, oz = (rnd() - 0.5) * PATCH, a = rnd(), b = rnd();
    const base = i * 7;
    for (let s = 0; s < 3; s++) {
      shape.push(-1, SEG[s], 0, 1, SEG[s], 0);
      for (let k = 0; k < 2; k++) blade.push(ox, oz, a, b);
    }
    shape.push(0, 1, 0);
    blade.push(ox, oz, a, b);
    for (let s = 0; s < 2; s++) {
      const v = base + s * 2;
      index.push(v, v + 1, v + 2, v + 1, v + 3, v + 2);
    }
    index.push(base + 4, base + 5, base + 6);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(shape, 3));
  geo.setAttribute("blade", new THREE.Float32BufferAttribute(blade, 4));
  geo.setIndex(index);
  return geo;
}

export function createGrass(world, scene, terrain = null) {
  const { tex, half } = densityMask(world);
  const count = Math.round(PATCH * PATCH * DENSITY);
  const geo = bladeGeometry(count);

  const camXZ = uniform(new THREE.Vector2());
  const blade = attribute("blade", "vec4");
  const side = positionGeometry.x, t = positionGeometry.y;

  // Wrap the patch around the camera so blades stay fixed in the world.
  const rel = mod(blade.xy.sub(camXZ).add(PATCH / 2), PATCH).sub(PATCH / 2);
  const wp = camXZ.add(rel);
  const fade = float(1).sub(smoothstep(PATCH * 0.32, PATCH * 0.5, rel.length()));
  const density = texture(tex, wp.add(half).div(half * 2)).level(0).r;
  const keep = step(blade.w, density); // thin out to the mapped density
  const height = blade.z.mul(blade.z).mul(0.3).add(0.08).mul(keep).mul(fade);

  const yaw = blade.z.mul(37.7).add(blade.w.mul(11.3));
  const across = vec2(cos(yaw), sin(yaw));
  const width = float(0.028).mul(float(1).sub(t.mul(0.85))).mul(keep);

  // Gusts roll across the lawn; blades bend more near the tip.
  const gust = sin(wp.x.mul(0.12).add(time.mul(1.4))).mul(cos(wp.y.mul(0.09).add(time.mul(0.9)))).mul(0.5).add(0.5);
  const flutter = sin(time.mul(4.2).add(blade.z.mul(40))).mul(0.04);
  const bend = t.mul(t).mul(height).mul(gust.mul(0.55).add(0.12).add(flutter));
  const wind = vec2(0.9, 0.42).normalize();
  // Each blade also leans its own way, so the lawn doesn't comb in one direction.
  const lean = t.mul(t).mul(height).mul(blade.w.mul(0.5));
  const leanDir = vec2(cos(yaw.mul(1.7)), sin(yaw.mul(1.7)));

  // Ground level under each blade, from the terrain height grid (canal banks, tunnel ramps).
  let ground = float(0);
  if (terrain?.texture) {
    const { x0, z0, step, nx, nz } = terrain.meta;
    const tuv = vec2(wp.x.sub(x0).div(step).add(0.5).div(nx), wp.y.sub(z0).div(step).add(0.5).div(nz));
    ground = texture(terrain.texture, tuv).level(0).r;
  }

  const material = new THREE.MeshStandardNodeMaterial({ side: THREE.DoubleSide, roughness: 0.75 });
  material.positionNode = vec3(
    wp.x.add(across.x.mul(side).mul(width)).add(wind.x.mul(bend)).add(leanDir.x.mul(lean)),
    t.mul(height).mul(float(1).sub(bend.mul(0.6))).add(0.02).add(ground),
    wp.y.add(across.y.mul(side).mul(width)).add(wind.y.mul(bend)).add(leanDir.y.mul(lean)),
  );
  // Soft, mostly-up normals so the field shades like a lawn, not a pile of cards.
  material.normalNode = cameraViewMatrix.mul(vec4(vec3(across.x.mul(side).mul(0.25), 1, across.y.mul(side).mul(0.25)).normalize(), 0)).xyz.normalize();
  const hue = blade.w.mul(0.35).add(0.8);
  const root = vec3(0.04, 0.075, 0.018), tip = vec3(0.17, 0.28, 0.06), dry = vec3(0.3, 0.29, 0.1);
  material.colorNode = mix(root, mix(tip, dry, step(0.9, blade.z).mul(0.6)), t).mul(hue);
  // Darker at the roots, and under trees and beside walls (the occlusion baked in Blender).
  material.aoNode = t.mul(0.55).add(0.45).mul(groundAO(terrain, wp));

  const mesh = new THREE.Mesh(geo, material);
  mesh.frustumCulled = false;
  mesh.receiveShadow = true;
  scene.add(mesh);

  const indicesPerBlade = 15;
  return {
    mesh,
    setAmount(a) { geo.setDrawRange(0, Math.round(count * a) * indicesPerBlade); },
    update(p) { camXZ.value.set(p.x, p.z); },
  };
}
