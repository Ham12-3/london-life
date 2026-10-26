"""Model the zoo's animals in Blender and export one GLB per species.

    blender --background --factory-startup --python tools/animals/build.py [-- species ...]

Each animal is built from its anatomy: overlapping masses for the ribcage, belly, shoulder blades,
haunches and limb muscles, slim bones down to hooves or paws, a skull with muzzle, jaw, ears and
eyes, a neck of muscle, and the tail, humps, manes, horns and tusks each species has. They are
Blender metaballs, so the masses fuse into one smooth surface the way muscle runs under skin;
negative masses carve the flanks and eye sockets. The surface is smoothed and decimated, and the coat
(giraffe patches, zebra and tiger stripes, countershading, darker legs and muzzles, ringed tails,
fur-tone variation...) is painted into vertex colours using the body part each vertex belongs to.

Animals face +x (Blender), stand on z = 0, in metres. Alongside the GLBs, animals.json records each
species' leg pivots (where each leg leaves the body) so src/animals.js can swing the legs as they walk.
"""
import bmesh
import bpy
import json
import math
import os
import random
import sys
import zlib

import numpy as np
from mathutils import Euler, Matrix, Vector

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "public", "assets", "animals")
LOG = os.path.join(ROOT, "work", "animals.log")
log_file = None


def log(*a):
    global log_file
    if log_file is None:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        log_file = open(LOG, "w", encoding="utf-8")
    print(*a, file=log_file, flush=True)


def hexrgb(h):
    """sRGB hex -> linear rgb (vertex colours are stored linear)."""
    c = [((h >> s) & 255) / 255 for s in (16, 8, 0)]
    return np.array([x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c])


# ---------- the old skin-modifier skeleton (still used for the bronze Guy the Gorilla statue) ----------

class Skel:
    def __init__(self):
        self.v, self.r, self.e, self.legs = [], [], [], []

    def add(self, p, r, parent=None):
        """r is a radius, or (width, depth) for an oval cross-section."""
        self.v.append(tuple(p))
        self.r.append(r if isinstance(r, tuple) else (r, r))
        i = len(self.v) - 1
        if parent is not None:
            self.e.append((parent, i))
        return i

    def chain(self, parent, pts):
        i = parent
        for p, r in pts:
            i = self.add(p, r, i)
        return i


def ape(s, L, H, R, legR, tail=0.0, head_r=None):
    head_r = head_r or R * 0.55
    hip = s.add((0, 0, H * 0.45), R)
    chest = s.add((L * 0.3, 0, H * 0.72), R * 1.15, hip)
    neck = s.add((L * 0.42, 0, H * 0.9), head_r * 0.8, chest)
    head = s.add((L * 0.47, 0, H * 0.98), head_r, neck)
    s.add((L * 0.47 + head_r * 0.75, 0, H * 0.93), head_r * 0.55, head)
    for side in (1, -1):
        sh = s.add((L * 0.3, R * 1.05 * side, H * 0.74), legR * 1.4, chest)
        s.chain(sh, [((L * 0.42, R * 1.2 * side, H * 0.42), legR), ((L * 0.48, R * 1.1 * side, 0.06), legR * 0.8), ((L * 0.52, R * 1.1 * side, 0.03), legR * 0.85)])
        s.legs.append((L * 0.3, R * 1.05 * side, H * 0.74))
        top = s.add((0, R * 0.65 * side, H * 0.4), legR * 1.3, hip)
        s.chain(top, [((0.06 * H, R * 0.7 * side, H * 0.22), legR * 0.9), ((0.02, R * 0.7 * side, 0.05), legR * 0.7), ((0.02 + legR, R * 0.7 * side, 0.02), legR * 0.75)])
        s.legs.append((0, R * 0.65 * side, H * 0.4))
    if tail:
        s.chain(hip, [((-tail * 0.4, 0, H * 0.5), legR * 0.5), ((-tail * 0.8, 0, H * 0.75), legR * 0.4), ((-tail, 0, H * 0.95), legR * 0.35)])
    return {"eye": (L * 0.47 + head_r * 0.55, head_r * 0.45, H * 1.0)}


# ---------- anatomy ----------

K = 1 / 0.575  # metaball radius whose lone surface sits at 1 (stiffness 2, threshold 0.6)
X = Vector((1, 0, 0))


class Body:
    """Muscle and bone masses as metaball elements, each tagged with the body part it shapes."""

    def __init__(self, seed=1):
        self.els, self.eyes, self.legs = [], [], []
        self.legR = 0.05
        self.rnd = random.Random(seed)

    def ell(self, c, axes, tag, pitch=0.0, yaw=0.0, roll=0.0, neg=False, q=None):
        """Ellipsoid with semi-axes `axes` (x along the body); pitch > 0 lifts its front (degrees)."""
        q = q or Euler((math.radians(roll), -math.radians(pitch), math.radians(yaw))).to_quaternion()
        self.els.append(dict(kind="ELLIPSOID", co=Vector(c), axes=Vector(axes), q=q, tag=tag, neg=neg))

    def ball(self, c, r, tag, neg=False):
        self.ell(c, (r, r, r), tag, neg=neg)

    def bone(self, a, b, r, tag):
        """A capsule of radius r from a to b."""
        a, b = Vector(a), Vector(b)
        d = b - a
        if d.length < 1e-5:
            return self.ball(a, r, tag)
        self.els.append(dict(kind="CAPSULE", co=(a + b) / 2, half=d.length / 2, r=r, q=X.rotation_difference(d.normalized()), tag=tag))

    def muscle(self, a, b, w, d, tag, over=0.62, up=None):
        """An ellipsoid stretched between a and b (a muscle belly or limb segment), w wide, d deep."""
        a, b = Vector(a), Vector(b)
        ax = b - a
        L = ax.length
        if L < 1e-5:
            return self.ball(a, w, tag)
        q = X.rotation_difference(ax.normalized())
        if up is not None:  # roll it so its depth points along `up`
            z = q @ Vector((0, 0, 1))
            want = (Vector(up) - Vector(up).project(ax)).normalized()
            ang = z.angle(want) if want.length > 0 else 0
            if (z.cross(want)).dot(ax) < 0:
                ang = -ang
            q = (Matrix.Rotation(ang, 4, ax.normalized()).to_quaternion()) @ q
        self.els.append(dict(kind="ELLIPSOID", co=(a + b) / 2, axes=Vector((L * over, w, d)), q=q, tag=tag, neg=False))

    def chain(self, pts, tag, taper_tag=None):
        """Bones through [(point, radius)], a ball at each joint."""
        for i in range(len(pts) - 1):
            (p, r0), (q, r1) = pts[i], pts[i + 1]
            self.bone(p, q, (r0 + r1) / 2, taper_tag(i) if taper_tag else tag)

    def eye(self, c, r):
        self.eyes.append((Vector(c), r))
        self.ball(c, r * 1.15, "eye", neg=True)  # the socket

    # Field of each element at points P (n x 3): which part each vertex belongs to.
    def fields(self, P):
        F = np.zeros((len(P), len(self.els)), dtype=np.float32)
        for j, e in enumerate(self.els):
            inv = np.array(e["q"].inverted().to_matrix())
            loc = (P - np.array(e["co"])) @ inv.T
            if e["kind"] == "ELLIPSOID":
                R = K
                d2 = np.sum((loc / np.array(e["axes"])) ** 2, axis=1) / (R * R)
            else:
                R = K * e["r"]
                x = np.clip(loc[:, 0], -e["half"], e["half"])
                d2 = ((loc[:, 0] - x) ** 2 + loc[:, 1] ** 2 + loc[:, 2] ** 2) / (R * R)
            f = np.clip(1 - d2, 0, None) ** 3
            F[:, j] = -f if e.get("neg") else f
        return F


