import * as THREE from "three";
import { Sky } from "three/addons/objects/Sky.js";
import { buildWorld } from "./world.js";
import { spawnAnimals } from "./animals.js";
import { Player } from "./player.js";
import { Hud } from "./hud.js";
import { loadManifest, streamAssets } from "./assets.js";

const status = document.getElementById("status");

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.9;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
document.getElementById("app").appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.fog = new THREE.Fog(0xc9d6de, 120, 650);
const camera = new THREE.PerspectiveCamera(70, innerWidth / innerHeight, 0.1, 3000);

// London summer afternoon light.
const sky = new Sky();
sky.scale.setScalar(4500);
const sunDir = new THREE.Vector3().setFromSphericalCoords(1, THREE.MathUtils.degToRad(50), THREE.MathUtils.degToRad(200));
sky.material.uniforms.turbidity.value = 6;
sky.material.uniforms.rayleigh.value = 1.6;
sky.material.uniforms.sunPosition.value.copy(sunDir);
scene.add(sky);
scene.add(new THREE.HemisphereLight(0xdfeaf5, 0x5b6b3a, 1.3));
const sun = new THREE.DirectionalLight(0xfff2dc, 2.4);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -70, right: 70, top: 70, bottom: -70, near: 1, far: 400 });
sun.shadow.bias = -0.0004;
scene.add(sun, sun.target);

status.textContent = "Loading London Zoo…";
const [world, manifest] = await Promise.all([fetch("world.json").then((r) => r.json()), loadManifest()]);

const items = manifest.items || [];
const hiddenBuildings = new Set(items.filter((i) => i.replacesBuilding).map((i) => i.anchor));
const replacedSpecies = new Set(items.filter((i) => i.species).map((i) => i.species));
const capturedPlaces = new Set(items.filter((i) => i.type === "splat").map((i) => i.anchor));
const info = buildWorld(world, scene, { hiddenBuildings, capturedPlaces });
const zooAnimals = spawnAnimals(world, scene, { replacedSpecies, capturedPlaces });

const player = new Player(camera, renderer.domElement, info.collision);
// Begin just outside the main entrance, facing the gates.
// The main site lies south of the Outer Circle: start on the forecourt between the road and the gates, facing in.
const s = world.start;
player.teleport(s.x, s.z - 3, s.x + 4, s.z + 20);

const hud = new Hud(world, info, player);
const intro = document.getElementById("intro");
document.getElementById("enter").addEventListener("click", () => player.controls.lock());
renderer.domElement.addEventListener("click", () => { if (!hud.panelOpen) player.controls.lock(); });
player.controls.addEventListener("lock", () => { intro.hidden = true; hud.close(); });
player.controls.addEventListener("unlock", () => { if (!hud.panelOpen) intro.hidden = false; });
status.textContent = "";

const assets = streamAssets(manifest, world, scene, renderer, (t) => (status.textContent = t));

addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

const clock = new THREE.Clock();
const labelRange = 70;
renderer.setAnimationLoop(() => {
  const dt = Math.min(clock.getDelta(), 0.1);
  if (player.locked) player.update(dt);
  zooAnimals.update(dt);
  const p = camera.position;
  sun.position.set(p.x + sunDir.x * 150, sunDir.y * 150, p.z + sunDir.z * 150);
  sun.target.position.set(p.x, 0, p.z);
  for (const l of info.labels) l.visible = l.position.distanceToSquared(p) < labelRange * labelRange;
  assets.update(p);
  hud.update();
  renderer.render(scene, camera);
});

// Handy for debugging from the console.
Object.assign(window, { zoo: { scene, camera, renderer, player, world, info, hud, assets } });
