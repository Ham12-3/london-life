// Loads captured 3D assets listed in public/assets/manifest.json:
//   type "splat" — Gaussian splat (.spz/.ply/.splat) reconstructed from a Google Flow video
//   type "glb"   — mesh (e.g. an image-to-3D animal or prop)
// Each item is placed either at an explicit [x, y, z] or at the centre of a named OSM place ("anchor").
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

export async function loadManifest() {
  try {
    const res = await fetch("assets/manifest.json");
    if (!res.ok) return { items: [] };
    return await res.json();
  } catch {
    return { items: [] };
  }
}

function anchorPosition(world, name) {
  const area = world.areas.find((a) => a.name === name);
  if (area) return [area.c[0], 0, area.c[1]];
  const b = world.buildings.find((x) => x.name === name);
  if (b) {
    const xs = b.pts.map((p) => p[0]), zs = b.pts.map((p) => p[1]);
    return [xs.reduce((s, v) => s + v, 0) / xs.length, 0, zs.reduce((s, v) => s + v, 0) / zs.length];
  }
  const poi = world.pois.find((p) => p.name === name);
  if (poi) return [poi.x, 0, poi.z];
  return null;
}

const LOAD_RANGE = 180; // metres: assets load when you come this close…
const HIDE_RANGE = 230; // …and are hidden (not unloaded) beyond this

// Assets stream in as you walk: with 50+ splats, loading everything up front would be slow and heavy.
export function streamAssets(manifest, world, scene, renderer, onStatus = () => {}) {
  const entries = [];
  for (const item of manifest.items || []) {
    // A fitted splat's matrix translation isn't its centre, so align_splat.py records the centre separately.
    const centre = item.centre || (item.position || anchorPosition(world, item.anchor) || []).filter((_, i) => i !== 1);
    if (centre.length !== 2) {
      console.warn(`asset ${item.id}: no position and unknown anchor "${item.anchor}"`);
      continue;
    }
    entries.push({ item, centre, state: "idle", object: null });
  }
  let busy = false;
  const ctx = { spark: null, gltf: new GLTFLoader() };
  return {
    entries,
    update(camPos) {
      for (const e of entries) {
        const d = Math.hypot(e.centre[0] - camPos.x, e.centre[1] - camPos.z);
        if (e.object) e.object.visible = d < HIDE_RANGE;
      }
      if (busy) return;
      const next = entries
        .filter((e) => e.state === "idle")
        .map((e) => ({ e, d: Math.hypot(e.centre[0] - camPos.x, e.centre[1] - camPos.z) }))
        .filter((x) => x.d < LOAD_RANGE)
        .sort((a, b) => a.d - b.d)[0];
      if (!next) return;
      busy = true;
      next.e.state = "loading";
      onStatus(`Loading ${next.e.item.id}…`);
      loadOne(next.e.item, world, scene, renderer, ctx)
        .then((obj) => { next.e.object = obj; next.e.state = obj ? "loaded" : "failed"; })
        .finally(() => { busy = false; onStatus(""); });
    },
  };
}

async function loadOne(item, world, scene, renderer, ctx) {
  // A full world matrix (from tools/align_splat.py) overrides anchor/position/rotation/scale.
  const pos = item.matrix ? [0, 0, 0] : item.position || anchorPosition(world, item.anchor);
  try {
    let obj;
    if (item.type === "splat") {
      if (!ctx.spark) {
        const mod = await import("@sparkjsdev/spark");
        ctx.spark = { mod, renderer: new mod.SparkRenderer({ renderer }) };
        scene.add(ctx.spark.renderer);
      }
      obj = new ctx.spark.mod.SplatMesh({ url: item.url });
      await obj.initialized;
      // Splats from COLMAP/Brush are usually y-down; flip unless the manifest aligns them itself.
      if (item.flip !== false && !item.matrix) obj.quaternion.set(1, 0, 0, 0);
    } else {
      obj = (await ctx.gltf.loadAsync(item.url)).scene;
      obj.traverse((o) => { if (o.isMesh) o.castShadow = o.receiveShadow = true; });
    }
    if (item.matrix) {
      obj.matrixAutoUpdate = false;
      obj.matrix.fromArray(item.matrix);
      obj.matrixWorldNeedsUpdate = true;
    }
    const wrap = new THREE.Group();
    wrap.add(obj);
    wrap.position.set(...pos);
    if (item.offset) wrap.position.add(new THREE.Vector3(...item.offset));
    wrap.rotation.y = THREE.MathUtils.degToRad(item.rotationY || 0);
    wrap.scale.setScalar(item.scale || 1);
    scene.add(wrap);
    return wrap;
  } catch (err) {
    console.warn(`asset ${item.id} failed to load`, err);
    return null;
  }
}
