// Physically based surfaces from CC0 Poly Haven scans (fetched by tools/fetch_textures.py).
// Every surface is mapped in world space, in metres: ground from above, walls along their length, so
// bricks and paving stones keep their real size on any shape without per-mesh UVs.
import * as THREE from "three/webgpu";
import { texture, positionWorld, normalWorldGeometry, cameraViewMatrix, vec2, vec3, vec4, float, abs, select, attribute, luminance, uv as meshUV, normalMap } from "three/tsl";

const loader = new THREE.TextureLoader();
const cache = new Map();

function load(path, srgb) {
  if (cache.has(path)) return cache.get(path);
  const t = loader.load(path);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = 8; // ground is mostly seen at grazing angles
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  cache.set(path, t);
  return t;
}

export function textureSet(id) {
  const dir = `assets/textures/${id}`;
  return { diff: load(`${dir}/diff.jpg`, true), nor: load(`${dir}/nor.jpg`, false), arm: load(`${dir}/arm.jpg`, false) };
}

// World-space box mapping: horizontal faces use (x, z), vertical faces run along the wall and up.
// Returns the uv plus the tangent frame that matches it, so normal maps light correctly.
function boxFrame(tile) {
  const n = normalWorldGeometry;
  const flat = abs(n.y).greaterThan(0.5);
  const along = vec3(n.z.negate(), 0, n.x).normalize();
  const T = select(flat, vec3(1, 0, 0), along);
  const B = select(flat, vec3(0, 0, 1), vec3(0, 1, 0));
  const uv = vec2(positionWorld.dot(T), positionWorld.dot(B)).div(tile);
  return { uv, T, B, N: n };
}

/**
 * A Poly Haven material.
 * @param {string} id        texture set
 * @param {object} o
 * @param {number} o.tile    metres covered by one repeat of the texture
 * @param {number|number[]} [o.tint]  colour multiplied into the albedo (white keeps the scan's colour);
 *   an [r, g, b] array may go above 1 to brighten a dark scan
 * @param {number[]} [o.colorize] keep only the scan's light and shade and recolour it (linear rgb)
 * @param {boolean} [o.vertexTint] multiply in the mesh's vertex colours (per-building paint)
 * @param {number} [o.normalScale]
 * @param {number} [o.roughness] scale on the scanned roughness
 * @param {"world"|"mesh"} [o.uv] world-space box mapping, or the mesh's own uvs (in metres)
 */
export function pbr(id, { tile = 2, tint = 0xffffff, colorize = null, vertexTint = false, normalScale = 1, roughness = 1, side, uv: mapping = "world" } = {}) {
  const set = textureSet(id);
  const mesh = mapping === "mesh";
  const { uv, T, B, N } = mesh ? { uv: meshUV().div(tile) } : boxFrame(float(tile));
  const m = new THREE.MeshStandardNodeMaterial({ side });
  const diff = texture(set.diff, uv).rgb;
  let albedo = colorize ? vec3(...colorize).mul(luminance(diff).mul(11))
    : diff.mul(Array.isArray(tint) ? new THREE.Color(...tint) : new THREE.Color(tint));
  if (vertexTint) albedo = albedo.mul(attribute("color", "vec3"));
  m.colorNode = albedo;
  const arm = texture(set.arm, uv);
  m.aoNode = arm.r;
  m.roughnessNode = arm.g.mul(roughness).clamp(0.04, 1);
  m.metalnessNode = float(0);
  if (mesh) {
    m.normalNode = normalMap(texture(set.nor, uv), vec2(normalScale));
    return m;
  }
  const nt = texture(set.nor, uv).xyz.mul(2).sub(1);
  const nWorld = T.mul(nt.x.mul(normalScale)).add(B.mul(nt.y.mul(normalScale))).add(N.mul(nt.z)).normalize();
  m.normalNode = cameraViewMatrix.mul(vec4(nWorld, 0)).xyz.normalize();
  return m;
}
