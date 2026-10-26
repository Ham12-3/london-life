"""Queue the remaining in-zoo places in tools/shotlist.json with descriptive Flow prompts.

Usage:  python -I tools/batch_prompts.py
Each queued shot gets a number (its clip file is assets/videos/<num>-<id>.mp4) and a prompt.
Already generated shots are left alone.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTLIST = ROOT / "tools" / "shotlist.json"

TAIL = (" Bright overcast daylight, completely static scene, no people, nothing moving, "
        "sharp focus, photorealistic, consistent lighting, steady stabilised camera.")
ORBIT = "Slow, smooth orbit camera move at eye level around "
WALK = "Slow, smooth forward dolly camera move at eye level through "

# id -> description of the real place (ZSL London Zoo, Regent's Park).
PLACES = {
    # enclosures and attractions
    "tiny-giants": (WALK, "Tiny Giants, the indoor invertebrate exhibit: dark gallery with glowing glass tanks of insects and spiders, curved display walls"),
    "outback": (ORBIT, "the Outback walk-through paddock: red sandy ground, eucalyptus trees, low wooden fencing, a wallaby and an emu standing still"),
    "mangabeys": (ORBIT, "the mangabey monkey enclosure: mesh-covered climbing frames, ropes and wooden platforms among trees, a mangabey sitting still"),
    "butterfly-paradise": (WALK, "Butterfly Paradise, a long tunnel-shaped glasshouse full of tropical flowering plants with a winding path, butterflies resting on leaves"),
    "in-with-the-monkeys": (ORBIT, "In with the Monkeys, a walk-through woodland enclosure with a raised wooden path, tall trees and ropes, squirrel monkeys sitting still"),
    "mongooses": (ORBIT, "the mongoose enclosure: sandy ground, rocks, logs and a low glass viewing panel, mongooses sitting still"),
    "into-africa": (ORBIT, "Into Africa: open grassy paddocks with acacia-style trees, wooden fencing and a raised timber viewing deck, giraffes and zebras standing still"),
    "warthogs": (ORBIT, "the warthog paddock: dry earth, mud wallow, logs and wooden fencing, a warthog standing still"),
    "okapis": (ORBIT, "the okapi paddock: lush grass, dense shrubs and a wooden stable, an okapi standing still"),
    "zebras": (ORBIT, "the zebra paddock: open grass, a few trees and post-and-rail fencing, zebras standing still"),
    "giraffes": (ORBIT, "the giraffe paddock beside the historic Giraffe House: open grass, tall feeding posts, giraffes standing still"),
    "monkey-valley": (ORBIT, "Monkey Valley inside the Snowdon Aviary: a huge tent-like steel mesh aviary over a wooded valley with climbing structures, colobus monkeys sitting still"),
    "pygmy-hippos": (ORBIT, "the pygmy hippo enclosure: a pool with rocky banks, reeds, mud and tropical plants, a pygmy hippo standing still"),
    "macaws": (ORBIT, "the macaw aviary: tall mesh aviary with perches and trees, colourful macaws perched still"),
    "bactrian-camels": (ORBIT, "the Bactrian camel paddock: dusty sandy ground, a wooden shelter and fencing, two-humped camels standing still"),
    "bird-safari": (ORBIT, "Bird Safari, a walk-through aviary with a pond, reeds, wooden boardwalk and mesh roof, wading birds standing still"),
    "in-with-the-lemurs": (ORBIT, "In with the Lemurs, a walk-through woodland enclosure with a winding path, tall trees and ropes, ring-tailed lemurs sitting still"),
    "gibbons": (ORBIT, "the gibbon island: tall wooden climbing frames with ropes over grass, surrounded by a water moat, a gibbon hanging still"),
    "hanuman-langur": (ORBIT, "the Hanuman langur enclosure: climbing frames, rocks and trees behind mesh, a grey langur sitting still"),
    "otters": (ORBIT, "the otter enclosure: a clear pool with a small stream, rocks, logs and planting, an otter lying still on a rock"),
    "red-titi-monkeys": (ORBIT, "the red titi monkey enclosure: indoor-outdoor mesh habitat with branches and ropes, a red titi monkey sitting still"),
    "attenborough-komodo-dragon-house": (ORBIT, "the Attenborough Komodo Dragon House: a modern low building with timber cladding and big glass viewing windows onto a sandy, rocky habitat with a Komodo dragon lying still"),
    "giants-of-the-galápagos": (ORBIT, "Giants of the Galapagos, the giant tortoise house: a low timber building with a sandy outdoor yard, volcanic rocks and cacti, a giant tortoise resting"),
    "the-farmyard": (ORBIT, "the Farmyard children's area: red barn, wooden pens, hay bales and paths, pygmy goats and pigs standing still"),
    "coatis": (ORBIT, "the coati enclosure: climbing logs, rocks and tropical plants behind mesh, a coati sitting still"),
    "meerkats": (ORBIT, "the meerkat enclosure: sandy ground with rocks, burrows and a low glass wall, meerkats standing upright still"),
    "chinese-water-deer": (ORBIT, "the Chinese water deer paddock: long grass, shrubs and a small pond, a small deer standing still"),
    "african-harrier-hawk": (ORBIT, "the African harrier-hawk aviary: mesh aviary with dead branches and perches, a grey hawk perched still"),
    "diana-monkeys": (ORBIT, "the Diana monkey enclosure: tall climbing frames and ropes among trees behind mesh, a Diana monkey sitting still"),
    "celebes-crested-macaques": (ORBIT, "the Celebes crested macaque enclosure: rocks, a pool, climbing frames and tropical planting, a black crested macaque sitting still"),
    "the-secret-life-of-reptiles-and-amphibians-slora": (WALK, "The Secret Life of Reptiles and Amphibians, a modern indoor gallery of glass terrariums with lush planting and soft lighting"),
    "lubetkin-pool": (ORBIT, "the Lubetkin Penguin Pool, the famous 1934 modernist white concrete pool with two interlocking spiral ramps over an oval blue pool, Grade I listed"),
    "red-river-hogs": (ORBIT, "the red river hog paddock: muddy ground, logs, ferns and wooden fencing, a red-furred hog standing still"),
    # buildings
    "zoo-shop": (ORBIT, "the zoo gift shop: a modern single-storey building with large shop windows and a zoo sign, paved forecourt"),
    "the-terrace": (ORBIT, "The Terrace restaurant: a two-storey 1920s brick building with a large outdoor dining terrace and parasols"),
    "zoological-society-of-london-main-building": (ORBIT, "the Zoological Society of London main building: a three-storey 1910 red brick and stone office building with tall sash windows on the Outer Circle"),
    "north-pheasantry": (ORBIT, "the North Pheasantry: a long low row of mesh-fronted bird aviaries with a tiled roof"),
    "mappin-pavilion": (ORBIT, "the Mappin Pavilion beside the Mappin Terraces: an Edwardian pavilion in front of a tall artificial concrete mountain of terraces and rocky outcrops"),
    "the-beach-hut": (ORBIT, "The Beach Hut café by Penguin Beach: a small timber kiosk with a striped canopy and picnic tables"),
    "blackburn-pavilion": (ORBIT, "the Blackburn Pavilion: an ornate Victorian building with a domed glass roof and decorative ironwork, a tropical bird house"),
    "amreli-street-food": (ORBIT, "Amreli street food stall: a colourful Indian-themed food kiosk with painted signs near Land of the Lions"),
    "the-stork-and-ostrich-house": (ORBIT, "the historic Stork and Ostrich House: a Victorian brick building with arched doors and a wide paddock"),
    "community-and-learning-hub": (ORBIT, "the Community and Learning Hub: a modern education building with timber cladding and large windows"),
    "clock-tower": (ORBIT, "the Clock Tower at London Zoo: an 1828 Decimus Burton clock tower on a small brick building with a white cupola"),
    "raven-cage": (ORBIT, "the Raven Cage: a tall ornate Victorian wrought-iron birdcage with a domed top, Grade II listed"),
    "peckish-parrot-café": (ORBIT, "the Peckish Parrot café: a small modern café kiosk with colourful parrot signage and outdoor seating"),
    "activity-den": (ORBIT, "the Activity Den: a timber-clad children's activity building with large doors and colourful murals"),
    # animal spots
    "golden-headed-lion-tamarin": (ORBIT, "the golden-headed lion tamarin enclosure: mesh habitat with thin branches, vines and nest boxes, a small golden-maned monkey sitting still"),
    "fruit-bats": (WALK, "the fruit bat walk-through: a dim indoor tropical room with hanging branches and fruit bats hanging still upside down"),
    "ostriches": (ORBIT, "the ostrich paddock: sandy grass, a wooden shelter and fencing, an ostrich standing still"),
    "alpacas": (ORBIT, "the alpaca and llama paddock: grassy field, wooden fencing and a small barn, alpacas standing still"),
    "flamingos": (ORBIT, "the flamingo pool: a shallow pond with a muddy island and reeds, pink flamingos standing still on one leg"),
    "pelicans": (ORBIT, "the pelican pond: a large pond with a grassy bank and a small rocky island, white pelicans resting still"),
    # statues and landmarks
    "winnie-the-bear": (ORBIT, "the Winnie the Bear statue: a bronze statue of a black bear cub with a small boy, on a stone plinth among planting"),
    "guy-the-gorilla": (ORBIT, "the Guy the Gorilla statue: a large bronze sculpture of a seated silverback gorilla on a plinth"),
    "tim-hunkin-clock": (ORBIT, "the Tim Hunkin clock: a quirky mechanical clock sculpture with moving animal figures on a tall post"),
}


def main():
    s = json.loads(SHOTLIST.read_text(encoding="utf-8"))
    nums = [int(Path(sh["video"]).name.split("-")[0].rstrip("abc")) for sh in s["shots"] if sh.get("video")]
    nxt = max(nums, default=9) + 1
    queued = 0
    for shot in s["shots"]:
        sid = shot["id"]
        if sid not in PLACES or shot["status"] != "todo":
            continue
        move, desc = PLACES[sid]
        shot["prompt"] = move + desc + " at ZSL London Zoo, Regent's Park, London." + TAIL
        shot["status"] = "queued"
        shot["num"] = nxt
        nxt += 1
        queued += 1
    SHOTLIST.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    missing = sorted(set(PLACES) - {sh["id"] for sh in s["shots"]})
    print(f"queued {queued} shots ({queued * s['settings']['credits_per_clip']} credits); unknown ids: {missing}")


if __name__ == "__main__":
    main()
