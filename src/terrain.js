// Ground levels (tools/terrain/height.py): the Regent's Canal cutting and the tunnel ramps under
// the Outer Circle. Everything that stands on the ground (you, trees, grass, furniture, animals)
// asks heightAt(); the grass reads the same grid from a texture on the GPU.
import * as THREE from "three/webgpu";

const FLAT = { heightAt: () => 0, surfaceAt: () => 0, texture: null, meta: null };

export async function loadTerrain() {
  try {
    const [meta, buf] = await Promise.all([
      fetch("assets/terrain/terrain.json").then((r) => (r.ok ? r.json() : null)),
      fetch("assets/terrain/height.bin").then((r) => (r.ok ? r.arrayBuffer() : null)),
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
    return { heightAt, surfaceAt, texture, meta };
  } catch {
    return FLAT;
  }
}
