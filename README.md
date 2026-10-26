# london-life

A first-person, walkable simulation of **ZSL London Zoo**, running in the browser (Three.js, WebGPU).

The world comes from OpenStreetMap, so it follows the real zoo. Every mapped path, building, enclosure, fence, wall, hedge, pond, the Regent's Canal, the Outer Circle, and all ~350 mapped trees are in it. Every zoo building has doorways, so you can walk in and out. Placeholder animals wander inside their real enclosure outlines.

Captured 3D assets get layered on top:

- **Buildings and enclosures** come from Google Flow videos turned into Gaussian splats.
- **Animals and props** come from image-to-3D models (GLB).

## Run it

```bash
npm install
npm run dev
```

Open http://localhost:5173 in Chrome or Edge (WebGPU) and click to start. The PBR textures are in
`public/assets/textures`; if they're missing, run `python tools/fetch_textures.py`.

| Key | Action |
| --- | --- |
| W A S D / arrows | Walk |
| Shift | Run |
| Mouse | Look |
| T | Search places and jump there |
| M | Full map (click to teleport) |
| N | Fly mode (Q/E down/up) |
| P | Graphics quality: Auto, High, Medium, Low |
| Esc | Pause |

Auto quality starts on Medium, steps down below ~40 fps and tries a step up while holding 60.
Add `?gpu` to the URL to turn on GPU timers (`zoo.renderer.info.render.timestamp`) for profiling.

## How it's built

| Path | What |
| --- | --- |
| `data/osm-zoo.json` | Raw OpenStreetMap extract (ODbL, © OpenStreetMap contributors) |
| `tools/build_world.py` | OSM → `public/world.json` in local metres, plus doorways and fence gaps where paths cross. Also writes `tools/shotlist.json` |
| `src/render.js` | WebGPU renderer: physical sky with clouds, sky lighting, cascaded sun shadows, haze, GTAO, TAAU upscaling, quality levels |
| `src/world.js` | Ground, paths, buildings (walls with doorways, floors, ceilings, roofs), fences, water, furniture, labels, collision |
| `src/buildings.js` | Detail for every building: plinth, cornice or parapet, windows per storey, door surrounds and front doors, hipped slate/tile roofs from the outline's straight skeleton |
| `src/materials.js` | Poly Haven PBR surfaces, mapped in world-space metres (brick, render, paving, asphalt, lawn, dirt…) |
| `src/trees.js` | Ez-Tree oaks, ashes and aspens with wind sway near you; baked impostor cards further out |
| `src/grass.js` | Wind-blown grass blades around you, grown from a density mask of the map's lawns |
| `src/water.js` | Ponds and canal: drifting ripples with sky reflections |
| `tools/fetch_textures.py` | Downloads the CC0 Poly Haven textures (1k) and the three.js water normal map |
| `src/animals.js` | Animals per enclosure: Blender models, one instanced draw per species, legs swung on the GPU as they walk |
| `src/terrain.js` | Ground levels: `heightAt` for everything standing on the ground, and the tunnel floor under the Outer Circle for walkers who came down the ramp |
| `src/furniture.js` | Blender-modelled benches, bins, Victorian lamp posts, fountains, picnic tables, cycle stands (instanced) and railings (drawn within 70 m) |
| `src/landmarks.js` | Loads the Blender landmark models and gives their surfaces the zoo's PBR materials |
| `src/player.js` | First-person controller and collision |
| `src/hud.js` | Location readout, minimap, full map, places search |
| `src/assets.js` | Loads GLBs listed in `public/assets/manifest.json` (the splats there are retired: their viewer needs WebGL) |

Rebuild the world after changing the converter: `npm run world`.

## Landmarks and animals (Blender)

The zoo's famous buildings and all its animals are modelled in Blender by script, so they can be
rebuilt or tweaked at any time. Your installed Blender is used headless (the Microsoft Store build
runs through its `blender-launcher` alias).

