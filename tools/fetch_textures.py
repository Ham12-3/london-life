"""Download the CC0 Poly Haven PBR textures the simulation uses (1k JPG: colour, OpenGL normal, AO/rough/metal).

    python tools/fetch_textures.py

Files land in public/assets/textures/<id>/{diff,nor,arm}.jpg. Already-downloaded files are skipped.
Also fetches three.js's water normal map (MIT) for the ponds and canal.
"""
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "public" / "assets" / "textures"
RES = "1k"

# Poly Haven ids, see https://polyhaven.com/textures
TEXTURES = [
    "brick_wall_02",        # red London brick
    "brick_wall_003",       # buff/yellow stock brick
    "white_stucco",         # painted render (tinted per building)
    "concrete_floor_02",    # flat roofs, interior floors, service corridors
    "sparse_grass",         # lawns
    "forest_floor",         # woodland and scrub
    "park_dirt",            # enclosures and playgrounds
    "coast_sand_01",        # sand
    "aerial_rocks_02",      # rock
    "concrete_pavement",    # footways and paved squares
    "gravel_ground_01",     # unpaved paths
    "asphalt_02",           # roads and cycleways
    "precast_stone_paving", # steps
    "wood_planks",          # bridges
    "roof_slates_02",       # slate roofs on houses and small zoo buildings
    "clay_roof_tiles",      # clay tile roofs on pavilions and kiosks
    "corrugated_iron_02",   # canopies and roofs (Tiger Territory, Land of the Lions)
    "rusty_corrugated_iron",  # village roofs in Land of the Lions
    "reed_roof_04",         # thatch (Gorilla Kingdom)
    "red_sandstone_wall",   # the Hindu temple in Land of the Lions
    "red_plaster_weathered",  # weathered village walls
    "blue_plaster_weathered",
    "old_sandstone_02",     # stone dressings
    "wood_plank_wall",      # weathered timber pavilions
    "bark_platanus",        # London plane bark: the camouflage-patched trunks all over the zoo and park
]
MAPS = {"diff": "Diffuse", "nor": "nor_gl", "arm": "arm"}
EXTRA = {
    "water/normals.jpg": "https://raw.githubusercontent.com/mrdoob/three.js/r170/examples/textures/waternormals.jpg",
}


def get(url, dest):
    if dest.exists() and dest.stat().st_size > 0:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "london-life-zoo-sim"})
    with urllib.request.urlopen(req) as r:
        dest.write_bytes(r.read())
    return True


def main():
    for tid in TEXTURES:
        req = urllib.request.Request(f"https://api.polyhaven.com/files/{tid}", headers={"User-Agent": "london-life-zoo-sim"})
        files = json.load(urllib.request.urlopen(req))
        for short, key in MAPS.items():
            url = files[key][RES]["jpg"]["url"]
            if get(url, OUT / tid / f"{short}.jpg"):
                print(f"  {tid}/{short}.jpg")
    for rel, url in EXTRA.items():
        if get(url, OUT / rel):
            print(f"  {rel}")
    total = sum(f.stat().st_size for f in OUT.rglob("*.jpg"))
    print(f"Textures ready in {OUT} ({total / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