def foot(B, at, legR, kind, side):
    x, y, z = at
    if kind == "hoof":
        B.ell((x + legR * 0.25, y, legR * 0.55), (legR * 0.75, legR * 0.62, legR * 0.55), "hoof")
    elif kind == "cloven":
        for s in (-1, 1):
            B.ell((x + legR * 0.3, y + s * legR * 0.28, legR * 0.45), (legR * 0.6, legR * 0.32, legR * 0.45), "hoof")
    elif kind == "pad":  # camel: broad soft pads
        B.ell((x + legR * 0.4, y, legR * 0.35), (legR * 1.2, legR * 0.95, legR * 0.38), "foot")
    else:  # paw
        B.ell((x + legR * 0.55, y, legR * 0.5), (legR * 1.15, legR * 0.85, legR * 0.5), "paw")
        for s in (-1, 0, 1):
            B.ball((x + legR * 1.35, y + s * legR * 0.42, legR * 0.32), legR * 0.3, "paw")


def ear(B, base, kind, size, side, hd_back):
    """An ear standing from `base`: thin front to back, broad side to side."""
    t = max(size * 0.07, 0.006)
    x, y, z = base
    if kind == "round":
        B.ell((x, y + side * size * 0.15, z + size * 0.3), (t, size * 0.38, size * 0.36), "ear", roll=side * 25)
    elif kind == "floppy":
        B.ell((x + size * 0.35, y + side * size * 0.4, z - size * 0.05), (size * 0.5, size * 0.38, t), "ear", pitch=-30, roll=side * 30)
    elif kind == "tall":  # zebra, okapi, wallaby, water deer: long and rounded
        B.ell((x, y + side * size * 0.22, z + size * 0.5), (t, size * 0.24, size * 0.55), "ear", pitch=12, roll=side * 22)
    elif kind == "banana":  # alpaca
        B.ell((x, y + side * size * 0.1, z + size * 0.55), (t, size * 0.14, size * 0.6), "ear", pitch=-8, roll=side * 10)
    elif kind == "small":
        B.ell((x, y + side * size * 0.2, z + size * 0.22), (t, size * 0.25, size * 0.22), "ear", roll=side * 35)
    else:  # pointed (giraffe, goat, deer)
        B.ell((x - hd_back * 0.02, y + side * size * 0.35, z + size * 0.3), (t, size * 0.2, size * 0.45), "ear", pitch=20, roll=side * 50)


def head(B, base, hd, L, w, h, muzzle=0.55, muzzle_w=0.6, ears="pointed", ear_size=None, eyes=0.045, nose="nose",
         jaw=0.5, brow=0.0):
    """A skull at `base` pointing along unit `hd` (in the x-z plane), L long, w wide, h high."""
    hd = Vector(hd).normalized()
    up = Vector((-hd.z, 0, hd.x))
    if up.z < 0:
        up = -up
    sk = Vector(base) + hd * L * 0.22
    pitch = math.degrees(math.atan2(hd.z, hd.x))
    B.ell(sk, (L * 0.3, w, h), "head", pitch=pitch)
    if brow:
        B.ell(sk + hd * L * 0.12 + up * h * 0.55, (L * 0.12, w * 0.95, h * brow), "head", pitch=pitch)
    tip = sk + hd * L * (0.2 + muzzle * 0.62) - up * h * 0.15
    B.muscle(sk + hd * L * 0.08, tip, w * muzzle_w, h * 0.62 * muzzle_w + h * 0.1, "muzzle", over=0.6, up=up)
    B.ball(tip + hd * L * 0.04, w * muzzle_w * 0.55, nose)
    B.muscle(sk - up * h * 0.3, tip - up * h * 0.25, w * 0.7, h * 0.4 * jaw + 0.001, "head", over=0.55, up=up)  # jaw and cheeks
    for side in (1, -1):
        B.eye(sk + hd * L * 0.14 + up * h * 0.3 + Vector((0, side * w * 0.82, 0)), L * eyes)
        if ears:
            ear(B, sk - hd * L * 0.12 + up * h * 0.8 + Vector((0, side * w * 0.55, 0)), ears, ear_size or L * 0.3, side, L)
    return sk, tip, up


def tail_chain(B, base, length, r0, r1, kind, droop=1.0, up=0.0, n=6, tuft_col="tuft"):
    """A tail from `base`, hanging (droop) or carried up (up > 0); kinds: thin, tuft, bushy, thick, rings."""
    pts = []
    p = Vector(base)
    ang = math.radians(200 - up * 70)  # direction in the x-z plane, from +x
    for i in range(n + 1):
        t = i / n
        pts.append((p.copy(), r0 + (r1 - r0) * t))
        a = ang + math.radians(droop * 55) * t * (1 if up <= 0 else -0.6)
        p = p + Vector((math.cos(a), 0, math.sin(a))) * (length / n)
    tag = "tail"
    B.chain(pts, tag)
    if kind == "tuft":
        end = pts[-1][0]
        prev = pts[-2][0]
        B.muscle(prev.lerp(end, 0.4), end + (end - prev) * 0.6, r0 * 1.3, r0 * 1.3, tuft_col)
    elif kind == "bushy":
        for i in range(1, n + 1):
            B.ball(pts[i][0], r0 * 1.5, "tail")
    return pts


def wool(B, centre, axes, pitch, count, r, tag="body", top_only=False):
    """Lumpy fleece: small balls scattered over an ellipsoid's surface."""
    q = Euler((0, -math.radians(pitch), 0)).to_quaternion()
    for _ in range(count):
        u = B.rnd.uniform(-1, 1)
        th = B.rnd.uniform(0, 2 * math.pi)
        s = math.sqrt(1 - u * u)
        v = Vector((s * math.cos(th), s * math.sin(th), u))
        if top_only and v.z < -0.35:
            continue
        p = Vector((v.x * axes[0], v.y * axes[1], v.z * axes[2]))
        B.ball(Vector(centre) + q @ p, r * B.rnd.uniform(0.7, 1.2), tag)


# ---------- body plans ----------

