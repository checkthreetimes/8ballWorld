"""Procedural creature-art generator for The World of 8Ball — v2 'pixelmon'.

Part-based pixel creatures in the classic handheld-monster style: a body and
head composed from ellipses, symmetric ears/horns/wings, leg stubs, belly
patch, eyes with pupils, black outline, 3-tone directional shading, a ground
shadow, element-tinted arena backdrop, name banner and rarity border.
Deterministic per name — re-running reproduces the set.

Usage:  BOT_TOKEN=x DB_PATH=/tmp/x.db python3 gen_art.py
"""
import hashlib
import os
import random
import re
import sys

from PIL import Image, ImageDraw, ImageFont

ART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "art")

# element: (bg_top, bg_bottom, base_hue)
ELEMENTS = {
    "fire":      ((52, 22, 14),  (18, 7, 4),   (226, 88, 44)),
    "water":     ((14, 30, 56),  (5, 10, 22),  (66, 132, 214)),
    "earth":     ((36, 30, 16),  (13, 10, 6),  (156, 116, 66)),
    "lightning": ((44, 40, 12),  (16, 14, 4),  (238, 204, 62)),
    "shadow":    ((30, 16, 44),  (10, 5, 16),  (138, 92, 190)),
    "nature":    ((16, 38, 18),  (6, 13, 7),   (88, 178, 96)),
    "ice":       ((18, 36, 46),  (6, 12, 16),  (128, 200, 226)),
    "holy":      ((48, 42, 24),  (17, 15, 8),  (238, 214, 138)),
    "light":     ((48, 42, 24),  (17, 15, 8),  (238, 214, 138)),
    "void":      ((20, 10, 34),  (6, 3, 11),   (104, 62, 160)),
    "wind":      ((22, 38, 34),  (8, 13, 11),  (146, 208, 186)),
    "neutral":   ((30, 30, 36),  (10, 10, 13), (164, 160, 176)),
}

RARITY_BORDERS = {
    "common":    (110, 110, 120),
    "uncommon":  (80, 200, 100),
    "rare":      (80, 140, 240),
    "epic":      (180, 90, 230),
    "legendary": (250, 190, 60),
    "mythic":    (250, 80, 90),
}

G = 28  # creature grid resolution (pixels)


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def _clamp(v):
    return max(0, min(255, int(v)))


def _tone(c, f):
    return tuple(_clamp(v * f) for v in c)


def _ellipse_cells(cx, cy, rx, ry):
    cells = set()
    for y in range(int(cy - ry), int(cy + ry) + 1):
        for x in range(int(cx - rx), int(cx + rx) + 1):
            if 0 <= x < G and 0 <= y < G:
                if ((x - cx) / max(0.6, rx)) ** 2 + ((y - cy) / max(0.6, ry)) ** 2 <= 1.0:
                    cells.add((x, y))
    return cells


