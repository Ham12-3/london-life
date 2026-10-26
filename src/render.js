// WebGPU rendering: physical sky with clouds, sky-lit environment, cascaded sun shadows, London haze,
// ground-truth ambient occlusion and temporal upscaling, with quality presets that adapt to the GPU.
// Built from the three.js r186 examples webgpu_sky, webgpu_shadowmap_csm, webgpu_fog_height,
// webgpu_postprocessing_ao and webgpu_upscaling_taau.
import * as THREE from "three/webgpu";
import {
  pass, mrt, output, normalView, velocity, packNormalToRGB, unpackRGBToNormal, sample, screenUV, vec4,
  fog, color, uniform, densityFogFactor, exponentialHeightFogFactor,
} from "three/tsl";
import { SkyMesh } from "three/addons/objects/SkyMesh.js";
import { CSMShadowNode } from "three/addons/csm/CSMShadowNode.js";
import { ao } from "three/addons/tsl/display/GTAONode.js";
import { taau } from "three/addons/tsl/display/TAAUNode.js";
import { sharpen } from "three/addons/tsl/display/SharpenNode.js";

// Render scale is the share of screen pixels actually shaded; TAAU reconstructs the rest.
export const QUALITY = {
  high: { label: "High", scale: 1.0, ao: true },
  medium: { label: "Medium", scale: 0.75, ao: true },
  low: { label: "Low", scale: 0.55, ao: false },
};
const ORDER = ["low", "medium", "high"];

// A London summer afternoon: sun high in the south-west.
const SUN_ELEVATION = 46;
const SUN_AZIMUTH = 215;
const HAZE = 0xc8d3dc;

export async function createRenderer(container) {
  // ?gpu in the URL turns on GPU timers (renderer.info.render.timestamp) for profiling.
  const renderer = new THREE.WebGPURenderer({ antialias: false, trackTimestamp: new URLSearchParams(location.search).has("gpu") });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1)); // TAAU handles edge quality; extra pixels cost too much on laptops
  renderer.setSize(innerWidth, innerHeight);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.55;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap; // WebGPU has no PCFSoftShadowMap; CSM fades between cascades instead
  container.appendChild(renderer.domElement);
  await renderer.init();
  return renderer;
}

function makeSky(sunDir) {
  const sky = new SkyMesh();
  sky.scale.setScalar(2500);
  sky.turbidity.value = 4;
  sky.rayleigh.value = 1.4;
  sky.mieCoefficient.value = 0.004;
  sky.mieDirectionalG.value = 0.75;
  sky.cloudCoverage.value = 0.45;
  sky.cloudDensity.value = 0.5;
  sky.cloudElevation.value = 0.55;
  sky.sunPosition.value.copy(sunDir);
  return sky;
}

export function setupAtmosphere(renderer, scene) {
  // World axes: +x east, +z south. Azimuth is clockwise from north.
  const el = THREE.MathUtils.degToRad(SUN_ELEVATION), az = THREE.MathUtils.degToRad(SUN_AZIMUTH);
  const sunDir = new THREE.Vector3(Math.cos(el) * Math.sin(az), Math.sin(el), -Math.cos(el) * Math.cos(az));

  scene.add(makeSky(sunDir));

  // Image-based lighting from the same sky, so every material picks up its colour and reflections.
  const envScene = new THREE.Scene();
  envScene.add(makeSky(sunDir));
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(envScene, 0, 1, 3000).texture;
  scene.environmentIntensity = 0.3; // the sky is HDR: a little goes a long way

  // A little bounce from the grass under the sky lighting.
  scene.add(new THREE.HemisphereLight(0xdfeaf5, 0x55703a, 0.35));

  const sun = new THREE.DirectionalLight(0xfff1dc, 3.2);
  sun.position.copy(sunDir).multiplyScalar(300);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { near: 1, far: 1200, left: -400, right: 400, top: 400, bottom: -400 });
  sun.shadow.bias = -0.0003;
  sun.shadow.normalBias = 0.02;
  // Cascaded shadows: crisp near the walker, still present across the whole 700 m zoo.
  const csm = new CSMShadowNode(sun, { cascades: 3, maxFar: 260, mode: "practical", lightMargin: 150 });
  csm.fade = true;
  sun.shadow.shadowNode = csm;
  scene.add(sun, sun.target);

  // Haze: light distance fog plus thicker air near the ground, like a warm London afternoon.
  const distance = densityFogFactor(uniform(0.0016));
  const ground = exponentialHeightFogFactor(uniform(0.00035), uniform(14));
  scene.fogNode = fog(color(HAZE), distance.max(ground));

  return { sun, sunDir, csm };
}