def quadruped(B, H, L, cw, cd, Hh=None, legR=0.06, feet="hoof", digit=False, belly=0.0,
              neck=0.4, neck_ang=45, neck_r=None, head_len=0.45, head_w=None, head_h=None, head_down=35,
              muzzle=0.55, muzzle_w=0.6, ears="pointed", ear_size=None, eyes=0.045, brow=0.0, jaw=0.5,
              tail=0.5, tail_kind="tuft", tail_r=None, tail_up=0.0, tail_droop=1.0,
              mane=None, humps=0, ossicones=False, horns=0.0, tusks=0.0, tusk_dir=1, wool_r=0.0, beard=0.0, crest=0.0):
    Hh = Hh or H
    xs, xh = L / 2, -L / 2
    back = lambda x: Hh + (H - Hh) * (x - xh) / L
    slope = math.degrees(math.atan2(H - Hh, L))
    B.legR = legR
    # Trunk: ribcage, belly, croup, shoulder blades, haunches, brisket.
    B.ell((xs - L * 0.18, 0, back(xs - L * 0.18) - cd), (L * 0.46, cw, cd), "body", pitch=slope)
    B.ell((-L * 0.06, 0, back(-L * 0.06) - cd * 1.02 - belly), (L * 0.36, cw * 0.94, cd * 0.9), "body", pitch=slope)
    B.ell((xh + L * 0.12, 0, Hh - cd * 0.78), (L * 0.3, cw * 0.86, cd * 0.82), "body", pitch=slope)
    B.ell((xs - L * 0.06, 0, H - cd * 0.38), (L * 0.24, cw * 0.42, cd * 0.42), "body", pitch=slope)  # withers
    B.ell((xs + L * 0.05, 0, H - cd * 1.3), (cd * 0.6, cw * 0.62, cd * 0.62), "body")  # brisket
    for side in (1, -1):
        y = side * cw * 0.6
        B.ell((xs - L * 0.02, y, H - cd * 0.95), (cd * 0.5, cw * 0.42, cd * 0.95), "body", pitch=22)  # shoulder blade
        B.ell((xh + L * 0.04, side * cw * 0.55, Hh - cd * 1.1), (cd * 0.7, cw * 0.46, cd * 1.05), "body", pitch=-8)  # haunch
    # The flank tucks in behind the ribs.
    for side in (1, -1):
        B.ball((-L * 0.18, side * cw * 1.25, back(-L * 0.18) - cd * 1.25 - belly), cw * 0.35, "body", neg=True)
    # Legs.
    elbow_z = H - cd * 1.85
    stifle_z = Hh - cd * 1.75
    for side in (1, -1):
        y = side * cw * 0.6
        # Fore: forearm muscle to the knee (carpus), cannon to the fetlock, then the foot.
        kz = H * (0.17 if digit else 0.3)
        el = Vector((xs - L * 0.03, y, elbow_z))
        kn = Vector((xs + 0.0, y, kz))
        fl = Vector((xs + (legR * 1.2 if digit else legR * 0.3), y, legR * 1.1))
        B.muscle(el + Vector((0, 0, cd * 0.35)), kn, legR * 1.25, legR * 1.15, "leg", over=0.6)
        B.ball(kn, legR * 0.72, "leg_low")
        B.bone(kn, fl, legR * 0.55, "leg_low")
        B.ball(fl, legR * 0.62, "leg_low")
        foot(B, (fl.x, y, 0), legR, feet, side)
        B.legs.append((xs, y, elbow_z - cd * 0.2))  # pivot just below the chest
        # Hind: thigh to the stifle, gaskin to the hock, cannon to the fetlock.
        y = side * cw * 0.55
        hip = Vector((xh + L * 0.02, y, Hh - cd * 0.9))
        st = Vector((xh + L * 0.14, y, stifle_z + cd * 0.2))
        hk = Vector((xh - L * 0.1, y, Hh * (0.2 if digit else 0.3)))
        hf = Vector((xh - L * 0.06, y, legR * 1.1))
        B.muscle(hip, st, legR * 1.7, legR * 1.6, "leg", over=0.65)
        B.muscle(st, hk, legR * 1.15, legR * 1.3, "leg", over=0.62)
        B.ball(hk, legR * 0.7, "leg_low")
        B.bone(hk, hf, legR * 0.52, "leg_low")
        B.ball(hf, legR * 0.6, "leg_low")
        foot(B, (hf.x, y, 0), legR, feet, side)
        B.legs.append((xh - L * 0.02, y, stifle_z - cd * 0.3))
    # Neck: two muscles from the withers to the head.
    a = math.radians(neck_ang)
    d = Vector((math.sin(a), 0, math.cos(a)))
    n0 = Vector((xs + L * 0.06, 0, H - cd * 0.55))
    n1 = n0 + d * neck
    nr = neck_r or cd * 0.7
    side_up = Vector((-d.z, 0, d.x)) if d.x > 0 else Vector((0, 0, 1))
    B.muscle(n0 - d * neck * 0.1, n0 + d * neck * 0.62, nr * 0.8, nr * 1.05, "neck", over=0.6)
    B.muscle(n0 + d * neck * 0.38, n1 + d * nr * 0.2, nr * 0.55, nr * 0.72, "neck", over=0.6)
    if crest:
        B.muscle(n0 + d * neck * 0.1 + side_up * nr * 0.4, n1 + side_up * nr * 0.2, nr * 0.35, nr * crest, "neck", over=0.55)
    # Head.
    hd = Vector((math.cos(math.radians(head_down)), 0, -math.sin(math.radians(head_down))))
    hw, hh = head_w or head_len * 0.22, head_h or head_len * 0.24
    sk, tip, up = head(B, n1, hd, head_len, hw, hh, muzzle, muzzle_w, ears, ear_size, eyes, jaw=jaw, brow=brow)
    if ossicones:
        for side in (1, -1):
            b0 = sk - hd * head_len * 0.05 + up * hh * 0.7 + Vector((0, side * hw * 0.35, 0))
            B.bone(b0, b0 + up * head_len * 0.22 - hd * head_len * 0.05, head_len * 0.035, "horn")
            B.ball(b0 + up * head_len * 0.24 - hd * head_len * 0.05, head_len * 0.05, "horn_tip")
    if horns:
        for side in (1, -1):
            p = sk - hd * head_len * 0.02 + up * hh * 0.75 + Vector((0, side * hw * 0.35, 0))
            pts = []
            for i in range(6):
                t = i / 5
                pts.append((p + up * horns * 0.6 * math.sin(t * 1.3) - hd * horns * t + Vector((0, side * horns * 0.15 * t, 0)), horns * (0.13 - 0.1 * t)))
            B.chain(pts, "horn")
    if tusks:
        for side in (1, -1):
            p = tip - hd * head_len * 0.12 + Vector((0, side * hw * 0.55, 0))
            tu = up * tusk_dir
            B.chain([(p, tusks * 0.12), (p + Vector((0, side * tusks * 0.25, 0)) + tu * tusks * 0.5 + hd * tusks * 0.15, tusks * 0.09),
                     (p + Vector((0, side * tusks * 0.3, 0)) + tu * tusks * 0.95 - hd * tusks * 0.05, tusks * 0.05)], "tusk")
    if beard:
        B.ell(tip - up * hh * 0.9 - hd * head_len * 0.1, (beard * 0.35, beard * 0.25, beard), "beard", pitch=20)
    # Mane.
    if mane == "upright":  # zebra: a stiff brush along the crest
        for i in range(14):
            t = i / 13
            p = n0.lerp(n1, t) + side_up * nr * (0.85 - 0.35 * t)
            B.ell(p + side_up * nr * 0.18, (neck * 0.05, nr * 0.12, nr * 0.32), "mane", pitch=90 - neck_ang)
        B.ell(sk - hd * head_len * 0.05 + up * hh * 0.9, (head_len * 0.12, hw * 0.25, hh * 0.35), "mane")  # forelock
    elif mane == "lion":  # shaggy tufts radiating from the neck and round the face
        B.ell(n0.lerp(n1, 0.55) + Vector((0, 0, nr * 0.15)), (neck * 0.75, nr * 1.25, nr * 1.35), "mane", pitch=90 - neck_ang)
        for _ in range(48):
            t = B.rnd.uniform(0.1, 1.05)
            c = n0.lerp(n1, t)
            th = B.rnd.uniform(-math.pi * 0.85, math.pi * 0.85)
            o = Vector((B.rnd.uniform(-0.3, 0.1), math.sin(th), math.cos(th))).normalized()
            ln = nr * B.rnd.uniform(0.7, 1.1)
            B.muscle(c + o * nr * 0.6, c + o * (nr * 0.6 + ln), nr * 0.28, nr * 0.22, "mane", over=0.6)
    elif mane == "ridge":  # warthog: a long mane down the neck and back
        for i in range(16):
            t = i / 15
            x = xs + L * 0.2 - t * L * 0.9
            B.ell((x, 0, back(x) + cd * 0.08), (L * 0.05, cw * 0.12, cd * 0.22), "mane")
    if humps:
        for x in ((-L * 0.2, L * 0.2) if humps == 2 else (0,)):
            B.ell((x, 0, back(x) + cd * 0.2), (L * 0.2, cw * 0.6, cd * 0.62), "hump")
    if wool_r:
        wool(B, (xs - L * 0.18, 0, back(xs - L * 0.18) - cd), (L * 0.46, cw, cd), slope, 60, wool_r)
        wool(B, (-L * 0.06, 0, back(-L * 0.06) - cd * 1.02 - belly), (L * 0.36, cw * 0.94, cd * 0.9), slope, 45, wool_r)
        wool(B, (xh + L * 0.12, 0, Hh - cd * 0.78), (L * 0.3, cw * 0.86, cd * 0.82), slope, 35, wool_r)
    # Tail.
    if tail:
        tail_chain(B, (xh - L * 0.06, 0, Hh - cd * 0.3), tail, tail_r or cd * 0.13, (tail_r or cd * 0.13) * 0.45, tail_kind,
                   droop=tail_droop, up=tail_up)
    return {"H": max(H, Hh), "L": L}