def build_creature(rng):
    """Compose a creature mask on the GxG grid. Returns (body_cells, belly_cells,
    eye_pixels, head_box). Mirror-symmetric around the center column."""
    cx = G / 2 - 0.5
    body = set()
    belly = set()

    archetype = rng.choice(["biped", "quad", "blob", "serpent", "winged"])

    if archetype == "serpent":
        # stacked coils narrowing upward, head on top
        y = G - 7
        r = rng.uniform(4.5, 6.0)
        while y > 9 and r > 2.2:
            body |= _ellipse_cells(cx, y, r, 2.6)
            y -= 3
            r -= rng.uniform(0.5, 0.9)
        head_cy = y
        head_r = max(3.2, r + 1.4)
        body |= _ellipse_cells(cx, head_cy, head_r, head_r * 0.85)
        head_box = (cx, head_cy, head_r, head_r * 0.85)
        belly |= _ellipse_cells(cx, G - 7, 2.6, 1.6)
    else:
        bw = rng.uniform(5.5, 8.0)   # body radii
        bh = rng.uniform(4.5, 6.5)
        bcy = G - 6 - bh * 0.55
        body |= _ellipse_cells(cx, bcy, bw, bh)
        hw = rng.uniform(4.0, 6.2)   # head radii
        hh = rng.uniform(3.6, 5.4)
        if archetype == "blob":
            hcy = bcy - bh * 0.35
            hw = bw * 0.95
        else:
            hcy = bcy - bh - hh * 0.35
        body |= _ellipse_cells(cx, hcy, hw, hh)
        head_box = (cx, hcy, hw, hh)
        # belly patch
        belly |= _ellipse_cells(cx, bcy + 0.5, bw * 0.55, bh * 0.6)
        # legs
        if archetype in ("biped", "winged"):
            leg_dx = bw * 0.45
            for sx in (-1, 1):
                body |= _ellipse_cells(cx + sx * leg_dx, G - 5, 1.7, 2.4)
        elif archetype == "quad":
            for sx in (-1, 1):
                body |= _ellipse_cells(cx + sx * bw * 0.62, G - 5, 1.6, 2.2)
                body |= _ellipse_cells(cx + sx * bw * 0.25, G - 4.6, 1.5, 2.0)
        # arms for bipeds
        if archetype == "biped" and rng.random() < 0.8:
            for sx in (-1, 1):
                body |= _ellipse_cells(cx + sx * (bw + 0.8), bcy - 0.5, 1.5, 2.6)
        # wings
        if archetype == "winged":
            for sx in (-1, 1):
                wx = cx + sx * (bw + 1.6)
                for i in range(4):
                    body |= _ellipse_cells(wx + sx * i * 0.7, bcy - 1 - i * 1.3,
                                           2.2 - i * 0.35, 1.4)

    # ears / horns on the head
    hx, hy, hrx, hry = head_box
    ear = rng.choice(["point", "round", "long", "horn", "none"])
    ear_dx = hrx * 0.62
    if ear == "point":
        for sx in (-1, 1):
            for i in range(3):
                body |= _ellipse_cells(hx + sx * ear_dx, hy - hry - i * 0.9, 1.6 - i * 0.4, 1.0)
    elif ear == "round":
        for sx in (-1, 1):
            body |= _ellipse_cells(hx + sx * ear_dx, hy - hry + 0.2, 2.0, 2.0)
    elif ear == "long":
        for sx in (-1, 1):
            for i in range(4):
                body |= _ellipse_cells(hx + sx * (ear_dx + i * 0.2), hy - hry - i * 1.0, 1.2, 1.1)
    elif ear == "horn":
        for i in range(3):
            body |= _ellipse_cells(hx, hy - hry - i * 1.0, 1.4 - i * 0.35, 1.0)

    # enforce mirror symmetry
    sym = set()
    for (x, y) in body:
        sym.add((x, y))
        sym.add((int(2 * cx - x + 0.5), y))
    body = {(x, y) for (x, y) in sym if 0 <= x < G and 0 <= y < G}
    belly &= body

    # eyes: symmetric on the head
    eye_dx = max(1.2, hrx * 0.42)
    ey = int(hy - hry * 0.15)
    ex_l, ex_r = int(hx - eye_dx), int(hx + eye_dx + 0.5)
    eyes = [(ex_l, ey), (ex_r, ey)]
    return body, belly, eyes, head_box


