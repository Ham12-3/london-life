// Exports the web app's Ez-Tree variants (same presets and seeds as src/trees.js) for Blender:
// geometry as JSON plus their bark and leaf textures as image files.
//
//   node tools/blender_world/trees_export.mjs     -> work/blender/trees/
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as THREE from "three";

// Ez-Tree loads its textures (embedded data URLs) when imported; in Node, just remember the URLs.
THREE.TextureLoader.prototype.load = function (url) {
  const t = new THREE.Texture();
  t.userData.src = url;
  return t;
};
const { Tree } = await import("@dgreenheck/ez-tree");

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const out = path.join(root, "work/blender/trees");
fs.mkdirSync(out, { recursive: true });

// Same as src/trees.js, including the London plane (last).
const VARIANTS = [
  ["Oak Medium", 35729], ["Oak Large", 1201], ["Ash Medium", 5521],
  ["Ash Large", 777], ["Aspen Medium", 4242], ["Oak Medium", 9001],
  ["Oak Large", 4321, "plane"],
];

function saveImage(tex, name) {
  const src = tex?.userData?.src;
  if (!src || !src.startsWith("data:")) return null;
  const [meta, b64] = src.split(",");
  const ext = meta.includes("png") ? "png" : "jpg";
  const file = `${name}.${ext}`;
  fs.writeFileSync(path.join(out, file), Buffer.from(b64, "base64"));
  return file;
}

const dump = (g) => ({
  position: Array.from(g.attributes.position.array, (v) => +v.toFixed(4)),
  normal: g.attributes.normal ? Array.from(g.attributes.normal.array, (v) => +v.toFixed(3)) : null,
  uv: g.attributes.uv ? Array.from(g.attributes.uv.array, (v) => +v.toFixed(4)) : null,
  index: Array.from(g.index.array),
});

const variants = VARIANTS.map(([preset, seed, kind], i) => {
  const tree = new Tree();
  tree.loadPreset(preset);
  tree.options.seed = seed;
  if (kind === "plane") {
    tree.options.branch.length[0] *= 1.25;
    tree.options.leaves.size *= 1.25;
    tree.options.leaves.tint = 0xffffff;
    tree.options.bark.tint = 0xffffff;
  }
  tree.options.leaves.count = Math.max(4, Math.round(tree.options.leaves.count * 0.45));
  tree.options.leaves.size *= 1.45;
  tree.generate();
  const branches = tree.branchesMesh.geometry, leaves = tree.leavesMesh.geometry;
  branches.computeBoundingBox();
  leaves.computeBoundingBox();
  const box = branches.boundingBox.clone().union(leaves.boundingBox);
  const s = 1 / (box.max.y - box.min.y);
  for (const g of [branches, leaves]) {
    g.translate(0, -box.min.y, 0);
    g.scale(s, s, s);
  }
  const bm = tree.branchesMesh.material, lm = tree.leavesMesh.material;
  const bark = tree.options.bark.type, leaf = tree.options.leaves.type;
  if (kind === "plane") {
    // Scanned plane bark (Poly Haven) and the painted plane-leaf sprig.
    fs.copyFileSync(path.join(root, "public/assets/textures/bark_platanus/diff.jpg"), path.join(out, "bark_plane_color.jpg"));
    fs.copyFileSync(path.join(root, "public/assets/textures/bark_platanus/nor.jpg"), path.join(out, "bark_plane_normal.jpg"));
    fs.copyFileSync(path.join(root, "public/assets/trees/leaf_plane.png"), path.join(out, "leaf_plane.png"));
    return {
      name: `london_plane_${i}`, plane: true,
      branches: dump(branches), leaves: dump(leaves),
      bark: { color: "bark_plane_color.jpg", normal: "bark_plane_normal.jpg", tint: 0xffffff, repeat: [1, 0.5] },
      leaf: { color: "leaf_plane.png", tint: 0xffffff, alphaTest: lm.alphaTest },
    };
  }
  return {
    name: `${preset.toLowerCase().replace(" ", "_")}_${i}`,
    branches: dump(branches),
    leaves: dump(leaves),
    bark: { color: saveImage(bm.map, `bark_${bark}_color`), normal: saveImage(bm.normalMap, `bark_${bark}_normal`), tint: bm.color.getHex(), repeat: [bm.map?.repeat.x ?? 1, bm.map?.repeat.y ?? 1] },
    leaf: { color: saveImage(lm.map, `leaf_${leaf}`), tint: lm.color.getHex(), alphaTest: lm.alphaTest },
  };
});
fs.writeFileSync(path.join(out, "trees.json"), JSON.stringify(variants));
console.log(variants.map((v) => `${v.name}: ${v.branches.index.length / 3 + v.leaves.index.length / 3} tris`).join("\n"));
