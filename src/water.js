// Ponds, moats and the Regent's Canal: two drifting ripple layers over a dark green body of water.
// Reflections come from the sky environment (no extra scene pass), so it costs about the same as
// any other surface.
import * as THREE from "three/webgpu";
import { texture, positionWorld, cameraViewMatrix, time, vec2, vec3, vec4, float, mix, positionViewDirection, normalView, dot, pow, clamp } from "three/tsl";

let material = null;

export function waterMaterial() {
  if (material) return material;
  const normals = new THREE.TextureLoader().load("assets/textures/water/normals.jpg");
  normals.wrapS = normals.wrapT = THREE.RepeatWrapping;

  const xz = positionWorld.xz;
  const a = texture(normals, xz.div(9).add(vec2(time.mul(0.012), time.mul(0.008)))).xyz.mul(2).sub(1);
  const b = texture(normals, xz.div(4).add(vec2(time.mul(-0.01), time.mul(0.016)))).xyz.mul(2).sub(1);
  const n = a.add(b);
  // Tangent-space (x, y) lie in the world (x, z) plane for a flat surface; keep the ripples gentle.
  const nWorld = vec3(n.x.mul(0.35), n.z, n.y.mul(0.35)).normalize();

  material = new THREE.MeshStandardNodeMaterial();
  material.normalNode = cameraViewMatrix.mul(vec4(nWorld, 0)).xyz.normalize();
  // Looking straight down you see into murky green water; at a glance it turns to sky.
  const facing = clamp(dot(normalView, positionViewDirection), 0, 1);
  const deep = vec3(0.025, 0.06, 0.05), shallow = vec3(0.07, 0.13, 0.1);
  material.colorNode = mix(deep, shallow, pow(facing, float(2)));
  material.roughnessNode = float(0.035);
  material.metalnessNode = float(0);
  return material;
}
