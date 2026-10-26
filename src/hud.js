// On-screen overlay: location readout, rotating minimap, full map with click-to-teleport, and a places search.
const MAP_SCALE = 1; // canvas pixels per metre in the pre-rendered map

function drawWorldMap(world) {
  const all = [...world.buildings.flatMap((b) => b.pts), ...world.paths.flatMap((p) => p.pts)];
  const minX = Math.min(...all.map((p) => p[0])) - 20, maxX = Math.max(...all.map((p) => p[0])) + 20;
  const minZ = Math.min(...all.map((p) => p[1])) - 20, maxZ = Math.max(...all.map((p) => p[1])) + 20;
  const c = document.createElement("canvas");
  c.width = Math.ceil((maxX - minX) * MAP_SCALE);
  c.height = Math.ceil((maxZ - minZ) * MAP_SCALE);
  const g = c.getContext("2d");
  const tx = (x) => (x - minX) * MAP_SCALE, tz = (z) => (z - minZ) * MAP_SCALE;
  const poly = (pts) => {
    g.beginPath();
    pts.forEach(([x, z], i) => (i ? g.lineTo(tx(x), tz(z)) : g.moveTo(tx(x), tz(z))));
  };
  g.fillStyle = "#5f8a43";
  g.fillRect(0, 0, c.width, c.height);
  g.fillStyle = "#8f9a6c";
  world.zoo.forEach((r) => { poly(r); g.fill(); });
  const groundColors = { grass: "#79a552", garden: "#6c9e4a", wood: "#4f7a37", enclosure: "#a8976a", sand: "#dcc58e", rock: "#8d8a83", scrub: "#5d7f3c" };
  for (const gp of world.ground) {
    if (!groundColors[gp.kind]) continue;
    g.fillStyle = groundColors[gp.kind];
    poly(gp.pts); g.fill();
  }
  g.fillStyle = "#3d6b73";
  g.strokeStyle = "#3d6b73";
  for (const w of world.water) {
    if (w.line) { g.lineWidth = w.w * MAP_SCALE; poly(w.line); g.stroke(); }
    else { poly(w.pts); g.fill(); }
  }
  g.lineCap = g.lineJoin = "round";
  for (const p of world.paths) {
    g.strokeStyle = p.kind === "road" ? "#555" : "#e6dcc6";
    g.lineWidth = p.w * MAP_SCALE;
    poly(p.pts); g.stroke();
  }
  for (const b of world.buildings) {
    g.fillStyle = b.inZoo ? "#c9b896" : "#9a8f84";
    poly(b.pts); g.fill();
  }
  g.strokeStyle = "rgba(30,50,30,0.6)";
  g.lineWidth = 0.8;
  for (const br of world.barriers) { poly(br.pts); g.stroke(); }
  return { canvas: c, minX, minZ };
}

