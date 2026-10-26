// Trees: procedural Ez-Tree London planes, oaks, ashes and aspens near the walker, swaying in the wind; baked
// impostor cards of the same trees further out. Each species variant is generated once and
// instanced, and trees swap between the two every few metres you walk.
import * as THREE from "three/webgpu";
import { positionLocal, positionGeometry, time, sin, cos, vec3, vec4, float, instanceIndex, hash, texture, cameraViewMatrix } from "three/tsl";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { Tree } from "@dgreenheck/ez-tree";

// Preset, seed, kind. Heights are normalised, so the preset size only sets the shape. The London
// plane (the commonest tree in the zoo and the park) is an Ez-Tree oak grown taller in the trunk and
// broader in the leaf, dressed in scanned plane bark (Poly Haven) and a painted plane-leaf sprig.
const VARIANTS = [
  ["Oak Medium", 35729], ["Oak Large", 1201], ["Ash Medium", 5521],
  ["Ash Large", 777], ["Aspen Medium", 4242], ["Oak Medium", 9001],
  ["Oak Large", 4321, "plane"],
];
export const PLANE_SHARE = 0.4; // of the mapped trees
const PLANE = VARIANTS.length - 1;
// Detailed trees within this distance (metres), by quality level.
export const TREE_RANGE = { high: 90, medium: 65, low: 40 };

function swayNode(leaf) {
  // The model is unit height (positionGeometry); sway grows with height squared and is added, in
  // metres, to the placed position (three applies the instance matrix before positionNode).
  const phase = hash(instanceIndex).mul(6.28);
  const h = positionGeometry.y.clamp(0, 1);
  const bend = h.mul(h);
  const t = time;
  let dx = sin(t.mul(0.9).add(phase)).mul(0.012).mul(bend);
  let dz = cos(t.mul(0.7).add(phase.mul(1.3))).mul(0.008).mul(bend);
  if (leaf) {
    const flutter = sin(t.mul(5.5).add(positionGeometry.x.add(positionGeometry.y).add(positionGeometry.z).mul(60)).add(phase)).mul(0.0035);
    dx = dx.add(flutter);
    dz = dz.add(flutter.mul(0.7));
  }
  return positionLocal.add(vec3(dx, float(0), dz).mul(14)); // ~14 m: a typical tree's height
}

function buildVariant([preset, seed, kind], textures) {
  const tree = new Tree();
  tree.loadPreset(preset);
  tree.options.seed = seed;
  if (kind === "plane") {
    tree.options.branch.length[0] *= 1.25; // a long clear trunk under a high, broad crown
    tree.options.leaves.size *= 1.25;
    tree.options.leaves.tint = 0xffffff;
    tree.options.bark.tint = 0xffffff;
  }
  // Fewer, larger leaf cards: nearly the same silhouette for well under half the triangles.
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
  if (kind === "plane") {
    bm.map = textures.planeBark;
    bm.normalMap = textures.planeBarkNormal;
    bm.aoMap = bm.roughnessMap = null;
    lm.map = textures.planeLeaf;
  }
  const bark = new THREE.MeshStandardNodeMaterial({
    map: bm.map, normalMap: bm.normalMap, aoMap: bm.aoMap, roughnessMap: bm.roughnessMap, color: bm.color, roughness: 1,
  });
  bark.positionNode = swayNode(false);
  // Leaves are the screen-filling, overdrawn part of a tree: diffuse-only shading is ~30% cheaper
  // than full PBR and foliage has next to no visible specular anyway.
  const leaf = new THREE.MeshLambertNodeMaterial({
    map: lm.map, color: lm.color, alphaTest: lm.alphaTest, side: THREE.DoubleSide,
  });
  // Sunlight shining through the canopy: leaves on the shaded side still glow green.
  leaf.emissiveNode = texture(lm.map).rgb.mul(vec3(0.6, 0.66, 0.48));
  leaf.positionNode = swayNode(true);
  const tris = (branches.index.count + leaves.index.count) / 3;
  return { branches, leaves, bark, leaf, tris, radius: (box.max.x - box.min.x) * s / 2 };
}

