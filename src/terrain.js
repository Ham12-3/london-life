// Ground levels (tools/terrain/height.py): the Regent's Canal cutting and the tunnel ramps under
// the Outer Circle. Everything that stands on the ground (you, trees, grass, furniture, animals)
// asks heightAt(); the grass reads the same grid from a texture on the GPU.
import * as THREE from "three/webgpu";
import { texture as tex, vec2, float, mix, smoothstep } from "three/tsl";

const FLAT = { heightAt: () => 0, surfaceAt: () => 0, texture: null, meta: null, ao: null };

// Ambient occlusion baked in Blender over the zoo (tools/blender_world/bake_ao.py): one top-down
// image, looked up by world position. Applied to sky light only (a material's aoNode).
async function loadGroundAO() {
  try {
    const region = await fetch("assets/terrain/ao.json").then((r) => (r.ok ? r.json() : null));
    if (!region) return null;
    const texture = await new THREE.TextureLoader().loadAsync("assets/terrain/ao.jpg");
    texture.colorSpace = THREE.SRGBColorSpace; // baked into an sRGB image
    texture.wrapS = texture.wrapT = THREE.ClampToEdgeWrapping;
    texture.anisotropy = 4;
    return { texture, region };
  } catch {
    return null;
  }
}

/**
 * Baked ground occlusion at a world-space xz node (a vec2 of world x, z), or 1 without a bake. The
 * image holds the topmost surface only; pass the world y as well and anything well below the
 * ground grid (the tunnel floors under the Outer Circle) is shaded as covered.
 */
export function groundAO(terrain, xz, y = null) {
  const ao = terrain?.ao;
  if (!ao) return float(1);
  const { x0, x1, z_at_v0: zA, z_at_v1: zB } = ao.region;
  const uv = vec2(xz.x.sub(x0).div(x1 - x0), xz.y.sub(zA).div(zB - zA));
  const open = tex(ao.texture, uv).r;
  if (y === null || !terrain.texture) return open;
  const { x0: gx, z0: gz, step, nx, nz } = terrain.meta;
  const top = tex(terrain.texture, vec2(xz.x.sub(gx).div(step).add(0.5).div(nx), xz.y.sub(gz).div(step).add(0.5).div(nz))).r;
  return mix(open, 0.3, smoothstep(1.5, 2.5, top.sub(y)));
}

export async function loadTerrain() {
  try {
    const [meta, buf, ao] = await Promise.all([
      fetch("assets/terrain/terrain.json").then((r) => (r.ok ? r.json() : null)),
      fetch("assets/terrain/height.bin").then((r) => (r.ok ? r.arrayBuffer() : null)),
      loadGroundAO(),
    ]);
    if (!meta || !buf) return FLAT;
    const h = new Float32Array(buf);
    const { x0, z0, step, nx, nz } = meta;

    const heightAt = (x, z) => {
      const gx = (x - x0) / step, gz = (z - z0) / step;
      const i = Math.floor(gx), j = Math.floor(gz);
      if (i < 0 || j < 0 || i >= nx - 1 || j >= nz - 1) return 0;
      const fx = gx - i, fz = gz - j, k = j * nx + i;
      return (h[k] * (1 - fx) + h[k + 1] * fx) * (1 - fz) + (h[k + nx] * (1 - fx) + h[k + nx + 1] * fx) * fz;
    };

    // Under the road the ground is solid on top, with the tunnel passage below: which one you're
    // on depends on whether you came down the ramp.
    const tunnels = meta.tunnels.map((t) => ({ ...t, half: t.w / 2 + 1.2 }));
    const inTunnel = (x, z) => {
      for (const t of tunnels) {
        let run = 0;
        for (let i = 0; i < t.pts.length - 1; i++) {
          const [ax, az] = t.pts[i], [bx, bz] = t.pts[i + 1];
          const dx = bx - ax, dz = bz - az, L = Math.hypot(dx, dz) || 1e-9;
          const s = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / (L * L)));
          if (Math.hypot(ax + dx * s - x, az + dz * s - z) < t.half) {
            const along = run + s * L;
            if (along >= t.covered[0] - 0.5 && along <= t.covered[1] + 0.5) return t.floor;
          }
          run += L;
        }
      }
      return null;
    };
    const surfaceAt = (x, z, currentY = 0) => {
      const floor = currentY < -1.2 ? inTunnel(x, z) : null;
      return floor ?? heightAt(x, z);
    };

    const texture = new THREE.DataTexture(h, nx, nz, THREE.RedFormat, THREE.FloatType);
    texture.magFilter = texture.minFilter = THREE.LinearFilter;
    texture.needsUpdate = true;
    return { heightAt, surfaceAt, texture, meta, ao };
  } catch {
    return FLAT;
  }
}
