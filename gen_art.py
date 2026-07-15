"""Procedural creature-art generator for The World of 8Ball.

Generates one 512x512 PNG per creature/NPC/boss into ./art/ using the classic
symmetric pixel-sprite technique: a mirrored random grid seeded by the name, so
every creature gets a unique but reproducible sprite, colored by element with a
rarity border and a name banner. Re-run any time; deterministic per name.

Usage:  BOT_TOKEN=x DB_PATH=/tmp/x.db python3 gen_art.py
"""
import hashlib
import os
import random
import re
import sys

from PIL import Image, ImageDraw, ImageFont

ART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "art")

ELEMENT_PALETTES = {
    # element: (bg_top, bg_bottom, body, accent)
    "fire":      ((40, 12, 8),   (12, 4, 2),   (232, 90, 40),  (255, 190, 60)),
    "water":     ((10, 24, 48),  (3, 8, 18),   (60, 130, 220), (150, 220, 255)),
    "earth":     ((30, 24, 12),  (10, 8, 4),   (150, 110, 60), (210, 180, 120)),
    "lightning": ((36, 32, 8),   (12, 10, 2),  (240, 210, 60), (255, 255, 170)),
    "shadow":    ((24, 12, 36),  (8, 4, 12),   (130, 80, 190), (200, 160, 255)),
    "nature":    ((12, 32, 14),  (4, 10, 5),   (80, 180, 90),  (170, 240, 150)),
    "ice":       ((14, 30, 40),  (4, 10, 14),  (120, 200, 230), (220, 250, 255)),
    "holy":      ((40, 36, 20),  (14, 12, 6),  (240, 220, 140), (255, 250, 220)),
    "light":     ((40, 36, 20),  (14, 12, 6),  (240, 220, 140), (255, 250, 220)),
    "void":      ((16, 8, 28),   (4, 2, 8),    (90, 50, 150),  (180, 120, 255)),
    "wind":      ((20, 32, 30),  (6, 10, 9),   (140, 210, 190), (220, 255, 240)),
    "neutral":   ((26, 26, 30),  (8, 8, 10),   (160, 160, 175), (225, 225, 235)),
}

RARITY_BORDERS = {
    "common":    (110, 110, 120),
    "uncommon":  (80, 200, 100),
    "rare":      (80, 140, 240),
    "epic":      (180, 90, 230),
    "legendary": (250, 190, 60),
    "mythic":    (250, 80, 90),
}


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def _shade(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def make_sprite(name, element="neutral", rarity="common", size=512):
    seed = int(hashlib.md5(name.encode()).hexdigest(), 16)
    rng = random.Random(seed)
    pal = ELEMENT_PALETTES.get((element or "neutral").lower(), ELEMENT_PALETTES["neutral"])
    bg_top, bg_bot, body, accent = pal

    img = Image.new("RGB", (size, size))
    dr = ImageDraw.Draw(img)
    # vertical gradient background
    for y in range(size):
        t = y / size
        dr.line([(0, y), (size, y)],
                fill=tuple(int(a + (b - a) * t) for a, b in zip(bg_top, bg_bot)))
    # faint radial glow behind the sprite
    glow = _shade(body, 0.35)
    cx, cy, rr = size // 2, int(size * 0.44), int(size * 0.34)
    for r in range(rr, 0, -6):
        a = (rr - r) / rr * 0.5
        col = tuple(int(g * a + bgc * (1 - a)) for g, bgc in zip(glow, bg_bot))
        dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)

    # symmetric pixel sprite: 7 random columns mirrored -> 13 wide, 13 tall
    W, H = 13, 13
    grid = [[0] * W for _ in range(H)]
    for y in range(1, H - 1):
        for x in range(W // 2 + 1):
            v = 0
            # bias towards a connected blob in the middle
            dx = abs(x - W // 2) / (W // 2)
            dy = abs(y - H // 2) / (H // 2)
            p_fill = 0.75 - 0.45 * (dx * 0.7 + dy * 0.6)
            if rng.random() < p_fill:
                v = 1 if rng.random() > 0.22 else 2  # 2 = accent pixel
            grid[y][x] = v
            grid[y][W - 1 - x] = v
    # eyes: two bright symmetric pixels in the upper-middle
    ey = 3 + rng.randint(0, 2)
    ex = 2 + rng.randint(0, 2)
    grid[ey][ex] = 3
    grid[ey][W - 1 - ex] = 3

    px = int(size * 0.62 / W)               # sprite pixel size
    ox = (size - W * px) // 2               # centered
    oy = int(size * 0.44) - (H * px) // 2
    dark = _shade(body, 0.55)
    for y in range(H):
        for x in range(W):
            v = grid[y][x]
            if not v:
                continue
            x0, y0 = ox + x * px, oy + y * px
            col = body if v == 1 else (accent if v == 2 else (255, 255, 255))
            # simple bevel: darker right/bottom edge
            dr.rectangle([x0, y0, x0 + px - 1, y0 + px - 1], fill=col)
            dr.line([(x0, y0 + px - 1), (x0 + px - 1, y0 + px - 1)], fill=dark)
            dr.line([(x0 + px - 1, y0), (x0 + px - 1, y0 + px - 1)], fill=dark)

    # name banner
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
    except Exception:
        font = ImageFont.load_default()
    banner_h = 66
    dr.rectangle([0, size - banner_h, size, size], fill=(10, 10, 14))
    tw = dr.textlength(name, font=font)
    dr.text(((size - tw) / 2, size - banner_h + 14), name,
            font=font, fill=(235, 235, 245))

    # rarity border
    bc = RARITY_BORDERS.get((rarity or "common").lower(), RARITY_BORDERS["common"])
    for i in range(6):
        dr.rectangle([i, i, size - 1 - i, size - 1 - i], outline=bc)
    return img


def collect_targets():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import main  # noqa: game tables
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
    print(f"generated {made} sprites into {ART_DIR}")