// Far trees are impostors: each variant is rendered once into a texture (its albedo, from the side)
// and drawn on two crossed cards, lit by the same sun and sky as everything else.
function bakeImpostor(renderer, v) {
  const S = Math.max(1, v.radius * 2) * 1.08;
  const rt = new THREE.RenderTarget(256, 256, { generateMipmaps: true, minFilter: THREE.LinearMipmapLinearFilter, type: THREE.HalfFloatType });
  const s = new THREE.Scene();
  s.add(
    new THREE.Mesh(v.branches, new THREE.MeshBasicNodeMaterial({ map: v.bark.map, color: v.bark.color })),
    new THREE.Mesh(v.leaves, new THREE.MeshBasicNodeMaterial({ map: v.leaf.map, color: v.leaf.color, alphaTest: v.leaf.alphaTest, side: THREE.DoubleSide })),
  );
  const cam = new THREE.OrthographicCamera(-S / 2, S / 2, S, 0, -10, 10);
  cam.position.set(0, 0, 5);
  const prevTarget = renderer.getRenderTarget(), prevColor = renderer.getClearColor(new THREE.Color()), prevAlpha = renderer.getClearAlpha();
  renderer.setRenderTarget(rt);
  renderer.setClearColor(0x000000, 0);
  renderer.clear();
  renderer.render(s, cam);
  renderer.setRenderTarget(prevTarget);
  renderer.setClearColor(prevColor, prevAlpha);

  const card = new THREE.PlaneGeometry(S, S).translate(0, S / 2, 0);
  const geo = mergeGeometries([card, card.clone().rotateY(Math.PI / 2)]);
  const mat = new THREE.MeshLambertNodeMaterial({ map: rt.texture, alphaTest: 0.15, side: THREE.DoubleSide });
  // Cards shade like a canopy seen from afar: lit from above, with the same through-leaf glow.
  mat.normalNode = cameraViewMatrix.mul(vec4(0, 1, 0, 0)).xyz;
  mat.emissiveNode = texture(rt.texture).rgb.mul(0.45);
  return { geo, mat };
}

async function loadTextures() {
  const loader = new THREE.TextureLoader();
  const [planeBark, planeBarkNormal, planeLeaf] = await Promise.all([
    loader.loadAsync("assets/textures/bark_platanus/diff.jpg"),
    loader.loadAsync("assets/textures/bark_platanus/nor.jpg"),
    loader.loadAsync("assets/trees/leaf_plane.png"),
  ]);
  for (const t of [planeBark, planeBarkNormal]) {
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(1, 0.5);
  }
  planeBark.colorSpace = planeLeaf.colorSpace = THREE.SRGBColorSpace;
  return { planeBark, planeBarkNormal, planeLeaf };
}

export async function createTrees(trees, scene, renderer) {
  const textures = await loadTextures(); // before the impostors are baked from these trees
  const variants = VARIANTS.map((v) => buildVariant(v, textures));
  const meshes = variants.map((v) => {
    const b = new THREE.InstancedMesh(v.branches, v.bark, trees.length);
    const l = new THREE.InstancedMesh(v.leaves, v.leaf, trees.length);
    const imp = bakeImpostor(renderer, v);
    const f = new THREE.InstancedMesh(imp.geo, imp.mat, trees.length);
    for (const m of [b, l, f]) {
      m.castShadow = true;
      m.receiveShadow = m !== f;
      m.count = 0;
      m.frustumCulled = false; // instances move between meshes; bounds would go stale
      scene.add(m);
    }
    return { b, l, f };
  });

  // Per-tree placement, fixed for the session.
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), sc = new THREE.Vector3(), pos = new THREE.Vector3();
  const up = new THREE.Vector3(0, 1, 0);
  const placed = trees.map(([x, z, h], i) => {
    const r = Math.abs(Math.sin(x * 12.9898 + z * 78.233)) % 1;
    const height = h * (0.9 + r * 0.25);
    const matrix = m4.compose(pos.set(x, 0, z), q.setFromAxisAngle(up, r * 6.28), sc.set(height, height, height)).clone();
    // London planes for 40% of trees; the rest cycle through the other species.
    return { x, z, matrix, variant: (Math.abs(Math.sin(x * 4.17 + z * 9.31)) % 1) < PLANE_SHARE ? PLANE : i % PLANE };
  });

  let lastX = Infinity, lastZ = Infinity, range = TREE_RANGE.medium;
  function rebuild(cx, cz) {
    const near = variants.map(() => 0), far = variants.map(() => 0);
    for (const t of placed) {
      const m = meshes[t.variant];
      if ((t.x - cx) ** 2 + (t.z - cz) ** 2 < range * range) {
        const k = near[t.variant]++;
        m.b.setMatrixAt(k, t.matrix);
        m.l.setMatrixAt(k, t.matrix);
      } else {
        m.f.setMatrixAt(far[t.variant]++, t.matrix);
      }
    }
    meshes.forEach((m, v) => {
      m.b.count = m.l.count = near[v];
      m.f.count = far[v];
      m.b.instanceMatrix.needsUpdate = m.l.instanceMatrix.needsUpdate = m.f.instanceMatrix.needsUpdate = true;
    });
  }

  return {
    variants,
    setRange(r) { range = r; lastX = Infinity; },
    update(p) {
      if ((p.x - lastX) ** 2 + (p.z - lastZ) ** 2 < 16) return;
      lastX = p.x;
      lastZ = p.z;
      rebuild(p.x, p.z);
    },
  };
}
