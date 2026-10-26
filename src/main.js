import * as THREE from "three/webgpu";
import { buildWorld } from "./world.js";
import { spawnAnimals } from "./animals.js";
import { Player } from "./player.js";
import { Hud } from "./hud.js";
import { loadManifest, streamAssets } from "./assets.js";
import { createRenderer, setupAtmosphere, createPipeline, QUALITY } from "./render.js";
import { createTrees, TREE_RANGE } from "./trees.js";
import { createGrass, GRASS_AMOUNT } from "./grass.js";

const status = document.getElementById("status");
const qualityChip = document.getElementById("quality");

// The video-derived Gaussian splats are retired: they only looked right from where each clip was
// filmed. Clean meshes (GLB) listed in the manifest still load.
const SHOW_SPLATS = false;

status.textContent = "Loading London Zoo…";
const renderer = await createRenderer(document.getElementById("app"));
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(70, innerWidth / innerHeight, 0.1, 3000);
const { sun } = setupAtmosphere(renderer, scene);

const [world, manifest] = await Promise.all([fetch("world.json").then((r) => r.json()), loadManifest()]);
const items = (manifest.items || []).filter((i) => SHOW_SPLATS || i.type !== "splat");
const hiddenBuildings = new Set(items.filter((i) => i.replacesBuilding).map((i) => i.anchor));
const replacedSpecies = new Set(items.filter((i) => i.species).map((i) => i.species));
const capturedPlaces = new Set(items.filter((i) => i.type === "splat").map((i) => i.anchor));
const info = buildWorld(world, scene, { hiddenBuildings, capturedPlaces });
const zooAnimals = spawnAnimals(world, scene, { replacedSpecies, capturedPlaces });
const trees = createTrees(info.trees, scene, renderer);
const grass = createGrass(world, scene);

const player = new Player(camera, renderer.domElement, info.collision);
const s = world.start;
// world.start sits on the entrance building's north wall; begin on the forecourt facing the gates.
player.teleport(s.x, s.z - 10, s.x, s.z + 20);

const hud = new Hud(world, info, player);
const intro = document.getElementById("intro");
document.getElementById("enter").addEventListener("click", () => player.controls.lock());
renderer.domElement.addEventListener("click", () => { if (!hud.panelOpen) player.controls.lock(); });
player.controls.addEventListener("lock", () => { intro.hidden = true; hud.close(); });
player.controls.addEventListener("unlock", () => { if (!hud.panelOpen) intro.hidden = false; });

const view = createPipeline(renderer, scene, camera);
const showQuality = () => {
  const { mode, level } = view.state;
  trees.setRange(TREE_RANGE[level]);
  grass.setAmount(GRASS_AMOUNT[level]);
  qualityChip.textContent = `Quality: ${mode === "auto" ? `Auto (${QUALITY[level].label})` : QUALITY[level].label} · P to change`;
};
showQuality();
addEventListener("keydown", (e) => {
  if (e.code === "KeyP" && !(e.target instanceof HTMLInputElement)) { view.cycle(); showQuality(); }
});
status.textContent = "";

const assets = streamAssets({ items }, world, scene, renderer, (t) => (status.textContent = t));

addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

const timer = new THREE.Timer();
const labelNear = 10, labelFar = 70;
let lastLevel = view.state.level;
renderer.setAnimationLoop(() => {
  timer.update();
  const dt = Math.min(timer.getDelta(), 0.1);
  if (player.locked) player.update(dt);
  zooAnimals.update(dt);
  const p = camera.position;
  // Labels: hidden when you're right on top of them (they'd fill the screen) and when far away.
  for (const l of info.labels) {
    const d2 = l.position.distanceToSquared(p);
    l.visible = d2 > labelNear * labelNear && d2 < labelFar * labelFar;
  }
  trees.update(p);
  grass.update(p);
  assets.update(p);
  hud.update();
  view.measure(dt);
  if (view.state.level !== lastLevel) { lastLevel = view.state.level; showQuality(); }
  view.render();
});

// Handy for debugging from the console.
Object.assign(window, { zoo: { scene, camera, renderer, player, world, info, hud, assets, view, sun, trees, grass } });