export function createPipeline(renderer, scene, camera) {
  const pipeline = new THREE.RenderPipeline(renderer);

  // One scene pass writes colour, normals and motion vectors together (drawing the scene twice
  // costs too much with trees and grass on a laptop GPU).
  const scenePass = pass(scene, camera);
  scenePass.setMRT(mrt({ output, normal: packNormalToRGB(normalView), velocity }));
  scenePass.getTexture("normal").type = THREE.UnsignedByteType;
  const sceneNormal = sample((uv) => unpackRGBToNormal(scenePass.getTextureNode("normal").sample(uv)));
  const sceneDepth = scenePass.getTextureNode("depth");
  const sceneVelocity = scenePass.getTextureNode("velocity");

  // Ground-truth AO at half resolution: contact shadows under benches, walls, eaves and trees.
  const aoPass = ao(sceneDepth, sceneNormal, camera);
  aoPass.resolutionScale = 0.5;
  aoPass.radius.value = 1.2; // metres
  aoPass.thickness.value = 1.5;
  aoPass.samples.value = 12;
  aoPass.useTemporalFiltering = true;

  // TAAU: anti-aliases and upscales from the reduced render scale; AO darkens the result.
  const upscaled = taau(scenePass.getTextureNode("output"), sceneDepth, sceneVelocity, camera);
  const sharpened = sharpen(upscaled.getTextureNode(), 0.3);
  const occlusion = aoPass.getTextureNode().sample(screenUV).r.mul(0.85).add(0.15);
  const withAO = vec4(sharpened.rgb.mul(occlusion), 1);

  const state = { mode: "auto", level: "medium" };
  function apply(level) {
    const q = QUALITY[level];
    state.level = level;
    scenePass.setResolutionScale(q.scale);
    pipeline.outputNode = q.ao ? withAO : sharpened;
    pipeline.needsUpdate = true;
  }
  apply(state.level);

  // Auto quality: average frame time over ~2 s windows; step down below ~40 fps, try a step up while
  // holding 60. A level that was too slow once is never retried, so it can't flip back and forth.
  let frames = 0, elapsed = 0, settledAt = 0, ceiling = ORDER.length - 1;
  function measure(dt) {
    if (state.mode !== "auto" || document.hidden) return;
    frames++;
    elapsed += dt;
    if (elapsed < 2) return;
    const ms = (elapsed / frames) * 1000;
    frames = 0;
    elapsed = 0;
    const i = ORDER.indexOf(state.level);
    const now = performance.now();
    if (ms > 25 && i > 0) { ceiling = i - 1; apply(ORDER[i - 1]); settledAt = now; }
    else if (ms < 18 && i < ceiling && now - settledAt > 10000) { apply(ORDER[i + 1]); settledAt = now; }
  }

  return {
    pipeline,
    state,
    render: () => pipeline.render(),
    measure,
    cycle() {
      const modes = ["auto", ...ORDER.slice().reverse()];
      state.mode = modes[(modes.indexOf(state.mode) + 1) % modes.length];
      if (state.mode !== "auto") apply(state.mode);
      return state;
    },
  };
}