export class Hud {
  constructor(world, worldInfo, player) {
    this.world = world;
    this.info = worldInfo;
    this.player = player;
    this.map = drawWorldMap(world);
    this.where = document.getElementById("where");
    this.mini = document.getElementById("minimap");
    this.miniCtx = this.mini.getContext("2d");
    this.big = document.getElementById("bigmap");
    this.bigCanvas = document.getElementById("bigmap-canvas");
    this.places = document.getElementById("places");
    this.search = document.getElementById("places-search");
    this.list = document.getElementById("places-list");
    this.mode = document.getElementById("mode");
    this.lastWhere = "";

    this.placeIndex = this.buildPlaces();
    this.bigCanvas.width = this.map.canvas.width;
    this.bigCanvas.height = this.map.canvas.height;
    this.bigCanvas.addEventListener("click", (e) => {
      const r = this.bigCanvas.getBoundingClientRect();
      const x = ((e.clientX - r.left) / r.width) * this.map.canvas.width / MAP_SCALE + this.map.minX;
      const z = ((e.clientY - r.top) / r.height) * this.map.canvas.height / MAP_SCALE + this.map.minZ;
      this.player.teleport(x, z);
      this.close();
      this.player.controls.lock();
    });
    this.search.addEventListener("input", () => this.renderPlaces());
    this.search.addEventListener("keydown", (e) => {
      if (e.key === "Enter") this.list.querySelector("button")?.click();
      if (e.key === "Escape") this.close();
    });
    addEventListener("keydown", (e) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.code === "KeyM") this.toggle(this.big);
      if (e.code === "KeyT") this.toggle(this.places);
    });
    document.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => this.toggle(document.getElementById(b.dataset.open))));
  }

  buildPlaces() {
    const seen = new Set();
    const out = [];
    const add = (name, x, z, kind) => {
      if (!name || seen.has(name)) return;
      seen.add(name);
      out.push({ name, x, z, kind });
    };
    for (const a of this.world.areas) add(a.name, a.c[0], a.c[1], a.enclosure ? "Enclosure" : "Attraction");
    for (const b of this.info.buildings) if (b.inZoo && b.name) {
      const [dx, dz] = b.doors[0] || b.pts[0];
      add(b.name, dx, dz, "Building");
    }
    for (const p of this.world.pois) add(p.name, p.x, p.z, p.kind === "gate" ? "Gate" : "Point of interest");
    return out.sort((a, b) => a.name.localeCompare(b.name));
  }

  renderPlaces() {
    const q = this.search.value.trim().toLowerCase();
    this.list.replaceChildren(...this.placeIndex.filter((p) => p.name.toLowerCase().includes(q)).map((p) => {
      const b = document.createElement("button");
      b.innerHTML = `<span>${p.name}</span><small>${p.kind}</small>`;
      b.addEventListener("click", () => {
        // Arrive on the nearest path a few steps back, facing the place.
        let [x, z] = this.info.nearestPathPoint(p.x, p.z) || [p.x, p.z];
        const d = Math.hypot(x - p.x, z - p.z);
        if (d > 0.5) {
          const bx = x + ((x - p.x) / d) * 3, bz = z + ((z - p.z) / d) * 3;
          if (!this.info.collision.inWater(bx, bz)) [x, z] = this.info.collision.resolve(bx, bz, 0.35);
        }
        this.player.teleport(x, z, p.x, p.z);
        this.close();
        this.player.controls.lock();
      });
      return b;
    }));
  }

  toggle(panel) {
    const open = panel.hidden;
    this.close();
    if (open) {
      panel.hidden = false;
      this.player.controls.unlock();
      if (panel === this.places) { this.search.value = ""; this.renderPlaces(); this.search.focus(); }
      if (panel === this.big) this.drawBig();
    }
  }

  close() {
    this.big.hidden = true;
    this.places.hidden = true;
  }

  get panelOpen() {
    return !this.big.hidden || !this.places.hidden;
  }

  drawBig() {
    const g = this.bigCanvas.getContext("2d");
    g.drawImage(this.map.canvas, 0, 0);
    const pos = this.player.camera.position;
    const x = (pos.x - this.map.minX) * MAP_SCALE, z = (pos.z - this.map.minZ) * MAP_SCALE;
    g.fillStyle = "#e33";
    g.beginPath(); g.arc(x, z, 6, 0, Math.PI * 2); g.fill();
    g.font = "600 11px system-ui";
    g.fillStyle = "#13261a";
    for (const a of this.world.areas) g.fillText(a.name, (a.c[0] - this.map.minX) * MAP_SCALE - 20, (a.c[1] - this.map.minZ) * MAP_SCALE);
  }

  update() {
    const pos = this.player.camera.position;
    const w = this.info.whereAmI(pos.x, pos.z);
    const parts = [];
    if (w.building) parts.push(`Inside ${w.building}`);
    if (w.area && w.area !== w.building) parts.push(w.area);
    if (!parts.length) parts.push(w.inZoo ? "ZSL London Zoo" : "Regent's Park");
    const text = parts.join(" · ");
    if (text !== this.lastWhere) {
      this.where.textContent = text;
      this.lastWhere = text;
    }
    this.mode.textContent = this.player.fly ? "Fly mode (N to walk)" : "";

    // Minimap: 160 m across, rotated so "up" is the way you're facing.
    const g = this.miniCtx, size = this.mini.width, span = 160;
    const k = size / span;
    g.save();
    g.clearRect(0, 0, size, size);
    g.beginPath(); g.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2); g.clip();
    g.translate(size / 2, size / 2);
    g.rotate(-this.player.heading());
    g.scale(k / MAP_SCALE, k / MAP_SCALE);
    g.drawImage(this.map.canvas, -(pos.x - this.map.minX) * MAP_SCALE, -(pos.z - this.map.minZ) * MAP_SCALE);
    g.restore();
    g.fillStyle = "#e33";
    g.beginPath();
    g.moveTo(size / 2, size / 2 - 8); g.lineTo(size / 2 - 6, size / 2 + 6); g.lineTo(size / 2 + 6, size / 2 + 6);
    g.fill();
  }
}