def primate(B, H, L, cw, cd, arm=1.0, legR=0.05, head_r=0.1, muzzle=0.35, tail=0.0, tail_up=0.0, tail_kind="thin",
            crest=0.0, brow=0.4, ears="small", knuckle=True, trap=0.0, head_up=0.3, pot=0.0):
    """A primate on all fours: gorilla (knuckle-walking, a massive chest and shoulders, the trapezius
    rising to a crested head), monkeys and lemurs."""
    sh_z, hip_z = H, H / arm  # shoulders higher than hips when the arms are long
    xs, xh = L / 2, -L / 2
    B.legR = legR
    pitch = math.degrees(math.atan2(sh_z - hip_z, L))
    B.ell((xs - L * 0.18, 0, sh_z - cd * 0.85), (L * 0.45, cw, cd * 1.05), "body", pitch=pitch)
    B.ell((xh + L * 0.2, 0, hip_z - cd * 0.8), (L * 0.36, cw * 0.85, cd * 0.85), "body", pitch=pitch)
    if pot:  # the gorilla's pot belly
        B.ell((-L * 0.05, 0, (sh_z + hip_z) / 2 - cd * (1.15 + pot)), (L * 0.32, cw * 0.85, cd * 0.7), "body", pitch=pitch)
    if trap:  # neck muscles mounding up behind the head
        B.ell((xs - L * 0.02, 0, sh_z - cd * 0.05), (L * 0.24, cw * 0.62, cd * trap), "body", pitch=-15)
    for side in (1, -1):
        B.ell((xs - L * 0.05, side * cw * 0.85, sh_z - cd * 0.55), (cd * 0.55, cw * 0.45, cd * 0.55), "body")  # deltoids
    # Arms: upper arm, forearm, hand on its knuckles.
    for side in (1, -1):
        y = side * cw * 1.05
        sh = Vector((xs - L * 0.02, y, sh_z - cd * 0.55))
        el = Vector((xs + L * 0.02, y * 1.05, sh_z * 0.5))
        wr = Vector((xs + L * 0.06, y, legR * 1.6))
        B.muscle(sh, el, legR * 1.35, legR * 1.4, "leg", over=0.62)
        B.muscle(el, wr, legR * 1.15, legR * 1.1, "leg", over=0.62)
        B.ell((wr.x + legR * 0.6, y, legR * 0.75), (legR * 1.1, legR * 0.9, legR * 0.75), "hand", pitch=-15 if knuckle else 0)
        B.legs.append((xs + L * 0.02, y, sh_z * 0.62))
        # Legs: thigh, shin, foot flat.
        y = side * cw * 0.7
        hp = Vector((xh + L * 0.08, y, hip_z - cd * 0.7))
        kn = Vector((xh + L * 0.28, y * 1.1, hip_z * 0.45))
        an = Vector((xh + L * 0.12, y, legR * 1.4))
        B.muscle(hp, kn, legR * 1.45, legR * 1.4, "leg", over=0.62)
        B.muscle(kn, an, legR * 1.05, legR * 1.1, "leg", over=0.62)
        B.ell((an.x + legR * 1.0, y, legR * 0.55), (legR * 1.6, legR * 0.8, legR * 0.55), "hand")
        B.legs.append((xh + L * 0.15, y, hip_z * 0.6))
    # Head: low on the shoulders, with brow ridge and short muzzle.
    hc = Vector((xs + L * (0.2 if trap else 0.12), 0, sh_z + head_r * head_up))
    B.ell(hc, (head_r, head_r * 0.92, head_r), "head")
    if crest:  # sagittal crest
        B.ell(hc + Vector((-head_r * 0.25, 0, head_r * 0.7)), (head_r * 0.62, head_r * 0.3, head_r * crest), "head", pitch=-15)
    B.ell(hc + Vector((head_r * 0.62, 0, head_r * 0.3)), (head_r * 0.28, head_r * 0.95, head_r * brow * 0.5), "head")  # brow ridge
    mz = hc + Vector((head_r * 0.75, 0, -head_r * 0.38))
    B.ell(mz, (head_r * (0.35 + muzzle * 0.5), head_r * 0.66, head_r * 0.5), "muzzle", pitch=-8)
    B.ball(mz + Vector((head_r * (0.3 + muzzle * 0.6), 0, head_r * 0.08)), head_r * 0.27, "nose")
    for side in (1, -1):
        B.eye(hc + Vector((head_r * 0.86, side * head_r * 0.34, head_r * 0.08)), head_r * 0.12)
        ear(B, hc + Vector((-head_r * 0.1, side * head_r * 0.85, head_r * 0.25)), ears, head_r * 0.6, side, head_r)
    if tail:
        tail_chain(B, (xh - L * 0.02, 0, hip_z - cd * 0.2), tail, legR * 0.6, legR * 0.4, tail_kind, droop=1.0, up=tail_up, n=10)
    return {"H": sh_z + head_r, "L": L}


def bird(B, H, body, neck, beak, leg_h, beak_down=0.0, pouch=0.0, neck_s=False, wing=1.0, tail=0.4, legR=None):
    """Long-legged birds (ostrich, flamingo, pelican): an egg-shaped body, folded wings, a neck
    (an S for the flamingo), a head with its beak, thin backward-kneed legs and toes."""
    L, R = body, body * 0.42
    zc = leg_h + R
    legR = legR or R * 0.09
    B.legR = legR
    B.ell((0, 0, zc), (L * 0.5, R, R * 0.95), "body", pitch=8)
    B.ell((-L * 0.42, 0, zc + R * 0.25), (L * 0.22, R * 0.55 * tail * 2, R * 0.35), "tail", pitch=25)
    for side in (1, -1):
        B.ell((-L * 0.05, side * R * 0.75, zc + R * 0.15), (L * 0.42 * wing, R * 0.35, R * 0.62), "wing", pitch=10, yaw=-side * 4)
    # Neck.
    base = Vector((L * 0.4, 0, zc + R * 0.4))
    if neck_s:
        pts = [base, base + Vector((neck * 0.05, 0, neck * 0.3)), base + Vector((-neck * 0.12, 0, neck * 0.6)),
               base + Vector((neck * 0.02, 0, neck * 0.85)), base + Vector((neck * 0.12, 0, neck))]
    else:
        pts = [base, base + Vector((neck * 0.15, 0, neck * 0.45)), base + Vector((neck * 0.08, 0, neck * 0.8)), base + Vector((neck * 0.12, 0, neck))]
    r0, r1 = R * 0.32, R * 0.16
    B.chain([(p, r0 + (r1 - r0) * i / (len(pts) - 1)) for i, p in enumerate(pts)], "neck")
    hc = pts[-1] + Vector((0, 0, R * 0.12))
    hr = R * 0.24
    B.ball(hc, hr, "head")
    d = Vector((1, 0, -beak_down)).normalized()
    B.chain([(hc + d * hr * 0.6, hr * 0.42), (hc + d * (hr + beak * 0.6), hr * 0.3), (hc + d * (hr + beak) + Vector((0, 0, -beak_down * beak * 0.4)), hr * 0.15)], "beak")
    if pouch:
        B.muscle(hc + d * hr, hc + d * (hr + beak * 0.8) - Vector((0, 0, pouch * 0.5)), hr * 0.35, pouch * 0.5, "pouch")
    for side in (1, -1):
        B.eye(hc + Vector((hr * 0.45, side * hr * 0.72, hr * 0.25)), hr * 0.2)
    # Legs: thigh hidden in the body, the "knee" (ankle) bends backwards, toes forward.
    for side in (1, -1):
        y = side * R * 0.35
        top = Vector((0.0, y, zc - R * 0.55))
        ank = Vector((-leg_h * 0.06, y, leg_h * 0.5))
        ft = Vector((0.02, y, legR * 1.2))
        B.muscle(top + Vector((0, 0, R * 0.3)), top - Vector((0, 0, R * 0.25)), legR * 2.5, legR * 2.5, "leg")
        B.bone(top, ank, legR * 1.2, "leg_low")
        B.ball(ank, legR * 1.3, "leg_low")
        B.bone(ank, ft, legR, "leg_low")
        for a in (-35, 0, 35):
            t = math.radians(a)
            B.bone(ft, ft + Vector((math.cos(t), math.sin(t) * side, 0)) * leg_h * 0.12 - Vector((0, 0, legR * 0.6)), legR * 0.75, "foot")
        B.legs.append((0.0, y, zc - R * 0.55))
    return {"H": zc + neck + R, "L": L}


