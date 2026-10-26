"""Paint the signs and patterned surfaces the landmark models use (public/assets/landmarks/textures/).

    python tools/landmarks/signs.py

The LONDON ZOO fascia over the turnstiles, the carved REPTILE HOUSE lettering, the Sasan Gir station
board and village shop signs in Land of the Lions, and the turnstile roller shutters.
"""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "public", "assets", "landmarks", "textures")
os.makedirs(OUT, exist_ok=True)
FONTS = "C:/Windows/Fonts"


def font(names, size):
    for n in names:
        try:
            return ImageFont.truetype(os.path.join(FONTS, n), size)
        except OSError:
            continue
    return ImageFont.load_default()


def centred(d, box, text, f, fill, stroke=0, stroke_fill=None):
    x0, y0, x1, y1 = box
    l, t, r, b = d.textbbox((0, 0), text, font=f, stroke_width=stroke)
    d.text(((x0 + x1 - (r - l)) / 2 - l, (y0 + y1 - (b - t)) / 2 - t), text, font=f, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)


def zoo_banner():
    """Jungle fascia over the turnstiles: leaves, painted animals, LONDON ZOO."""
    W, H = 2048, 256
    im = Image.new("RGB", (W, H), (18, 64, 32))
    d = ImageDraw.Draw(im)
    rnd = random.Random(4)
    for _ in range(900):  # layered leaves
        x, y = rnd.uniform(0, W), rnd.uniform(-20, H + 20)
        g = rnd.randint(70, 170)
        r = rnd.uniform(14, 46)
        a = rnd.uniform(0, math.pi)
        pts = [(x + math.cos(a + t) * r * (1 if k % 2 == 0 else 0.35), y + math.sin(a + t) * r * (1 if k % 2 == 0 else 0.35))
               for k, t in enumerate([i * math.pi / 2 for i in range(4)])]
        d.polygon(pts, fill=(rnd.randint(20, 60), g, rnd.randint(30, 70)))
    # Painted animals: a zebra panel, a tiger, a giraffe, a lion's head, a penguin.
    def zebra(x):
        d.ellipse((x, 70, x + 230, 200), fill=(235, 235, 230))
        for i in range(0, 230, 22):
            d.polygon([(x + i, 70), (x + i + 9, 70), (x + i + 18, 200), (x + i + 9, 200)], fill=(20, 20, 20))
        d.ellipse((x + 200, 40, x + 280, 120), fill=(235, 235, 230))

    def tiger(x):
        d.ellipse((x, 90, x + 250, 210), fill=(222, 128, 40))
        for i in range(0, 250, 26):
            d.line((x + i, 95, x + i + 12, 205), fill=(25, 20, 15), width=7)
        d.ellipse((x + 210, 60, x + 300, 150), fill=(222, 128, 40))
        d.ellipse((x + 235, 85, x + 250, 100), fill=(30, 30, 20))

    def giraffe(x):
        d.rectangle((x + 60, 20, x + 95, 200), fill=(214, 160, 70))
        d.ellipse((x, 130, x + 170, 230), fill=(214, 160, 70))
        d.ellipse((x + 55, 0, x + 135, 50), fill=(214, 160, 70))
        for i in range(14):
            cx, cy = x + 20 + (i * 37) % 140, 140 + (i * 23) % 80
            d.ellipse((cx, cy, cx + 22, cy + 18), fill=(130, 70, 30))

    def lion(x):
        d.ellipse((x, 40, x + 200, 240), fill=(120, 70, 30))
        d.ellipse((x + 40, 80, x + 160, 200), fill=(214, 168, 96))
        d.ellipse((x + 70, 120, x + 85, 135), fill=(30, 20, 10))
        d.ellipse((x + 115, 120, x + 130, 135), fill=(30, 20, 10))

    def penguin(x):
        d.ellipse((x, 60, x + 90, 230), fill=(20, 20, 24))
        d.ellipse((x + 22, 95, x + 80, 225), fill=(240, 240, 236))
        d.polygon([(x + 70, 75), (x + 110, 85), (x + 70, 92)], fill=(230, 140, 40))

    zebra(40); lion(330); tiger(1450); giraffe(1760); penguin(1300)
    im = im.filter(ImageFilter.GaussianBlur(1.2))
    d = ImageDraw.Draw(im)
    centred(d, (560, 0, 1260, H), "LONDON ZOO", font(["impact.ttf", "arialbd.ttf"], 150), (255, 255, 255), 6, (12, 40, 20))
    d.text((580, 22), "ZSL", font=font(["arialbd.ttf"], 44), fill=(255, 255, 255))
    im.save(os.path.join(OUT, "banner_zoo.png"))


