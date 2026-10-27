"""Paint a London plane sprig for the leaf cards (public/assets/trees/leaf_plane.png): broad
five-lobed, maple-like leaves on a twig, on a transparent background, like Ez-Tree's leaf images.

    python tools/trees/plane_leaf.py
"""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "public", "assets", "trees")
os.makedirs(OUT, exist_ok=True)
S = 1024
rnd = random.Random(9)
im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(im)


def leaf(cx, cy, size, ang, shade):
    """A plane leaf: five pointed lobes from the stalk, with veins."""
    pts = []
    lobes = [(-1.25, 0.62), (-0.62, 0.92), (0.0, 1.0), (0.62, 0.92), (1.25, 0.62)]
    steps = 60
    for i in range(steps + 1):
        a = -1.6 + 3.2 * i / steps
        r = 0.55
        for la, lr in lobes:
            r = max(r, lr * max(0.0, 1 - abs(a - la) / 0.62) ** 0.6)
        r *= 1 + 0.06 * math.sin(i * 1.7)  # toothed edge
        pts.append((cx + math.sin(a + ang) * r * size, cy - math.cos(a + ang) * r * size))
    pts.append((cx, cy))
    g = int(110 + shade * 60)
    d.polygon(pts, fill=(int(60 + shade * 40), g, int(30 + shade * 20), 255))
    for la, lr in lobes:  # veins
        d.line((cx, cy, cx + math.sin(la + ang) * lr * size * 0.85, cy - math.cos(la + ang) * lr * size * 0.85), fill=(150, 175, 90, 255), width=3)
    d.line((cx, cy, cx - math.sin(ang) * size * 0.35, cy + math.cos(ang) * size * 0.35), fill=(110, 95, 50, 255), width=4)


# The twig, then leaves along it at alternating angles.
twig = [(512 + 30 * math.sin(t * 3), 1000 - t * 900) for t in [i / 20 for i in range(21)]]
d.line(twig, fill=(95, 75, 50, 255), width=9)
for k in range(9):
    t = 0.12 + k * 0.1
    x, y = 512 + 30 * math.sin(t * 3), 1000 - t * 900
    side = 1 if k % 2 else -1
    ang = side * rnd.uniform(0.5, 1.0)
    lx, ly = x + side * 130, y - 100
    d.line((x, y, lx, ly), fill=(95, 75, 50, 255), width=5)
    leaf(lx, ly, rnd.uniform(200, 250), ang, rnd.random())
leaf(512 + 30 * math.sin(3), 110, 190, 0.1, 0.6)
im = im.filter(ImageFilter.SMOOTH)
im.save(os.path.join(OUT, "leaf_plane.png"))
print("wrote", os.path.join(OUT, "leaf_plane.png"))