def make_sprite(name, element="neutral", rarity="common", size=512):
    seed = int(hashlib.md5(("v2:" + name).encode()).hexdigest(), 16)
    rng = random.Random(seed)
    bg_top, bg_bot, base = ELEMENTS.get((element or "neutral").lower(), ELEMENTS["neutral"])
    body_c   = base
    dark_c   = _tone(base, 0.62)
    light_c  = _tone(base, 1.35)
    belly_c  = tuple(_clamp(v * 0.35 + 200) for v in base)  # creamy tint
    outline  = (16, 14, 20)

    img = Image.new("RGB", (size, size))
    dr = ImageDraw.Draw(img)
    for y in range(size):
        t = y / size
        dr.line([(0, y), (size, y)],
                fill=tuple(int(a + (b - a) * t) for a, b in zip(bg_top, bg_bot)))

    # arena glow circle
    cx_px, cy_px = size // 2, int(size * 0.47)
    glow = _tone(base, 0.30)
    rr = int(size * 0.36)
    for r in range(rr, 0, -6):
        a = (rr - r) / rr * 0.45
        col = tuple(int(g * a + b * (1 - a)) for g, b in zip(glow, bg_bot))
        dr.ellipse([cx_px - r, cy_px - r, cx_px + r, cy_px + r], fill=col)

    body, belly, eyes, head_box = build_creature(rng)

    px = int(size * 0.74 / G)
    ox = (size - G * px) // 2
    oy = int(size * 0.47) - (G * px) // 2

    # ground shadow beneath the creature
    ys = [y for (_, y) in body]
    foot_y = oy + (max(ys) + 1) * px if ys else cy_px
    dr.ellipse([cx_px - int(size * 0.22), foot_y - px, cx_px + int(size * 0.22), foot_y + px],
               fill=_tone(bg_bot, 0.6))

    # directional shading: distance from the top-left of the mass
    def shade_for(x, y):
        if (x - 1, y) not in body or (x, y - 1) not in body:
            if (x + 1, y) in body and (x, y + 1) in body:
                return light_c
        if (x + 1, y) not in body or (x, y + 1) not in body:
            return dark_c
        return body_c

    for (x, y) in body:
        col = belly_c if (x, y) in belly else shade_for(x, y)
        x0, y0 = ox + x * px, oy + y * px
        dr.rectangle([x0, y0, x0 + px - 1, y0 + px - 1], fill=col)

    # black outline around the whole mass (the signature look)
    for (x, y) in body:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if (nx, ny) not in body and 0 <= nx < G and 0 <= ny < G:
                x0, y0 = ox + nx * px, oy + ny * px
                dr.rectangle([x0, y0, x0 + px - 1, y0 + px - 1], fill=outline)

    # eyes: white with dark pupil, plus a tiny mouth
    for (exx, eyy) in eyes:
        if (exx, eyy) in body:
            x0, y0 = ox + exx * px, oy + eyy * px
            dr.rectangle([x0, y0, x0 + px - 1, y0 + px - 1], fill=(250, 250, 252))
            pr = max(2, px // 3)
            dr.rectangle([x0 + px - pr - 1, y0 + px // 3, x0 + px - 2, y0 + px // 3 + pr],
                         fill=(20, 18, 26))
    hx, hy, hrx, hry = head_box
    mx, my = int(hx), int(hy + hry * 0.45)
    if (mx, my) in body:
        x0, y0 = ox + mx * px, oy + my * px
        dr.rectangle([x0 - px // 2, y0 + px // 3, x0 + px // 2, y0 + px // 2 + 2],
                     fill=_tone(outline, 1.6))

    # name banner
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
    except Exception:
        font = ImageFont.load_default()
    banner_h = 66
    dr.rectangle([0, size - banner_h, size, size], fill=(10, 10, 14))
    tw = dr.textlength(name, font=font)
    dr.text(((size - tw) / 2, size - banner_h + 14), name, font=font, fill=(235, 235, 245))

    bc = RARITY_BORDERS.get((rarity or "common").lower(), RARITY_BORDERS["common"])
    for i in range(6):
        dr.rectangle([i, i, size - 1 - i, size - 1 - i], outline=bc)
    return img


def collect_targets():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import main  # noqa
    targets = {}
    for v in main.PET_SPECIES.values():
        targets[v["name"]] = (v.get("element", "neutral"), v.get("rarity", "common"))
    for pool in main._DNG_ENEMIES.values():
        for e in pool:
            targets.setdefault(e[0], (e[3] or "neutral", "common"))
    for b in main._DNG_BOSSES:
        targets[b["name"]] = (b.get("element") or "shadow", "epic")
    for v in main.BOSSES.values():
        targets[v["name"]] = ("void", "legendary")
    for m in main.ENCOUNTER_MONSTERS:
        targets.setdefault(m[1], (m[2] or "neutral", "common"))
    for n in main.ENCOUNTER_NPCS:
        targets.setdefault(n[0], ("neutral", "uncommon"))
    return targets


if __name__ == "__main__":
    os.makedirs(ART_DIR, exist_ok=True)
    targets = collect_targets()
    made = 0
    for name, (element, rarity) in sorted(targets.items()):
        out = os.path.join(ART_DIR, slug(name) + ".png")
        make_sprite(name, element, rarity).save(out, optimize=True)
        made += 1
    print(f"generated {made} v2 sprites into {ART_DIR}")