def carved(text, name, size=(1024, 160)):
    """Lettering cut into Portland stone."""
    im = Image.new("RGB", size, (214, 206, 188))
    rnd = random.Random(1)
    px = im.load()
    for _ in range(size[0] * size[1] // 6):
        x, y = rnd.randrange(size[0]), rnd.randrange(size[1])
        v = rnd.randint(-14, 10)
        r, g, b = px[x, y]
        px[x, y] = (r + v, g + v, b + v)
    d = ImageDraw.Draw(im)
    f = font(["timesbd.ttf", "georgiab.ttf", "georgia.ttf"], int(size[1] * 0.62))
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    x, y = (size[0] - (r - l)) / 2 - l, (size[1] - (b - t)) / 2 - t
    d.text((x + 3, y + 3), text, font=f, fill=(238, 232, 218))  # lit lower edge of the cut
    d.text((x, y), text, font=f, fill=(96, 88, 76))
    im.save(os.path.join(OUT, name))


def board(text, name, bg, fg, sub=None, size=(1024, 256), border=None):
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    if border:
        d.rectangle((8, 8, size[0] - 9, size[1] - 9), outline=border, width=12)
    if sub:
        centred(d, (0, 10, size[0], size[1] * 0.68), text, font(["arialbd.ttf"], int(size[1] * 0.44)), fg)
        centred(d, (0, size[1] * 0.62, size[0], size[1] - 16), sub, font(["arial.ttf"], int(size[1] * 0.2)), fg)
    else:
        centred(d, (0, 0, size[0], size[1]), text, font(["arialbd.ttf"], int(size[1] * 0.5)), fg)
    # Weathering: faded patches and grime.
    rnd = random.Random(hash(name) & 0xFFFF)
    over = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    for _ in range(60):
        x, y, r = rnd.uniform(0, size[0]), rnd.uniform(0, size[1]), rnd.uniform(10, 60)
        od.ellipse((x - r, y - r, x + r, y + r), fill=(120, 100, 80, rnd.randint(8, 28)))
    im = Image.alpha_composite(im.convert("RGBA"), over.filter(ImageFilter.GaussianBlur(8))).convert("RGB")
    im.save(os.path.join(OUT, name))


def shutter():
    im = Image.new("RGB", (64, 256), (214, 216, 214))
    d = ImageDraw.Draw(im)
    for y in range(0, 256, 16):
        d.rectangle((0, y + 12, 64, y + 15), fill=(160, 164, 164))
        d.rectangle((0, y, 64, y + 2), fill=(236, 238, 236))
    im.save(os.path.join(OUT, "shutter.png"))


zoo_banner()
carved("REPTILE HOUSE", "sign_reptile.png")
carved("PENGUIN POOL", "sign_penguin.png")
board("SASAN GIR", "sign_station.png", (246, 196, 30), (20, 20, 20), sub="JUNCTION  ·  RAILWAY STATION", border=(20, 20, 20))
board("CHAI", "sign_chai.png", (196, 40, 40), (255, 236, 160), sub="GARAM GARAM  ·  FRESH TEA")
board("GIR STORES", "sign_stores.png", (30, 120, 160), (255, 255, 255), sub="GENERAL MERCHANT  ·  SINCE 1972")
board("SWEETS", "sign_sweets.png", (236, 120, 30), (60, 20, 10), sub="MITHAI  ·  FARSAN")
board("TAILOR", "sign_tailor.png", (60, 140, 70), (255, 250, 230), sub="ALTERATIONS  ·  PHONE")
shutter()
print("signs written to", OUT)