def upright(B, H, R, beak=0.0, snout=0.0, flippers=True, tail=0.0, ears=False):
    """Upright animals: the penguin (flippers, white front) and the meerkat on sentry."""
    B.legR = R * 0.25
    B.ell((0, 0, H * 0.36), (R * 0.95, R, H * 0.33), "body", pitch=-6)
    B.ell((R * 0.25, 0, H * 0.38), (R * 0.7, R * 0.82, H * 0.28), "chest", pitch=-6)
    neck = Vector((0.02 * H, 0, H * 0.7))
    B.ell(neck, (R * 0.62, R * 0.62, H * 0.12), "neck")
    hc = Vector((R * 0.15, 0, H * 0.82))
    hr = R * 0.62
    B.ball(hc, hr, "head")
    if beak:
        B.chain([(hc + Vector((hr * 0.7, 0, -hr * 0.05)), hr * 0.25), (hc + Vector((hr * 0.7 + beak, 0, -hr * 0.12)), hr * 0.07)], "beak")
    if snout:
        B.chain([(hc + Vector((hr * 0.6, 0, -hr * 0.1)), hr * 0.42), (hc + Vector((hr * 0.6 + snout, 0, -hr * 0.25)), hr * 0.12)], "muzzle")
        B.ball(hc + Vector((hr * 0.62 + snout, 0, -hr * 0.25)), hr * 0.12, "nose")
    for side in (1, -1):
        B.eye(hc + Vector((hr * 0.55, side * hr * 0.55, hr * 0.22)), hr * 0.16)
        if ears:
            B.ell(hc + Vector((-hr * 0.15, side * hr * 0.85, hr * 0.15)), (hr * 0.08, hr * 0.22, hr * 0.2), "ear", roll=side * 40)
        sh = Vector((R * 0.1, side * R * 0.88, H * 0.58))
        if flippers:
            B.ell(sh + Vector((-R * 0.05, side * R * 0.1, -H * 0.15)), (R * 0.22, R * 0.07, H * 0.19), "wing", roll=side * 18, pitch=-10)
        else:  # little arms held in front
            B.muscle(sh, sh + Vector((R * 0.45, -side * R * 0.25, -H * 0.12)), R * 0.17, R * 0.17, "leg")
            B.ball(sh + Vector((R * 0.52, -side * R * 0.3, -H * 0.14)), R * 0.14, "hand")
        ft = Vector((R * 0.15, side * R * 0.42, R * 0.12))
        B.muscle(Vector((0, side * R * 0.45, H * 0.15)), ft, R * 0.3, R * 0.3, "leg")
        B.ell(ft + Vector((R * 0.3, 0, -R * 0.06)), (R * 0.42, R * 0.24, R * 0.08), "foot")
        B.legs.append((0.0, side * R * 0.45, H * 0.18))
    if tail:
        tail_chain(B, (-R * 0.8, 0, H * 0.12), tail, R * 0.18, R * 0.06, "thin", droop=0.3, up=-0.3, n=6)
    return {"H": H, "L": R * 2}


def macropod(B, H, L, cw, legR, head_len, tail):
    """A wallaby resting on its haunches: big hind legs folded, long feet flat, small arms, a thick
    tail along the ground, a deer-like head with tall ears."""
    B.legR = legR
    B.ell((-L * 0.1, 0, H * 0.45), (L * 0.42, cw, H * 0.3), "body", pitch=40)
    B.ell((L * 0.12, 0, H * 0.68), (L * 0.25, cw * 0.75, H * 0.2), "body", pitch=55)
    for side in (1, -1):
        y = side * cw * 0.7
        B.ell((-L * 0.25, y, H * 0.3), (L * 0.3, cw * 0.45, H * 0.25), "leg", pitch=20)  # thigh
        B.bone((-L * 0.1, y, H * 0.12), (-L * 0.35, y, H * 0.08), legR, "leg_low")
        B.ell((-L * 0.05, y, legR * 0.8), (L * 0.35, legR * 1.1, legR * 0.8), "foot")
        B.legs.append((-L * 0.2, y, H * 0.35))
        sh = Vector((L * 0.25, side * cw * 0.55, H * 0.72))
        B.muscle(sh, sh + Vector((L * 0.15, 0, -H * 0.3)), legR * 0.75, legR * 0.75, "leg")
        B.ball(sh + Vector((L * 0.18, 0, -H * 0.33)), legR * 0.6, "hand")
    n1 = Vector((L * 0.3, 0, H * 0.92))
    B.muscle((L * 0.15, 0, H * 0.75), n1, cw * 0.45, cw * 0.5, "neck")
    head(B, n1, (math.cos(math.radians(20)), 0, -math.sin(math.radians(20))), head_len, head_len * 0.25, head_len * 0.26,
         muzzle=0.5, ears="tall", ear_size=head_len * 0.55, eyes=0.06)
    tail_chain(B, (-L * 0.45, 0, H * 0.25), tail, cw * 0.32, cw * 0.1, "thin", droop=0.25, up=-0.2, n=8)
    return {"H": H, "L": L}


# ---------- coats ----------

def noise3(P, scale, seed):
    """Smooth value-ish noise in [-1, 1] from a few random sine waves."""
    rnd = np.random.default_rng(seed)
    out = np.zeros(len(P))
    for _ in range(7):
        d = rnd.normal(size=3)
        d /= np.linalg.norm(d)
        out += np.sin(P @ d * scale * rnd.uniform(0.6, 1.6) + rnd.uniform(0, 6.28))
    return out / 7 * 2