| Path | What |
| --- | --- |
| `tools/landmarks/prepare.mjs` | Real footprints of each landmark from `world.json`, plus straight-skeleton hipped roofs |
| `tools/landmarks/build.py` | Models the Outer Circle main entrance (lodges, turnstiles, canopy and LONDON ZOO fascia), the 1927 Reptile House, Gorilla Kingdom, Rainforest Life, Land of the Lions (Sasan Gir station, high street, temple), Tiger Territory (mesh canopy on masts), the Mappin Terraces (concrete cast as rock), Guy the Gorilla in bronze, the Lubetkin Penguin Pool, Snowdon Aviary, Casson Pavilion, Clock Tower, Giraffe House, Raven Cage and Blackburn Pavilion on their footprints; writes `public/assets/landmarks/*.glb` and `landmarks.json` |
| `tools/landmarks/signs.py` | Paints the signs, banners and entrance mosaics the landmarks use (`public/assets/landmarks/textures/`) |
| `tools/animals/build.py` | 23 species built with Blender's Skin modifier, coats painted into vertex colours; writes `public/assets/animals/*.glb` and `animals.json` (leg joints for the walk cycle) |
| `tools/furniture/build.py` | Models the street furniture and a 2.5 m railing section in Blender; writes `public/assets/furniture/*.glb` |
| `tools/furniture/place.py` | Where it all goes: mapped items plus lamps, benches and bins along the paths, railings along every fence (`placements.json`) |
| `tools/trees/plane_leaf.py` | Paints the London plane leaf sprig for the plane trees (which also use Poly Haven's scanned plane bark) |
| `tools/animals/preview.py` | Renders all animals side by side to `work/animals_preview.png` |

```bash
node tools/landmarks/prepare.mjs
blender --background --factory-startup --python tools/landmarks/build.py
blender --background --factory-startup --python tools/animals/build.py
```

Add species names after `--` to rebuild only those (e.g. `-- clock-tower`). A landmark replaces the
generated building on its footprint (its walls stay solid for collision).

## The zoo in Blender (live, through the Blender MCP add-on)

With Blender open and the BlenderMCP add-on connected (sidebar > BlenderMCP > Connect), the whole
zoo is built and refined inside Blender, and the buildings are exported back to the web app.
`tools/blender_mcp.py` talks to the add-on the same way the MCP server does.

| Path | What |
| --- | --- |
| `tools/blender_mcp.py` | `info`, `run <script>`, `shot <png>`, `cmd <type> <json>` against the running add-on |
| `tools/blender_world/scene.py` | The whole zoo from `world.json`: ground, paths, water, buildings, landmarks, trees, sky, sun, camera |
| `tools/blender_world/prepare.mjs` | Per building: outline, doorways, window style and roof skeleton (same rules as the web app) |
| `tools/blender_world/buildings.py` | Buildings with real openings: recessed windows (glass, frames, bars, sills, lintels), doorways and surrounds, front doors, plinths, cornices or parapets, hipped roofs with soffits and fascias |
| `tools/blender_world/trees_export.mjs`, `trees.py` | The web app's Ez-Tree trees, with bark and leaf textures, at every mapped tree |
| `tools/blender_world/materials.py` | Poly Haven materials in Blender; `render_settings.py` (Eevee ray tracing), `camera.py`, `view.py` |
| `tools/blender_world/landmarks_reload.py` | Reloads rebuilt landmark models into the Blender zoo without rebuilding the scene |
| `tools/blender_world/furniture.py` | Places the furniture and railings in the Blender zoo from the same placements |
| `tools/terrain/height.py` | The height map: the Regent's Canal in its cutting (water 5.5 m down, towpath, banks) and the tunnel ramps under the Outer Circle; ground level under buildings (`public/assets/terrain/`) |
| `tools/blender_world/terrain.py` | Drops the Blender ground, paths and canal onto the height map; builds the canal walls, tunnel ramps, vaulted brick tunnels with stone portals, and bridge parapets and piers |
| `tools/blender_world/corridors.py`, `export_terrain.py` | Clears the ground out of the open tunnel ramps; exports `public/assets/blender/terrain.glb` for the app |
| `tools/blender_world/export.py` | Writes `public/assets/blender/buildings.glb` (Draco); the app then uses it instead of generating buildings |
| `tools/blender_world/save_copy.py`, `bake_ao.py` | Baked lighting: Cycles ambient occlusion (how much open sky each point sees, within 7 m): an atlas each for the buildings and the earthworks on a second UV map (`public/assets/blender/ao_*.jpg`, ~15 and ~7 cm a pixel), and one top-down image of the ground (`public/assets/terrain/ao.jpg`, ~22 cm a pixel); re-exports both GLBs with the second UV map |

```bash
node tools/blender_world/prepare.mjs
python tools/blender_mcp.py run tools/blender_world/scene.py
python tools/blender_mcp.py run tools/blender_world/buildings.py
node tools/blender_world/trees_export.mjs
python tools/blender_mcp.py run tools/blender_world/trees.py
python tools/blender_mcp.py run tools/blender_world/export.py
```

The app applies the baked occlusion to sky light only, so the moving sun and its shadows stay live
while wall bases, doorways, window reveals, the canal cutting, tunnel ramps and the lawn under the
trees darken the way they do outdoors. Bake on a saved copy of the scene, in the background (about
40 minutes on a desktop CPU; `-- ground` or `-- atlas` redoes just one part):

```bash
python tools/blender_mcp.py run tools/blender_world/save_copy.py
blender --background work/blender/zoo.blend --python tools/blender_world/bake_ao.py
```

## Asset pipeline

### 1. Generate clips in Google Flow

`tools/shotlist.json` has one prompt per named place in the zoo (96 shots). Use the cheapest settings: **Omni 1.1 Flash · 360p · 8s · x1 = 6 credits per clip**. Prompts ask for a slow orbit around a completely static scene, because that's what reconstruction needs.

Save each clip as `assets/videos/NN-<shot-id>.mp4`.

### 2. Install the tools (once)

Both go in the git-ignored `.tools/` folder, where the scripts find them automatically:

- [COLMAP 4.2.1](https://github.com/colmap/colmap/releases/tag/4.2.1): `colmap-x64-windows-nocuda.zip`, unzipped to `.tools/colmap/`
- [Brush v0.3.0](https://github.com/ArthurBrussee/brush/releases/tag/v0.3.0): `brush-app-x86_64-pc-windows-msvc.zip`, unzipped to `.tools/brush/`

### 3. Clip → splat

```bash
powershell -File tools/video_to_splat.ps1 -Video assets/videos/09-casson-pavilion.mp4 -Name casson-pavilion
```

What happens:

1. ffmpeg extracts 64 frames.
2. COLMAP solves the camera poses on the CPU (~5 min).
3. Brush trains 7,000 steps (~16 min on Intel Iris Xe) and writes `public/assets/splats/<name>.ply`.

Add `-SkipPoses` to retrain from an existing COLMAP solve.

On this laptop's Intel GPU, Brush 0.3 crashes at random points during training (a GPU-timing panic). The script works around it:

- It forces Vulkan.
- It saves a checkpoint every 500 steps and resumes from the last one after a crash. For example, Casson survived 4 crashes.

### 4. Fit it to the map

```bash
python -I tools/align_splat.py casson-pavilion "Casson Pavilion"
```

The script puts the splat on its real OSM footprint:

- **Up** comes from the camera orientation.
- **The scene centre** is the median of the sparse 3D points. That works for orbits and walk-through clips alike.
- **Scale** puts the cameras at eye height (1.7 m), limited to 0.6–1.6× the footprint size.
- **Rotation:** the scene sits on the footprint centre, turned so the side the clip filmed faces the nearest walkway.
- **Cropping** keeps only the footprint area and drops the AI's sky haze (splats over 1.5 m or nearly transparent).
- **Manifest:** it writes `<name>-fit.ply` and its manifest entry, including a `matrix` and the scene `centre`.

An earlier version searched for the scale and rotation that best filled the footprint. That proved unreliable, because the AI invents its own buildings.

A splat only looks right from the sides the clips saw. A single 8s Omni Flash orbit only sweeps about 20° around a building.

**Covering the whole building.** Separate prompts for "the east side" don't work: each generation invents a different building, so COLMAP can't merge them. Instead, chain continuations:

1. Extract the last frame of the clip (`ffmpeg -sseof -0.1 -i clip.mp4 -frames:v 1 last.png`).
2. In Flow, switch to **Frames** mode and set that image as the **Start** frame. It's still 6 credits at 360p/8s.
3. Prompt the camera to "continue the same orbit clockwise… sweeping ~120° further".
4. Repeat from the new clip's last frame.
5. Solve all the clips together. Each continuation's duplicate first frame is skipped:

```bash
powershell -File tools/video_to_splat.ps1 -Video assets/videos/09-casson-pavilion.mp4,assets/videos/09b-casson-pavilion-north.mp4,assets/videos/09c-casson-pavilion-east.mp4 -Name casson-pavilion
```

### Batch: every clip at once

```bash
powershell -File tools/batch_splats.ps1 -Stage poses
powershell -File tools/batch_splats.ps1 -Stage train -Steps 2000
```

Run both at the same time, in two terminals:

- **poses** solves cameras on the CPU and writes `work/<id>/poses.ok`.
- **train** waits for each place's poses, then trains it in Brush, fits it with `align_splat.py`, adds it to the manifest and marks it `splat` in the shot list.

Both stages re-scan for new clips after each pass and skip finished or failed places, so re-running is safe. Progress is logged in `work/batch-poses.log` and `work/batch-train.log`.

The simulation streams splats in: each one loads when you come within about 180 m, and is hidden beyond about 230 m. Inside a captured place, the map's trees and placeholder animals are skipped, because the splat already shows them.

### Faster: train on a Colab GPU

The laptop's integrated GPU takes about 8½ minutes per place. A Colab T4 is much faster. Camera solving still runs locally, and only the training moves.

1. **Pack** the solved places into uploads under 10 MB. Each holds the frames and a slimmed COLMAP model:

   ```bash
   python -I tools/colab_transfer.py pack
   ```

   The zips land in `work/colab-up/batch-NN.zip`.
2. **Upload** `tools/colab_train.py` and the batch zips to the Colab session's files (`/content`), then run in a cell:

   ```
   !pip -q install gsplat imageio && python /content/colab_train.py
   ```

   This trains every uploaded place at 5,000 steps with `gsplat`, then writes `/content/splats-<time>.zip`.
3. **Download** that zip and bring it home:

   ```bash
   python -I tools/colab_transfer.py unpack <zip>
   ```

   Each splat is fitted to the map, added to the manifest and marked done.

### 5. Place it by hand (optional)

`align_splat.py` writes this entry for you. To place an asset by hand, add one to `public/assets/manifest.json`:

```json
{
  "items": [
    {
      "id": "main-entrance",
      "type": "splat",
      "url": "assets/splats/main-entrance.ply",
      "anchor": "London Zoo Entrance",
      "replacesBuilding": true,
      "rotationY": 0,
      "scale": 1,
      "offset": [0, 0, 0]
    },
    {
      "id": "penguin",
      "type": "glb",
      "url": "assets/models/penguin.glb",
      "anchor": "Penguin Beach",
      "species": "Humboldt penguin"
    }
  ]
}
```

- `anchor` is any area, building or point name from the map. You can use `position: [x, y, z]` instead.
- `replacesBuilding` hides that building's placeholder walls. Its collision stays, so you still can't walk through it.
- `species` turns off that species' placeholder animals.

Splats from AI video have no real-world scale. Tune `scale`, `rotationY` and `offset` by eye.

## Known limits

- AI video invents details, so splats will look *like* London Zoo, not match it exactly. The layout itself is accurate.
- 360p clips give soft splats. Use the 720p upscale download for hero areas if blur matters more than credits.
- The ground is flat: no terrain heights, and the tunnels under the Outer Circle are drawn as surface paths.