def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def paint(sid, P, N, T, info):
    """Vertex colours for a species from positions P, normals N and body-part tags T."""
    c = COATS[sid]
    n = len(P)
    H = info["H"]
    col = np.tile(hexrgb(c["base"]), (n, 1))
    tagged = lambda *ts: np.isin(T, ts)
    # Countershading: lighter underneath.
    if c.get("belly"):
        under = smooth(-0.1, -0.7, N[:, 2]) * smooth(H * 0.85, H * 0.45, P[:, 2]) * tagged("body", "neck", "leg", "head", "muzzle")
        col = col * (1 - under[:, None] * 0.85) + hexrgb(c["belly"]) * under[:, None] * 0.85
    for tag, h in c.get("parts", {}).items():
        m = tagged(tag)
        col[m] = hexrgb(h)
    pat = c.get("pattern")
    x, y, z = P[:, 0], P[:, 1], P[:, 2]
    if pat == "giraffe":
        rnd = np.random.default_rng(7)
        m = tagged("body", "neck", "leg", "hump")
        pts = P[m]
        span = P.max(0) - P.min(0)
        sites = P.min(0) + rnd.uniform(0, 1, size=(int(span[0] * span[2] / 0.012) + 200, 3)) * span
        d = np.sqrt(((pts[:, None, :] - sites[None, :, :]) ** 2).sum(-1))
        part = np.partition(d, 1, axis=1)
        edge = part[:, 1] - part[:, 0]
        cell = np.argmin(d, axis=1)
        shade = 0.75 + 0.5 * rnd.uniform(0, 1, len(sites))[cell]
        patch = hexrgb(0x8a4a1c) * shade[:, None]
        cream = hexrgb(0xeadbb8)
        low = P[m][:, 2] < H * 0.38
        t = smooth(0.012, 0.03, edge)[:, None] * (1 - low[:, None] * 0.8)
        col[m] = cream * (1 - t) + patch * t
    elif pat == "zebra":
        m = tagged("body", "neck", "leg", "leg_low", "head", "mane", "tail")
        f = np.where(tagged("leg", "leg_low"), np.sin(z * 2 * math.pi / 0.075 + y * 3),
            np.where(tagged("neck", "mane"), np.sin((x * 0.6 + z) * 2 * math.pi / 0.11),
            np.where(tagged("head"), np.sin((x * 0.4 + z) * 2 * math.pi / 0.05),
                     np.sin((x + 0.35 * np.sin(z * 7) + 0.25 * (x < -0.25) * z * 2.2) * 2 * math.pi / 0.13))))
        f = f + 0.12 * noise3(P, 5, 3)
        black = (f > 0.05) & m & ~((N[:, 2] < -0.75) & tagged("body"))
        col[black] = hexrgb(0x161414)
    elif pat == "tiger":
        m = tagged("body", "neck", "leg", "tail", "head")
        f = np.where(tagged("tail"), np.sin(x * 2 * math.pi / 0.11),
                     np.sin((x + 0.18 * np.sin(z * 9) + 0.06 * y) * 2 * math.pi / 0.12 + 1.8 * noise3(P, 6, 5)))
        width = 0.55 + 0.2 * noise3(P, 9, 11)
        black = (f > width) & m & (N[:, 2] > -0.45)
        col[black] = hexrgb(0x1a1410)
        face = tagged("muzzle") | (tagged("head") & (N[:, 0] > 0.3) & (np.abs(y) > 0.05))
        col[face] = hexrgb(0xf2ead8)
    elif pat == "okapi":
        m = tagged("leg", "leg_low", "body") & (x < -0.15) | tagged("leg_low")
        stripes = (np.sin(z * 2 * math.pi / 0.07 + 0.5 * noise3(P, 10, 2)) > 0.1) & m & (z < H * 0.75)
        col[stripes] = hexrgb(0xf2ece0)
        col[tagged("head", "muzzle") & (N[:, 0] > -0.2)] = hexrgb(0xd8ccb8)
    elif pat == "rings":  # lemur, coati: banded tails
        tail = tagged("tail")
        dist = np.linalg.norm(P - info["tail0"], axis=1)
        col[tail & (np.sin(dist * 2 * math.pi / c.get("ring", 0.06)) > 0)] = hexrgb(c["ring_col"])
    elif pat == "silverback":  # the grey saddle across a mature male's back
        saddle = tagged("body") & (N[:, 2] > 0.2) & (x < info["L"] * 0.2) & (x > -info["L"] * 0.55)
        col[saddle] = col[saddle] * 0.3 + hexrgb(0x9a9894) * 0.7 * (0.85 + 0.15 * noise3(P[saddle], 30, 9))[:, None]
    elif pat == "penguin":
        front = tagged("chest", "body") & (x > -0.01 + 0.03 * np.abs(y) / max(1e-3, info["L"])) & (z < H * 0.66)
        col[front] = hexrgb(0xf2f0ea)
        band = front & (z > H * 0.5) & (z < H * 0.56)  # the black breast band
        col[band] = hexrgb(0x161616)
        head = tagged("head")
        hd = P - info["head_c"]
        ring = head & (np.abs(np.linalg.norm(hd[:, [0, 2]], axis=1) - info["head_r"] * 0.8) < info["head_r"] * 0.16) & (hd[:, 0] < info["head_r"] * 0.4)
        col[ring] = hexrgb(0xf2f0ea)
        col[head & (hd[:, 0] > info["head_r"] * 0.35) & (hd[:, 2] < 0)] = hexrgb(0xd9a3a0)  # bare pink face
    if c.get("face"):  # lighter face (lemur mask, lion muzzle)
        col[tagged("muzzle")] = hexrgb(c["face"])
    if c.get("mask"):  # dark eye patches
        col[tagged("head") & (np.linalg.norm(P[:, None, :] - info["eyes"][None, :, :], axis=2).min(1) < info["eye_r"] * 2.4)] = hexrgb(c["mask"])
    # Darker lower legs and feet, muzzle tip, eyes.
    if c.get("stockings"):
        col[tagged("leg_low")] = col[tagged("leg_low")] * 0.4 + hexrgb(c["stockings"]) * 0.6
    col[tagged("eye")] = hexrgb(0x0c0a08)
    # Fur: soft variation in tone, darker along the spine.
    fur = c.get("fur", 0.08)
    v = 1 + fur * noise3(P, 14 / max(H, 0.3), 1) + fur * 0.5 * noise3(P, 60 / max(H, 0.3), 2)
    spine = smooth(0.5, 0.95, N[:, 2]) * tagged("body", "neck") * c.get("dorsal", 0.15)
    col = col * (v - spine)[:, None]
    return np.clip(col, 0, 1)


# Species: (body plan, its parameters). Sizes are adult heights in metres (shoulder H, hip Hh).
SPECIES = {
    "lion": (quadruped, dict(H=1.0, L=1.0, cw=0.22, cd=0.24, legR=0.075, feet="paw", digit=True, belly=-0.03,
                             neck=0.32, neck_ang=58, neck_r=0.2, head_len=0.42, head_w=0.13, head_h=0.13, head_down=12,
                             muzzle=0.38, muzzle_w=0.75, ears="round", ear_size=0.1, eyes=0.04, brow=0.4,
                             tail=0.85, tail_kind="tuft", tail_r=0.03, mane="lion")),
    "tiger": (quadruped, dict(H=0.95, L=1.12, cw=0.2, cd=0.22, legR=0.07, feet="paw", digit=True, belly=-0.02,
                              neck=0.3, neck_ang=62, neck_r=0.17, head_len=0.4, head_w=0.13, head_h=0.12, head_down=10,
                              muzzle=0.35, muzzle_w=0.75, ears="round", ear_size=0.09, eyes=0.04, brow=0.35,
                              tail=0.95, tail_kind="thin", tail_r=0.032, tail_droop=0.7)),
    "giraffe": (quadruped, dict(H=1.95, Hh=1.55, L=1.05, cw=0.28, cd=0.34, legR=0.06, feet="cloven",
                                neck=1.75, neck_ang=32, neck_r=0.2, head_len=0.55, head_w=0.1, head_h=0.12, head_down=60,
                                muzzle=0.6, ears="pointed", ear_size=0.14, eyes=0.05, tail=0.85, tail_kind="tuft", tail_r=0.025,
                                ossicones=True, crest=0.5)),
    "zebra": (quadruped, dict(H=1.32, L=0.95, cw=0.25, cd=0.31, legR=0.055, feet="hoof", belly=0.02,
                              neck=0.68, neck_ang=48, neck_r=0.2, head_len=0.58, head_w=0.11, head_h=0.13, head_down=58,
                              muzzle=0.62, muzzle_w=0.62, ears="tall", ear_size=0.17, tail=0.7, tail_kind="tuft", tail_r=0.03,
                              mane="upright", crest=0.6)),
    "okapi": (quadruped, dict(H=1.55, Hh=1.38, L=1.0, cw=0.24, cd=0.3, legR=0.055, feet="cloven",
                              neck=0.72, neck_ang=42, neck_r=0.19, head_len=0.5, head_w=0.1, head_h=0.12, head_down=55,
                              muzzle=0.6, ears="tall", ear_size=0.2, tail=0.5, tail_kind="tuft", tail_r=0.025)),
    "warthog": (quadruped, dict(H=0.7, Hh=0.62, L=0.62, cw=0.2, cd=0.21, legR=0.045, feet="cloven",
                                neck=0.16, neck_ang=78, neck_r=0.16, head_len=0.48, head_w=0.13, head_h=0.12, head_down=45,
                                muzzle=0.65, muzzle_w=0.8, ears="small", ear_size=0.1, tusks=0.2, mane="ridge",
                                tail=0.35, tail_kind="tuft", tail_r=0.012, tail_up=1.0)),
    "hippo": (quadruped, dict(H=0.8, L=0.75, cw=0.33, cd=0.3, legR=0.09, feet="paw", belly=0.03,
                              neck=0.14, neck_ang=72, neck_r=0.24, head_len=0.48, head_w=0.17, head_h=0.15, head_down=22,
                              muzzle=0.5, muzzle_w=0.95, ears="small", ear_size=0.06, eyes=0.04, tail=0.15, tail_kind="thin", tail_r=0.03)),
    "camel": (quadruped, dict(H=1.85, L=1.15, cw=0.3, cd=0.36, legR=0.065, feet="pad", belly=0.04,
                              neck=1.0, neck_ang=48, neck_r=0.17, head_len=0.52, head_w=0.12, head_h=0.13, head_down=5,
                              muzzle=0.55, ears="small", ear_size=0.09, humps=2, tail=0.45, tail_kind="tuft", tail_r=0.03)),
    "alpaca": (quadruped, dict(H=0.9, L=0.62, cw=0.2, cd=0.22, legR=0.045, feet="pad",
                               neck=0.62, neck_ang=12, neck_r=0.12, head_len=0.28, head_w=0.08, head_h=0.09, head_down=8,
                               muzzle=0.45, ears="banana", ear_size=0.15, eyes=0.06, tail=0.18, tail_kind="bushy", tail_r=0.04,
                               wool_r=0.035)),
    "deer": (quadruped, dict(H=0.55, Hh=0.58, L=0.5, cw=0.12, cd=0.14, legR=0.025, feet="cloven",
                             neck=0.3, neck_ang=40, neck_r=0.07, head_len=0.24, head_w=0.055, head_h=0.06, head_down=30,
                             muzzle=0.55, ears="round", ear_size=0.1, eyes=0.07, tusks=0.06, tusk_dir=-1, tail=0.08, tail_kind="thin", tail_r=0.02)),
    "goat": (quadruped, dict(H=0.52, L=0.46, cw=0.16, cd=0.17, legR=0.03, feet="cloven", belly=0.03,
                             neck=0.22, neck_ang=42, neck_r=0.08, head_len=0.24, head_w=0.065, head_h=0.07, head_down=40,
                             muzzle=0.5, ears="pointed", ear_size=0.1, horns=0.14, beard=0.06,
                             tail=0.1, tail_kind="thin", tail_r=0.02, tail_up=1.0)),
    "pig": (quadruped, dict(H=0.72, L=0.72, cw=0.26, cd=0.26, legR=0.045, feet="cloven", belly=0.03,
                            neck=0.14, neck_ang=78, neck_r=0.2, head_len=0.38, head_w=0.12, head_h=0.13, head_down=25,
                            muzzle=0.6, muzzle_w=0.75, ears="floppy", ear_size=0.16, tail=0.18, tail_kind="thin", tail_r=0.015,
                            wool_r=0.03)),
    "otter": (quadruped, dict(H=0.27, L=0.5, cw=0.1, cd=0.1, legR=0.025, feet="paw", digit=True,
                              neck=0.16, neck_ang=72, neck_r=0.075, head_len=0.16, head_w=0.06, head_h=0.05, head_down=5,
                              muzzle=0.35, muzzle_w=0.8, ears="small", ear_size=0.04, eyes=0.06,
                              tail=0.42, tail_kind="thin", tail_r=0.045, tail_droop=0.3)),
    "coati": (quadruped, dict(H=0.32, L=0.42, cw=0.1, cd=0.11, legR=0.024, feet="paw", digit=True,
                              neck=0.12, neck_ang=70, neck_r=0.07, head_len=0.24, head_w=0.055, head_h=0.055, head_down=15,
                              muzzle=0.8, muzzle_w=0.55, ears="small", ear_size=0.05, eyes=0.06,
                              tail=0.55, tail_kind="thin", tail_r=0.03, tail_up=1.0)),
    "wallaby": (macropod, dict(H=0.72, L=0.55, cw=0.15, legR=0.03, head_len=0.22, tail=0.6)),
    "gorilla": (primate, dict(H=1.25, L=0.78, cw=0.34, cd=0.32, arm=1.4, legR=0.09, head_r=0.16, muzzle=0.35, crest=0.55, brow=0.6,
                              trap=0.55, head_up=-0.05, pot=0.15)),
    "monkey": (primate, dict(H=0.32, L=0.3, cw=0.07, cd=0.07, arm=1.0, legR=0.02, head_r=0.055, muzzle=0.2, tail=0.42,
                             tail_up=0.2, ears="round", knuckle=False)),
    "lemur": (primate, dict(H=0.36, L=0.38, cw=0.08, cd=0.08, arm=0.9, legR=0.022, head_r=0.05, muzzle=0.9, tail=0.6,
                            tail_up=1.0, ears="round", knuckle=False)),
    "ostrich": (bird, dict(H=2.3, body=1.05, neck=0.95, beak=0.12, leg_h=1.05, wing=1.0, tail=0.5)),
    "flamingo": (bird, dict(H=1.3, body=0.5, neck=0.62, beak=0.12, leg_h=0.78, beak_down=0.9, neck_s=True, tail=0.3)),
    "pelican": (bird, dict(H=1.2, body=0.95, neck=0.35, beak=0.4, leg_h=0.32, pouch=0.12, tail=0.35)),
    "penguin": (upright, dict(H=0.62, R=0.15, beak=0.065, flippers=True)),
    "meerkat": (upright, dict(H=0.32, R=0.055, snout=0.035, flippers=False, tail=0.22, ears=True)),
}

COATS = {
    "lion": dict(base=0xc49a5e, belly=0xe8d4ac, parts={"mane": 0x7a5530, "tuft": 0x2a1e14, "nose": 0x6e3a30, "paw": 0xb08a58},
                 face=0xe6d6b4, fur=0.07),
    "tiger": dict(base=0xd97a26, belly=0xf2ead8, parts={"nose": 0xc07a70, "ear": 0x2a2018, "paw": 0xe8d8c0}, pattern="tiger", fur=0.06),
    "giraffe": dict(base=0x9a5a24, belly=0xe8d6b0, parts={"horn": 0x6a4a2c, "horn_tip": 0x1e1812, "tuft": 0x1e1812, "hoof": 0x2a2420,
                    "muzzle": 0xd8c6a0, "nose": 0x4a3a2c, "ear": 0xd8c6a0}, pattern="giraffe", fur=0.05, dorsal=0.05),
    "zebra": dict(base=0xf0ece4, parts={"hoof": 0x222222, "muzzle": 0x1c1a18, "nose": 0x1c1a18, "tuft": 0x161414}, pattern="zebra", fur=0.04, dorsal=0.0),
    "okapi": dict(base=0x3a2218, belly=0x4a3020, parts={"hoof": 0x1e1812, "ear": 0x3a2218, "tuft": 0x1e1812, "nose": 0x1e1812},
                  pattern="okapi", fur=0.05),
    "warthog": dict(base=0x6a5a4c, belly=0x8a7a6a, parts={"mane": 0x3a2e24, "tusk": 0xf0e8d4, "hoof": 0x2a2420, "nose": 0x3a3028,
                    "tuft": 0x2a2018}, fur=0.12),
    "hippo": dict(base=0x5a4850, belly=0xb08080, parts={"nose": 0x6a5258, "paw": 0x4a3a40}, face=0xa07878, fur=0.05, dorsal=0.08),
    "camel": dict(base=0xa8814f, belly=0xc8a476, parts={"hump": 0x9a7244, "foot": 0x6a5a48, "tuft": 0x5a4024, "nose": 0x6a5440}, fur=0.09),
    "alpaca": dict(base=0xe6d8be, belly=0xf0e6d2, parts={"muzzle": 0xd8c8aa, "nose": 0x3a3028, "foot": 0x4a4038}, fur=0.12, dorsal=0.0),
    "deer": dict(base=0xa07a50, belly=0xe2d2b6, parts={"nose": 0x1e1812, "tusk": 0xf0e8d4, "hoof": 0x2a2420, "ear": 0xb89068},
                 face=0xc8a882, fur=0.07),
    "goat": dict(base=0x5e544c, belly=0x8a8078, parts={"horn": 0x8a7a66, "beard": 0x2a2420, "hoof": 0x2a2420, "nose": 0x2a2420},
                 stockings=0x2a2420, fur=0.12),
    "pig": dict(base=0xc89a62, belly=0xe0c090, parts={"nose": 0xd8a090, "hoof": 0x4a3a30}, fur=0.14, dorsal=0.05),
    "otter": dict(base=0x4a3626, belly=0x9a8a72, parts={"nose": 0x1e1812, "paw": 0x2a2018}, face=0xb0a088, fur=0.06),
    "coati": dict(base=0x8a6440, belly=0xc8a882, parts={"nose": 0x1e1812, "paw": 0x2a2018}, face=0xd8c8b0, mask=0x2a2018,
                  pattern="rings", ring=0.07, ring_col=0x3a2818, fur=0.08),
    "wallaby": dict(base=0x8e7a66, belly=0xd0c0aa, parts={"nose": 0x1e1812, "ear": 0x6a5a4a, "hand": 0x3a3028, "foot": 0x6a5a4a},
                    fur=0.08),
    "gorilla": dict(base=0x262422, belly=0x1e1c1a, parts={"hand": 0x161412, "muzzle": 0x141210, "nose": 0x141210}, pattern="silverback",
                    fur=0.1, dorsal=0.0),
    "monkey": dict(base=0x8a8a6a, belly=0xe0c890, parts={"hand": 0xd8a040, "leg": 0xc89a40, "nose": 0x2a2018, "tail": 0x6a6a52},
                   face=0xf0e8d8, mask=0x1e1a16, fur=0.08),
    "lemur": dict(base=0x9a9894, belly=0xeae6de, parts={"nose": 0x161616, "hand": 0x2a2826}, face=0xf2f0ea, mask=0x161616,
                  pattern="rings", ring=0.075, ring_col=0x161616, fur=0.06),
    "ostrich": dict(base=0x1e1c1a, parts={"neck": 0xb8a8a0, "head": 0xb8a8a0, "leg_low": 0xd8a8a0, "foot": 0xb89890, "leg": 0xd8a8a0,
                    "beak": 0xd8c8a8, "tail": 0xf2f0ea}, fur=0.08, dorsal=0.0),
    "flamingo": dict(base=0xf3a0ae, parts={"neck": 0xf6b0bc, "wing": 0xee8898, "leg_low": 0xe8808e, "foot": 0xe8808e, "leg": 0xf3a0ae,
                     "beak": 0x1c1a1a, "tail": 0xe07888}, fur=0.05, dorsal=0.0),
    "pelican": dict(base=0xf2f0ea, parts={"beak": 0xe8c060, "pouch": 0xf0a050, "leg_low": 0x8a8a8a, "foot": 0x8a8a8a, "wing": 0xe8e4dc,
                    "tail": 0x2a2826}, fur=0.04, dorsal=0.0),
    "penguin": dict(base=0x161616, parts={"beak": 0x1a1a1a, "foot": 0x3a3232}, pattern="penguin", fur=0.03, dorsal=0.0),
    "meerkat": dict(base=0xb39470, belly=0xdcc6a2, parts={"ear": 0x2a2018, "nose": 0x1e1812, "hand": 0x6a5440}, mask=0x2a2018, fur=0.08),
}

TARGET_TRIS = {"giraffe": 16000, "zebra": 16000, "tiger": 14000, "okapi": 14000, "lion": 16000}


def build(sid):
    plan, params = SPECIES[sid]
    B = Body(seed=zlib.crc32(sid.encode()))
    info = plan(B, **params)
    span = max(info["H"], info["L"] + 0.6)
    res = max(0.004, span / 170)
    # Metaballs -> mesh (each species gets its own family name, so they don't fuse together).
    mb = bpy.data.metaballs.new(f"mb_{sid}")
    mb.resolution = mb.render_resolution = res
    mb.threshold = 0.6
    for e in B.els:
        el = mb.elements.new(type=e["kind"])
        el.co = e["co"]
        el.rotation = e["q"]
        el.stiffness = 2.0
        el.use_negative = e.get("neg", False)
        if e["kind"] == "ELLIPSOID":
            el.radius = K
            el.size_x, el.size_y, el.size_z = (max(a, res * 0.7) for a in e["axes"])
        else:
            el.radius = K * e["r"]
            el.size_x = e["half"]
    obj = bpy.data.objects.new(f"mb_{sid}", mb)
    bpy.context.scene.collection.objects.link(obj)
    me = bpy.data.meshes.new_from_object(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(obj)
    bpy.data.metaballs.remove(mb)
    # Smooth out the polygoniser's grain, then decimate to a game-friendly size.
    body = bpy.data.objects.new(sid, me)
    bpy.context.scene.collection.objects.link(body)
    sm = body.modifiers.new("Smooth", "SMOOTH")
    sm.factor, sm.iterations = 0.6, 4
    target = TARGET_TRIS.get(sid, 10000)
    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    if tris > target:
        dec = body.modifiers.new("Decimate", "DECIMATE")
        dec.ratio = target / tris
    final = bpy.data.meshes.new_from_object(body.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(body)
    bpy.data.meshes.remove(me)
    # Eyes: glossy spheres in their sockets.
    bm = bmesh.new()
    bm.from_mesh(final)
    n_body = len(bm.verts)
    for c, r in B.eyes:
        bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=r, matrix=Matrix.Translation(c))
    bm.to_mesh(final)
    bm.free()
    for p in final.polygons:
        p.use_smooth = True
    final.update()
    # Paint the coat.
    P = np.array([v.co[:] for v in final.vertices])
    Nm = np.array([v.normal[:] for v in final.vertices])
    tags = [e["tag"] for e in B.els]
    F = B.fields(P)
    T = np.array(tags, dtype=object)[np.argmax(F, axis=1)]
    T[n_body:] = "eye"
    eyes = np.array([e[0][:] for e in B.eyes]) if B.eyes else np.zeros((1, 3))
    info.update(eyes=eyes, eye_r=B.eyes[0][1] if B.eyes else 0.01)
    if any(t == "tail" for t in tags):
        ti = tags.index("tail")
        e = B.els[ti]
        info["tail0"] = np.array(e["co"] - (e["q"] @ X) * e.get("half", 0))
    if sid == "penguin":
        hi = tags.index("head")
        info["head_c"] = np.array(B.els[hi]["co"])
        info["head_r"] = B.els[hi]["axes"][0]
    C = paint(sid, P, Nm, T, info)
    col = final.color_attributes.new("Col", "BYTE_COLOR", "POINT")
    col.data.foreach_set("color", np.hstack([C, np.ones((len(C), 1))]).astype(np.float32).ravel())
    final.color_attributes.active_color = col
    mat = bpy.data.materials.get("animal") or bpy.data.materials.new("animal")
    final.materials.append(mat)
    out = bpy.data.objects.new(sid, final)
    bpy.context.scene.collection.objects.link(out)
    for o in bpy.context.scene.objects:
        o.select_set(o == out)
    bpy.context.view_layer.objects.active = out
    path = os.path.join(OUT, sid + ".glb")
    kw = dict(filepath=path, export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
              export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=7)
    try:
        bpy.ops.export_scene.gltf(**kw, export_vertex_color="ACTIVE")
    except TypeError:
        bpy.ops.export_scene.gltf(**kw, export_colors=True)
    tris = sum(len(p.vertices) - 2 for p in final.polygons)
    log(f"{sid}: {len(B.els)} masses, res {res * 100:.1f} cm, {len(final.vertices)} verts, ~{tris} tris -> {os.path.getsize(path) // 1024} KB")
    bpy.data.objects.remove(out)
    # Legs in three.js axes (x forward, y up, z = -Blender y).
    return {"legs": [[round(x, 3), round(z, 3), round(-y, 3)] for x, y, z in B.legs], "height": round(info["H"], 3), "legR": round(B.legR, 3)}


def main():
    only = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    bpy.ops.wm.read_factory_settings(use_empty=True)
    os.makedirs(OUT, exist_ok=True)
    index_path = os.path.join(OUT, "animals.json")
    index = json.load(open(index_path)) if os.path.exists(index_path) else {}
    for sid in SPECIES:
        if only and sid not in only:
            continue
        index[sid] = build(sid)
    json.dump(index, open(index_path, "w"), indent=1)
    log("done")


if __name__ == "__main__":  # importable (the bronze gorilla statue in tools/landmarks reuses the gorilla)
    try:
        main()
    except Exception:
        import traceback
        log(traceback.format_exc())
        log("failed")
